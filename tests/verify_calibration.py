"""Calibration check for the full pipeline: both signals + the scorer on real text.

Runs deliberately chosen inputs through Signal 1 (Groq), Signal 2 (stylometry),
and the confidence scorer, then shows every intermediate number so we can see if
the combined score matches intuition, and if not, which signal is misbehaving.

Inputs: the four from the milestone prompt (one clear AI, one clear human, two
borderline), plus two longer (75+ word) samples so the "likely_ai" label, which
the short-text cap blocks under 75 words, gets a fair test.

This calls the Groq API (Signal 1), so it needs GROQ_API_KEY and spends a few
requests of quota.

Run from the project root:
    .venv/bin/python tests/verify_calibration.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from signals.llm import classify_with_llm          # noqa: E402
from signals.stylometry import classify_with_stylometry  # noqa: E402
from scoring import combine_signals                # noqa: E402


# Each case: text, my intuition in words, and the attribution(s) I would accept
# as "matches intuition" once the short-text cap is taken into account.
CASES = [
    {
        "name": "Clear AI (provided, short)",
        "text": (
            "Artificial intelligence represents a transformative paradigm shift in "
            "modern society. It is important to note that while the benefits of AI "
            "are numerous, it is equally essential to consider the ethical "
            "implications. Furthermore, stakeholders across various sectors must "
            "collaborate to ensure responsible deployment."
        ),
        "intuition": "reads strongly AI, but it is short, so the cap should hold it at 'uncertain' (direction ai)",
        "accept": {"uncertain"},
    },
    {
        "name": "Clear human (provided, short)",
        "text": (
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium in "
            "it and i was thirsty for like three hours after. my friend got the "
            "spicy version and said it was better. probably won't go back unless "
            "someone drags me there"
        ),
        "intuition": "reads strongly human; short, but the human bar (0.70) fits under the 0.75 cap, so 'likely_human' is allowed",
        "accept": {"likely_human", "uncertain"},
    },
    {
        "name": "Borderline: formal human (short)",
        "text": (
            "The relationship between monetary policy and asset price inflation has "
            "been extensively studied in the literature. Central banks face a "
            "fundamental tension between their mandate for price stability and the "
            "unintended consequences of prolonged low interest rates on equity and "
            "real estate valuations."
        ),
        "intuition": "a real person, but polished and uniform, so stylometry may lean AI; want 'uncertain' or 'likely_human', never a confident AI call",
        "accept": {"uncertain", "likely_human"},
    },
    {
        "name": "Borderline: lightly edited AI (short)",
        "text": (
            "I've been thinking a lot about remote work lately. There are genuine "
            "tradeoffs — flexibility and no commute on one side, isolation and "
            "blurred work-life boundaries on the other. Studies show productivity "
            "varies widely by individual and role type."
        ),
        "intuition": "lightly edited AI, ambiguous by nature; it reads human to both signals, so 'uncertain' or the tolerable 'likely_human' both fit",
        "accept": {"uncertain", "likely_human"},
    },
    {
        "name": "Clear AI (added, 75+ words)",
        "text": (
            "In today's rapidly evolving digital landscape, organizations must "
            "continually adapt in order to remain competitive and relevant. By "
            "leveraging cutting-edge technologies and data-driven insights, "
            "businesses can unlock new opportunities for growth and innovation. It "
            "is important to recognize that sustained success in this environment "
            "requires a holistic approach that carefully considers both short-term "
            "objectives and long-term strategic goals. By fostering a culture of "
            "collaboration and continuous improvement, companies can navigate "
            "complex challenges effectively and consistently deliver meaningful "
            "value to stakeholders across the entire organization."
        ),
        "intuition": "moderately uniform AI with varied vocabulary; mixed structural evidence, so 'uncertain' is the honest landing",
        "accept": {"uncertain"},
    },
    {
        "name": "Strongly uniform AI (added, 75+ words)",
        "text": (
            "Our team is committed to delivering excellent results. Our team is "
            "focused on meeting every client need. Our team is dedicated to "
            "maintaining the highest standards. Our team is working hard to exceed "
            "all expectations. Our team is proud to support our valued customers. "
            "Our team is ready to tackle any new challenge. Our team is eager to "
            "build lasting business relationships. Our team is passionate about "
            "continuous learning and steady growth. Our team is confident in our "
            "long and proven track record. Our team is here to provide reliable "
            "ongoing support."
        ),
        "intuition": "long, repetitive, uniform sentence length: exactly what stylometry should catch; with the M4 fix this should reach 'likely_ai'",
        "accept": {"likely_ai"},
    },
    {
        "name": "Clear human (added, 75+ words)",
        "text": (
            "My dad taught me to change a tire in the Costco parking lot when I was "
            "seventeen, mostly because the spare had gone flat too and he thought "
            "that was hilarious. We ended up calling my uncle, who showed up an "
            "hour later with the wrong size wrench and a paper bag of tangerines. I "
            "honestly don't remember how we got home that night. I do remember the "
            "tangerines, and my dad laughing so hard he had to sit down on the "
            "curb. Some lessons stick sideways."
        ),
        "intuition": "long, casual, irregular, clearly human; should reach 'likely_human'",
        "accept": {"likely_human"},
    },
]


def main():
    rows = []
    all_match = True
    for case in CASES:
        text = case["text"]
        llm = classify_with_llm(text)
        sty = classify_with_stylometry(text)
        word_count = sty["metrics"].get("word_count", 0)
        result = combine_signals(llm, sty, word_count)
        d = result["details"]

        match = result["attribution"] in case["accept"]
        all_match = all_match and match

        print("=" * 74)
        print(case["name"], f"({word_count} words)")
        print(f"  intuition: {case['intuition']}")
        print("  --- signals, separately ---")
        print(
            f"  Signal 1 (LLM):        verdict={llm['verdict']:5s} "
            f"confidence={llm['confidence']:.2f}  -> llm_ai={d['llm_ai']:.2f}"
        )
        m = sty["metrics"]
        print(
            f"  Signal 2 (stylometry): verdict={sty['verdict']:5s} "
            f"score={sty['score']:.2f}        -> sty_ai={d['sty_ai']:.2f}"
        )
        print(
            f"      metrics: len_cv={m.get('sentence_length_cv')}, "
            f"ttr={m.get('type_token_ratio')}, "
            f"clause_cv={m.get('clauses_per_sentence_cv')}, "
            f"punct={m.get('punctuation_density')}"
        )
        if "subscores" in m:
            print(f"      subscores: {m['subscores']}")
        print("  --- combine ---")
        print(
            f"  raw_ai={d['raw_ai']:.2f}  disagreement={d['disagreement']:.2f}  "
            f"adj_ai={result['adj_ai']:.2f}"
        )
        print(
            f"  confidence: uncapped={d['confidence_uncapped']:.2f}  "
            f"ceiling={d['confidence_ceiling']}  final={result['confidence']:.2f}"
        )
        print(
            f"  => direction={result['direction']}, "
            f"attribution={result['attribution']}  "
            f"[{'MATCHES intuition' if match else 'INVESTIGATE'}]"
        )
        print()
        rows.append((case["name"], word_count, result["adj_ai"],
                     result["confidence"], result["attribution"], match))

    print("=" * 74)
    print("SUMMARY")
    print(f"{'case':<38}{'words':>6}{'adj_ai':>8}{'conf':>7}  {'attribution':<14}{'ok'}")
    print("-" * 74)
    for name, wc, adj, conf, attr, match in rows:
        print(f"{name:<38}{wc:>6}{adj:>8.2f}{conf:>7.2f}  {attr:<14}"
              f"{'PASS' if match else 'CHECK'}")
    print()
    print("All matched intuition." if all_match else
          "Some did not match; see the INVESTIGATE lines above.")


if __name__ == "__main__":
    main()
