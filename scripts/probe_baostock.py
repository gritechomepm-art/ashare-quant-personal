"""BaoStock availability/quality probe. Research only; never publishes trading signals.
Uses the most recently completed China trading day; checks calendar, stock universe,
and two test symbols with unadjusted history. No credentials or account access.
"""
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import baostock as bs

CST = ZoneInfo("Asia/Shanghai")
SAMPLES = {"sz.000708": "中信特钢", "sz.002600": "领益智造"}


def checked_frame(rs, label):
    if rs.error_code != "0":
        raise RuntimeError(f"{label}: BaoStock error {rs.error_code} - {rs.error_msg}")
    df = rs.get_data()
    if df is None:
        raise RuntimeError(f"{label}: returned None")
    return df


def probe(client=bs, clock=None):
    now = clock or datetime.now(CST)
    end = now.date() if (now.hour, now.minute) >= (17, 30) else now.date() - timedelta(days=1)
    start = end - timedelta(days=18)
    login = client.login()
    if login.error_code != "0":
        raise RuntimeError("BaoStock login failed: " + str(login.error_msg))
    try:
        calendar = checked_frame(client.query_trade_dates(
            start_date=start.isoformat(), end_date=end.isoformat()), "trade calendar")
        if not {"calendar_date", "is_trading_day"}.issubset(calendar.columns):
            raise ValueError("Trade calendar missing required columns")
        trading = calendar.loc[calendar.is_trading_day == "1", "calendar_date"].tolist()
        if not trading:
            raise ValueError("No recent completed trading days")
        asof = max(trading)
        universe = checked_frame(client.query_all_stock(day=asof), "stock universe")
        if not {"code", "code_name"}.issubset(universe.columns):
            raise ValueError("Universe missing code and code_name")
        codes = set(universe.code.astype(str))
        a_share = [code for code in codes
                   if (code.startswith(("sh.6", "sz.0", "sz.3", "bj.4", "bj.8"))
                       and len(code) == 9)]
        if len(a_share) < 1200:
            raise ValueError(f"Incomplete A-share universe: {len(a_share)} valid codes")
        detail = {}
        for code, label in SAMPLES.items():
            if code not in codes:
                raise ValueError(f"{label} {code} missing from stock list")
            bars = checked_frame(client.query_history_k_data_plus(
                code,
                "date,code,open,high,low,close,volume,amount,tradestatus,isST",
                start_date=(end - timedelta(days=200)).isoformat(),
                end_date=asof,
                frequency="d", adjustflag="3"), f"{label} daily bars")
            required = {"date", "open", "high", "low", "close", "volume", "tradestatus"}
            if not required.issubset(bars.columns):
                raise ValueError(f"{label}: missing daily columns")
            if len(bars) < 65:
                raise ValueError(f"{label}: only {len(bars)} historical bars (<65)")
            latest = bars.iloc[-1]
            if not latest["date"] or float(latest["close"]) <= 0:
                raise ValueError(f"{label}: bad latest history")
            detail[code[3:]] = {
                "name": label,
                "bars": len(bars),
                "history_last_date": str(latest["date"]),
                "last_close": float(latest["close"]),
                "latest_tradestatus": str(latest["tradestatus"]),
            }
        return {
            "status": "probe_pass",
            "source": "BaoStock 0.9.4",
            "asof_trade_day": asof,
            "universe_count": len(a_share),
            "sample_history": detail,
            "note": "Only a two-stock availability probe. Not full-market daily screening.",
            "checked_at": now.isoformat(),
        }
    finally:
        client.logout()


if __name__ == "__main__":
    result = probe()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## BaoStock data source probe\\n")
            f.write(f"- Source: {result['source']}\\n")
            f.write(f"- Completed trade date: {result['asof_trade_day']}\\n")
            f.write(f"- A-share universe: {result['universe_count']}\\n")
            for code, data in result["sample_history"].items():
                f.write(f"- {code}: {data['bars']} bars; latest {data['history_last_date']}\\n")
            f.write("**Not a production screening result.**\\n")
