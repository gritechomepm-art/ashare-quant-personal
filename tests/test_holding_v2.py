"""V2 holding-horizon JS regression tests executed by pytest/Node."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run_js(source):
    code = "const B=require('./assets/backtest-v2.js'); const assert=require('node:assert/strict');\n" + source
    result = subprocess.run(["node", "-e", code], cwd=ROOT, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_v2_exit_rules_and_horizons():
    run_js(r"""
const make=(n=105)=>Array.from({length:n},(_,i)=>({
 date:new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10),
 open:100,high:101,low:99,close:100,ma5:99,ma10:98,atr14:1
}));
const buy=x=>({buy:x.length===65});
for(const h of [1,3,5,10]){
 const t=B.tradeAt(make(),'000001',h,64,buy);
 assert.equal(t.entryIndex,65);assert.equal(t.exitIndex,65+h);
 assert.equal(t.reason,'持有期限到');assert.ok(t.pl<0);
}
let a=make();a[65].low=95;
assert.equal(B.tradeAt(a,'000001',1,64,buy).exitIndex,66,'T+1 blocks same-day exit');
a=make();a[66].low=98;a[66].high=104;
assert.ok(B.tradeAt(a,'000001',3,64,buy).reason.includes('保守按止损'));
a=make();a[67].ma5=101;
assert.equal(B.tradeAt(a,'000001',5,64,buy).exitIndex,68);
a=make();a[68].ma5=101;
assert.equal(B.tradeAt(a,'000001',3,64,buy).reason,'持有期限到');
a=make();a[66].open=97;
assert.equal(B.tradeAt(a,'000001',5,64,buy).reason,'跳空止损');
assert.equal(B.tradeAt(make(67),'000001',10,64,buy),null);
""")


def test_v2_time_split_and_same_signal_pairing():
    run_js(r"""
const a=Array.from({length:200},(_,i)=>({
 date:new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10),
 open:100,high:101,low:99,close:100,ma5:99,ma10:98,atr14:1
}));
const signals=new Set([64,100,130,139,150,165,189]);
const choose=x=>({buy:signals.has(x.length-1)});
const r=B.study(a,'000001',choose,140);
assert.equal(r.paired.train[3].length,2);
assert.equal(r.paired.test[3].length,3);
for(const h of B.HORIZONS){
 assert.equal(r.paired.train[h].length,r.paired.train[1].length);
 assert.equal(r.paired.test[h].length,r.paired.test[1].length);
 assert.deepEqual(r.paired.test[h].map(x=>x.entryDate),r.paired.test[1].map(x=>x.entryDate));
 assert.ok(r.paired.train[h].every(x=>x.exitIndex<140));
 assert.ok(r.paired.test[h].every(x=>x.entryIndex>=140));
 const ts=r.sequential.test[h];
 assert.ok(ts.every((t,i)=>!i||ts[i-1].exitIndex<t.entryIndex));
}
assert.ok(!r.paired.train[1].some(x=>x.entryIndex===131));
assert.ok(r.paired.test[10].some(x=>x.entryIndex===140));
assert.ok(!r.paired.test[10].some(x=>x.entryIndex===190));
""")


def test_v2_missing_data_statistics_and_frontend():
    run_js(r"""
const zero=B.evaluate([]);
assert.equal(zero.count,0);assert.equal(zero.profitFactor,null);
const onlyWin=B.evaluate([{pl:5,returnPct:1,heldSessions:2}]);
assert.equal(onlyWin.profitFactor,Infinity);
const onlyLoss=B.evaluate([{pl:-5,returnPct:-1,heldSessions:2}]);
assert.equal(onlyLoss.profitFactor,0);
const paired=B.evaluate([{pl:5,returnPct:1,heldSessions:1},{pl:-3,returnPct:-.6,heldSessions:1}],false);
assert.equal(paired.profitFactor,5/3);assert.equal(paired.maxDrawdown,null);
""")
    html = (ROOT/"index.html").read_text(encoding="utf-8")
    build = (ROOT/"scripts"/"build_site.py").read_text(encoding="utf-8")
    assert '<script src="./assets/backtest-v2.js"></script>' in html
    assert "AShareBT2.study" in html
    assert "运行四组对比" in html
    assert "loadV2Cohort();" in html
    assert "build_v2_study.js" in build


def test_v2_generator_reads_only_actual_history(tmp_path):
    import json
    target=tmp_path/"study.json"
    result=subprocess.run(
        ["node", "scripts/build_v2_study.js", str(target), "40"],
        cwd=ROOT, text=True, capture_output=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    study=json.loads(target.read_text(encoding="utf-8"))
    assert study["schema"]==2
    assert study["horizons"]==[1,3,5,10]
    assert study["stocks_eligible"]>0
    assert study["cutoff_date"]
    assert study["comparison"]["live_default_hold"]==3
    assert study["comparison"]["auto_promotion"] is False
    for group in ["train","test"]:
        counts=[study["metrics"]["paired"][group][str(h)]["count"] for h in [1,3,5,10]]
        assert len(set(counts))==1, "paired results must share identical entry cohort"

    # V2.1 freezes the initially published holdout. Future data must not move it.
    assert study["cutoff_date"]=="2026-07-21"
    assert study["prospective"]["start_date"]=="2026-11-20"
    assert study["prospective"]["auto_promotion"] is False
    assert study["diagnostic"]["candidate_promotion"] is False
    assert study["diagnostic"]["holdout_reused_for_diagnostics"] is True
    for part in ("train","test"):
        stats=study["diagnostic"][part]
        assert stats["count"]==study["metrics"]["paired"][part]["3"]["count"]
        assert stats["priceAtLeast20"]["count"]<=stats["count"]
        if stats["count"]:
            assert stats["avgGrossPriceReturnPct"] is not None
            assert stats["avgEstimatedCostDragPp"] is not None
            # Cost drag exactly links raw entry/exit price returns to net returns.
            diff=stats["avgGrossPriceReturnPct"]-stats["avgNet100SharesPct"]
            assert abs(diff-stats["avgEstimatedCostDragPp"])<1e-8
            assert stats["avgNetMinimum5000NotionalPct"] is not None


def test_v21_frontend_research_is_not_live_signal():
    text=(ROOT/"index.html").read_text(encoding="utf-8")
    generator=(ROOT/"scripts"/"build_v2_study.js").read_text(encoding="utf-8")
    assert "v21DiagnosticBlock(data)" in text
    assert "冻结在2026-07-21" in text
    assert "2026-11-20" in text
    assert "candidate_promotion:false" in generator
    assert "auto_promotion:false" in generator
    assert "const cutDate='2026-07-21'" in generator
