"""Validated AKShare market serialization and V1 strategy screening. Research only."""
from __future__ import annotations
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quant_v1 import enrich,backtest_one

CST=ZoneInfo('Asia/Shanghai')
BASE=Path(__file__).resolve().parents[1]
ROOT=BASE/'data'

def now_cst():
    return datetime.now(CST)

def atomic_json(path,obj):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
    tmp.replace(path)

def load_json(path,default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError):return default

def norm_spot(frame,fetched=None):
    """Reject partial / malformed all-market snapshots; never publish fabricated data."""
    required=['代码','名称','最新价','涨跌幅','今开','最高','最低','昨收','成交量','成交额']
    missing=[c for c in required if c not in frame.columns]
    if missing:raise ValueError('Spot columns missing: '+','.join(missing))
    quotes={}
    for row in frame[required].itertuples(index=False,name=None):
        raw={k:v for k,v in zip(required,row)}
        code=str(raw['代码']).split('.')[0].zfill(6)
        if len(code)!=6 or not code.isdigit():continue
        try:nums={k:float(raw[k]) for k in required[2:]}
        except (TypeError,ValueError):continue
        if not all(math.isfinite(v) for v in nums.values()):continue
        if any(nums[k]<=0 for k in ['最新价','昨收','最高','最低']):continue
        quotes[code]={'name':str(raw['名称'])[:30],'price':round(nums['最新价'],3),
                      'change_pct':round(nums['涨跌幅'],3),'open':round(nums['今开'],3),
                      'high':round(nums['最高'],3),'low':round(nums['最低'],3),
                      'prev_close':round(nums['昨收'],3),'volume_lots':int(nums['成交量']),
                      'amount_cny':round(nums['成交额'],2)}
    if len(quotes)<1200:raise ValueError(f'Only {len(quotes)} valid quotes; refuse partial-market overwrite')
    fetched=fetched or now_cst()
    return {'schema':1,'status':'ok','source':'AKShare stock_zh_a_spot_em / 东方财富公开行情',
            'fetched_at':fetched.isoformat(timespec='seconds'),
            'timing_note':'Collection time only, NOT exchange tick time. May be delayed.',
            'market_timezone':'Asia/Shanghai','count':len(quotes),'quotes':quotes}

def norm_hist(frame,code,asof=None):
    cols={'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close','成交量':'volume'}
    data=frame.rename(columns=cols)
    if not set(cols.values()).issubset(data.columns):raise ValueError('Missing daily bar columns')
    data=data[list(cols.values())].copy()
    data['date']=pd.to_datetime(data.date,errors='coerce')
    for col in ['open','high','low','close','volume']:data[col]=pd.to_numeric(data[col],errors='coerce')
    data=data.dropna().sort_values('date').drop_duplicates('date')
    data=data[(data[['open','high','low','close']]>0).all(axis=1)&(data.volume>=0)].copy()
    if asof:data=data[data.date<=pd.Timestamp(asof)]
    if len(data)<65:raise ValueError(f'{code} needs 65 daily bars, found {len(data)}')
    data=data.tail(260)
    return [{'date':r.date.strftime('%Y-%m-%d'),'open':round(float(r.open),3),
             'high':round(float(r.high),3),'low':round(float(r.low),3),
             'close':round(float(r.close),3),'volume':int(r.volume)}
            for r in data.itertuples(index=False)]

def is_eligible(code,name,quote):
    """Current snapshot filtering. Not a historical executable universe."""
    if 'ST' in name.upper() or '退' in name or '退市' in name:return False
    if not code.startswith(('0','3','6','4','8')):return False
    if quote.get('price',0)<=0 or quote.get('amount_cny',0)<30_000_000:return False
    return True

def score_history(code,history,quote,asof):
    bars=history.get('bars',[])
    if len(bars)<65 or bars[-1]['date']!=asof:return None
    frame=pd.DataFrame(bars)
    frame['date']=pd.to_datetime(frame['date'])
    x=enrich(frame);last=x.iloc[-1]
    def numeric(k):
        v=float(last[k])
        return round(v,3) if math.isfinite(v) else None
    return {'code':code,'name':quote['name'],'asof':asof,
            'close':numeric('close'),'score':int(last['score']),
            'signal':bool(last['signal']),'ma5':numeric('ma5'),
            'ma10':numeric('ma10'),'rsi14':numeric('rsi14'),'atr14':numeric('atr14')}

def make_screen(quotes_payload,root=ROOT,asof=None):
    asof=asof or now_cst().date().isoformat()
    quotes=quotes_payload['quotes'];universe=len(quotes)
    eligible=[(code,q) for code,q in quotes.items() if is_eligible(code,q['name'],q)]
    ranked=[];ready=0;failed=[]
    for code,quote in eligible:
        history=load_json(Path(root)/'history'/f'{code}.json',{})
        try:row=score_history(code,history,quote,asof)
        except Exception as exc:
            failed.append({'code':code,'reason':str(exc)[:70]});continue
        if row is not None:ready+=1;ranked.append(row)
    ranked.sort(key=lambda r:(r['signal'],r['score'],r['code']),reverse=True)
    coverage=round(ready/len(eligible)*100,2) if eligible else 0
    status='complete' if len(eligible)>0 and ready==len(eligible) else 'partial'
    return {'schema':1,'status':status,
            'source':'Python quant_v1.enrich / 不复权日线 (研究信号)',
            'asof':asof,'generated_at':now_cst().isoformat(timespec='seconds'),
            'universe_count':universe,'eligible_count':len(eligible),'covered_count':ready,
            'coverage_pct':coverage,'filter_note':'非ST/退市、成交额>=3000万元、至少65根K线；未建模停牌和历史成分',
            'total_signals':sum(bool(r['signal']) for r in ranked),
            'rows':ranked[:200],'screened_count':len(ranked),
            'warning':'只覆盖历史成功下载且截至当日的股票；未覆盖不等于无信号。'}

def append_bar_from_quote(history,quote,session_date):
    bars=list(history.get('bars',[]))
    price=quote['price'];high=quote['high'];low=quote['low'];o=quote['open']
    if not (0<low<=max(price,high,o) and high>=max(low,price,o)):
        return False,history
    if bars and bars[-1]['date']>session_date:raise ValueError('History newer than session')
    bar={'date':session_date,'open':o,'high':high,'low':low,'close':price,'volume':int(quote['volume_lots'])}
    if bars and bars[-1]['date']==session_date:bars[-1]=bar
    else:bars.append(bar)
    return True,{'schema':1,'code':history.get('code',''),
                 'source':'AKShare hist + close snapshot (不复权)',
                 'adjust':'none','asof':session_date,'bars':bars[-260:]}
