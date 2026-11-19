"""Research-only V2.2: predeclared entry filters, disjoint dates, and no auto-promotion."""
from pathlib import Path
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def run_node(code):
    result=subprocess.run(["node","-e",code],cwd=ROOT,text=True,capture_output=True,timeout=20)
    assert result.returncode==0,result.stdout+"\n"+result.stderr


def test_research_filters_are_signal_day_only():
    run_node(r"""
const assert=require('node:assert/strict'),R=require('./assets/entry-quality-v22.js');
assert.deepEqual(R.RULES.map(x=>x.id),['baseline','ma_gap','ma_slope','volume','rsi','atr']);
const trade={signalMetrics:{maGap:.006,maSlope:.004,volRatio:1.5,rsi:55,atrPct:.035}};
for(const r of R.RULES)assert.equal(R.supports(r.id,trade),true);
assert.equal(R.supports('volume',{signalMetrics:{...trade.signalMetrics,volRatio:1.2}}),false);
assert.equal(R.supports('ma_gap',{signalMetrics:{...trade.signalMetrics,maGap:.005}}),false);
assert.equal(R.supports('rsi',{signalMetrics:{...trade.signalMetrics,rsi:69}}),false);
assert.equal(R.supports('atr',{signalMetrics:{...trade.signalMetrics,atrPct:.04}}),false);
assert.throws(()=>R.supports('unknown',trade));
const rows=[{date:'2026-01-01',close:100,ma5:98,ma10:97,atr14:2,volRatio:1.4,rsi14:55},
 {date:'2026-01-02',close:100,ma5:99,ma10:97,atr14:2,volRatio:1.5,rsi14:55},
 {date:'2026-01-03',close:100,ma5:99,ma10:97,atr14:7,volRatio:1.5,rsi14:55}];
const enriched=R.annotate({signalIndex:1,code:'000001',entryDate:'2026-01-03'},rows);
assert.equal(enriched.signalMetrics.atrPct,.02,'signal index only, no use of next day ATR');
assert.equal(enriched.signalMetrics.maGap,.02);
assert.equal(enriched.signalMetrics.maSlope,.01);
""")


def test_research_statistics_and_future_gate():
    run_node(r"""
const assert=require('node:assert/strict'),R=require('./assets/entry-quality-v22.js');
const base={code:'000001',entry:100.1,exit:98.901,entryDate:'2026-11-19',signalMetrics:{maGap:.01,maSlope:.006,volRatio:1.6,rsi:55,atrPct:.02}};
const trades=[{...base,reason:'趋势转弱',returnPct:-1.5,pl:-155},
 {...base,code:'000002',reason:'止盈',returnPct:1,pl:100}];
const s=R.stats(trades);
assert.equal(s.count,2);assert.equal(s.distinctStocks,2);assert.equal(s.trendExitPct,50);
assert.equal(s.reasons.find(x=>x.reason==='趋势转弱').count,1);
assert.equal(s.avgNetPct,-.25);
assert.equal(s.winRatePct,50);
assert.equal(s.profitFactor,100/155);
assert.equal(R.evaluateRuleTables(trades,trades).length,6);
const p=R.prospectiveState(trades,'2026-11-20');
assert.equal(p.completedPairedSignals,0);
assert.equal(p.status,'WAIT_FOR_FUTURE_SAMPLES');
assert.equal(p.autoApply,false);
const newer=R.prospectiveState([{...trades[0],entryDate:'2026-11-20'}],'2026-11-20');
assert.equal(newer.completedPairedSignals,1);
assert.equal(newer.distinctStocks,1);
assert.equal(newer.autoApply,false);
""")


def test_real_committed_history_smoke_and_frozen_cutoff(tmp_path):
    output=tmp_path/"entry_v22.json"
    result=subprocess.run(["node","scripts/build_entry_quality_v22.js",str(output),"35"],
        cwd=ROOT,text=True,capture_output=True,timeout=75)
    assert result.returncode==0,result.stdout+"\n"+result.stderr
    research=json.loads(output.read_text(encoding="utf-8"))
    assert research["schema"]==1
    assert research["historicCutoff"]=="2026-07-21"
    assert research["forwardStart"]=="2026-11-20"
    assert research["historyFilesRead"]==35
    assert research["eligibleHistoryFiles"]>0
    assert research["candidateAutoApply"] is False
    assert research["criteria"]["historicalOosUsedBefore"] is True
    assert research["criteria"]["automaticStrategyPromotion"] is False
    assert len(research["candidates"])==6
    assert research["baseline"]["train"]["count"]>=0
    assert research["baseline"]["test"]["count"]>=0
    for phase in ["train","test"]:
        base=research["baseline"][phase]
        count=sum(x["count"] for x in base["reasons"])
        assert count==base["count"]
        assert sum(c[phase]["count"]>base["count"] for c in research["candidates"])==0


def test_frontend_and_publish_wiring():
    html=(ROOT/"index.html").read_text(encoding="utf-8")
    build=(ROOT/"scripts"/"build_site.py").read_text(encoding="utf-8")
    assert "V2.2" in html
    assert 'id="btEntryQuality"' in html
    assert "loadEntryQualityV22();" in html
    assert "entry_quality_v22.json" in html
    assert "不可回填的信号记录" in html
    assert "build_entry_quality_v22.js" in build
    assert "build_v2_study.js" in build
