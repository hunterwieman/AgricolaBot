"""Tests for Mineral Feeder (minor improvement, C67; Corbarius Expansion).

Card text (verbatim): "At the start of each round that does not end with a
harvest, if you have at least 1 sheep in a pasture, you get 1 grain."
Cost 1 Reed; 1 VP; no prerequisite.

User ruling 29 (2026-07-06): "a sheep in a pasture" = some legal arrangement
houses >= 1 sheep (not all) in a pasture — tested by the user's per-pasture
max-fill construction — and the player may COOK animals to make such an
arrangement possible (the Shepherd's Whistle analog). The case-B frontier is
over (animals, grain): declining keeps everything at 0 grain; each option is
a Pareto keep-set at 1 grain.
"""
import dataclasses

import agricola.cards.mineral_feeder  # noqa: F401  (register the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.mineral_feeder import CARD_ID, _options, _pastured_sheep_possible
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.legality import legal_actions
from agricola.pending import PendingPreparation
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import setup


def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {cid})


def _animals(state, idx, **kw):
    return _edit_player(state, idx, animals=Animals(**kw))


def _set_pasture_1x1(state, player_idx, row=0, col=0):
    from agricola.pasture import compute_pastures_from_arrays
    from agricola.state import Farmyard

    p = state.players[player_idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    h[row][col] = True
    h[row + 1][col] = True
    v[row][col] = True
    v[row][col + 1] = True
    return _edit_player(state, player_idx, farmyard=Farmyard(
        grid=p.farmyard.grid,
        horizontal_fences=tuple(tuple(r) for r in h),
        vertical_fences=tuple(tuple(r) for r in v),
        pastures=compute_pastures_from_arrays(
            p.farmyard.grid, tuple(tuple(r) for r in h),
            tuple(tuple(r) for r in v))))


def _enter_round(state, *, from_round: int):
    """Run the real preparation walk into round from_round+1 (Recluse idiom)."""
    state = fast_replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


# ---------------------------------------------------------------------------
# Registration + the satisfiability test
# ---------------------------------------------------------------------------

def test_registration():
    import json
    from agricola.cards.specs import MINORS

    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(reed=1))
    assert spec.vps == 1
    row = next(r for r in json.load(
        open("agricola/cards/data/revised_minor_improvements.json"))
        if r["name"] == "Mineral Feeder")
    assert (row["deck"], row["number"], row["cost"], row["vps"]) == ("C", 67, "1 Reed", 1)


def test_pastured_sheep_possible():
    base = setup(seed=0)
    pastured = _set_pasture_1x1(base, 0)
    # No sheep -> no; sheep but no pasture -> no; sheep + pasture -> yes.
    assert not _pastured_sheep_possible(base.players[0], Animals(sheep=0))
    assert not _pastured_sheep_possible(base.players[0], Animals(sheep=1))
    assert _pastured_sheep_possible(pastured.players[0], Animals(sheep=1))
    # The forced-out case: 1 sheep + 2 boar, one 2-space pasture + the pet —
    # the boars must take the pasture, so no arrangement pastures the sheep.
    assert not _pastured_sheep_possible(pastured.players[0],
                                        Animals(sheep=1, boar=2))
    # 1 sheep + 1 boar: sheep in the pasture, boar in the house.
    assert _pastured_sheep_possible(pastured.players[0],
                                    Animals(sheep=1, boar=1))


def test_dollys_mother_strip_composes():
    """3 sheep + 1 boar, one 2-space pasture + the pet: the leftover sheep and
    the boar fight over the one house slot — unsatisfiable alone, satisfiable
    with Dolly's Mother's sheep slot taking the leftover."""
    import agricola.cards.dollys_mother  # noqa: F401
    from agricola.cards.dollys_mother import CARD_ID as DOLLY

    state = _set_pasture_1x1(setup(seed=0), 0)
    a = Animals(sheep=3, boar=1)
    assert not _pastured_sheep_possible(state.players[0], a)
    owned = _own(state, 0, DOLLY)
    assert _pastured_sheep_possible(owned.players[0], a)


