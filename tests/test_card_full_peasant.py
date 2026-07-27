import agricola.cards.full_peasant  # noqa: F401  (registers the card)

"""Tests for Full Peasant (occupation, B130; Bubulcus Expansion; players 3+).

Card text: "Each time after you use the "Grain Utilization" or "Fencing" action
space while the other is unoccupied, you can pay 1 food to use the other space
with the same person."
Clarification: "The person ends on the second action space used."
Errata: "ERRATA: The “jump” to a second action space may only be done once per turn."

User ruling 81 (2026-07-26): the jump is an optional trigger in the SOURCE's
after_action_space window; "while the other is unoccupied" is a zero-workers
check at trigger time; the jump mints no placement number (ruling 79).

A 3+-player card: never dealt in the 2-player pool, so tests inject it into the
tableau (the Lodger precedent) and drive REAL 2p Cards-mode flows.
"""
import json
from pathlib import Path

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitFoodPayment,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.cards.triggers import (
    ANY_PLAYER_HOOK_CARDS,
    CARDS,
    OWN_ACTION_HOOK_CARDS,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment, PendingSubActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_fields, with_resources, with_space

CARD_ID = "full_peasant"
GU = "grain_utilization"
FE = "fencing"
_PASTURE = frozenset({(1, 1)})           # 1x1 pasture: 4 new edges -> 4 wood

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_occupations.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Full Peasant")


# ---------------------------------------------------------------------------
# State helpers — drive the REAL flows
# ---------------------------------------------------------------------------

def _base(seed=5, *, food=1, grain=1, wood=15):
    """Cards-mode round-1 WORK state: P0 to move with Full Peasant in the
    tableau (injected — 3+ card, never dealt at 2p), both spaces revealed, and
    both players equipped to use either space (grain + empty fields + wood)."""
    state, _env = setup_env(seed, card_pool=_POOL)
    state = fast_replace(state, current_player=0)
    state = with_space(state, GU, revealed=True)
    state = with_space(state, FE, revealed=True)
    p = state.players[0]
    p = fast_replace(p, occupations=p.occupations | {CARD_ID})
    state = fast_replace(state, players=(p, state.players[1]))
    state = with_resources(state, 0, food=food, grain=grain, wood=wood)
    state = with_resources(state, 1, food=3, grain=2, wood=15)
    for i in (0, 1):
        state = with_fields(state, i, [(0, 0), (0, 1)])
    return state


def _sole_sow(state, grain):
    """The unique legal CommitSow sowing exactly `grain` grain (0 veg)."""
    opts = [a for a in legal_actions(state)
            if isinstance(a, CommitSow) and a.grain == grain and a.veg == 0]
    assert len(opts) == 1, f"expected one CommitSow(grain={grain}), got {opts!r}"
    return opts[0]


def _use_gu_to_after_window(state, *, sow_grain=1):
    """Place the current player on Grain Utilization, sow, Proceed — parked at
    the source host's after-window (where the jump trigger lives)."""
    state = step(state, PlaceWorker(space=GU))
    state = step(state, ChooseSubAction(name="sow"))
    state = step(state, _sole_sow(state, sow_grain))
    state = step(state, Stop())              # pop PendingSow (its after-phase)
    return step(state, Proceed())            # GU host -> after-phase

def _use_fencing_to_after_window(state):
    """Place the current player on Fencing, build the 1x1 pasture, Proceed
    (the multi-shot's work-complete flip — settles the fence bill in CARDS
    mode) and Stop it out — the Delegating host auto-flips to its after-window."""
    state = step(state, PlaceWorker(space=FE))
    state = step(state, ChooseSubAction(name="build_fences"))
    assert CommitBuildPasture(cells=_PASTURE) in legal_actions(state)
    state = step(state, CommitBuildPasture(cells=_PASTURE))
    state = step(state, Proceed())           # flip the build; the bill settles
    return step(state, Stop())               # pop the multi-shot build frame


def _offers(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _commit_food_payment(state, **consumed):
    want = CommitFoodPayment(
        grain=consumed.get("grain", 0), veg=consumed.get("veg", 0),
        sheep=consumed.get("sheep", 0), boar=consumed.get("boar", 0),
        cattle=consumed.get("cattle", 0),
    )
    assert want in legal_actions(state), f"{want!r} not among {legal_actions(state)!r}"
    return step(state, want)


def _full_jump_gu_to_fencing(state):
    """P0's whole jump turn: sow at Grain Utilization, fire in the after-window,
    build the pasture at Fencing, return to the source window, Stop out."""
    state = _use_gu_to_after_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    state = step(state, ChooseSubAction(name="build_fences"))
    state = step(state, CommitBuildPasture(cells=_PASTURE))
    state = step(state, Proceed())           # flip the build; the bill settles
    state = step(state, Stop())              # pop the multi-shot build frame
    state = step(state, Stop())              # pop the Fencing host (after-window)
    state = step(state, Stop())              # pop the source GU host
    assert state.pending_stack == ()
    return state


# ---------------------------------------------------------------------------
# Registration & static facts
# ---------------------------------------------------------------------------

def test_json_row_and_docstring_verbatim():
    assert _ROW["players"] == "3+"
    assert _ROW["deck"] == "B" and _ROW["number"] == 130
    assert _ROW["text"] == (
        'Each time after you use the "Grain Utilization" or "Fencing" action '
        "space while the other is unoccupied, you can pay 1 food to use the "
        "other space with the same person.")
    assert _ROW["clarifications"] == "The person ends on the second action space used."
    assert _ROW["errata"] == (
        "ERRATA: The “jump” to a second action space may only be "
        "done once per turn.")
    import agricola.cards.full_peasant as mod
    doc = " ".join(mod.__doc__.split())
    assert _ROW["text"] in doc
    assert _ROW["clarifications"] in doc
    assert _ROW["errata"] in doc


def test_registered():
    assert CARD_ID in OCCUPATIONS
    s = _base()
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s     # no on-play effect
    entry = CARDS[CARD_ID]
    assert entry.event == "after_action_space"
    assert entry.mandatory is False                    # optional — declinable
    assert CARD_ID in FOOD_PAYMENT_RESUMES             # the Plow Hero payment shape
    # Both sources are non-atomic (always hosted): no action-space hook indexed.
    assert all(CARD_ID not in v for v in OWN_ACTION_HOOK_CARDS.values())
    assert all(CARD_ID not in v for v in ANY_PLAYER_HOOK_CARDS.values())


# ---------------------------------------------------------------------------
# The jump — both directions, real flows
# ---------------------------------------------------------------------------

def test_jump_grain_utilization_to_fencing():
    s = _base()
    s = _use_gu_to_after_window(s)
    # The after-window offers exactly the jump + Stop.
    assert legal_actions(s) == [FireTrigger(card_id=CARD_ID), Stop()]
    s = step(s, FireTrigger(card_id=CARD_ID))
    # The person moved source -> destination; exactly 1 food debited; no
    # placement number minted (ruling 79) and no person returned home.
    assert get_space(s.board, GU).workers == (0, 0)
    assert get_space(s.board, FE).workers[0] == 1
    assert s.players[0].resources.food == 0
    assert s.players[0].placements_this_round == 1
    assert s.players[0].people_home == 1
    # The destination's FULL action runs above the source's window.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace) and top.space_id == FE
    s = step(s, ChooseSubAction(name="build_fences"))
    assert CommitBuildPasture(cells=_PASTURE) in legal_actions(s)
    s = step(s, CommitBuildPasture(cells=_PASTURE))
    s = step(s, Proceed())                    # flip the build; the bill settles
    s = step(s, Stop())                       # pop the multi-shot build frame
    # ERRATA: once per turn — the destination's own after-window must NOT
    # re-offer the jump back (the source is now vacated, so only the latch
    # stops the chain).
    assert _offers(s) == []
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())                       # pop the Fencing host
    # Back at the source's after-window: the trigger is consumed -> Stop only.
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())
    assert s.pending_stack == ()
    assert s.current_player == 1              # the turn passed normally
    p = s.players[0]
    assert p.placements_this_round == 1       # ordinal unchanged by the jump
    assert p.resources.wood == 11             # pasture paid at Fencing's price
    assert len(p.farmyard.pastures) == 1
    assert p.resources.grain == 0             # the sow happened too


