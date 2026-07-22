"""Tests for Plow Builder (occupation, E91; rulings 74 + 75, 2026-07-21).

Card text (verbatim): "You can build the Joinery when taking a "Minor
Improvement" action. If you use the Joinery (or an upgrade thereof) during the
harvest, you can pay 1 food to plow 1 field."

Ruling 75 item 7 (user, 2026-07-21): no Joinery upgrades exist today; clause 2
is a FUSED trigger — the Joinery conversion AND the pay-1-food plow as one
fired action, available throughout the harvest (every span window), sharing
the Joinery's once-per-harvest budget ("joinery" in
`harvest_conversions_used`) with the plain surfaces.

Coverage:

- Registration on every surface: occupation spec, the free-span trigger set,
  the minor-action major-build seam row, the before_play_minor swap trigger —
  and the NEGATIVES the design demands: no cost formula (the Joinery builds at
  its NORMAL printed cost) and no conversion row of its own (the fused trigger
  consumes the Joinery's).
- Clause 1 end-to-end in CARDS mode: Meeting Place -> the minor branch
  takeable with NO playable minor in hand (the seam's gate) -> the swap
  trigger -> the Joinery built at the printed 2 wood + 2 stone; the decline
  path (playing a hand minor normally); the branch-gate negatives.
- The fused trigger at a real span window through the REAL banded harvest
  walk: wood -1, net food +1 (the +2 conversion covers the 1-food plow), a
  plow committed onto a real cell, the Joinery budget consumed — and the
  plain craft_span_joinery trigger then blocked, and vice versa (a plain
  window or feed use blocks the fused trigger and grants NO plow).
- Eligibility negatives: card not owned / Joinery not this player's / no wood
  / no plowable cell (each verified at the real surface).
- The early-harvest value case (the ruled point of the span availability):
  firing at start_of_feeding nets +1 food that then pays the feeding —
  begging-free where the no-fire walk begs.
"""
from __future__ import annotations

import agricola.cards.plow_builder  # noqa: F401  (register the card)

import dataclasses

from agricola.actions import (
    ChooseSubAction,
    CommitBreed,
    CommitBuildMajor,
    CommitConvert,
    CommitFieldTake,
    CommitHarvestConversion,
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.cost_mods import FORMULA_MODS
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import (
    FREE_SPAN_EVENTS,
    HARVEST_WINDOW_CARDS,
    SENTINEL_WINDOWS,
)
from agricola.cards.plow_builder import CARD_ID, JOINERY_IDX
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, GameMode, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import (
    MINOR_ACTION_MAJOR_BUILDS,
    legal_actions,
    minor_action_major_build_options,
)
from agricola.pending import (
    PendingBuildMajor,
    PendingHarvestFeed,
    PendingHarvestWindow,
    PendingPlayMinor,
    PendingPlow,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_majors, with_phase, with_resources
from tests.test_utils import sole_play_minor

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)

_CRAFT_SPAN_JOINERY = "craft_span_joinery"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, idx):
    p = state.players[idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == idx else state.players[i] for i in range(2)),
    )


def _cards_harvest_state(*, joinery_owner=0, wood=0, food=10, give_occ=True):
    """A CARDS-mode HARVEST_FIELD-phase state at the fresh walk entry: P0 is
    starting player, owns Plow Builder (unless give_occ is False) and holds
    `wood`/`food`; the Joinery belongs to `joinery_owner` (None = unbuilt);
    P1 is food-rich so its frames resolve trivially."""
    cs, _env = setup_env(5, card_pool=_POOL)
    assert cs.mode is GameMode.CARDS
    cs = with_phase(cs, Phase.HARVEST_FIELD)
    cs = dataclasses.replace(
        cs, starting_player=0, pending_stack=(), harvest_cursor=None)
    if joinery_owner is not None:
        cs = with_majors(cs, owner_by_idx={JOINERY_IDX: joinery_owner})
    if give_occ:
        cs = _give_occupation(cs, 0)
    cs = with_resources(cs, 0, food=food, wood=wood)
    cs = with_resources(cs, 1, food=99)
    return cs


