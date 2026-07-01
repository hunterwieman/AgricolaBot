"""Random-play fuzz test for the card system — surface crashes / soft-locks fast.

Plays a large number of 2-player CARD-mode games with a random agent whose
worker placement is *biased* toward the two card-play spaces so cards actually
get played:

  * 15% chance to place on `lessons`        (play an occupation) when legal
  * 15% chance to place on `meeting_place`   (become SP + optionally play a
                                              minor) when legal AND the player
                                              has at least one playable minor

Otherwise it picks uniformly at random among ALL legal actions (no
implemented-action filter — we WANT to exercise every action `legal_actions`
offers; if `step` can't apply one, that's a bug to catch). Reveals are picked
randomly from the candidate `RevealCard`s, so a game needs no Environment.

The card pool is EVERY implemented card (all of `OCCUPATIONS` / `MINORS`), so
across many seeds the random 7+7 deal covers the whole registry. Each game is
fully deterministic in its seed (both the deal and the agent's choices), so any
failure reproduces with `--seed <N>`.

Failures detected:
  * crash      — an exception in legal_actions / step
  * softlock   — no legal actions before BEFORE_SCORING
  * nonprogress— step cap exceeded (a non-terminating loop)

Usage:
    python scripts/card_fuzz_test.py                      # 2000 games, all cores
    python scripts/card_fuzz_test.py --n 20000 --jobs 8
    python scripts/card_fuzz_test.py --seed 12345         # replay ONE game, verbose
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import time
import traceback

import numpy as np

# Populate the card registries (import side effects register every card).
import agricola.cards  # noqa: F401
from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS, MINORS
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.setup import CardPool, setup_env

STEP_CAP = 6000  # a full game is a few hundred steps; this catches non-termination

# Built once per process (cheap; the registries are already imported).
_POOL = CardPool(occupations=tuple(OCCUPATIONS), minors=tuple(MINORS))


def _pick(state, rng, legal):
    """Biased random action choice. Bias only applies at worker-placement
    decisions (empty pending stack → decider is current_player)."""
    if not state.pending_stack:
        by_space = {a.space: a for a in legal if isinstance(a, PlaceWorker)}
        idx = state.current_player
        r = rng.random()
        if "lessons" in by_space and r < 0.15:
            return by_space["lessons"]
        if (
            "meeting_place" in by_space
            and 0.15 <= r < 0.30
            and playable_minors(state, idx)
        ):
            return by_space["meeting_place"]
    return legal[int(rng.integers(len(legal)))]


def play_one(seed: int, *, keep_trace: bool = False):
    """Play one card-mode game. Returns a result dict; never raises."""
    rng = np.random.default_rng(seed)
    try:
        state, _env = setup_env(seed, card_pool=_POOL)
    except Exception:
        return {
            "seed": seed, "status": "crash", "where": "setup",
            "tb": traceback.format_exc(), "trace": [], "steps": 0,
            "hands": None, "played": None, "action": None,
        }

    trace = []  # short reprs of recent actions (ring-buffered)
    seen = set()  # state hashes — a revisit means a no-progress cycle (soft-lock)
    steps = 0
    while state.phase != Phase.BEFORE_SCORING:
        if steps > STEP_CAP:
            return _fail(seed, "nonprogress", state, trace, steps, None,
                         f"exceeded {STEP_CAP} steps")
        # Exact-state revisit = the engine is cycling (resources/round advance
        # monotonically in real play, so a repeated GameState is a true soft-lock,
        # not coincidence). Catch it in ~2 steps instead of spinning to STEP_CAP.
        h = hash(state)
        if h in seen:
            return _fail(seed, "cycle", state, trace, steps, None,
                         "state repeated — engine soft-lock cycle")
        seen.add(h)
        try:
            legal = legal_actions(state)
        except Exception:
            return _fail(seed, "crash", state, trace, steps, None,
                         traceback.format_exc(), where="legal_actions")
        if not legal:
            return _fail(seed, "softlock", state, trace, steps, None,
                         "no legal actions")
        action = _pick(state, rng, legal)
        trace.append(repr(action))
        steps += 1
        try:
            state = step(state, action)
        except Exception:
            return _fail(seed, "crash", state, trace, steps, action,
                         traceback.format_exc(), where="step")

    return {"seed": seed, "status": "ok", "steps": steps}


def _fail(seed, status, state, trace, steps, action, detail, where=""):
    def _hand(p):
        return {"occ": sorted(p.hand_occupations), "min": sorted(p.hand_minors)}

    def _played(p):
        return {"occ": sorted(p.occupations),
                "min": sorted(p.minor_improvements)}

    def _frame(f):
        return {
            "type": type(f).__name__,
            "player_idx": getattr(f, "player_idx", None),
            "initiated_by": getattr(f, "initiated_by_id", None),
            "phase": getattr(f, "phase", None),
        }

    return {
        "seed": seed, "status": status, "where": where, "detail": detail,
        "tb": detail if status == "crash" else "",
        "steps": steps,
        "current_player": state.current_player,
        "round": state.round_number, "phase": str(state.phase),
        "pending": [type(f).__name__ for f in state.pending_stack],
        "pending_full": [_frame(f) for f in state.pending_stack],
        "action": repr(action) if action is not None else None,
        "hands": [_hand(p) for p in state.players],
        "played": [_played(p) for p in state.players],
        "trace": list(trace),
    }


def _worker(seed):
    return play_one(seed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000, help="number of games")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--base-seed", type=int, default=0)
    ap.add_argument("--seed", type=int, default=None,
                    help="replay ONE game with full trace (verbose, no pool)")
    ap.add_argument("--out", default="card_fuzz_failures.json",
                    help="write every failure (full trace + ids) to this JSON file")
    args = ap.parse_args()

    print(f"card pool: {len(_POOL.occupations)} occupations + "
          f"{len(_POOL.minors)} minors", flush=True)

    if args.seed is not None:
        r = play_one(args.seed, keep_trace=True)
        _report_one(r)
        sys.exit(0 if r["status"] == "ok" else 1)

    seeds = range(args.base_seed, args.base_seed + args.n)
    failures = []
    t0 = time.time()
    done = 0
    with mp.Pool(args.jobs) as pool:
        for r in pool.imap_unordered(_worker, seeds, chunksize=4):
            done += 1
            if r["status"] != "ok":
                failures.append(r)
                print(f"\n  [FAIL #{len(failures)}] seed={r['seed']} "
                      f"{r['status']} ({r.get('where','')}) "
                      f"round={r.get('round','?')} "
                      f"action={r.get('action')}", flush=True)
            if done % 200 == 0 or done == args.n:
                rate = done / (time.time() - t0)
                print(f"  {done}/{args.n} games  "
                      f"{rate:.0f} games/s  {len(failures)} failures",
                      flush=True)

    dt = time.time() - t0
    print(f"\n=== DONE: {args.n} games in {dt:.1f}s "
          f"({args.n/dt:.0f} games/s), {len(failures)} failures ===")
    if failures:
        _summarize(failures)
        import json
        # Sort by signature so same-cause failures are adjacent; each record is
        # individually investigable (replay with --seed <its seed>).
        for f in failures:
            f["signature"] = _signature(f)
        failures.sort(key=lambda f: (f["signature"], f["seed"]))
        with open(args.out, "w") as fh:
            json.dump(failures, fh, indent=2)
        print(f"\nwrote {len(failures)} failure records → {args.out}")
        print(f"  reproduce any one with:  "
              f"PYTHONPATH=. python scripts/card_fuzz_test.py --seed <seed>")
    sys.exit(1 if failures else 0)


def _report_one(r):
    print(f"\nseed={r['seed']}  status={r['status']}  steps={r['steps']}")
    if r["status"] == "ok":
        return
    print(f"where={r.get('where')}  round={r.get('round')}  "
          f"phase={r.get('phase')}  pending={r.get('pending')}")
    print(f"action={r.get('action')}")
    print(f"detail/tb:\n{r.get('tb') or r.get('detail')}")
    print(f"hands={r.get('hands')}")
    print(f"played={r.get('played')}")
    print("recent trace:")
    for a in r.get("trace", [])[-30:]:
        print(f"    {a}")


def _signature(f):
    """A discriminating signature for grouping failures by underlying cause.

    Crashes → the last traceback line. Cycles/softlocks/nonprogress → the
    pending-stack shape (+ the action that crashed, if any), since the detail
    text is identical across all instances of those statuses."""
    if f["status"] == "crash":
        tb = f.get("tb", "")
        return tb.strip().splitlines()[-1] if tb.strip() else f.get("detail", "")
    pend = "/".join(f.get("pending", [])) or "<empty>"
    return f"{f['status']} @ [{pend}]"


def _summarize(failures):
    from collections import Counter
    by_status = Counter(f["status"] for f in failures)
    print(f"failure breakdown: {dict(by_status)}")
    sigs = Counter(_signature(f) for f in failures)
    print("\ntop failure signatures:")
    for sig, cnt in sigs.most_common(25):
        print(f"  {cnt:4d}  {sig}")
    # Print the first example of each distinct signature in full.
    print("\n=== one full example per distinct signature ===")
    seen = set()
    for f in failures:
        sig = _signature(f)
        if sig in seen:
            continue
        seen.add(sig)
        print("\n" + "-" * 70)
        _report_one(f)


if __name__ == "__main__":
    main()
