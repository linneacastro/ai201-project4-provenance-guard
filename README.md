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
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Detection Pipeline (Multi-Signal)](#detection-pipeline-multi-signal)
- [Confidence Scoring](#confidence-scoring)
- [Transparency Labels](#transparency-labels)
- [Appeals Workflow](#appeals-workflow)
- [Rate Limiting](#rate-limiting)
- [Audit Log](#audit-log)
- [Known Limitations](#known-limitations)
- [Spec Reflection](#spec-reflection)
- [AI Usage](#ai-usage)
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

## Architecture

The path one submission takes, from the text arriving to a label going back:

1. **Request arrives** at `POST /submit` with the text (and an optional `creator_id`).
2. **Rate limiter checks first.** If this client has sent too many requests recently, it
   stops here with `429`, before any real work happens.
3. **Input validation.** The text must be a non-empty string and not too long, or it stops
   with `400`. This saves a wasted model call.
4. **Both signals run.** The text goes to Signal 1 (the Groq LLM, meaning) and Signal 2
   (stylometry, structure). Each returns its own read, independently.
5. **The confidence scorer combines them.** The two reads become one AI-leaning number,
   pulled toward "unsure" when they disagree and capped on short text, then turned into an
   attribution (`likely_ai`, `likely_human`, or `uncertain`) plus a confidence score.
6. **The label generator picks the wording.** The attribution maps to one of three
   plain-language transparency labels, the text a reader actually sees.
7. **The audit log saves the record** under a new `content_id`: the text, both signals, the
   score, the label, and an empty appeals list.
8. **The response returns** the `content_id`, attribution, confidence, label text, and
   signals to the platform.

An appeal later uses that same `content_id` to find the decision in the audit log, attach the
creator's reasoning, and flip the status to `under_review`. Both flows meet at the audit log,
tied together by the `content_id`.

The full architecture write-up, including ASCII and Mermaid diagrams of both flows, is in
[planning.md](planning.md) under "Architecture."

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

**What each signal misses (its blind spots):**
- **Signal 1 (the LLM)** can be confidently wrong. Polished, edited human writing can read
  as "AI-smooth" and get flagged, which is the false positive we care about most. Lightly
  edited AI text can slip past it. It is also not perfectly consistent: the same text can
  draw a slightly different verdict on different runs.
- **Signal 2 (stylometry)** only sees structure, never meaning, so varied nonsense still
  looks "human" to it. It needs enough text to be stable, it is easy to game once you know
  the rules, and it misreads genres with unusual stats (poetry, lists, recipes).

The full blind-spot list for each signal is in [planning.md](planning.md) under "Detection
Signals," and the specific content types they get wrong are in
[Known Limitations](#known-limitations) below.

**How the two combine into one verdict:** see Confidence Scoring, below. In short, both
signals are put on one 0-to-1 AI-leaning scale, blended (the LLM weighted a bit heavier),
pulled toward the middle when they disagree, and capped on short text.

**Why two signals, not one (and not five).** A single detector is easy to fool and has no
honest way to show its own doubt: it just returns a number. Two signals that measure
different things (meaning vs. structure) can disagree, and that disagreement is the real
uncertainty we want to surface instead of hide. We stopped at two because a third weak
signal would add noise, not a new view. If we found a signal that measured something
genuinely different (for example, token-level perplexity from a base model), we would add
it and give it real weight.

**What we'd change deploying this for real:**
- **Calibrate stylometry on a labeled corpus.** The reference ranges (sentence-length
  variation, vocabulary variety, and so on) are tuned guesses. With a real set of
  known-human and known-AI writing, we would fit the cutoffs to data instead of picking
  them by hand.
- **Treat the LLM as non-deterministic.** The same text can get a slightly different
  verdict on different runs. In production we would call it a few times and average, or at
  least record the spread, so one unlucky call does not decide a creator's label.
- **Plan for drift.** AI writing changes fast, so a cutoff that works today will rot. We
  would track score distributions over time and re-tune on a schedule.

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

**Why this approach, and not a simple average.** A plain average of the two signals would
hide the one thing we care about most: when the signals fight, an average still returns a
confident-looking middle number. Our approach keeps a single AI-leaning number and pulls it
toward 0.5 as the signals disagree, so a fight shows up as low confidence, not false
certainty. The asymmetric bars (0.80 to call AI, 0.70 to call human) and the short-text caps
all lean the same direction: away from calling a real person's work AI.

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

### Two example submissions (real scores)

Two real `/submit` results, lifted straight from testing, that land far apart on the
confidence scale. Same system, same rules, very different scores: that gap is the variation
the scoring is meant to produce, not a constant.

**High-confidence case: 0.88 (likely AI).** A repetitive corporate paragraph.

> "Our team is committed to delivering excellent results. Our team is focused on meeting
> every client need. Our team is dedicated to maintaining the highest standards..."

| Field | Value |
|-------|-------|
| Confidence | **0.88** |
| Attribution | `likely_ai` -> High-confidence AI label |
| LLM signal | `ai`, 0.90 sure ("repetitive and formulaic sentence structures") |
| Stylometry signal | `ai`, score 0.87 (sentence lengths barely vary) |
| Why so high | Both signals agree strongly, and at 92 words the text is long enough that no cap applies. Nothing pulls the score down. |

**Lower-confidence case: 0.58 (uncertain).** A short personal note.

> "Rain again today. I forgot my umbrella."

| Field | Value |
|-------|-------|
| Confidence | **0.58** |
| Attribution | `uncertain` -> Uncertain label |
| LLM signal | `human`, 0.80 sure ("personal, relatable experience") |
| Stylometry signal | `ai`, score 0.66 (too few words to trust the structure) |
| Why so low | The two signals disagree (one says human, one says AI), which pulls the score toward the middle. And at just 7 words there is too little to go on, so the short-text cap would block any confident call anyway. |

The gap between **0.88** and **0.58** is the whole point: a confident call needs agreeing
signals and enough text, and when either is missing the score drops and the label changes
from an accusation to an honest "not sure."

**What we'd change deploying this for real:**
- **Set the bars from a target error rate.** Today 0.80 and 0.70 are reasoned guesses. With
  labeled data we would pick the AI bar to hold the false-positive rate (human work wrongly
  called AI) under a chosen limit, since that is the mistake we most want to avoid.
- **Return a range, not just a point.** A bare 0.58 hides how shaky it is. We would return a
  confidence interval, or a "based on N model runs" note, so the platform can decide how far
  to trust it.
- **Feed appeals back in.** Every upheld or overturned appeal is a free labeled example. Over
  time those are the cheapest, most relevant calibration data we have, so we would use them
  to re-tune the bars.

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

## Known Limitations

Detecting AI writing is an unsolved problem, and this system gets some cases wrong. These
are not vague "needs more data" gaps. Each one traces back to a specific property of one of
our two signals, so we can point at exactly where it breaks. The full list is in
[planning.md](planning.md) under "Edge Cases and Known Weak Spots." The three that matter
most:

**1. Plain, repetitive poems get read as AI.** This is the false positive we most want to
avoid. Our stylometry signal treats even sentence lengths and low vocabulary variety as
"AI-uniform," because its reference ranges are tuned for ordinary prose. A poem with a
steady, repeating rhythm hits those same numbers on purpose, so stylometry pushes toward AI.
If the LLM also reads the poem as "AI-smooth," both signals agree and the score climbs. The
short-text cap saves most poems (nothing under 75 words can be called "likely AI"), but a
long, repetitive poem could still be misjudged. That is a real residual risk, and it is
exactly what the appeal path is for.

**2. Non-native (ESL) English writing skews toward AI.** A fluent non-native writer often
uses simpler vocabulary and more uniform sentence shapes. Stylometry reads that uniformity
as AI, and the LLM can read unusual phrasing as "off" and lean AI too. So both signals can
tip the same wrong way for the same group of real people. This is a fairness problem, not
just an accuracy one, because it would hit one group harder than others. The cautious
thresholds and the wide "uncertain" band keep most of these out of "likely AI," but we name
it openly instead of pretending the system is fair to everyone.

**3. Lists, recipes, and technical formats confuse the structure signal.** A recipe or a
bulleted list has very short, very uniform "sentences," so stylometry sees almost no
sentence-length variation and reads it as strongly AI. The reference ranges simply do not
fit structured text. Here the two-signal design usually helps: the LLM recognizes "this is a
recipe" and does not call it AI, the signals disagree, and our scoring turns that
disagreement into "uncertain" instead of a false accusation.

The pattern across all three: stylometry's cutoffs assume ordinary prose, so any genre that
is uniform for an innocent reason can look AI to it. The defenses are the same each time: the
short-text cap, the disagreement rule that pulls toward "uncertain," and the appeal path for
when the automated call is still wrong.

---

## Spec Reflection

**One way the spec helped.** The assignment made one point loudly: labeling a real person's
writing as AI is the worst mistake this system can make. That single idea drove the core of
the scoring. It is why the bar to call something "likely AI" (0.80 confidence) sits higher
than the bar to call it "likely human" (0.70), why short text can never reach a confident
"AI" call, and why two signals that disagree get pulled toward "uncertain" instead of forced
into a guess. Left to my own devices, the natural thing to build is a symmetric detector that
treats both mistakes as equal. The spec stopped me from doing that.

**One way my build diverged from my plan.** My [planning.md](planning.md) gave the
vocabulary-variety measure (type-token ratio) a weight of 0.25 in the stylometry score, with
a "human" cutoff at 0.65. When I built it and tested on real text at realistic lengths (40 to
90 words), that measure scored 0.0 on every sample, including clearly AI ones. Short text
does not give words enough chances to repeat, so the ratio always looked "human" and never
added AI evidence. So I diverged from my own plan: I dropped its weight to 0.15, moved its
human cutoff up to 0.75 so it still fires on genuinely repetitive text, and shifted the freed
weight to sentence-length variation, the most reliable tell. The plan was a reasonable guess;
testing showed it was wrong, so the build won.

---

## AI Usage

I used an AI coding tool throughout, but on a short leash: I handed it one spec section at a
time, asked for one focused piece, and checked that piece on its own before wiring it in. Two
specific instances where I changed what it produced:

**1. Re-weighting the stylometry score.** I directed the AI to build the stylometry scorer to
my plan: four measurements (sentence-length variation, vocabulary variety, sentence
complexity, punctuation) blended into one 0-to-1 score with the weights I had written down. It
produced exactly that, faithfully, including the vocabulary measure at weight 0.25. When I ran
real samples through it, that measure scored 0.0 across the board and flattened the results. I
overrode the numbers: I re-weighted the measurements (vocabulary 0.25 down to 0.15,
sentence-length variation 0.40 up to 0.50) and moved a cutoff, based on my own testing rather
than the AI's spec-faithful version. I kept its structure and changed its judgment.

**2. Naming the submission endpoint.** I directed the AI to help draft the architecture and
API surface in planning.md. Its early draft named the main endpoint `/analyze`. I revised it
to `/submit`, to match the assignment's "submission endpoint" and because it reads plainer to
a platform integrator: you submit a piece of writing, and the service does the analyzing. A
small change, but I made it deliberately and renamed it everywhere so the code, the plan, and
the docs all agree.

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