def _neutral_action(state):
    """An action that advances the harvest walk WITHOUT firing any Joinery
    surface: the mechanical commits first, then Proceed/Stop, never a
    FireTrigger or a CommitHarvestConversion."""
    actions = legal_actions(state)
    for kind in (CommitFieldTake, CommitConvert, CommitBreed):
        for a in actions:
            if isinstance(a, kind):
                return a
    for a in actions:
        if isinstance(a, (Proceed, Stop)):
            return a
    for a in actions:
        if not isinstance(a, (FireTrigger, CommitHarvestConversion)):
            return a
    raise AssertionError(f"no neutral action among {actions}")


def _joinery_offers(state):
    """Every surface currently offering a Joinery use: the fused trigger, the
    plain craft-span window trigger, and the feed-frame conversion."""
    return [
        a for a in legal_actions(state)
        if (isinstance(a, FireTrigger)
            and a.card_id in (CARD_ID, _CRAFT_SPAN_JOINERY))
        or (isinstance(a, CommitHarvestConversion)
            and a.conversion_id == "joinery")
    ]


def _walk_until(state, stop_pred, *, max_steps=500):
    """Neutral-step the harvest walk until stop_pred(state) or the harvest
    ends. Returns (state, offers_seen): every Joinery offer observed at
    decisions stepped THROUGH (not the stop state itself)."""
    offers_seen = []
    state = _advance_until_decision(state)
    for _ in range(max_steps):
        if state.phase not in _HARVEST_PHASES:
            return state, offers_seen
        if stop_pred(state):
            return state, offers_seen
        offers_seen.extend(_joinery_offers(state))
        state = step(state, _neutral_action(state))
    raise AssertionError("harvest walk did not terminate")


def _top_is_p0_feed(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return (isinstance(top, PendingHarvestFeed) and top.player_idx == 0
            and not top.conversion_done)


def _top_is_p0_window(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestWindow) and top.player_idx == 0


def _top_is_p0_start_of_feeding(state):
    return _top_is_p0_window(state) and \
        state.pending_stack[-1].window_id == "start_of_feeding"


def _num_fields(player_state):
    grid = player_state.farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if grid[r][c].cell_type == CellType.FIELD)


def _fill_empty_cells_with_fields(state, idx):
    """Leave player `idx` with NO plowable cell: every EMPTY farmyard cell
    becomes an (unsown) field. Sown crops are untouched, so the field take
    stays empty."""
    grid = state.players[idx].farmyard.grid
    overrides = {(r, c): Cell(cell_type=CellType.FIELD)
                 for r in range(3) for c in range(5)
                 if grid[r][c].cell_type == CellType.EMPTY}
    return with_grid(state, idx, overrides)


def _commit_the_plow(state):
    """At the just-pushed PendingPlow: commit onto a real cell, then Stop out
    of the after-phase. Returns the state with the host frame back on top."""
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.initiated_by_id == f"card:{CARD_ID}"
    plows = [a for a in legal_actions(state) if isinstance(a, CommitPlow)]
    assert plows
    state = step(state, plows[0])
    assert Stop() in legal_actions(state)
    return step(state, Stop())