# ---------------------------------------------------------------------------
# Case A: automatic grain
# ---------------------------------------------------------------------------

def test_auto_grain_on_non_harvest_round():
    state = _own(_set_pasture_1x1(setup(seed=0), 0), 0)
    state = _animals(state, 0, sheep=1)
    g0 = state.players[0].resources.grain
    state = _enter_round(state, from_round=1)          # into round 2 (no harvest)
    assert state.players[0].resources.grain == g0 + 1


def test_no_grain_entering_a_harvest_round():
    """Round 4 ends with a harvest — the printed gate withholds the grain."""
    state = _own(_set_pasture_1x1(setup(seed=0), 0), 0)
    state = _animals(state, 0, sheep=1)
    g0 = state.players[0].resources.grain
    state = _enter_round(state, from_round=3)          # into round 4
    assert state.players[0].resources.grain == g0


def test_no_grain_without_a_pastured_sheep():
    # Sheep exists but only the house can hold it (no pasture).
    state = _own(setup(seed=0), 0)
    state = _animals(state, 0, sheep=1)
    g0 = state.players[0].resources.grain
    state = _enter_round(state, from_round=1)
    assert state.players[0].resources.grain == g0


def test_unowned_never_fires():
    state = _set_pasture_1x1(setup(seed=0), 0)
    state = _animals(state, 0, sheep=1)
    g0 = state.players[0].resources.grain
    state = _enter_round(state, from_round=1)
    assert state.players[0].resources.grain == g0


# ---------------------------------------------------------------------------
# Case B: cook to qualify
# ---------------------------------------------------------------------------

def _case_b_state():
    """1 sheep + 2 boar, one 2-space pasture + the pet: unsatisfiable as held
    (the boars must take the pasture); cooking one boar frees it."""
    state = _own(_set_pasture_1x1(setup(seed=0), 0), 0)
    return _animals(state, 0, sheep=1, boar=2)


def test_case_b_option_shape():
    state = _case_b_state()
    opts = _options(state, 0)
    # The single Pareto keep-set: 1 sheep + 1 boar (cook one boar).
    assert [(k.sheep, k.boar, k.cattle) for k, _f in opts] == [(1, 1, 0)]
    # No cooking improvement -> the released boar cooks for 0; the option is
    # still offered (the (animals, grain) frontier: it never ties Proceed).
    assert opts[0][1] == 0


def test_case_b_fire_and_decline():
    state = _case_b_state()
    g0 = state.players[0].resources.grain
    state = _enter_round(state, from_round=1)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPreparation)
    acts = legal_actions(state)
    fires = [a for a in acts if isinstance(a, FireTrigger) and a.card_id == CARD_ID]
    assert [a.variant for a in fires] == ["s1b1c0"]
    assert Proceed() in acts
    assert state.players[0].resources.grain == g0      # no auto (unsatisfiable)

    from agricola.engine import step
    fired = step(state, fires[0])
    p = fired.players[0]
    assert p.animals == Animals(sheep=1, boar=1)
    assert p.resources.grain == g0 + 1
    # Once per round: no re-offer on the same frame.
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(fired))

    # Decline path: Proceed keeps everything, no grain.
    declined = step(state, Proceed())
    assert declined.players[0].animals == Animals(sheep=1, boar=2)
    assert declined.players[0].resources.grain == g0


def test_case_b_not_offered_when_auto_fired():
    """The tiers are mutually exclusive: a satisfiable holding gets the auto
    and never the trigger."""
    state = _own(_set_pasture_1x1(setup(seed=0), 0), 0)
    state = _animals(state, 0, sheep=1, boar=1)        # satisfiable as held
    state = _enter_round(state, from_round=1)
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state))
