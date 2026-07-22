"""Stable Master (occupation, C89; Corbarius Expansion; players 1+).

Card text (verbatim): "When you play this card, you can immediately build
exactly 1 stable for 1 wood. Exactly one of your unfenced stables can hold up
to 3 animals of one type."

Ruling 74 (2026-07-21, CARD_DEFERRED_PLANS.md): "on-play optional
build-1-stable-for-1-wood; clause 2 converts ONE unfenced stable's 1-cap
flexible slot into a 3-cap single-type bin — a strict upgrade, so no player
choice (plan, flagged; needs the extract_slots flexible->bin transformation;
check the Shepherd's Whistle arrangement interplay at build)". NOTE: the
capacity clause is recorded there as a PLAN, FLAGGED — not a dictated ruling
— with the Shepherd's Whistle interplay check required at build time (its
conclusion is below).

Clause 1 — the optional on-play build ("you can" -> optional). The build's
eligibility is exact PRE-play (1 wood + a legal stable cell + a stable piece
in supply — nothing the card itself creates), so per the wide-vs-wrapper
guideline (CARD_ENGINE_IMPLEMENTATION.md §6) the decline is the PLAY VARIANT
(the Baker shape, ruling 17): "play and build" and "play, decline the build"
are two distinct `CommitPlayOccupation` actions. The build variant is offered
only when `_can_build_stable` passes for the 1-wood cost (supply + empty cell
+ cost payable through the cost-modifier chokepoint) — never a dead-end; its
on_play pushes the reusable `PendingBuildStables` primitive with
`cost=Resources(wood=1)`, `max_builds=1` (the wood is spent inside the build,
not as a play surcharge, so stable-cost modifiers see it normally).

The stranding pair-gate — USER RULING 75 (2026-07-21, verbatim from
CARD_DEFERRED_PLANS.md): "the overlooked fact is that Stable Master's build is
OPTIONAL — no mandatory build can strand. The ruled shape: a wide display of
(payment × build/no-build) pairs — the build variant is offered only with
payments that leave the build doable; the decline variant with every payment."
The pre-play `_can_build_stable` gate above runs before the occupation cost
debits, so a payment could consume the very wood the granted build needs
(Working Gloves paying the play with the player's only wood) and reach a
`PendingBuildStables` with zero legal actions. `_pair_ok` (registered as the
`pair_ok_fn`) re-runs `_can_build_stable` on the POST-DEBIT state the seam
simulates — routed through the cost-modifier chokepoint, so a broke player
whose 3rd/4th stable Carpenter's Apprentice makes free stays eligible — and
returns True unconditionally for the decline variant.
`build_stables_action=False` per the §9.6 flag contract (name the action the
card grants): this is the card's own build effect, not the named "Build
Stables" action — cards keyed to the literal action must not fire on it
(mirrors stable.py / stallwright.py / pole_barns.py).

Clause 2 — the capacity upgrade (the flagged plan above). ONE unfenced
(standalone) stable's 1-capacity flexible slot becomes a 3-capacity
SINGLE-TYPE bin — a strict upgrade (any single animal that fit the flexible
slot fits the bin, which adds room for two more of that type), so NO player
choice is surfaced. Wired through `register_flexible_to_bin`
(`agricola/cards/capacity_mods.py`): `_bin_capacity` returns 3
unconditionally, and the `flexible_to_bin_caps` fold itself caps applications
at the number of standalone stables — so the no-unfenced-stable case (none
built, or every stable inside a pasture) yields no bin structurally.
`helpers.extract_slots` decrements `num_flexible` by one per applied upgrade
and appends the bin to the capacity list AFTER every pasture-only fold, so
pasture-geometry readers never see it.

Shepherd's Whistle interplay (the ruling-74 REQUIRED check — conclusion):
COMPOSES CORRECTLY, no change needed to either card. Shepherd's Whistle's
"unfenced stable without an animal" test (ruling 16) hands the standard
helpers a DOCTORED player with one standalone-stable CELL blanked; on that
doctored player this card's fold re-derives the bin from the REMAINING
standalone-stable count. That matches the physical optimum under free animal
rearrangement: with >=2 unfenced stables the freed (empty) stable is a plain
one and the bin designation sits on a still-occupied stable (the fold keeps
one bin while a standalone stable remains); with exactly 1 unfenced stable
the freed stable IS the bin, so the bin vanishes with it (the fold yields no
bin at zero standalone stables) — the Whistle then correctly requires the
animals to fit without the bin. The strict-upgrade property means the
Whistle's condition only ever gets EASIER with this card, and case A's
"provably fits" argument still holds: the full farm's capacity is the
reduced farm's plus either one flexible slot or one empty 3-bin, and the
granted single sheep fits either.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_flexible_to_bin
from agricola.cards.specs import (
    register_occupation,
    register_play_occupation_variant,
)
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "stable_master"
FRAME_ID = "card:stable_master"
_BUILD_COST = Resources(wood=1)


def _variants(state: GameState, idx: int) -> list:
    """The two play routes — build (only when the 1-wood stable build is
    currently doable: >=1 stable piece in supply, an empty cell, and the cost
    payable through the chokepoint) or decline. No surcharge on either (the
    build's wood is spent inside the pushed build frame)."""
    out = [("decline_build", Resources())]
    if _can_build_stable(state, state.players[idx], _BUILD_COST):
        out.insert(0, ("build", Resources()))
    return out


def _pair_ok(state: GameState, idx: int, variant: str, payment) -> bool:
    """The stranding pair-gate (user ruling 75, 2026-07-21 — docstring above):
    `state` is the simulated post-debit state; the build pair survives only if
    the 1-wood build is still doable there (through `_can_build_stable`, hence
    the cost-modifier chokepoint — Carpenter's Apprentice's 3rd/4th-stable
    discount keeps a broke player eligible). Decline pairs always pass."""
    if variant != "build":
        return True
    return _can_build_stable(state, state.players[idx], _BUILD_COST)


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    if variant != "build":
        return state                    # declined at the wide play choice
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id=FRAME_ID,
        cost=_BUILD_COST, max_builds=1, build_stables_action=False))


def _bin_capacity(player_state) -> int:
    """The upgraded stable's single-type bin capacity — 3, unconditionally:
    the flexible_to_bin fold caps applications at the number of standalone
    (unfenced) stables, so the no-unfenced-stable case is handled
    structurally (no bin)."""
    return 3


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants, pair_ok_fn=_pair_ok)
register_flexible_to_bin(CARD_ID, _bin_capacity)
