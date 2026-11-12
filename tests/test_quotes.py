import sys
# Trigger a full-universe quote refresh after the BaoStock stock master is published.
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_quotes import chunked, market_symbol, parse_tencent_response


def sample_quote(code="000708", name="中信特钢", market="sz"):
    fields = [""] * 50
    fields[1] = name
    fields[2] = code
    fields[3] = "12.34"
    fields[4] = "12.00"
    fields[5] = "12.10"
    fields[6] = "12345"
    fields[30] = "20261111150000"
    fields[31] = "0.34"
    fields[32] = "2.83"
    fields[33] = "12.50"
    fields[34] = "12.05"
    return f'v_{market}{code}="' + "~".join(fields) + '";'


def test_market_symbol():
    assert market_symbol("000708") == "sz000708"
    assert market_symbol("002600") == "sz002600"
    assert market_symbol("600519") == "sh600519"
    assert market_symbol("430047") == "bj430047"
    assert market_symbol("920001") == "bj920001"


def test_parse_tencent_quotes():
    raw = sample_quote() + sample_quote("002600", "领益智造")
    result = parse_tencent_response(raw, ["000708", "002600"])
    assert result["000708"]["name"] == "中信特钢"
    assert result["000708"]["price"] == 12.34
    assert result["002600"]["change_pct"] == 2.83
    assert result["000708"]["quote_time"] == "2026-11-11T15:00:00+08:00"


def test_quote_batches_are_bounded():
    batches = list(chunked(list(range(251)), 100))
    assert [len(x) for x in batches] == [100, 100, 51]


def test_partial_quote_response_does_not_create_fake_rows():
    result = parse_tencent_response(sample_quote(), ["000708", "002600"])
    assert list(result) == ["000708"]


def test_quote_workflow_covers_market_sessions_and_close_snapshot():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/quotes.yml").read_text()
    # GitHub cron is UTC; 01:00-03:59 and 05:00-07:59 cover
    # Beijing morning/afternoon sessions, including the 15:07 close snapshot.
    assert "*/5 1-3,5-7 * * 1-5" in workflow
    assert "1 7 * * 1-5" in workflow
    assert "570 <= m <= 690" in workflow
    assert "780 <= m <= 915" in workflow
    assert "t.weekday() < 5" in workflow
    updater = (root / "scripts/update_quotes.py").read_text()
    assert "Stale Tencent snapshot during market session" in updater
    assert "fresh_quote_pct" in updater


def test_watchlist_defaults_to_score_ranked_candidates():
    root = Path(__file__).resolve().parents[1]
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "let filter='all';" in html
    assert '<button class="filter active" id="filterAll" data-filter="all">候选股评分</button>' in html
    assert '<button class="filter" id="filterSignals" data-filter="signal">收盘确认信号</button>' in html
    assert "(filter==='all'||s.entry_signal===true||(s.entry_signal===undefined&&s.signal===true))" in html
