"""Card-registered action spaces — the played-card-as-action-space machinery
(user ruling 74, 2026-07-21, CARD_DEFERRED_PLANS.md):

    "Card-as-action-space approved; card spaces count as action spaces for
    other cards' hooks (user: both texts literally say 'action space')."

A card like Collector (C104, "This card is an action space for you only") or
Tree Inspector (D116, "This card is a '1 Wood' accumulation space for you
only") turns its own tableau card into a worker-placement target. This module
is the registry those cards populate and the CardStore-backed worker-marker
helpers the engine consumes; the engine seams that read it are:

- ``legality.legal_placements`` — offers ``PlaceWorker(space="card:<id>",
  picks=…)`` for each OWNED, registered, un-occupied-this-round card space
  with a non-empty ``placeable_fn`` variants list ("for you only": the
  opponent never sees the placement at all).
- ``engine._apply_place_worker`` — dispatches ``card:`` space ids: decrements
  ``people_home`` exactly like any placement, sets the on-card worker marker
  (occupancy), and hosts the use with the generic ``PendingActionSpace``
  lifecycle (before-autos at push → the work at Proceed → the after-window →
  Stop), so a card-space use fires ``before_/after_action_space`` with
  ``space_id = "card:<id>"`` — the ruling's "counts as an action space for
  other cards' hooks" consequence.
- ``engine._apply_proceed`` — runs the registered ``use_fn`` as the hosted
  space's work (the ``ATOMIC_HANDLERS`` slot for a card space).
- ``engine._return_home_reset`` — clears every worker marker (the on-card
  workers go home with everyone else; ``people_home = people_total`` already
  covers the meeple count).

Empty registry → every one of those seams is an O(1) no-op, so the Family
game — and any card game without these cards — is byte-identical.

**Occupancy.** "An occupied action space cannot be used again that round"
applies to card spaces exactly as to board spaces. The marker is a per-card
count in the OWNER's CardStore under the machinery key
``"card_space_worker:<card_id>"`` (a machinery-owned key, distinct from the
card's own ``card_id`` entry — Collector keeps its use counter there). Per
the Tea Time occupancy ruling (user 2026-07-20: what makes a space illegal to
place on is the presence of a worker on it, nothing else), a card effect that
returns the on-card worker home mid-round re-opens the space.

**Card accumulation spaces.** A card space that stockpiles a resource on
itself round over round (Tree Inspector's wood stack) is a true ACCUMULATION
space, so cards that read or raid accumulation-space stocks reach it too.
Governing ruling (user ruling 75, 2026-07-21, CARD_DEFERRED_PLANS.md,
verbatim): "Work Certificate × Tree Inspector: a Work Certificate owner CAN
take 1 wood from a 4+-stack Tree Inspector card space — regardless of which
player played Tree Inspector." The second registry below
(``CARD_ACCUMULATIONS``) is the seam that ruling generalizes to: an
accumulation card registers its stock's resource type plus count/remove
accessors, and a consumer (Work Certificate's source enumeration) treats
every registered card accumulation of EITHER player as one more accumulation
space — reading its stock against the consumer's own threshold and debiting
the stack on a take (taker and card owner may differ, per the ruling).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agricola.replace import fast_replace
from agricola.state import CardStore, GameState


# The CardStore key prefix for the machinery's on-card worker markers. A
# machinery-owned namespace: no card id contains ":", so these keys can never
# collide with a card's own CardStore entry.
_WORKER_KEY_PREFIX = "card_space_worker:"


@dataclass(frozen=True)
class CardActionSpaceSpec:
    """One registered card action space.

    - ``use_fn(state, owner_idx, picks) -> state`` performs the space's action
      at the hosted use's work step (Proceed). ``picks`` is the placement's
      payload (the chosen variant) — ``None`` for a plain placement.
    - ``placeable_fn(state, owner_idx) -> list[picks | None]`` returns the
      legal placement variants right now: ``[None]`` = one plain placement; a
      list of picks tuples = the wide variants (one ``PlaceWorker`` each);
      ``[]`` = not placeable now (e.g. an empty accumulation card, mirroring
      the engine's prune of placements on empty board accumulation spaces).
    """
    card_id: str
    use_fn: Callable
    placeable_fn: Callable


# card_id -> CardActionSpaceSpec. Populated at card-module import, like every
# other card registry; empty in the Family game.
CARD_ACTION_SPACES: dict[str, CardActionSpaceSpec] = {}


def register_card_action_space(card_id: str, use_fn, *, placeable_fn=None) -> None:
    """Register ``card_id``'s tableau card as an action space for its owner.

    ``placeable_fn=None`` means "always one plain placement" (``[None]``).
    """
    if placeable_fn is None:
        placeable_fn = lambda state, owner_idx: [None]   # noqa: E731
    CARD_ACTION_SPACES[card_id] = CardActionSpaceSpec(
        card_id=card_id, use_fn=use_fn, placeable_fn=placeable_fn)


# ---------------------------------------------------------------------------
# Card accumulation spaces (user ruling 75 — module docstring)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CardAccumulationSpec:
    """One registered card accumulation space — a card space whose card
    stockpiles a resource on itself (Tree Inspector's wood stack).

    - ``resource_kind`` — the single resource type the card accumulates
      (``"wood"`` for Tree Inspector). Consumers filter on it (Work
      Certificate takes only building resources).
    - ``count_fn(state, owner_idx) -> int`` — the stack's current size.
    - ``remove_fn(state, owner_idx, n) -> state`` — debit ``n`` from the
      stack (the card OWNER's stock; the goods' destination is the consumer's
      business — Work Certificate credits the TAKER, who may be the other
      player, per ruling 75).
    """
    card_id: str
    resource_kind: str
    count_fn: Callable
    remove_fn: Callable


# card_id -> CardAccumulationSpec. Populated at card-module import, like every
# other card registry; empty in the Family game.
CARD_ACCUMULATIONS: dict[str, CardAccumulationSpec] = {}


def register_card_accumulation(card_id: str, resource_kind: str,
                               count_fn, remove_fn) -> None:
    """Register ``card_id``'s tableau card as an accumulation space whose
    stock other cards may read/raid (ruling 75 — module docstring)."""
    CARD_ACCUMULATIONS[card_id] = CardAccumulationSpec(
        card_id=card_id, resource_kind=resource_kind,
        count_fn=count_fn, remove_fn=remove_fn)


def card_accumulation_owner(state: GameState, card_id: str):
    """Which player has PLAYED ``card_id`` (tableau, not hand) — the owner of
    its card space; ``None`` if nobody has. Cards are dealt without overlap,
    so at most one player can own a given card."""
    for i, p in enumerate(state.players):
        if card_id in p.occupations or card_id in p.minor_improvements:
            return i
    return None


# ---------------------------------------------------------------------------
# Worker-marker helpers (occupancy)
# ---------------------------------------------------------------------------

def card_space_worker_count(player_state, card_id: str) -> int:
    """How many of the owner's workers are on ``card_id``'s card space (0 or 1
    today — one placement occupies the space for the round)."""
    return player_state.card_state.get(_WORKER_KEY_PREFIX + card_id, 0)


def card_space_occupied(player_state, card_id: str) -> bool:
    """Occupancy: a worker on the card blocks re-placement that round."""
    return card_space_worker_count(player_state, card_id) > 0


def place_card_space_worker(player_state, card_id: str):
    """The owner's PlayerState with the on-card worker marker set (the
    occupancy record of a placement; ``people_home`` accounting is the
    caller's — ``engine._apply_place_card_space_worker``)."""
    key = _WORKER_KEY_PREFIX + card_id
    n = player_state.card_state.get(key, 0)
    return fast_replace(
        player_state, card_state=player_state.card_state.set(key, n + 1))


def return_card_space_worker(state: GameState, idx: int, card_id: str) -> GameState:
    """Return the owner's on-card worker home mid-round (a card effect —
    Henpecked Husband's return): clear the marker and credit ``people_home``.
    Per the Tea Time occupancy ruling (user 2026-07-20), the vacated space is
    OPEN — occupancy is solely worker presence."""
    p = state.players[idx]
    key = _WORKER_KEY_PREFIX + card_id
    n = p.card_state.get(key, 0)
    assert n >= 1, f"no worker on card space {card_id!r} to return"
    store = (p.card_state.remove(key) if n == 1
             else p.card_state.set(key, n - 1))
    p = fast_replace(p, card_state=store, people_home=p.people_home + 1)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def clear_card_space_workers(state: GameState) -> GameState:
    """The return-home sweep: drop every on-card worker marker (both players)
    so the card spaces are placeable next round. The meeples themselves go
    home via the reset's blanket ``people_home = people_total``. Registry
    empty → O(1) no-op returning the same object (the Family fast path)."""
    if not CARD_ACTION_SPACES:
        return state
    new_players = list(state.players)
    changed = False
    for i, p in enumerate(new_players):
        kept = tuple(
            (k, v) for (k, v) in p.card_state.items
            if not k.startswith(_WORKER_KEY_PREFIX)
        )
        if len(kept) != len(p.card_state.items):
            new_players[i] = fast_replace(p, card_state=CardStore(kept))
            changed = True
    if not changed:
        return state
    return fast_replace(state, players=tuple(new_players))
