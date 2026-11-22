"""Read-only preflight for the 5-minute EOD-screened main-board quote monitor.

An empty / legacy screen is an expected *no-op*, not a provider outage.
Never substitute a full-market pool. This script does not create market data.
Malformed EOD input remains an error.
"""
import argparse
import json
from pathlib import Path

from update_quotes import select_opportunity_codes


def quote_readiness(screen):
    if not isinstance(screen, dict) or screen.get("schema") != 1:
        raise ValueError("Invalid EOD screen schema; cannot certify main-board pool")
    if not isinstance(screen.get("rows"), list):
        raise ValueError("Invalid EOD screen rows; cannot certify main-board pool")
    if screen.get("board_scope") != "SH_SZ_MAIN":
        return {"can_fetch": False, "status": "WAITING_MAINBOARD_EOD",
                "asof": str(screen.get("asof") or "unknown"),
                "candidates": 0,
                "reason": "Existing EOD snapshot has no certified SH_SZ_MAIN universe; no full-market fallback."}
    codes = select_opportunity_codes(screen)
    if not codes:
        return {"can_fetch": False, "status": "NO_ELIGIBLE_MAINBOARD_CANDIDATES",
                "asof": str(screen.get("asof") or "unknown"),
                "candidates": 0,
                "reason": "No screened main-board stock meets current (unchanged) opportunity rules."}
    return {"can_fetch": True, "status": "READY", "asof": screen.get("asof"),
            "candidates": len(codes),
            "reason": "Only the existing EOD-screened main-board pool may be refreshed."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen", default="data/screen.json")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--github-summary", default="")
    args = parser.parse_args()
    screen = json.loads(Path(args.screen).read_text(encoding="utf-8"))
    decision = quote_readiness(screen)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as f:
            f.write(f"fetch={'true' if decision['can_fetch'] else 'false'}\n")
            f.write("status="+decision["status"]+"\n")
    if args.github_summary:
        with Path(args.github_summary).open("a", encoding="utf-8") as f:
            f.write("## Main-board quote refresh preflight\n")
            f.write("- Outcome: **"+decision["status"]+"**\n")
            f.write("- EOD date: "+str(decision["asof"])+"\n")
            f.write("- Eligible codes: "+str(decision["candidates"])+"\n")
            f.write("- Safety: "+decision["reason"]+"\n")
            if not decision["can_fetch"]:
                f.write("- No Tencent quote request, no quote-feed push, and no market-wide fallback.\n")


if __name__ == "__main__":
    main()
