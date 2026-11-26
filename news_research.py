"""
Free news research for the bot: no API key, no account, no cost.

How it works, for each question:
  1. One LLM call turns the question into a few short news search queries.
  2. Each query is sent to the public Google News RSS search feed.
  3. Headlines are de-duplicated, sorted newest first and returned as plain
     text, which the forecasting prompt then reads as "research".

Only one LLM call is spent per question, which matters on the OpenRouter
free tier (50 free-model requests per day).

If anything fails (network error, feed blocked, bad LLM output), the
function falls back gracefully and never crashes the bot: worst case it
returns an explanation that no news could be found.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from forecasting_tools import GeneralLlm, MetaculusQuestion

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
MAX_QUERIES = 3
MAX_HEADLINES = 25
USER_AGENT = "Mozilla/5.0 (compatible; metaculus-forecasting-bot)"


def _query_prompt(question: MetaculusQuestion) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        "You help a forecaster find recent news about a question.\n"
        f"Today is {today}.\n\n"
        f"Question: {question.question_text}\n\n"
        f"Resolution criteria: {question.resolution_criteria}\n\n"
        f"Write {MAX_QUERIES} short news search queries (2 to 6 words each, in English) "
        "that would surface the most recent and relevant news for this question. "
        "Make them different from each other (main topic, key actor, key number or event).\n"
        'Answer with a JSON list of strings only, for example: ["query one", "query two", "query three"]'
    )


def _parse_queries(text: str, fallback: str) -> list[str]:
    match = re.search(r"\[.*?\]", text or "", re.DOTALL)
    if match:
        try:
            items = json.loads(match.group(0))
            queries = [str(q).strip() for q in items if str(q).strip()]
            if queries:
                return queries[:MAX_QUERIES]
        except json.JSONDecodeError:
            pass
    # Fallback: the question title itself, without punctuation.
    return [re.sub(r"[^\w\s-]", " ", fallback)[:120]]


def _parse_rss(xml_text: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        pub = item.findtext("pubDate") or ""
        try:
            date = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            date = None
        if title:
            # Google News titles end with " - Source"; keep the source separately.
            if source and title.endswith(f" - {source}"):
                title = title[: -len(f" - {source}")]
            items.append({"title": title, "source": source, "date": date})
    return items


async def _search(client: httpx.AsyncClient, query: str) -> list[dict]:
    url = GOOGLE_NEWS_RSS.format(q=urllib.parse.quote_plus(query))
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return _parse_rss(resp.text)
    except Exception as e:  # network errors must never break a forecast
        logger.warning(f"News search failed for '{query}': {e}")
        return []


async def gather_news(question: MetaculusQuestion, llm: GeneralLlm) -> str:
    try:
        raw = await llm.invoke(_query_prompt(question))
    except Exception as e:
        logger.warning(f"Query generation failed, using question title: {e}")
        raw = ""
    queries = _parse_queries(raw, question.question_text)

    async with httpx.AsyncClient(
        timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        results = await asyncio.gather(*(_search(client, q) for q in queries))

    seen, headlines = set(), []
    for batch in results:
        for h in batch:
            key = h["title"].lower()
            if key not in seen:
                seen.add(key)
                headlines.append(h)
    oldest = datetime(1970, 1, 1, tzinfo=timezone.utc)
    headlines.sort(key=lambda h: h["date"] or oldest, reverse=True)
    headlines = headlines[:MAX_HEADLINES]

    header = f"News search queries used: {', '.join(queries)}\n"
    if not headlines:
        return header + "No recent news headlines were found. Rely on background knowledge and base rates."

    lines = [
        header,
        "Most recent news headlines found (Google News, newest first). "
        "Headlines only: treat them as signals, not as full articles.",
    ]
    for h in headlines:
        day = h["date"].strftime("%Y-%m-%d") if h["date"] else "date unknown"
        src = f" ({h['source']})" if h["source"] else ""
        lines.append(f"- [{day}] {h['title']}{src}")
    return "\n".join(lines)
