"""Approved mobile preview becomes production homepage without altering frozen strategy."""
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def test_frozen_full_app_is_unchanged_and_published_separately():
    # Full original application (same origin, same localStorage) is not rewritten.
    source=subprocess.run(["git","hash-object","index.html"],cwd=ROOT,
                          text=True,capture_output=True,check=True).stdout.strip()
    assert source=="56ea7031da1d3d82b42c768d06210403c446f7cf"
    src=(ROOT/"scripts/build_site.py").read_text(encoding="utf-8")
    assert "shutil.copy2(BASE/'index.html', site/'app.html')" in src
    assert "shutil.copy2(BASE/'mobile.html', site/'index.html')" in src
    assert "build_v2_study.js" in src
    assert "build_entry_quality_v22.js" in src
    assert "build_matched_control.js" in src


def test_mobile_homepage_is_data_driven_and_links_original_features():
    html=(ROOT/"mobile.html").read_text(encoding="utf-8")
    assert "手机首页" in html
    assert "原策略不变" in html
    assert "不允许启用候选规则" in html
    assert 'href="./app.html"' in html
    assert "./data/screen.json" in html
    assert "./data/evidence_control.json" in html
    assert "./data/backtest_v2.json" in html
    assert "tracker/index.json" not in html or "signal_tracker.json" not in html
    assert "ref=signal-evidence-ledger" in html
    assert "不构成独立前瞻验证" in html
    assert "按股票聚类" in html
    assert "评分仅排序用" in html
    assert "不能补写" in html
    assert "const stocks=[" not in html
    assert "let stocks=[]" in html
    assert "loadLatestResearch()" in html
    assert 'id="signalCount"' in html
    assert 'id="coveredCount"' in html
    assert 'id="controlDifference"' in html
    assert 'id="ledgerStatus"' in html
    assert 'id="historyEligible"' in html
    assert 'id="searchStock"' in html
    assert "价格门槛" in html
    assert 'name="viewport"' in html


def test_mobile_javascript_syntax_and_render_element_references(tmp_path):
    html=(ROOT/"mobile.html").read_text(encoding="utf-8")
    scripts=re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>',html,re.S)
    assert len(scripts)==1
    js=tmp_path/"mobile.js"
    js.write_text("\n".join(scripts),encoding="utf-8")
    p=subprocess.run(["node","--check",str(js)],text=True,capture_output=True,timeout=15)
    assert p.returncode==0,p.stdout+"\n"+p.stderr
    for key in ["signalCount","coveredCount","eligibleCount","coverageText",
                "screenDateLine","lastScreenDate","controlPairs","signalAvg","controlAvg",
                "controlDifference","controlClusterBounds","controlClusterLabel",
                "historyEligible","masterCount","missingHist","currentST",
                "ledgerStatus","ledgerDescription","sealedDates","mobileStatus"]:
        assert f'id="{key}"' in html,key
