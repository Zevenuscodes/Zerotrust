"""Measure whether fixed-phrase verification actually separates people.

This answers the question the rest of the project does not: a system that
detects "typing changed" is not the same as one that detects "different
person". Without genuine-vs-impostor data there is no evidence of the
latter, so nothing here should be claimed as accuracy until this has been
run on real people.

Reports the standard biometric metrics:
  FAR  false accept rate  -- impostors wrongly let in
  FRR  false reject rate  -- the genuine user wrongly challenged again
  EER  equal error rate   -- threshold where FAR == FRR (lower is better)

Usage
-----
Collect data first (one JSON file per person, several attempts each):

    python backend/tests/eval_accuracy.py collect --user alice --out data/
      -> prompts you to type the phrase N times, saves alice.json

Have at least one other person do the same, then:

    python backend/tests/eval_accuracy.py report --dir data/ --genuine alice

Every attempt by `alice` is scored against alice's enrolled profile
(leave-one-out, so an attempt is never scored against itself); every
attempt by everyone else is scored against it as an impostor.
"""

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.phrase_auth import MIN_ENROLLMENTS, score_attempt  # noqa: E402

PHRASE = "the quick zero trust fox verifies every packet"


def collect(user: str, out_dir: str, attempts: int) -> None:
    """Capture timings from a real keyboard. Uses raw terminal mode so each
    keypress is read individually -- dwell time cannot be recovered from a
    line of text after the fact."""
    import termios
    import tty

    os.makedirs(out_dir, exist_ok=True)
    print(f"\nTyping test for '{user}'. Type the phrase {attempts} times.")
    print("Type it naturally. A typo restarts that attempt.\n")
    print(f"  {PHRASE}\n")

    samples = []
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        for n in range(1, attempts + 1):
            while True:
                print(f"attempt {n}/{attempts}: ", end="", flush=True)
                dwell, flight = [], []
                last_up = None
                ok = True
                tty.setraw(fd)
                for expected in PHRASE:
                    ch = sys.stdin.read(1)
                    down = time.perf_counter() * 1000
                    # terminals deliver press+release together, so dwell is
                    # measured to the next event rather than a true keyup
                    if ch != expected:
                        ok = False
                        break
                    flight.append(None if last_up is None else down - last_up)
                    up = time.perf_counter() * 1000
                    dwell.append(up - down)
                    last_up = up
                    sys.stdout.write(ch)
                    sys.stdout.flush()
                termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                print()
                if ok:
                    samples.append({"phrase": PHRASE, "dwell_ms": dwell, "flight_ms": flight})
                    break
                print("  typo -- retrying this attempt")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    path = os.path.join(out_dir, f"{user}.json")
    with open(path, "w") as f:
        json.dump({"user": user, "phrase": PHRASE, "samples": samples}, f, indent=2)
    print(f"\nsaved {len(samples)} attempts to {path}")


def report(data_dir: str, genuine_user: str) -> int:
    files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    people = {}
    for p in files:
        with open(p) as f:
            d = json.load(f)
        people[d["user"]] = d["samples"]

    if genuine_user not in people:
        print(f"no data for '{genuine_user}' in {data_dir} (found: {list(people)})")
        return 1
    impostors = {u: s for u, s in people.items() if u != genuine_user}
    if not impostors:
        print("\nOnly one person's data present.")
        print("FAR cannot be measured without at least one other person --")
        print("this is exactly the gap the project has. Collect a second user.")
        return 1

    genuine = people[genuine_user]
    if len(genuine) < MIN_ENROLLMENTS + 1:
        print(f"need at least {MIN_ENROLLMENTS + 1} genuine attempts, have {len(genuine)}")
        return 1

    # leave-one-out so an attempt is never scored against a profile containing itself
    genuine_scores = []
    for i, attempt in enumerate(genuine):
        profile = [s for j, s in enumerate(genuine) if j != i]
        genuine_scores.append(score_attempt(attempt, profile)[0])

    impostor_scores = []
    for user, samples in impostors.items():
        for attempt in samples:
            impostor_scores.append((user, score_attempt(attempt, genuine)[0]))

    print(f"\nProfile: {genuine_user}  ({len(genuine)} enrolled attempts)")
    print(f"genuine scores : {', '.join(f'{s:.0f}' for s in sorted(genuine_scores, reverse=True))}")
    for user in impostors:
        s = sorted((sc for u, sc in impostor_scores if u == user), reverse=True)
        print(f"impostor {user:<8}: {', '.join(f'{x:.0f}' for x in s)}")

    imp = [s for _, s in impostor_scores]
    print(f"\n{'thresh':>7} {'FRR':>7} {'FAR':>7}")
    best, eer = None, None
    for t in range(0, 101, 5):
        frr = sum(1 for s in genuine_scores if s < t) / len(genuine_scores)
        far = sum(1 for s in imp if s >= t) / len(imp)
        print(f"{t:>7} {frr:>6.0%} {far:>6.0%}")
        gap = abs(frr - far)
        if best is None or gap < best:
            best, eer = gap, (t, (frr + far) / 2)

    print(f"\nEER ~ {eer[1]:.0%} at threshold {eer[0]}")
    print(f"(separation: worst genuine {min(genuine_scores):.0f} vs best impostor {max(imp):.0f})")
    if min(genuine_scores) > max(imp):
        print("Clean separation -- no threshold confuses the two sets.")
    else:
        print("Overlap present: some impostor attempts score above some genuine ones.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--user", required=True)
    c.add_argument("--out", default="phrase_data")
    c.add_argument("--attempts", type=int, default=6)
    r = sub.add_parser("report")
    r.add_argument("--dir", default="phrase_data")
    r.add_argument("--genuine", required=True)
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.user, a.out, a.attempts)
        return 0
    return report(a.dir, a.genuine)


if __name__ == "__main__":
    sys.exit(main())
