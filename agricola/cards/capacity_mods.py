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

from agricola.resources import Animals

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
# equals the standard frontier computed with the parked animals removed and
# added back). Consumers: `helpers.accommodates`, `helpers.pareto_frontier`,
# `helpers.breeding_frontier` (via the `_typed_slot_strip` family). Originally
# sheep-only (Dolly's Mother, user-proposed 2026-07-06); generalized to a
# per-species registry 2026-07-21 for the typed-holder family (Wildlife
# Reserve 1/1/1, Cattle Farm's cattle-per-pasture, Mud Patch's
# boar-per-unplanted-field-tile, Sheep Agent's sheep-per-qualifying-
# occupation). The dominance argument holds per type INDEPENDENTLY: a typed
# slot can hold only its own species, so filling it with that species never
# constrains any other animal. slots_fn(player_state) -> Animals (may read
# the farm — a dynamic count like Mud Patch's is recomputed per call; the
# strip changes the memoized internals' ARGUMENTS, so every cache keys
# honestly). Empty registry / nothing owned -> Animals() (Family
# byte-identity).
TYPED_SLOT_CARDS: list[tuple[str, Callable]] = []


def register_typed_slots(card_id: str, slots_fn: Callable) -> None:
    """Register a card's per-species slot counts (card-module import time).
    `slots_fn(state, player_state) -> Animals`; ownership-gated in the fold.

    SIGNATURE NOTE (the 2026-07-21 widening, user-approved): the fn takes BOTH
    the GameState and an explicit PlayerState — `state` because a count may
    depend on game-global facts (Truffle Searcher / Woolgrower's completed
    feeding phases, `helpers.completed_feeding_phases`), and a separate
    `player_state` (never `state.players[idx]` inside the fold) because the
    accommodation helpers are routinely handed DOCTORED players (Shepherd's
    Whistle's blanked stable, the strip's reduced animals) that differ from
    any player on `state`. Farm/tableau reads come off `player_state`;
    game-time reads off `state`."""
    TYPED_SLOT_CARDS.append((card_id, slots_fn))


def typed_slot_counts(state, player_state) -> Animals:
    """Summed per-species card-slot counts over owned cards. Empty registry /
    nothing owned -> Animals() (Family byte-identity)."""
    if not TYPED_SLOT_CARDS:
        return Animals()
    s = b = c = 0
    for card_id, slots_fn in TYPED_SLOT_CARDS:
        if _owns(player_state, card_id):
            a = slots_fn(state, player_state)
            s += a.sheep
            b += a.boar
            c += a.cattle
    return Animals(sheep=s, boar=b, cattle=c)


def sheep_slot_count(state, player_state) -> int:
    """The sheep component of `typed_slot_counts` — kept as the
    pre-generalization view (Mineral Feeder's arrangement strip reads it)."""
    return typed_slot_counts(state, player_state).sheep


def animal_holder_card_ids() -> frozenset:
    """Every REGISTERED card id that is 'able to hold animals' — typed slots,
    pasture-like capacity bins, or flexible slots. Registration-time identity
    (deliberately not ownership-gated): this is the predicate behind wording
    like Sheep Agent's "unless it is already able to hold animals"."""
    return frozenset(
        [cid for cid, _ in TYPED_SLOT_CARDS]
        + [cid for cid, _ in ANIMAL_CAP_SLOT_CARDS]
        + [cid for cid, _ in FLEXIBLE_SLOT_CARDS])


# Cards that are pasture-LIKE animal holders — a card holding up to N animals of
# ONE type without being a pasture (Stockyard B12: "up to 3 animals of the same
# type. (It is not considered a pasture)"). Folded into `extract_slots`' capacity
# list as extra ANONYMOUS single-type bins, appended AFTER every pasture-only fold
# (the per-pasture bonuses, Tinsmith's conditioned list, Herbal Garden's
# reserved-empty drop) — so nothing that treats real pastures as distinct can ever
# touch a card bin, and the rules layer (pasture scoring, pasture-referencing card
# effects) keeps reading farmyard geometry, never this list (user design direction
# 2026-07-20: fold holders into the solver's list, keep them distinct wherever
# card effects distinguish them). The accommodation solver already treats capacity
# entries as an anonymous one-type-per-bin multiset, and the frontier caches key
# on `extract_slots` OUTPUTS, so the fold is cache-safe by construction.
# caps_fn(player_state) -> tuple[int, ...] (the card's extra bin capacities; may
# read the farm — e.g. a count scaled by pastures). Empty registry / nothing
# owned -> () (Family byte-identity).
ANIMAL_CAP_SLOT_CARDS: list[tuple[str, Callable]] = []


