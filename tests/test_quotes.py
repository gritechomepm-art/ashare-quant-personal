import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_quotes import market_symbol, parse_tencent_response


def sample_quote(code="000708", name="中信特钢", market="sz"):
    fields = [""] * 50
    fields[0] = "51"
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
    fields[37] = "123456.78"
    return f'v_{market}{code}="' + "~".join(fields) + '";'


def test_market_symbol():
    assert market_symbol("000708") == "sz000708"
    assert market_symbol("002600") == "sz002600"
    assert market_symbol("600519") == "sh600519"


def test_parse_two_tencent_quotes():
    raw = sample_quote() + sample_quote("002600", "领益智造")
    result = parse_tencent_response(raw, ["000708", "002600"])
    assert result["000708"]["name"] == "中信特钢"
    assert result["000708"]["price"] == 12.34
    assert result["002600"]["change_pct"] == 2.83
    assert result["000708"]["quote_time"] == "2026-11-11T15:00:00+08:00"


def test_reject_partial_response():
    import pytest
    with pytest.raises(ValueError, match="missing symbols"):
        parse_tencent_response(sample_quote(), ["000708", "002600"])
