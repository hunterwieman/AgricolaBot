"""Shifting Cultivation (minor improvement, A2; Base Revised; cost 2 food, traveling).

Card text: "Immediately plow 1 field." No prerequisite, no printed VPs; a TRAVELING
(passing) card — after the immediate plow it is passed to the opponent rather than
kept.

Category 2 (on-play one-shot) that COMPOSES A PRIMITIVE on play: its on_play pushes
the existing PendingPlow primitive (initiated_by_id "card:shifting_cultivation"),
so the plow runs through the normal CommitPlow path.

The plow is MANDATORY ("Immediately plow 1 field", not "you may"), so the card is
PLAYABLE ONLY WHEN A PLOW IS POSSIBLE — a `_can_plow` prerequisite. This both matches
the rule (you cannot play it if you cannot carry out the forced plow) and avoids a
dead state: `PendingPlow`'s before-phase offers a CommitPlow per legal cell and NO
Stop (the plow cannot be declined), so pushing it with no legal cell would leave an
empty legal-action set. Gating playability on `_can_plow` guarantees the pushed plow
always has a target.

Sequencing (the subtle bit): PendingPlayMinor is a non-auto-pop host. Under the
DEFERRED after-flip (user ruling 2026-07-14) _execute_play_minor marks the host's
work applied before running on_play, so the PendingPlow this on_play pushes lands on
top of the still-before-phase host; when the plow resolves and pops, the host flips
(firing the after_play_minor autos only then) and its after-phase Stop pops it
cleanly. See CARD_IMPLEMENTATION_PLAN.md Category 2.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "shifting_cultivation"


def _prereq(state: GameState, idx: int) -> bool:
    """The plow is mandatory, so playability requires a legal plow target."""
    return _can_plow(state.players[idx])


def _on_play(state: GameState, idx: int) -> GameState:
    # Push the plow primitive onto the (already after-phase) PendingPlayMinor host; the
    # normal CommitPlow path resolves it. The `_can_plow` prereq guarantees a legal
    # target exists, so the forced plow never dead-ends.
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:shifting_cultivation"))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    passing_left=True,
    prereq=_prereq,
    on_play=_on_play,
)
