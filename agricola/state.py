from __future__ import annotations

from dataclasses import dataclass
from typing import Optional  # used by BoardState.major_improvement_owners annotation

from agricola.constants import SPACE_IDS, SPACE_INDEX, CellType, GameMode, HouseMaterial, Phase
from agricola.resources import Animals, Resources


# ---------------------------------------------------------------------------
# Lazily-cached __hash__ for the hot state dataclasses
# ---------------------------------------------------------------------------
#
# These frozen dataclasses form a deep nested tree (GameState → players →
# farmyard → grid …) and are the keys of the MCTS transposition table, so they
# are hashed enormously often — the #1 self-time in the production NN-leaf PUCT
# profile (PROFILING.md). The default frozen `__hash__` re-hashes the whole tree
# every call; but most transitions change one small field and SHARE the rest of
# the tree by reference (see fast_replace). So we memoize each object's hash
# lazily and let a parent's hash reuse its unchanged children's cached hashes.
#
# Correctness: these objects are immutable (frozen), so a cached hash can never
# go stale — there is no sync invariant (CLAUDE.md "derived data" S5 / the
# projection-keyed exception). The cache lives in `__dict__["_hash_cache"]` via
# object.__setattr__ (no __slots__ here). It is NOT a dataclass field, so it is
# invisible to the generated __eq__/__repr__. Each class below keeps the
# generated __eq__ and supplies a matching __hash__ (same field tuple, same
# order → identical hash values, just memoized).
#
# `__hash__` is defined in the class BODY, which @dataclass(frozen=True) leaves
# intact (has_explicit_hash → the decorator adds no __hash__ of its own).

def _getstate_without_hash_cache(self):
    """Pickle state excluding the memoized hash (`_hash_cache`).

    The cached hash incorporates Python's per-process seed-randomized hashing
    of strings/enums, so it MUST NOT cross a process boundary — training loads
    pickles produced by data-gen workers. Stripping it here makes the loading
    process recompute a fresh, correct hash on first use (restoring the
    pre-cache cross-process behavior). The default `__dict__.update` restore
    path handles the trimmed dict, so no matching __setstate__ is needed.
    """
    d = self.__dict__
    if "_hash_cache" in d:
        d = dict(d)
        d.pop("_hash_cache")
    return d


@dataclass(frozen=True)
class Cell:
    cell_type: CellType = CellType.EMPTY
    grain:     int = 0  # populated iff cell_type == FIELD
    veg:       int = 0  # populated iff cell_type == FIELD
    # Note: a STABLE cell may also be enclosed by fences (derived from fence arrays)


@dataclass(frozen=True)
class Farmyard:
    # 3 rows × 5 columns of Cell objects
    grid: tuple  # tuple[tuple[Cell, ...], ...], shape (3, 5)

    # Fence encoding — two arrays, no redundancy:
    # horizontal_fences[r][c]: fence running east–west between row r-1 and row r at column c
    #   r=0: top boundary of farmyard
    #   r=3: bottom boundary of farmyard
    #   shape: (4, 5) — 4 rows of horizontal edges × 5 columns
    horizontal_fences: tuple  # tuple[tuple[bool, ...], ...], shape (4, 5)

    # vertical_fences[r][c]: fence running north–south between column c-1 and column c at row r
    #   c=0: left boundary of farmyard
    #   c=5: right boundary of farmyard
    #   shape: (3, 6) — 3 rows × 6 columns of vertical edges
    vertical_fences: tuple  # tuple[tuple[bool, ...], ...], shape (3, 6)

    # Cached pasture decomposition. Originally auto-filled by __post_init__
    # (CHANGES.md Change 2). After CHANGES.md Change 3 the auto-fill is
    # disabled: it is the responsibility of pasture-changing resolvers
    # (Fencing, Farm Expansion's stable build, Side Job's stable build,
    # Farm Redevelopment's fence build) to recompute and pass
    # `pastures=...` when constructing a new Farmyard. All other Farmyard
    # mutations leave `pastures` alone, which rides along correctly via
    # dataclasses.replace.
    pastures: tuple = ()  # tuple[Pasture, ...], canonically ordered

    def __hash__(self):  # see "Lazily-cached __hash__" note above
        h = self.__dict__.get("_hash_cache")
        if h is None:
            h = hash((self.grid, self.horizontal_fences,
                      self.vertical_fences, self.pastures))
            object.__setattr__(self, "_hash_cache", h)
        return h

    __getstate__ = _getstate_without_hash_cache