def _mp_state(*, hand_minors=frozenset(), give_occ=True, **res):
    """A CARDS-mode state with the current player owning Plow Builder (unless
    give_occ=False), the given hand minors, and exactly the given resources;
    the opponent's hand is emptied. Returns (state, current_player)."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(
        p,
        hand_minors=frozenset(hand_minors),
        occupations=(p.occupations | {CARD_ID}) if give_occ else p.occupations,
        resources=Resources(**res),
    )
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _joinery_commits(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitBuildMajor) and a.major_idx == JOINERY_IDX]


# --- Registration -----------------------------------------------------------

def test_registered_on_every_surface():
    # A no-op on-play occupation (pure recurring effects).
    assert CARD_ID in OCCUPATIONS
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) is state

    # The fused trigger: on EVERY free-span event, with the window hooks
    # indexed for the non-sentinel windows (ruling 75 item 7).
    for event in FREE_SPAN_EVENTS:
        assert any(e.card_id == CARD_ID for e in TRIGGERS.get(event, ())), event
        if event not in SENTINEL_WINDOWS:
            assert CARD_ID in HARVEST_WINDOW_CARDS.get(event, set()), event

    # The named-minor-action build seam row + the swap trigger (ruling 74).
    assert MINOR_ACTION_MAJOR_BUILDS[CARD_ID] == JOINERY_IDX
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("before_play_minor", ()))

    # The Joinery builds at its NORMAL printed cost — NO formula (contrast
    # Braid Maker's printed 1r+1s price).
    assert not any(cid == CARD_ID
                   for cid, _a, _f in FORMULA_MODS.get("build_major", ()))
    # No conversion row of its own — the fused trigger consumes the Joinery's
    # built-in budget, it does not add a second conversion.
    assert CARD_ID not in HARVEST_CONVERSIONS


# --- Clause 1: the named-minor-action build, end-to-end (CARDS mode) ---------

def test_meeting_place_swap_builds_joinery_with_no_playable_minor():
    """Meeting Place, empty hand: the minor branch is takeable purely on the
    seam's gate; the frame's only action is the swap trigger; firing it
    converts the named action into the Joinery build at the printed
    2 wood + 2 stone (no formula)."""
    cs, cp = _mp_state(wood=2, stone=2)
    cs = step(cs, PlaceWorker(space="meeting_place"))

    # The branch is gated IN despite no playable hand minor (the seam's gate).
    acts = legal_actions(cs)
    assert ChooseSubAction(name="play_minor") in acts
    assert Proceed() in acts

    cs = step(cs, ChooseSubAction(name="play_minor"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayMinor) and top.minor_improvement_action
    # No hand minor is playable, so the swap trigger is the frame's only action
    # (the gate<->eligibility agreement the seam's caller contract demands).
    assert legal_actions(cs) == [FireTrigger(card_id=CARD_ID)]

    cs = step(cs, FireTrigger(card_id=CARD_ID))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    assert top.allowed_majors == (JOINERY_IDX,)
    # Menu-restricted to the Joinery, at its NORMAL printed cost.
    acts = legal_actions(cs)
    assert acts == [CommitBuildMajor(major_idx=JOINERY_IDX,
                                     payment=Resources(wood=2, stone=2))]

    cs = step(cs, acts[0])
    assert cs.board.major_improvement_owners[JOINERY_IDX] == cp
    res = cs.players[cp].resources
    assert res.wood == 0 and res.stone == 0

    # Unwind: build-major after-phase, then the Meeting Place parent.
    assert legal_actions(cs) == [Stop()]
    cs = step(cs, Stop())
    assert legal_actions(cs) == [Proceed()]     # minor branch consumed
    cs = step(cs, Proceed())
    assert legal_actions(cs) == [Stop()]
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


def test_meeting_place_decline_by_playing_a_minor_normally():
    """With a playable hand minor, both routes surface at the frame; playing
    the minor normally is the swap's implicit decline."""
    cs, cp = _mp_state(hand_minors={"market_stall"}, grain=1, wood=2, stone=2)
    cs = step(cs, PlaceWorker(space="meeting_place"))
    cs = step(cs, ChooseSubAction(name="play_minor"))

    acts = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) in acts
    play = sole_play_minor(cs, "market_stall")
    assert play in acts

    cs = step(cs, play)
    # The minor was played; the Joinery was NOT built, resources kept.
    assert cs.board.major_improvement_owners[JOINERY_IDX] is None
    res = cs.players[cp].resources
    assert res.wood == 2 and res.stone == 2
    # After-phase: the before_play_minor swap is no longer offered.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)
    assert Stop() in legal_actions(cs)


