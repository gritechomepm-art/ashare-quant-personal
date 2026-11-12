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
MIN_SIGNAL_PRICE = 3.0
MAX_SIGNAL_PRICE = 100.0


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
        if not (MIN_SIGNAL_PRICE <= signal_close <= MAX_SIGNAL_PRICE):
            continue
        atr_value = float(row["atr14"])
        buy_low = signal_close - 0.25 * atr_value
        buy_high = signal_close + 0.25 * atr_value

        event = {
            "id": code + "|" + signal_date,
            "code": code,
            "name": name,
            "signal_date": signal_date,
            "signal_close": round(signal_close, 3),
            "score": int(row.get("score", 0)),
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
    """Independent signal event study; overlapping events are intentionally not a portfolio."""
    key = str(horizon)
    completed = [
        event["outcomes"].get(key, {})
        for event in events
        if event.get("entry_status") == "ENTERED"
        and event.get("outcomes", {}).get(key, {}).get("status") == "COMPLETE"
    ]
    returns = [float(item["return_pct"]) for item in completed]
    pnls = [float(item["pnl_yuan"]) for item in completed]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    total = len(events)
    entered = sum(event.get("entry_status") == "ENTERED" for event in events)
    skipped = sum(event.get("entry_status") == "SKIPPED_NO_CHASE" for event in events)
    pending = sum(
        event.get("entry_status") == "PENDING_ENTRY"
        or event.get("outcomes", {}).get(key, {}).get("status") == "PENDING"
        for event in events
    )
    ordered = sorted(
        (event for event in events
         if event.get("entry_status") == "ENTERED"
         and event.get("outcomes", {}).get(key, {}).get("status") == "COMPLETE"),
        key=lambda event: (event.get("signal_date", ""), event.get("code", "")),
    )
    curve = 0.0
    peak = 0.0
    event_drawdown = 0.0
    streak = 0
    max_streak = 0
    for event in ordered:
        result = float(event["outcomes"][key]["return_pct"])
        curve += result
        peak = max(peak, curve)
        event_drawdown = min(event_drawdown, curve - peak)
        streak = streak + 1 if result < 0 else 0
        max_streak = max(max_streak, streak)
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
        "event_sequence_max_drawdown_pct": round(event_drawdown, 3) if completed else None,
        "max_consecutive_losses": max_streak if completed else None,
        "note": "独立信号事件统计；同一股票/日期附近的信号可能重叠，不代表组合净值或可直接执行的资金曲线。组合回撤请看组合模拟指标。",
    }


