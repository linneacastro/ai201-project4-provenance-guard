"""Confidence Scorer: turn two signals into one answer.

This is the aggregator from planning.md, "Confidence Scoring: From Two Signals
to One Answer". It takes Signal 1 (Groq LLM) and Signal 2 (stylometry) and runs
the six combine steps to produce one attribution (likely_ai, likely_human, or
uncertain) and one confidence score from 0 to 1.

The whole way through it keeps ONE internal number, an AI-leaning score from 0
to 1: 0.0 = reads fully human, 1.0 = reads fully AI, 0.5 = no idea.

The design is cautious on purpose (planning.md, "Design for the Worst Case"):
disagreement pulls the score toward the middle, short text caps confidence, and
the bar to call "AI" (0.80) is higher than the bar to call "human" (0.70),
because calling a real person's work AI is the worst mistake.
"""

# Combine step 2: the LLM judges meaning (the richer signal) so it gets the
# bigger vote, but stylometry's 0.4 is a real vote, not just a tiebreaker.
LLM_WEIGHT = 0.6
STY_WEIGHT = 0.4

# Combine step 6: the attribution thresholds. The AI bar is higher than the
# human bar. That asymmetry is the whole false-positive defense in one line.
AI_THRESHOLD = 0.80
HUMAN_THRESHOLD = 0.70

# Combine step 5: short text means less to go on, so cap how sure we allow
# ourselves to be. Under 25 words never gets past "uncertain"; under 75 words
# can reach "likely human" but never "likely AI".
SHORT_TEXT_CEILINGS = (
    (25, 0.65),   # n < 25  -> ceiling 0.65
    (75, 0.75),   # n < 75  -> ceiling 0.75
)                 # n >= 75 -> no ceiling


def _llm_ai_scale(llm):
    """Combine step 1: put the LLM on the 0-to-1 AI-leaning scale.

    verdict "ai"    -> 0.5 + 0.5 * confidence   (0.5 up toward 1.0)
    verdict "human" -> 0.5 - 0.5 * confidence   (0.5 down toward 0.0)
    So "ai, 0.7 sure" -> 0.85, "human, 0.8 sure" -> 0.10, a 0.5 stays neutral.
    """
    confidence = llm["confidence"]
    if llm["verdict"] == "ai":
        return 0.5 + 0.5 * confidence
    return 0.5 - 0.5 * confidence


def _short_text_ceiling(word_count):
    """Combine step 5: the confidence ceiling for this text length, or None."""
    for limit, ceiling in SHORT_TEXT_CEILINGS:
        if word_count < limit:
            return ceiling
    return None


def combine_signals(llm, stylometry, word_count):
    """Run the six combine steps and return the attribution + confidence.

    Args:
        llm: Signal 1 result, {"verdict": "ai"|"human", "confidence": 0-1, ...}.
        stylometry: Signal 2 result, {"score": 0-1 (AI-leaning), ...}.
        word_count: number of words in the text (for the short-text cap).

    Returns a dict:
        {
          "attribution": "likely_ai" | "likely_human" | "uncertain",
          "confidence": float 0-1 (how sure, not which way),
          "direction": "ai" | "human",
          "adj_ai": float 0-1 (the internal AI-leaning score after adjustment),
          "details": { ...every intermediate value, for transparency... }
        }
    """
    # Step 1: both signals onto the 0-to-1 AI-leaning scale.
    llm_ai = _llm_ai_scale(llm)
    sty_ai = stylometry["score"]

    # Step 2: weighted blend.
    raw_ai = LLM_WEIGHT * llm_ai + STY_WEIGHT * sty_ai

    # Step 3: let disagreement pull the score toward the middle (0.5).
    disagreement = abs(llm_ai - sty_ai)
    adj_ai = raw_ai + (0.5 - raw_ai) * disagreement

    # Step 4: read off how sure we are, and which way.
    confidence = 0.5 + abs(adj_ai - 0.5)
    direction = "ai" if adj_ai > 0.5 else "human"

    # Step 5: cap confidence on short text.
    ceiling = _short_text_ceiling(word_count)
    if ceiling is not None:
        confidence = min(confidence, ceiling)

    # Step 6: pick the attribution. Thresholds run on the full-precision
    # confidence so a value like 0.7999 is not rounded up over the bar.
    if direction == "ai" and confidence >= AI_THRESHOLD:
        attribution = "likely_ai"
    elif direction == "human" and confidence >= HUMAN_THRESHOLD:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    return {
        "attribution": attribution,
        "confidence": round(confidence, 2),
        "direction": direction,
        "adj_ai": round(adj_ai, 4),
        "details": {
            "llm_ai": round(llm_ai, 4),
            "sty_ai": round(sty_ai, 4),
            "raw_ai": round(raw_ai, 4),
            "disagreement": round(disagreement, 4),
            "confidence_uncapped": round(0.5 + abs(adj_ai - 0.5), 4),
            "confidence_ceiling": ceiling,
            "word_count": word_count,
        },
    }