def test_meeting_place_branch_stays_gated_without_the_build():
    """No playable minor AND no available swap -> the branch is not offered
    (exactly the pre-seam gate)."""
    # Unaffordable Joinery (no wood/stone).
    cs, _cp = _mp_state()
    cs = step(cs, PlaceWorker(space="meeting_place"))
    assert legal_actions(cs) == [Proceed()]
    # Joinery already built.
    cs2, cp2 = _mp_state(wood=2, stone=2)
    cs2 = with_majors(cs2, owner_by_idx={JOINERY_IDX: 1 - cp2})
    cs2 = step(cs2, PlaceWorker(space="meeting_place"))
    assert legal_actions(cs2) == [Proceed()]
    # Card not owned.
    cs3, _cp3 = _mp_state(give_occ=False, wood=2, stone=2)
    cs3 = step(cs3, PlaceWorker(space="meeting_place"))
    assert legal_actions(cs3) == [Proceed()]
    # The options predicate itself (the gate<->trigger agreement's shared
    # source of truth) tracks the same conditions.
    cs4, cp4 = _mp_state(wood=2, stone=2)
    assert (CARD_ID, JOINERY_IDX) in minor_action_major_build_options(cs4, cp4)
    assert minor_action_major_build_options(cs3, _cp3) == []


# --- Clause 2: the fused trigger at a real span window -----------------------

def test_fused_fire_plows_and_consumes_the_joinery_budget():
    """The one fired action (ruling 75 item 7): wood -1, net food +1 (the +2
    conversion covers the 1-food plow), a plow committed onto a real cell,
    the SHARED Joinery budget marked — the plain craft_span_joinery trigger
    and the feed offer are then blocked for the rest of the harvest."""
    state = _cards_harvest_state(wood=2)
    state, _ = _walk_until(state, _top_is_p0_window)
    assert _top_is_p0_window(state)
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    # The plain use co-surfaces on the same window (craft_major_span) until
    # either fire consumes the shared budget.
    assert FireTrigger(card_id=_CRAFT_SPAN_JOINERY) in acts
    assert Proceed() in acts

    res0 = state.players[0].resources
    fields0 = _num_fields(state.players[0])
    state = step(state, FireTrigger(card_id=CARD_ID))
    res1 = state.players[0].resources
    assert res1.wood == res0.wood - 1
    assert res1.food == res0.food + 1      # +2 conversion, -1 plow cost
    assert "joinery" in state.players[0].harvest_conversions_used

    state = _commit_the_plow(state)
    assert _num_fields(state.players[0]) == fields0 + 1

    # Back on the window frame: the budget is spent, so the plain craft-span
    # trigger is blocked despite the second wood — only the decline remains.
    assert _top_is_p0_window(state)
    assert legal_actions(state) == [Proceed()]
    # ... and no later surface (feed offer included) fires this harvest.
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


def test_plain_window_use_grants_no_plow_and_blocks_the_fused_trigger():
    """The plain Joinery use is a SEPARATE surface: firing craft_span_joinery
    performs the bare exchange (no plow), and the shared budget then blocks
    the fused trigger for the rest of the harvest."""
    state = _cards_harvest_state(wood=2)
    state, _ = _walk_until(state, _top_is_p0_window)
    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id=_CRAFT_SPAN_JOINERY))
    res1 = state.players[0].resources
    assert res1.wood == res0.wood - 1
    assert res1.food == res0.food + 2      # the bare exchange, no plow cost
    assert "joinery" in state.players[0].harvest_conversions_used
    # No plow was granted by the plain use.
    assert not any(isinstance(f, PendingPlow) for f in state.pending_stack)
    # The fused trigger is blocked on this frame (budget) — only the decline.
    assert legal_actions(state) == [Proceed()]
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


