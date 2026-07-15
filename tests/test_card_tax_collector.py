import agricola.cards.tax_collector  # noqa: F401

"""Tests for Tax Collector (occupation, deck E #126).

"Once you live in a stone house, at the start of each round, you get your
choice of 2 wood, 2 clay, 1 reed, or 1 stone."

Mandatory-with-choice trigger on the preparation ladder's `start_of_round`
window (the Childless pattern), gated on the standing stone-house condition
(the Scholar / Plow Driver formula). Exercised by driving the REAL preparation
ladder (`_complete_preparation`, the legacy round-boundary drive the
category-7 tests use) and the synthetic start_of_round window host.
"""
from agricola.actions import CommitCardChoice, FireTrigger, Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARD_CHOICE_RESOLVERS, TRIGGERS
from agricola.constants import HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice, PendingHarvestWindow, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

CARD_ID = "tax_collector"

_OPTIONS = ("2 wood", "2 clay", "1 reed", "1 stone")


# ---------------------------------------------------------------------------
# Helpers (the category-7 test idiom)
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_house(state, idx, material):
    p = state.players[idx]
    p = fast_replace(p, house_material=material)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _host(state, idx):
    """A WORK state with a start_of_round window choice host for `idx` on top —
    the synthetic-frame idiom (constructed outside the ladder walk)."""
    return push(fast_replace(state, phase=Phase.WORK),
                PendingHarvestWindow(window_id="start_of_round", player_idx=idx))


def _goods(p):
    r = p.resources
    return (r.wood, r.clay, r.reed, r.stone)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_tax_collector_registered():
    assert CARD_ID in OCCUPATIONS
    # Mandatory-tagged trigger on the start_of_round window (subset checks).
    so = {e.card_id: e.mandatory for e in TRIGGERS.get("start_of_round", [])}
    assert so[CARD_ID] is True
    assert CARD_ID in CARD_CHOICE_RESOLVERS


def test_tax_collector_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


# ---------------------------------------------------------------------------
# No effect outside a stone house
# ---------------------------------------------------------------------------

def test_no_effect_in_wooden_house():
    s = _own_occ(setup(0), 0, CARD_ID)   # default house is WOOD
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    before = _goods(s.players[0])
    after = _complete_preparation(s)
    # Ineligible → no host frame pushed, no choice, no goods; straight to WORK.
    assert after.pending_stack == ()
    assert after.phase is Phase.WORK
    assert _goods(after.players[0]) == before


def test_no_effect_in_clay_house():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    before = _goods(s.players[0])
    after = _complete_preparation(s)
    assert after.pending_stack == ()
    assert _goods(after.players[0]) == before


def test_not_offered_at_host_in_wooden_house():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# Stone house — the mandatory choice through the real preparation ladder
# ---------------------------------------------------------------------------

def test_stone_house_forces_choice_at_round_start():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_house(s, 0, HouseMaterial.STONE)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    opp_before = _goods(s.players[1])
    s = _complete_preparation(s)
    # The ladder paused at the start_of_round window host for player 0.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round" and top.player_idx == 0
    # MANDATORY: Proceed is withheld while the trigger is unfired — the fire
    # is the only legal action (pinned exactly).
    assert legal_actions(s) == [FireTrigger(card_id=CARD_ID)]
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingCardChoice) and top.options == _OPTIONS
    # The pick is forced: one CommitCardChoice per option, no decline.
    assert legal_actions(s) == [CommitCardChoice(index=i) for i in range(4)]
    wood0 = s.players[0].resources.wood
    s = step(s, CommitCardChoice(index=0))   # 2 wood
    assert s.players[0].resources.wood == wood0 + 2
    # Gate reopens; Proceed resumes the ladder to WORK.
    assert Proceed() in legal_actions(s)
    s = step(s, Proceed())
    assert s.pending_stack == ()
    assert s.phase is Phase.WORK
    # Opponent unaffected throughout.
    assert _goods(s.players[1]) == opp_before


def test_fires_every_round_while_in_stone():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_house(s, 0, HouseMaterial.STONE)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    # First round boundary.
    s = _complete_preparation(s)
    assert legal_actions(s) == [FireTrigger(card_id=CARD_ID)]
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitCardChoice(index=3))   # 1 stone
    s = step(s, Proceed())
    assert s.phase is Phase.WORK
    stone1 = s.players[0].resources.stone
    # Second round boundary: the standing condition still holds → fires again.
    s = fast_replace(s, phase=Phase.PREPARATION)
    s = _complete_preparation(s)
    assert legal_actions(s) == [FireTrigger(card_id=CARD_ID)]
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitCardChoice(index=3))   # 1 stone again
    assert s.players[0].resources.stone == stone1 + 1


# ---------------------------------------------------------------------------
# Each option grants exactly its printed goods
# ---------------------------------------------------------------------------

def test_each_option_grants_exactly_printed_goods():
    expected = {
        0: Resources(wood=2),
        1: Resources(clay=2),
        2: Resources(reed=1),
        3: Resources(stone=1),
    }
    for i, gain in expected.items():
        s = _own_occ(setup(0), 0, CARD_ID)
        s = _set_house(s, 0, HouseMaterial.STONE)
        s = _host(s, 0)
        before = s.players[0].resources
        s = step(s, FireTrigger(card_id=CARD_ID))
        s = step(s, CommitCardChoice(index=i))
        assert s.players[0].resources == before + gain
        # The choice frame popped back to the host; the gate is open.
        top = s.pending_stack[-1]
        assert isinstance(top, PendingHarvestWindow)
        assert Proceed() in legal_actions(s)


# ---------------------------------------------------------------------------
# Hand-only inert
# ---------------------------------------------------------------------------

def test_hand_only_is_inert():
    s = setup(0)
    p = fast_replace(s.players[0],
                     hand_occupations=s.players[0].hand_occupations | {CARD_ID},
                     house_material=HouseMaterial.STONE)
    s = fast_replace(s, players=(p, s.players[1]))
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    before = _goods(s.players[0])
    after = _complete_preparation(s)
    assert after.pending_stack == ()
    assert _goods(after.players[0]) == before
    # And at a synthetic host: not surfaced, Proceed alone.
    s2 = _host(fast_replace(after, phase=Phase.WORK), 0)
    assert legal_actions(s2) == [Proceed()]
