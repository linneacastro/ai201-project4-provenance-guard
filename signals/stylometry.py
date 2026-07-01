"""Detection Signal 2: Stylometry (structure).

Pure-Python measurements of the text, no model and no external libraries. It
measures four things, maps each to a 0-to-1 "AI-likeness", then takes a
weighted average. Higher = more even and uniform = more AI-like. This is the
"structure" signal in planning.md.

Output shape (matches planning.md, "What each signal hands us"):
    {"score": 0.0-1.0, "verdict": "ai" | "human", "metrics": { ... }}

`score` is the AI-leaning number directly: higher = more uniform = more AI-like.
The confidence scorer (M4) uses `score` as-is on the 0-to-1 AI-leaning scale.
"""

import re
import statistics

# Each measurement's weight in the final score. Sentence-length variation
# carries the most weight (most reliable tell); punctuation the least (easiest
# to read wrong). From planning.md, "How stylometry turns four measurements
# into one score".
#
# Milestone 4 recalibration: vocabulary variety dropped from 0.25 to 0.15 and
# sentence-length variation rose from 0.40 to 0.50. Testing on real text showed
# the type-token ratio read "fully human" on every sample (see REF_RANGES note),
# so it was near-dead weight; the reliable length tell earns more of the vote.
WEIGHTS = {
    "length_variation": 0.50,
    "vocab_variety": 0.15,
    "complexity": 0.20,
    "punctuation": 0.15,
}

# Reference ranges. Each pair maps a raw measurement to a 0-to-1 AI-likeness:
# at "human_at" (or above) it reads human (0.0); at "ai_at" (or below) it reads
# AI (1.0); linear in between. Every measurement has the same orientation: a
# higher raw value means more human. These are tuned heuristics, NOT ground
# truth (planning.md warns they can be wrong on poetry, lists, short text).
#
# - length_variation uses the exact range from planning.md.
# - vocab_variety was recalibrated in Milestone 4. The old range (human >= 0.65)
#   scored real text as 0.0 (fully human) almost every time, because raw TTR
#   runs high on short text and modern AI uses varied vocabulary. The "human"
#   band moved up to 0.75 so the metric still fires when text is genuinely
#   repetitive, which is when TTR is actually a useful AI tell.
# - complexity and punctuation are only described in planning.md as "even -> AI,
#   lumpy -> human" and "plain -> AI", so these concrete cutoffs are our own
#   reasonable guesses.
REF_RANGES = {
    "length_variation": {"human_at": 0.60, "ai_at": 0.10},  # CV of words/sentence
    "vocab_variety":    {"human_at": 0.75, "ai_at": 0.45},  # type-token ratio
    "complexity":       {"human_at": 0.75, "ai_at": 0.15},  # CV of clauses/sentence
    "punctuation":      {"human_at": 0.20, "ai_at": 0.05},  # punctuation per word
}

# A sentence ends at . ! ? or a line break. Words are runs of letters (with
# apostrophes for contractions). Clause separators split a sentence into parts.
# Punctuation is any character that is not a word character or whitespace.
_SENTENCE_SPLIT = re.compile(r"[.!?\n]+")
_WORD = re.compile(r"[A-Za-z']+")
_CLAUSE_SEP = re.compile(r"[,;:]")
_PUNCT = re.compile(r"[^\w\s]")

# When there is not enough text to measure something (for example, only one
# sentence, so length cannot vary), that measurement gives no evidence either
# way, so it contributes a neutral 0.5.
_NEUTRAL = 0.5


def _ai_likeness(value, human_at, ai_at):
    """Map one raw measurement to a 0-to-1 AI-likeness.

    value >= human_at -> 0.0 (reads human)
    value <= ai_at    -> 1.0 (reads AI)
    linear in between. Assumes human_at > ai_at (a higher value = more human).
    """
    if value >= human_at:
        return 0.0
    if value <= ai_at:
        return 1.0
    return (human_at - value) / (human_at - ai_at)


def _cv(values):
    """Coefficient of variation (spread / mean) for a list of numbers.

    Returns None when it cannot be measured (fewer than two values, or a mean
    of zero). CV is unitless, so it compares sentence patterns fairly across
    texts of different sizes.
    """
    if len(values) < 2:
        return None
    mean = statistics.mean(values)
    if mean == 0:
        return None
    return statistics.pstdev(values) / mean


def classify_with_stylometry(text):
    """Run Signal 2 on a piece of text.

    Returns a dict:
        {"score": float 0.0-1.0, "verdict": "ai"|"human", "metrics": {...}}

    `score` is the AI-leaning number (higher = more uniform = more AI-like).
    `verdict` is "ai" when score > 0.5, else "human" (a tie leans to the safer
    "human"). `metrics` holds the raw measurements and the per-measurement
    sub-scores, so the result is transparent for the audit log and reviewers.

    Empty or whitespace-only text has nothing to measure, so it comes back
    neutral (score 0.5, verdict "human").
    """
    if not text or not text.strip():
        return {
            "score": _NEUTRAL,
            "verdict": "human",
            "metrics": {
                "word_count": 0,
                "sentence_count": 0,
                "note": "No text to measure.",
            },
        }

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    words_all = _WORD.findall(text.lower())
    word_count = len(words_all)

    # Words per sentence and clauses per sentence, counting only sentences that
    # actually contain words (so "..." or stray punctuation does not skew it).
    words_per_sentence = []
    clauses_per_sentence = []
    for s in sentences:
        n_words = len(_WORD.findall(s))
        if n_words == 0:
            continue
        words_per_sentence.append(n_words)
        clauses_per_sentence.append(1 + len(_CLAUSE_SEP.findall(s)))

    # 1. Sentence-length variation (CV of words per sentence).
    length_cv = _cv(words_per_sentence)
    length_ai = (
        _NEUTRAL if length_cv is None
        else _ai_likeness(length_cv, **REF_RANGES["length_variation"])
    )

    # 2. Vocabulary variety (type-token ratio).
    ttr = len(set(words_all)) / word_count if word_count else None
    vocab_ai = (
        _NEUTRAL if ttr is None
        else _ai_likeness(ttr, **REF_RANGES["vocab_variety"])
    )

    # 3. Sentence complexity (CV of clauses per sentence).
    clause_cv = _cv(clauses_per_sentence)
    complexity_ai = (
        _NEUTRAL if clause_cv is None
        else _ai_likeness(clause_cv, **REF_RANGES["complexity"])
    )

    # 4. Punctuation density (punctuation marks per word).
    punct_count = len(_PUNCT.findall(text))
    punct_density = punct_count / word_count if word_count else 0.0
    punct_ai = _ai_likeness(punct_density, **REF_RANGES["punctuation"])

    subscores = {
        "length_variation": length_ai,
        "vocab_variety": vocab_ai,
        "complexity": complexity_ai,
        "punctuation": punct_ai,
    }
    score = sum(WEIGHTS[k] * subscores[k] for k in WEIGHTS)
    score = round(score, 4)

    metrics = {
        "word_count": word_count,
        "sentence_count": len(words_per_sentence),
        "sentence_length_cv": None if length_cv is None else round(length_cv, 4),
        "type_token_ratio": None if ttr is None else round(ttr, 4),
        "clauses_per_sentence_cv": None if clause_cv is None else round(clause_cv, 4),
        "punctuation_density": round(punct_density, 4),
        "subscores": {k: round(v, 4) for k, v in subscores.items()},
    }

    return {
        "score": score,
        "verdict": "ai" if score > 0.5 else "human",
        "metrics": metrics,
    }
