"""The preparation-phase timing ladder — user ruling 54, 2026-07-14.

Printed card text names several distinct instants between a round's beginning
and its first worker placement: "at the start of these rounds, you get …"
(the ~68 round-space schedule cards — Pond Hut, Sack Cart, Wall Builder),
"each time [a card] is revealed" (Heart of Stone, Task Artisan, Tree
Inspector), "at the start of each round" (Childless, Scullery, Plow Driver,
Scholar, …), "… placed on [a space] … in the preparation phase" (Nest Site,
Shoreforester), "before each work phase" (Handcart, Nightworker), and "at
the start of each work phase" (Freemason, Cob, Trout Pool, Roman Pot,
Museum Caretaker). The pre-ladder engine collapsed the last four phrasings
onto one mis-timed event (a "start_of_round" fired at the END of
preparation, after the phase had already flipped to WORK) — wrong on both
counts, since the start of the round IS the start of the preparation phase
(RULES.md's phase order).

The user's ruling (2026-07-14) fixes the order:

    round-space goods collected → round card revealed → start of round
    → replenishment → before the work phase → start of the work phase

each an explicitly DISTINCT instant. This module is the data side: the
ordered step table the engine's ``_advance_preparation`` walks between the
round transition and the first worker placement. Every named step is a
simple window — its id doubles as the trigger/auto EVENT string, exactly
like the harvest and round-end ladders' windows — resolved window-major
(both players per window, starting player first; no banding). The
``__dunder__`` entries are mechanical sentinels, never events:

- ``__collect__`` — the new round begins: last round's newborns become
  plain adults (the field clears), the per-round/per-turn used-sets clear,
  and the goods/animals promised on this round's round space are collected
  (``future_resources`` + the ``future_rewards`` animals; over-capacity
  animal grants reconcile through the standard accommodation barrier).
- ``__reveal__`` — the nature step: push ``PendingReveal`` if this round's
  stage card is still face-down (the walk pauses; the environment answers
  with ``RevealCard``). The step re-checks, so a resume — or a legacy
  fixture whose card is already up — passes straight through.
- ``__round_setup__`` — ``round_number`` increments here, AFTER the reveal,
  preserving the public-state discriminator (revealed-count == round_number
  at every WORK state; count == round_number + 1 exactly in the post-reveal
  segment). Consequence, documented rather than hidden: at the
  ``round_space_collection`` window and the reveal, ``round_number`` still
  names the JUST-COMPLETED round — the round being entered is
  ``round_number + 1`` there, and ``round_number`` itself from
  ``reveal`` onward.
- ``__replenish__`` — the accumulation spaces refill (the mechanical
  Preparation step of RULES.md).

The walk completes by flipping ``phase`` to WORK with the starting player
active. Scheduled EFFECT grants (Handplow's deferred plow — "at the start
of that round, you can plow") surface at the ``start_of_round`` window,
their printed wording's rung; scheduled GOODS are the ``__collect__``
sentinel's mechanical job.

The harvest SKIP guard (`window_skipped`) is NOT consulted on this ladder:
ruling 14's whole-harvest skip (Layabout) covers the harvest ladder only,
and preparation is not part of any harvest.

Family fast path: no registrations → each window is two empty dict lookups;
no frames beyond the (pre-existing) reveal, ``prep_cursor`` stays None on
every state — it is set only across a card window's pause, never across the
reveal — and the walk applies exactly the pre-ladder mechanical effects.
The one Family-OBSERVABLE change from the pre-ladder engine is the ruling's
reordering itself: round-space goods (the Well) are collected — and
newborns cleared — BEFORE the reveal pause instead of after it, so the
reveal decision state shows them settled. The C++ twin mirrors that
reordering (the 2026-07-14 re-port).
"""
from __future__ import annotations

# The walk order. Window ids double as event strings; "__dunder__" entries
# are the engine's mechanical bookkeeping sentinels (never events).
PREP_STEPS: tuple[str, ...] = (
    "__collect__",              # 0 — newborns/used-sets clear + round-space collection
    "round_space_collection",   # 1 — window (reserved — no live card yet)
    "__reveal__",               # 2 — the nature reveal (PendingReveal; pauses, no cursor)
    "__round_setup__",          # 3 — round_number += 1 (post-reveal: the discriminator)
    "reveal",                   # 4 — window (reserved: Heart of Stone, Task Artisan, …)
    "start_of_round",           # 5 — window (Childless, Scullery, Plow Driver, Scholar, …)
    "__replenish__",            # 6 — accumulation spaces refill
    "replenishment",            # 7 — window (Nest Site)
    "before_work",              # 8 — window (reserved: Handcart, Nightworker)
    "start_of_work",            # 9 — window (Freemason, Cob, Trout Pool, Museum Caretaker)
)

PREP_INDEX: dict[str, int] = {w: i for i, w in enumerate(PREP_STEPS)}

# The post-reveal resume position (see __round_setup__ above): entered when
# the public state shows revealed-count == round_number + 1 and no cursor.
ROUND_SETUP: int = PREP_INDEX["__round_setup__"]
