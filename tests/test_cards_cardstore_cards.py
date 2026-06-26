"""Tests for the five CardStore / leftover cards (Unit 5):

  - Tutor (occupation, Cat 1): snapshots len(occupations) at play, scores
    occupations played strictly after it.
  - Big Country (minor, Cat 2): immediate food + banked bonus points scaled by
    complete rounds left; prereq "all farmyard spaces used".
  - Moldboard Plow (minor, Cat 4): twice-per-game granted plow on Farmland's
    after-hook, uses-left tracked in CardStore.
  - Roof Ballaster (occupation, Cat 2): optional pay-1-food→1-stone-per-room,
    modeled as a play-VARIANT (two CommitPlayOccupations).
  - Shifting Cultivation (minor, Cat 2, traveling): on_play pushes PendingPlow on
    top of the after-flipped PendingPlayMinor host (the nested-pending walk).
"""
from agricola.actions import (
    ChooseSubAction,
    CommitPlayMinor,
    CommitPlayOccupation,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType, HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import CardStore, get_space, with_space
from tests.factories import with_grid, with_house, with_resources

_POOL = CardPool(
    occupations=("tutor", "roof_ballaster") + tuple(f"o{i}" for i in range(20)),
    minors=("big_country", "moldboard_plow", "shifting_cultivation")
    + tuple(f"m{i}" for i in range(20)),
)


def _own_occ(state, idx, *card_ids):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(card_ids))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_card_state(state, idx, store):
    p = fast_replace(state.players[idx], card_state=store)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5) if g[r][c].cell_type == CellType.FIELD)


