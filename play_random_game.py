"""Play one full Family-game-mode game between two random agents and print
the final score.

Usage:
    python play_random_game.py             # random seed
    python play_random_game.py 42          # specific seed
    python play_random_game.py --quiet 42  # totals only
    python play_random_game.py --trace 42  # also print per-round action log
"""
from __future__ import annotations

import argparse
import random
import sys

from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.constants import Phase
from agricola.engine import step
from agricola.scoring import score, tiebreaker
from agricola.setup import setup
from tests.test_utils import random_agent_play


CATEGORY_ORDER = [
    ("field_tiles",              "Field tiles"),
    ("pastures",                 "Pastures"),
    ("grain",                    "Grain"),
    ("vegetables",               "Vegetables"),
    ("sheep",                    "Sheep"),
    ("boar",                     "Wild boar"),
    ("cattle",                   "Cattle"),
    ("unused_spaces",            "Unused spaces"),
    ("fenced_stables",           "Fenced stables"),
    ("clay_rooms",               "Clay rooms"),
    ("stone_rooms",              "Stone rooms"),
    ("people",                   "People"),
    ("begging_markers",          "Begging markers"),
    ("major_improvement_points", "Major improvements"),
    ("bonus_points",             "Craft bonuses"),
]


def _fmt_action(a) -> str:
    """Render an Action as a short human-readable string for trace output."""
    if isinstance(a, PlaceWorker):
        return f"place {a.space}"
    if isinstance(a, ChooseSubAction):
        return f"choose {a.name}"
    if isinstance(a, CommitSow):
        return f"sow g={a.grain},v={a.veg}"
    if isinstance(a, CommitBake):
        return f"bake g={a.grain}"
    if isinstance(a, CommitPlow):
        return f"plow ({a.row},{a.col})"
    if isinstance(a, CommitBuildStable):
        return f"stable ({a.row},{a.col})"
    if isinstance(a, CommitBuildRoom):
        return f"room ({a.row},{a.col})"
    if isinstance(a, CommitBuildMajor):
        suffix = f" (return fp{a.return_fireplace_idx})" if a.return_fireplace_idx is not None else ""
        return f"major idx={a.major_idx}{suffix}"
    if isinstance(a, CommitRenovate):
        return "renovate"
    if isinstance(a, CommitAccommodate):
        return f"accommodate s={a.sheep},b={a.boar},c={a.cattle}"
    if isinstance(a, CommitBuildPasture):
        return f"pasture {set(sorted(a.cells))}"
    if isinstance(a, CommitHarvestConversion):
        return f"{a.conversion_id}={'fire' if a.use else 'skip'}"
    if isinstance(a, CommitConvert):
        parts = [f"{k}={v}" for k, v in [
            ("g", a.grain), ("v", a.veg),
            ("s", a.sheep), ("b", a.boar), ("c", a.cattle),
        ] if v]
        return "convert " + (",".join(parts) if parts else "nothing")
    if isinstance(a, CommitBreed):
        return f"breed ({a.sheep},{a.boar},{a.cattle})"
    if isinstance(a, FireTrigger):
        return f"fire {a.card_id}"
    if isinstance(a, Stop):
        return "stop"
    return repr(a)


