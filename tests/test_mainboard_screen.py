"""Main-board-only *future screening* and legacy screen display; research frozen."""
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

from mainboard_scope import is_mainboard_code, is_mainboard_symbol
from mainboard_page import patch_full_app_for_mainboard
from update_quotes import select_opportunity_codes


def test_main_board_codes_and_symbol_market_validation():
    included=("600000","601318","603259","605000","000001","001201","002532","003002")
    excluded=("300940","301039","688981","689009","920000","830001","430047",
              "870001","900000","200000","123456","60000","399001")
    for code in included:
        assert is_mainboard_code(code), code
    for code in excluded:
        assert not is_mainboard_code(code), code
    assert is_mainboard_symbol("sh.600000")
    assert is_mainboard_symbol("sh.605999")
    assert is_mainboard_symbol("sz.000001")
    assert is_mainboard_symbol("sz.002532")
    assert is_mainboard_symbol("sz.003002")
    for value in ["sz.600000","sh.000001","sh.688981","sh.689009",
                  "sz.300940","sz.301039","bj.920001","bj.830001",
                  "sh.900999","sz.200001"]:
        assert not is_mainboard_symbol(value), value


def test_still_separate_ranked_candidates_and_buy_signals():
    fake={
      "schema":1,
      "rows":[
         {"code":"300940","close":12,"score":100,"entry_signal":True},
         {"code":"688981","close":90,"score":100,"entry_signal":True},
         {"code":"920001","close":13,"score":100,"entry_signal":True},
         {"code":"600000","close":10,"score":70,"entry_signal":True},
         {"code":"002532","close":15,"score":65,"entry_signal":False},
         {"code":"003002","close":20,"score":40,"entry_signal":False},
      ]
    }
    assert select_opportunity_codes(fake)==["600000","002532"]
    assert select_opportunity_codes(fake,min_score=40,cap=20)==["600000","002532","003002"]


def test_actual_eod_paths_filter_before_scoring_and_keep_full_master():
    scheduled=(ROOT/"scripts/ingest_baostock.py").read_text(encoding="utf8")
    manual=(ROOT/"scripts/update_daily.py").read_text(encoding="utf8")
    quote=(ROOT/"scripts/update_quotes.py").read_text(encoding="utf8")
    assert "if is_mainboard_symbol(str(r.code))" in scheduled
    assert "for full, name in active:" in scheduled
    assert "board_scope" in scheduled
    assert "all_a_universe_count" in scheduled
    assert "normalize_stock_master(universe, asof)" in scheduled
    assert "if is_mainboard_code(c) and is_eligible(c,q['name'],q)" in manual
    assert "make_screen({'quotes':main_quotes},root,asof)" in manual
    assert "atomic_json(root/'quotes.json',fetched)" in manual
    assert "if not is_mainboard_code(code):" in quote


def test_full_app_output_only_filter_preserves_source_and_syntax(tmp_path):
    source=(ROOT/"index.html").read_text(encoding="utf8")
    before=subprocess.run(["git","hash-object","index.html"],cwd=ROOT,
          text=True,capture_output=True,check=True).stdout.strip()
    assert before=="56ea7031da1d3d82b42c768d06210403c446f7cf"
    app=patch_full_app_for_mainboard(source)
    assert "function isMainBoardRow(row)" in app
    assert "filter(s=>isMainBoardRow(s)&&(filter==='all'" in app
    assert "filter(row=>isMainBoardRow(row)&&rowInPriceRange(row))" in app
    assert "旧全市场覆盖率待主板重算" in app
    assert "沪深主板观察清单" in app
    assert "function isMainBoardRow" not in source
    scripts=re.findall(r"<script(?:\\s[^>]*)?>(.*?)</script>",app,re.S)
    assert scripts
    target=tmp_path/"mainboard_app.js"
    target.write_text("\n".join(scripts),encoding="utf8")
    result=subprocess.run(["node","--check",str(target)],cwd=ROOT,text=True,
                          capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr
    # Test the actually generated regex from the served app, not a duplicate.
    pos=app.index("function isMainBoardRow(row)")
    expr=app[pos:app.index("\nfunction rowsForScreen(){",pos)]
    node="const assert=require('node:assert/strict');"+expr+";assert.equal(isMainBoardRow({code:'002532'}),true);assert.equal(isMainBoardRow({code:'605001'}),true);assert.equal(isMainBoardRow({code:'300940'}),false);assert.equal(isMainBoardRow({code:'688981'}),false);assert.equal(isMainBoardRow({code:'920001'}),false);"
    result=subprocess.run(["node","-e",node],cwd=ROOT,text=True,
                          capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_mobile_home_only_shows_main_board_and_has_legacy_guard():
    mobile=(ROOT/"mobile.html").read_text(encoding="utf8")
    assert "仅沪深主板" in mobile
    assert "mainRows=data.rows.filter(row=>isMainBoard(row.code))" in mobile
    assert "stocks=mainRows.slice(0,100)" in mobile
    assert "data.board_scope==='SH_SZ_MAIN'" in mobile
    assert "旧全市场快照 · 主板覆盖率待下一次盘后重算" in mobile
    assert "旧版回测和随机对照包含其他板块" in mobile
    assert "不允许启用候选规则" in mobile


def test_production_build_mapping_and_frozen_evidence():
    source=(ROOT/"scripts/build_site.py").read_text(encoding="utf8")
    assert "patch_full_app_for_mainboard" in source
    assert "app_path.write_text(" in source
    assert "shutil.copy2(BASE/'mobile.html', site/'index.html')" in source
    assert "build_matched_control.js" in source
    assert "build_entry_quality_v22.js" in source
    assert "build_v2_study.js" in source
