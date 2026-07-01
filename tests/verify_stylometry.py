"""Standalone check for Signal 2 (stylometry), plus a side-by-side with Signal 1.

Two parts:
  1. Test stylometry on its own. Pure Python, no API. Runs it on the same
     inputs used for Signal 1, confirms the output shape, and shows that
     AI-leaning and human-leaning text get clearly different scores.
  2. Run both signals on those same inputs and see where they agree and where
     they disagree. Part 2 calls the Groq API (Signal 1), so it needs
     GROQ_API_KEY and spends a few requests of quota.

Run from the project root:
    .venv/bin/python tests/verify_stylometry.py            # part 1 only
    .venv/bin/python tests/verify_stylometry.py --compare  # parts 1 and 2
"""

import json
import os
import sys

# Make the project root importable (this file lives in tests/, root is one up).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the tests dir

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))  # put GROQ_API_KEY in the env

from signals.stylometry import classify_with_stylometry  # noqa: E402

# Reuse the exact same inputs Signal 1 was checked on, so the comparison is fair.
from verify_signal import CASES  # noqa: E402


def shape_ok(result):
    """True if the stylometry result has the exact keys and types our spec promises."""
    return (
        isinstance(result, dict)
        and isinstance(result.get("score"), (int, float))
        and 0.0 <= result["score"] <= 1.0
        and result.get("verdict") in ("ai", "human")
        and isinstance(result.get("metrics"), dict)
    )


def _llm_ai(llm):
    """Put Signal 1 on the 0-to-1 AI-leaning scale (planning.md, combine step 1).

    verdict "ai"    -> 0.5 + 0.5 * confidence
    verdict "human" -> 0.5 - 0.5 * confidence
    """
    if llm["verdict"] == "ai":
        return 0.5 + 0.5 * llm["confidence"]
    return 0.5 - 0.5 * llm["confidence"]


def part1_standalone():
    """Run Signal 2 by itself on every case and print the result + shape check."""
    print("########## PART 1: stylometry standalone (no API) ##########\n")
    for name, text in CASES:
        result = classify_with_stylometry(text)
        print(f"=== {name} ===")
        print(json.dumps(result, indent=2))
        print("shape_ok:", shape_ok(result))
        print()


def part2_compare():
    """Run both signals on the same inputs and report agree / disagree."""
    from signals.llm import classify_with_llm  # imported here so part 1 needs no key

    print("########## PART 2: Signal 1 vs Signal 2 on the same inputs ##########")
    print("(scale: 0.0 = reads human, 1.0 = reads AI)\n")
    for name, text in CASES:
        llm = classify_with_llm(text)
        sty = classify_with_stylometry(text)
        llm_ai = _llm_ai(llm)
        sty_ai = sty["score"]
        agree = llm["verdict"] == sty["verdict"]
        gap = abs(llm_ai - sty_ai)

        print(f"=== {name} ===")
        print(
            f"  Signal 1 (LLM):        verdict={llm['verdict']:5s} "
            f"confidence={llm['confidence']:.2f}  -> llm_ai={llm_ai:.2f}"
        )
        print(
            f"  Signal 2 (stylometry): verdict={sty['verdict']:5s} "
            f"score={sty_ai:.2f}        -> sty_ai={sty_ai:.2f}"
        )
        print(f"  {'AGREE' if agree else 'DISAGREE'} on verdict | "
              f"disagreement (gap on AI scale) = {gap:.2f}")
        print()


def main():
    part1_standalone()
    if "--compare" in sys.argv:
        part2_compare()
    else:
        print("(Run with --compare to also test against Signal 1 via Groq.)")


if __name__ == "__main__":
    main()
