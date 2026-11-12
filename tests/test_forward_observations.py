"""Regression checks for V1.9 forward event-study accounting."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_signal_tracker import forward_observations, summarize_forward


def bars():
    return [
        {"date": "2026-11-12", "close": 10.0},
        {"date": "2026-11-13", "close": 10.5},
        {"date": "2026-11-16", "close": 9.0},
        {"date": "2026-11-17", "close": 11.0},
    ]


def test_forward_horizon_uses_signal_date_not_hypothetical_buy_date():
    result = forward_observations(bars(), 0, 10.0)
    assert result["1"]["observation_date"] == "2026-11-13"
    assert result["1"]["return_pct"] == 5.0
    assert result["2"]["observation_date"] == "2026-11-16"
    assert result["2"]["return_pct"] == -10.0
    assert result["3"]["observation_date"] == "2026-11-17"
    assert result["3"]["return_pct"] == 10.0


def test_forward_horizon_waits_for_actual_subsequent_session():
    result = forward_observations(bars(), 2, 9.0)
    assert result["1"]["status"] == "COMPLETE"
    assert result["2"]["status"] == "PENDING"
    assert result["3"]["status"] == "PENDING"


def test_same_forward_observation_for_both_signal_classes():
    future = forward_observations(bars(), 0, 10.0)
    for signal_type in ("CLOSE_CONFIRM", "INTRADAY_WARNING"):
        events = [{
            "id": signal_type + "|000001|2026-11-12",
            "signal_type": signal_type,
            "signal_date": "2026-11-12",
            "code": "000001",
            "forward_outcomes": future,
            "entry_status": "SKIPPED_NO_CHASE" if signal_type == "CLOSE_CONFIRM" else "RECORDED_INTRADAY",
        }]
        summary = summarize_forward(events, 1)
        assert summary["completed_count"] == 1
        assert summary["win_rate_pct"] == 100.0
        assert summary["average_profit_pct"] == 5.0


def test_losing_streak_on_completed_events_only():
    events = []
    for i, value in enumerate((-1, -2, 3, -4, -5, -6)):
        events.append({"signal_date": "2026-11-%02d" % (12 + i),
                       "code": "000001",
                       "forward_outcomes": {"1": {"status": "COMPLETE", "return_pct": value}}})
    summary = summarize_forward(events, 1)
    assert summary["max_consecutive_losses"] == 3
    assert summary["completed_count"] == 6
    assert summary["win_rate_pct"] == 16.67
    assert summary["average_profit_pct"] == 3.0
    assert summary["average_loss_pct"] == -3.6


def test_no_history_means_no_fake_win_rate():
    m = summarize_forward([{
        "signal_date": "2026-11-12", "code": "000001",
        "forward_outcomes": {"1": {"status": "PENDING"}}
    }], 1)
    assert m["completed_count"] == 0
    assert m["pending_count"] == 1
    assert m["win_rate_pct"] is None
