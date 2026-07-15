"""Tests for Stable Sergeant (occupation, B167; Bubulcus Expansion; players 4+).

Card text: "When you play this card, you can pay 2 food to get 1 sheep, 1 wild
boar, and 1 cattle, but only if you can accommodate all three animals on your
farm."

A play-variant occupation (the Automatic Water Trough shape for three animals):
the 2-food "buy" variant is offered only when the permissive keep-frontier can
house all three; a displacing buy resolves through a min_keep-filtered
PendingAccommodate that can never discard the three purchased animals.
"""
import agricola.cards.stable_sergeant  # noqa: F401  (registers the card)

from agricola.actions import CommitAccommodate, CommitPlayOccupation
from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_grid, with_pending_stack

CARD_ID = "stable_sergeant"
_GAINED = Animals(sheep=1, boar=1, cattle=1)

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

# Three empty cells to fill with unfenced stables (default rooms are (1,0),(2,0)).
_STABLE_CELLS = ((0, 2), (0, 3), (0, 4))


def _state(*, food=2, animals=Animals(), stables=0):
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    if stables:
        overrides = {rc: Cell(cell_type=CellType.STABLE)
                     for rc in _STABLE_CELLS[:stables]}
        cs = with_grid(cs, cp, overrides)
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({CARD_ID}),
                     occupations=frozenset(), resources=Resources(food=food),
                     animals=animals)
    opp = fast_replace(cs.players[1 - cp], hand_occupations=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayOccupation(
        player_idx=cp, initiated_by_id="space:lessons", cost=Resources()),))
    return cs, cp


def _variants(cs):
    return sorted(a.variant for a in legal_actions(cs)
                  if isinstance(a, CommitPlayOccupation) and a.card_id == CARD_ID)


def _commit(cs, variant):
    return next(a for a in legal_actions(cs)
               if isinstance(a, CommitPlayOccupation)
               and a.card_id == CARD_ID and a.variant == variant)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_OCCUPATION_VARIANTS


# ---------------------------------------------------------------------------
# The accommodation gate on the "buy" variant
# ---------------------------------------------------------------------------

def test_buy_offered_with_room_and_food():
    # 3 stables can house 1 sheep + 1 boar + 1 cattle; 2 food affords it.
    cs, _cp = _state(food=2, stables=3)
    assert _variants(cs) == ["buy", "decline"]


def test_buy_blocked_when_cannot_accommodate_all_three():
    # Fresh farm has only the house-pet slot (1 animal) -> can't hold 3 types.
    cs, _cp = _state(food=2, stables=0)
    assert _variants(cs) == ["decline"]


def test_buy_blocked_without_two_food():
    # Room to house them, but only 1 food -> the surcharge is unaffordable.
    cs, _cp = _state(food=1, stables=3)
    assert _variants(cs) == ["decline"]


# ---------------------------------------------------------------------------
# Resolving the buy
# ---------------------------------------------------------------------------

def test_buy_grants_three_animals_and_debits_food():
    cs, cp = _state(food=2, stables=3)
    out = step(cs, _commit(cs, "buy"))
    p = out.players[cp]
    assert p.animals == _GAINED                  # 1 of each
    assert p.resources.food == 0                 # 2-food surcharge paid
    assert CARD_ID in p.occupations
    assert not any(isinstance(f, PendingAccommodate) for f in out.pending_stack)


def test_decline_grants_nothing():
    cs, cp = _state(food=2, stables=3)
    out = step(cs, _commit(cs, "decline"))
    p = out.players[cp]
    assert p.animals == Animals()
    assert p.resources.food == 2                 # no surcharge
    assert CARD_ID in p.occupations


# ---------------------------------------------------------------------------
# A displacing buy surfaces the min_keep-filtered accommodation
# ---------------------------------------------------------------------------

def test_displacing_buy_keeps_all_three_purchased():
    # 3 stables + house pet = 4 slots, all held by sheep. Buying overflows, so
    # the barrier must displace sheep — but never one of the three purchased.
    cs, cp = _state(food=2, stables=3, animals=Animals(sheep=4))
    assert _variants(cs) == ["buy", "decline"]      # still accommodatable
    out = step(cs, _commit(cs, "buy"))
    top = out.pending_stack[-1]
    assert isinstance(top, PendingAccommodate)
    assert top.min_keep == _GAINED
    options = [a for a in legal_actions(out) if isinstance(a, CommitAccommodate)]
    assert options
    assert all(a.sheep >= 1 and a.boar >= 1 and a.cattle >= 1 for a in options)
    resolved = step(out, options[0])
    p = resolved.players[cp]
    assert p.animals.boar >= 1 and p.animals.cattle >= 1   # the purchase survived
    assert not any(isinstance(f, PendingAccommodate) for f in resolved.pending_stack)
