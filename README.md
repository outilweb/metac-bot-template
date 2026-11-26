# ScrollLibarian-bot: a zero-cost Metaculus forecasting bot

This repository is the full source code of **ScrollLibarian-bot**, an automated forecasting bot that takes part in the [Metaculus FutureEval](https://www.metaculus.com/futureeval/) AI forecasting tournaments.

It is a fork of the official [Metaculus bot template](https://github.com/Metaculus/metac-bot-template). The main change is that it runs at **zero cost**, using only:
- a free OpenRouter model;
- free Google News headlines;
- free GitHub Actions minutes.

Everything the bot does is in this repository. There are no hidden prompts, private services or manual steps.

---

## 1. How the bot works

For each open tournament question the bot runs the same fully automatic pipeline. **No human reviews, edits or reruns any forecast.**

```
Metaculus question
   │
   ▼
1. News research (news_research.py)
   - 1 LLM call: the model writes 3 short news search queries
   - each query is sent to the public Google News RSS search feed
   - headlines are de-duplicated and sorted newest first (max 25)
   │
   ▼
2. Forecasting (main.py, prompts from the Metaculus template)
   - 3 independent LLM calls, each sees the question, its resolution
     criteria, fine print, background and the news headlines
   - each call reasons step by step and ends with a fixed answer format
     ("Probability: ZZ%", "Option: P%", or "Percentile 10..90: value")
   │
   ▼
3. Reading the answer (fast_parse.py)
   - the final answer is read with plain pattern matching (no LLM call)
   - if the text cannot be read reliably (e.g. "4.5 million" needs a unit
     conversion), the template's LLM parser is used as a fallback
   │
   ▼
4. Combining (forecasting-tools library)
   - the 3 forecasts are aggregated by the library: median for binary
     and numeric questions, averaged probabilities for multiple choice
   - binary probabilities are clipped to [1%, 99%]
   │
   ▼
5. Publishing
   - the forecast is posted with a private comment (the library default,
     visible to Metaculus) containing the news headlines used and the
     full reasoning of each of the 3 forecasts
```

### Models

| Purpose | Model |
|---|---|
| Everything (queries, forecasts, fallback parser) | `nvidia/nemotron-3-ultra-550b-a55b:free` on OpenRouter |

You can change the model in one place: `FREE_MODEL` in `main.py`. If paid credits become available (for example Metaculus-granted OpenRouter credits), `FREE_MODEL` can point to a stronger model with no other change.

### Prompts

The forecasting prompts are the Metaculus template prompts, unchanged. In short, they ask the model to:
- reason about the time left, the status quo, and both a Yes and a No scenario;
- put extra weight on the status quo;
- set wide 10/90 intervals on numeric questions.

They are in `main.py`, in the `_run_forecast_on_*` methods.

---

## 2. Staying within the free budget

An OpenRouter free-tier key allows **50 free-model requests per day**. The bot is built around that limit:

- **About 4 LLM calls per question:** 1 for the news queries and 3 for the forecasts. The template used about 11.
  - the research summary step is disabled, because it was not used for forecasting;
  - answers are read by `fast_parse.py` instead of an extra LLM call.
- **Daily budget guard (`budget.py`):**
  - before every run, the bot asks OpenRouter how many free requests are left today;
  - it then takes only as many new questions as fit, counting 5 calls per question and keeping 2 in reserve;
  - questions that close soonest go first, and the others wait for a later run;
  - so the bot never runs out of requests in the middle of a question.
- If the key is not on the free tier, the guard does not limit anything.

---

## 3. Which tournaments it enters

The schedules are set in `.github/workflows/`:

| Workflow | What it does | Schedule |
|---|---|---|
| `run_bot_on_tournament.yaml` | Forecasts new questions of the current seasonal FutureEval tournament | every 20 minutes |
| `test_bot.yaml` | Forecasts the [bot-testing-area](https://www.metaculus.com/tournament/bot-testing-area/) | manual only |
| `run_bot_on_metaculus_cup.yaml` | Metaculus Cup (practice, no bot prize) | manual only (schedule disabled to save the daily budget) |
| `review_bot.yaml` | Scores resolved forecasts, read-only | manual, or weekly if enabled |

**MiniBench** is off by default (`INCLUDE_MINIBENCH = False` in `main.py`). It will be switched on once the bot is considered ready.

Each run only forecasts questions the bot has **not** forecast yet. Forecasts are never rerun or edited by hand.

---

## 4. Rules compliance

- **No human in the loop.** All forecasts are produced and posted automatically by the code in this repository, run by GitHub Actions.
- **One bot.** ScrollLibarian-bot is the only bot of its owner.
- **Testing** is done only:
  - in dry-run mode, which publishes nothing;
  - or in the bot-testing-area.
- **Reasoning is published** with every forecast, as a private comment.
- **Open source.** This repository is public, and its history shows every change.

---

## 5. Running it yourself

You need Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/outilweb/metac-bot-template.git
cd metac-bot-template
uv sync
cp .env.template .env   # then put your METACULUS_TOKEN and OPENROUTER_API_KEY in .env
```

| Command | What it does | Publishes? |
|---|---|---|
| `uv run python dry_run.py` | Forecasts 2 bot-testing-area questions of different types | **No** |
| `uv run python main.py --mode test_questions --dry-run --max-questions 1` | Same pipeline as production, on 1 test question | **No** |
| `uv run python main.py --mode test_questions` | Forecasts the bot-testing-area | Yes (test area only) |
| `uv run python main.py` | Production: current tournament, new questions only | Yes |

`.env` is listed in `.gitignore`, so keys are never committed. In GitHub Actions, the keys are stored as repository secrets: `METACULUS_TOKEN` and `OPENROUTER_API_KEY`.

---

## 6. Files

| File | Role |
|---|---|
| `main.py` | The bot: prompts, pipeline, free-model configuration, run modes |
| `news_research.py` | Free Google News headline research |
| `fast_parse.py` | Reads the model's final answer without an extra LLM call |
| `budget.py` | Daily OpenRouter free-tier budget guard |
| `dry_run.py` | Test script that never publishes |
| `bot_helpers.py` | Environment checks and console banners (from the template) |
| `main_with_no_framework.py`, `integrations/` | Unchanged template files, not used by this bot |

---

## 7. Credits

Built on the [Metaculus bot template](https://github.com/Metaculus/metac-bot-template) and the [forecasting-tools](https://github.com/Metaculus/forecasting-tools) library. The template's original README is available in that repository.

---

## Résumé en français

Ce dépôt contient tout le code du bot **ScrollLibarian-bot**, qui participe aux tournois de prévision pour IA de Metaculus.

**Ce qu'il fait, pour chaque question :**
1. il cherche les titres d'actualité récents sur Google News ;
2. il demande 3 prévisions indépendantes à une IA gratuite ;
3. il combine ces 3 prévisions ;
4. il publie le résultat, avec son raisonnement.

**Les règles qu'il respecte :**
- personne n'intervient à la main ;
- rien n'est payant ;
- un garde-fou empêche de dépasser le quota de 50 appels gratuits par jour.
