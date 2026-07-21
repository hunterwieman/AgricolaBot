"""Renovation Company (minor improvement, A13; Artifex Expansion; players -).

Card text: "When you play this card, you immediately get 3 clay. Immediately
after, you can renovate without paying any building resources."
Cost: 4 Wood. Prereq: "In Wooden House with Exactly 2 Rooms". No printed VPs.
Clarification: "The renovation can be declined, but the free cost cannot be
applied later."

User rulings (2026-07-21):

1. "Immediately after" — the renovate grant resolves WITHIN the card's play
   (part of on_play, after the +3 clay, before any after-play triggers). The
   deferred after-flip (ruling 60) already guarantees this ordering: the
   PendingPlayMinor host is marked work-applied before `on_play` runs, so the
   pushed PendingRenovate fully resolves before the host flips and the
   `after_play_minor` autos fire — no extra work needed here.
2. The free renovate follows NORMAL renovate-target rules: usually wood→clay,
   but with Conservator owned the wood→stone target is also legal — free either
   way ("without paying any building resources" is unqualified). Hence NO
   `forced_target`: the frame's enumerator runs the standard
   `_legal_renovate_targets`, and only the price is overridden.
3. The decline is the play-variant choice itself ("play + renovate" vs "play,
   decline") — matching the clarification: declining at play forfeits the free
   renovate forever. Once the "renovate" variant is chosen, the pushed frame's
   before-phase offers only its zero-cost commit(s), no Stop (the standard
   cost_override frame shape — see renovation_materials.py).

Shape: a PLAY-VARIANT minor (`register_play_minor_variant` — the wide
on-play-optional-grant shape, ruling 17 / the §6 wide-vs-wrapper guideline).
Wide is safe because the grant's eligibility is exact pre-play: the card's own
prereq guarantees a wooden house (which always has a next renovation tier), and
a zero-cost renovate is always payable. Both variants carry a zero surcharge —
the choice prices nothing, it only decides whether the free renovate happens.

The "renovate" variant is offered only while `_legal_renovate_targets` is
non-empty for the player — the exact emptiness condition of the pushed frame's
enumerator, so "variant offered ⇔ the frame has a legal commit" by
construction. For a wooden-house player that set is empty only when a
renovate-forbid card (Mantlepiece / Wooden Shed — anything in
RENOVATE_FORBID_CARDS) is owned; without the gate, choosing "renovate" would
strand a commit-less, Stop-less frame. Mirrors Renovation Materials' forbid
handling (user ruling 2026-07-20 there), except here only the VARIANT is
withheld — the card itself stays playable (play + decline: the +3 clay is
unconditional).

`on_play`: +3 clay (the player-edit idiom); the "renovate" variant additionally
pushes the `PendingRenovate` primitive with `cost_override=Resources()` — the
push-time price that bypasses the cost-modifier pipeline (the override IS the
single offered payment per target; see renovation_materials.py, the mandatory
sibling of this grant — it uses cost_override + forced_target, this card
cost_override only). The renovate runs through the normal `CommitRenovate`
path, so every before/after renovate event fires as usual.

The card's OWN 4-wood cost is paid normally at play through the standard minor
`cost=`. A kept (non-traveling) minor. Card-only registries are empty in the
Family game, so the Family game is byte-identical.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.constants import HouseMaterial
from agricola.legality import _legal_renovate_targets, _num_rooms
from agricola.pending import PendingRenovate, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "renovation_company"


def _prereq(state: GameState, idx: int) -> bool:
    """Prereq "In Wooden House with Exactly 2 Rooms": house material is wood AND
    the farmyard has exactly 2 ROOM cells (`_num_rooms` — the engine's count)."""
    p = state.players[idx]
    return p.house_material is HouseMaterial.WOOD and _num_rooms(p) == 2


def _variants(state: GameState, idx: int):
    """Both zero-surcharge routes: "renovate" (play + the free renovate) and
    "decline" (play, forfeit the renovate — the clarification's decline). The
    renovate variant is gated on `_legal_renovate_targets` being non-empty —
    exactly the pushed frame's enumerator condition, so the chosen variant can
    never strand a commit-less frame (empty only under a renovate-forbid card;
    see the module docstring)."""
    p = state.players[idx]
    out = []
    if _legal_renovate_targets(state, p):
        out.append(("renovate", Resources()))
    out.append(("decline", Resources()))
    return out


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    """+3 clay (unconditional), then — on the "renovate" variant — push the free
    renovate primitive. No `forced_target`: the target menu stays the normal
    `_legal_renovate_targets` (user ruling 2026-07-21 #2 — Conservator's
    wood→stone is also free). The pushed frame lands on the already
    work-applied-marked PendingPlayMinor host, so it resolves before the
    after_play_minor autos fire (ruling #1)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=3))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    if variant == "renovate":
        state = push(state, PendingRenovate(
            player_idx=idx,
            initiated_by_id=f"card:{CARD_ID}",
            cost_override=Resources(),
        ))
    return state


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=4)),   # printed cost: 4 Wood
    prereq=_prereq,
    on_play=_on_play,
)
register_play_minor_variant(CARD_ID, _variants)
