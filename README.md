# Provenance Guard

A backend system that any creative-sharing platform can plug into to classify submitted
text content, score confidence in that classification, surface a transparency label to
readers, and handle appeals from creators who believe they've been misclassified.

> **Status:** ✅ Production layer complete (Milestone 5). All seven required features work
> end to end: submission, multi-signal detection, confidence scoring, transparency labels,
> appeals, rate limiting, and a structured audit log.

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

> **Port note:** on macOS, AirPlay Receiver squats on port 5000. If `flask run` clashes,
> use another port: `flask run --port 5001`. The examples below use `localhost:5000`.

---

## API Reference

Four endpoints. Full request/response shapes are in [planning.md](planning.md) under
"API Surface."

| Method | Endpoint   | Purpose                                  |
|--------|------------|------------------------------------------|
| POST   | `/submit`  | Submit text, get an attribution + label  |
| POST   | `/appeal`  | Contest a classification                 |
| GET    | `/log`     | View the structured audit log            |
| GET    | `/health`  | Service health check (for monitoring)    |

### `POST /submit`

Submit one piece of text. Get back the result, the confidence score, and the label.

**Request:**
```json
{ "text": "The poem or story text goes here.", "creator_id": "optional" }
```

**Response (`200 OK`):**
```json
{
  "content_id": "f0d95e0d-037c-4681-92eb-62cca1f59e5a",
  "attribution": "likely_ai",
  "confidence": 0.88,
  "label": {
    "variant": "high_confidence_ai",
    "badge": "🤖 Reads as AI-generated",
    "text": "🤖 This reads as AI-generated. Our automated check thinks this was most likely written with AI help..."
  },
  "signals": {
    "llm": { "verdict": "ai", "confidence": 0.9 },
    "stylometry": { "verdict": "ai", "score": 0.8674 }
  },
  "creator_id": "demo-ai",
  "status": "classified",
  "timestamp": "2026-07-01T03:01:32Z"
}
```
- `attribution` is one of `likely_ai`, `likely_human`, `uncertain`.
- `content_id` is what a creator uses to appeal.
- `label` is the exact text shown to a reader, plus its `variant` and inline `badge`.
- `signals` shows what each signal said, so the result is transparent.
- Errors: `400` (text missing, empty, or too long), `429` (rate limit hit).

### `POST /appeal`

A creator contests a decision.

**Request:**
```json
{ "content_id": "f0d95e0d-...", "creator_reasoning": "I wrote this myself. Here is my draft history." }
```

**Response (`200 OK`):**
```json
{
  "appeal_id": "e80e4872-eddb-458d-81ae-1c8f61949f28",
  "content_id": "f0d95e0d-037c-4681-92eb-62cca1f59e5a",
  "status": "under_review",
  "message": "Your appeal was received. This content is now under review.",
  "timestamp": "2026-07-01T03:02:36Z"
}
```
- Errors: `400` (`content_id` or `creator_reasoning` missing), `404` (no decision with that ID).

### `GET /log`

View the audit log, newest first. Optional `?limit=N`. Optional `?status=under_review` for
the review queue (open appeals, oldest first). Returns a list of decision entries, each with
its signals, result, confidence, label variant, status, and any appeals attached.

### `GET /health`

A cheap check for monitoring. Confirms the audit log store is reachable and the Groq API key
is present. It does **not** call Groq on every check (that would waste free quota and add
latency). Returns `200` when healthy, `503` if a critical part is down.

```json
{
  "status": "ok",
  "timestamp": "2026-07-01T02:59:35Z",
  "checks": { "audit_log": "ok", "groq_api_key": "present" }
}
```

---

## Detection Pipeline (Multi-Signal)

The pipeline uses **two distinct signals** to classify content. "Distinct" here means they
capture genuinely different properties of the text, not two versions of the same approach.
One is **semantic**, one is **structural**, which makes the combination more informative
than either signal alone.

| Signal | What it captures | Why we chose it |
|--------|------------------|-----------------|
| **Signal 1: LLM-based classification (Groq, `llama-3.3-70b-versatile`)** | Asks the model to assess whether the text *reads* as human- or AI-generated. Captures **semantic and stylistic coherence holistically**, meaning, tone, and flow that a fixed rule can't measure. | A language model can judge the overall "feel" of writing and contextual coherence, the holistic qualities that distinguish human voice from generated text. |
| **Signal 2: Stylometric heuristics (pure Python)** | Measurable **statistical / structural** properties: sentence-length variance, type-token ratio (vocabulary diversity), punctuation density, and average sentence complexity. AI text tends to be **more uniform**; human writing is **more variable**. | A deterministic, explainable, API-free signal grounded in measurable text properties, completely independent of the model's judgment. |

