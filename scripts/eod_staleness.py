"""EOD scheduler recovery decision; does not touch market data or strategy."""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CST=ZoneInfo("Asia/Shanghai")


def after_close_stale(screen, now):
    local=now.astimezone(CST)
    if local.weekday() >= 5 or (local.hour,local.minute) < (17,30):
        return False
    asof=str(screen.get("asof",""))
    # Only a currently completed day can trigger a recovery; no future date.
    return asof < local.date().isoformat() or screen.get("board_scope") != "SH_SZ_MAIN"


def validate_mainboard(screen):
    if screen.get("schema")!=1 or screen.get("board_scope")!="SH_SZ_MAIN":
        raise ValueError("Missing actual SH_SZ_MAIN screen")
    if (not isinstance(screen.get("rows"),list)
        or not isinstance(screen.get("asof"),str)
        or not isinstance(screen.get("eligible_count"),int)
        or not isinstance(screen.get("covered_count"),int)
        or screen["eligible_count"]<1000
        or screen["covered_count"]<1):
        raise ValueError("No usable verified mainboard EOD coverage")
    return True


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--screen",required=True)
    p.add_argument("--require-today-after-close",action="store_true")
    p.add_argument("--require-mainboard",action="store_true")
    p.add_argument("--now",default=None,help="ISO datetime for reproducible testing")
    a=p.parse_args()
    now=datetime.fromisoformat(a.now) if a.now else datetime.now(CST)
    doc=json.loads(Path(a.screen).read_text(encoding="utf8"))
    if a.require_mainboard:
        validate_mainboard(doc)
        print("Verified mainboard EOD:",doc["asof"],doc["covered_count"],"/",doc["eligible_count"])
    if a.require_today_after_close:
        stale=after_close_stale(doc,now)
        print("After-close EOD recovery required:",stale)
        if not stale:
            raise SystemExit(1)

if __name__=="__main__":
    main()