def register_animal_cap_slots(card_id: str, caps_fn: Callable) -> None:
    """Register a pasture-like card holder's extra capacity bins (import time).
    `caps_fn(player_state) -> tuple[int, ...]`; ownership-gated in the fold."""
    ANIMAL_CAP_SLOT_CARDS.append((card_id, caps_fn))


def extra_animal_caps(player_state) -> tuple:
    """Extra anonymous single-type capacity bins from owned holder cards, in
    registration order. Empty registry / nothing owned -> () (Family)."""
    if not ANIMAL_CAP_SLOT_CARDS:
        return ()
    out: list[int] = []
    for card_id, caps_fn in ANIMAL_CAP_SLOT_CARDS:
        if _owns(player_state, card_id):
            out.extend(caps_fn(player_state))
    return tuple(out)


# Cards granting extra FLEXIBLE slots — 1 animal each, any type, mixable across
# slots, exactly the standalone-stable/house-pet shape (Petting Zoo E11: one per
# room while a pasture is orthogonally adjacent to the house — ruled MIXED-type
# 2026-07-20, the Feedyard "even different types" family, unlike Stockyard's
# same-type bin). Summed into `num_flexible` beside standalone stables + the
# house-pet fold. Deliberately independent of HOUSE_CAPACITY_MODS and the
# house-pet negation: Milking Place forbids animals in the HOUSE, and a holder
# card is not the house. count_fn(player_state) -> int. Empty registry / nothing
# owned -> 0 (Family byte-identity; cache-safe for the same reason as above).
FLEXIBLE_SLOT_CARDS: list[tuple[str, Callable]] = []


def register_flexible_slots(card_id: str, count_fn: Callable) -> None:
    """Register a card's extra flexible-slot count (import time).
    `count_fn(player_state) -> int`; ownership-gated in the fold."""
    FLEXIBLE_SLOT_CARDS.append((card_id, count_fn))


def extra_flexible_slots(player_state) -> int:
    """Extra flexible (any-type, capacity-1) slots from owned cards, summed.
    Empty registry / nothing owned -> 0 (Family)."""
    total = 0
    for card_id, count_fn in FLEXIBLE_SLOT_CARDS:
        if _owns(player_state, card_id):
            total += count_fn(player_state)
    return total


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


# ===========================================================================
# PEOPLE / HOUSING capacity  (distinct from the ANIMAL capacity registries above)
# ===========================================================================
# How many PEOPLE a player's house can hold — the ceiling on the "Family Growth
# with room" action (legal iff people_total < housing capacity). The base is the
# ROOM count (each room houses 1 person, the Family-game rule); a capacity card
# adds a bonus here. Read ONLY by the two family-growth-with-room sites
# (legality._housing_capacity, consumed by _legal_basic_wish_for_children and by
# resolution._resolve_wish_for_children's override-consume).
#
# A capacity DECREASE never evicts an existing person — people_total is untouched;
# a lower ceiling only forbids FUTURE growth, so legality stays a pure function of
# current state (memoryless). The one card that DOES evict a person (Lodger) drives
# its own removal via a schedule hook, NOT this registry.
#
# fn(state, player_idx) -> int: the extra people the owned card houses (may read
# the round from `state` — e.g. a time-limited slot). Summed across owned cards.
# Empty registry / nothing owned -> 0 -> the whole Family game is byte-identical
# (housing capacity == room count).
HOUSING_CAPACITY_MODS: list[tuple[str, Callable]] = []


def register_housing_capacity(card_id: str, bonus_fn: Callable) -> None:
    """Register a card's PEOPLE-capacity bonus. `bonus_fn(state, player_idx) -> int`
    returns the extra people the card houses for that player (Homekeeper: 1 when a
    clay/stone room touches both a field and a pasture; Bunk Beds: 1 at >=4 rooms).
    Card-module import time; ownership-gated in the fold below."""
    HOUSING_CAPACITY_MODS.append((card_id, bonus_fn))


