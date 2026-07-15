"""House-pet-capacity modifier registry (animal accommodation; CARD_AUTHORING_GUIDE §4).

The number of "flexible" animal slots a player's HOUSE provides — capacity-1 slots that
each hold one animal of ANY type (the same abstraction as a standalone stable), read by
`extract_slots` in `helpers.py`. The Family-game default is exactly 1 (the single house
pet). A capacity card raises it by adding one row here at import time; no engine edits.
`extract_slots` reads the fold accessor `house_pet_capacity`.

Empty registry (the Family game owns no cards) -> `house_pet_capacity` returns 1, so
`extract_slots`'s `num_flexible` is byte-identical to the pre-card `standalone_stables + 1`.

Only capacity-RAISING modifiers exist today (Animal Tamer: one slot per room — and the
heterogeneous-type freedom it grants is already captured by the flexible-slot model, since
`can_accommodate` sums overflow across types into a flat slot count). A future NEGATION
card — Milking Place D012, "you can no longer hold animals in your house (not even via
another card)" — must drive the result to 0, which the `max`-fold below cannot express.
Milking Place explicitly negates Animal Tamer, so the two are co-designed: wire the
negation as a separate check when Milking Place is implemented. (Out of scope now; flagged
so the `max` fold isn't mistaken for the whole story.)
"""
from __future__ import annotations

from typing import Callable

# (card_id, fn(player_state) -> int): each owned modifier proposes a house-pet-slot count;
# the fold takes the max (starting from the default 1). Capacity-raising only — see the
# module docstring on the future negation case.
HOUSE_CAPACITY_MODS: list[tuple[str, Callable]] = []


def register_house_capacity(card_id: str, capacity_fn: Callable) -> None:
    """Register a capacity card's house-pet-slot count. `capacity_fn(player_state) -> int`
    returns how many flexible house slots the card grants this player (Animal Tamer: the
    room count). Called at card-module import; ownership-gated in the fold below."""
    HOUSE_CAPACITY_MODS.append((card_id, capacity_fn))


# (card_id, fn(player_state) -> int): a flat per-PASTURE additive capacity bonus — added to
# EVERY pasture's capacity (Drinking Trough: +2). Summed across owned cards, applied in
# extract_slots to each pasture's already-computed capacity. Empty registry -> 0 -> Family
# byte-identical. Distinct from HOUSE_CAPACITY_MODS (the house's flexible-slot count): this
# raises individual pasture capacities, which each still hold exactly one animal type.
PASTURE_CAPACITY_MODS: list[tuple[str, Callable]] = []


def register_pasture_capacity(card_id: str, bonus_fn: Callable) -> None:
    """Register a flat per-pasture capacity bonus. `bonus_fn(player_state) -> int` returns
    the amount added to EVERY pasture's capacity (Drinking Trough: 2). Called at card-module
    import; ownership-gated in the fold below."""
    PASTURE_CAPACITY_MODS.append((card_id, bonus_fn))


# (card_id, fn(pasture) -> int): a PER-PASTURE CONDITIONED additive capacity bonus — the
# card inspects each individual pasture and proposes that pasture's bonus (Tinsmith Master:
# +1 for a pasture with NO stable, 0 otherwise). Distinct from PASTURE_CAPACITY_MODS above,
# whose bonus is flat across every pasture and cannot condition on pasture shape. Summed
# across owned cards per pasture, applied in extract_slots alongside the flat fold (also
# after the stable doubling, to the FINAL capacity). Empty registry -> None from the fold
# -> Family byte-identical. Cache safety: the accommodation caches (_animal_points_cached,
# _phi_cached) key on extract_slots' OUTPUTS (caps_tuple, num_flexible), computed
# downstream of this fold, so a conditioned bonus changes the key itself and staleness is
# impossible by construction (CARD_ENGINE_IMPLEMENTATION.md §5.4's projection-key contract).
PASTURE_CAPACITY_PER_MODS: list[tuple[str, Callable]] = []


