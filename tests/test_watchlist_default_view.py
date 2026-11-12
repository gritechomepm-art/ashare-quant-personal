from pathlib import Path


def test_watchlist_defaults_to_score_ranked_candidates():
    html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    assert "let filter='all';" in html
    assert '<button class="filter active" id="filterAll" data-filter="all">候选股评分</button>' in html
    assert '<button class="filter" id="filterSignals" data-filter="signal">收盘确认信号</button>' in html


def test_confirmed_signal_filter_remains_separate_from_candidate_score_view():
    html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    assert "(filter==='all'||s.entry_signal===true||(s.entry_signal===undefined&&s.signal===true))" in html
    assert "当前筛选覆盖不完整，未覆盖股票不代表没有机会" in html
