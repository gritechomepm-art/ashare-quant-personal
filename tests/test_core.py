from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from core import norm_spot,norm_hist,append_bar_from_quote,make_screen,atomic_json,normalize_stock_master
import pandas as pd
import pytest

def synthetic_quotes(n):
    return pd.DataFrame([{'代码':str(100000+i),'名称':f'模拟样本{i}',
        '最新价':10+i*.0001,'涨跌幅':1.,'今开':10.,'最高':11.,
        '最低':9.,'昨收':10.,'成交量':10000,'成交额':60_000_000}
        for i in range(n)])

def test_quote_rejects_partial_market():
    with pytest.raises(ValueError,match='Only'):
        norm_spot(synthetic_quotes(20))
    x=norm_spot(synthetic_quotes(1500))
    assert x['status']=='ok' and x['count']==1500

def test_history_and_score_coverage(tmp_path):
    dates=pd.bdate_range(end='2026-11-10',periods=90)
    rows=[]
    for i,d in enumerate(dates):
        p=10+i*.01
        rows.append({'日期':str(d.date()),'开盘':p,'最高':p+.2,
                     '最低':p-.2,'收盘':p,'成交量':10000})
    bars=norm_hist(pd.DataFrame(rows),'000708')
    assert len(bars)==90
    quote={'name':'测试股票','price':bars[-1]['close'],
           'open':bars[-1]['open'],'high':bars[-1]['high'],
           'low':bars[-1]['low'],'volume_lots':bars[-1]['volume'],
           'amount_cny':80_000_000}
    ok,h=append_bar_from_quote({'schema':1,'code':'000708','bars':bars},quote,'2026-11-10')
    assert ok and len(h['bars'])==90
    root=tmp_path/'data'
    atomic_json(root/'history'/'000708.json',h)
    x=make_screen({'quotes':{'000708':quote}},root,asof='2026-11-10')
    assert x['status']=='complete' and x['covered_count']==1
    y=make_screen({'quotes':{'000708':quote,'000001':{**quote,'name':'第二只'}}},root,asof='2026-11-10')
    assert y['status']=='partial' and y['covered_count']==1

def test_rejects_short_history():
    with pytest.raises(ValueError,match='65'):
        norm_hist(pd.DataFrame([{'日期':'2026-11-10','开盘':10,'最高':11,
                                 '最低':9,'收盘':10,'成交量':1000}]),'000708')

def test_no_private_data_published():
    src=Path(__file__).resolve().parents[1]
    shell=(src/'index.html').read_text()
    assert '本机' in shell and '自动下单' in shell
    assert 'stock_zh_a_spot_em' not in shell
    sw=(src/'sw.js').read_text()
    assert "includes('/data/')" in sw and 'no-store' in sw
    pub=(src/'scripts'/'build_site.py').read_text()
    assert 'positions.json' not in pub

def test_quotes_workflow_no_pages_artifact():
    src=Path(__file__).resolve().parents[1]
    quotes=(src/'.github/workflows/quotes.yml').read_text()
    assert 'upload-pages-artifact@' not in quotes
    assert 'deploy-pages@' not in quotes
    shell=(src/'index.html').read_text()
    assert 'raw.githubusercontent.com' in shell


def test_full_stock_master_contains_exchange_and_names():
    frame = pd.DataFrame([
        {"code": "sz.000708", "code_name": "中信特钢"},
        {"code": "sz.002600", "code_name": "领益智造"},
        {"code": "sh.600000", "code_name": "浦发银行"},
    ] * 500)
    master = normalize_stock_master(frame, "2026-11-11")
    assert master["count"] == 3
    assert master["stocks"]["000708"]["name"] == "中信特钢"
    assert master["stocks"]["600000"]["market"] == "SH"
