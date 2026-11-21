import sys
# Trigger a full-universe quote refresh after the BaoStock stock master is published.
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_quotes import chunked, market_symbol, parse_tencent_response, verify_quote_source_day
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest


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
    # Beijing morning/afternoon sessions, including the 15:11 close catch-up.
    assert "3-58/5 1-3,5-7 * * 1-5" in workflow
    assert "11 7 * * 1-5" in workflow
    assert "workflow_run:" in workflow
    assert "after-hours catch-up" in workflow
    assert "570 <= m <= 690" in workflow
    assert "780 <= m <= 900" in workflow
    assert "t.weekday() < 5" in workflow
    assert 'event != "workflow_run" or upstream == "success"' in workflow
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


def test_late_friday_quote_can_be_published_over_weekend_without_faking_collection_time():
    now = datetime(2026, 11, 15, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    stamp = "2026-11-13T15:00:02+08:00"
    assert verify_quote_source_day(stamp, "2026-11-13", now) == stamp


def test_quote_older_than_latest_eod_screen_cannot_replace_feed():
    now = datetime(2026, 11, 15, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    with pytest.raises(RuntimeError, match="older than EOD screen"):
        verify_quote_source_day("2026-11-12T13:33:51+08:00", "2026-11-13", now)


def test_quote_source_future_or_far_in_past_is_rejected():
    now = datetime(2026, 11, 15, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    with pytest.raises(RuntimeError, match="out of bounds"):
        verify_quote_source_day("2026-11-16T11:00:00+08:00", "2026-11-13", now)
    with pytest.raises(RuntimeError, match="out of bounds"):
        verify_quote_source_day("2026-11-08T15:00:00+08:00", "2026-11-08", now)


def test_eod_scheduler_has_off_peak_backup_slot():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/baostock-backfill.yml").read_text()
    assert "37 9 * * 1-5" in workflow
    assert "17 10 * * 1-5" in workflow


def test_frontend_does_not_redownload_large_eod_tracker_every_minute():
    root = Path(__file__).resolve().parents[1]
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "EOD_REFRESH_MS=10*60*1000" in html
    assert "needEodFetch?loadTrackerIndex():Promise.resolve(null)" in html
    assert "tracker/index.json" in html and "tracker/recent30.json" in html
    assert "needEodFetch?fetchJSON('./data/signal_tracker.json')" not in html
    assert "' · 日线筛选 '+(screen.asof||'未更新')" in html
    assert "'历史行情（非实时；禁用盘中预警）'" in html
