"""Opportunity-only quote collection: never fall back to the full stock master."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from scripts import update_quotes as quote


def make_screen(rows, asof="2026-11-12"):
    return {"schema": 1, "asof": asof, "status": "partial",
            "eligible_count": 5317, "covered_count": len(rows), "rows": rows}


def test_only_high_scored_and_true_signals_are_selected():
    screen = make_screen([
        {"code": "600001", "entry_signal": False, "score": 80, "close": 18},
        {"code": "600002", "entry_signal": True, "score": 10, "close": 16},
        {"code": "600003", "entry_signal": False, "score": 54, "close": 16},
        {"code": "600004", "entry_signal": False, "score": 55, "close": 11},
        {"code": "600005", "entry_signal": True, "score": 99, "close": 130},
    ])
    assert quote.select_opportunity_codes(screen) == ["600002", "600001", "600004"]


def test_candidate_cap_and_priority_are_deterministic():
    rows = [{"code": f"{600100+i:06d}", "entry_signal": False, "score": i,
             "close": 11} for i in range(60)]
    rows.append({"code": "000001", "entry_signal": True, "score": 0, "close": 10})
    result = quote.select_opportunity_codes(make_screen(rows), min_score=50, cap=3)
    assert result == ["000001", "600159", "600158"]


def test_missing_or_bad_data_cannot_trigger_full_market_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(quote, "ROOT", tmp_path)
    (tmp_path/"data").mkdir()
    (tmp_path/"data"/"stocks.json").write_text(
        json.dumps({"stocks": {f"{i:06d}": {} for i in range(5500)}}))
    with pytest.raises(RuntimeError, match="No EOD screening"):
        quote.load_codes()
    (tmp_path/"data"/"screen.json").write_text(json.dumps(make_screen(
        [{"code": "000001", "score": 20, "entry_signal": False, "close": 10}],
        asof=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())))
    with pytest.raises(RuntimeError, match="No qualified"):
        quote.load_codes()


def test_screened_pool_is_small_even_with_full_master(tmp_path, monkeypatch):
    monkeypatch.setattr(quote, "ROOT", tmp_path)
    (tmp_path/"data").mkdir()
    (tmp_path/"data"/"stocks.json").write_text(
        json.dumps({"stocks": {f"{i:06d}": {} for i in range(5500)}}))
    rows=[{"code": "603217", "score": 80, "entry_signal": False, "close": 23},
          {"code": "603211", "score": 60, "entry_signal": False, "close": 19},
          {"code": "603215", "score": 55, "entry_signal": False, "close": 15},
          {"code": "603220", "score": 20, "entry_signal": False, "close": 14}]
    screen=make_screen(rows, asof=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    (tmp_path/"data"/"screen.json").write_text(json.dumps(screen))
    codes, source=quote.load_codes()
    assert codes == ["603217", "603211", "603215"]
    assert len(codes) == 3
    assert "EOD screen" in source


def test_missing_signal_candidates_do_not_populate_with_random_tickers():
    assert quote.select_opportunity_codes(make_screen([])) == []
    assert quote.select_opportunity_codes({"schema":1,"rows":[
        {"code":"000001","score":0,"entry_signal":False,"close":10}
    ]}) == []
