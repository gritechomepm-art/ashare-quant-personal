"""Trading-day EOD bootstrap, data validation and research screen."""
import argparse
import time
from datetime import timedelta
from pathlib import Path
import akshare as ak
import pandas as pd
from core import ROOT,load_json,norm_hist,norm_spot,atomic_json,now_cst,make_screen,append_bar_from_quote,is_eligible

def is_trade_date(date):
    x=ak.tool_trade_date_hist_sina()
    if 'trade_date' not in x.columns:raise ValueError('Trade calendar invalid; refuse update')
    valid=set(pd.to_datetime(x.trade_date,errors='coerce').dropna().dt.strftime('%Y-%m-%d').tolist())
    if len(valid)<100:raise ValueError('Trade calendar incomplete; refuse update')
    return date in valid

def main(root=ROOT,max_new=600,max_seconds=1000,retries=2,sleep=0.4):
    root=Path(root);today=now_cst()
    if today.hour<15 or (today.hour==15 and today.minute<15):
        raise RuntimeError('No EOD screen before 15:15 China time')
    asof=today.date().isoformat()
    if not is_trade_date(asof):
        print('Market holiday; no changes');return {'status':'closed','asof':asof}
    fetched=norm_spot(ak.stock_zh_a_spot_em(),today)
    quotes=fetched['quotes']
    atomic_json(root/'quotes.json',fetched)
    eligible=[(c,q) for c,q in sorted(quotes.items()) if is_eligible(c,q['name'],q)]
    fresh=0;bootstrapped=0;failure=[];start=time.monotonic()
    for code,quote in eligible:
        path=root/'history'/f'{code}.json'
        hist=load_json(path,{})
        bars=hist.get('bars',[])
        if len(bars)>=65:
            try:
                ok,new=append_bar_from_quote(hist,quote,asof)
                if ok:
                    new['code']=code;atomic_json(path,new);fresh+=1
            except Exception as exc:failure.append([code,str(exc)[:90]])
            continue
        if bootstrapped>=max_new or time.monotonic()-start>max_seconds:continue
        for attempt in range(retries+1):
            try:
                df=ak.stock_zh_a_hist(symbol=code,period='daily',
                    start_date=(today.date()-timedelta(days=540)).strftime('%Y%m%d'),
                    end_date=asof.replace('-',''),adjust='')
                if df is None:raise ValueError('No provider rows')
                v=norm_hist(df,code,asof=asof)
                if v[-1]['date']!=asof:raise ValueError('History missing today')
                atomic_json(path,{'schema':1,'code':code,'source':'AKShare stock_zh_a_hist 东方财富',
                    'adjust':'none','asof':asof,'bars':v})
                bootstrapped+=1;break
            except Exception as exc:
                if attempt==retries:failure.append([code,str(exc)[:90]])
                else:time.sleep(1.5*(attempt+1))
        time.sleep(sleep)
    screen=make_screen(fetched,root,asof)
    atomic_json(root/'screen.json',screen)
    atomic_json(root/'job_status.json',{'status':'ok','asof':asof,
        'full_universe':len(quotes),'history_updated':fresh,
        'new_histories':bootstrapped,'failed_count':len(failure),
        'failed_samples':failure[:12],'coverage_pct':screen['coverage_pct'],
        'generated_at':now_cst().isoformat(timespec='seconds')})
    print(f'EOD {asof}: quotes={len(quotes)}, eligible={len(eligible)}, history_updated={fresh}, new={bootstrapped}, coverage={screen["coverage_pct"]}%, failures={len(failure)}')
    return screen

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--max-new',type=int,default=600)
    ap.add_argument('--max-seconds',type=int,default=1000)
    ap.add_argument('--sleep',type=float,default=0.4)
    x=ap.parse_args()
    main(max_new=x.max_new,max_seconds=x.max_seconds,sleep=x.sleep)
