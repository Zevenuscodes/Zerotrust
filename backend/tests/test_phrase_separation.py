"""Does fixed-phrase scoring actually separate different people?

This is the question the free-text engine cannot answer. It runs against
SIMULATED typists, so it proves the scoring maths discriminates when a real
per-character signature exists -- it is NOT evidence about real humans.
For that, collect real data with eval_accuracy.py. Treat this as a
regression guard on the scorer, not as an accuracy result.

    python backend/tests/test_phrase_separation.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.config import settings  # noqa: E402
from app.phrase_auth import score_attempt  # noqa: E402

PHRASE = "the quick zero trust fox verifies every packet"
N = len(PHRASE)
rng = np.random.default_rng(5)


def typist(seed, base_dwell, base_flight, inconsistency=0.18):
    """A person: a stable per-character signature (muscle memory) plus
    run-to-run inconsistency."""
    r = np.random.default_rng(seed)
    char_dwell = r.normal(base_dwell, base_dwell * 0.22, N)
    char_flight = r.normal(base_flight, base_flight * 0.30, N)

    def attempt():
        d = char_dwell * rng.normal(1, inconsistency, N)
        f = char_flight * rng.normal(1, inconsistency, N)
        return {
            "phrase": PHRASE,
            "dwell_ms": [max(15.0, float(x)) for x in d],
            "flight_ms": [None] + [max(10.0, float(x)) for x in f[1:]],
        }

    return attempt


def main():
    genuine = typist(1, 95, 150)
    impostors = {
        "slower typist": typist(2, 130, 210),
        "faster typist": typist(3, 72, 110),
        "same avg speed": typist(4, 96, 152),  # only the signature differs
    }

    enrolled = [genuine() for _ in range(5)]
    g = [score_attempt(genuine(), enrolled)[0] for _ in range(8)]

    print(f"\n  genuine            : {' '.join(f'{s:3.0f}' for s in sorted(g, reverse=True))}")
    imp = []
    for name, fn in impostors.items():
        s = [score_attempt(fn(), enrolled)[0] for _ in range(8)]
        imp += s
        print(f"  impostor {name:<10}: {' '.join(f'{x:3.0f}' for x in sorted(s, reverse=True))}")

    t = settings.phrase_verify_threshold
    frr = sum(1 for s in g if s < t) / len(g)
    far = sum(1 for s in imp if s >= t) / len(imp)
    print(f"\n  worst genuine {min(g):.0f}  |  best impostor {max(imp):.0f}")
    print(f"  at threshold {t:.0f}:  FRR {frr:.0%}   FAR {far:.0%}")

    failures = []
    if min(g) <= max(imp):
        failures.append(f"no separation: genuine {min(g):.0f} <= impostor {max(imp):.0f}")
    if frr > 0.10:
        failures.append(f"FRR {frr:.0%} too high at threshold {t:.0f}")
    if far > 0.20:
        failures.append(f"FAR {far:.0%} too high at threshold {t:.0f}")
    # the signature-only impostor is the one averaging would miss entirely
    same_speed = [score_attempt(impostors["same avg speed"](), enrolled)[0] for _ in range(8)]
    if sum(1 for s in same_speed if s >= t) / len(same_speed) > 0.25:
        failures.append("an impostor with matching average speed is getting through")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\n  separation holds (simulated typists only -- not a real-world accuracy claim)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
