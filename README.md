# Provenance Guard

A backend system that any creative-sharing platform can plug into to classify submitted
text content, score confidence in that classification, surface a transparency label to
readers, and handle appeals from creators who believe they've been misclassified.

> **Status:** 🚧 In development

---

## Table of Contents

- [What It Does](#what-it-does)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Detection Pipeline (Multi-Signal)](#detection-pipeline-multi-signal)
- [Confidence Scoring](#confidence-scoring)
- [Transparency Labels](#transparency-labels)
- [Appeals Workflow](#appeals-workflow)
- [Rate Limiting](#rate-limiting)
- [Audit Log](#audit-log)
- [Project Structure](#project-structure)

---

## What It Does

Provenance Guard is a backend service for platforms where people share their own writing.

A platform sends it a piece of text. The service checks whether the text reads as
human-written or AI-generated, gives a confidence score, and returns a plain-language label
the platform can show to readers. If a creator believes the result is wrong, they can
appeal, and the content is marked "under review." Every decision is saved in an audit log.

The goal is **not** to police creativity. It is to protect attribution, build trust, and
give readers honest context about where writing came from. Because labeling a real person's
work as AI is the most harmful mistake the system can make, it is built to stay cautious:
when the evidence is weak or mixed, it says "unsure" instead of guessing.

---

## Quick Start

> Note: the server code is still being built. These are the intended setup steps.

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Groq API key (copy .env and fill it in)
export GROQ_API_KEY="your-key-here"

# 4. Run the server
flask run
```

---

## API Reference

Four endpoints. Full request/response shapes are in [planning.md](planning.md) under
"API Surface."

| Method | Endpoint   | Purpose                                  |
|--------|------------|------------------------------------------|
| POST   | `/analyze` | Submit text, get an attribution + label  |
| POST   | `/appeal`  | Contest a classification                 |
| GET    | `/log`     | View the structured audit log            |
| GET    | `/health`  | Service health check (for monitoring)    |

### `POST /analyze`

Submit one piece of text. Get back the result, the confidence score, and the label.

**Request:**
```json
{ "text": "The poem or story text goes here.", "creator_id": "optional" }
```

**Response (`200 OK`):**
```json
{
  "decision_id": "a1b2c3",
  "attribution": "uncertain",
  "confidence": 0.58,
  "label": {
    "variant": "uncertain",
    "text": "We could not tell whether AI helped with this..."
  },
  "signals": {
    "llm": { "verdict": "ai", "confidence": 0.7 },
    "stylometry": { "verdict": "human", "score": 0.4 }
  },
  "status": "classified",
  "timestamp": "2026-06-28T18:00:00Z"
}
```
- `attribution` is one of `likely_ai`, `likely_human`, `uncertain`.
- `decision_id` is what a creator uses to appeal.
- `signals` shows what each signal said, so the result is transparent.
- Errors: `400` (text missing, empty, or too long), `429` (rate limit hit).

### `POST /appeal`

A creator contests a decision.

**Request:**
```json
{ "decision_id": "a1b2c3", "reason": "I wrote this myself. Here is my draft history." }
```

**Response (`200 OK`):**
```json
{
  "appeal_id": "x9y8z7",
  "decision_id": "a1b2c3",
  "status": "under_review",
  "message": "Your appeal was received. This content is now under review.",
  "timestamp": "2026-06-28T18:05:00Z"
}
```
- Errors: `400` (`decision_id` or `reason` missing), `404` (no decision with that ID).

### `GET /log`

View the audit log, newest first. Optional `?limit=N`. Returns a list of decision entries,
each with its signals, result, confidence, label, status, and any appeals attached.

### `GET /health`

A cheap check for monitoring. Confirms the audit log store is writable and the Groq API key
is present. It does **not** call Groq on every check (that would waste free quota and add
latency). Returns `200` when healthy, `503` if a critical part is down.

---

## Detection Pipeline (Multi-Signal)

The pipeline uses **two distinct signals** to classify content. "Distinct" here means they
capture genuinely different properties of the text — not two versions of the same approach.
One is **semantic**, one is **structural**, which makes the combination more informative
than either signal alone.

| Signal | What it captures | Why we chose it |
|--------|------------------|-----------------|
| **Signal 1 — LLM-based classification (Groq, `llama-3.3-70b-versatile`)** | Asks the model to assess whether the text *reads* as human- or AI-generated. Captures **semantic and stylistic coherence holistically** — meaning, tone, and flow that a fixed rule can't measure. | A language model can judge the overall "feel" of writing and contextual coherence — the holistic qualities that distinguish human voice from generated text. |
| **Signal 2 — Stylometric heuristics (pure Python)** | Measurable **statistical / structural** properties: sentence-length variance, type-token ratio (vocabulary diversity), punctuation density, and average sentence complexity. AI text tends to be **more uniform**; human writing is **more variable**. | A deterministic, explainable, API-free signal grounded in measurable text properties — completely independent of the model's judgment. |

**Why these two are genuinely independent:** Signal 1 is semantic (what the text *means*
and how it reads); Signal 2 is structural (the *statistics* of how it's written). They can
disagree, and that disagreement is itself informative — it's what drives an honest
"uncertain" verdict rather than a forced binary one.

Each signal's blind spots are written out in full in [planning.md](planning.md) under
"Detection Signals."

> **How the two combine into one verdict:** _Finalized with confidence scoring (see below)._

---

## Confidence Scoring

The system returns a **confidence score from 0 to 1**, not just a yes/no answer. The score
is how sure the system is about the result it is showing.

**What the numbers mean to a reader:**
- A score near **0.5** means the system is barely leaning one way — basically a coin flip.
  This produces the **"unsure"** label.
- A score near **0.95** means the system is very sure. This produces a **confident** label.
- So **0.51 and 0.95 do not produce the same label.** A 0.51 says "we are not sure"; a 0.95
  says "we are confident." The wording the reader sees changes with the score.

**How we get there (the design rules):**
- **Both signals must agree, strongly, for a confident result.** If they only mildly agree,
  confidence stays in the middle.
- **Disagreement lowers the score.** If the model says AI but the stats say human, the score
  drops toward the unsure middle instead of picking a winner.
- **Short or thin text caps confidence.** Less evidence means a lower ceiling on how sure we
  let ourselves be.
- **The "AI" side is harder to reach than the "human" side.** Because calling a real
  person's work AI is the worst mistake, we require stronger evidence before we land a
  confident "likely AI" result. When in doubt, we lean away from accusing a human.

<!-- TODO (build + test): finalize the exact band cutoffs, and document how we tested that
     the scores are meaningful — e.g. running known-human and known-AI samples and checking
     that confident-AI is hard to trigger on real human writing. -->

---

## Transparency Labels

> ⚠️ **TO DO (required deliverable, not yet written):** the exact wording of all three
> label variants below still needs to be drafted and then tested on someone who hasn't seen
> the project. This is a required README item. Do not consider the project done until these
> three blockquotes hold real, final text.

These are the exact strings shown to a reader on the platform. There are three variants,
chosen by the confidence score.

**Design rules for every label:**
- Plain language a non-technical reader understands.
- Always framed as an automated guess, never a stated fact.
- Always points the creator to the appeal path.
- Never a judgment of the person, only a note about the text.

<!-- REQUIRED: verbatim text of all three variants. Being drafted as a dedicated step,
     then tested on someone who hasn't seen the project (per the project hint). -->

### High-confidence AI

> _Final wording to be drafted._

### High-confidence Human

> _Final wording to be drafted._

### Uncertain

> _Final wording to be drafted._

---

## Appeals Workflow

A creator can contest a classification through `POST /appeal`. An appeal:

1. **Captures the creator's reasoning** — sent in the `reason` field.
2. **Logs the appeal alongside the original decision** — found by `decision_id`, the appeal
   is stored inside that same decision's log entry (an `appeals` list). One decision, one
   record, everything attached to it.
3. **Updates the content's status to `under_review`** — so the AI label can step back and
   the creator is not publicly branded while the dispute is open.

Automated re-classification is **not** part of this. The appeal opens the door for a human
to look again; it does not re-run detection on its own.

---

## Rate Limiting

Rate limiting protects the `/analyze` endpoint from floods and abuse, and protects our free
Groq quota.

<!-- REQUIRED: choose the limits AND explain the reasoning. Will be based on realistic
     creator usage (a person posts work occasionally, not dozens of times a minute) vs. an
     adversary trying to flood the endpoint. -->

| Endpoint   | Limit        | Reasoning |
|------------|--------------|-----------|
| `/analyze` | _To be set_  | _To be documented_ |

---

## Audit Log

Every attribution decision — including the confidence score, the signals used, and any
appeals — is captured in a structured audit log, viewable through `GET /log`.

Each entry has this shape:
```json
{
  "decision_id": "a1b2c3",
  "timestamp": "2026-06-28T18:00:00Z",
  "text_snippet": "The poem or story text...",
  "signals": { "llm": {}, "stylometry": {} },
  "attribution": "uncertain",
  "confidence": 0.58,
  "label_variant": "uncertain",
  "status": "under_review",
  "appeals": [
    { "appeal_id": "x9y8z7", "reason": "I wrote this myself...", "timestamp": "..." }
  ]
}
```

<!-- REQUIRED: paste at least 3 real entries here (or show GET /log output) once running. -->

---

## Project Structure

```
ai201-project4-provenance-guard/
├── README.md          # this file
├── planning.md        # architecture, signals, design decisions, API contract
├── PROJECT_BRIEF.md   # reference copy of the assignment spec
├── requirements.txt   # dependencies
├── .env               # GROQ_API_KEY (gitignored, never committed)
├── .gitignore
└── ...                # app code to come
```

---

## Built With

- **Flask** — API framework
- **Groq (`llama-3.3-70b-versatile`)** — detection signal (semantic)
- **Stylometric heuristics** — detection signal (structural, pure Python)
- **Flask-Limiter** — rate limiting
- **SQLite / structured JSON** — audit log
