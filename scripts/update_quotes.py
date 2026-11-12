"""Fetch a limited EOD-screened opportunity pool from Tencent's public quote endpoint.
Unofficial provider; reject missing/stale candidate data, never fetch 5,000+ symbols.
"""
import argparse
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CST = ZoneInfo("Asia/Shanghai")


def market_symbol(code):
    code = str(code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("Invalid A-share code: " + code)
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    if code.startswith(("4", "8", "92")):
        return "bj" + code
    raise ValueError("Unsupported A-share code: " + code)


def chunked(items, size=100):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def parse_tencent_response(raw, requested_codes):
    found = {}
    for market, code, body in re.findall(r'v_(sh|sz|bj)(\d{6})="([^"]*)"', raw):
        fields = body.split("~")
        if len(fields) < 35 or code not in requested_codes or fields[2] != code:
            continue
        try:
            price = float(fields[3])
            prev = float(fields[4])
            open_price = float(fields[5])
            volume = int(float(fields[6] or 0))
            change = float(fields[31])
            change_pct = float(fields[32])
            high = float(fields[33])
            low = float(fields[34])
        except (ValueError, IndexError):
            continue
        if not (price > 0 and prev > 0 and low > 0 and high >= low):
            continue
        stamp = (fields[30] or "").strip()
        quote_time = None
        if re.fullmatch(r"\d{14}", stamp):
            quote_time = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=CST).isoformat()
        found[code] = {
            "name": fields[1].strip(), "price": round(price, 3),
            "prev_close": round(prev, 3), "open": round(open_price, 3),
            "volume_lots": volume, "change": round(change, 3),
            "change_pct": round(change_pct, 3), "high": round(high, 3),
            "low": round(low, 3), "quote_time": quote_time,
            "source": "Tencent qt.gtimg.cn", "market_symbol": market + code,
        }
    return found



OPPORTUNITY_SCORE_MIN = 55
OPPORTUNITY_CAP = 120
MIN_SIGNAL_PRICE = 3.0
MAX_SIGNAL_PRICE = 100.0


def select_opportunity_codes(screen, min_score=OPPORTUNITY_SCORE_MIN, cap=OPPORTUNITY_CAP):
    """Prioritize true close buy signals, then high-score observations; never pad with random stocks.

    Selection is only over the successfully screened EOD rows, which may be
    partial. This does NOT independently discover opportunities across the A-share market.
    """
    if not isinstance(screen, dict) or screen.get("schema") != 1:
        raise ValueError("No valid public EOD screening result")
    rows = screen.get("rows")
    if not isinstance(rows, list):
        raise ValueError("EOD screening rows missing")
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", ""))
        if not re.fullmatch(r"\d{6}", code):
            continue
        try:
            close = float(row.get("close"))
            score = float(row.get("score", 0))
        except (TypeError, ValueError):
            continue
        buy_signal = row.get("entry_signal") is True
        if not (math.isfinite(close) and math.isfinite(score)):
            continue
        if not (MIN_SIGNAL_PRICE <= close <= MAX_SIGNAL_PRICE):
            continue
        if not buy_signal and score < min_score:
            continue
        candidates.append((not buy_signal, -score, code))
    candidates.sort()
    codes = []
    for _, _, code in candidates:
        if code not in codes:
            codes.append(code)
        if len(codes) >= cap:
            break
    return codes


