"""Tests for Tree Cutter (D143) — an occupation granting +1 wood each time you use
an accumulation space providing at least 3 goods of the same type EXCEPT wood (food
counts).

Bare "each time you use" + flat +1 wood → an `after_action_space` automatic effect
(Refactor A): the gate reads what was actually TAKEN — a non-wood building `taken`
(clay/reed/stone ≥ 3), Fishing's `taken.food` (≥ 3), or a market's staged animal
`gained` (≥ 3). Forest never qualifies (only wood, `taken` non-wood 0), and a space
holding 3 WOOD does not qualify — the "except wood" clause. Owner-gated.

Because the reward IS wood and the take may also be wood (a space stocked with wood),
the helper drives through the take then subtracts the wood swept from the space,
isolating the reward.
"""
import agricola.cards.tree_cutter  # noqa: F401  (registers the card)

from agricola.actions import CommitAccommodate, PlaceWorker, Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_space

CARD_ID = "tree_cutter"


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def _drive_to_after(state):
    """Drive the hosted lifecycle to the after-window, where the after-auto fires:
    Proceed runs the take for an atomic host; CommitAccommodate flips a market host."""
    if isinstance(state.pending_stack[-1], PendingActionSpace):
        return step(state, Proceed())
    accs = [a for a in legal_actions(state) if isinstance(a, CommitAccommodate)]
    return step(state, accs[0])


def _use(space, owner=0, **space_kwargs):
    s = setup(seed=0)
    s = with_current_player(s, owner)
    s = with_space(s, space, revealed=True, **space_kwargs)
    s = _give(s, owner)
    w0 = s.players[owner].resources.wood
    s = step(s, PlaceWorker(space=space))
    s = _drive_to_after(s)
    # The take (for a building space) may itself add wood; subtract it so the return
    # value is the Tree Cutter reward alone. Fishing/market takes carry no wood.
    took_wood = space_kwargs.get("accumulated", Resources()).wood
    return (s.players[owner].resources.wood - w0) - took_wood


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_three_clay_grants_wood():
    assert _use("clay_pit", accumulated=Resources(clay=3)) == 1


def test_two_clay_no_wood():
    assert _use("clay_pit", accumulated=Resources(clay=2)) == 0


def test_three_wood_excluded():
    """A space holding 3 WOOD does not qualify — the 'except wood' clause."""
    assert _use("clay_pit", accumulated=Resources(wood=3)) == 0


def test_three_food_grants_wood():
    """Fishing food counts as a good (parenthetical clarification)."""
    assert _use("fishing", accumulated_amount=3) == 1


def test_three_animals_grants_wood():
    assert _use("cattle_market", accumulated_amount=3) == 1


def test_two_animals_no_wood():
    assert _use("cattle_market", accumulated_amount=2) == 0
