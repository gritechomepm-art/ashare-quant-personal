from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quant_v1 import evaluate_entry_signal, evaluate_exit_signal, backtest_trade_signals


def rising_bars(n=100):
    close = np.array([20 + i * 0.02 + 0.12 * np.sin(i * 1.3) for i in range(n)])
    frame = pd.DataFrame({
        "date": pd.bdate_range("2026-01-05", periods=n),
        "open": close,
        "high": close + 0.08,
        "low": close - 0.08,
        "close": close,
        "volume": np.full(n, 1000.0),
    })
    frame.loc[n - 1, "volume"] = 1400
    return frame


def test_buy_watch_requires_all_entry_conditions():
    result = evaluate_entry_signal(rising_bars())
    assert result["status"] == "BUY_WATCH"
    assert result["passed_count"] == result["total_checks"] == 5
    assert result["valid_sessions"] == 1
    assert result["buy_low"] < result["close"] < result["buy_high"]
    assert result["stop_reference"] < result["close"] < result["target_reference"]


def test_buy_watch_rejects_volume_without_confirmation():
    frame = rising_bars()
    frame.loc[frame.index[-1], "volume"] = 1000
    result = evaluate_entry_signal(frame)
    assert result["status"] == "WAIT"
    assert any("成交量" in reason for reason in result["reasons"])


def test_sell_stop_and_take_profit_are_cost_based():
    frame = rising_bars()
    last_close = float(frame.close.iloc[-1])
    atr = 0.2
    stop = evaluate_exit_signal(frame, cost=last_close + 5 * atr)
    target = evaluate_exit_signal(frame, cost=last_close - 3 * atr)
    assert stop["status"] == "SELL_STOP"
    assert target["status"] == "SELL_TARGET"


def test_t_plus_one_blocks_same_session_exit():
    frame = rising_bars()
    entry_date = frame.date.iloc[-1].strftime("%Y-%m-%d")
    result = evaluate_exit_signal(frame, cost=float(frame.close.iloc[-1]), entry_date=entry_date)
    assert result["status"] == "HOLD_T1"


def test_three_trading_session_time_exit():
    frame = rising_bars()
    entry_date = frame.date.iloc[-3].strftime("%Y-%m-%d")
    result = evaluate_exit_signal(frame, cost=float(frame.close.iloc[-1]), entry_date=entry_date)
    assert result["status"] == "SELL_TIME"


def test_v13_backtest_uses_next_session_entry_and_three_day_exit():
    frame = rising_bars(105)
    frame["volume"] = 1000.0
    frame.loc[99, "volume"] = 1400.0
    frame.loc[100, "open"] = float(frame.loc[99, "close"])
    for idx in range(100, 105):
        close = float(frame.loc[99, "close"]) + 0.03 * (idx - 99)
        frame.loc[idx, ["close", "open"]] = [close, close]
        frame.loc[idx, "high"] = close + 0.08
        frame.loc[idx, "low"] = close - 0.08
    trades = backtest_trade_signals(frame, "000001", maxhold=3)
    assert len(trades) == 1
    assert trades[0]["signal_date"] == frame.loc[99, "date"].date().isoformat()
    assert trades[0]["entry_date"] == frame.loc[100, "date"].date().isoformat()
    assert trades[0]["exit_date"] == frame.loc[103, "date"].date().isoformat()
    assert trades[0]["bars_held"] == 3
