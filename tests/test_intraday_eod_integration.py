"""Integration test: intraday ledger merges into the EOD event study, not the portfolio."""
from pathlib import Path
import sys
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_signal_tracker import build_tracker
from core import atomic_json


def test_intraday_event_merges_and_stays_out_of_portfolio(tmp_path):
    root = tmp_path / "data"
    dates = pd.bdate_range("2026-06-01", periods=68)
    bars = [{"date": str(day.date()), "open": 10.0, "high": 10.5,
             "low": 9.5, "close": 10.0 + (index - 64)*0.1 if index >= 64 else 10.0,
             "volume": 1000} for index, day in enumerate(dates)]
    day = bars[64]["date"]
    atomic_json(root / "screen.json", {
        "asof": bars[-1]["date"], "eligible_count": 1,
        "covered_count": 1, "coverage_pct": 100.0, "rows": []
    })
    atomic_json(root / "stocks.json", {"stocks": {}})
    atomic_json(root / "history" / "000001.json", {
        "asof": bars[-1]["date"], "bars": bars,
    })
    atomic_json(root / "intraday_signal_events.json", {
        "schema": 1, "events": [{
            "id": "INTRADAY_WARNING|000001|" + day,
            "signal_date": day, "signal_time": day + "T10:00:00+08:00",
            "code": "000001", "name": "测试股票",
            "reference_price": 10.0, "signal_type": "INTRADAY_WARNING"
        }]
    })
    result = build_tracker(root)
    assert result["signal_count"] == 1
    event = result["events"][0]
    assert event["signal_type"] == "INTRADAY_WARNING"
    assert event["entry_status"] == "RECORDED_INTRADAY"
    assert event["forward_outcomes"]["1"]["observation_date"] == bars[65]["date"]
    assert event["forward_outcomes"]["1"]["return_pct"] == 1.0
    assert event["forward_outcomes"]["3"]["observation_date"] == bars[67]["date"]
    assert result["forward_metrics"]["INTRADAY_WARNING"]["1"]["completed_count"] == 1
    assert result["forward_metrics"]["CLOSE_CONFIRM"]["1"]["completed_count"] == 0
    assert result["portfolio"]["1"]["closed_trades"] == 0