@dataclass(frozen=True)
class ActionSpaceState:
    # workers[p] = number of workers player p has on this space.
    # (0, 0) = unoccupied; (1, 0) = one worker from player 0; (2, 0) = parent+newborn from player 0.
    # NOTE (see IMPLEMENTATION_CHOICES.md #1): hardcodes 2 players; may need revision for certain cards.
    workers: tuple = (0, 0)  # tuple[int, int]

    # Building-resource accumulation spaces (forest, clay_pit, reed_bank, western_quarry,
    # eastern_quarry) store their pending goods as a Resources object. All other fields
    # default to 0. Cards like the Geologist can modify what accumulates here.
    accumulated: Resources = Resources()

    # Food/animal accumulation spaces (fishing, meeting_place, sheep_market, pig_market,
    # cattle_market) use a scalar int. These are never modified by cards in the same way.
    accumulated_amount: int = 0

    revealed: bool = False  # True once the card is turned up (permanents: True from setup)

    def __hash__(self):  # see "Lazily-cached __hash__" note above
        h = self.__dict__.get("_hash_cache")
        if h is None:
            h = hash((self.workers, self.accumulated,
                      self.accumulated_amount, self.revealed))
            object.__setattr__(self, "_hash_cache", h)
        return h

    __getstate__ = _getstate_without_hash_cache


@dataclass(frozen=True)
class CardStore:
    """Sparse, hashable per-player side-map of persistent per-card state
    (CARD_IMPLEMENTATION_PLAN.md II.7).

    A few cards carry state beyond "played or not" — Tutor's occupation-count
    snapshot, Moldboard Plow's uses-left, Big Country's banked bonus points. That
    state lives here, NOT on `occupations` / `minor_improvements` (which stay plain
    id frozensets). Only the cards that store something get an entry; a stateless
    card (the vast majority) has none, so this is one small map per player, not one
    object per played card.

    `items` is a tuple of `(card_id, value)` pairs kept SORTED by card_id, so two
    stores with the same logical contents are structurally identical → equal and
    same-hash (the transposition table needs `GameState` hashable + stable). Values
    are heterogeneous: an `int` for the common case (Tutor / Moldboard / Big
    Country), a card-specific frozen payload dataclass for the rare complex card.

    Being a frozen dataclass over a tuple field, the canonical serializer walks it
    generically (no special-casing). Card-only: the default-empty store is added to
    PlayerState's `__hash__` and to canonical's `_DEFAULT_SKIP_FIELDS`, so the
    Family game is byte-identical (empty → omitted) and the C++ engine is untouched.
    """
    items: tuple = ()   # tuple[tuple[str, Hashable], ...], sorted by card_id

    def get(self, cid: str, default=None):
        """Value stored for `cid`, or `default` if the card has no entry."""
        for k, v in self.items:
            if k == cid:
                return v
        return default

    def set(self, cid: str, value) -> "CardStore":
        """A new CardStore with `cid` mapped to `value` (one value per card —
        any existing entry is replaced). Re-sorted so the result is canonical."""
        kept = tuple((k, v) for k, v in self.items if k != cid)
        return CardStore(tuple(sorted(kept + ((cid, value),))))


@dataclass(frozen=True)
class FutureReward:
    """A non-goods reward promised at the start of a future round
    (CARD_IMPLEMENTATION_PLAN.md II.5).

    Goods/food promised on a round space already ride on
    `PlayerState.future_resources` (a `tuple[Resources, ...]`, used by the Well and
    by the goods-scheduling Category-8 cards). This sibling tuple carries the two
    things a plain `Resources` slot cannot: **animals** (collected and accommodated
    at round start — Acorns Basket, deferred) and **effect-card hooks** (a card id
    whose round-start effect fires when the round is entered — Handplow's deferred
    plow). Splitting it out keeps the Family-reachable `future_resources` structure
    (and its C++ serialization) untouched: this field is card-only, default-empty,
    skipped in the canonical JSON, so the Family game is byte-identical.

    Scheduling is **additive** — repeated placers stack on the same round slot
    (animals add, effect_card_ids union).
    """
    animals: Animals = Animals()
    effect_card_ids: frozenset = frozenset()   # round-start effect hooks (card ids)

    def __bool__(self) -> bool:
        """True iff this slot carries anything (so a default slot is falsy — lets
        `_complete_preparation` skip the whole animals/hooks branch on empty slots,
        the Family fast path). `Animals` has no `__bool__`, so check its counts."""
        a = self.animals
        return bool(a.sheep or a.boar or a.cattle or self.effect_card_ids)

    def __add__(self, other: "FutureReward") -> "FutureReward":
        return FutureReward(
            animals=self.animals + other.animals,
            effect_card_ids=self.effect_card_ids | other.effect_card_ids,
        )