def test_plain_feed_use_grants_no_plow_and_blocks_the_fused_trigger():
    """Same in the feed direction: the FEED offering performs the bare
    exchange (no plow) and its fire blocks the fused trigger."""
    state = _cards_harvest_state(wood=2)
    state, _ = _walk_until(state, _top_is_p0_feed)
    assert _top_is_p0_feed(state)
    assert CommitHarvestConversion(conversion_id="joinery") in legal_actions(state)
    res0 = state.players[0].resources
    state = step(state, CommitHarvestConversion(conversion_id="joinery"))
    res1 = state.players[0].resources
    assert res1.wood == res0.wood - 1
    assert res1.food == res0.food + 2
    assert "joinery" in state.players[0].harvest_conversions_used
    assert not any(isinstance(f, PendingPlow) for f in state.pending_stack)
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []              # despite the second wood


# --- Eligibility negatives (each at the real surface) ------------------------

def test_not_owned_never_offered():
    """P0 owns the Joinery + wood but NOT the card: the plain craft-span
    trigger surfaces, the fused trigger never does."""
    state = _cards_harvest_state(give_occ=False, wood=2)
    state, _ = _walk_until(state, _top_is_p0_window)
    acts = legal_actions(state)
    assert FireTrigger(card_id=_CRAFT_SPAN_JOINERY) in acts
    assert FireTrigger(card_id=CARD_ID) not in acts


def test_no_joinery_never_offered():
    """The Joinery belongs to the OPPONENT: the fused trigger never surfaces
    for P0 anywhere on the walk (and P1, woodless, gets nothing either)."""
    state = _cards_harvest_state(joinery_owner=1, wood=2)
    state, offers = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers == []


def test_no_wood_never_offered():
    """No conversion input on hand: no surface offers anything, no window
    frame is ever hosted."""
    state = _cards_harvest_state(wood=0)
    saw_window_frame = False
    state = _advance_until_decision(state)
    for _ in range(500):
        if state.phase not in _HARVEST_PHASES:
            break
        assert _joinery_offers(state) == []
        if any(isinstance(f, PendingHarvestWindow) for f in state.pending_stack):
            saw_window_frame = True
        state = step(state, _neutral_action(state))
    else:
        raise AssertionError("harvest walk did not terminate")
    assert not saw_window_frame


def test_no_plowable_cell_not_offered():
    """Every empty cell filled: the plow half is undoable, so the fused
    trigger is withheld (never a dead end) while the plain craft-span
    trigger still surfaces."""
    state = _cards_harvest_state(wood=2)
    state = _fill_empty_cells_with_fields(state, 0)
    state, _ = _walk_until(state, _top_is_p0_window)
    acts = legal_actions(state)
    assert FireTrigger(card_id=_CRAFT_SPAN_JOINERY) in acts
    assert FireTrigger(card_id=CARD_ID) not in acts


# --- The early-harvest value case (the ruled point of the span) --------------

def test_early_fire_at_start_of_feeding_pays_the_feeding():
    """Ruling 75 item 7's 'so the player can take the plow early': with 3 food
    against a 4-food feeding bill, firing the fused trigger at
    start_of_feeding nets +1 food — the feeding is then paid begging-free."""
    state = _cards_harvest_state(wood=1, food=3)
    state, _ = _walk_until(state, _top_is_p0_start_of_feeding)
    assert _top_is_p0_start_of_feeding(state)

    state = step(state, FireTrigger(card_id=CARD_ID))
    state = _commit_the_plow(state)
    assert state.players[0].resources.food == 4    # 3 + 2 - 1
    assert state.players[0].resources.wood == 0

    state, _ = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert state.players[0].begging_markers == 0
    assert state.players[0].resources.food == 0    # the 4 paid the 2-adult bill


def test_without_the_fire_the_same_state_begs():
    """The contrast leg: the identical state walked neutrally (no Joinery use
    at all) cannot cover the 4-food bill with 3 food and takes a begging
    marker."""
    state = _cards_harvest_state(wood=1, food=3)
    state, _ = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert state.players[0].begging_markers == 1