def housing_capacity_bonus(state, player_idx: int) -> int:
    """Total PEOPLE-capacity bonus from owned cards (summed). Empty registry /
    nothing owned -> 0 (Family byte-identity)."""
    p = state.players[player_idx]
    total = 0
    for card_id, bonus_fn in HOUSING_CAPACITY_MODS:
        if _owns(p, card_id):
            total += bonus_fn(state, player_idx)
    return total


# ---------------------------------------------------------------------------
# Volatile capacity — cards whose capacity contribution can DROP outside the
# animal-granting paths (ruling 74, 2026-07-21; first member Livestock Feeder
# C86: one flexible slot per grain in supply, and grain is spent at many
# seam-less sites — sow, bake, feeding, card costs, liquidation). Rather than
# flagging every grain-spend seam (the Mud Patch pattern does not scale to an
# open-ended site list), the accommodation barrier
# (`engine._reconcile_accommodation`) consults this registry at EVERY agent-
# decision boundary: each registered fn self-gates on ownership, maintains its
# own last-confirmed watermark (CardStore), and reports whether its capacity
# input fell since the last boundary. Soundness: capacity through such a card
# only drops when its input drops, and every animal INCREASE already reconciles
# through its own path (grant_animals' flag, the market frames, the breeding
# frontier) — so "input has not fallen since the last boundary" implies no new
# violation. Empty registry -> zero cost (the Family game and every card game
# with no member card owned).
# ---------------------------------------------------------------------------

VOLATILE_CAPACITY_CARDS: list[tuple[str, Callable]] = []


def register_volatile_capacity(card_id: str, dropped_fn: Callable) -> None:
    """Register a volatile-capacity re-check. `dropped_fn(state, player_idx) ->
    (state, dropped)` is called for BOTH players at every decision boundary; it must
    self-gate on ownership (return (state, False) unchanged for a non-owner), refresh
    its watermark to the current input value at every call (write only when changed),
    and return dropped=True iff the input fell since the previous boundary."""
    VOLATILE_CAPACITY_CARDS.append((card_id, dropped_fn))


# ---------------------------------------------------------------------------
# Flexible-slot -> single-type-bin upgrades (ruling 74, 2026-07-21; first
# member Stable Master C89: "Exactly one of your unfenced stables can hold up
# to 3 animals of one type"). The upgrade converts ONE standalone (unfenced)
# stable's 1-capacity flexible slot into an anonymous single-type bin of the
# card's stated capacity — a strict upgrade (any single animal that fit the
# flexible slot fits the bin, which adds room for more of that type), so no
# player choice is surfaced. Consumed by `helpers.extract_slots`: each owned
# card's bin, while an unconverted standalone stable remains, decrements
# num_flexible by 1 and appends the bin to the cap-slot list (the Stockyard
# family — appended after every pasture-only fold, invisible to pasture
# geometry readers). Cache-safe: the frontier caches key on extract_slots'
# outputs. Empty registry -> no-op (Family byte-identical).
# ---------------------------------------------------------------------------

FLEX_TO_BIN_CARDS: list[tuple[str, Callable]] = []


def register_flexible_to_bin(card_id: str, bin_fn: Callable) -> None:
    """Register a stable-slot upgrade. `bin_fn(player_state) -> int` returns the
    single-type bin capacity the owned card provides (Stable Master: 3), or 0 when the
    card's own condition is not met. The fold applies at most one upgrade per standalone
    stable and never converts more flexible slots than exist."""
    FLEX_TO_BIN_CARDS.append((card_id, bin_fn))


def flexible_to_bin_caps(player_state, standalone_stables: int) -> tuple[int, ...]:
    """The bin capacities of the owned, applicable upgrades, capped at the number of
    standalone stables (each upgrade converts a distinct stable's slot). The caller
    (`extract_slots`) decrements num_flexible by len(result) and appends the bins."""
    if not FLEX_TO_BIN_CARDS or standalone_stables <= 0:
        return ()
    bins: list[int] = []
    for card_id, bin_fn in FLEX_TO_BIN_CARDS:
        if len(bins) >= standalone_stables:
            break
        if _owns(player_state, card_id):
            cap = bin_fn(player_state)
            if cap > 0:
                bins.append(cap)
    return tuple(bins)