def register_pasture_capacity_per(card_id: str, bonus_fn: Callable) -> None:
    """Register a per-pasture conditioned capacity bonus. `bonus_fn(pasture) -> int`
    returns the amount added to THAT pasture's capacity (Tinsmith Master: 1 if the pasture
    has no stable, else 0). Called at card-module import; ownership-gated in the fold
    below."""
    PASTURE_CAPACITY_PER_MODS.append((card_id, bonus_fn))


def pasture_capacity_per_list(player_state, pastures) -> list | None:
    """Per-pasture conditioned bonuses from owned cards, as a list parallel to
    `pastures` (each entry the sum of every owned card's bonus for that pasture) — or
    None when no registered card is owned (the Family fast path: empty registry /
    nothing owned -> None -> extract_slots adds nothing, byte-identical)."""
    if not PASTURE_CAPACITY_PER_MODS:
        return None
    owned = [fn for card_id, fn in PASTURE_CAPACITY_PER_MODS
             if _owns(player_state, card_id)]
    if not owned:
        return None
    return [sum(fn(p) for fn in owned) for p in pastures]


def _owns(player_state, card_id: str) -> bool:
    return card_id in player_state.occupations or card_id in player_state.minor_improvements


# Cards that FORBID holding animals in the house — Milking Place D12's "You can
# no longer hold animals in your house (not even via another card)". A negation
# beats every raise (the printed "not even via another card" overrides Animal
# Tamer), so it is applied before the max-fold, driving the count to 0. Empty in
# the Family game.
HOUSE_PET_NEGATIONS: set[str] = set()


def register_house_pet_negation(card_id: str) -> None:
    """Register a card that forbids house animals outright (card-module import
    time). Overrides every capacity raise."""
    HOUSE_PET_NEGATIONS.add(card_id)


def house_pet_capacity(player_state) -> int:
    """Flexible animal slots provided by the house: 1 (the default pet) unless an owned
    capacity card raises it — or 0 when an owned card FORBIDS house animals
    (Milking Place; the negation beats every raise, per its printed "not even
    via another card"). Empty registries -> 1 (Family byte-identity)."""
    if HOUSE_PET_NEGATIONS and any(_owns(player_state, cid)
                                   for cid in HOUSE_PET_NEGATIONS):
        return 0
    cap = 1
    for card_id, capacity_fn in HOUSE_CAPACITY_MODS:
        if _owns(player_state, card_id):
            cap = max(cap, capacity_fn(player_state))
    return cap


# Cards that HOLD animals of one specific type — Dolly's Mother E84's "This
# card can hold 1 sheep." Unlike a flexible slot (any type), a typed slot
# cannot ride `num_flexible`; instead the accommodation entry points apply the
# GREEDY STRIP (user-proposed, 2026-07-06, exact by dominance: parking a sheep
# on a sheep-only slot never hurts the other animals, so an owner's frontier
# equals the standard frontier computed with `sheep_slot_count` fewer sheep,
# the parked sheep added back). Consumers: `helpers.accommodates`,
# `helpers.pareto_frontier`, `helpers.breeding_frontier`. Empty in the Family
# game.
SHEEP_SLOT_CARDS: dict[str, int] = {}


def register_sheep_slot(card_id: str, slots: int) -> None:
    """Register a card that holds `slots` sheep (card-module import time)."""
    SHEEP_SLOT_CARDS[card_id] = slots


def sheep_slot_count(player_state) -> int:
    """Sheep-only card slots this player owns (Dolly's Mother: 1). Empty
    registry / nothing owned -> 0 (Family byte-identity)."""
    if not SHEEP_SLOT_CARDS:
        return 0
    return sum(n for cid, n in SHEEP_SLOT_CARDS.items()
               if _owns(player_state, cid))


# Cards that let SHEEP breed from a single parent — Dolly's Mother E84's "You
# only require 1 sheep to breed sheep during the breeding phase of a harvest."
# Read by `helpers.breeding_frontier` / `breeding_food_gained` (the
# sheep_min_parents argument joins their memo keys) and by the breeding-outcome
# computation in `resolution._execute_breed`. Empty in the Family game.
SINGLE_PARENT_SHEEP_CARDS: set[str] = set()


