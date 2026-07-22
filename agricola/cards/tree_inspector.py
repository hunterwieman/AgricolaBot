"""Tree Inspector (occupation, Dulcinaria Expansion; deck D #116; players 1+).

Card text (verbatim): "This card is a "1 Wood" accumulation space for you
only. Each time the newly revealed action space card is a "Quarry"
accumulation space, you must discard all wood from this card."
Category: Building Resource Provider. No printed VPs. On-play is a no-op —
the effect is the standing accumulation space.

GOVERNING RULING (user ruling 74, 2026-07-21, CARD_DEFERRED_PLANS.md, quoted):
"Card-as-action-space approved; card spaces count as action spaces for other
cards' hooks (user: both texts literally say 'action space'). … Tree
Inspector accumulates +1 wood at the prep refill — the quarry-reveal discard
(`reveal` window) precedes the refill on the preparation ladder, matching the
user's stated ordering."

MECHANICS — three registered pieces:

1. **The accumulation** — a ``replenishment``-window AUTO (the preparation
   ladder, ruling 54 — `agricola/cards/preparation.py`; Nest Site is the
   registration template): each preparation phase, +1 wood onto the card
   (its own CardStore entry; no entry = empty). The card is played mid-round,
   so its first wood arrives at the NEXT round's preparation.
2. **The quarry discard** — a ``reveal``-window AUTO ("you must" — mandatory,
   choice-free). "A 'Quarry' accumulation space" is the collective name rule
   (space name ends "Quarry"): the stone accumulation spaces Western Quarry /
   Eastern Quarry — ``STONE_ACCUMULATION_SPACES``, exactly Heart of Stone's
   reading of the identical event. "The newly revealed action space card" is
   read off the ``revealed_round`` stamp: at the ``reveal`` window the round
   increment has already run, so this round's reveal satisfies
   ``revealed_round == state.round_number``. The ladder ordering is
   load-bearing (the ruling's "the quarry-reveal discard precedes the
   refill"): ``reveal`` is rung 3, the mechanical ``__replenish__`` rung 7
   (and this card's own +1 rides the post-refill ``replenishment`` window,
   rung 8) — so on a quarry round the stack is discarded FIRST and the card
   enters the round holding exactly the fresh 1 wood.
3. **The action space** — the played-card-as-action-space machinery
   (`agricola/cards/card_spaces.py`; ruling 74): the owner — and only the
   owner ("for you only") — may place a worker on the card, exactly as on a
   board accumulation space. Using it sweeps ALL its accumulated wood to the
   owner's supply. An EMPTY card is not placeable — mirroring the engine's
   prune of placements on empty board accumulation spaces (Forest / Clay Pit
   / the quarries all require stock > 0). The placement decrements
   ``people_home``, occupies the card for the round (the on-card worker
   marker, cleared at return home), and is hosted with the generic
   action-space lifecycle, so other cards' before/after action-space hooks
   fire on it with ``space_id = "card:tree_inspector"`` (the ruling's
   consequence).

Because the card is a "1 Wood" ACCUMULATION space, it also registers in
``CARD_ACCUMULATIONS`` (`card_spaces.py`) so accumulation-stock readers reach
its stack. Governing ruling (user ruling 75, 2026-07-21, CARD_DEFERRED_PLANS.md,
verbatim): "Work Certificate × Tree Inspector: a Work Certificate owner CAN
take 1 wood from a 4+-stack Tree Inspector card space — regardless of which
player played Tree Inspector." The registered ``remove_fn`` debits THIS
card's stack (the owner's CardStore entry); the taken wood's destination is
the consumer's side (Work Certificate credits its own owner — possibly the
other player).

Card-game only (ownership-gated registries; the machinery is registry-gated
and Family-inert), so the Family trace and the C++ differential gates are
untouched. See CARD_ENGINE_IMPLEMENTATION.md §2/§5d and
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.card_spaces import (
    register_card_accumulation,
    register_card_action_space,
)
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import STONE_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "tree_inspector"


def _wood(player_state) -> int:
    """Wood on the card (its own CardStore entry; no entry = empty)."""
    return player_state.card_state.get(CARD_ID, 0)


def _update_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


# ---------------------------------------------------------------------------
# (1) The accumulation — +1 wood each preparation replenishment
# ---------------------------------------------------------------------------

def _accumulate_eligible(state: GameState, idx: int) -> bool:
    return True   # ownership is apply_auto_effects' gate; the refill is unconditional


def _accumulate(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, _wood(p) + 1))
    return _update_player(state, idx, p)


# ---------------------------------------------------------------------------
# (2) The quarry discard — mandatory, at the `reveal` window (pre-refill)
# ---------------------------------------------------------------------------

def _quarry_revealed_this_round(state: GameState) -> bool:
    """Did THIS round's preparation reveal a "Quarry" accumulation space? The
    Heart of Stone idiom: at the ``reveal`` window the round increment has
    already run, so the just-revealed quarry's ``revealed_round`` equals
    ``state.round_number`` (permanents carry 0, earlier reveals a smaller
    number, unrevealed None)."""
    return any(
        get_space(state.board, q).revealed_round == state.round_number
        for q in STONE_ACCUMULATION_SPACES
    )


def _discard_eligible(state: GameState, idx: int) -> bool:
    # "you must discard all wood from this card" — only meaningful while the
    # card holds any.
    return _wood(state.players[idx]) > 0 and _quarry_revealed_this_round(state)


def _discard(state: GameState, idx: int) -> GameState:
    """Discard ALL wood from the card (to the general supply — gone, not to
    the player). Empty is "no entry" (the CardStore logical-default idiom)."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.remove(CARD_ID))
    return _update_player(state, idx, p)


