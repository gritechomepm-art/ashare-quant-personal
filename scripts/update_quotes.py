"""Fetch a validated full-market A-share snapshot through AKShare/Eastmoney."""
import argparse
from pathlib import Path
import akshare as ak
from core import ROOT, atomic_json, norm_spot

def normalize_market(frame, fetched=None):
    payload = norm_spot(frame, fetched)
    payload["source"] = "AKShare stock_zh_a_spot_em / 东方财富公开A股行情"
    payload["scope"] = "全市场A股快照"
    payload["warning"] = "采集时间不是交易所逐笔时间；数据可能延迟、限流或中断。仅发布通过全市场完整性校验的快照。"
    return payload

def fetch_market():
    frame = ak.stock_zh_a_spot_em()
    if frame is None or frame.empty:
        raise RuntimeError("Eastmoney returned an empty A-share snapshot")
    return normalize_market(frame)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "quotes.json"))
    args = parser.parse_args()
    payload = fetch_market()
    atomic_json(Path(args.output), payload)
    print(f"Full-market quote snapshot: source={payload['source']}, count={payload['count']}, fetched_at={payload['fetched_at']}")
    return payload

if __name__ == "__main__":
    main()