**Why these two are genuinely independent:** Signal 1 is semantic (what the text *means*
and how it reads); Signal 2 is structural (the *statistics* of how it's written). They can
disagree, and that disagreement is itself informative: it's what drives an honest
"uncertain" verdict rather than a forced binary one.

Each signal's blind spots are written out in full in [planning.md](planning.md) under
"Detection Signals" and "Edge Cases and Known Weak Spots."

**How the two combine into one verdict:** see Confidence Scoring, below. In short, both
signals are put on one 0-to-1 AI-leaning scale, blended (the LLM weighted a bit heavier),
pulled toward the middle when they disagree, and capped on short text.

---

## Confidence Scoring

The system returns a **confidence score from 0 to 1**, not just a yes/no answer. The score
is how sure the system is about the result it is showing.

**What the numbers mean to a reader:**
- A score near **0.5** means the system is barely leaning one way, basically a coin flip.
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

**The bands (the cutoffs):** the confidence score plus the direction decide the result.

| Result | Cutoff | Label shown |
|--------|--------|-------------|
| `likely_ai` | leans AI **and** confidence ≥ **0.80** | High-confidence AI |
| `likely_human` | leans human **and** confidence ≥ **0.70** | High-confidence human |
| `uncertain` | everything else | Uncertain |

The **AI bar (0.80) is set higher than the human bar (0.70)** on purpose: calling a human's
work AI is the worst mistake, so it takes stronger evidence. Short text also caps the score:
under 25 words can only ever be "uncertain," and under 75 words can never be "likely AI." The
full method (how the two signals blend, how disagreement pulls the score to the middle, the
short-text caps, and worked examples) is in [planning.md](planning.md) under "Confidence
Scoring."

**How we tested that the scores are meaningful:**
- [tests/verify_scoring.py](tests/verify_scoring.py) runs the worked examples from planning.md
  as assertions: it confirms strong agreement produces a confident score, disagreement pulls
  the score toward the "uncertain" middle, and short text caps the ceiling.
- [tests/verify_calibration.py](tests/verify_calibration.py) runs known-human and known-AI
  samples to check that a confident "likely AI" result is hard to trigger on real human
  writing (the false-positive we care most about).
- The live demo below lands three real submissions in three different bands: a short note at
  **0.58 (uncertain)**, a casual human review at **0.74 (likely_human)**, and a repetitive
  corporate paragraph at **0.88 (likely_ai)**. Different scores, different labels.

---

## Transparency Labels

These are the exact strings shown to a reader on the platform. There are three variants,
chosen by the confidence score (through the attribution band it lands in).

**Design rules for every label:**
- Plain language a non-technical reader understands.
- Always framed as an automated guess, never a stated fact.
- Always points the creator to the appeal path.
- Never a judgment of the person, only a note about the text.

Each label has a **short badge** (shown inline) and the **full text** (shown on tap/hover or
beside the work). The full text is the required deliverable and is reproduced verbatim below.

### High-confidence AI

Badge: **🤖 Reads as AI-generated**

> 🤖 This reads as AI-generated. Our automated check thinks this was most likely written
> with AI help. How it reads and how it's put together both point that way. This is an
> automated guess about the text, not a proven fact, and not a judgment of the writer. If
> you wrote this yourself, you can appeal, and it will be marked "under review" while a
> person takes a look.

### High-confidence Human

Badge: **✍️ Reads as human-written**

> ✍️ This reads as human-written. Our automated check thinks a person most likely wrote
> this. How it reads and how it's put together both point that way. This is still an
> automated guess, not a proven fact. If something looks wrong, you can appeal, and it will
> be marked "under review."

### Uncertain

Badge: **❓ Not sure who wrote this**

> ❓ We're not sure who wrote this. Our automated check could not tell whether a person or
> AI wrote this. The signs were weak or pointed in different directions, so we are not
> making a call. Treat this as context, not an answer. If you'd like a person to take a
> look, you can appeal, and it will be marked "under review."

---

## Appeals Workflow

A creator can contest a classification through `POST /appeal`. An appeal:

1. **Captures the creator's reasoning**, sent in the `creator_reasoning` field.
2. **Logs the appeal alongside the original decision**, found by `content_id`. The appeal is
   stored inside that same decision's log entry (an `appeals` list). One decision, one
   record, everything attached to it.
3. **Updates the content's status to `under_review`**, so the AI label can step back and the
   creator is not publicly branded while the dispute is open.

Automated re-classification is **not** part of this. The appeal opens the door for a human to
look again; it does not re-run detection on its own. The review queue is just a filtered view
of the same log: `GET /log?status=under_review`, oldest appeal first.

**Example (using a `content_id` from an earlier `/submit`):**
```bash
curl -s -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "f0d95e0d-...", "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."}'
```

---

## Rate Limiting

Rate limiting sits at the front of the `/submit` flow. It protects three things: the service
from floods, real creators' experience, and our free Groq quota (every `/submit` call spends
one Groq request). Built with **Flask-Limiter** (in-memory storage), keyed on `creator_id`
when the platform sends it, otherwise the caller's IP. Over the limit returns
`429 Too Many Requests`.

