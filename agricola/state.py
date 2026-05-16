from __future__ import annotations

from dataclasses import dataclass
from typing import Optional  # used by BoardState.major_improvement_owners annotation

from agricola.constants import CellType, HouseMaterial, Phase
from agricola.pasture import compute_pastures_from_arrays
from agricola.resources import Animals, Resources


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

    # def __post_init__(self):
    #     # Auto-fill removed in CHANGES.md Change 3 to skip the BFS on
    #     # Farmyard mutations that cannot change pastures (room-builds,
    #     # plows, sows, renovations, etc.). Pasture-changing resolvers
    #     # now pass `pastures=compute_pastures_from_arrays(...)`
    #     # explicitly. See CHANGES.md Change 3 for the full rationale.
    #     computed = compute_pastures_from_arrays(
    #         self.grid, self.horizontal_fences, self.vertical_fences,
    #     )
    #     object.__setattr__(self, "pastures", computed)


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

    round_revealed: int = 0  # 0 = always available; 1–14 = the round this card appears


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

    # Minor improvement and occupation card ids the player has played.
    # Cards are NOT directly playable in Task 5 (no spaces implement
    # Lessons / play-a-minor); tests construct these directly.
    minor_improvements: frozenset = frozenset()  # frozenset[str]
    occupations:        frozenset = frozenset()  # frozenset[str]

    # TODO: Track animal locations explicitly if full-game cards require it.
    # Currently only totals are stored in Animals; location is derived from
    # pasture/stable/house capacity checks.


@dataclass(frozen=True)
class BoardState:
    # Maps action_space_id (str) -> ActionSpaceState for all 25 spaces.
    # Treat as immutable — never mutate this dict after creation.
    action_spaces: dict  # dict[str, ActionSpaceState]

    # Who owns each of the 10 major improvements (None = still on supply board).
    # Indexed by major improvement index 0–9 (see constants.py).
    major_improvement_owners: tuple  # tuple[Optional[int], ...], length 10

    # The action space card that appears at each round 1–14.
    # round_card_order[i] is the action space ID appearing at round i+1.
    # Determined randomly at setup (randomised within each stage).
    round_card_order: tuple  # tuple[str, ...], length 14


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
    # See CLAUDE.md "The pending-decision stack" for the architecture.
    pending_stack: tuple = ()  # tuple[PendingDecision, ...]