def load_codes():
    screen_path = ROOT / "data" / "screen.json"
    if not screen_path.exists():
        raise RuntimeError("No EOD screening data; refuse unfiltered all-market fallback")
    screen = json.loads(screen_path.read_text(encoding="utf-8"))
    codes = select_opportunity_codes(screen)
    if not codes:
        raise RuntimeError("No qualified opportunity candidates in EOD screen; refuse all-market fallback")
    asof = str(screen.get("asof", ""))
    try:
        screening_day = datetime.strptime(asof, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError("Invalid EOD screen date") from exc
    days_old = (datetime.now(CST).date() - screening_day).days
    if days_old < 0 or days_old > 10:
        raise RuntimeError(f"EOD screen date out of bounds: {asof}; refusing stale opportunity pool")
    source = f"EOD screen {asof}; BUY first; observation score >= {OPPORTUNITY_SCORE_MIN}; max {OPPORTUNITY_CAP}; partial-coverage possible"
    return codes, source


def fetch_market(codes=None, batch_size=100, pause=0.12):
    if codes is None:
        codes, universe_source = load_codes()
    else:
        universe_source = "explicit test code list"
    symbols = [market_symbol(code) for code in codes]
    quotes = {}
    failed_chunks = []
    for index, batch in enumerate(chunked(list(zip(codes, symbols)), batch_size)):
        query = ",".join(symbol for _, symbol in batch)
        url = "https://qt.gtimg.cn/q=" + query
        request = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ASharePersonalResearch/1.2)",
            "Referer": "https://gu.qq.com/", "Accept": "*/*",
        })
        ok = False
        for attempt in range(2):
            try:
                with urlopen(request, timeout=15) as response:
                    if response.status != 200:
                        raise RuntimeError("HTTP " + str(response.status))
                    raw = response.read().decode("gb18030", errors="strict")
                parsed = parse_tencent_response(raw, [code for code, _ in batch])
                quotes.update(parsed)
                ok = True
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(1.0)
        if not ok:
            failed_chunks.append({"batch": index, "error": last_error[:120]})
        if pause:
            time.sleep(pause)
    count = len(quotes)
    coverage = round(count / max(1, len(codes)) * 100, 2)
    minimum = max(1, math.ceil(len(codes) * 0.70))
    if count < minimum:
        raise RuntimeError(
            f"Insufficient Tencent quote coverage: {count}/{len(codes)} "
            f"({coverage}%), minimum required {minimum}; failed chunks={len(failed_chunks)}"
        )
    now = datetime.now(CST)
    timed = []
    for quote in quotes.values():
        stamp = quote.get("quote_time")
        if not stamp:
            continue
        try:
            age_minutes = (now - datetime.fromisoformat(stamp)).total_seconds() / 60
        except ValueError:
            continue
        if -5 <= age_minutes <= 15:
            timed.append(stamp)
    fresh_count = len(timed)
    fresh_pct = round(fresh_count / max(1, len(codes)) * 100, 2)
    in_session = now.weekday() < 5 and (
        570 <= now.hour * 60 + now.minute <= 690
        or 780 <= now.hour * 60 + now.minute <= 915
    )
    # Do not replace a usable feed with a newly collected but stale response.
    # A minimum active-quote ratio avoids one fresh symbol masking a stale market snapshot.
    if in_session and fresh_count < max(1, math.ceil(len(codes) * 0.60)):
        raise RuntimeError(
            f"Stale Tencent snapshot during market session: only "
            f"{fresh_count}/{len(codes)} ({fresh_pct}%) quotes are <=15 minutes old"
        )
    times = [q["quote_time"] for q in quotes.values() if q.get("quote_time")]
    return {
        "schema": 1, "status": "ok",
        "source": "腾讯财经 qt.gtimg.cn（非官方公开行情接口）",
        "scope": "盘中机会观察池（仅覆盖已筛选股票，不是全市场）",
        "selection_policy": {"score_min": OPPORTUNITY_SCORE_MIN, "max_codes": OPPORTUNITY_CAP, "signal_priority": True},
        "candidate_count": len(codes), "candidate_codes": codes,
        "universe_source": universe_source,
        "fetched_at": now.isoformat(timespec="seconds"),
        "quote_time_latest": max(times) if times else None,
        "market_timezone": "Asia/Shanghai",
        "count": count, "requested_count": len(codes),
        "coverage_pct": coverage, "fresh_quote_count": fresh_count,
        "fresh_quote_pct": fresh_pct, "failed_chunk_count": len(failed_chunks),
        "failed_chunks": failed_chunks[:10], "quotes": quotes,
        "warning": "仅监控盘后已筛选的高分观察候选与买入信号；当前盘后筛选覆盖不完整，不能代表全市场机会。腾讯非官方行情可能延迟或限流；未入池股票不提供盘中报价。",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "data" / "quotes.json"))
    args = parser.parse_args()
    payload = fetch_market()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(output)
    print(json.dumps({
        "status": payload["status"], "source": payload["source"],
        "count": payload["count"], "requested_count": payload["requested_count"],
        "coverage_pct": payload["coverage_pct"], "fresh_quote_count": payload["fresh_quote_count"],
        "fresh_quote_pct": payload["fresh_quote_pct"], "failed_chunk_count": payload["failed_chunk_count"],
        "fetched_at": payload["fetched_at"],
    }, ensure_ascii=False))
    return payload


if __name__ == "__main__":
    main()
