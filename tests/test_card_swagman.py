import agricola.cards.swagman  # noqa: F401  (registers the card)

"""Swagman (occupation, A129, [3+]): "Immediately after each time you use the
'Farm Expansion' or 'Grain Seeds' action space, you can use the respective
other space with the same person (even if it is occupied)."
Clarification: "The person ends on the second action space used."
Errata: "The 'jump' to a second action space may only be done once per turn."

Rulings under test (user, 2026-07-26 — ruling 81): the jump is an optional
trigger in the SOURCE's after_action_space window; firing moves the acting
worker's marker source -> destination and runs the destination's FULL action
(frames stack above the source host, resolve, and the walk returns to the
source's after-window); no placement number is minted (ruling 79); the vacated
source re-opens. The errata's once-per-turn budget is the used_this_turn latch
— which is also what stops the destination's own after-window from offering
the jump straight back. Players 3+: never dealt at 2p, injected here (the
Lodger precedent).
"""

from agricola import helpers
from agricola.actions import (
    ChooseSubAction,
    CommitBuildStable,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.swagman import CARD_ID
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingFarmExpansion
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import get_space
from tests.factories import with_current_player, with_resources

_FE, _GS = "farm_expansion", "grain_seeds"


def _own(state, idx):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _state(*, wood=0, p1_wood=0, current_player=0):
    """A CARDS-mode state, P0 owning Swagman and holding exactly `wood` wood
    (nothing else); `current_player` to move (and starting player, so round
    boundaries hand the move back deterministically)."""
    state = fast_replace(setup(seed=0), mode=GameMode.CARDS, starting_player=0)
    state = with_current_player(state, current_player)
    state = with_resources(state, 0, wood=wood)
    if p1_wood:
        state = with_resources(state, 1, wood=p1_wood)
    return _own(state, 0)


def _jump_offers(opts):
    return [a for a in opts
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _build_one_stable(state):
    """At a just-entered farm-expansion host: build one 2-wood stable and exit
    the multi-shot (choose -> commit -> Proceed -> Stop), leaving the
    PendingFarmExpansion host in its before-phase with stable_chosen."""
    state = step(state, ChooseSubAction(name="build_stables"))
    commit = next(a for a in legal_actions(state)
                  if isinstance(a, CommitBuildStable))
    state = step(state, commit)
    state = step(state, Proceed())          # multi-shot work-complete flip
    state = step(state, Stop())             # pop the stable host
    return state


def _farm_expansion_after_window(state):
    """P0 places on Farm Expansion, builds one 2-wood stable, and Proceeds to
    the host's after-window (where the jump trigger lives)."""
    state = step(state, PlaceWorker(space=_FE))
    state = _build_one_stable(state)
    return step(state, Proceed())           # flip the FE host to "after"


def _grain_seeds_after_window(state):
    """P0 places on Grain Seeds (hosted — Swagman hooks it) and Proceeds
    through the atomic take to the host's after-window."""
    state = step(state, PlaceWorker(space=_GS))
    assert [type(a).__name__ for a in legal_actions(state)] == ["Proceed"]
    return step(state, Proceed())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
    assert CARD_ID in OCCUPATIONS
    # optional (never mandatory) trigger, AFTER window only
    assert any(e.card_id == CARD_ID and not e.mandatory
               for e in TRIGGERS.get("after_action_space", []))
    assert not any(e.card_id == CARD_ID
                   for e in TRIGGERS.get("before_action_space", []))
    # grain_seeds (atomic) is hooked own-use so the owner's use is hosted;
    # farm_expansion needs no hook (non-atomic, always hosted).
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(_GS, set())


# ---------------------------------------------------------------------------
# The full jump, Farm Expansion -> Grain Seeds
# ---------------------------------------------------------------------------

def test_jump_farm_expansion_to_grain_seeds():
    s = _state(wood=2)
    s = _farm_expansion_after_window(s)
    # The source's after-window offers the jump (plus Stop).
    offers = _jump_offers(legal_actions(s))
    assert offers == [FireTrigger(card_id=CARD_ID)]
    grain_before = s.players[0].resources.grain

    s = step(s, FireTrigger(card_id=CARD_ID))
    # The SAME person moved: source vacated, destination gained the marker.
    assert get_space(s.board, _FE).workers == (0, 0)
    assert get_space(s.board, _GS).workers == (1, 0)
    assert s.players[0].people_home == 1            # no second person placed
    assert CARD_ID in s.players[0].used_this_turn   # errata latch stamped
    # The destination's FULL action runs: its host frame is stacked above the
    # source's after-window host.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].space_id == _GS
    assert isinstance(s.pending_stack[-2], PendingFarmExpansion)
    assert [type(a).__name__ for a in legal_actions(s)] == ["Proceed"]

    s = step(s, Proceed())                          # the grain-seeds take
    assert s.players[0].resources.grain == grain_before + 1
    # Destination after-window: the latch keeps the jump from re-offering
    # (otherwise Grain Seeds' own after-window would offer the jump BACK).
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]

    s = step(s, Stop())                             # pop the destination host
    # Back at the SOURCE's after-window for its remaining triggers.
    assert isinstance(s.pending_stack[-1], PendingFarmExpansion)
    assert s.pending_stack[-1].phase == "after"
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]

    s = step(s, Stop())                             # end the turn
    assert not s.pending_stack
    assert s.current_player == 1


