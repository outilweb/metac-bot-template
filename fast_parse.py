"""
Read the final answer out of the model's text with plain pattern matching,
instead of spending extra LLM calls on it.

The forecasting prompts already ask for a fixed final format, for example
"Probability: 35%" or "Percentile 10: 1200". When the model follows that
format (the usual case), these functions extract the answer for free.
When they cannot, they return None and main.py falls back to the
template's LLM parser (structure_output), so nothing is lost.

Each function reads the LAST matching answer in the text, because models
sometimes mention the format or a draft number earlier in their reasoning.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from forecasting_tools import DatePercentile, Percentile, PredictedOption, PredictedOptionList

_NUM = r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+"
# Words that mean the number would need a unit conversion: leave those to the LLM parser.
_SCALE_WORDS = re.compile(r"\b(thousand|million|billion|trillion|mn|bn|tn|k|m|b)\b", re.I)


def _clean(text: str) -> str:
    # Remove markdown emphasis so "**Probability:** 35%" still matches.
    return text.replace("**", "").replace("__", "")


def binary(text: str) -> float | None:
    matches = re.findall(r"Probability\s*:\s*(" + _NUM + r")\s*%", _clean(text), re.I)
    if not matches:
        return None
    value = float(matches[-1].replace(",", "")) / 100
    if not 0 <= value <= 1:
        return None
    return max(0.01, min(0.99, value))


def multiple_choice(text: str, options: list[str]) -> PredictedOptionList | None:
    text = _clean(text)
    probs: dict[str, float] = {}
    for option in options:
        pattern = r"(?:^|\n)\s*[-*]?\s*(?:Option[_\s]*)?" + re.escape(option) + r"\s*:\s*(" + _NUM + r")\s*%?"
        found = re.findall(pattern, text, re.I)
        if not found:
            return None
        probs[option] = float(found[-1].replace(",", ""))
    total = sum(probs.values())
    if total <= 0:
        return None
    # Accept answers written as 0-100 or as 0-1; normalise to sum exactly 1.
    return PredictedOptionList(
        predicted_options=[
            PredictedOption(option_name=o, probability=p / total) for o, p in probs.items()
        ]
    )


def _percentile_lines(text: str) -> list[tuple[int, str]]:
    lines = re.findall(r"Percentile\s*(\d{1,2})\s*:\s*([^\n]+)", _clean(text), re.I)
    # Keep only the last block: walk backwards collecting each percentile once.
    seen: dict[int, str] = {}
    for p, raw in reversed(lines):
        p = int(p)
        if p not in seen:
            seen[p] = raw.strip()
    return sorted(seen.items())


def numeric(text: str) -> list[Percentile] | None:
    out = []
    for p, raw in _percentile_lines(text):
        raw = raw.strip("\"' ")
        if _SCALE_WORDS.search(raw) or re.search(r"\de[+-]?\d", raw, re.I):
            return None  # needs unit / scientific-notation handling
        m = re.match(r"[$€£]?\s*(" + _NUM + r")", raw)
        if not m:
            return None
        out.append(Percentile(percentile=p / 100, value=float(m.group(1).replace(",", ""))))
    if len(out) < 4:
        return None
    values = [x.value for x in out]
    if any(b < a for a, b in zip(values, values[1:])):
        return None
    return out


def date(text: str) -> list[DatePercentile] | None:
    out = []
    for p, raw in _percentile_lines(text):
        m = re.search(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?)Z?)?", raw)
        if not m:
            return None
        stamp = m.group(1) + ("T" + m.group(2) if m.group(2) else "T00:00")
        try:
            value = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        out.append(DatePercentile(percentile=p / 100, value=value))
    if len(out) < 4:
        return None
    values = [x.value for x in out]
    if any(b < a for a, b in zip(values, values[1:])):
        return None
    return out
