"""Unit check for the confidence scorer, no API needed.

Runs the worked-examples table from planning.md ("Confidence Scoring") straight
through combine_signals and checks that adj_ai, confidence, and attribution all
match the spec. Then checks the two things this milestone asks for:

  1. The score varies meaningfully: a clearly AI (uniform) input and a clearly
     human (irregular) input produce clearly different scores.
  2. At least three distinct label categories are reachable across the table.

Run from the project root:
    .venv/bin/python tests/verify_scoring.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scoring import combine_signals  # noqa: E402


def _llm(verdict, confidence):
    return {"verdict": verdict, "confidence": confidence, "reasoning": "test"}


def _sty(score):
    return {"score": score, "verdict": "ai" if score > 0.5 else "human", "metrics": {}}


# The worked-examples table from planning.md. Each row is the inputs plus the
# expected outputs (rounded to two decimals, as the table is).
#   name, llm_verdict, llm_conf, sty_score, word_count,
#   expected_adj_ai, expected_confidence, expected_attribution
CASES = [
    ("Clear AI essay, both agree",        "ai",    0.90, 0.85, 75, 0.87, 0.87, "likely_ai"),
    ("Clear human essay, both agree",     "human", 0.85, 0.20, 75, 0.17, 0.83, "likely_human"),
    ("Model says AI, stats say human",    "ai",    0.90, 0.15, 75, 0.53, 0.53, "uncertain"),
    ("Weak lean (the API sample)",        "ai",    0.70, 0.40, 75, 0.59, 0.59, "uncertain"),
    ("Short, strong AI poem (40 words)",  "ai",    0.85, 0.90, 40, 0.90, 0.75, "uncertain"),
]


def run_table():
    """Run every worked example and check the numbers. Returns (results, all_ok)."""
    results = []
    all_ok = True
    print("########## Worked-examples table (from planning.md) ##########\n")
    print(f"{'scenario':<34} {'adj_ai':>7} {'conf':>6} {'attribution':<14} {'ok'}")
    print("-" * 72)
    for (name, v, c, s, n, exp_adj, exp_conf, exp_attr) in CASES:
        r = combine_signals(_llm(v, c), _sty(s), n)
        got_adj = round(r["adj_ai"], 2)
        got_conf = round(r["confidence"], 2)
        got_attr = r["attribution"]
        ok = (got_adj == exp_adj and got_conf == exp_conf and got_attr == exp_attr)
        all_ok = all_ok and ok
        results.append((name, r))
        flag = "PASS" if ok else f"FAIL (want {exp_adj}/{exp_conf}/{exp_attr})"
        print(f"{name:<34} {got_adj:>7.2f} {got_conf:>6.2f} {got_attr:<14} {flag}")
    print()
    return results, all_ok


def check_criteria(results):
    """Check the two milestone criteria: meaningful spread + 3 label categories."""
    print("########## Milestone criteria ##########\n")

    by_name = {name: r for name, r in results}
    ai_score = by_name["Clear AI essay, both agree"]["adj_ai"]
    human_score = by_name["Clear human essay, both agree"]["adj_ai"]
    spread = round(ai_score - human_score, 2)
    spread_ok = spread >= 0.30
    print(f"1. Meaningful spread: clear AI adj_ai={ai_score:.2f} vs "
          f"clear human adj_ai={human_score:.2f} -> spread {spread:.2f}")
    print(f"   {'PASS' if spread_ok else 'FAIL'}: uniform and irregular text land far apart\n")

    categories = {r["attribution"] for _, r in results}
    wanted = {"likely_ai", "likely_human", "uncertain"}
    categories_ok = wanted.issubset(categories)
    print(f"2. Distinct label categories reached: {sorted(categories)}")
    print(f"   {'PASS' if categories_ok else 'FAIL'}: all three of {sorted(wanted)} reachable\n")

    return spread_ok and categories_ok


def main():
    results, table_ok = run_table()
    criteria_ok = check_criteria(results)
    print("=" * 72)
    if table_ok and criteria_ok:
        print("ALL CHECKS PASSED: scorer matches planning.md and the milestone criteria.")
    else:
        print("SOME CHECKS FAILED (see above).")
        sys.exit(1)


if __name__ == "__main__":
    main()
