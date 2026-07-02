# NEET Adaptive

AI-powered adaptive quiz platform for NEET exam preparation. Generates NEET-style MCQs on demand, adapts question difficulty (and pace) to the student's ability in real time, and produces a detailed end-of-session performance report with NEET-style scoring, concept mastery, cognitive-level breakdown, error analysis, and time-efficiency insights.

---

## How it works

1. When a session starts, the **Generator** agent calls Ollama to pre-generate a pool of NEET-style MCQs for the selected chapter and concepts — each question tagged with a Bloom's Taxonomy level (1–5) and Webb's DOK level (1–3) in addition to difficulty and question type. Every draft is checked against stems already stored for that concept (across *all* past sessions, not just the current batch) and against a numeric-signature check for numerical questions (same numbers, different story still counts as a collision); a discarded slot is automatically regenerated rather than silently shrinking the batch.
2. The **Router** selects the next question using an IRT-inspired ability estimate (1.0–5.0), targeting difficulty at the student's current level, softly prioritising concepts whose difficulty-weighted mastery is below the report's own "weak" threshold (so retesting boosts a weak concept's priority without excluding other concepts from the session), and modulating the ability update by how the student's response time compared to an expected pace for that question's type/difficulty. Fast + correct swings the estimate further; slow answers are treated as lower-confidence signal in either direction; a wrong answer much faster than expected is dampened rather than amplified, since it looks like a rushed guess rather than a genuine, diagnostic mistake.
3. After each answer the **Evaluator** determines whether the answer was correct and — if wrong — tags the failure mode: `conceptual_gap`, `calculation_error`, or `exception_not_known`.
4. After the session ends, the **Gap Analyser** deterministically computes a full performance report — NEET-style score (+4/−1/0), per-concept mastery %, Bloom/DOK cognitive-level breakdown, error-type analysis, time-efficiency (including a rushed-guess count and a per-question-type time breakdown) and speed/accuracy tradeoff, recovery rate and difficulty progression, and a prioritised "fix these first" list weighted by real NEET PYQ frequency — then calls Ollama once to write the personalised prose on top of those already-finalized numbers: per-concept misconception notes for weak concepts, expertise notes for strong concepts (grounded in the student's actual answer-rationale tags either way), a short summary, and a concrete next-steps checklist.

---

## Architecture

| Agent | Type | Role |
|---|---|---|
| Generator | LLM | Generates NEET-style MCQs with LaTeX formulas, inline SVG diagrams, and Bloom/DOK tags; self-heals by regenerating any question discarded for being a duplicate (cross-session), a numeric-signature collision, or schema-invalid |
| Evaluator | LLM + deterministic | Grades answers; tags failure mode for incorrect answers (fast-path, no LLM call, when the answer matches or times out) |
| Router | Deterministic | Adaptive difficulty/concept/type selection based on ability estimate and response-time confidence, with rushed-guess damping and weak-concept prioritization aligned with the report's own mastery formula |
| Gap Analyser | Deterministic + LLM narration | Computes every report metric deterministically, including per-concept misconception/expertise notes and a next-steps checklist grounded in real answer data; LLM only writes prose on top, never alters a number |

**Session state machine:**
```
GENERATING_POOL → AWAITING_ANSWER → EVALUATING → ROUTING → ... → COMPLETE → DONE
```

**Question serving strategy**: the router only decides *what* to ask next (concept/difficulty/type) — `_serve_question` then looks for a match in the pre-generated pool first, progressively relaxing (type, then difficulty) before ever calling the Generator live. A well-warmed pool (see `scripts/warmup_all_chapters.py`) means most questions serve in well under 100ms; the Generator is only invoked synchronously as a last resort.

---

## Prerequisites

- **Python 3.12+**
- **Ollama** — either:
  - [Ollama Cloud](https://ollama.com) account (free tier, no GPU needed) — set `OLLAMA_HOST=https://ollama.com` and provide `OLLAMA_API_KEY`
  - Local Ollama install — set `OLLAMA_HOST=http://localhost:11434`, leave `OLLAMA_API_KEY` blank, and `ollama pull <model>`

---

## Quick Start

```bash
# 1. Clone
git clone <repo-url> && cd neet-adaptive

# 2. Virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 3. Dependencies
pip install -r requirements.txt

# 4. Environment
cp .env.example .env
# Edit .env: set OLLAMA_API_KEY (and OLLAMA_HOST if using local Ollama)

# 5. Seed the taxonomy (46 chapters / 150 concepts across Physics, Chemistry, Botany, Zoology)
python seed_taxonomy.py

# 6. (Recommended) Pre-warm the question pool so sessions don't wait on live generation
python scripts/warmup_all_chapters.py

# 7. Start the server
python app.py
# (equivalent to: uvicorn app:app --host 127.0.0.1 --port 8010 --reload)

# 8. Open in browser
# http://localhost:8010
```

`python app.py` is the recommended way to (re)start the dev server — it checks port 8010 for an existing listener before binding, so you can't accidentally leave a stale server running old code after an edit (a real issue during active development, since FastAPI/uvicorn won't pick up code changes until the process actually restarts).

---

## Configuration

All settings are environment variables. Copy `.env.example` to `.env` and edit as needed.

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `https://ollama.com` | Ollama API base URL (cloud or local) |
| `OLLAMA_API_KEY` | _(empty)_ | API key for Ollama Cloud; leave blank for local |
| `OLLAMA_MODEL` | `gpt-oss:120b` | Model name. `gpt-oss:120b` was validated as reliable for JSON-schema compliance and NEET-level numericals |
| `DB_PATH` | `./data/neet.db` | SQLite database path (auto-created on first run) |
| `TAXONOMY_PATH` | `./data/taxonomy.json` | Chapter/concept taxonomy file |
| `LLM_CALL_LOG_PATH` | `./data/llm_call_log.jsonl` | JSONL log of every LLM call (prompts + raw responses) |
| `GENERATOR_BATCH_SIZE` | `3` | Questions generated per LLM call |
| `POOL_QUESTIONS_PER_CONCEPT` | `10` | Questions pre-generated per concept per session |
| `QUESTIONS_PER_SESSION` | `10` | Target questions per session before gap analysis |

A larger set of tunable thresholds (mastery verdict cutoffs, NEET marking scheme, time-efficiency heuristics, priority-concept weighting, etc.) lives as plain constants in `config.py` rather than environment variables, since they're report/scoring calibration rather than deployment config — see the "Report metric thresholds" section of that file.

---

## Deployment (Render)

This app needs a **Web Service** (a long-running HTTP process), not a static site or background worker — `render.yaml` in the repo root is a ready-to-use [Render Blueprint](https://render.com/docs/blueprint-spec) covering all of this.

- **Build command**: `pip install -r requirements.txt`
- **Start command**: `uvicorn app:app --host 0.0.0.0 --port $PORT` — the `HOST`/`PORT` env vars are read by `app.py`'s entry point (falling back to the local-dev defaults `127.0.0.1:8010` when unset), so the same file works locally and on Render without changes.
- **Persistent disk is required**: the SQLite database (`DB_PATH`) and LLM call log (`LLM_CALL_LOG_PATH`) are files on disk, and Render's default filesystem is wiped on every redeploy/restart. The Blueprint mounts a 1 GB disk at `/var/data` and points both paths at it. Persistent disks need Render's **Starter plan or above** — the Free tier doesn't support them, and using this app on Free means losing all sessions/questions on every restart.
- **Single instance only** — the app keeps in-memory state (background pool-generation status) and uses a single-file SQLite database with no concurrent-writer support. Do not enable autoscaling or run more than one instance; `render.yaml` sets `numInstances: 1` for this reason.
- **Secrets**: `OLLAMA_API_KEY` is marked `sync: false` in `render.yaml`, meaning it must be set manually in the Render dashboard's Environment tab rather than committed to the repo.
- **One-time setup after the first deploy**, via Render's Shell tab:
  - `python seed_taxonomy.py` — populates the taxonomy tables (idempotent, safe to re-run).
  - Optionally `python scripts/warmup_all_chapters.py` — pre-warms the question pool so early users don't wait on live generation. This makes real LLM calls, so it's worth doing once but not on every deploy.
- **Free-tier cold starts**: if not on a paid always-on plan, the service spins down after inactivity; combined with background pool generation, the first request after a cold start may be slower than usual.

---

## Project Structure

```
neet-adaptive/
├── app.py                    # FastAPI entry point (port 8010) - includes a port-conflict guard on startup
├── config.py                 # Environment variable config + report/scoring/routing thresholds
├── db.py                     # SQLite schema + auto-migration
├── seed_taxonomy.py          # Taxonomy seed script (idempotent - safe to re-run after editing taxonomy.json)
├── requirements.txt
├── .env.example              # Environment template
│
├── agents/
│   ├── generator.py          # LLM question generation with few-shot examples + Bloom/DOK tagging
│   ├── evaluator.py          # Answer evaluation + failure mode tagging
│   ├── gap_analyser.py       # Full end-of-session report computation + LLM-written narrations
│   ├── router.py             # Adaptive difficulty/concept/type routing + time-aware ability updates
│   ├── time_model.py         # Shared expected-time-per-question heuristic (router + report use one definition)
│   └── ollama_client.py      # Ollama API wrapper with retry + logging
│
├── models/
│   ├── question.py           # QuestionDraft, QuestionSchema, QuestionPublic (bloom_level, dok_level included)
│   ├── report.py             # GapReport + sub-models: NeetScore, BloomDokBreakdown, ErrorAnalysis,
│   │                          #   TimeEfficiency (+ TimeByTypeEntry), RecoveryProgression,
│   │                          #   PriorityConcept, StrengthConcept, ConceptVerdict
│   ├── agent_io.py           # ConceptSpec and other agent I/O types
│   └── session_state.py      # SessionState, DifficultyHistoryEntry, FailureModeTally
│
├── orchestrator/
│   ├── state_machine.py      # Session lifecycle (start, answer, route, report)
│   └── states.py             # SessionStatus enum
│
├── repositories/
│   ├── question_repo.py      # Question bank CRUD + get_stems_for_concept (cross-session duplicate detection)
│   ├── session_repo.py       # Session persistence
│   ├── report_repo.py        # Gap report storage (insights_json holds the extended report fields)
│   └── taxonomy_repo.py      # Chapter/concept queries
│
├── scripts/
│   ├── warmup_all_chapters.py  # Pre-warm the question pool for every chapter + end-to-end flow check
│   └── test_generate.py        # Standalone Generator smoke test (no DB writes)
│
├── static/
│   ├── app.js                # Frontend logic (adaptive UI, KaTeX, SVG diagrams, full report rendering)
│   ├── api.js                # Fetch-based API client
│   └── style.css
│
├── templates/
│   └── index.html            # Single-page app shell (KaTeX CDN included)
│
├── data/
│   └── taxonomy.json         # Full NEET syllabus: Physics / Chemistry / Botany / Zoology, Grades 11-12
│
└── tests/
    ├── test_router.py        # Routing, time-aware ability updates, rushed-guess damping, tie-breaking
    ├── test_generator.py     # Duplicate/numeric-collision detection + retry-on-discard behavior
    └── test_gap_analyser.py  # Report metric computation: priority/strength concepts, time-by-type, etc.
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Quiz UI (HTML) |
| `GET` | `/api/health` | Health check (includes server process `started_at`, useful for confirming a restart picked up new code) |
| `GET` | `/api/taxonomy/grades` | List grade levels (11, 12) |
| `GET` | `/api/taxonomy/chapters` | Chapters + concepts for a grade/subject |
| `POST` | `/api/sessions` | Start a new adaptive session |
| `GET` | `/api/sessions/{id}/current` | Get the current question |
| `POST` | `/api/sessions/{id}/answer` | Submit an answer |
| `POST` | `/api/sessions/{id}/report` | Generate the gap analysis report |
| `GET` | `/api/sessions/{id}/report` | Retrieve an existing report |

---

## Features

- **Adaptive difficulty** — ability estimate updated after each answer using asymmetric IRT-inspired steps (±0.5 when answer matches expectation, ±0.25 otherwise), further scaled ±30% by response-time confidence, clamped to [1, 5]
- **Weakness detection** — router softly re-prioritises concepts flagged weak by the same difficulty-weighted mastery formula the report uses, weighted by PYQ importance, without excluding other concepts from the session
- **Rushed-guess detection** — a wrong answer given much faster than the expected pace is treated as a likely guess rather than a genuine mistake, both in how it affects the live ability estimate and as a surfaced count in the end-of-session report
- **Duplicate-free question generation** — every new question is checked against stems already stored for that concept across *all* past sessions (not just the current batch) and against a numeric-signature collision check for numerical problems; discarded slots are automatically regenerated
- **5 question types** — recall, exception (NOT-correct), numerical, diagram, multi_concept
- **Bloom's Taxonomy + Webb's DOK tagging** — every question carries a cognitive-level (1–5) and depth-of-knowledge (1–3) tag, assigned by the Generator and back-filled deterministically for legacy questions
- **Full NEET syllabus taxonomy** — 46 chapters / 150 concepts across Physics, Chemistry, Botany, and Zoology (Grades 11–12), calibrated against the current NTA rationalized syllabus
- **KaTeX math rendering** — LaTeX formulas (`\( \)`, `\[ \]`, `$ $`, `$$ $$`) rendered client-side via KaTeX 0.16.9
- **SVG diagrams** — Physics/Chemistry diagram questions include LLM-generated inline SVG (circuits, force diagrams, ray diagrams); rendered safely as `<img src="data:image/svg+xml,...">`
- **NEET-style scoring** — +4 correct / −1 incorrect / 0 unattempted, with the resulting score, percentage, and marks lost to negative marking all surfaced in the report
- **Concept mastery %** — difficulty-weighted accuracy per concept (getting harder questions right counts for more), with a low-confidence flag when a verdict is based on very few questions
- **Cognitive-level breakdown** — accuracy by Bloom level and DOK level actually encountered in the session, to see whether performance holds up as cognitive demand increases
- **Error analysis** — session-wide breakdown of failure modes (conceptual gap / calculation error / missed exception)
- **Time efficiency** — actual vs. expected time per question, a hesitation index (correct answers that took much longer than expected), a rushed-guess count, a per-question-type average time breakdown, and a speed/accuracy tradeoff verdict
- **Recovery & progression** — bounce-back rate after a wrong answer, and first-half vs. second-half accuracy/difficulty
- **Priority concepts** — weak/needs-improvement concepts that also have high real-world NEET PYQ frequency, each with an LLM-written misconception note grounded in the student's actual wrong-answer rationale tags, so students know what to fix first for maximum score impact
- **Strength concepts** — the mirror image of priority concepts: strong concepts with an LLM-written expertise note grounded in the student's actual correct-answer rationale tags, so it's equally clear what's already working
- **Next steps checklist** — a short, concrete list of LLM-written action items generated alongside the rest of the report narration
- **Gap analysis report** — per-concept verdict (strong / needs_improvement / weak / not_assessed) with LLM-written personalised narrations, grounded in (and never allowed to contradict) the deterministic numbers above
- **Idempotent report generation** — calling `POST /report` twice returns the same cached report without re-running the LLM

---

## Testing

```bash
# Run all unit tests
pytest tests/

# Quick manual end-to-end (5 questions instead of 10)
QUESTIONS_PER_SESSION=5 python app.py
```

The test suite (42 tests across 3 files) covers: the router's ability update logic including time-aware modulation and rushed-guess damping, concept selection (weak-concept boosting, coverage caps, randomized tie-breaking), question type rotation, and difficulty targeting (`test_router.py`); generator duplicate and numeric-signature collision detection with retry-on-discard behavior (`test_generator.py`); and gap analyser report metric computation, including priority/strength concept extraction, rationale-note collection, and time-by-question-type breakdowns (`test_gap_analyser.py`).

---

## LLM Notes

- Default model `gpt-oss:120b` on Ollama Cloud was chosen for reliable JSON-schema compliance and correct handling of NEET-level numerical problems.
- Any model available on your Ollama instance can be used — set `OLLAMA_MODEL` accordingly.
- All LLM calls are logged to `data/llm_call_log.jsonl` (prompts, raw responses, validation errors) for debugging and cost tracking.
- The client retries once on JSON validation failure, feeding the error back to the model before raising `AgentGenerationError`.
- Every LLM-backed agent (Generator, Evaluator, Gap Analyser) has a deterministic fallback for when Ollama is unavailable, so a session degrades gracefully rather than failing outright.
