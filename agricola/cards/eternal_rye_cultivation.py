"""Eternal Rye Cultivation (minor improvement, C66; Corbarius Expansion).

Card text (verbatim): "After each harvest in which you have 2 or 3+ grain in
your supply, you get 1 food and 1 additional grain, respectively."
ERRATA (verbatim from the JSON row): 'ERRATA: last "and" should be "or"'.
Cost: none (free). Prerequisite: "1 Grain Field". Printed VPs: 0. Kept (not
passing). Category: Crop Provider.

What the card does, in game terms: after every harvest, look at how much grain
the owner holds in supply. The "respectively" pairs the two thresholds with the
two rewards, and the errata's and->or makes the tiers EXCLUSIVE (user ruling
2026-07-06): with EXACTLY 2 grain the owner gets 1 food; with 3 OR MORE grain
the owner gets 1 additional grain INSTEAD; never both; with 0-1 grain, nothing.

Timing — "After each harvest" -> the ``after_harvest`` window (#17 on the
harvest-window ladder, ``agricola/cards/harvest_windows.py``), OUTSIDE the
harvest, strictly after ``end_of_harvest``. Per the user ruling of 2026-07-05
this is one merged window ("immediately after each harvest" and "after each
harvest" name the same instant). The payout is MANDATORY and choice-free — a
tiered income, no player decision — so it is an automatic effect
(``register_auto`` on the window event), fired mechanically by the harvest walk
(``engine._process_simple_window``) per owner, starting player first; no
``PendingHarvestWindow`` frame is ever pushed for it.

The supply-grain read happens AT the window — after the whole harvest has
resolved. Concretely: grain the field phase just harvested COUNTS (it is in
supply by then), and grain spent during the FEED phase (a raw grain->food
conversion at ``CommitConvert``) no longer counts. A player who enters the
harvest with 3 grain but converts one to feed the family holds 2 at the window
and gets the food tier, not the grain tier.

The window also fires after the FINAL harvest (round 14): the ladder is walked
to its end before the phase moves to ``BEFORE_SCORING``, so the 3+ tier's bonus
grain joins the owner's supply BEFORE the end-game grain scoring category
counts it.

Prerequisite "1 Grain Field" is a HAVE-check at PLAY time: at least one of the
player's own FIELD cells currently holds grain (``cell.grain > 0``) — the same
definition Bumper Crop's "2 Grain Fields" prerequisite uses (and Raised Bed /
Bale of Straw's "grain field" counting) — or at least one grain-holding
card-field (ruling 45, 2026-07-12; verbatim quote in ``_prereq``). A
prerequisite is checked, never spent (distinct from the cost).

Card-only state is empty (no CardStore use) and the registrations are
card-only registries, so the Family game is byte-identical and the C++ gates
are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "eternal_rye_cultivation"

WINDOW_ID = "after_harvest"


def _prereq(state: GameState, idx: int) -> bool:
    """1 Grain Field — at least one FIELD cell that currently holds grain, or
    at least one grain-holding card-field. Ruling 45 (2026-07-12), verbatim:
    ""field TILES" means the plowed fields on the farmyard grid; "field" is
    the BROADER category and includes card-fields. So a card-field counts for
    field-count readers — the Fields scoring category and any "you need N
    fields" requirement — while per-TILE readers still exclude it (ruling 32
    unchanged)." A veg- or wood-holding card-field is not a grain field."""
    from agricola.cards.card_fields import crop_card_field_count
    p = state.players[idx]
    return crop_card_field_count(p, "grain") >= 1 or any(
        cell.cell_type == CellType.FIELD and cell.grain > 0
        for row in p.farmyard.grid
        for cell in row
    )


def _eligible(state: GameState, idx: int) -> bool:
    """Fire iff the owner holds at least 2 grain in supply at the window (the
    0-1 tier is 'nothing'). Ownership: ``apply_auto_effects`` already gates on
    it, but registrations are global so the check is kept explicit here, per
    the surrounding card idioms."""
    p = state.players[idx]
    return CARD_ID in p.minor_improvements and p.resources.grain >= 2


def _apply(state: GameState, idx: int) -> GameState:
    """The exclusive tier table (errata and->or; user ruling 2026-07-06):
    3+ grain in supply -> +1 grain; exactly 2 -> +1 food; never both."""
    p = state.players[idx]
    gained = Resources(grain=1) if p.resources.grain >= 3 else Resources(food=1)
    p = fast_replace(p, resources=p.resources + gained)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# Cost null -> free; prereq "1 Grain Field"; vps null -> 0.
register_minor(CARD_ID, prereq=_prereq)

# The tiered after-harvest income: mandatory + choice-free -> an AUTO on the
# after_harvest window (fires after every harvest, round 14's included).
register_auto(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
