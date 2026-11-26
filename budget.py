"""
Daily budget guard for the OpenRouter free tier.

A free-tier OpenRouter key gets a fixed number of free-model requests per
day (50 at the time of writing). The tournament workflow runs every 20
minutes, so without a guard the bot could start a question, run out of
requests half-way and post nothing useful.

Before each run, main.py asks OpenRouter how many free requests are left
today and only takes as many new questions as fit in that budget. The
remaining questions are picked up by a later run (the next day at worst).

If the key is NOT on the free tier (e.g. Metaculus-granted credits were
added), there is no daily request cap and the guard does not limit anything.
"""
from __future__ import annotations

import logging
import os

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


def max_questions_this_run() -> int | None:
    """How many new questions this run may forecast (None = no limit)."""
    remaining = free_requests_remaining()
    if remaining is None:
        return None
    allowed = max(0, (remaining - DAILY_RESERVE) // CALLS_PER_QUESTION)
    logger.info(
        f"OpenRouter free requests left today: {remaining} -> up to {allowed} new question(s) this run"
    )
    return allowed
