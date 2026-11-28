"""Quote refresh scheduling should distinguish no candidate from a feed failure.

Do not change candidate selection, signal validation, ATR, position or EOD source.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from check_quote_readiness import quote_readiness


def screen(rows, scope="SH_SZ_MAIN"):
    return {"schema":1,"asof":"2026-11-20","board_scope":scope,"rows":rows,
            "status":"partial","eligible_count":3052}


def test_wait_for_mainboard_eod_when_legacy_full_market_screen_has_no_matching_board_scope():
    # Use an isolated legacy fixture. Never assert that the live production
    # screen must remain old; production data is expected to advance.
    old={"schema":1,"asof":"2026-11-20","board_scope":"FULL_A","rows":[],
         "status":"partial","eligible_count":3052}
    result=quote_readiness(old)
    assert result["status"]=="WAITING_MAINBOARD_EOD"
    assert result["can_fetch"] is False
    assert result["candidates"]==0
    assert "no full-market fallback" in result["reason"]


def test_new_mainboard_eod_with_zero_signals_is_safe_noop():
    result=quote_readiness(screen([
        {"code":"600001","score":30,"entry_signal":False,"close":10},
        {"code":"002532","score":54,"entry_signal":False,"close":15},
        {"code":"300940","score":95,"entry_signal":True,"close":14}]))
    assert result["status"]=="NO_ELIGIBLE_MAINBOARD_CANDIDATES"
    assert result["can_fetch"] is False
    assert result["candidates"]==0


def test_genuine_close_screen_mainboard_candidates_activate_existing_intraday_monitor():
    result=quote_readiness(screen([
        {"code":"600000","score":70,"entry_signal":False,"close":12},
        {"code":"002532","score":20,"entry_signal":True,"close":15},
        {"code":"300940","score":100,"entry_signal":True,"close":12},
        {"code":"688981","score":100,"entry_signal":True,"close":12},
        {"code":"920001","score":100,"entry_signal":True,"close":12},
        {"code":"605002","score":66,"entry_signal":False,"close":11}
    ]))
    assert result["status"]=="READY"
    assert result["can_fetch"] is True
    assert result["candidates"]==3


def test_legacy_screen_with_some_mainboard_rows_cannot_fake_mainboard_coverage():
    result=quote_readiness(screen([
        {"code":"600000","score":90,"entry_signal":True,"close":10}
    ],scope="FULL_A"))
    assert result["can_fetch"] is False
    assert result["status"]=="WAITING_MAINBOARD_EOD"


def test_malformed_screen_is_not_misclassified_as_normal_zero_candidate():
    for bad in [{},{"schema":2,"rows":[]},
                {"schema":1,"board_scope":"SH_SZ_MAIN","rows":None}]:
        with pytest.raises(ValueError):
            quote_readiness(bad)


def test_preflight_writes_auditable_outputs_without_fetch_or_data_mutation(tmp_path):
    p=tmp_path/"screen.json"
    p.write_text(json.dumps(screen([])),encoding="utf8")
    out=tmp_path/"output.txt"
    summary=tmp_path/"summary.txt"
    result=subprocess.run([sys.executable,"scripts/check_quote_readiness.py",
       "--screen",str(p),"--github-output",str(out),"--github-summary",str(summary)],
       cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert result.returncode==0,result.stdout+"\n"+result.stderr
    assert "fetch=false" in out.read_text()
    assert "NO_ELIGIBLE_MAINBOARD_CANDIDATES" in summary.read_text()
    assert "no quote-feed push" in summary.read_text()
    assert json.loads(p.read_text())==screen([])


def test_zero_candidate_paths_run_before_install_and_skip_every_mutation():
    w=(ROOT/".github/workflows/quotes.yml").read_text(encoding="utf8")
    header=w.index("Preflight EOD-screened main-board candidate pool")
    setup=w.index("actions/setup-python@v5")
    assert header<setup
    assert "--github-output \"$GITHUB_OUTPUT\"" in w
    assert "--github-summary \"$GITHUB_STEP_SUMMARY\"" in w
    assert w.count("steps.readiness.outputs.fetch")>=8
    assert "steps.readiness.outputs.fetch == 'true' && steps.clock.outputs.run == 'true'" in w
    assert "30 6 * * 1-5" in w  # 14:30 Beijing intraday snapshot
    assert "3-58/5 1-3,5-7 * * 1-5" not in w
    assert "11 7 * * 1-5" in w  # 15:11 Beijing post-close catch-up
    assert "python scripts/update_quotes.py --output /tmp/ashare-latest-quotes.json" in w
    quote=(ROOT/"scripts/update_quotes.py").read_text(encoding="utf8")
    assert "No qualified opportunity candidates in EOD screen; refuse all-market fallback" in quote
    assert "Stale Tencent snapshot during market session" in quote
    assert "verify_quote_source_day" in quote


def test_eod_producer_is_still_mainboard_and_old_history_remains_unmodified():
    eod=(ROOT/"scripts/ingest_baostock.py").read_text(encoding="utf8")
    assert "if is_mainboard_symbol(str(r.code))" in eod
    assert '"board_scope": "SH_SZ_MAIN"' in eod
    assert "query_history_k_data_plus" in eod
    build=(ROOT/"scripts/build_site.py").read_text(encoding="utf8")
    assert "build_v2_study.js" in build
    assert "build_entry_quality_v22.js" in build
