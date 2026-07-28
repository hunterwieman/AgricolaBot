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
count in the PLACING player's CardStore under the machinery key
``"card_space_worker:<card_id>"`` (a machinery-owned key, distinct from the
card's own ``card_id`` entry — Collector keeps its use counter there); the
occupancy READ aggregates both players' markers (ruling 86 — a "for all"
space holds one worker total per round, either player's). Per the Tea Time
occupancy ruling (user 2026-07-20: what makes a space illegal to place on is
the presence of a worker on it, nothing else), a card effect that returns the
on-card worker home mid-round re-opens the space.

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

    Both functions carry the ACTING player and the card's OWNER separately
    (ruling 86 — the "for all" spaces put another player's worker on your
    card, so the two roles split; on a "for you only" space they are always
    the same player):

    - ``use_fn(state, placer_idx, owner_idx, picks) -> state`` performs the
      space's action at the hosted use's work step (Proceed) — the acting
      player is the one whose worker stands on the card. ``picks`` is the
      placement's payload (the chosen variant) — ``None`` for a plain
      placement.
    - ``placeable_fn(state, placer_idx, owner_idx) -> list[picks | None]``
      returns the legal placement variants for THAT acting player right now:
      ``[None]`` = one plain placement; a list of picks tuples = the wide
      variants (one ``PlaceWorker`` each); ``[]`` = not placeable now (e.g.
      an empty accumulation card, mirroring the engine's prune of placements
      on empty board accumulation spaces).
    - ``for_all`` — False = "for you only" (only the owner may place; the
      opponent never sees the placement); True = "for all" (either player may
      place).
    - ``toll`` — the "must first pay you …" cost a NON-OWNER pays the owner to
      use a for-all space (ruling 86: unpayable → the placement/arrival is
      illegal; owed PER USE however the worker arrives; paid BEFORE the use's
      before-window benefits, so nothing the use grants can fund it). None =
      no toll (Archway, every for-you-only space).
    """
    card_id: str
    use_fn: Callable
    placeable_fn: Callable
    for_all: bool = False
    toll: object = None          # Cost | None


# card_id -> CardActionSpaceSpec. Populated at card-module import, like every
# other card registry; empty in the Family game.
CARD_ACTION_SPACES: dict[str, CardActionSpaceSpec] = {}


def register_card_action_space(card_id: str, use_fn, *, placeable_fn=None,
                               for_all: bool = False, toll=None) -> None:
    """Register ``card_id``'s tableau card as an action space (owner-only by
    default; ``for_all=True`` for the "action space for all" cards, with the
    non-owner ``toll`` where printed).

    ``placeable_fn=None`` means "always one plain placement" (``[None]``).
    """
    if toll is not None and toll.resources.food:
        # The FOOD tolls (Forest Inn, Alchemists Lab) need the liquidation-
        # aware raise path (ruling 86 item 2 — a plain food gate would delete
        # rules-legal placements, ruling 82). Build-order guard, not a rule:
        # remove when that path lands with those two cards.
        raise NotImplementedError(
            "food tolls await the raise-path build (ruling 86 item 2)")
    if placeable_fn is None:
        placeable_fn = lambda state, placer_idx, owner_idx: [None]   # noqa: E731
    CARD_ACTION_SPACES[card_id] = CardActionSpaceSpec(
        card_id=card_id, use_fn=use_fn, placeable_fn=placeable_fn,
        for_all=for_all, toll=toll)


def toll_payable(state: GameState, payer_idx: int, toll) -> bool:
    """Can `payer_idx` pay this toll right now — on the PRE-use state (ruling
    84 item 8: the toll fires before every benefit of the use, so nothing the
    use grants is available). Non-food goods only today (the registration
    guard above); a plain have-it read is exact for them — no at-any-time
    conversion produces grain/wood/clay/reed/stone."""
    r = state.players[payer_idx].resources
    t = toll.resources
    return (r.wood >= t.wood and r.clay >= t.clay and r.reed >= t.reed
            and r.stone >= t.stone and r.grain >= t.grain and r.veg >= t.veg
            and r.food >= t.food)


def pay_card_space_toll(state: GameState, payer_idx: int, owner_idx: int,
                        toll) -> GameState:
    """Transfer the toll from the payer to the OWNER (ruling 86 item 2 — the
    engine's player-to-player payment; everything else burns to the supply).

    Ruling 84 item 7: a toll received IS "obtaining" those goods for the
    payee — when the obtain-reactor seam lands (Hayloft Barn B21, Wolf E103,
    Agricultural Labourer C120), this credit is the single site that must
    fire it."""
    payer = state.players[payer_idx]
    owner = state.players[owner_idx]
    payer = fast_replace(payer, resources=payer.resources - toll.resources)
    owner = fast_replace(owner, resources=owner.resources + toll.resources)
    by_idx = {payer_idx: payer, owner_idx: owner}
    return fast_replace(state, players=tuple(
        by_idx.get(i, state.players[i]) for i in range(len(state.players))))


def played_card_owner(state: GameState, card_id: str):
    """Which player has PLAYED ``card_id`` (tableau, not hand) — the owner of
    its card space; ``None`` if nobody has. Cards are dealt without overlap,
    so at most one player can own a given card."""
    for i, p in enumerate(state.players):
        if card_id in p.occupations or card_id in p.minor_improvements:
            return i
    return None


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


# Back-compat alias: the accumulation consumers (Work Certificate) predate the
# general name. One implementation — `played_card_owner` above.
card_accumulation_owner = played_card_owner


# ---------------------------------------------------------------------------
# Worker-marker helpers (occupancy)
# ---------------------------------------------------------------------------

def card_space_worker_count(player_state, card_id: str) -> int:
    """How many of THIS player's workers are on ``card_id``'s card space (the
    marker lives in the PLACING player's CardStore — whose ``people_home`` was
    debited, whose meeple it is; on a "for you only" space the placer is
    always the owner, which is why older docs said "the owner's store")."""
    return player_state.card_state.get(_WORKER_KEY_PREFIX + card_id, 0)


def card_space_occupied(state: GameState, card_id: str) -> bool:
    """Occupancy: ANY player's worker on the card blocks re-placement that
    round (ruling 86 — "for all" spaces follow standard occupancy: one worker
    total per round, either player's; an occupancy-exemption card composes
    here exactly as on board spaces, via its own seam)."""
    return any(card_space_worker_count(p, card_id) for p in state.players)


def place_card_space_worker(player_state, card_id: str):
    """The owner's PlayerState with the on-card worker marker set (the
    occupancy record of a placement; ``people_home`` accounting is the
    caller's — ``engine._apply_place_card_space_worker``)."""
    key = _WORKER_KEY_PREFIX + card_id
    n = player_state.card_state.get(key, 0)
    return fast_replace(
        player_state, card_state=player_state.card_state.set(key, n + 1))


def return_card_space_worker(state: GameState, idx: int, card_id: str) -> GameState:
    """Return player `idx`'s on-card worker home mid-round (a card effect —
    Henpecked Husband's / Sheep Inspector's card-target returns): clear the
    marker and credit ``people_home``. Per the Tea Time occupancy ruling (user
    2026-07-20), the vacated space is OPEN — occupancy is solely worker
    presence.

    Notifies `worker_moves.notify_worker_returned` itself (with the
    "card:<id>" location) — the return-chokepoint convention: the standing-
    worker ledger entry is dropped there and the returned-hooks fire, so a
    caller must NOT notify again."""
    p = state.players[idx]
    key = _WORKER_KEY_PREFIX + card_id
    n = p.card_state.get(key, 0)
    assert n >= 1, f"no worker on card space {card_id!r} to return"
    store = (p.card_state.remove(key) if n == 1
             else p.card_state.set(key, n - 1))
    p = fast_replace(p, card_state=store, people_home=p.people_home + 1)
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))
    from agricola.cards.worker_moves import notify_worker_returned
    return notify_worker_returned(state, idx, f"card:{card_id}")


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
