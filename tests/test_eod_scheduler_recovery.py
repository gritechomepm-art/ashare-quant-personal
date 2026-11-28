"""EOD recovery gating, independent scheduled dispatch and immutable strategy checks."""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from eod_staleness import after_close_stale,validate_mainboard


def doc(day="2026-11-20",scope=None,count=600):
    return {"schema":1,"asof":day,"board_scope":scope,
            "eligible_count":3052,"covered_count":count,"rows":[]}


def test_recovery_only_in_weekday_beijing_after_close_and_when_stale():
    now=lambda s:datetime.fromisoformat(s)
    assert not after_close_stale(doc(),now("2026-11-23T15:30:00+08:00"))
    assert not after_close_stale(doc(),now("2026-11-22T20:00:00+08:00"))
    assert not after_close_stale(doc(),now("2026-11-23T17:29:00+08:00"))
    assert after_close_stale(doc(),now("2026-11-23T17:30:00+08:00"))
    assert after_close_stale(doc("2026-11-23",scope="FULL_A"),now("2026-11-23T18:57:00+08:00"))
    assert not after_close_stale(doc("2026-11-23",scope="SH_SZ_MAIN"),now("2026-11-23T18:57:00+08:00"))
    assert not after_close_stale(doc("2026-11-23",scope="SH_SZ_MAIN"),now("2026-11-24T16:00:00+08:00"))


def test_mainboard_publish_validation_is_fail_closed():
    assert validate_mainboard(doc("2026-11-23",scope="SH_SZ_MAIN",count=15))
    for v in [doc(),doc("2026-11-23",scope="SH_SZ_MAIN",count=0),
              {"schema":1,"asof":"2026-11-23","board_scope":"SH_SZ_MAIN","eligible_count":0,"covered_count":0,"rows":[]}]:
        with pytest.raises(ValueError):
            validate_mainboard(v)


def test_cli_simulated_missed_eod(tmp_path):
    path=tmp_path/"screen.json"
    path.write_text(json.dumps(doc()),encoding="utf8")
    args=[sys.executable,"scripts/eod_staleness.py","--screen",str(path),
          "--require-today-after-close","--now","2026-11-23T18:57:00+08:00"]
    x=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert x.returncode==0,x.stderr
    assert "True" in x.stdout
    args[-1]="2026-11-23T12:00:00+08:00"
    y=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert y.returncode==1


def test_independent_watchdog_node_scoped_and_no_secrets_in_git(tmp_path):
    r=subprocess.run(["node","--test","infra/cloudflare/ashare-eod-watchdog/test/watchdog.test.mjs"],
                      cwd=ROOT,text=True,capture_output=True,timeout=40)
    assert r.returncode==0,r.stdout+"\n"+r.stderr
    folder=ROOT/"infra/cloudflare/ashare-eod-watchdog"
    wrangler=(folder/"wrangler.toml").read_text(encoding="utf8")
    worker=(folder/"src/index.mjs").read_text(encoding="utf8")
    assert 'workers_dev = false' in wrangler
    assert '45 11,13 * * 1-5' in wrangler
    assert "GITHUB_ACTIONS_TOKEN" in worker
    assert "async fetch()" in worker and 'new Response("Not found"' in worker
    assert 'method: "POST"' in worker
    assert "No public" not in worker or "No HTTP dispatch endpoint" in worker
    assert "quant_v1.py" not in worker and "data/history" not in worker


def test_existing_workflow_remains_one_eod_and_frozen_strategy():
    workflow=(ROOT/".github/workflows/baostock-backfill.yml").read_text(encoding="utf8")
    assert "workflow_dispatch:" in workflow
    assert "37 9 * * 1-5" in workflow
    assert "17 10 * * 1-5" in workflow
    assert "eod_staleness.py" in workflow
    assert "if [ \"$GITHUB_EVENT_NAME\" = \"push\" ]; then" in workflow
    assert "batch_new=15" in workflow and "batch_new=300" in workflow
    assert "Validate output market scope and record EOD freshness" in workflow
    assert "scripts/ingest_baostock.py --quotes-file /tmp/ashare-quote-feed.json" in workflow
    original=(ROOT/"scripts/ingest_baostock.py").read_text(encoding="utf8")
    assert "if is_mainboard_symbol(str(r.code))" in original
    assert '"board_scope": "SH_SZ_MAIN"' in original
