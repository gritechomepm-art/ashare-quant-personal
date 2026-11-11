import sys
from pathlib import Path
import pandas as pd
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_quotes import normalize_market

def sample_market(count):
    return pd.DataFrame([
        {"代码": str(600000+i), "名称": "测试股票"+str(i),
         "最新价": 10.0+i/10000, "涨跌幅": 1.2, "今开": 10.0,
         "最高": 10.5, "最低": 9.8, "昨收": 9.9,
         "成交量": 123456, "成交额": 60_000_000}
        for i in range(count)
    ])

def test_full_market_snapshot_normalizes_all_codes():
    payload=normalize_market(sample_market(1500))
    assert payload["status"]=="ok"
    assert payload["count"]==1500
    assert payload["scope"]=="全市场A股快照"
    assert payload["quotes"]["600000"]["name"]=="测试股票0"
    assert payload["quotes"]["600000"]["price"]==10.0

def test_partial_market_snapshot_is_rejected():
    with pytest.raises(ValueError,match="Only"):
        normalize_market(sample_market(100))

def test_workflow_publishes_market_only_to_quote_feed():
    root=Path(__file__).resolve().parents[1]
    workflow=(root/".github/workflows/quotes.yml").read_text()
    assert "schedule:" in workflow and "quote-feed" in workflow
    assert "upload-pages-artifact@" not in workflow
    assert "deploy-pages@" not in workflow
    shell=(root/"index.html").read_text()
    assert "raw.githubusercontent.com" in shell
