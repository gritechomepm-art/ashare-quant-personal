"""Read-only mobile tracker partitioning and same-cost comparison smoke tests."""
from pathlib import Path
from datetime import date
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from slice_signal_tracker import split_tracker


def test_mobile_tracker_cannot_edit_cache_and_preserves_metrics(tmp_path):
    source=tmp_path/"signal_tracker.json"
    orig={
      "schema":1,"asof":"2026-11-20","status":"ready",
      "signal_count":3,"metrics":{"3":{"completed_count":4,"win_rate_pct":25}},
      "portfolio":{"3":{"closed_trades":8,"profit_factor":.2}},
      "events":[
       {"id":"1","signal_date":"2026-11-20","code":"000001"},
       {"id":"2","signal_date":"2026-10-15","code":"000002"},
       {"id":"3","signal_date":"2026-09-17","code":"600000"}
      ]
    }
    source.write_text(json.dumps(orig,ensure_ascii=False),encoding="utf8")
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    folder=tmp_path/"site"/"data"/"tracker"
    stats=split_tracker(source,folder)
    assert stats["latest"]==1 and stats["archives"]==2
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    index=json.loads((folder/"index.json").read_text(encoding="utf8"))
    assert index["events"]==[]
    assert index["metrics"]==orig["metrics"]
    assert index["portfolio"]==orig["portfolio"]
    assert index["signal_count"]==3
    assert (folder/"recent30.json").exists()
    assert json.loads((folder/"recent30.json").read_text(encoding="utf8"))["events"][0]["id"]=="1"
    older=[json.loads((folder/(x["file"])).read_text(encoding="utf8"))["events"] for x in index["mobile_index"]["archives"]]
    assert sorted(e["id"] for events in older for e in events)==["2","3"]
    assert "signal_tracker.json" not in (ROOT/"scripts/build_site.py").read_text(encoding="utf8").split("for file in ['quotes.json'")[-1].split("]")[0]


def test_matched_control_same_trade_costs_and_clusters(tmp_path):
    code=r"""
const assert=require('node:assert/strict'),B=require('./assets/backtest-v2.js');
const bars=Array.from({length:86},(_,i)=>({
 date:new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10),
 open:100,high:101,low:99,close:100,ma5:99,ma10:98,atr14:2
}));
const gate=()=>({buy:true});  // not a trading rule; research benchmark only.
const orig=B.tradeAt(bars,'000001',3,64,gate);
const control=B.tradeAt(bars,'000001',3,64,gate);
assert.deepEqual(orig,control);
assert.equal(orig.exitIndex,68);
"""
    run=subprocess.run(["node","-e",code],cwd=ROOT,text=True,capture_output=True,timeout=20)
    assert run.returncode==0,run.stdout+run.stderr
    output=tmp_path/"control.json"
    build=subprocess.run(["node","scripts/build_matched_control.js",str(output),"40"],
         cwd=ROOT,text=True,capture_output=True,timeout=100)
    assert build.returncode==0,build.stdout+build.stderr
    report=json.loads(output.read_text(encoding="utf8"))
    assert report["schema"]==1
    assert report["fixed_historical_cutoff"]=="2026-07-21"
    assert report["rules_frozen"] is True
    assert report["auto_activate"] is False
    assert report["seed"]
    assert report["baseline_reference_trades"]>=report["results"]["train"]["matchedPairs"]+report["results"]["historical_test"]["matchedPairs"]
    for part in ("train","historical_test"):
        r=report["results"][part]
        assert r["distinctStocks"]<=r["matchedPairs"]
        if r["matchedPairs"]:
            assert r["clusterBootstrapReplicates"]==1000
            assert len(r["clusterBootstrap95Pp"])==2
            diff=r["signalAvgNetPct"]-r["controlAvgNetPct"]
            assert abs(diff-r["signalMinusControlPp"])<1e-9


def test_frontend_and_document_evidence_flags():
    html=(ROOT/"index.html").read_text(encoding="utf8")
    build=(ROOT/"scripts/build_site.py").read_text(encoding="utf8")
    assert "原策略不变" in html
    assert "不允许启用候选规则" in html
    assert "最优组不作独立结论" in html
    assert "评分仅排序用，不表示入选" in html
    assert "左右滑动看全表" in html
    assert "tracker/recent30.json" in html
    assert "tracker/index.json" in html
    assert "trackerLoadArchive" in html
    assert "signal_tracker.json" not in html
    assert "evidence_control.json" in html
    assert "build_matched_control.js" in build
    assert "slice_signal_tracker" in build
