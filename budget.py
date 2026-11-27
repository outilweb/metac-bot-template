"""
Daily budget guard for the OpenRouter free tier.

A free-tier OpenRouter key gets a fixed number of free-model requests per
day (50 at the time of writing). The tournament workflow runs about every 25
minutes, so without a guard the bot could start a question, run out of
requests half-way and post nothing useful.

Before each run, main.py asks OpenRouter how many free requests are left
today and only takes as many new questions as fit in that budget
(pick_within_budget). Questions that close within hours go first; the
others wait for a later run (the next day at worst).

If the key is NOT on the free tier (e.g. Metaculus-granted credits were
added), there is no daily request cap and the guard does not limit anything.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

# LLM calls per question with the current settings: 1 (news search
# queries) + 3 (predictions). One extra is kept for the rare case where the
# answer has to go through the LLM parser.
CALLS_PER_QUESTION = 5
# Requests kept aside each day (manual tests, retries after a timeout).
DAILY_RESERVE = 2


def free_requests_remaining() -> int | None:
    """Free-model requests left today, or None if there is no daily cap / unknown."""
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        resp = httpx.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
    except Exception as e:
        logger.warning(f"Could not read OpenRouter budget, assuming a small one: {e}")
        return CALLS_PER_QUESTION + DAILY_RESERVE  # be careful: allow one question
    if not data.get("is_free_tier"):
        return None
    daily = data.get("free_model_daily_requests") or {}
    remaining = daily.get("remaining")
    return int(remaining) if remaining is not None else None


# FutureEval (the bot tournament with the largest prize) opens short
# questions that can be forecast for only 3 hours, starting at a 3-hour slot
# (00:00, 03:00, ... 21:00 UTC). Long-horizon questions (e.g. Animal Futures,
# closing months from now) can be done any day. So, during the day, requests
# are kept for the FutureEval slots still to come before the daily reset
# (00:00 UTC), and long-horizon questions only get what is left over.
SHORT_WINDOW = timedelta(hours=6)  # closes this soon -> must be done now
SLOT_HOURS = 3
QUESTIONS_PER_SLOT = 1


def slots_left_today(now: datetime) -> int:
    """FutureEval slots that start after `now` and before the next 00:00 UTC."""
    now = now.astimezone(timezone.utc)
    return sum(1 for hour in range(0, 24, SLOT_HOURS) if hour > now.hour)


def pick_within_budget(
    questions: list,
    remaining: int | None,
    reserve_for_short_questions: bool,
    now: datetime | None = None,
) -> list:
    """
    Choose which of `questions` (sorted soonest-closing first) to forecast now.

    Questions closing within SHORT_WINDOW come first. Others only use the
    requests not needed by the FutureEval slots left today (when
    reserve_for_short_questions is True). `remaining` None = no daily cap.
    """
    if remaining is None:
        return list(questions)
    now = now or datetime.now(timezone.utc)

    def close_time(q) -> datetime:
        close = q.close_time
        if close is None:
            return datetime.max.replace(tzinfo=timezone.utc)
        return close if close.tzinfo else close.replace(tzinfo=timezone.utc)

    def closes_soon(q) -> bool:
        return q.close_time is not None and close_time(q) - now <= SHORT_WINDOW

    short = [q for q in questions if closes_soon(q)]
    long_ = [q for q in questions if not closes_soon(q)]

    usable = max(0, remaining - DAILY_RESERVE)
    n_short = min(len(short), usable // CALLS_PER_QUESTION)
    usable -= n_short * CALLS_PER_QUESTION

    kept = 0
    if reserve_for_short_questions:
        kept = slots_left_today(now) * QUESTIONS_PER_SLOT * CALLS_PER_QUESTION
    n_long = min(len(long_), max(0, usable - kept) // CALLS_PER_QUESTION)

    logger.info(
        f"OpenRouter free requests left today: {remaining}. "
        f"Closing within {SHORT_WINDOW.total_seconds() / 3600:.0f}h: {n_short}/{len(short)} taken. "
        f"Longer questions: {n_long}/{len(long_)} taken "
        f"({kept} requests kept for the FutureEval slots left today)."
    )
    return sorted(short[:n_short] + long_[:n_long], key=close_time)
