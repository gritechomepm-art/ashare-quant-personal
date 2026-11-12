"""Build a reproducible, T+1-aware forward-outcome ledger for daily entry signals.

This is an event study over the currently covered universe, not a portfolio backtest.
Signals are generated at the close; entries are at the next session open only when
that open remains inside the signal's no-chase zone. The first legal exit is the
following trading session close (A-share T+1).
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from core import ROOT, atomic_json, load_json, now_cst
from quant_v1 import enrich


SHARES = 100
FEE_RATE = 0.0003
STAMP_RATE = 0.0005
MIN_FEE = 5.0
SLIPPAGE = 0.001
HORIZONS = (1, 2, 3)


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def signal_events(code, name, bars, lookback_sessions=180):
    """Return every BUY_WATCH event in the trailing window and its 1/2/3-day outcomes."""
    if not isinstance(bars, list) or len(bars) < 65:
        return []
    frame = pd.DataFrame(bars)
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return []
    x = enrich(frame).reset_index(drop=True)
    close = pd.to_numeric(x["close"], errors="coerce")
    ma5 = pd.to_numeric(x["ma5"], errors="coerce")
    ma10 = pd.to_numeric(x["ma10"], errors="coerce")
    prev_ma5 = ma5.shift(1)
    vol_prev = pd.to_numeric(x["vol5_prev"], errors="coerce")
    volume = pd.to_numeric(x["volume"], errors="coerce")
    rsi = pd.to_numeric(x["rsi14"], errors="coerce")
    atr = pd.to_numeric(x["atr14"], errors="coerce")
    high20 = pd.to_numeric(x["past20_high"], errors="coerce")
    vol_ratio = volume / vol_prev.where(vol_prev > 0)
    high_ratio = close / high20.where(high20 > 0)
    atr_ratio = atr / close.where(close > 0)

    mask = (
        (close > ma5) & (ma5 > ma10) & (ma5 > prev_ma5)
        & (vol_ratio >= 1.20)
        & rsi.between(45, 68)
        & high_ratio.between(0.97, 1.02)
        & (atr_ratio > 0) & (atr_ratio <= 0.06)
    ).fillna(False)

    start = max(64, len(x) - max(1, int(lookback_sessions)))
    output = []
    for i in range(start, len(x)):
        if not bool(mask.iloc[i]):
            continue
        row = x.iloc[i]
        signal_date = str(row["date"])[:10]
        signal_close = float(row["close"])
        atr_value = float(row["atr14"])
        buy_low = signal_close - 0.25 * atr_value
        buy_high = signal_close + 0.25 * atr_value

        event = {
            "id": code + "|" + signal_date,
            "code": code,
            "name": name,
            "signal_date": signal_date,
            "signal_close": round(signal_close, 3),
            "buy_low": round(buy_low, 3),
            "buy_high": round(buy_high, 3),
            "stop_reference": round(signal_close - 1.5 * atr_value, 3),
            "target_reference": round(signal_close + 2.0 * atr_value, 3),
            "volume_ratio": round(float(vol_ratio.iloc[i]), 3),
            "entry_status": "PENDING_ENTRY",
            "entry_date": None,
            "entry_price": None,
            "outcomes": {},
        }

        entry_i = i + 1
        if entry_i >= len(x):
            event["entry_reason"] = "尚无下一交易日开盘数据"
            for horizon in HORIZONS:
                event["outcomes"][str(horizon)] = {"status": "PENDING", "reason": "等待入场"}
            output.append(event)
            continue

        entry_bar = x.iloc[entry_i]
        raw_open = float(entry_bar["open"])
        entry_date = str(entry_bar["date"])[:10]
        event["entry_date"] = entry_date
        event["next_open"] = round(raw_open, 3)
        if not (buy_low <= raw_open <= buy_high):
            event["entry_status"] = "SKIPPED_NO_CHASE"
            event["entry_reason"] = "次日开盘超出观察区间，按不追高规则放弃"
            for horizon in HORIZONS:
                event["outcomes"][str(horizon)] = {
                    "status": "SKIPPED", "reason": "次日开盘超出观察区间"
                }
            output.append(event)
            continue

        entry_price = raw_open * (1 + SLIPPAGE)
        buy_value = entry_price * SHARES
        buy_fee = max(MIN_FEE, buy_value * FEE_RATE)
        event["entry_status"] = "ENTERED"
        event["entry_price"] = round(entry_price, 3)
        event["entry_reason"] = "次日开盘位于观察区间；按100股模拟入场"

        for horizon in HORIZONS:
            # A shares are T+1: the first legal exit is the next trading
            # session after the entry date, not the entry day's close.
            exit_i = entry_i + horizon
            if exit_i >= len(x):
                event["outcomes"][str(horizon)] = {
                    "status": "PENDING", "reason": "尚未到达该持有期限的可卖收盘日"
                }
                continue
            exit_bar = x.iloc[exit_i]
            raw_exit = float(exit_bar["close"])
            exit_price = raw_exit * (1 - SLIPPAGE)
            sell_value = exit_price * SHARES
            sell_fee = max(MIN_FEE, sell_value * FEE_RATE) + sell_value * STAMP_RATE
            pnl = sell_value - buy_value - buy_fee - sell_fee
            denominator = buy_value + buy_fee
            ret = 100 * pnl / denominator if denominator > 0 else 0.0
            event["outcomes"][str(horizon)] = {
                "status": "COMPLETE",
                "exit_date": str(exit_bar["date"])[:10],
                "exit_close": round(raw_exit, 3),
                "exit_price_after_slippage": round(exit_price, 3),
                "pnl_yuan": round(pnl, 2),
                "return_pct": round(ret, 3),
            }
        output.append(event)
    return output


def summarize_horizon(events, horizon):
    key = str(horizon)
    completed = [
        event["outcomes"].get(key, {})
        for event in events
        if event.get("entry_status") == "ENTERED"
        and event.get("outcomes", {}).get(key, {}).get("status") == "COMPLETE"
    ]
    completed.sort(key=lambda item: (item.get("exit_date", ""), item.get("return_pct", 0)))
    returns = [float(item["return_pct"]) for item in completed]
    pnls = [float(item["pnl_yuan"]) for item in completed]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]

    curve = 0.0
    peak = 0.0
    max_drawdown = 0.0
    losing_streak = 0
    max_losing_streak = 0
    for item in sorted(
        (event for event in events
         if event.get("entry_status") == "ENTERED"
         and event.get("outcomes", {}).get(key, {}).get("status") == "COMPLETE"),
        key=lambda event: (event["signal_date"], event["code"]),
    ):
        result = float(item["outcomes"][key]["return_pct"])
        curve += result
        peak = max(peak, curve)
        max_drawdown = min(max_drawdown, curve - peak)
        if result < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0

    total = len(events)
    entered = sum(event.get("entry_status") == "ENTERED" for event in events)
    skipped = sum(event.get("entry_status") == "SKIPPED_NO_CHASE" for event in events)
    pending = sum(
        event.get("entry_status") == "PENDING_ENTRY"
        or event.get("outcomes", {}).get(key, {}).get("status") == "PENDING"
        for event in events
    )
    return {
        "horizon_sessions_after_t1_unlock": horizon,
        "signal_count": total,
        "entered_count": entered,
        "skipped_no_chase_count": skipped,
        "pending_count": pending,
        "completed_count": len(completed),
        "win_rate_pct": round(100 * len(wins) / len(completed), 2) if completed else None,
        "average_return_pct": round(sum(returns) / len(returns), 3) if returns else None,
        "median_return_pct": round(float(pd.Series(returns).median()), 3) if returns else None,
        "average_profit_yuan": round(sum(wins) / len(wins), 2) if wins else None,
        "average_loss_yuan": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / -sum(losses), 3) if losses else ("∞" if wins else None),
        "net_profit_yuan": round(sum(pnls), 2) if pnls else None,
        "event_sequence_max_drawdown_pct": round(max_drawdown, 3) if completed else None,
        "max_consecutive_losses": max_losing_streak if completed else None,
        "note": "每笔100股、次日开盘入场、T+1后第N个可卖交易日收盘退出；含双边佣金、卖出印花税和0.1%单边滑点。事件可重叠，累计回撤是事件序列统计，不是组合净值回撤。",
    }


def build_tracker(root=ROOT, lookback_sessions=180):
    root = Path(root)
    screen = load_json(root / "screen.json", {}) or {}
    master = load_json(root / "stocks.json", {}) or {}
    if not screen.get("asof"):
        raise ValueError("screen.json has no asof date")
    asof = str(screen["asof"])
    rows = screen.get("rows", [])
    events = []
    tracked = 0
    skipped_missing = 0
    for row in rows:
        code = str(row.get("code", ""))
        if len(code) != 6 or not code.isdigit():
            continue
        history = load_json(root / "history" / (code + ".json"), {}) or {}
        bars = history.get("bars", [])
        if len(bars) < 65 or history.get("asof") != asof:
            skipped_missing += 1
            continue
        tracked += 1
        name = str(row.get("name") or master.get("stocks", {}).get(code, {}).get("name") or code)
        events.extend(signal_events(code, name, bars, lookback_sessions))

    events.sort(key=lambda event: (event["signal_date"], event["code"]))
    metrics = {str(h): summarize_horizon(events, h) for h in HORIZONS}
    first_dates = [
        event["signal_date"] for event in events
        if event.get("signal_date")
    ]
    return {
        "schema": 1,
        "status": "ready" if tracked else "uninitialized",
        "source": "BaoStock unadjusted daily bars + quant_v1.evaluate_entry_signal equivalent",
        "asof": asof,
        "generated_at": now_cst().isoformat(timespec="seconds"),
        "lookback_sessions": int(lookback_sessions),
        "period_start": min(first_dates) if first_dates else None,
        "period_end": asof,
        "universe": {
            "current_candidate_count": int(screen.get("eligible_count", 0)),
            "current_covered_count": int(screen.get("covered_count", 0)),
            "current_coverage_pct": float(screen.get("coverage_pct", 0)),
            "stocks_with_current_history": tracked,
            "stocks_missing_current_history": skipped_missing,
            "stocks_in_current_screen": len(rows),
        },
        "signal_count": len(events),
        "metrics": metrics,
        "events": events[-20000:],
        "warning": [
            "当前统计只覆盖本次已成功获取且截至最新收盘日的股票，不代表完整历史A股成分股。",
            "使用当前股票池回溯历史信号，未包含历史退市股及历史成分变动，存在幸存者偏差。",
            "每个信号独立统计，多个信号可能重叠；事件序列回撤不是可交易组合回撤。",
            "使用不复权日线和固定费用/滑点假设；未模拟停牌、涨跌停、分红除权及真实成交队列。",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback-sessions", type=int, default=180)
    parser.add_argument("--output", default=str(ROOT / "signal_tracker.json"))
    args = parser.parse_args()
    result = build_tracker(ROOT, args.lookback_sessions)
    atomic_json(Path(args.output), result)
    print({
        "status": result["status"],
        "asof": result["asof"],
        "tracked_stocks": result["universe"]["stocks_with_current_history"],
        "signal_count": result["signal_count"],
        "metrics": result["metrics"],
        "output": args.output,
    })


if __name__ == "__main__":
    main()