def _hand_occ(seed, occupations, hand, **player_changes):
    """A card-mode round-1 state with the current player's hand/tableau set."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    changes = {"hand_occupations": hand, "occupations": frozenset(occupations)}
    changes.update(player_changes)
    p = fast_replace(cs.players[cp], **changes)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _play_minor_via_improvement(state, cp, card_id):
    state = _reveal_improvement_space(state)
    p = fast_replace(state.players[cp], hand_minors=state.players[cp].hand_minors | {card_id})
    state = fast_replace(state, players=tuple(
        p if i == cp else state.players[i] for i in range(2)))
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))
    state = step(state, ChooseSubAction(name="play_minor"))
    return step(state, CommitPlayMinor(card_id=card_id))


# ---------------------------------------------------------------------------
# Tutor
# ---------------------------------------------------------------------------

def test_tutor_snapshots_occupation_count_on_play():
    # Already own 1 occupation; play Tutor as the 2nd. Snapshot includes Tutor (=2).
    cs, cp = _hand_occ(5, occupations=["o3"], hand=frozenset({"tutor"}))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="tutor"))
    assert cs.players[cp].card_state.get("tutor") == 2     # o3 + tutor


def test_tutor_scores_occupations_played_after():
    s = setup(0)
    # Tutor played when 2 occupations were in the tableau (incl. itself); now 5 total.
    s = _own_occ(s, 0, "tutor", "a", "b", "c")            # 4 occs in set
    s = fast_replace(s, players=tuple(
        fast_replace(s.players[0], occupations=s.players[0].occupations | {"d"})
        if i == 0 else s.players[i] for i in range(2)))   # 5 occs total
    s = _set_card_state(s, 0, CardStore().set("tutor", 2))
    _t, bd = score(s, 0)
    # 5 total - 1 (tutor) - 2 (snapshot) = 2 occupations after.
    assert bd.card_points == 2


def test_tutor_scores_zero_when_played_last():
    s = setup(0)
    s = _own_occ(s, 0, "tutor", "x", "y")                 # 3 occs total
    s = _set_card_state(s, 0, CardStore().set("tutor", 3)) # played as the 3rd → none after
    _t, bd = score(s, 0)
    assert bd.card_points == 0


# ---------------------------------------------------------------------------
# Big Country
# ---------------------------------------------------------------------------

def _fill_farmyard(state, idx):
    """Make every cell non-empty (FIELD where currently EMPTY) for the prereq."""
    g = state.players[idx].farmyard.grid
    overrides = {}
    from agricola.state import Cell
    for r in range(3):
        for c in range(5):
            if g[r][c].cell_type == CellType.EMPTY:
                overrides[(r, c)] = Cell(cell_type=CellType.FIELD)
    return with_grid(state, idx, overrides)


def test_big_country_prereq_all_spaces_used():
    s = setup(0)
    assert not prereq_met(MINORS["big_country"], s, 0)    # default has empty cells
    s_full = _fill_farmyard(s, 0)
    assert prereq_met(MINORS["big_country"], s_full, 0)


def test_big_country_immediate_food_and_banked_points():
    cs, env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    assert cs.round_number == 1                            # 13 complete rounds left
    cs = _fill_farmyard(cs, cp)
    food0 = cs.players[cp].resources.food
    cs = _play_minor_via_improvement(cs, cp, "big_country")
    n = 14 - 1                                             # complete rounds left
    assert cs.players[cp].resources.food == food0 + 2 * n  # immediate food
    assert cs.players[cp].card_state.get("big_country") == n
    # The banked points are scored at end-game.
    _t, bd = score(cs, cp)
    assert bd.card_points == n


def test_big_country_scoring_reads_bank():
    s = setup(0)
    s = _own_minor(s, 0, "big_country")
    s = _set_card_state(s, 0, CardStore().set("big_country", 4))
    _t, bd = score(s, 0)
    assert bd.card_points == 4


# ---------------------------------------------------------------------------
# Moldboard Plow — twice-per-game granted plow on Farmland
# ---------------------------------------------------------------------------

def _use_farmland_and_plow_once(state, cp):
    """Place a worker on Farmland, do the base plow, then fire Moldboard's grant
    in the after-phase and commit its plow. Returns the state after the host pops."""
    state = step(state, PlaceWorker(space="farmland"))
    # Base sub-action: plow (singleton choose), then commit the one base plow.
    state = step(state, ChooseSubAction(name="plow"))
    base_plows = [a for a in legal_actions(state)]
    state = step(state, base_plows[0])                    # CommitPlow (base)
    state = step(state, Stop())                           # pop base PendingPlow's after
    # Now at the Farmland host's after-phase: Moldboard grant available.
    from agricola.actions import FireTrigger
    la = legal_actions(state)
    assert FireTrigger(card_id="moldboard_plow") in la
    state = step(state, FireTrigger(card_id="moldboard_plow"))
    assert isinstance(state.pending_stack[-1], PendingPlow)
    granted = legal_actions(state)
    state = step(state, granted[0])                       # commit the granted plow
    state = step(state, Stop())                           # pop granted PendingPlow's after
    state = step(state, Stop())                           # pop the Farmland host
    return state


def test_moldboard_plow_grants_twice_then_stops():
    s = _own_minor(_card_state(), 0, "moldboard_plow")
    assert s.players[0].card_state.get("moldboard_plow") is None  # defaults to 2
    fields0 = _num_fields(s, 0)

    # First Farmland use: base plow + granted plow → +2 fields, uses-left → 1.
    s = _use_farmland_and_plow_once(s, 0)
    assert _num_fields(s, 0) == fields0 + 2
    assert s.players[0].card_state.get("moldboard_plow") == 1

    # Reset for a fresh turn (clear workers on Farmland, advance back to this player).
    s = _fresh_turn_same_player(s, 0)
    # Second Farmland use: another grant, uses-left → 0.
    s = _use_farmland_and_plow_once(s, 0)
    assert s.players[0].card_state.get("moldboard_plow") == 0

    # Third Farmland use: grant exhausted → no Moldboard FireTrigger offered.
    s = _fresh_turn_same_player(s, 0)
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, ChooseSubAction(name="plow"))
    s = step(s, legal_actions(s)[0])                      # base plow
    s = step(s, Stop())                                   # pop base plow's after
    from agricola.actions import FireTrigger
    assert FireTrigger(card_id="moldboard_plow") not in legal_actions(s)


def _card_state():
    s, _env = setup_env(5, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _fresh_turn_same_player(state, idx):
    """Reset Farmland's worker + this player's per-turn latch + current_player so a
    new Farmland placement is legal again (test-only state surgery)."""
    sp = fast_replace(get_space(state.board, "farmland"), workers=(0, 0))
    state = fast_replace(state, board=with_space(state.board, "farmland", sp))
    p = fast_replace(state.players[idx], used_this_turn=frozenset(),
                     people_home=max(1, state.players[idx].people_home))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return fast_replace(state, current_player=idx)


def test_moldboard_plow_grant_can_be_declined():
    s = _own_minor(_card_state(), 0, "moldboard_plow")
    fields0 = _num_fields(s, 0)
    s = step(s, PlaceWorker(space="farmland"))
    s = step(s, ChooseSubAction(name="plow"))
    s = step(s, legal_actions(s)[0])                      # base plow
    s = step(s, Stop())                                   # pop base plow's after
    s = step(s, Stop())                                   # decline the grant, pop host
    assert not s.pending_stack
    assert _num_fields(s, 0) == fields0 + 1               # only the base plow
    assert s.players[0].card_state.get("moldboard_plow") is None  # untouched (still 2)


# ---------------------------------------------------------------------------
# Roof Ballaster — optional pay-1-food → 1-stone-per-room play variant
# ---------------------------------------------------------------------------

def test_roof_ballaster_surfaces_two_variants_when_food_available():
    cs, cp = _hand_occ(5, occupations=[], hand=frozenset({"roof_ballaster"}),
                       resources=Resources(food=1))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="roof_ballaster", variant="pay") in la
    assert CommitPlayOccupation(card_id="roof_ballaster", variant="decline") in la


def test_roof_ballaster_only_decline_when_no_food():
    cs, cp = _hand_occ(5, occupations=[], hand=frozenset({"roof_ballaster"}),
                       resources=Resources(food=0))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="roof_ballaster", variant="pay") not in la
    assert CommitPlayOccupation(card_id="roof_ballaster", variant="decline") in la


def test_roof_ballaster_pay_variant_grants_stone_per_room():
    cs, cp = _hand_occ(5, occupations=[], hand=frozenset({"roof_ballaster"}),
                       resources=Resources(food=3))
    rooms = sum(1 for r in range(3) for c in range(5)
                if cs.players[cp].farmyard.grid[r][c].cell_type == CellType.ROOM)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="roof_ballaster", variant="pay"))
    assert cs.players[cp].resources.stone == rooms        # 1 stone per room (2)
    assert cs.players[cp].resources.food == 3 - 1         # paid 1 food
    assert "roof_ballaster" in cs.players[cp].occupations


def test_roof_ballaster_decline_variant_pays_nothing():
    cs, cp = _hand_occ(5, occupations=[], hand=frozenset({"roof_ballaster"}),
                       resources=Resources(food=3))
    before = cs.players[cp].resources
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="roof_ballaster", variant="decline"))
    assert cs.players[cp].resources == before             # no exchange
    assert "roof_ballaster" in cs.players[cp].occupations


# ---------------------------------------------------------------------------
# Shifting Cultivation — on_play pushes PendingPlow (the nested-pending walk)
# ---------------------------------------------------------------------------

def test_shifting_cultivation_nested_plow_walk():
    cs, env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    cs = _reveal_improvement_space(cs)
    cs = with_resources(cs, cp, food=5)                   # afford the 2-food cost
    fields0 = _num_fields(cs, cp)

    p = fast_replace(cs.players[cp], hand_minors=frozenset({"shifting_cultivation"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, CommitPlayMinor(card_id="shifting_cultivation"))

    # The play frame flipped to "after" and on_play pushed PendingPlow ON TOP of it:
    # the top is the plow, with the (after-phase) PendingPlayMinor host underneath.
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    assert isinstance(cs.pending_stack[-2], PendingPlayMinor)
    assert cs.pending_stack[-2].phase == "after"

    # Commit the granted plow; +1 field. Cost (2 food) was paid; the card was passed.
    plows = legal_actions(cs)
    cs = step(cs, plows[0])
    assert _num_fields(cs, cp) == fields0 + 1
    assert cs.players[cp].resources.food == 5 - 2
    assert "shifting_cultivation" in cs.players[1 - cp].hand_minors
    assert "shifting_cultivation" not in cs.players[cp].minor_improvements

    # Unwind: plow's after-phase Stop, then the play host, then the
    # PendingMajorMinorImprovement composite, then the major_improvement space host
    # — control returns cleanly through every frame the play opened.
    cs = step(cs, Stop())                                 # pop PendingPlow's after
    assert isinstance(cs.pending_stack[-1], PendingPlayMinor)
    cs = step(cs, Stop())                                 # pop the play host
    cs = step(cs, Stop())                                 # pop PendingMajorMinorImprovement
    cs = step(cs, Stop())                                 # pop the major_improvement space host
    assert not cs.pending_stack