def simulate_portfolio(events, bars_by_code, horizon, initial_capital=1_000_000.0,
                       max_positions=10, position_size_pct=0.10):
    """Simulate one long-only portfolio with cash, 100-share lots and T+1 exits."""
    key = str(horizon)
    dates = sorted({str(bar["date"])[:10] for bars in bars_by_code.values() for bar in bars})
    if not dates:
        return {"status": "NO_DATA"}

    bar_maps = {
        code: {str(bar["date"])[:10]: bar for bar in bars}
        for code, bars in bars_by_code.items()
    }
    candidates_by_date = {}
    for event in events:
        if event.get("entry_status") != "ENTERED":
            continue
        entry_date = event.get("entry_date")
        if not entry_date or entry_date not in bar_maps.get(event["code"], {}):
            continue
        entry_bar = bar_maps[event["code"]][entry_date]
        candidates_by_date.setdefault(entry_date, []).append({
            "event": event,
            "code": event["code"],
            "name": event.get("name", event["code"]),
            "entry_date": entry_date,
            "raw_open": float(entry_bar["open"]),
            "exit_date": event.get("outcomes", {}).get(key, {}).get("exit_date"),
        })
    for candidates in candidates_by_date.values():
        candidates.sort(key=lambda c: (
            -int(c["event"].get("score", 0)),
            -float(c["event"].get("volume_ratio", 0)),
            c["code"],
        ))

    cash = float(initial_capital)
    equity = float(initial_capital)
    peak = float(initial_capital)
    max_drawdown_pct = 0.0
    open_positions = {}
    closed = []
    rejected_capacity = 0
    rejected_duplicate = 0
    rejected_cash = 0
    curve = []

    for day in dates:
        # New entries occur at today's open. Positions scheduled to exit at
        # today's close still occupy a slot throughout the trading session.
        for candidate in candidates_by_date.get(day, []):
            code = candidate["code"]
            if code in open_positions:
                rejected_duplicate += 1
                candidate["event"].setdefault("portfolio_status", {})[key] = "SKIPPED_DUPLICATE"
                continue
            if len(open_positions) >= max_positions:
                rejected_capacity += 1
                candidate["event"].setdefault("portfolio_status", {})[key] = "SKIPPED_CAPACITY"
                continue
            entry_price = candidate["raw_open"] * (1 + SLIPPAGE)
            target_value = equity * position_size_pct
            shares = int(target_value / (entry_price * 100)) * 100
            if shares < 100:
                rejected_cash += 1
                candidate["event"].setdefault("portfolio_status", {})[key] = "SKIPPED_LOT_SIZE"
                continue
            buy_value = entry_price * shares
            buy_fee = max(MIN_FEE, buy_value * FEE_RATE)
            total_cost = buy_value + buy_fee
            if total_cost > cash:
                rejected_cash += 1
                candidate["event"].setdefault("portfolio_status", {})[key] = "SKIPPED_CASH"
                continue
            cash -= total_cost
            open_positions[code] = {
                "code": code, "name": candidate["name"], "shares": shares,
                "entry_date": day, "entry_price": entry_price,
                "buy_value": buy_value, "buy_fee": buy_fee,
                "exit_date": candidate["exit_date"],
                "last_close": candidate["raw_open"],
            }
            candidate["event"].setdefault("portfolio_status", {})[key] = "ENTERED"

        # Close T+1-eligible positions at the specified daily close.
        for code, position in list(open_positions.items()):
            bar = bar_maps.get(code, {}).get(day)
            if not bar:
                continue
            close_price = float(bar["close"])
            position["last_close"] = close_price
            if position["exit_date"] == day:
                exit_price = close_price * (1 - SLIPPAGE)
                sell_value = exit_price * position["shares"]
                sell_fee = max(MIN_FEE, sell_value * FEE_RATE) + sell_value * STAMP_RATE
                pnl = sell_value - position["buy_value"] - position["buy_fee"] - sell_fee
                ret = 100 * pnl / (position["buy_value"] + position["buy_fee"])
                cash += sell_value - sell_fee
                closed.append({
                    "code": code, "name": position["name"],
                    "entry_date": position["entry_date"], "exit_date": day,
                    "pnl_yuan": pnl, "return_pct": ret,
                })
                del open_positions[code]

        # Mark open holdings to estimated liquidation value (slippage + sell fees).
        market_value = 0.0
        for code, position in open_positions.items():
            mark = position["last_close"] * (1 - SLIPPAGE) * position["shares"]
            estimated_sell_fee = max(MIN_FEE, mark * FEE_RATE) + mark * STAMP_RATE
            market_value += max(0.0, mark - estimated_sell_fee)
        equity = cash + market_value
        peak = max(peak, equity)
        drawdown = (equity / peak - 1) * 100 if peak > 0 else 0.0
        max_drawdown_pct = min(max_drawdown_pct, drawdown)
        curve.append({"date": day, "equity_yuan": round(equity, 2), "drawdown_pct": round(drawdown, 3)})

    closed.sort(key=lambda trade: (trade["exit_date"], trade["code"]))
    pnls = [trade["pnl_yuan"] for trade in closed]
    returns = [trade["return_pct"] for trade in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    streak = 0
    max_streak = 0
    for pnl in pnls:
        if pnl < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    unrealized = 0.0
    for position in open_positions.values():
        mark = position["last_close"] * (1 - SLIPPAGE) * position["shares"]
        estimated_sell_fee = max(MIN_FEE, mark * FEE_RATE) + mark * STAMP_RATE
        unrealized += mark - estimated_sell_fee - position["buy_value"] - position["buy_fee"]

    return {
        "status": "ready",
        "initial_capital_yuan": round(initial_capital, 2),
        "ending_equity_yuan": round(equity, 2),
        "net_profit_yuan": round(equity - initial_capital, 2),
        "total_return_pct": round((equity / initial_capital - 1) * 100, 3),
        "realized_net_profit_yuan": round(sum(pnls), 2),
        "unrealized_pnl_yuan": round(unrealized, 2),
        "closed_trades": len(closed),
        "open_positions": len(open_positions),
        "win_rate_pct": round(100 * len(wins) / len(closed), 2) if closed else None,
        "average_return_pct": round(sum(returns) / len(returns), 3) if returns else None,
        "average_profit_yuan": round(sum(wins) / len(wins), 2) if wins else None,
        "average_loss_yuan": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / -sum(losses), 3) if losses else ("∞" if wins else None),
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "max_consecutive_losses": max_streak,
        "max_positions": max_positions,
        "position_size_pct": round(position_size_pct * 100, 1),
        "rejected_capacity_count": rejected_capacity,
        "rejected_duplicate_code_count": rejected_duplicate,
        "rejected_cash_or_lot_count": rejected_cash,
        "note": "组合模拟：初始资金100万元，最多10只持仓，每笔按当日组合权益10%买入、整手100股；次日开盘入场，T+1后按指定周期收盘退出。含佣金、卖出印花税及0.1%单边滑点；未模拟涨跌停、停牌、除权及真实成交队列。",
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
    bars_by_code = {}
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
        bars_by_code[code] = bars
        name = str(row.get("name") or master.get("stocks", {}).get(code, {}).get("name") or code)
        events.extend(signal_events(code, name, bars, lookback_sessions))

    events.sort(key=lambda event: (event["signal_date"], event["code"]))
    metrics = {str(h): summarize_horizon(events, h) for h in HORIZONS}
    portfolio = {str(h): simulate_portfolio(events, bars_by_code, h) for h in HORIZONS}
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
        "price_filter": {"min": MIN_SIGNAL_PRICE, "max": MAX_SIGNAL_PRICE, "unit": "CNY"},
        "portfolio_assumptions": {"initial_capital_yuan": 1000000, "max_positions": 10, "position_size_pct": 10},
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
        "portfolio": portfolio,
        "events": events[-20000:],
        "warning": [
            "当前统计只覆盖本次已成功获取且截至最新收盘日的股票，不代表完整历史A股成分股。",
            "使用当前股票池回溯历史信号，未包含历史退市股及历史成分变动，存在幸存者偏差。",
            "独立信号事件统计可能重叠；组合回撤另按100万元初始资金、最多10个持仓、每笔10%权益的组合模拟计算。",
            "统计按信号收盘价3–100元过滤；使用不复权日线和固定费用/滑点假设，未模拟停牌、涨跌停、分红除权及真实成交队列。",
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
