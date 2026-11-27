"""
Find, at every run, all Metaculus tournaments where this bot can win money.

The Metaculus API lists every tournament with two fields that settle it:
  - prize_pool             -> is there money at all?
  - bot_leaderboard_status -> "bots_only" (bot tournament) or "include"
                              (humans and bots ranked together, bots can win);
                              "exclude_and_show" / "exclude_and_hide" mean
                              bots are not eligible for prizes.

So new seasons (e.g. the January FutureEval season), each new quarterly
Market Pulse, or any new prize tournament open to bots are joined
automatically, with no code change.

Rules for mixed tournaments ("include"): a person may enter only once,
either as a bot or as a human. The owner of this bot does not forecast
those tournaments by hand.

MiniBench is excluded unless INCLUDE_MINIBENCH is switched on in main.py.
If the API call fails, the caller falls back to a fixed list.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://www.metaculus.com/api/projects/tournaments/"
BOT_PRIZE_STATUSES = {"bots_only", "include"}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def discover_bot_prize_tournaments(include_minibench: bool = False) -> list[int] | None:
    """Ids of ongoing prize tournaments open to bots, or None if the API failed."""
    token = os.getenv("METACULUS_TOKEN")
    try:
        resp = httpx.get(API_URL, headers={"Authorization": f"Token {token}"}, timeout=30)
        resp.raise_for_status()
        items = resp.json()
        if isinstance(items, dict):
            items = items.get("results", [])
    except Exception as e:
        logger.warning(f"Could not list Metaculus tournaments: {e}")
        return None

    now = datetime.now(timezone.utc)
    found = []
    for t in items:
        try:
            prize = float(t.get("prize_pool") or 0)
        except (TypeError, ValueError):
            prize = 0
        name = t.get("name") or ""
        end = _parse_date(t.get("forecasting_end_date"))
        if not t.get("is_ongoing") or prize <= 0:
            continue
        if t.get("bot_leaderboard_status") not in BOT_PRIZE_STATUSES:
            continue
        if end is not None and end < now:
            continue
        if "minibench" in name.lower() and not include_minibench:
            continue
        found.append(t)

    for t in found:
        logger.info(
            f"Prize tournament open to bots: {t.get('name')} (id {t.get('id')}, "
            f"${float(t.get('prize_pool')):,.0f}, {t.get('bot_leaderboard_status')})"
        )
    return [t["id"] for t in found]
