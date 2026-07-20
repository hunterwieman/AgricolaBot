"""Oven Site (minor improvement, A27; Artifex Expansion; no cost, kept).

Card text: "When you play this card, you get 2 wood and you can immediately build the
"Clay Oven" or "Stone Oven" major improvement. Either way, it only costs you 1 clay
and 1 stone."

Prerequisite: "Both Fireplace and Cooking Hearth" — the player must own at least one
Fireplace (major indices 0/1) AND at least one Cooking Hearth (major indices 2/3).
No printed VPs; kept (not traveling).

Two mechanisms:

- ON PLAY (`on_play`): grant 2 wood UNCONDITIONALLY, then push the generic
  `PendingGrantedSubAction` choose-or-decline wrapper for a single `build_major`
  granted category, with the menu restricted to Clay Oven (idx 5) and Stone Oven
  (idx 6) via `major_allowed=(5, 6)`. "You CAN immediately build …" is an OPTIONAL
  grant, so the wrapper's `ChooseSubAction("build_major")` / `Stop` is the take-or-
  decline; the 2 wood are granted first, so they arrive whether or not an oven is
  built. Choosing pushes a BARE `PendingBuildMajor` (menu = the two ovens, provenance
  `"card:oven_site"`) — a card's own "build a major improvement" effect is NOT the
  named "Major or Minor Improvement" action (CARD_AUTHORING_GUIDE.md §2), so no
  minor-play branch is offered and Merchant / Small Trader cannot fire off it. The
  wrapper's eligibility gate anticipates the same grant-scoped price, so it never
  offers a dead-end (no affordable oven on the menu → only Stop). Building an oven
  through this grant is a real major build: the oven's free Bake Bread on purchase
  fires as normal (the deferred after-flip handles ordering).

- THE PRICE ("only costs you 1 clay and 1 stone"): a whole-cost `register_formula`
  on `build_major`, scoped to THIS grant via `ctx.granted_by == "card:oven_site"`
  (the pending frame's provenance, threaded by `_build_major_ctx(granted_by=…)`).
  Modeling the price as a PIPELINE FORMULA (the Carpenter "only costs you X" shape),
  not a frame override, is deliberate — user ruling 2026-07-20: other owned cost
  reductions / discounts / conversions DO stack on top of the 1 clay + 1 stone, so
  the price must flow through the `effective_payments` chokepoint where reductions
  (e.g. Stonecutter's −1 stone) fold onto it. The printed oven costs (Clay Oven
  3 clay + 1 stone, Stone Oven 1 clay + 3 stone) remain as bases but are Pareto-
  dominated by the discounted 1 clay + 1 stone, so only the discounted payment (and
  any further-discounted variants) surfaces. Gating on `granted_by` (not permanent
  ownership) confines the discount to the on-play build only: a normal Major
  Improvement action by an Oven-Site owner carries `granted_by is None`, so the
  formula does not apply and the printed cost is paid.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_formula
from agricola.cards.specs import register_minor
from agricola.constants import COOKING_HEARTH_INDICES, FIREPLACE_INDICES
from agricola.pending import PendingGrantedSubAction, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "oven_site"
FRAME_ID = "card:oven_site"          # the granted build-major frame's initiated_by_id

CLAY_OVEN_IDX = 5
STONE_OVEN_IDX = 6


def _prereq(state: GameState, idx: int) -> bool:
    """"Both Fireplace and Cooking Hearth": owns >=1 Fireplace AND >=1 Cooking Hearth."""
    owners = state.board.major_improvement_owners
    has_fireplace = any(owners[i] == idx for i in FIREPLACE_INDICES)
    has_hearth = any(owners[i] == idx for i in COOKING_HEARTH_INDICES)
    return has_fireplace and has_hearth


def _on_play(state: GameState, idx: int) -> GameState:
    # Grant 2 wood UNCONDITIONALLY (before the optional build, so it arrives whether or
    # not an oven is built), then push the optional build-major grant restricted to the
    # two ovens. The wrapper's ChooseSubAction("build_major")/Stop is the take-or-decline;
    # its eligibility gate anticipates the grant-scoped 1c+1s price (never a dead-end).
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=2))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingGrantedSubAction(
        player_idx=idx, initiated_by_id=FRAME_ID, subactions=("build_major",),
        major_allowed=(CLAY_OVEN_IDX, STONE_OVEN_IDX)))


def _applies(state, idx, ctx) -> bool:
    # Scope the discount to THIS card's own granted build (provenance match), so a
    # normal Major Improvement action by an Oven-Site owner (granted_by is None) is
    # unaffected. The grant menu is (Clay Oven, Stone Oven), so granted_by matching
    # already implies an oven build.
    return ctx.granted_by == FRAME_ID


def _formula(state, idx, ctx) -> Resources:
    """"Either way, it only costs you 1 clay and 1 stone." """
    return Resources(clay=1, stone=1)


register_formula("build_major", CARD_ID, _applies, _formula)
register_minor(CARD_ID, cost=Cost(), prereq=_prereq, on_play=_on_play)