| Endpoint | Limit | Reasoning |
|----------|-------|-----------|
| `/submit` | **10 / minute** and **100 / day** per client | A real creator posts occasionally, not in bursts. 10/min leaves comfortable room for someone actively revising and resubmitting, while a flood script hits the wall fast. 100/day caps sustained abuse and keeps one client from draining our Groq free-tier quota, and stays well under Groq's own daily limit, so one heavy user can't take the service down for everyone. |
| `/appeal`, `/log`, `/health` | default (**30 / minute**) | Cheap, no model call. They only need basic flood protection. |

**Evidence (12 rapid submits, limit is 10/min):**
```text
$ for i in $(seq 1 12); do
    curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5000/submit \
      -H "Content-Type: application/json" \
      -d '{"text": "...", "creator_id": "ratelimit-test"}'
  done
200
200
200
200
200
200
200
200
200
200
429
429
```
The first 10 succeed; the 11th and 12th are rejected with `429`.

---

## Audit Log

Every attribution decision, including the confidence score, the signals used, and any
appeals, is captured in a structured JSON audit log, viewable through `GET /log`.

Below is a real `GET /log` snapshot with three entries (newest first). The middle entry was
appealed, so its status is `under_review` and the appeal is attached. Per-signal reasoning,
stylometry metrics, and the scoring internals are trimmed here for readability; the full
records come back from `GET /log`.

```json
{
  "entries": [
    {
      "content_id": "51d83ae5-6f61-4c49-a4df-644021be1f24",
      "creator_id": "demo-short",
      "timestamp": "2026-07-01T03:01:32Z",
      "text_snippet": "Rain again today. I forgot my umbrella.",
      "attribution": "uncertain",
      "confidence": 0.58,
      "label_variant": "uncertain",
      "signals": {
        "llm": { "verdict": "human", "confidence": 0.8 },
        "stylometry": { "verdict": "ai", "score": 0.6571 }
      },
      "status": "classified",
      "appeals": []
    },
    {
      "content_id": "f0d95e0d-037c-4681-92eb-62cca1f59e5a",
      "creator_id": "demo-ai",
      "timestamp": "2026-07-01T03:01:32Z",
      "text_snippet": "Our team is committed to delivering excellent results. Our team is focused on meeting every client need...",
      "attribution": "likely_ai",
      "confidence": 0.88,
      "label_variant": "high_confidence_ai",
      "signals": {
        "llm": { "verdict": "ai", "confidence": 0.9 },
        "stylometry": { "verdict": "ai", "score": 0.8674 }
      },
      "status": "under_review",
      "appeals": [
        {
          "appeal_id": "e80e4872-eddb-458d-81ae-1c8f61949f28",
          "reason": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
          "timestamp": "2026-07-01T03:02:36Z"
        }
      ]
    },
    {
      "content_id": "65270387-316a-4612-be10-2fe6ff0b7fb8",
      "creator_id": "demo-human",
      "timestamp": "2026-07-01T03:01:31Z",
      "text_snippet": "ok so i finally tried that new ramen place downtown and honestly? underwhelming...",
      "attribution": "likely_human",
      "confidence": 0.74,
      "label_variant": "high_confidence_human",
      "signals": {
        "llm": { "verdict": "human", "confidence": 0.8 },
        "stylometry": { "verdict": "human", "score": 0.3273 }
      },
      "status": "classified",
      "appeals": []
    }
  ]
}
```

---

## Project Structure

```
ai201-project4-provenance-guard/
├── README.md          # this file
├── planning.md        # architecture, signals, design decisions, API contract
├── PROJECT_BRIEF.md   # reference copy of the assignment spec
├── app.py             # Flask app: /submit, /appeal, /log, /health + rate limiting
├── scoring.py         # confidence scorer: two signals into one attribution + score
├── labels.py          # transparency label text for the three variants
├── audit_log.py       # structured JSON audit log (append, read, appeal, health)
├── signals/
│   ├── llm.py         # Signal 1: Groq LLM classification (semantic)
│   └── stylometry.py  # Signal 2: stylometric heuristics (structural, pure Python)
├── tests/             # verify_*.py checks for each signal, scoring, submit, labels, appeal
├── requirements.txt   # dependencies
├── .env               # GROQ_API_KEY (gitignored, never committed)
└── audit_log.json     # the log store (created at runtime)
```

---

## Built With

- **Flask**: API framework
- **Groq (`llama-3.3-70b-versatile`)**: detection signal (semantic)
- **Stylometric heuristics**: detection signal (structural, pure Python, standard library)
- **Flask-Limiter**: rate limiting
- **Structured JSON**: audit log store