def test_jump_fencing_to_grain_utilization():
    s = _base()
    s = _use_fencing_to_after_window(s)
    assert legal_actions(s) == [FireTrigger(card_id=CARD_ID), Stop()]
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert get_space(s.board, FE).workers == (0, 0)
    assert get_space(s.board, GU).workers[0] == 1
    assert s.players[0].resources.food == 0
    # The destination (Grain Utilization) runs in full: sow.
    s = step(s, ChooseSubAction(name="sow"))
    s = step(s, _sole_sow(s, 1))
    s = step(s, Stop())                       # pop PendingSow
    s = step(s, Proceed())                    # GU host -> after-phase
    assert _offers(s) == []                   # once per turn: no jump back
    s = step(s, Stop())                       # pop the GU host
    assert legal_actions(s) == [Stop()]       # source window: consumed
    s = step(s, Stop())
    assert s.pending_stack == ()
    # Clarification: "The person ends on the second action space used."
    assert get_space(s.board, GU).workers[0] == 1
    p = s.players[0]
    assert p.resources.grain == 0 and p.resources.wood == 11
    assert p.placements_this_round == 1


def test_liquidation_raise_resume():
    """0 food on hand but a grain in supply: the fire pushes the raise-only
    PendingFoodPayment; committing the grain conversion resumes into the jump
    (the Plow Hero payment shape)."""
    s = _base(food=0, grain=2)
    s = _use_gu_to_after_window(s)            # sows 1, leaving 1 grain as fuel
    assert _offers(s) != []                   # payable via liquidation
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == CARD_ID
    s = _commit_food_payment(s, grain=1)      # 1 grain -> 1 food, then resume
    # The resume debited the raised food and performed the jump.
    assert s.players[0].resources.food == 0   # raised 1, paid 1
    assert s.players[0].resources.grain == 0  # 1 sown + 1 converted
    assert get_space(s.board, GU).workers == (0, 0)
    assert get_space(s.board, FE).workers[0] == 1
    top = s.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace) and top.space_id == FE
    # Finish the destination + the turn.
    s = step(s, ChooseSubAction(name="build_fences"))
    s = step(s, CommitBuildPasture(cells=_PASTURE))
    s = step(s, Proceed())                    # flip the build; the bill settles
    s = step(s, Stop())                       # pop the multi-shot build frame
    assert _offers(s) == []                   # errata latch spans the resume path
    s = step(s, Stop())
    s = step(s, Stop())
    assert s.pending_stack == ()
    assert len(s.players[0].farmyard.pastures) == 1
    assert s.players[0].resources.wood == 11  # the fence bill was settled


