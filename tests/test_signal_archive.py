"""Persistent close-signal history remains visible after candidate-pool changes."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))

from build_signal_tracker import build_tracker
from core import atomic_json


def test_archived_close_signal_retained_without_current_universe(tmp_path):
    root=tmp_path/"data"
    atomic_json(root/"screen.json",{
        "asof":"2026-11-13","eligible_count":1,"covered_count":0,
        "coverage_pct":0,"rows":[]
    })
    atomic_json(root/"stocks.json",{"stocks":{}})
    atomic_json(root/"signal_tracker.json",{
        "schema":1,"status":"ready","events":[{
            "id":"000001|2026-11-11","code":"000001","name":"测试股票",
            "signal_type":"CLOSE_CONFIRM","signal_date":"2026-11-11",
            "signal_close":10.0,"reference_price":10.0,
            "entry_status":"SKIPPED_NO_CHASE","outcomes":{},
            "forward_outcomes":{
                "1":{"status":"COMPLETE","observation_date":"2026-11-12",
                      "close":10.5,"return_pct":5.0},
                "2":{"status":"PENDING"},"3":{"status":"PENDING"},
            },
        }]
    })
    output=build_tracker(root)
    assert output["status"]=="ready"
    assert output["signal_count"]==1
    assert output["events"][0]["id"]=="CLOSE_CONFIRM|000001|2026-11-11"
    assert output["forward_metrics"]["CLOSE_CONFIRM"]["1"]["win_rate_pct"]==100.0
    assert output["forward_metrics"]["INTRADAY_WARNING"]["1"]["signal_count"]==0
