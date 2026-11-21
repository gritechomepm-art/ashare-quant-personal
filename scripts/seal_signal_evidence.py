"""Create-only GitHub evidence ledger for actually published EOD screen signals.

A fingerprint/chain detects accidental rewriting, but Git branch history alone is
NOT WORM storage. Protect the separate ledger branch against force push/deletion
and retain run/commit IDs outside that branch for independent audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")
MIN_SESSION_DATE = "2026-11-23"  # No retrospective claims about November 20.
BRANCH_NAME = "signal-evidence-ledger"


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def validate_chain(directory):
    """Check every existing record. Abort on gaps in hash links or modified bytes."""
    paths = sorted(Path(directory).glob("*.json"))
    prev = None
    for p in paths:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", p.name):
            raise ValueError("Unexpected ledger file " + p.name)
        r = json.loads(p.read_text(encoding="utf-8"))
        fingerprint = r.get("record_sha256")
        unsigned = {k: v for k, v in r.items() if k != "record_sha256"}
        if fingerprint != digest(unsigned):
            raise ValueError("Evidence fingerprint mismatch " + p.name)
        if r.get("previous_record_sha256") != prev:
            raise ValueError("Broken evidence chain at " + p.name)
        if r.get("session_date") + ".json" != p.name:
            raise ValueError("Evidence date mismatch " + p.name)
        prev = fingerprint
    return prev, len(paths)


def make_evidence(screen_bytes, now, source_commit, previous_record_sha256):
    if now.tzinfo is None:
        raise ValueError("Capture timestamp must have timezone")
    captured = now.astimezone(timezone.utc)
    local = captured.astimezone(CST)
    screen = json.loads(screen_bytes)
    session = str(screen.get("asof", ""))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", session) or session < MIN_SESSION_DATE:
        raise ValueError("Historical session cannot be retrospectively sealed")
    close = datetime.combine(datetime.fromisoformat(session).date(), time(15, 0), CST)
    if not (close <= local <= close + timedelta(hours=24)):
        raise ValueError("Not a timely post-close capture; omit this session, do not backfill")
    raw_generated = str(screen.get("generated_at", ""))
    generated = datetime.fromisoformat(raw_generated)
    if generated.tzinfo is None or not (close <= generated.astimezone(CST) <= local):
        raise ValueError("EOD generation time not verified relative to session close")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("A complete source Git commit SHA is required")
    if not isinstance(screen.get("rows"), list):
        raise ValueError("No usable EOD rows")
    rows, seen = [], set()
    for s in screen["rows"]:
        if s.get("entry_signal") is not True:
            continue
        code = str(s.get("code", ""))
        if not re.fullmatch(r"\d{6}", code) or code in seen or str(s.get("asof")) != session:
            raise ValueError("Invalid, duplicate or stale confirmed signal " + code)
        seen.add(code)
        rows.append({
            "code": code, "name": str(s.get("name", "")),
            "signal_date": session,
            "score": s.get("score"),
            "signal_close": s.get("close"), "atr14": s.get("atr14"),
            "buy_low": s.get("buy_low"), "buy_high": s.get("buy_high"),
            "entry_status": s.get("entry_status"),
            "ma5": s.get("ma5"), "ma10": s.get("ma10"), "rsi14": s.get("rsi14"),
            "volume_ratio": s.get("volume_ratio")
        })
    rows.sort(key=lambda r: r["code"])
    record = {
        "schema": 1, "kind": "AShare verified close observation / not actual trade",
        "session_date": session,
        "source_screen_generated_at": raw_generated,
        "source_screen_sha256": hashlib.sha256(screen_bytes).hexdigest(),
        "source_main_commit": source_commit,
        "sealed_at_utc": captured.isoformat(timespec="seconds"),
        "sealed_at_beijing": local.isoformat(timespec="seconds"),
        "coverage": {
            "universe_count": screen.get("universe_count"),
            "eligible_count": screen.get("eligible_count"),
            "covered_count": screen.get("covered_count"),
            "source_screen_status": screen.get("status"),
            "screen_row_count": len(screen["rows"])
        },
        "confirmed_signal_count": len(rows), "confirmed_signals": rows,
        "signal_content_sha256": digest(rows),
        "previous_record_sha256": previous_record_sha256,
        "provenance_note": "Recorded only after actual EOD data was committed. This is the first verifiable seal time, not a claim of timestamped publication at 15:00."
    }
    record["record_sha256"] = digest(record)
    return record


def capture(screen_path, ledger_dir, now, source_commit):
    ledger = Path(ledger_dir)
    ledger.mkdir(parents=True, exist_ok=True)
    prev, count = validate_chain(ledger)
    raw = Path(screen_path).read_bytes()
    session = str(json.loads(raw).get("asof", ""))
    dest = ledger / (session + ".json")
    if dest.exists():
        old = json.loads(dest.read_text(encoding="utf-8"))
        if hashlib.sha256(raw).hexdigest() != old["source_screen_sha256"]:
            raise ValueError("Sealed day has changed since its first capture; refusing overwrite")
        return {"status": "UNCHANGED", "session_date": session,
                "record_sha256": old["record_sha256"], "path": str(dest)}
    record = make_evidence(raw, now, source_commit, prev)
    # Exclusive create: never overwrite an existing date, even across retries.
    with dest.open("x", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return {"status": "CREATED", "session_date": session,
            "sealed_at_utc": record["sealed_at_utc"],
            "confirmed_signals": record["confirmed_signal_count"],
            "record_sha256": record["record_sha256"],
            "chain_index": count + 1, "path": str(dest)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--screen", required=True)
    p.add_argument("--ledger-dir", required=True)
    p.add_argument("--source-commit", required=True)
    a = p.parse_args()
    result = capture(a.screen, a.ledger_dir, datetime.now(timezone.utc), a.source_commit)
    print(json.dumps(result, ensure_ascii=False))
    out = Path(a.ledger_dir) / "capture-result.json"
    # The result is runtime metadata only; never commit this mutable file.
    if not out.parent.exists():
        raise RuntimeError("Missing evidence dir")


if __name__ == "__main__":
    main()