@dataclass(frozen=True)
class PlayerState:
    resources:      Resources
    animals:        Animals
    farmyard:       Farmyard
    house_material: HouseMaterial  # all rooms share one material; WOOD → CLAY → STONE
    people_total:   int  # total people in play (home + placed), range 2–5
    people_home:    int  # people currently at home (available to place this round)
    newborns:       int = 0  # born during the current round; cleared in _resolve_preparation when the next round begins. Included in people_total. Used only for the harvest feeding cost discount (1 food instead of 2), which applies only when a harvest occurs at the end of their birth round.
    begging_markers: int = 0

    # Goods promised at the start of each future round (from Well, etc.)
    # Indexed 0–13 corresponding to rounds 1–14.
    # Each entry is a full Resources object (covers all 7 goods: food, wood,
    # clay, reed, stone, grain, veg). Future animals and exotic future
    # rewards are not supported by this field; a FutureRewards wrapper will
    # be introduced when needed.
    future_resources: tuple = (Resources(),) * 14  # tuple[Resources, ...], length 14

    # Non-goods rewards promised at the start of each future round
    # (CARD_IMPLEMENTATION_PLAN.md II.5) — the FutureReward sibling of
    # future_resources, one slot per round (indexed 0-13 → rounds 1-14). Each
    # slot carries animals (collected + accommodated at round start) and
    # effect-card hooks (a card id whose round-start effect fires). Card-only:
    # the default is all-empty FutureReward()s, so the Family game never populates
    # it (added to __hash__ below + to canonical's _DEFAULT_SKIP_FIELDS → byte-
    # identical Family JSON, no C++ change). Goods/food schedules stay on
    # future_resources; this carries only what a Resources slot cannot.
    future_rewards: tuple = (FutureReward(),) * 14  # tuple[FutureReward, ...], length 14

    # Minor improvement and occupation card ids the player has played.
    # Cards are NOT directly playable in Task 5 (no spaces implement
    # Lessons / play-a-minor); tests construct these directly.
    minor_improvements: frozenset = frozenset()  # frozenset[str]
    occupations:        frozenset = frozenset()  # frozenset[str]

    # Once-per-harvest conversion budget. Tracks which conversion ids
    # (joinery / pottery / basketmaker, plus any future card-registered ids)
    # have been FIRED this harvest. Reset to frozenset() inside
    # engine._resolve_harvest_field at the start of each harvest. Used by the
    # HARVEST_FEED legality enumerator to filter out already-fired conversions
    # (declining is implicit — no skip is recorded). Lives on PlayerState rather than
    # on PendingHarvestFeed per ENGINE_IMPLEMENTATION.md §2 guidance ("per-card
    # budgets that span events live on PlayerState").
    harvest_conversions_used: frozenset = frozenset()  # frozenset[str]

    # --- Card game (GameMode.CARDS) only; empty/inert in the Family game. ---
    # Private hands dealt at setup: occupation / minor-improvement card ids drawn
    # but not yet played. step / legal_actions read the DECIDER's own hand off
    # these fields (the only hand any decision needs); the opponent's hidden hand
    # is handled above the engine (ISMCTS determinization). Default empty → the
    # Family game never populates them and stays byte-identical.
    # See CARD_IMPLEMENTATION_PLAN.md I.5.
    hand_occupations: frozenset = frozenset()  # frozenset[str]
    hand_minors:      frozenset = frozenset()  # frozenset[str]

    # Scoped "have I fired this card already?" latches (CARD_IMPLEMENTATION_PLAN.md
    # II.3). Each holds card ids, cleared AT its scope boundary by the transition
    # code (engine._clear). harvest_conversions_used (above) is the per-harvest
    # scope. Default empty → the Family game never populates them and stays
    # byte-identical; engine._clear is a no-op when both players' sets are empty.
    used_this_turn:  frozenset = frozenset()  # reset in _advance_current_player + on WORK entry
    used_this_round: frozenset = frozenset()  # reset on entry to the new round (_complete_preparation)
    fired_once:      frozenset = frozenset()  # per-game one-shots; never reset

    # Persistent per-card state side-map (CARD_IMPLEMENTATION_PLAN.md II.7). A
    # sparse, hashable CardStore — empty by default, so the Family game never
    # populates it and stays byte-identical (added to __hash__ below + to
    # canonical's _DEFAULT_SKIP_FIELDS → no C++ change). See CardStore above.
    card_state:      "CardStore" = CardStore()

    # Fence pieces in the player's SUPPLY (location 4 of the four a fence can be in: on the
    # board / removed from play / on a card / in supply). Distinct from "buildable" fences,
    # which also includes those held on a card (Ash Trees) — see helpers.buildable_fences.
    # Maintained as an independent pile (decremented when a fence LEAVES supply: built from
    # supply, moved onto a card, or removed), NOT derived, because building from a card does
    # not touch supply yet does add a board fence, so `15 - built` would be wrong once a card
    # holds fences. In the Family game every fence comes from supply, so this stays exactly
    # `15 - fences_built` — but it is NOT a skip-field (its value varies), so it IS serialized
    # in Family and the C++ PlayerState mirrors it (decrement at the fence-build site).
    fences_in_supply: int = 15

    # Card-only reconciliation flag: set True when a DECISION-FREE animal grant is
    # applied (round-start collection, an on-play gain) via helpers.grant_animals. It
    # leaves the animals in `animals` even if that exceeds the farm's housing capacity;
    # the engine's accommodation barrier (engine._reconcile_accommodation, run at every
    # decision boundary in _advance_until_decision) reads this flag, and — only when it
    # is set — checks can_accommodate and, if the animals don't fit, surfaces a
    # PendingAccommodate so the player chooses which to keep (excess cooked to food).
    # The barrier clears the flag as it handles the player. Default False → the Family
    # game never sets it and stays byte-identical (added to __hash__ below + canonical's
    # _DEFAULT_SKIP_FIELDS → no C++ change). It gates the barrier's cost: without a grant
    # the boundary check is a single bool, never a can_accommodate scan.
    animals_need_accommodation: bool = False

    # TODO: Track animal locations explicitly if full-game cards require it.
    # Currently only totals are stored in Animals; location is derived from
    # pasture/stable/house capacity checks.

    def __hash__(self):  # see "Lazily-cached __hash__" note above
        h = self.__dict__.get("_hash_cache")
        if h is None:
            h = hash((self.resources, self.animals, self.farmyard,
                      self.house_material, self.people_total, self.people_home,
                      self.newborns, self.begging_markers, self.future_resources,
                      self.future_rewards,
                      self.minor_improvements, self.occupations,
                      self.harvest_conversions_used,
                      self.hand_occupations, self.hand_minors,
                      self.used_this_turn, self.used_this_round,
                      self.fired_once, self.card_state,
                      self.fences_in_supply,
                      self.animals_need_accommodation))
            object.__setattr__(self, "_hash_cache", h)
        return h

    __getstate__ = _getstate_without_hash_cache


