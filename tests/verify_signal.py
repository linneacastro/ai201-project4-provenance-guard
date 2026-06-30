"""Manual check for Signal 1 (Groq), run before and after wiring it into /analyze.

Calls classify_with_llm directly on a few inputs and prints each result so the
verdicts and the shape can be eyeballed. This makes real Groq API calls, so it
needs GROQ_API_KEY in .env and spends a few requests of quota.

Run from the project root:
    .venv/bin/python tests/verify_signal.py
"""

import json
import os
import sys

# Make the project root importable and find its .env, no matter where this is
# run from (this file lives in tests/, so the root is one level up).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))  # put GROQ_API_KEY in the env

from signals.llm import classify_with_llm  # noqa: E402

HUMAN = (
    "My grandmother kept her buttons in an old cookie tin, the blue one with the "
    "snowman that had long since lost his carrot nose. Rainy afternoons, she'd "
    "dump them out on the kitchen table and we'd sort them by color, then by "
    "size, then by whatever rule she made up that day. I never asked why. It just "
    "felt like the kind of thing you did when the sky went gray and the bread was "
    "rising and there was nowhere else you needed to be."
)

AI = (
    "Artificial intelligence is transforming the way we live and work in today's "
    "fast-paced world. From healthcare to finance, AI-powered solutions are "
    "streamlining processes and improving efficiency across a wide range of "
    "industries. As these technologies continue to evolve, it is important to "
    "consider both the benefits and the challenges they present. By embracing "
    "innovation responsibly, we can ensure that artificial intelligence serves "
    "the needs of society as a whole."
)

CASES = [
    ("clearly human paragraph", HUMAN),
    ("clearly AI paragraph", AI),
    ("very short text", "The cat sat."),
    ("empty string", ""),
]


def shape_ok(result):
    """True if the result has the exact keys and types our spec promises."""
    return (
        isinstance(result, dict)
        and result.get("verdict") in ("ai", "human")
        and isinstance(result.get("confidence"), float)
        and 0.0 <= result["confidence"] <= 1.0
        and isinstance(result.get("reasoning"), str)
    )


def main():
    for name, text in CASES:
        result = classify_with_llm(text)
        print(f"=== {name} ===")
        print(json.dumps(result, indent=2))
        print("shape_ok:", shape_ok(result))
        print()


if __name__ == "__main__":
    main()
