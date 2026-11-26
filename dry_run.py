"""
Dry run: forecast a few questions from the Metaculus bot-testing-area
WITHOUT publishing anything, using a free OpenRouter model.

Why this file exists: the template's default models are paid OpenRouter
models (gpt-4o, gpt-4o-search-preview), and an OpenRouter free-tier key only
gets 50 free-model requests per day. This script keeps a test within that
budget: few questions, few predictions per question, one free model.

Usage:
    uv run python dry_run.py              # 2 questions
    uv run python dry_run.py --n 1        # 1 question
"""
import argparse
import asyncio
import logging

from bot_helpers import check_environment
from main import FallTemplateBot2026
from forecasting_tools import GeneralLlm, MetaculusClient

FREE_MODEL = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"


def build_bot(predictions: int, no_news: bool = False) -> FallTemplateBot2026:
    llm = GeneralLlm(model=FREE_MODEL, temperature=0.3, timeout=180, allowed_tries=2)
    return FallTemplateBot2026(
        research_reports_per_question=1,
        predictions_per_research_report=predictions,
        use_research_summary_to_forecast=False,
        enable_summarize_research=False,  # saves 1 LLM call per question
        publish_reports_to_metaculus=False,  # never publish from a dry run
        folder_to_save_reports_to="dry_run_reports",
        skip_previously_forecasted_questions=False,
        extra_metadata_in_explanation=True,
        llms={
            "default": llm,
            "summarizer": llm,
            # Free Google News headlines (news_research.py); --no-news falls
            # back to the LLM writing "research" from its own knowledge.
            "researcher": llm if no_news else "free-news/google-rss",
            "parser": llm,
        },
    )


def short(prediction) -> str:
    """Readable one-line version of a prediction (numeric CDFs are huge)."""
    pts = getattr(prediction, "declared_percentiles", None)
    if not pts:
        return str(prediction)
    def at(p: float) -> float:
        return min(pts, key=lambda x: abs(x.percentile - p)).value
    return f"10%: {at(0.1):,.0f} | median: {at(0.5):,.0f} | 90%: {at(0.9):,.0f}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=2, help="number of questions")
    parser.add_argument("--predictions", type=int, default=2)
    parser.add_argument("--no-news", action="store_true", help="skip the free news search")
    args = parser.parse_args()

    check_environment(strict=True)
    questions = MetaculusClient().get_all_open_questions_from_tournament("bot-testing-area")
    # Prefer a mix of question types (binary first, then numeric, then the rest).
    order = {"binary": 0, "numeric": 1, "multiple_choice": 2}
    seen, picked = set(), []
    for q in sorted(questions, key=lambda q: order.get(q.get_question_type(), 9)):
        t = q.get_question_type()
        if t not in seen:
            seen.add(t)
            picked.append(q)
        if len(picked) >= args.n:
            break

    print(f"\n🧪  Dry run on {len(picked)} question(s), publish=no, model={FREE_MODEL}")
    for q in picked:
        print(f"   - [{q.get_question_type()}] {q.question_text}  {q.page_url}")

    bot = build_bot(args.predictions, no_news=args.no_news)
    reports = asyncio.run(bot.forecast_questions(picked, return_exceptions=True))

    print("\n" + "=" * 80)
    for r in reports:
        if isinstance(r, BaseException):
            print(f"❌ {type(r).__name__}: {str(r)[:300]}")
        else:
            print(f"✅ {r.question.question_text}\n   → prediction: {short(r.prediction)}\n   {r.question.page_url}")
    print("=" * 80)
