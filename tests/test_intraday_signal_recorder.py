from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.record_intraday_signals import record, elapsed_fraction

CST = ZoneInfo("Asia/Shanghai")


def fixture():
    screen = {"rows": [{
        "code": "000001", "name": "平安银行", "asof": "2026-11-11",
        "entry_signal": True, "buy_low": 9.9, "buy_high": 10.2,
        "ma5": 10.0, "ma10": 9.8, "avg_volume5": 10000,
    }]}
    quotes = {"000001": {
        "name": "平安银行", "price": 10.1, "volume_lots": 20,
        "quote_time": "2026-11-12T10:00:00+08:00",
        "source": "Tencent qt.gtimg.cn",
    }}
    return screen, quotes


def test_session_fraction_matches_full_240_minute_session():
    assert elapsed_fraction(datetime(2026, 11, 12, 10, 0, tzinfo=CST)) == 0.125
    assert elapsed_fraction(datetime(2026, 11, 12, 13, 0, tzinfo=CST)) == 0.5


def test_records_first_intraday_warning_once_per_stock_per_day():
    screen, quotes = fixture()
    now = datetime(2026, 11, 12, 10, 0, 30, tzinfo=CST)
    payload, added = record(screen, quotes, now=now)
    assert added == 1
    event = payload["events"][0]
    assert event["signal_type"] == "INTRADAY_WARNING"
    assert event["reference_price"] == 10.1
    assert event["signal_date"] == "2026-11-12"
    payload2, added2 = record(screen, quotes, payload, now=now)
    assert added2 == 0
    assert len(payload2["events"]) == 1


def test_rejects_stale_quote_and_non_triggered_price():
    screen, quotes = fixture()
    quotes["000001"]["quote_time"] = "2026-11-12T09:45:00+08:00"
    payload, added = record(screen, quotes, now=datetime(2026, 11, 12, 10, 0, tzinfo=CST))
    assert added == 0
    quotes["000001"]["quote_time"] = "2026-11-12T10:00:00+08:00"
    quotes["000001"]["price"] = 10.5
    payload, added = record(screen, quotes, now=datetime(2026, 11, 12, 10, 0, 30, tzinfo=CST))
    assert added == 0
