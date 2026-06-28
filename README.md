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

<!-- TODO: 2–3 sentence plain-language summary of the system once built. -->

The goal is **not** to police creativity — it's to protect attribution, build trust, and
give audiences the context they need about whether content was human-made or AI-generated.

---

## Quick Start

<!-- TODO: fill in once the app exists. -->

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Groq API key
export GROQ_API_KEY="your-key-here"

# 4. Run the server
flask run
```

---

## API Reference

<!-- TODO: document each endpoint with method, path, request body, and example response. -->

| Method | Endpoint   | Purpose                                  |
|--------|------------|------------------------------------------|
| POST   | `/analyze` | Submit content for attribution analysis  |
| POST   | `/appeal`  | Contest a classification                 |
| GET    | `/log`     | View the structured audit log            |

### `POST /analyze`

<!-- TODO: request/response example. Response must include attribution result,
     confidence score, and the transparency label text. -->

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

<!-- TODO: document the exact aggregation/weighting once built — finalized alongside the
     Confidence Scoring section below. -->

> **How the two combine into one verdict:** _TODO — finalized with confidence scoring._

---

## Confidence Scoring

<!-- TODO: explain the approach. Key points to cover:
     - What does 0.5 mean to a user? (design decision first)
     - How a 0.51 produces a meaningfully different label than 0.95
     - The false-positive asymmetry: labeling a human's work as AI is worse than the reverse
     - How we tested whether the scores are meaningful -->

---

## Transparency Labels

These are the exact strings shown to a reader on the platform. There are three variants,
keyed to the confidence level.

<!-- REQUIRED: verbatim text of all three variants. Fill in the exact display strings. -->

### High-confidence AI

> _TODO: verbatim label text_

### High-confidence Human

> _TODO: verbatim label text_

### Uncertain

> _TODO: verbatim label text_

---

## Appeals Workflow

A creator can contest a classification. An appeal:

1. Captures the creator's reasoning
2. Logs the appeal alongside the original decision
3. Updates the content's status to **`under review`**

<!-- TODO: document the endpoint, request shape, and what changes in the record.
     Automated re-classification is not required. -->

---

## Rate Limiting

<!-- REQUIRED: document the chosen limits AND the reasoning for those specific values.
     Consider: how often does a real creator submit work? How would an adversary flood
     the system? -->

| Endpoint   | Limit        | Reasoning |
|------------|--------------|-----------|
| `/analyze` | _TODO_       | _TODO_    |

---

## Audit Log

Every attribution decision — including confidence score, signals used, and any appeals —
is captured in a structured audit log.

<!-- REQUIRED: show at least 3 sample entries here (or via GET /log output). -->

```json
[
  // TODO: ≥3 sample entries
]
```

---

## Project Structure

<!-- TODO: update as files are added. -->

```
ai201-project4-provenance-guard/
├── README.md          # this file
├── planning.md        # architecture + design decisions
├── PROJECT_BRIEF.md   # reference copy of the assignment spec
└── ...
```

---

## Built With

- **Flask** — API framework
- **Groq (`llama-3.3-70b-versatile`)** — detection signal
- **Stylometric heuristics** — detection signal (pure Python)
- **Flask-Limiter** — rate limiting
- **SQLite / structured JSON** — audit log
