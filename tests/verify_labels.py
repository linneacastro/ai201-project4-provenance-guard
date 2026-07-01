"""Check the transparency label function against the planning.md spec.

Confirms all three variants are reachable, each maps from the right attribution,
each carries the right badge and lead emoji, and each text offers the appeal
path. Prints the full text of every variant so it can be eyeballed against
planning.md ("Transparency Labels").

No API calls, no Groq. Run from the project root:
    .venv/bin/python tests/verify_labels.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from labels import label_for  # noqa: E402

# attribution -> (expected variant, expected lead emoji)
CASES = [
    ("likely_ai", "high_confidence_ai", "🤖"),
    ("likely_human", "high_confidence_human", "✍️"),
    ("uncertain", "uncertain", "❓"),
]


def main():
    failures = []
    texts = []

    print("########## Transparency label variants ##########\n")
    for attribution, want_variant, want_emoji in CASES:
        label = label_for(attribution)
        variant = label["variant"]
        badge = label["badge"]
        text = label["text"]
        texts.append(text)

        print(f"=== {attribution} -> {variant} ===")
        print(f"  badge: {badge}")
        print(f"  text : {text}\n")

        if variant != want_variant:
            failures.append(f"{attribution}: variant {variant!r} != {want_variant!r}")
        if not badge.startswith(want_emoji):
            failures.append(f"{attribution}: badge missing {want_emoji}")
        if not text.startswith(want_emoji):
            failures.append(f"{attribution}: text missing lead {want_emoji}")
        # Every label must offer the appeal path (a design rule in planning.md).
        if "appeal" not in text.lower():
            failures.append(f"{attribution}: text does not offer the appeal path")
        if "under review" not in text.lower():
            failures.append(f"{attribution}: text does not mention 'under review'")

    # The three variants must be genuinely different words, not one string.
    if len(set(texts)) != 3:
        failures.append("the three variant texts are not all distinct")

    # An unknown attribution falls back to the safe 'uncertain' label.
    if label_for("bananas")["variant"] != "uncertain":
        failures.append("unknown attribution did not fall back to uncertain")

    print("########## Result ##########")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("  PASS: all three variants reachable, distinct, and spec-shaped.")


if __name__ == "__main__":
    main()