@dataclass(frozen=True)
class BoardState:
    # ActionSpaceState for all 25 spaces, indexed by SPACE_INDEX[space_id].
    # The canonical ordering (constants.SPACE_IDS) is fixed across all games,
    # which keeps BoardState — and transitively GameState — hashable. Use the
    # `get_space` / `with_space` helpers below for keyed access; never index
    # this tuple directly with raw integers in callers.
    action_spaces: tuple  # tuple[ActionSpaceState, ...], length 25

    # Who owns each of the 10 major improvements (None = still on supply board).
    # Indexed by major improvement index 0–9 (see constants.py).
    major_improvement_owners: tuple  # tuple[Optional[int], ...], length 10

    # The per-game stage-card reveal order is hidden information and does NOT
    # live here — it is held in the Environment (agricola/environment.py).
    # BoardState carries only common knowledge; a space's `revealed` bool says
    # whether its card is up, never which future round an unrevealed card lands.

    def __hash__(self):  # see "Lazily-cached __hash__" note above
        h = self.__dict__.get("_hash_cache")
        if h is None:
            h = hash((self.action_spaces, self.major_improvement_owners))
            object.__setattr__(self, "_hash_cache", h)
        return h

    __getstate__ = _getstate_without_hash_cache


def get_space(board: BoardState, space_id: str) -> ActionSpaceState:
    """Return the ActionSpaceState for `space_id`."""
    return board.action_spaces[SPACE_INDEX[space_id]]