# ---------------------------------------------------------------------------
# The reverse direction, Grain Seeds -> Farm Expansion
# ---------------------------------------------------------------------------

def test_jump_grain_seeds_to_farm_expansion():
    s = _state(wood=2)                              # a 2-wood stable is buildable
    s = _grain_seeds_after_window(s)
    assert s.players[0].resources.grain == 1        # the take already happened
    assert _jump_offers(legal_actions(s)) == [FireTrigger(card_id=CARD_ID)]

    s = step(s, FireTrigger(card_id=CARD_ID))
    # Marker moved; the destination's full non-atomic action opened.
    assert get_space(s.board, _GS).workers == (0, 0)
    assert get_space(s.board, _FE).workers == (1, 0)
    assert isinstance(s.pending_stack[-1], PendingFarmExpansion)
    assert isinstance(s.pending_stack[-2], PendingActionSpace)
    s = _build_one_stable(s)
    assert helpers.stables_built(s.players[0].farmyard) == 1
    assert s.players[0].resources.wood == 0

    s = step(s, Proceed())                          # FE host -> after-window
    # The latch: Farm Expansion's own after-window does NOT re-offer the jump.
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())                             # pop the destination host
    # Back at the source (Grain Seeds) after-window; Stop ends the turn.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].space_id == _GS
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())
    assert not s.pending_stack
    assert s.current_player == 1


# ---------------------------------------------------------------------------
# No placement number is minted (ruling 79)
# ---------------------------------------------------------------------------

def test_jump_mints_no_placement_number():
    s = _state(wood=2)
    s = _farm_expansion_after_window(s)
    assert helpers.placements_this_round(s.players[0]) == 1
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert helpers.placements_this_round(s.players[0]) == 1   # unchanged by the move
    s = step(s, Proceed())
    s = step(s, Stop())
    s = step(s, Stop())
    assert helpers.placements_this_round(s.players[0]) == 1   # whole turn = one act
    # The NEXT real placement mints 2 — the jump consumed no number.
    s = step(s, PlaceWorker(space="clay_pit"))                # P1, atomic
    s = step(s, PlaceWorker(space="forest"))                  # P0's second person
    assert helpers.placements_this_round(s.players[0]) == 2


# ---------------------------------------------------------------------------
# Once per TURN (the errata): latched within the turn, fresh next turn
# ---------------------------------------------------------------------------

