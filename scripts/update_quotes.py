"""Fetch a broad A-share snapshot in batches from Tencent's public quote endpoint.
Unofficial provider; failed chunks are reported and incomplete snapshots are rejected.
"""
import argparse
import json
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


def load_codes():
    master_path = ROOT / "data" / "stocks.json"
    if master_path.exists():
        master = json.loads(master_path.read_text(encoding="utf-8"))
        stocks = master.get("stocks", {})
        codes = sorted(code for code in stocks if re.fullmatch(r"\d{6}", code))
        if len(codes) >= 1200:
            return codes, "BaoStock full A-share stock master"
    fallback_path = ROOT / "data" / "watchlist_public.json"
    if fallback_path.exists():
        codes = json.loads(fallback_path.read_text(encoding="utf-8"))
        return list(dict.fromkeys(str(x).strip() for x in codes)), "temporary two-stock fallback"
    raise RuntimeError("No public A-share stock master is available")


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
    minimum = 2 if len(codes) <= 2 else max(1200, int(len(codes) * 0.25))
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
    if in_session and fresh_count < max(100, int(len(codes) * 0.20)):
        raise RuntimeError(
            f"Stale Tencent snapshot during market session: only "
            f"{fresh_count}/{len(codes)} ({fresh_pct}%) quotes are <=15 minutes old"
        )
    times = [q["quote_time"] for q in quotes.values() if q.get("quote_time")]
    return {
        "schema": 1, "status": "ok",
        "source": "腾讯财经 qt.gtimg.cn（非官方公开行情接口）",
        "scope": "全市场A股快照" if len(codes) > 2 else "测试股票快照",
        "universe_source": universe_source,
        "fetched_at": now.isoformat(timespec="seconds"),
        "quote_time_latest": max(times) if times else None,
        "market_timezone": "Asia/Shanghai",
        "count": count, "requested_count": len(codes),
        "coverage_pct": coverage, "fresh_quote_count": fresh_count,
        "fresh_quote_pct": fresh_pct, "failed_chunk_count": len(failed_chunks),
        "failed_chunks": failed_chunks[:10], "quotes": quotes,
        "warning": "腾讯公开行情接口为非官方快照，可能延迟、限流或变更；未返回的股票不代表停牌或无交易。",
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
