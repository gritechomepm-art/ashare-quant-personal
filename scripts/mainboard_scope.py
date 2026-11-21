"""Single source of truth for SH/SZ A-share MAIN BOARD screening scope.

This predicate changes screening universe only. Historical evidence, individual
research/backtests, frozen entry logic, and already archived snapshots remain as-is.
"""
import re

SH_MAIN = ("600", "601", "603", "605")
SZ_MAIN = ("000", "001", "002", "003")


def is_mainboard_code(code):
    """Stock CODE only. Require six digits; exclude funds/indices/other boards."""
    code = str(code).strip()
    return bool(re.fullmatch(r"\d{6}", code) and
                code.startswith(SH_MAIN + SZ_MAIN))


def is_mainboard_symbol(symbol):
    """BaoStock exchange-qualified symbol prevents SH index '000xxx' confusion."""
    symbol = str(symbol).strip()
    if not re.fullmatch(r"(sh|sz)\.\d{6}", symbol):
        return False
    exchange, code = symbol.split(".")
    return code.startswith(SH_MAIN if exchange == "sh" else SZ_MAIN)
