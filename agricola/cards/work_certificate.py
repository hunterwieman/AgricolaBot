"""Work Certificate (minor improvement, Artifex A82; deck A #82; players -).

Card text (verbatim): "Each time after you use an action space, you can take 1
building resource from a building resource accumulation space with at least 4
building resources on it."
Clarification (verbatim): "Can be immediately triggered."
Cost: none. Prerequisite: "3 Occupations" — a HAVE-check (hold >= 3 played
occupations), never spent. No VPs. Not passing. Category: Building Resource
Provider.

USER RULING (2026-07-20): the mechanism is APPROVED — surfacing "take 1 building
resource off an accumulation space, no worker placed" as an `after_action_space`
trigger that edits the space's stock is sanctioned (deferred-plans cluster C3,
resolved 2026-07-20).

TIMING / KIND. "Each time AFTER you use an action space … you can" → an OPTIONAL
trigger in the AFTER window of the OWNER's every action-space use — the text says
"after" explicitly (the one legitimate reason to key ``after_action_space``, the
Nail Basket precedent). Because the card names EVERY action space, the hook is
registered over the whole canonical ``SPACE_IDS`` list: atomic spaces are only
hosted when hooked (``register_action_space_hook`` → ``should_host_space``), so
every own placement gains a ``PendingActionSpace`` host while the card is owned —
an accepted cost of the user-approved mechanism. Non-atomic spaces are always
hosted; their ids in the hook set are harmless. Own use only ("you use"): the
hook is own-use (not ``any_player``), and the enumerator only surfaces triggers
the HOST frame's player owns. Once per use via the host's ``triggers_resolved``.

THE TAKE — a play-variant trigger (the Cottager/Scholar idiom): one
``FireTrigger("work_certificate", variant="<space_id>:<type>")`` per legal
(source space, building-resource type) pair, e.g. ``"forest:wood"``. A QUALIFYING
SOURCE is one of the building-resource accumulation spaces
(``BUILDING_RESOURCE_ACCUMULATION_SPACES``: forest, clay_pit, reed_bank,
western_quarry, eastern_quarry at 2p — derived from the rate table, so future 4p
building spaces join automatically) whose ``accumulated`` stock holds at least 4
building resources IN TOTAL (wood+clay+reed+stone, any mix) — the printed
threshold is typeless ("at least 4 building resources on it"), unlike Material
Hub's per-type thresholds ("5 wood, 4 clay, …"). USER-CONFIRMED (2026-07-20):
"typless total is correct, and the player can take any resource type that
exists on the relevant space." The taken resource may be ANY
building-resource type present on the qualifying space (a card deposit — e.g.
Nail Basket's stone on Forest — can put a foreign type there; it both counts
toward the 4 and may be taken). Non-building goods on a space neither count nor
may be taken ("building resource" twice in the text). An unrevealed space holds
nothing (replenishment only refills revealed spaces), so it can never qualify —
no special-casing. Firing debits 1 of the chosen type from the space's
``accumulated`` (the board-edit idiom: Nail Basket / Pet Lover) and credits the
owner 1 of it; declining is the host's after-phase Stop.

The clarification "Can be immediately triggered" — the very action-space use that
PLAYS Work Certificate (e.g. the Major Improvement space's play-minor branch) may
fire it in that same use's after window: eligibility/ownership are read at fire
time, when the card is already in the tableau — the machinery's natural behavior,
so deliberately NO "later turns only" guard.

Card-game only (ownership-gated registries; no new engine state), so the Family
trace and the C++ differential gates are untouched. See
CARD_ENGINE_IMPLEMENTATION.md §2 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.constants import BUILDING_RESOURCE_ACCUMULATION_SPACES, SPACE_IDS
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "work_certificate"

# "at least 4 building resources on it" — a TYPELESS total over the four building
# resource types (any mix), contrast Material Hub's per-type thresholds.
_MIN_STOCK = 4

# The four building-resource types, in the surfacing order for variants.
_BUILDING_TYPES = ("wood", "clay", "reed", "stone")


def _variants(state: GameState, idx: int) -> list[str]:
    """The currently-legal takes: one ``"<space_id>:<type>"`` per building-resource
    type present on a qualifying source (a building-resource accumulation space
    holding >= 4 building resources in total). Empty list → nothing to take now."""
    out: list[str] = []
    for space_id in sorted(BUILDING_RESOURCE_ACCUMULATION_SPACES):
        acc = get_space(state.board, space_id).accumulated
        total = sum(getattr(acc, t) for t in _BUILDING_TYPES)
        if total < _MIN_STOCK:
            continue
        for t in _BUILDING_TYPES:
            if getattr(acc, t) >= 1:
                out.append(f"{space_id}:{t}")
    return out


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "each time after YOU use an action space": the enumerator already routes on
    # the host frame's player_idx (and the hook is own-use), so idx is the acting
    # player whenever this runs — the guard is belt-and-braces. Offer only when a
    # qualifying source exists (never a dead-end). Once per use is the host's
    # triggers_resolved (filtered by the firing machinery before this runs).
    top = state.pending_stack[-1]
    if getattr(top, "player_idx", None) != idx:
        return False
    return bool(_variants(state, idx))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one take: move 1 of the chosen building-resource type from the chosen
    space's accumulated stock to the owner's supply."""
    space_id, rtype = variant.split(":", 1)
    one = Resources(**{rtype: 1})
    # Debit the space's stock (the board-edit idiom — Nail Basket in reverse).
    sp = get_space(state.board, space_id)
    state = fast_replace(
        state, board=with_space(
            state.board, space_id,
            fast_replace(sp, accumulated=sp.accumulated - one)))
    # Credit the owner.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + one)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


# Prereq "3 Occupations" is a HAVE-check; no cost, no VPs, no on-play effect.
register_minor(CARD_ID, min_occupations=3)
# Optional after-window trigger on the owner's every action-space use.
register("after_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
# "an action space" = every space: hook the whole canonical list (atomic spaces
# are hosted only when hooked; non-atomic ids here are harmless).
register_action_space_hook(CARD_ID, SPACE_IDS)
