"""The preparation-phase timing ladder — the canonical round-entry chronology
(user ruling 54, 2026-07-14; the reference of record is
CARD_ENGINE_IMPLEMENTATION.md §5d).

Between one round's end and the next round's first worker placement, printed
card text names SEVEN distinct instants: "before the start of each round"
(Small Animal Breeder, Civic Facade), reveal reactions ("each time [a card]
is revealed" — Heart of Stone, Task Artisan, Tree Inspector, when built),
"at the start of these rounds, you can [take the thing on the round space]"
(the schedule grants — Handplow, Plowman, Chain Float, Grassland Harrow,
Small Greenhouse, Stable Planner, Tree Farm Joiner), "at the start of each
round" (Childless, Scullery, Plow Driver, Scholar, …), "… placed on [a
space] … during the preparation phase" (Nest Site), "at the end of each
preparation phase" / "before each work phase" (Pavior; Handcart, Nightworker
when built), and "at the start of each work phase" (Freemason, Cob, Trout
Pool, Museum Caretaker). The cards and printed rules are AMBIGUOUS about how
these instants are ordered relative to one another and to the mechanical
preparation steps; ruling 54 fixes the order:

    before the round → round card revealed → round-space goods collected
    → start of round → replenishment → before the work phase
    → start of the work phase

each an explicitly DISTINCT instant. This module is the data side: the
ordered step table the engine's ``_advance_preparation`` walks between the
round transition and the first worker placement. Every named step is a
simple window — its id doubles as the trigger/auto EVENT string, exactly
like the harvest and round-end ladders' windows — resolved window-major
(both players per window, starting player first; no banding). The
``__dunder__`` entries are mechanical sentinels, never events:

- ``__reveal__`` — the nature step: push ``PendingReveal`` if this round's
  stage card is still face-down (the walk pauses; the environment answers
  with ``RevealCard``). The step re-checks, so a resume — or a legacy
  fixture whose card is already up — passes straight through.
- ``__round_setup__`` — ``round_number`` increments here, immediately AFTER
  the reveal, preserving the public-state discriminator (revealed-count ==
  round_number at every WORK state; count == round_number + 1 exactly in
  the post-reveal segment). Consequence, documented rather than hidden: at
  the ``before_round`` window and the reveal itself, ``round_number`` still
  names the JUST-COMPLETED round — the round being entered is
  ``round_number + 1`` there (Small Animal Breeder's "the current round
  number" reads it so), and ``round_number`` itself from the ``reveal``
  window onward.
- ``__collect__`` — the round-space payout: last round's newborns become
  plain adults (the field clears), the per-round/per-turn used-sets clear,
  and the goods/animals promised on this round's round space are collected
  (``future_resources``, slot ``round_number - 1``, plus the
  ``future_rewards`` animals; over-capacity animal grants reconcile through
  the standard accommodation barrier). The card is turned up before the
  goods on its space are taken.
- ``__replenish__`` — the accumulation spaces refill (the mechanical
  Preparation step of RULES.md).

The walk completes by flipping ``phase`` to WORK with the starting player
active. Scheduled GOODS are the ``__collect__`` sentinel's mechanical job;
scheduled EFFECT grants (Handplow's deferred plow — "at the start of that
round, you can plow [the field on the round space]") surface at the
``round_space_collection`` window, the same instant's choice host (ruling
54: a thing on the round space resolves at COLLECTION time, not the
``start_of_round`` rung).

The harvest SKIP guard (`window_skipped`) is NOT consulted on this ladder:
ruling 14's whole-harvest skip (Layabout) covers the harvest ladder only,
and preparation is not part of any harvest.

Family fast path: no registrations → each window is two empty dict lookups;
no frames beyond the (pre-existing) reveal, and ``prep_cursor`` stays None
on every state — it is set only across a card window's pause, never across
the reveal — so the walk is exactly the mechanical sentinels plus the reveal
pause, matching the C++ twin's preparation code state-for-state (no C++
field, no C++ change).
"""
from __future__ import annotations

# The walk order. Window ids double as event strings; "__dunder__" entries
# are the engine's mechanical bookkeeping sentinels (never events).
PREP_STEPS: tuple[str, ...] = (
    "before_round",             # 0 — window: "before the start of each round"
    #                                 (Small Animal Breeder, Civic Facade)
    "__reveal__",               # 1 — the nature reveal (PendingReveal; pauses, no cursor)
    "__round_setup__",          # 2 — round_number += 1 (post-reveal: the discriminator)
    "reveal",                   # 3 — window (reserved: Heart of Stone, Task Artisan, …)
    "__collect__",              # 4 — newborns/used-sets clear + round-space collection
    "round_space_collection",   # 5 — window (the round-space schedule grants:
    #                                 Handplow, Plowman, Chain Float, Grassland
    #                                 Harrow, Small Greenhouse, Stable Planner,
    #                                 Tree Farm Joiner)
    "start_of_round",           # 6 — window (Childless, Scullery, Plow Driver, Scholar, …)
    "__replenish__",            # 7 — accumulation spaces refill
    "replenishment",            # 8 — window (Nest Site)
    "before_work",              # 9 — window (Pavior; Handcart, Nightworker when built)
    "start_of_work",            # 10 — window (Freemason, Cob, Trout Pool, Museum Caretaker)
)

PREP_INDEX: dict[str, int] = {w: i for i, w in enumerate(PREP_STEPS)}

# The post-reveal resume position (see __round_setup__ above): entered when
# the public state shows revealed-count == round_number + 1 and no cursor.
ROUND_SETUP: int = PREP_INDEX["__round_setup__"]
