#!/usr/bin/env python3
"""A-share educational daily-bar scanner/backtester (NO brokerage integrations)."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

COLS={'日期':'date','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume','成交额':'amount','换手率':'turnover'}

def load_csv(path):
    x=pd.read_csv(path,encoding='utf-8-sig').rename(columns=COLS)
    need={'date','open','high','low','close','volume'}
    if not need.issubset(x.columns): raise ValueError(f'{path}: missing {need-set(x.columns)}')
    x['date']=pd.to_datetime(x['date']); x=x.sort_values('date').drop_duplicates('date')
    for k in ['open','high','low','close','volume']:
        x[k]=pd.to_numeric(x[k],errors='coerce')
    x=x.dropna(subset=list(need)).reset_index(drop=True)
    if (x[['open','high','low','close']]<=0).any().any(): raise ValueError('Invalid price: nonpositive')
    return x

def enrich(x):
    x=x.copy(); c=x.close
    x['ma5']=c.rolling(5).mean(); x['ma10']=c.rolling(10).mean(); x['ma20']=c.rolling(20).mean()
    x['vol5_prev']=x.volume.shift(1).rolling(5).mean()
    pc=c.shift(1); tr=pd.concat([x.high-x.low,(x.high-pc).abs(),(x.low-pc).abs()],axis=1).max(axis=1)
    x['atr14']=tr.rolling(14).mean()
    delta=c.diff()
    up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    dn=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    rs=up/dn.replace(0,np.nan); x['rsi14']=100-100/(1+rs)
    x['past20_high']=x.high.shift(1).rolling(20).max()
    # All fields use the current close and earlier. Signals are actionable only NEXT session.
    x['signal']=(c>x.ma5)&(x.ma5>x.ma5.shift(1))&(x.ma5>x.ma10)&(x.volume>=1.15*x.vol5_prev)&x.rsi14.between(45,75)&(c>=x.past20_high*0.97)&(c<=x.past20_high*1.05)
    x['score']=((c>x.ma5)*25+(x.ma5>x.ma10)*20+(x.volume>=1.15*x.vol5_prev)*20+x.rsi14.between(45,75)*15+(c>=x.past20_high*0.97)*20).astype(int)
    return x


def evaluate_entry_signal(frame):
    """One-session-ahead research setup. This is a watch signal, never an order."""
    x = enrich(frame)
    if len(x) < 65:
        return {"status": "WAIT", "label": "历史数据不足", "reasons": ["至少需要65根有效日线"]}
    last, prev = x.iloc[-1], x.iloc[-2]
    values = [last.ma5, last.ma10, prev.ma5, last.vol5_prev,
              last.rsi14, last.atr14, last.past20_high]
    if not all(np.isfinite(float(v)) for v in values):
        return {"status": "WAIT", "label": "指标尚未就绪", "reasons": ["均线、RSI、ATR或成交量数据不足"]}
    close = float(last.close)
    atr = float(last.atr14)
    vol_ratio = float(last.volume / last.vol5_prev) if last.vol5_prev > 0 else 0.0
    high_ratio = close / float(last.past20_high) if last.past20_high > 0 else 0.0
    checks = [
        (close > float(last.ma5) and float(last.ma5) > float(last.ma10)
         and float(last.ma5) > float(prev.ma5), "收盘价站上MA5，MA5高于MA10且向上"),
        (vol_ratio >= 1.20, "成交量至少为前5日均量的1.2倍"),
        (45 <= float(last.rsi14) <= 68, "RSI14处于45–68的动能区间"),
        (0.97 <= high_ratio <= 1.02, "收盘价位于前20日高点下方3%至上方2%以内"),
        (0 < atr / close <= 0.06, "ATR波动率不高于收盘价的6%"),
    ]
    passed = [reason for ok, reason in checks if ok]
    failed = [reason for ok, reason in checks if not ok]
    buy = not failed
    return {
        "status": "BUY_WATCH" if buy else "WAIT",
        "label": "次日买入观察" if buy else "暂不买入",
        "asof_date": str(last.date.date()) if hasattr(last.date, "date") else str(last.date),
        "close": round(close, 3),
        "volume_ratio": round(vol_ratio, 2),
        "buy_low": round(close - 0.25 * atr, 3),
        "buy_high": round(close + 0.25 * atr, 3),
        "stop_reference": round(close - 1.5 * atr, 3),
        "target_reference": round(close + 2.0 * atr, 3),
        "valid_sessions": 1,
        "reasons": passed if buy else failed,
        "passed_count": len(passed),
        "total_checks": len(checks),
        "note": "收盘后生成的次日观察信号；次日跳空过大、流动性不足或行情过期时应放弃，不构成实际买单。",
    }


def evaluate_exit_signal(frame, cost, entry_date=None):
    """Close-based simulated position management; all exits are next-session reviews."""
    x = enrich(frame)
    if len(x) < 65 or not np.isfinite(float(cost)) or float(cost) <= 0:
        return {"status": "WAIT", "label": "历史数据不足", "reasons": ["无法可靠计算退出条件"]}
    last = x.iloc[-1]
    if not np.isfinite(float(last.atr14)) or not np.isfinite(float(last.ma5)) or not np.isfinite(float(last.ma10)):
        return {"status": "WAIT", "label": "指标尚未就绪", "reasons": ["ATR或均线数据不足"]}
    close = float(last.close)
    atr = float(last.atr14)
    cost = float(cost)
    stop = cost - 1.5 * atr
    target = cost + 2.0 * atr
    held_bars = None
    if entry_date:
        dates = pd.to_datetime(x.date).dt.strftime("%Y-%m-%d")
        held_bars = int((dates >= str(entry_date)[:10]).sum())
        latest_date = str(last.date.date()) if hasattr(last.date, "date") else str(last.date)
        if str(entry_date)[:10] >= latest_date:
            return {"status": "HOLD_T1", "label": "T+1限制，暂不可卖", "stop_price": round(stop, 3),
                    "target_price": round(target, 3), "held_bars": held_bars,
                    "reasons": ["买入日尚未结束或尚无后续交易日"]}
    if close <= stop:
        status, label, reason = "SELL_STOP", "止损退出观察", "收盘价触及或跌破成本价减1.5倍ATR"
    elif close >= target:
        status, label, reason = "SELL_TARGET", "止盈退出观察", "收盘价达到成本价加2倍ATR"
    elif close < float(last.ma5) or float(last.ma5) < float(last.ma10):
        status, label, reason = "SELL_TREND", "趋势转弱退出观察", "收盘价跌破MA5或MA5跌破MA10"
    elif held_bars is not None and held_bars >= 3:
        status, label, reason = "SELL_TIME", "达到3日持有期限", "达到策略设定的3个交易日持有期限"
    else:
        status, label, reason = "HOLD", "继续观察持有", "止损、止盈、趋势退出和持有期限条件均未触发"
    return {
        "status": status, "label": label, "reason": reason,
        "stop_price": round(stop, 3), "target_price": round(target, 3),
        "held_bars": held_bars, "asof_date": str(last.date.date()) if hasattr(last.date, "date") else str(last.date),
        "note": "依据最新完整日线收盘确认；卖出观察信号仅供下一交易时段复核，未考虑涨跌停、停牌和实际成交限制。",
    }



def backtest_trade_signals(frame, code, maxhold=3, fee=0.0003, stamp=0.0005,
                          minfee=5, slip=0.001):
    """V1.3 short-term signal backtest. Signal at close; next-open entry; T+1 exit."""
    if maxhold not in (1, 2, 3):
        raise ValueError("V1.3 maxhold must be 1, 2, or 3 trading sessions")
    x = enrich(frame).reset_index(drop=True)
    trades = []
    i = 64
    while i < len(x) - 1:
        setup = evaluate_entry_signal(x.iloc[:i + 1])
        if setup["status"] != "BUY_WATCH":
            i += 1
            continue
        signal_close = float(x.loc[i, "close"])
        atr = float(x.loc[i, "atr14"])
        entry_i = i + 1
        raw_open = float(x.loc[entry_i, "open"])
        # No chase: next open must remain inside the close-based observation zone.
        if raw_open < signal_close - 0.25 * atr or raw_open > signal_close + 0.25 * atr:
            i += 1
            continue
        buy = raw_open * (1 + slip)
        notional = buy * 100
        buy_fee = max(minfee, notional * fee)
        stop = buy - 1.5 * atr
        target = buy + 2.0 * atr
        last_exit = min(len(x) - 1, entry_i + maxhold)
        exit_i = None
        sell = None
        reason = "time"
        # T+1: begin exit checks on the session after the simulated purchase.
        for j in range(entry_i + 1, last_exit + 1):
            o, h, low, close = [float(x.loc[j, k]) for k in ("open", "high", "low", "close")]
            if o <= stop:
                exit_i, sell, reason = j, o * (1 - slip), "gap_stop"
                break
            if o >= target:
                exit_i, sell, reason = j, target * (1 - slip), "take_profit"
                break
            if low <= stop and h >= target:
                exit_i, sell, reason = j, stop * (1 - slip), "stop_both_touched_conservative"
                break
            if low <= stop:
                exit_i, sell, reason = j, stop * (1 - slip), "stop_loss"
                break
            if h >= target:
                exit_i, sell, reason = j, target * (1 - slip), "take_profit"
                break
            if close < float(x.loc[j, "ma5"]) or float(x.loc[j, "ma5"]) < float(x.loc[j, "ma10"]):
                exit_i = min(j + 1, len(x) - 1)
                raw_sell = float(x.loc[exit_i, "open"]) if exit_i > j else close
                sell, reason = raw_sell * (1 - slip), "trend_exit"
                break
            if j == last_exit:
                exit_i, sell, reason = j, close * (1 - slip), "time_exit"
                break
        if exit_i is None:
            # Incomplete forward sample: do not invent an exit or count an open trade.
            break
        sell_value = sell * 100
        sell_fee = max(minfee, sell_value * fee) + sell_value * stamp
        pnl = sell_value - notional - buy_fee - sell_fee
        trades.append({
            "code": code,
            "signal_date": str(x.loc[i, "date"].date()),
            "entry_date": str(x.loc[entry_i, "date"].date()),
            "exit_date": str(x.loc[exit_i, "date"].date()),
            "entry": round(buy, 3), "exit": round(sell, 3),
            "shares": 100, "bars_held": exit_i - entry_i,
            "exit_reason": reason, "pnl_yuan": round(pnl, 2),
            "return_pct": round(100 * pnl / (notional + buy_fee), 3),
        })
        i = exit_i + 1
    return trades


def backtest_one(x,code,fee=0.0003,stamp=0.0005,minfee=5,slip=0.001,maxhold=10,stop_atr=1.7):
    """Single-stock simulation: signal at close, next-open entry/exit, 100 shares.
    Models costs and T+1 direction, but NOT suspensions, limit-ups/downs or corporate actions.
    """
    x=enrich(x); trades=[]; i=35
    while i<len(x)-1:
        if not bool(x.loc[i,'signal']):i+=1;continue
        entry_i=i+1;price=float(x.loc[entry_i,'open'])*(1+slip)
        if not np.isfinite(price) or price<=0:i+=1;continue
        entrycost=price*100;buyfee=max(minfee,entrycost*fee)
        atr=float(x.loc[i,'atr14']);stop=price-max(0.01,stop_atr*atr)
        peak=float(x.loc[entry_i,'close']);exit_signal=entry_i+maxhold-1;reason='time'
        for j in range(entry_i,len(x)-1):
            peak=max(peak,float(x.loc[j,'close']))
            trailing=max(stop,peak-max(0.01,stop_atr*atr))
            if j>=entry_i and (x.loc[j,'close']<trailing or x.loc[j,'close']<x.loc[j,'ma5']):
                exit_signal=j;reason='risk';break
            if j>=entry_i+maxhold-1:exit_signal=j;reason='time';break
        exit_i=min(exit_signal+1,len(x)-1)
        if exit_i<=entry_i:i=entry_i+1;continue
        sellprice=float(x.loc[exit_i,'open'])*(1-slip);sellvalue=sellprice*100
        sellfee=max(minfee,sellvalue*fee)+sellvalue*stamp
        pnl=sellvalue-entrycost-buyfee-sellfee
        trades.append({'code':code,'signal_date':str(x.loc[i,'date'].date()),
                       'entry_date':str(x.loc[entry_i,'date'].date()),
                       'exit_date':str(x.loc[exit_i,'date'].date()),'entry':round(price,3),
                       'exit':round(sellprice,3),'shares':100,'bars_held':exit_i-entry_i,
                       'exit_reason':reason,'pnl_yuan':round(pnl,2),
                       'return_pct':round(100*pnl/(entrycost+buyfee),3)})
        i=exit_i+1
    return trades

def evaluate(trades):
    if not trades:return {'trades':0,'status':'NO_TRADES'}
    d=pd.DataFrame(trades);p=d.pnl_yuan.astype(float);curve=p.cumsum()
    drawdown=curve-curve.cummax().clip(lower=0)
    win=p[p>0];lose=p[p<0]
    return {'trades':len(d),'win_rate_pct':round(100*(p>0).mean(),2),
            'net_profit_yuan':round(p.sum(),2),'mean_pnl_yuan':round(p.mean(),2),
            'profit_factor':round(win.sum()/(-lose.sum()),2) if len(lose) else None,
            'max_trade_equity_drawdown_yuan':round(drawdown.min(),2),
            'worst_trade_yuan':round(p.min(),2),
            'max_holding_days':int(d.bars_held.max()),
            'note':'Trade-level sum, not portfolio CAGR or portfolio max drawdown'}

def fetch(codes,start,end,output):
    import akshare as ak
    output.mkdir(parents=True,exist_ok=True)
    ok=[];fail=[]
    for code in codes:
        try:
            raw=ak.stock_zh_a_hist(symbol=code,period='daily',start_date=start,end_date=end,adjust='')
            if raw is None or len(raw)<65:raise ValueError('not enough daily rows')
            raw.to_csv(output/f'{code}.csv',index=False,encoding='utf-8-sig');ok.append(code)
        except Exception as exc:fail.append((code,str(exc)[:150]))
    print('downloaded',ok,'errors',fail)

def run(csvdir,out,asof=None,hold=10):
    out.mkdir(parents=True,exist_ok=True);signals=[];trades=[];errors=[]
    for path in sorted(csvdir.glob('*.csv')):
        try:
            code=path.stem;raw=load_csv(path)
            if asof:raw=raw[raw.date<=pd.Timestamp(asof)].reset_index(drop=True)
            if len(raw)<65:errors.append({'code':code,'error':'less than 65 observations'});continue
            x=enrich(raw);last=x.iloc[-1]
            signals.append({'code':code,'asof_date':str(last.date.date()),'close':round(float(last.close),3),
                            'score':int(last.score),'watch_signal':bool(last.signal),
                            'ma5':round(float(last.ma5),3),'ma10':round(float(last.ma10),3),
                            'atr14':round(float(last.atr14),3),
                            'next_action':'WATCH_NEXT_SESSION_OPEN' if last.signal else 'NO_SIGNAL'})
            trades+=backtest_trade_signals(raw,code,maxhold=hold)
        except Exception as e:errors.append({'code':path.stem,'error':str(e)[:200]})
    pd.DataFrame(signals,columns=['code','asof_date','close','score','watch_signal','ma5','ma10','atr14','next_action']).sort_values('score',ascending=False).to_csv(out/'signals.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(trades,columns=['code','signal_date','entry_date','exit_date','entry','exit','shares','bars_held','exit_reason','pnl_yuan','return_pct']).to_csv(out/'trades.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([evaluate(trades)]).to_csv(out/'metrics.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(errors,columns=['code','error']).to_csv(out/'errors.csv',index=False,encoding='utf-8-sig')
    print(f'Analysed {len(signals)} stocks, {len(trades)} trades, {len(errors)} errors. Output: {out}')

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('fetch');a.add_argument('--codes',nargs='+',required=True)
    a.add_argument('--start',default='20230101');a.add_argument('--end',default='20261030');a.add_argument('--out',default='data')
    b=sub.add_parser('run');b.add_argument('--data',default='data');b.add_argument('--out',default='results')
    b.add_argument('--asof');b.add_argument('--hold',type=int,choices=[1,2,3],default=3)
    z=ap.parse_args()
    if z.cmd=='fetch':fetch(z.codes,z.start,z.end,Path(z.out))
    else:run(Path(z.data),Path(z.out),z.asof,z.hold)

if __name__=='__main__':main()
