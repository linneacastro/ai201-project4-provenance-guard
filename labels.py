"""Transparency labels: the exact words a reader sees under a piece of writing.

Three variants, drafted in planning.md ("Transparency Labels") and copied here
verbatim. The scoring step (scoring.py) already turned confidence and direction
into one attribution, so this module only maps that attribution to its label.
Keeping the confidence thresholds in one place (scoring.py) means the label can
never disagree with the confidence band it came from.

Because attribution is set by the confidence bands (likely_ai needs confidence
>= 0.80, likely_human needs >= 0.70, everything else is uncertain), the label
this returns changes with the confidence score. That is the required behavior:
a 0.51 result and a 0.95 result do not show the same words.

Each variant has a short badge (shown inline) and the full text (shown on
tap/hover, or beside the work). The full text is the graded deliverable.
"""

# Keyed by attribution (the scoring.py output). Each value is what /submit
# returns under "label" and what the audit log stores as label_variant + text.
_LABELS = {
    "likely_ai": {
        "variant": "high_confidence_ai",
        "badge": "🤖 Reads as AI-generated",
        "text": (
            "🤖 This reads as AI-generated. Our automated check thinks this was "
            "most likely written with AI help. How it reads and how it's put "
            "together both point that way. This is an automated guess about the "
            "text, not a proven fact, and not a judgment of the writer. If you "
            "wrote this yourself, you can appeal, and it will be marked "
            "\"under review\" while a person takes a look."
        ),
    },
    "likely_human": {
        "variant": "high_confidence_human",
        "badge": "✍️ Reads as human-written",
        "text": (
            "✍️ This reads as human-written. Our automated check thinks a person "
            "most likely wrote this. How it reads and how it's put together both "
            "point that way. This is still an automated guess, not a proven "
            "fact. If something looks wrong, you can appeal, and it will be "
            "marked \"under review.\""
        ),
    },
    "uncertain": {
        "variant": "uncertain",
        "badge": "❓ Not sure who wrote this",
        "text": (
            "❓ We're not sure who wrote this. Our automated check could not tell "
            "whether a person or AI wrote this. The signs were weak or pointed "
            "in different directions, so we are not making a call. Treat this as "
            "context, not an answer. If you'd like a person to take a look, you "
            "can appeal, and it will be marked \"under review.\""
        ),
    },
}


def label_for(attribution):
    """Return the transparency label for an attribution.

    Args:
        attribution: "likely_ai", "likely_human", or "uncertain" (from
            scoring.combine_signals).

    Returns a dict {"variant": str, "badge": str, "text": str}. An unknown
    attribution falls back to the uncertain label, the safe, non-committal one.
    """
    return _LABELS.get(attribution, _LABELS["uncertain"])
