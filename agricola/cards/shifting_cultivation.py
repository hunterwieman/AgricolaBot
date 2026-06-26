"""Shifting Cultivation (minor improvement, A2; Base Revised; cost 2 food, traveling).

Card text: "Immediately plow 1 field." No prerequisite, no printed VPs; a TRAVELING
(passing) card — after the immediate plow it is passed to the opponent rather than
kept.

Category 2 (on-play one-shot) that COMPOSES A PRIMITIVE on play: its on_play pushes
the existing PendingPlow primitive (initiated_by_id "card:shifting_cultivation"),
so the plow runs through the normal CommitPlow path.

Sequencing (the subtle bit): PendingPlayMinor is a non-auto-pop host that pivots to
its after-phase on commit. _execute_play_minor now flips that host to "after"
BEFORE running on_play (mirroring how _execute_build_major flips PendingBuildMajor
before pushing its oven wrapper), so the PendingPlow this on_play pushes lands on
top of the ALREADY-flipped host. When the plow resolves and pops, the host's
after-phase Stop pops it cleanly — control returns without colliding with the flip.
See CARD_IMPLEMENTATION_PLAN.md Category 2.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.pending import PendingPlow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "shifting_cultivation"


def _on_play(state: GameState, idx: int) -> GameState:
    # Push the plow primitive onto the (already after-phase) PendingPlayMinor host;
    # the normal CommitPlow path resolves it. If no plow is currently possible the
    # frame's enumerator offers only Stop (the plow is forfeited) — a minor with no
    # legal target is still played/passed, matching the card's mandatory-but-stuck
    # wording.
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:shifting_cultivation"))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    passing_left=True,
    on_play=_on_play,
)
