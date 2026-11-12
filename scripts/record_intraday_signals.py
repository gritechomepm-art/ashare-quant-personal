"""Persist the first valid intraday BUY warning per stock and trading date."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")


def elapsed_fraction(now):
    minute = now.hour * 60 + now.minute
    if 570 <= minute <= 690:
        return min(1.0, max(0.0, (minute - 570) / 240))
    if 780 <= minute <= 915:
        return min(1.0, max(0.0, (minute - 780 + 120) / 240))
    return 0.0


def record(screen, quotes, existing=None, now=None):
    now = now or datetime.now(CST)
    fraction = elapsed_fraction(now)
    payload = existing or {"schema": 1, "events": []}
    events = payload.get("events", [])
    seen = {item.get("id") for item in events}
    if fraction < 0.125:
        return payload, 0
    added = 0
    for row in screen.get("rows", []):
        code = str(row.get("code", ""))
        if row.get("entry_signal") is not True or str(row.get("asof", "")) >= now.date().isoformat():
            continue
        quote = quotes.get(code, {})
        stamp = quote.get("quote_time")
        if not stamp or not quote.get("price"):
            continue
        try:
            quote_time = datetime.fromisoformat(stamp)
            if quote_time.tzinfo is None:
                quote_time = quote_time.replace(tzinfo=CST)
            age = (now - quote_time).total_seconds() / 60
        except Exception:
            continue
        if age < -5 or age > 7:
            continue
        price = float(quote["price"])
        low, high = float(row.get("buy_low") or 0), float(row.get("buy_high") or 0)
        if not low <= price <= high:
            continue
        if not (price > float(row.get("ma5") or 0) > float(row.get("ma10") or 0)):
            continue
        avg = float(row.get("avg_volume5") or 0)
        volume = float(quote.get("volume_lots") or 0) * 100
        if avg <= 0 or volume / (avg * fraction) < 1.2:
            continue
        signal_date = now.date().isoformat()
        event_id = "INTRADAY_WARNING|" + code + "|" + signal_date
        if event_id in seen:
            continue
        events.append({
            "id": event_id, "code": code,
            "name": quote.get("name") or row.get("name") or code,
            "signal_type": "INTRADAY_WARNING", "signal_label": "盘中预警",
            "signal_date": signal_date,
            "signal_time": quote_time.isoformat(timespec="seconds"),
            "reference_price": round(price, 3),
            "quote_source": quote.get("source", "Tencent qt.gtimg.cn"),
            "relative_volume": round(volume / (avg * fraction), 3),
            "entry_status": "RECORDED_INTRADAY",
        })
        seen.add(event_id)
        added += 1
    payload.update({"schema": 1, "updated_at": now.isoformat(timespec="seconds"), "events": events[-50000:]})
    return payload, added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", required=True)
    ap.add_argument("--quotes", required=True)
    ap.add_argument("--existing", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    def read(path, default):
        p = Path(path)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    result, added = record(read(args.screen, {}), read(args.quotes, {}).get("quotes", {}),
                           read(args.existing, {"schema": 1, "events": []}))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print({"intraday_events_added": added, "total": len(result.get("events", []))})


if __name__ == "__main__":
    main()