def test_once_per_turn_fresh_next_turn():
    s = _state(wood=4)                              # two stables' worth
    s = _farm_expansion_after_window(s)             # builds one (wood 4 -> 2)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Proceed())
    # Destination after-window: latched, no re-offer (also pinned in the full
    # forward-flow test).
    assert _jump_offers(legal_actions(s)) == []
    s = step(s, Stop())
    s = step(s, Stop())                             # turn over
    assert CARD_ID not in s.players[0].used_this_turn   # cleared at the boundary

    s = step(s, PlaceWorker(space="clay_pit"))      # P1, atomic
    # P0's NEXT turn: the vacated Farm Expansion is open again and a second
    # stable is affordable — the jump is offered afresh (per turn, not per
    # round). The destination (Grain Seeds) holds P0's own first worker; the
    # jump pierces that too.
    s = _farm_expansion_after_window(s)
    assert _jump_offers(legal_actions(s)) == [FireTrigger(card_id=CARD_ID)]
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert get_space(s.board, _GS).workers == (2, 0)


# ---------------------------------------------------------------------------
# "Even if it is occupied": the jump pierces an opponent-occupied destination
# ---------------------------------------------------------------------------

def test_pierces_occupied_destination():
    s = _state(wood=2, current_player=1)
    s = step(s, PlaceWorker(space=_GS))             # P1 takes Grain Seeds (atomic)
    assert get_space(s.board, _GS).workers == (0, 1)
    assert s.current_player == 0
    s = _farm_expansion_after_window(s)
    # Occupied destination -> still offered (occupancy is NOT an eligibility gate).
    assert _jump_offers(legal_actions(s)) == [FireTrigger(card_id=CARD_ID)]
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert get_space(s.board, _GS).workers == (1, 1)   # markers stack
    s = step(s, Proceed())
    assert s.players[0].resources.grain == 1           # the take still happens


# ---------------------------------------------------------------------------
# Never a dead-end: no buildable room/stable -> no jump to Farm Expansion
# ---------------------------------------------------------------------------

def test_dead_end_destination_not_offered():
    s = _state(wood=0)                              # nothing buildable at FE
    s = _grain_seeds_after_window(s)
    assert _jump_offers(legal_actions(s)) == []
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]


# ---------------------------------------------------------------------------
# Declinable: Stop at the source's after-window without firing
# ---------------------------------------------------------------------------

def test_declinable_via_stop():
    s = _state(wood=2)
    s = _farm_expansion_after_window(s)
    assert _jump_offers(legal_actions(s)) == [FireTrigger(card_id=CARD_ID)]
    s = step(s, Stop())                             # decline
    assert get_space(s.board, _FE).workers == (1, 0)    # the person stayed put
    assert get_space(s.board, _GS).workers == (0, 0)
    assert s.players[0].resources.grain == 0            # no destination take
    assert CARD_ID not in s.players[0].used_this_turn   # a decline is not a use
    assert not s.pending_stack
    assert s.current_player == 1


# ---------------------------------------------------------------------------
# The vacated source re-opens (occupancy is solely worker presence)
# ---------------------------------------------------------------------------

def test_vacated_source_open_for_opponent():
    s = _state(wood=2, p1_wood=2)
    s = _farm_expansion_after_window(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Proceed())
    s = step(s, Stop())
    s = step(s, Stop())                             # P0's turn over
    assert s.current_player == 1
    # P1 may place on the vacated Farm Expansion through real legality.
    assert PlaceWorker(space=_FE) in legal_actions(s)
    s = step(s, PlaceWorker(space=_FE))
    assert get_space(s.board, _FE).workers == (0, 1)


# ---------------------------------------------------------------------------
# A non-owner / an unrelated space gets no offer
# ---------------------------------------------------------------------------

def test_not_offered_to_non_owner():
    from agricola.cards.triggers import should_host_space
    s = fast_replace(setup(seed=0), mode=GameMode.CARDS, starting_player=0)
    s = with_current_player(s, 0)
    s = with_resources(s, 0, wood=2)                # NO Swagman owned
    assert should_host_space(s, _GS, 0) is False    # grain_seeds stays atomic
    s = step(s, PlaceWorker(space=_FE))
    s = _build_one_stable(s)
    s = step(s, Proceed())
    assert _jump_offers(legal_actions(s)) == []


def test_not_offered_on_unrelated_space():
    s = _state()
    s = step(s, PlaceWorker(space="forest"))        # atomic, unhooked by Swagman
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.current_player == 1                    # the turn simply resolved
