/* AShare V2.0 — deterministic holding-horizon research (no brokerage integration).
 * Historical trade fees and execution rules intentionally match the V1.9 browser backtest.
 * Each record needs full future holding-window data; incomplete windows are censored.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.AShareBT2 = api;
})(typeof globalThis === 'undefined' ? this : globalThis, function () {
  'use strict';
  const HORIZONS = Object.freeze([1, 3, 5, 10]);
  function finite(value) { return typeof value === 'number' && Number.isFinite(value); }
  function buckets() { return Object.fromEntries(HORIZONS.map(h => [String(h), []])); }

  function tradeAt(a, code, hold, signalIdx, entrySignal, maxExitIdx = a.length - 1) {
    const en = signalIdx + 1, lastExit = en + hold;
    if (!HORIZONS.includes(hold) || signalIdx < 64 ||
        lastExit > Math.min(maxExitIdx, a.length - 1)) return null;
    const signal = a[signalIdx], entry = a[en];
    if (!signal || !entry) return null;
    const setup = entrySignal(a.slice(0, signalIdx + 1));
    if (!setup || !setup.buy) return null;
    const signalAtr = Number(signal.atr14), signalClose = Number(signal.close);
    const open = Number(entry.open);
    if (!finite(signalAtr) || signalAtr <= 0 || !finite(signalClose) ||
        !finite(open) || open < signalClose - .25 * signalAtr ||
        open > signalClose + .25 * signalAtr) return null;
    const buy = open * 1.001, notional = buy * 100;
    const buyfee = Math.max(5, notional * .0003);
    const stop = buy - 1.5 * signalAtr, target = buy + 2 * signalAtr;
    let ex = -1, sell = NaN, reason = '持有到期';
    for (let j = en + 1; j <= lastExit; j++) {
      const bar = a[j], o = Number(bar.open), high = Number(bar.high);
      const low = Number(bar.low), close = Number(bar.close);
      if (![o, high, low, close].every(finite)) return null;
      if (o <= stop) { ex = j; sell = o * .999; reason = '跳空止损'; break; }
      if (o >= target) { ex = j; sell = target * .999; reason = '止盈'; break; }
      if (low <= stop && high >= target) {
        ex = j; sell = stop * .999; reason = '止损（同日触及两线，保守按止损）'; break;
      }
      if (low <= stop) { ex = j; sell = stop * .999; reason = '止损'; break; }
      if (high >= target) { ex = j; sell = target * .999; reason = '止盈'; break; }
      // Deadline is an exit at that session close, not the following open.
      if (j === lastExit) { ex = j; sell = close * .999; reason = '持有期限到'; break; }
      if (close < bar.ma5 || bar.ma5 < bar.ma10) {
        ex = j + 1; sell = Number(a[ex].open) * .999;
        reason = '趋势转弱'; break;
      }
    }
    if (ex < 0 || !finite(sell)) return null;
    const proceeds = sell * 100;
    const sellfee = Math.max(5, proceeds * .0003) + proceeds * .0005;
    const pl = proceeds - notional - buyfee - sellfee;
    return {
      code, signalDate: signal.date, entryDate: a[en].date,
      exitDate: a[ex].date, entry: buy, exit: sell, pl, reason,
      returnPct: 100 * pl / (notional + buyfee), signalIndex: signalIdx,
      entryIndex: en, exitIndex: ex, heldSessions: ex - en
    };
  }

  function sequential(a, code, hold, entrySignal, options = {}) {
    if (!HORIZONS.includes(hold)) throw new Error('Unsupported hold: ' + hold);
    const minEntryIndex = Math.max(0, options.minEntryIndex ?? 0);
    const maxExitIndex = Math.min(a.length - 1, options.maxExitIndex ?? a.length - 1);
    const trades = [];
    let i = 64;
    while (i < maxExitIndex) {
      const en = i + 1;
      if (en < minEntryIndex) { i++; continue; }
      // Keep V1.9 rule: don't simulate trades with an incomplete holding window.
      if (en + hold > maxExitIndex) break;
      const result = tradeAt(a, code, hold, i, entrySignal, maxExitIndex);
      if (!result) { i++; continue; }
      trades.push(result);
      // Do not overlap a second position while this trade is open.
      i = result.exitIndex + 1;
    }
    return trades;
  }

  function evaluate(trades, includeDrawdown = true) {
    const n = trades.length;
    if (!n) return {count: 0, wins: 0, losses: 0, flats: 0,
      winRate: null, avgReturnPct: null, totalPnl: null,
      profitFactor: null, maxDrawdown: null, avgHold: null};
    let grossProfit = 0, grossLoss = 0, total = 0, returnSum = 0;
    let wins = 0, losses = 0, flats = 0, holdSum = 0;
    let peak = 0, equity = 0, draw = 0;
    // For paired (potentially overlapping) signals, drawdown is not a portfolio statistic.
    for (const trade of trades) {
      const p = trade.pl;
      total += p; returnSum += trade.returnPct; holdSum += trade.heldSessions;
      if (p > 0) { wins++; grossProfit += p; }
      else if (p < 0) { losses++; grossLoss -= p; } else flats++;
      equity += p; peak = Math.max(peak, equity);
      draw = Math.min(draw, equity - peak);
    }
    return {
      count: n, wins, losses, flats, winRate: 100 * wins / n,
      avgReturnPct: returnSum / n, totalPnl: total,
      profitFactor: grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : null,
      maxDrawdown: includeDrawdown ? Math.abs(draw) : null,
      avgHold: holdSum / n
    };
  }

  function study(a, code, entrySignal, requestedSplitIndex) {
    const n = a.length;
    const splitIndex = Math.max(65, Math.min(n, requestedSplitIndex ?? Math.floor(n * .70)));
    const paired = {train: buckets(), test: buckets()};
    const seq = {all: {}, train: {}, test: {}};
    for (const hold of HORIZONS) {
      seq.all[hold] = sequential(a, code, hold, entrySignal);
      seq.train[hold] = sequential(a, code, hold, entrySignal, {maxExitIndex: splitIndex - 1});
      seq.test[hold] = sequential(a, code, hold, entrySignal, {minEntryIndex: splitIndex});
    }
    for (let i = 64; i + 11 < n; i++) {
      const en = i + 1, maxOutcome = en + 10;
      if (en < splitIndex && maxOutcome >= splitIndex) continue; // purge crossing train/test
      const group = en < splitIndex ? 'train' : 'test';
      const first = tradeAt(a, code, 1, i, entrySignal);
      if (!first) continue;
      const results = {1: first};
      let valid = true;
      for (const hold of [3, 5, 10]) {
        results[hold] = tradeAt(a, code, hold, i, entrySignal);
        if (!results[hold]) { valid = false; break; }
      }
      if (!valid) continue;
      for (const hold of HORIZONS) paired[group][hold].push(results[hold]);
    }
    return {
      code, firstDate: a[0]?.date ?? null, lastDate: a.at(-1)?.date ?? null,
      splitIndex, splitDate: a[splitIndex]?.date ?? null,
      paired, sequential: seq
    };
  }

  function compareAverage(pairedPart) {
    const b = evaluate(pairedPart['3'], false), a = evaluate(pairedPart['5'], false);
    return a.avgReturnPct == null || b.avgReturnPct == null ? null :
      a.avgReturnPct - b.avgReturnPct;
  }

  return {HORIZONS, tradeAt, sequential, evaluate, study, compareAverage};
});