# ---------------------------------------------------------------------------
# Eligibility conjuncts — each failing alone withholds the offer
# ---------------------------------------------------------------------------

def test_not_offered_when_destination_occupied_by_opponent():
    """Ruling 81 item 2: the zero-workers check runs at trigger time. The
    opponent's person on Fencing (a real placement) withholds the offer."""
    s = fast_replace(_base(), current_player=1)
    s = _use_fencing_to_after_window(s)       # P1 places on Fencing first
    assert _offers(s) == []                   # P1 does not own the card
    s = step(s, Stop())                       # pop the Fencing host; P0's turn
    assert s.current_player == 0
    s = _use_gu_to_after_window(s)
    assert get_space(s.board, FE).workers[1] == 1
    assert _offers(s) == []                   # destination occupied
    assert legal_actions(s) == [Stop()]


def test_not_offered_when_destination_occupied_by_own_worker():
    """Zero workers means zero of ANY player — the owner's own earlier person
    on Fencing blocks the jump too (and declining is free: Stop, no debit)."""
    s = _base()
    s = _use_fencing_to_after_window(s)       # P0 turn 1: Fencing
    assert _offers(s) != []                   # offered (GU empty + usable) ...
    s = step(s, Stop())                       # ... and declined: Stop instead
    assert s.pending_stack == ()
    assert s.players[0].resources.food == 1   # no debit on decline
    assert get_space(s.board, FE).workers[0] == 1
    assert s.current_player == 1
    s = step(s, PlaceWorker(space="forest"))  # P1 elsewhere
    assert s.current_player == 0
    s = _use_gu_to_after_window(s)            # P0 turn 2: Grain Utilization
    assert _offers(s) == []                   # own worker occupies the other
    assert legal_actions(s) == [Stop()]


