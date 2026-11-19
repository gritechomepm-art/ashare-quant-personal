"""Exercise the exact inline JS ATR verifier through Node, not a duplicate Python model."""
from pathlib import Path
import subprocess


def test_fixed_signal_day_atr_binding_and_regressions():
    html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    begin = html.index("function entrySignalJS(a){")
    end = html.index("function graph(a){", begin)
    source = html[begin:end]
    checks = r"""
const assert = require('node:assert/strict');
function bars(){
 const a=[];
 for(let i=0;i<70;i++){
  const date=new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10);
  a.push({date,open:100,close:100,ma5:98,ma10:97,volRatio:1.4,rsi14:55,past20_high:101,atr14:2});
 }
 a[64].ma5=97;
 a[65].ma5=99;
 return a;
}
const a=bars(), entry=a[66].date, signal=a[65].date;
const candidate=verifiedPositionSignal(a,entry);
assert.deepEqual(candidate,{signal_date:signal,signal_atr:2,signal_source:'verified_eod_v19'});
const legacy={code:'000001',qty:100,cost:100,entry_date:entry};
assert.equal(positionAtrBasis(legacy,a).valid,false,'old holding must never silently bind');
assert.equal(positionAtrBasis(legacy,a).candidate.signal_date,signal);
const locked={...legacy,...candidate};
assert.equal(positionAtrBasis(locked,a).valid,true);
assert.equal(locked.cost-1.5*positionAtrBasis(locked,a).atr,97);
assert.equal(locked.cost+2*positionAtrBasis(locked,a).atr,104);
const recent=bars();recent[69].atr14=9;
assert.equal(positionAtrBasis(locked,recent).valid,true,'recent ATR must not move fixed risk lines');
assert.equal(locked.cost-1.5*positionAtrBasis(locked,recent).atr,97);
assert.equal(positionAtrBasis({...locked,signal_atr:3},a).valid,false,'pinned ATR mismatch must fail closed');
assert.equal(positionAtrBasis({...locked,signal_source:'manual'},a).valid,false);
assert.equal(positionAtrBasis({...locked,signal_date:a[64].date},a).valid,false);
assert.equal(positionAtrBasis({...locked,signal_atr:'2'},a).valid,false);
assert.equal(verifiedPositionSignal(a,'2026-12-31'),null,'unavailable entry history');
const noSignal=bars();noSignal[65].volRatio=1;
assert.equal(verifiedPositionSignal(noSignal,entry),null,'five signal conditions required');
assert.equal(positionAtrBasis(locked,noSignal).valid,false);
const noEntry=bars();noEntry[66].open=105;
assert.equal(verifiedPositionSignal(noEntry,entry),null,'next-session open must be in observation corridor');
assert.equal(positionAtrBasis(locked,noEntry).valid,false);
const corrected=bars();corrected[65].atr14=2.5;
assert.equal(positionAtrBasis(locked,corrected).valid,false,'historic correction must not rewrite prior pin');
assert.ok(htmlNotUsed === undefined);
""".replace("assert.ok(htmlNotUsed === undefined);", "")
    result = subprocess.run(["node", "-e", source + "\n" + checks], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "const hitStop=atrState.valid&&current<=stop" in html
    assert "const hitStop=current<=stop" not in html
    assert "data-bind-atr" in html
    assert "if(!confirm(" in html
    assert "saveLocal('positions',positions)" in html