def with_space(board: BoardState, space_id: str, new_space: ActionSpaceState) -> BoardState:
    """Return a new BoardState with `space_id` replaced by `new_space`."""
    idx = SPACE_INDEX[space_id]
    spaces = board.action_spaces
    new_spaces = spaces[:idx] + (new_space,) + spaces[idx + 1:]
    return BoardState(
        action_spaces=new_spaces,
        major_improvement_owners=board.major_improvement_owners,
    )


@dataclass(frozen=True)
class GameState:
    round_number:    int    # 1–14
    phase:           Phase
    current_player:  int    # 0 or 1 — whose worker placement is currently being resolved
    starting_player: int    # 0 or 1 — who holds the starting player token; updated immediately when Meeting Place is taken
    players:         tuple  # tuple[PlayerState, PlayerState]
    board:           BoardState

    # Stack of pending sub-decisions (frozen dataclasses defined in
    # agricola/pending.py). Bottom-to-top; top is pending_stack[-1].
    # Empty tuple means no non-atomic action is in progress.
    # See CLAUDE.md Phase 1 (the pending-decision stack) for the concept;
    # ENGINE_IMPLEMENTATION.md §2 for the full mechanics.
    pending_stack: tuple = ()  # tuple[PendingDecision, ...]

    # Which variant this state belongs to (Family vs. the card game). Default
    # FAMILY → existing states are unchanged in shape; read wherever the two
    # variants diverge. See CARD_IMPLEMENTATION_PLAN.md I.1.
    mode: GameMode = GameMode.FAMILY

    # Four draft pools during Phase.DRAFT: (p0_occ, p0_min, p1_occ, p1_min),
    # each a tuple[str, ...] of card ids. None for Family and random-deal games.
    # Swapped between players at the end of each draft round (all pools equal
    # size > 0). Set to None when the draft completes (all pools empty).
    draft_pools: tuple | None = None

    # Card-only discriminator for the FIELD during-window's LEGACY stage: True
    # while a player's PendingHarvestField choice frame (a legacy `harvest_field`
    # trigger — Stable Manure, pre-migration) is out, so re-entering that
    # player's field-phase step after it pops skips the pre-take autos and moves
    # on to the take (engine._field_phase_step). One bool suffices because the
    # FIELD band is per-player sequential. Family-constant False
    # (default-skipped in canonical.py); retired with the legacy seam when the
    # harvest_field cards migrate to the window events.
    field_triggers_offered: bool = False

    # Card-only harvest-window walk cursor (engine._advance_harvest): the
    # VIRTUAL-walk index the walk resumes at — the HARVEST_WINDOWS ladder with
    # the FIELD band repeated once per player (harvest_windows.walk_position
    # decodes it) — set ONLY when a choice frame pauses the walk mid-segment.
    # None everywhere else — the phase derives the resume point at each harvest
    # phase boundary, so a Family game (no window cards, no frames) carries
    # None on every returned state and stays byte-identical (default-skipped
    # in canonical.py).
    harvest_cursor: int | None = None

    def __hash__(self):  # see "Lazily-cached __hash__" note above
        h = self.__dict__.get("_hash_cache")
        if h is None:
            h = hash((self.round_number, self.phase, self.current_player,
                      self.starting_player, self.players, self.board,
                      self.pending_stack, self.mode, self.draft_pools,
                      self.field_triggers_offered, self.harvest_cursor))
            object.__setattr__(self, "_hash_cache", h)
        return h

    __getstate__ = _getstate_without_hash_cache
