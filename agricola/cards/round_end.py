"""The round-end timing ladder (card game only) — rulings 49/50, 2026-07-12.

Printed card text names several distinct instants around a round's end: "at
the end of each work phase" (Straw Hat, Iron Hoe, Apiary, Sundial, Piggy
Bank, Master Renovator), "after each work phase" / "immediately before the
returning home phase" (Informant, Archway — ruling 50's separate later rung),
"at the start of the/each returning home phase" (Sample Stable Maker + the
3+/4+ family), "in the returning home phase" (Ale-Benches, Swimming Class,
Silage, Curator, Bellfounder, …), "immediately after each returning home
phase" (Steam Plow — concurrent with after_returning_home per ruling 49's
per-instance merge), and "at the end of each round" (Baking Course, Credit,
Lifting Machine, Sculpture Course). The user's ruling: the returning-home
phase is the round's LAST phase, and "the end of the round" is a DISTINCT,
LATER instant.

This module is the data side: the ordered step table the engine's
`_advance_round_end` walks between the work phase's last placement and the
round's phase transition (the harvest on harvest rounds, otherwise the next
round's preparation). Every named step is a simple window — its id doubles as
the trigger/auto EVENT string, exactly like the harvest ladder's simple
windows — resolved window-major (both players per window, starting player
first; no banding is ruled for round-end). The one non-window entry is the
``"__reset__"`` sentinel: the mechanical return-home bookkeeping (placements
cleared, people home). Its position IS the pre/post boundary the user's
Swimming Class design generalizes: the ``returning_home`` window fires BEFORE
the reset, so a member card reads the still-placed board directly — live
occupancy is the event data, no recorded manifest needed — while
``after_returning_home`` and ``end_of_round`` see the board cleared.

The harvest SKIP guard (`window_skipped`) is deliberately NOT consulted on
this ladder: ruling 14's whole-harvest skip (Layabout) covers the harvest
ladder only — the user (2026-07-12): the returning-home phase is DISTINCT
from the harvest — and Layabout's round-latched predicate is id-blind, so
consulting it here would wrongly swallow round-end windows on its latched
round.

UNCONDITIONED members fire on harvest rounds too (the round end precedes the
harvest); the "that does not end with a harvest" condition is each bearer's
own eligibility clause, not a ladder concern.

Family fast path: no registrations → each window is two empty dict lookups;
no frames, `round_end_cursor` stays None, and every state is byte-identical
to the pre-ladder engine (the C++ twin needs no change).
"""
from __future__ import annotations

# The walk order. Window ids double as event strings; "__reset__" is the
# engine's mechanical bookkeeping sentinel (never an event).
ROUND_END_STEPS: tuple[str, ...] = (
    "end_of_work",              # 0 — still DURING the work phase (ruling 49)
    "after_work",               # 1 — Informant + Archway (ruling 50)
    "start_of_returning_home",  # 2 — before the phase (ruling 49)
    "returning_home",           # 3 — PRE-reset: the live board is the data
    "__reset__",                # 4 — placements cleared, people home
    "after_returning_home",     # 5 — post-reset ("immediately after" merges)
    "end_of_round",             # 6 — the round's last instant (ruling 49)
)

ROUND_END_INDEX: dict[str, int] = {w: i for i, w in enumerate(ROUND_END_STEPS)}

# The WORK-phase segment (positions 0..1) runs before the RETURN_HOME flip;
# the RETURN_HOME segment (positions 2..6) runs inside that phase.
WORK_SEGMENT_END: int = ROUND_END_INDEX["after_work"]            # inclusive
RETURN_SEGMENT_START: int = ROUND_END_INDEX["start_of_returning_home"]