def test_not_offered_without_food_or_liquidation():
    """0 food and nothing liquidatable (the last grain was sown): the 1-food
    cost is unpayable, so the trigger is withheld (never a dead offer)."""
    s = _base(food=0, grain=1)
    s = _use_gu_to_after_window(s)            # sows the only grain
    p = s.players[0]
    assert p.resources.food == 0 and p.resources.grain == 0
    assert p.animals.sheep == p.animals.boar == p.animals.cattle == 0
    assert _offers(s) == []
    assert legal_actions(s) == [Stop()]


def test_not_offered_when_destination_dead_end():
    """The destination's own action must be legal right now. Fencing with no
    wood (no free-fence card): no legal pasture commit -> withheld. Fencing
    with no fence pieces left in supply: likewise withheld."""
    s = _base(food=5, grain=1, wood=0)
    s = _use_gu_to_after_window(s)
    assert _offers(s) == []                   # no affordable fence build
    assert legal_actions(s) == [Stop()]

    s2 = _base(food=5, grain=1, wood=15)
    p = s2.players[0]
    s2 = fast_replace(s2, players=(fast_replace(p, fences_in_supply=0),
                                   s2.players[1]))
    s2 = _use_gu_to_after_window(s2)
    assert _offers(s2) == []                  # no fence piece to place
    assert legal_actions(s2) == [Stop()]


def test_not_offered_when_destination_unrevealed():
    """Both spaces are stage-1 round cards; a not-yet-revealed destination is
    not in play and cannot be used — the jump is withheld."""
    s = with_space(_base(), FE, revealed=False)
    s = _use_gu_to_after_window(s)
    assert get_space(s.board, FE).workers == (0, 0)   # unoccupied, yet...
    assert _offers(s) == []                            # ...not in play
    assert legal_actions(s) == [Stop()]


def test_declinable_at_the_source_window():
    """The jump is an OPTIONAL trigger: Stop at the source's after-window ends
    the turn with no debit and the person still on the source."""
    s = _base()
    s = _use_gu_to_after_window(s)
    assert _offers(s) != []
    s = step(s, Stop())
    assert s.pending_stack == ()
    assert s.current_player == 1
    assert s.players[0].resources.food == 1   # never debited
    assert get_space(s.board, GU).workers[0] == 1
    assert get_space(s.board, FE).workers == (0, 0)


# ---------------------------------------------------------------------------
# Board consequences of the move
# ---------------------------------------------------------------------------

def test_vacated_source_open_to_opponent_and_destination_blocked():
    """After the jump the vacated source is a normal empty space — the opponent
    may place there this round (the Tea Time occupancy ruling) — while the
    destination now holds the jumped person and is blocked."""
    s = _full_jump_gu_to_fencing(_base())
    assert s.current_player == 1
    acts = legal_actions(s)
    assert PlaceWorker(space=GU) in acts
    assert PlaceWorker(space=FE) not in acts
    s = step(s, PlaceWorker(space=GU))
    assert get_space(s.board, GU).workers[1] == 1
    s = step(s, ChooseSubAction(name="sow"))
    s = step(s, _sole_sow(s, 1))
    s = step(s, Stop())
    s = step(s, Proceed())
    s = step(s, Stop())
    assert s.pending_stack == ()
    assert s.players[1].resources.grain == 1  # sowed one of two