def register_single_parent_sheep(card_id: str) -> None:
    """Register a card that lets sheep breed from 1 parent (import time)."""
    SINGLE_PARENT_SHEEP_CARDS.add(card_id)


def sheep_min_parents(player_state) -> int:
    """How many sheep this player needs for sheep to breed: 2 (the rule) or 1
    with an owned single-parent card. Empty registry -> 2 (Family)."""
    if SINGLE_PARENT_SHEEP_CARDS and any(_owns(player_state, cid)
                                         for cid in SINGLE_PARENT_SHEEP_CARDS):
        return 1
    return 2


# Cards that FORBID animals in one of the player's pastures — a standing capacity
# restriction: "at least one of your pastures must contain no animals" (Herbal Garden
# E36) / "one of your pastures with a stable cannot hold animals" (Beaver Colony E33).
# Each owned member reserves ONE qualifying pasture empty; `extract_slots` then drops the
# smallest-capacity reserved pasture from the capacity list (dropping the smallest is
# optimal for maximum housing — a larger remaining capacity multiset never houses fewer).
# A member's `qualifies_fn(pasture) -> bool` restricts which pastures satisfy it (Herbal:
# any pasture; Beaver: `pasture.num_stables >= 1`).
#
# Arrangement sharing (user ruling 2026-07-13): when one pasture satisfies two members'
# predicates, a SINGLE empty pasture covers both (Herbal + Beaver share one empty
# pasture-with-stable — the optimal play). And when a member has NO qualifying pasture
# (Beaver with no pasture-with-stable — e.g. after Overhaul razes it), that member imposes
# NO restriction at all (it is dropped). The fold below is exact for the current
# nested-predicate members. Empty registry -> no reduction (Family byte-identity).
EMPTY_PASTURE_CARDS: list[tuple[str, Callable]] = []


def register_empty_pasture(card_id: str, qualifies_fn: Callable) -> None:
    """Register a card that forces one qualifying pasture to hold no animals.
    `qualifies_fn(pasture) -> bool` says which pastures can be the empty one (Herbal
    Garden: any pasture; Beaver Colony: `p.num_stables >= 1`). Import-time; ownership-gated
    in the fold below."""
    EMPTY_PASTURE_CARDS.append((card_id, qualifies_fn))


def reserved_empty_pasture_indices(player_state, pastures, capacities) -> set:
    """Indices (into `pastures`/`capacities`) of pastures that owned "empty-pasture" cards
    force to hold no animals — the minimum-capacity set satisfying every owned member,
    dropping any member with no qualifying pasture.

    `pastures` is the `Pasture` list; `capacities` the parallel (bonus-applied) capacity
    list. Empty registry / nothing owned -> empty set (Family byte-identity). Greedy,
    strictest-predicate-first: for each still-uncovered member reserve its smallest-capacity
    qualifying pasture, which also covers every looser member that pasture satisfies — exact
    for nested predicates (the current cards)."""
    if not EMPTY_PASTURE_CARDS or not pastures:
        return set()
    quals = []
    for card_id, qualifies_fn in EMPTY_PASTURE_CARDS:
        if not _owns(player_state, card_id):
            continue
        idxs = frozenset(i for i, p in enumerate(pastures) if qualifies_fn(p))
        if idxs:                       # a member with no qualifying pasture imposes nothing
            quals.append(idxs)
    reserved: set = set()
    for idxs in sorted(quals, key=len):        # strictest (smallest set) first
        if reserved & idxs:                    # already covered by an earlier reservation
            continue
        reserved.add(min(idxs, key=lambda i: capacities[i]))
    return reserved


def pasture_capacity_bonus(player_state) -> int:
    """Flat per-pasture capacity bonus from owned cards (Drinking Trough: +2 each), summed.
    Empty registry / no owned modifier -> 0 (Family byte-identity). Applied AFTER the stable
    doubling — the card adds animals to the FINAL pasture capacity ("with or without a
    stable"), so extract_slots adds it to each already-computed pasture capacity, not inside
    the 2*cells*2^stables formula."""
    total = 0
    for card_id, bonus_fn in PASTURE_CAPACITY_MODS:
        if _owns(player_state, card_id):
            total += bonus_fn(player_state)
    return total
