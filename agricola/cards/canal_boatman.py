"""Canal Boatman (occupation, deck D #103; Dulcinaria Expansion; players 1+).

Card text (verbatim): "Each time you use "Fishing" or "Reed Bank", you can pay
1 food to immediately place another person on this card. If you do, you get
your choice of 3 stone or 1 grain plus 1 vegetable."
Clarification: "The choices are (3 stone) or (grain+vegetable)."
Category: Goods Provider. No printed VPs. On-play is a no-op.

GOVERNING RULINGS (ruling 74, 2026-07-21, CARD_DEFERRED_PLANS.md):

- Implemented as an **``after_action_space`` trigger** — a USER-AUTHORIZED
  DEVIATION from the enforce-first before-default for bare "each time you use
  [space]" wording (user ruling 74, 2026-07-21: "slightly incorrect, but
  easier to implement"). Without that dated ruling this card would be
  ``before_action_space``.
- MULTIPLE workers may be parked on this card in one round (user ruling 74,
  2026-07-21): each qualifying Fishing / Reed Bank use is a fresh trigger —
  no once-per-round latch. (At 2 players that caps at two parks per round:
  each space is usable once per round.) The once-per-HOST-VISIT scope comes
  free from the host frame's ``triggers_resolved``.
- Sheep Inspector CAN return the on-card worker (user ruling 74, 2026-07-21)
  — implemented as the card-space return extension in
  ``agricola/cards/sheep_inspector.py``.

MECHANICS. An OPTIONAL play-variant trigger on ``after_action_space`` with
variants ``"3_stone"`` / ``"grain_veg"`` (the printed clarification's two
choices), eligible only when the host's ``space_id`` is ``fishing`` or
``reed_bank`` (own use — the hook is own-use and the eligibility re-checks the
host's player), the owner holds >= 1 food, and a person is HOME to park
(``people_home >= 1``: the acting person is already on the space, so anyone
still home is "another person"). Both spaces are TRUE-ATOMIC accumulation
spaces, so ``register_action_space_hook`` is required — it is what makes the
placement push a host frame at all. Firing pays 1 food, moves one person from
home onto this card (``people_home`` -1 plus the
``card_space_worker:canal_boatman`` marker via
``card_spaces.place_card_space_worker`` — the same occupancy bookkeeping a
card-space placement uses), and grants the chosen reward (3 stone, or 1 grain
+ 1 vegetable). Declining is the host's after-phase Stop. The space's own
accumulation take is untouched — it lands at Proceed, before this after-window
trigger.

CANAL BOATMAN IS NOT AN ACTION SPACE. It deliberately does NOT register in
``CARD_ACTION_SPACES`` — nobody ever places on it through ``legal_placements``
(contrast Collector / Tree Inspector); the worker-marker is pure occupancy
bookkeeping for the parked person. The park is nonetheless a REAL placement
for the round: the ``people_home`` debit makes the parked person unavailable
for later turns (player alternation and the round's all-placed detection both
key on ``people_home``), and the person returns home at the round's
returning-home reset.

WHY NO CARD-OWN RESET PATH IS NEEDED (verified in code, 2026-07-21):
``engine._return_home_reset`` step 2 returns every meeple home
(``people_home = people_total``) and step 3 calls
``card_spaces.clear_card_space_workers``, which sweeps EVERY key in the
``card_space_worker:`` namespace for both players — it does NOT filter to ids
registered in ``CARD_ACTION_SPACES``. Its registry-empty fast path
(``if not CARD_ACTION_SPACES: return state``) can never skip this card's
markers, because ``CARD_ACTION_SPACES`` is populated at import time:
``collector.py`` and ``tree_inspector.py`` both call
``register_card_action_space`` at module level, both are imported
unconditionally by ``agricola/cards/__init__.py``, and ``engine.py`` imports
``agricola.cards`` at load. So in any process that can run a card game the
registry is non-empty and the sweep always runs.

Card-game only (ownership-gated registries; no new engine state), so the
Family trace and the C++ differential gates are untouched. See
CARD_ENGINE_IMPLEMENTATION.md §2 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.card_spaces import place_card_space_worker
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "canal_boatman"

# The two hooked spaces, verbatim from the card text. Both are true-atomic
# accumulation spaces, so the hook registration below is what hosts them.
_SPACES = frozenset({"fishing", "reed_bank"})

# The reward choice, per the printed clarification:
# "The choices are (3 stone) or (grain+vegetable)."
_REWARDS = {
    "3_stone": Resources(stone=3),
    "grain_veg": Resources(grain=1, veg=1),
}


def _variants(state: GameState, idx: int) -> list[str]:
    """Both reward routes are always jointly legal when the trigger is
    eligible (pure gains — nothing else to afford), so the variant list is
    constant; `_eligible` carries every gate."""
    return ["3_stone", "grain_veg"]


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "Each time YOU use 'Fishing' or 'Reed Bank'": the host must be one of
    # the two named spaces and the owner's own use (the hook is own-use, so
    # the host only exists on the owner's turn — the player check is
    # belt-and-braces, the Sheep Inspector shape). Firing needs the 1-food
    # payment and a person at home to park ("place ANOTHER person on this
    # card" — the acting person is already on the space, so anyone home
    # qualifies). Never offer a dead-end.
    top = state.pending_stack[-1]
    if getattr(top, "space_id", None) not in _SPACES:
        return False
    if getattr(top, "player_idx", None) != idx:
        return False
    p = state.players[idx]
    return p.resources.food >= 1 and p.people_home >= 1


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one park: pay 1 food, move a person from home onto this card
    (people_home -1 + the on-card worker marker — the card_spaces occupancy
    bookkeeping; the marker is swept and the person returns home at the
    round's returning-home reset), and grant the chosen reward."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(food=1) + _REWARDS[variant],
        people_home=p.people_home - 1,
    )
    p = place_card_space_worker(p, CARD_ID)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# The after-window trigger (ruling 74, 2026-07-21: user-authorized
# after_action_space deviation from the before-default).
register("after_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
# Fishing / Reed Bank are true-atomic: without this hook no host frame is ever
# pushed and the trigger can never surface. Own-use only ("you use").
register_action_space_hook(CARD_ID, _SPACES)