# ---------------------------------------------------------------------------
# (3) The action space — sweep the stack to the owner's supply
# ---------------------------------------------------------------------------

def _placeable(state: GameState, owner_idx: int) -> list:
    """One plain placement while the card holds wood; an EMPTY accumulation
    space is not placeable (the engine's board-space prune, mirrored)."""
    return [None] if _wood(state.players[owner_idx]) > 0 else []


def _use(state: GameState, owner_idx: int, picks) -> GameState:
    """The space's action: take ALL the wood on the card (the accumulation-
    space rule — a use sweeps the whole stack). `picks` is always None (a
    plain, non-wide placement)."""
    p = state.players[owner_idx]
    n = _wood(p)
    p = fast_replace(
        p,
        resources=p.resources + Resources(wood=n),
        card_state=p.card_state.remove(CARD_ID),
    )
    return _update_player(state, owner_idx, p)


# ---------------------------------------------------------------------------
# (4) The accumulation-space stock accessors (ruling 75 — Work Certificate's
#     take reaches this card's stack, whichever player owns each card)
# ---------------------------------------------------------------------------

def _accum_count(state: GameState, owner_idx: int) -> int:
    """The stack's current size (wood on the card)."""
    return _wood(state.players[owner_idx])


def _accum_remove(state: GameState, owner_idx: int, n: int) -> GameState:
    """Debit ``n`` wood from the card's stack (empty = no entry — the
    CardStore logical-default idiom, matching `_discard` / `_use`)."""
    p = state.players[owner_idx]
    cur = _wood(p)
    assert cur >= n, f"tree_inspector stack {cur} < remove {n}"
    store = (p.card_state.remove(CARD_ID) if cur == n
             else p.card_state.set(CARD_ID, cur - n))
    return _update_player(state, owner_idx, fast_replace(p, card_state=store))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_card_action_space(CARD_ID, _use, placeable_fn=_placeable)
# A "1 Wood" accumulation space: expose the stack to accumulation-stock
# consumers (Work Certificate's source enumeration — ruling 75).
register_card_accumulation(CARD_ID, "wood", _accum_count, _accum_remove)
# +1 wood each preparation replenishment (the post-refill window — Nest Site's
# registration form; rung ordering per ruling 74: the reveal discard precedes).
register_auto("replenishment", CARD_ID, _accumulate_eligible, _accumulate)
# The mandatory quarry-reveal discard ("you must") — the `reveal` window.
register_auto("reveal", CARD_ID, _discard_eligible, _discard)
