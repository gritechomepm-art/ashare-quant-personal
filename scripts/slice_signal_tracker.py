"""Derive small, date-sliced public tracker files without touching its EOD cache.

The 20+ MB source data/signal_tracker.json remains unmodified for historical
metrics and portfolio calculations. Web clients fetch a small manifest + last
30 calendar days and request older date partitions only on demand.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def split_tracker(source: Path, destination: Path):
    document = json.loads(Path(source).read_text(encoding="utf-8"))
    if int(document.get("schema", 0)) != 1:
        raise ValueError("Unexpected tracker schema")
    asof = date.fromisoformat(document["asof"])
    recent_start = (asof - timedelta(days=29)).isoformat()
    events = document.get("events", [])
    if not isinstance(events, list):
        raise ValueError("Malformed tracker events")
    recent, months = [], {}
    for e in events:
        session = str(e.get("signal_date", ""))[:10]
        date.fromisoformat(session)
        if session > document["asof"]:
            raise ValueError("Future event cannot be in published tracker")
        if session >= recent_start:
            recent.append(e)
        else:
            months.setdefault(session[:7], []).append(e)
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    recent_bytes = encode({"schema": 1, "start": recent_start,
                           "through": document["asof"], "events": recent})
    (dest / "recent30.json").write_bytes(recent_bytes)
    archives = []
    for month, values in sorted(months.items()):
        raw = encode({"schema": 1, "month": month, "events": values})
        (dest / (month + ".json")).write_bytes(raw)
        archives.append({"month": month, "file": month + ".json", "count": len(values),
                         "sha256": hashlib.sha256(raw).hexdigest(),
                         "bytes": len(raw)})
    stats = {k: v for k, v in document.items() if k != "events"}
    stats["events"] = []
    stats["mobile_index"] = {
        "schema": 1, "recent_file": "recent30.json",
        "recent_window": {"start": recent_start, "through": document["asof"],
                          "count": len(recent), "bytes": len(recent_bytes)},
        "archives": archives, "archive_months": len(archives),
        "partition_rule": "30 calendar days from tracker asof; older events grouped by signal_date YYYY-MM",
        "source_cache_unchanged": True
    }
    (dest / "index.json").write_bytes(encode(stats))
    return {"latest": len(recent), "archives": len(archives),
            "events_original": len(events), "index_bytes": (dest/"index.json").stat().st_size,
            "recent_bytes": len(recent_bytes)}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    a = parser.parse_args()
    print("Tracker mobile partitions:", split_tracker(Path(a.source), Path(a.output)))


if __name__ == "__main__":
    main()
