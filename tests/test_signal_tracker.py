from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_signal_tracker as tracker
from core import atomic_json


def fake_enrich(frame):
    x = frame.copy().reset_index(drop=True)
    x["ma5"] = 9.0
    x["ma10"] = 8.8
    x["vol5_prev"] = 100.0
    x["rsi14"] = 55.0
    x["atr14"] = 0.2
    x["past20_high"] = 10.1
    # One valid signal at index 64. The prior MA5 is lower.
    x.loc[63, "ma5"] = 8.9
    x.loc[64, "close"] = 10.0
    x.loc[64, "ma5"] = 9.8
    x.loc[64, "ma10"] = 9.6
    x.loc[64, "volume"] = 130.0
    x.loc[64, "rsi14"] = 55.0
    x.loc[64, "atr14"] = 0.2
    x.loc[64, "past20_high"] = 10.1
    return x


def synthetic_bars(n=68):
    dates = pd.bdate_range("2026-01-05", periods=n)
    return [
        {"date": str(d.date()), "open": 10.0, "high": 10.5,
         "low": 9.5, "close": 10.0, "volume": 100}
        for d in dates
    ]


def test_signal_outcomes_obey_t_plus_one(monkeypatch):
    monkeypatch.setattr(tracker, "enrich", fake_enrich)
    bars = synthetic_bars()
    bars[65]["open"] = 10.0  # next-session entry is inside the 9.95–10.05 zone
    bars[66]["close"] = 10.3  # first legal exit: session after the entry date
    bars[67]["close"] = 10.4

    events = tracker.signal_events("000001", "测试股票", bars)
    assert len(events) == 1
    event = events[0]
    assert event["entry_status"] == "ENTERED"
    assert event["entry_date"] == bars[65]["date"]
    assert event["outcomes"]["1"]["status"] == "COMPLETE"
    assert event["outcomes"]["1"]["exit_date"] == bars[66]["date"]
    assert event["outcomes"]["2"]["exit_date"] == bars[67]["date"]
    assert event["outcomes"]["3"]["status"] == "PENDING"


def test_signal_is_skipped_when_next_open_chases(monkeypatch):
    monkeypatch.setattr(tracker, "enrich", fake_enrich)
    bars = synthetic_bars()
    bars[65]["open"] = 10.2
    events = tracker.signal_events("000001", "测试股票", bars)
    assert len(events) == 1
    assert events[0]["entry_status"] == "SKIPPED_NO_CHASE"
    assert events[0]["outcomes"]["1"]["status"] == "SKIPPED"


def test_horizon_metrics_report_losses_and_drawdown():
    events = [
        {"entry_status": "ENTERED", "signal_date": "2026-01-01", "code": "000001",
         "outcomes": {"1": {"status": "COMPLETE", "return_pct": 2.0, "pnl_yuan": 20.0}}},
        {"entry_status": "ENTERED", "signal_date": "2026-01-02", "code": "000002",
         "outcomes": {"1": {"status": "COMPLETE", "return_pct": -1.0, "pnl_yuan": -10.0}}},
        {"entry_status": "ENTERED", "signal_date": "2026-01-03", "code": "000003",
         "outcomes": {"1": {"status": "COMPLETE", "return_pct": -0.5, "pnl_yuan": -5.0}}},
    ]
    result = tracker.summarize_horizon(events, 1)
    assert result["completed_count"] == 3
    assert result["win_rate_pct"] == 33.33
    assert result["average_profit_yuan"] == 20.0
    assert result["average_loss_yuan"] == -7.5
    assert result["max_consecutive_losses"] == 2
    assert result["event_sequence_max_drawdown_pct"] == -1.5


def test_tracker_builds_from_current_screen_and_histories(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "enrich", fake_enrich)
    root = tmp_path / "data"
    atomic_json(root / "screen.json", {
        "asof": "2026-04-08", "eligible_count": 1, "covered_count": 1,
        "coverage_pct": 100.0,
        "rows": [{"code": "000001", "name": "测试股票"}],
    })
    atomic_json(root / "stocks.json", {"stocks": {"000001": {"name": "测试股票"}}})
    bars = synthetic_bars()
    bars[-1]["date"] = "2026-04-08"
    atomic_json(root / "history" / "000001.json", {
        "asof": "2026-04-08", "bars": bars,
    })
    result = tracker.build_tracker(root, lookback_sessions=180)
    assert result["status"] == "ready"
    assert result["universe"]["stocks_with_current_history"] == 1
    assert result["signal_count"] == 1
    assert set(result["metrics"]) == {"1", "2", "3"}
