"""Renovation Materials (minor improvement, E2; Ephipparius Expansion; cost 3 Clay + 1 Reed;
prereq "Wooden House"; traveling).

Card text: "Immediately renovate to clay at no cost. (You must pay the cost of this card
though.)"

No printed VPs; a TRAVELING (passing) card — after the immediate renovate it is passed to
the opponent rather than kept.

Category 2 (on-play one-shot) that COMPOSES A PRIMITIVE on play, the same shape as
Shifting Cultivation: its `on_play` pushes the existing `PendingRenovate` primitive
(initiated_by_id "card:renovation_materials"), so the renovate runs through the normal
`CommitRenovate` path and every before/after renovate event (e.g. Roof Ladder's
after_renovate +1 stone) fires exactly as it would for any other renovate.

Two new push-time fields on `PendingRenovate` express the card's non-standard clauses
(user ruling 2026-07-20):

- `cost_override=Resources()` — "renovate to clay AT NO COST". A push-time price that
  bypasses the cost-modifier pipeline entirely (the override IS the single offered payment);
  reductions/conversions have nothing to act on for a zero-cost renovate. A frame field
  rather than a `register_formula` because this card TRAVELS: a traveling card is never in
  the tableau, so an ownership-gated cost formula could never fire for it — the pushed
  frame's provenance ("card:renovation_materials") is the authorization instead.
- `forced_target=HouseMaterial.CLAY` — "renovate TO CLAY". Pins the renovation target,
  replacing the normal next-tier + extension enumeration, so a co-owned Conservator
  (wood→stone target extension) may NOT widen the granted renovate to stone: the card's own
  prereq (a wooden house) guarantees wood→clay is the valid step, and it is the authority
  for that target.

The renovate is MANDATORY ("Immediately renovate to clay", not "you may"), so the card is
PLAYABLE ONLY on a wooden house — the printed "Wooden House" prerequisite. A wooden house
can always be renovated to clay (the target/cost are supplied by the frame, not derived), so
the pushed `PendingRenovate`'s before-phase always offers its single zero-cost
`CommitRenovate` and never dead-ends: its before-phase offers the commit and no Stop (the
renovate cannot be declined), flipping to the after-phase — offering `after_renovate`
triggers + Stop — once committed.

The card's OWN cost (3 clay + 1 reed) is paid normally at play through the standard minor
`cost=` — "(You must pay the cost of this card though.)".

Sequencing mirrors Shifting Cultivation: `PendingPlayMinor` is marked work-applied (the
deferred after-flip) before `on_play` runs, so the pushed `PendingRenovate` lands on top of
the still-before-phase host; when the renovate resolves and pops, the host flips (firing the
after_play_minor autos) and its after-phase Stop pops it cleanly.

Card-only registries are empty in the Family game (no cards owned), so the Family game is
byte-identical and the C++ differential gates are untouched. See CARD_AUTHORING_GUIDE.md,
shifting_cultivation.py (the mandatory pushed primitive), market_stall.py (passing), and
conservator.py (the wood→stone target extension `forced_target` guards against).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import HouseMaterial
from agricola.pending import PendingRenovate, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "renovation_materials"


def _prereq(state: GameState, idx: int) -> bool:
    """Prereq "Wooden House": the house material is wood. The mandatory renovate-to-clay
    is only valid from a wooden house, and a wooden house is always renovatable to clay
    (the frame supplies target + zero cost), so this guarantees the pushed renovate has a
    legal commit and never dead-ends.

    A renovate-forbid card in play (Mantlepiece, Wooden Shed — anything in
    RENOVATE_FORBID_CARDS) also blocks the play (user ruling 2026-07-20): the card's
    mandatory renovate may not happen for such a player, so the card is not legal to
    play at all. Checked against the registry, not card names, so future forbid cards
    compose automatically. (`forced_target` bypasses `_legal_renovate_targets`, where
    the forbid normally lives — this gate is the forbid's home on this card.)"""
    from agricola.legality import RENOVATE_FORBID_CARDS
    p = state.players[idx]
    if RENOVATE_FORBID_CARDS & (p.minor_improvements | p.occupations):
        return False
    return p.house_material is HouseMaterial.WOOD


def _on_play(state: GameState, idx: int) -> GameState:
    # Push the renovate primitive onto the (already after-phase-marked) PendingPlayMinor
    # host. `cost_override=Resources()` makes it free ("at no cost"); `forced_target=CLAY`
    # pins the target ("to clay") so a co-owned Conservator can't widen it to stone. The
    # normal CommitRenovate path resolves it, firing before/after renovate events.
    return push(state, PendingRenovate(
        player_idx=idx,
        initiated_by_id=f"card:{CARD_ID}",
        cost_override=Resources(),
        forced_target=HouseMaterial.CLAY,
    ))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=3, reed=1)),   # printed cost: 3 clay + 1 reed
    prereq=_prereq,
    passing_left=True,
    on_play=_on_play,
)