def _print_trace(initial_state, trace):
    """Per-round action log.

    Re-walks the trace from the initial state, tracking which player owned
    each action and which phase the engine was in when it was committed.
    Worker-placement chains (PlaceWorker + sub-actions + Stop) appear
    grouped: the lead action is prefixed with `P{n}:`, follow-on actions
    indented under the same player. Harvest sub-phases (HARVEST_FEED,
    HARVEST_BREED) get their own dividers within the round.
    """
    state = initial_state

    # Pre-walk: snapshot (round, phase, actor) BEFORE each step so each
    # action is labeled with the engine state that actually owned it.
    entries = []
    for action in trace:
        actor = (
            state.pending_stack[-1].player_idx if state.pending_stack
            else state.current_player
        )
        entries.append((state.round_number, state.phase, actor, action))
        state = step(state, action)

    last_round = None
    last_phase = None
    last_actor = None

    for (rnd, phase, actor, action) in entries:
        if rnd != last_round:
            print()
            print(f"Round {rnd}:")
            last_actor = None       # next action will be a fresh lead
            last_phase = None       # force phase header check below

        if phase != last_phase:
            if phase in (Phase.HARVEST_FEED, Phase.HARVEST_BREED):
                print(f"  -- {phase.name} --")
                last_actor = None   # harvest sections start fresh

        fmt = _fmt_action(action)
        # A "lead" line gets the `P{n}:` prefix; chain lines (sub-actions
        # belonging to the same placement) get indented. Every PlaceWorker
        # starts a fresh lead even when the same player placed last —
        # otherwise consecutive PlaceWorkers (e.g., when one player ran out
        # of workers before the other) read as sub-action chains.
        is_lead = (actor != last_actor) or isinstance(action, PlaceWorker)
        if is_lead:
            print(f"  P{actor}: {fmt}")
        else:
            print(f"         {fmt}")

        last_round = rnd
        last_phase = phase
        last_actor = actor


def _format_player_summary(state, player_idx):
    """Return a single-line summary of the player's terminal state."""
    p = state.players[player_idx]
    r = p.resources
    a = p.animals
    return (
        f"  resources: wood={r.wood} clay={r.clay} reed={r.reed} stone={r.stone} "
        f"food={r.food} grain={r.grain} veg={r.veg}\n"
        f"  animals:   sheep={a.sheep} boar={a.boar} cattle={a.cattle}\n"
        f"  people:    {p.people_total} ({p.house_material.name} house) "
        f"begging={p.begging_markers}"
    )


def _print_scoreboard(state, *, quiet: bool):
    breakdowns = [score(state, p) for p in (0, 1)]
    tbs        = [tiebreaker(state, p) for p in (0, 1)]
    totals     = [b[0] for b in breakdowns]
    bds        = [b[1] for b in breakdowns]

    name_w = max(len(label) for _, label in CATEGORY_ORDER)
    col_w  = max(6, len(f"{totals[0]}"), len(f"{totals[1]}"))

    print()
    print("=" * (name_w + 2 * col_w + 8))
    header = f"{'Category':<{name_w}}  {'P0':>{col_w}}  {'P1':>{col_w}}"
    print(header)
    print("-" * len(header))

    if not quiet:
        for field, label in CATEGORY_ORDER:
            v0 = getattr(bds[0], field)
            v1 = getattr(bds[1], field)
            print(f"{label:<{name_w}}  {v0:>{col_w}}  {v1:>{col_w}}")
        print("-" * len(header))

    print(f"{'TOTAL':<{name_w}}  {totals[0]:>{col_w}}  {totals[1]:>{col_w}}")
    print(f"{'Tiebreaker':<{name_w}}  {tbs[0]:>{col_w}}  {tbs[1]:>{col_w}}")
    print("=" * len(header))

    # Result.
    if totals[0] > totals[1]:
        winner = "P0"
    elif totals[1] > totals[0]:
        winner = "P1"
    else:
        if tbs[0] > tbs[1]:
            winner = "P0 (tiebreaker)"
        elif tbs[1] > tbs[0]:
            winner = "P1 (tiebreaker)"
        else:
            winner = "Tie"
    print(f"Winner: {winner}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "seed", nargs="?", type=int, default=None,
        help="Seed for setup() and the agent's RNG (defaults to a random int).",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Only print totals + winner, not the per-category breakdown.",
    )
    parser.add_argument(
        "--trace", "-t", action="store_true",
        help="Print a per-round action log before the scoreboard.",
    )
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else random.randint(0, 2**31 - 1)
    print(f"Random-vs-random Agricola game, seed={seed}")

    initial_state = setup(seed=seed)
    print(f"Starting player: P{initial_state.starting_player}")

    state, trace = random_agent_play(initial_state, seed=seed)

    print(f"Final phase: {state.phase.name}, round {state.round_number}, "
          f"{len(trace)} actions played.")

    if args.trace:
        _print_trace(initial_state, trace)

    print()
    print("Player 0:")
    print(_format_player_summary(state, 0))
    print()
    print("Player 1:")
    print(_format_player_summary(state, 1))

    _print_scoreboard(state, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
