"""Bounded BaoStock EOD bootstrap; publishes only real dated and explicitly partial signals."""
import argparse
import time
from datetime import timedelta
from pathlib import Path

import baostock as bs

from core import ROOT, atomic_json, load_json, now_cst, score_history
from probe_baostock import checked_frame

FIELDS = "date,code,open,high,low,close,volume,amount,tradestatus,isST"


def is_share(code):
    return len(code) == 9 and code[2] == "." and code[3:].isdigit() and code.startswith(
        ("sh.6", "sz.0", "sz.3", "bj.4", "bj.8"))


def normalize_history(frame, code, name, day):
    cols = {"date", "open", "high", "low", "close", "volume", "amount", "tradestatus"}
    if not cols.issubset(frame.columns):
        raise ValueError("BaoStock history columns missing")
    bars = {}
    amounts = {}
    for r in frame.to_dict("records"):
        if str(r["tradestatus"]) != "1":
            continue
        try:
            d = str(r["date"])
            o, h, l, c = [float(r[k]) for k in ("open", "high", "low", "close")]
            v = float(r["volume"])
            amount = float(r["amount"])
        except (TypeError, ValueError):
            continue
        if not (d <= day and 0 < l <= min(o, h, c) and h >= max(o, l, c)
                and v >= 0 and amount >= 0):
            continue
        bars[d] = {"date": d, "open": round(o, 3), "high": round(h, 3),
                   "low": round(l, 3), "close": round(c, 3), "volume": int(v)}
        amounts[d] = amount
    ordered = [bars[d] for d in sorted(bars)][-260:]
    if len(ordered) < 65 or ordered[-1]["date"] != day:
        raise ValueError("Missing 65 current trading bars for " + code)
    return {"schema": 1, "code": code, "source": "BaoStock query_history_k_data_plus",
            "adjust": "none", "name": name, "asof": day, "bars": ordered,
            "last_amount_cny": amounts[day]}


def collect(root=ROOT, max_new=80, max_seconds=700):
    root = Path(root)
    now = now_cst()
    cutoff = now.date() if (now.hour, now.minute) >= (17, 30) else now.date() - timedelta(days=1)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError("BaoStock login failed: " + str(login.error_msg))
    clock = time.monotonic()
    failures = []
    successes = 0
    try:
        cal = checked_frame(bs.query_trade_dates(
            start_date=(cutoff-timedelta(days=20)).isoformat(),
            end_date=cutoff.isoformat()), "trade calendar")
        days = cal.loc[cal.is_trading_day == "1", "calendar_date"].tolist()
        if not days:
            raise ValueError("No completed trading days")
        asof = max(days)
        universe = checked_frame(bs.query_all_stock(day=asof), "stock universe")
        if not {"code", "code_name", "tradeStatus"}.issubset(universe.columns):
            raise ValueError("Incomplete BaoStock universe columns")
        names = {str(r.code): str(r.code_name) for r in universe.itertuples(index=False)
                 if is_share(str(r.code))}
        if len(names) < 1200:
            raise ValueError(f"Invalid partial universe: {len(names)}")
        active = [(full, name) for full, name in names.items()
                  if "ST" not in name.upper() and "退" not in name]
        prioritize = {"sz.000708": 0, "sz.002600": 1}
        active.sort(key=lambda pair: (prioritize.get(pair[0], 9), pair[0]))
        path = root/"history"
        path.mkdir(parents=True, exist_ok=True)
        checked = 0
        for full, name in active:
            code = full[3:]
            cached = load_json(path/f"{code}.json", {})
            if cached.get("source") == "BaoStock query_history_k_data_plus" and cached.get("asof") == asof:
                continue
            if successes >= max_new or checked >= max_new*3 or time.monotonic()-clock > max_seconds:
                break
            checked += 1
            try:
                frame = checked_frame(bs.query_history_k_data_plus(
                    full, FIELDS, start_date=(cutoff-timedelta(days=550)).isoformat(),
                    end_date=asof, frequency="d", adjustflag="3"), f"history {full}")
                doc = normalize_history(frame, code, name, asof)
                atomic_json(path/f"{code}.json", doc)
                successes += 1
            except Exception as exc:
                failures.append([code, str(exc)[:100]])
        if successes == 0 and not any(
            (path/f"{p[3:]}.json").exists() for p in prioritize):
            raise RuntimeError("No validated BaoStock historical bars")
    finally:
        bs.logout()

    ready = 0
    ranked = []
    for full, name in active:
        code = full[3:]
        hist = load_json(root/"history"/f"{code}.json", {})
        if hist.get("source") != "BaoStock query_history_k_data_plus" or hist.get("asof") != asof:
            continue
        ready += 1
        if hist.get("last_amount_cny", 0) < 30_000_000:
            continue
        try:
            result = score_history(code, hist, {"name": name}, asof)
            if result:
                ranked.append(result)
        except Exception as exc:
            failures.append([code, "scoring: "+str(exc)[:70]])
    ranked.sort(key=lambda x: (bool(x["signal"]), x["score"], x["code"]), reverse=True)
    total = len(active)
    screen = {"schema": 1, "status": "complete" if ready == total else "partial",
              "source": "BaoStock 0.9.4 unadjusted EOD + quant_v1 research signals",
              "asof": asof, "generated_at": now_cst().isoformat(timespec="seconds"),
              "universe_count": len(names), "eligible_count": total,
              "covered_count": ready, "coverage_pct": round(100*ready/total, 2),
              "filter_note": "覆盖率分母为当前非ST非退市A股候选池；只有下载日K后才可检查成交额>=3000万元；非历史可交易成分回测",
              "total_signals": sum(bool(row["signal"]) for row in ranked),
              "rows": ranked[:200], "screened_count": len(ranked),
              "warning": "历史数据覆盖不完整；未覆盖不是无信号，严禁当作全市场筛选。"}
    atomic_json(root/"screen.json", screen)
    atomic_json(root/"baostock_status.json", {
        "status": screen["status"], "asof": asof, "universe_count": len(names),
        "candidate_count": total, "covered_count": ready,
        "new_histories": successes, "failed_count": len(failures),
        "failed_samples": failures[:12], "generated_at": screen["generated_at"]})
    print(f"BaoStock {asof}: universe={len(names)}, covered={ready}/{total}, new={successes}, errors={len(failures)}, signals={screen['total_signals']}")
    return screen


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new", type=int, default=80)
    parser.add_argument("--max-seconds", type=int, default=700)
    args = parser.parse_args()
    collect(max_new=args.max_new, max_seconds=args.max_seconds)
