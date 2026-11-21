"""Evidence write-once ledger and frozen pre-change single-stock regression."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from seal_signal_evidence import capture, validate_chain


def mock_screen(day="2026-11-23"):
    # Generated after the true day's close, never timestamped as the prior afternoon.
    next_day = "2026-11-24" if day == "2026-11-23" else "2026-11-25"
    return {"schema": 1, "status": "partial", "asof": day,
            "generated_at": next_day+"T02:53:06+08:00",
            "universe_count": 5510, "eligible_count": 5317, "covered_count": 600,
            "rows": [
                {"code":"000001", "name":"示例A", "asof":day, "entry_signal":True,
                 "score":70, "close":10.0, "atr14":.25, "buy_low":9.9,"buy_high":10.1,
                 "entry_status":"BUY_WATCH","ma5":10,"ma10":9.9,"rsi14":51,
                 "volume_ratio":1.4},
                {"code":"000002", "name":"示例B","asof":day,"entry_signal":False}
            ]}


def save_source(path, obj):
    path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")


def test_append_only_hash_chain_no_rewrites(tmp_path):
    source=tmp_path/"screen.json"; ledger=tmp_path/"ledger"
    save_source(source,mock_screen())
    utc=datetime.fromisoformat("2026-11-23T19:35:00+00:00")
    first=capture(source,ledger,utc,"a"*40)
    assert first["status"]=="CREATED" and first["confirmed_signals"]==1
    path=ledger/"2026-11-23.json"
    locked=path.read_bytes()
    assert hashlib.sha256(source.read_bytes()).hexdigest()==json.loads(locked)["source_screen_sha256"]
    second=capture(source,ledger,utc,"a"*40)
    assert second["status"]=="UNCHANGED"
    assert path.read_bytes()==locked
    changed=mock_screen();changed["rows"][0]["score"]=99
    save_source(source,changed)
    with pytest.raises(ValueError,match="refusing overwrite"):
        capture(source,ledger,utc,"b"*40)
    assert path.read_bytes()==locked
    save_source(source,mock_screen("2026-11-24"))
    third=capture(source,ledger,datetime.fromisoformat("2026-11-24T19:35:00+00:00"),"c"*40)
    assert third["status"]=="CREATED"
    prev=json.loads(path.read_text(encoding="utf-8"))
    new=json.loads((ledger/"2026-11-24.json").read_text(encoding="utf-8"))
    assert new["previous_record_sha256"]==prev["record_sha256"]
    assert validate_chain(ledger)[1]==2
    path.write_text(locked.replace(b"5510",b"5511",1).decode("utf-8"),encoding="utf-8")
    with pytest.raises(ValueError,match="fingerprint"):
        validate_chain(ledger)


def test_no_retroactive_seal_or_lookahead(tmp_path):
    screen=tmp_path/"screen.json";ledger=tmp_path/"e"
    save_source(screen,mock_screen("2026-11-23"))
    with pytest.raises(ValueError,match="timely"):
        capture(screen,ledger,datetime.fromisoformat("2026-11-25T19:35:00+00:00"),"a"*40)
    legacy=mock_screen("2026-11-20")
    save_source(screen,legacy)
    with pytest.raises(ValueError,match="retrospectively"):
        capture(screen,ledger,datetime.fromisoformat("2026-11-20T19:35:00+00:00"),"a"*40)


def test_frozen_single_stock_000001_metrics_match_previous_main():
    # Fixture is frozen from main c588de9, NOT a refreshed EOD historical cache.
    code=r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const B=require('./assets/backtest-v2.js');
const html=fs.readFileSync('index.html','utf8');
const start=html.indexOf('function valMA('),end=html.indexOf('function graph(a){',start);
const {enrichJS,entrySignalJS}=new Function(html.slice(start,end)+
  '\nreturn {enrichJS,entrySignalJS} ')();
const a=enrichJS(JSON.parse(fs.readFileSync('tests/fixtures/frozen_000001_20261117.json','utf8')).bars);
const trades=B.sequential(a,'000001',3,entrySignalJS);
const r=B.evaluate(trades);
assert.equal(r.count,8);
assert.equal(r.winRate,25);
assert.ok(Math.abs(r.totalPnl-(-98.81738711178517))<1e-9);
assert.ok(Math.abs(r.profitFactor-0.19465087708979673)<1e-12);
"""
    p=subprocess.run(["node","-e",code],cwd=ROOT,text=True,capture_output=True,timeout=20)
    assert p.returncode==0,p.stdout+p.stderr


def test_immutable_strategy_engine_source_blobs():
    # If any strategy engine parameter or tracker calculation changes, stop release.
    pins={"assets/backtest-v2.js":"4bf2cf6c102dec8ce4cfecae44902b1aa7c99f4b",
          "quant_v1.py":"cef0378adc0bc0aa46aaea43bf051ec68a12922c",
          "scripts/build_signal_tracker.py":"b789123ff53590532922ef9d9b0a4fd729757d7d",
          "scripts/core.py":"77bbb87e599a7e30ef785978b78cf8906cf8355e"}
    for name,blob in pins.items():
        found=subprocess.run(["git","hash-object",name],cwd=ROOT,
                             text=True,capture_output=True,check=True).stdout.strip()
        assert found==blob,name+" changed while strategy code was frozen"


def test_ruleset_gate_requires_no_force_no_delete_without_bypass():
    from require_ledger_ruleset import require_rulesets
    def fetch(suffix):
        if not suffix:
            return [{"id":17,"enforcement":"active","target":"branch"}]
        return {"enforcement":"active","target":"branch",
                "conditions":{"ref_name":{"include":["refs/heads/signal-evidence-ledger"],"exclude":[]}},
                "rules":[{"type":"non_fast_forward"},{"type":"deletion"}],
                "bypass_actors":[]}
    assert require_rulesets(fetch) is True
    with pytest.raises(RuntimeError,match="missing"):
        require_rulesets(lambda suf: [])
    def bypass(suffix):
        d=fetch(suffix)
        if suffix:
            d["bypass_actors"]=[{"actor_id":1,"actor_type":"OrganizationAdmin","bypass_mode":"always"}]
        return d
    with pytest.raises(ValueError,match="bypass"):
        require_rulesets(bypass)
