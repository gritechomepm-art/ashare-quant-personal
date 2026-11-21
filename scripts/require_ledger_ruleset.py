"""Fail closed unless an active GitHub ruleset blocks deletion and force push.

The ruleset is an independent repository setting. This integration has read-only
access to it; only the repository administrator can enable it.
"""
from __future__ import annotations
import json
import os
from urllib.request import Request, urlopen

REQUIRED_REF = "refs/heads/signal-evidence-ledger"


def check_details(details):
    if details.get("enforcement") != "active" or details.get("target") != "branch":
        return set()
    conditions = details.get("conditions") or {}
    refs = (conditions.get("ref_name") or {}).get("include") or []
    if REQUIRED_REF not in refs:
        return set()
    if details.get("bypass_actors"):
        raise ValueError("Evidence ruleset allows bypass actors, including possible administrators")
    return {rule.get("type") for rule in details.get("rules", [])}


def require_rulesets(fetch):
    items = fetch("")
    protections = set()
    for rule in items:
        if rule.get("enforcement") != "active" or rule.get("target") != "branch":
            continue
        details = fetch("/" + str(rule["id"]))
        protections.update(check_details(details))
    missing = {"non_fast_forward", "deletion"} - protections
    if missing:
        raise RuntimeError("Evidence writes blocked: missing active no-force/no-delete GitHub ruleset for "+REQUIRED_REF+"; missing "+",".join(sorted(missing)))
    return True


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    base = "https://api.github.com/repos/" + repo + "/rulesets"
    def fetch(suffix):
        req=Request(base+suffix,headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer "+token,
            "X-GitHub-Api-Version": "2022-11-28"
        })
        with urlopen(req, timeout=15) as r:
            return json.load(r)
    require_rulesets(fetch)
    print("Evidence branch ruleset verified (no-force, no-delete; no bypass actors)")

if __name__ == "__main__":
    main()
