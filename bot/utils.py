from __future__ import annotations

import re


def parse_units(text: str) -> float:
    patterns = [r'([0-9]+(?:\.[0-9]+)?)\s*[uU]\b', r'\+?([0-9]+(?:\.[0-9]+)?)\s*[uU]\b']
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return float(m.group(1))
    return 1.0


def parse_odds(text: str) -> int | None:
    m = re.search(r'([+-]\d{3,4})\b', text)
    return int(m.group(1)) if m else None


def american_profit(odds: int | None, units: float) -> float:
    if odds is None:
        return round(units, 2)
    if odds > 0:
        return round(units * (odds / 100), 2)
    return round(units * (100 / abs(odds)), 2)


def format_mode(units: float, unit_value: float, mode: str) -> str:
    if mode == 'dollars':
        return f"${units * unit_value:,.2f}"
    return f"{units:+.2f}U"
