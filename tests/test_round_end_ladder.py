"""Seam tests for the round-end timing ladder (rulings 49/50, 2026-07-12;
`agricola/cards/round_end.py` + `engine._advance_round_end`), driven through
SYNTHETIC cards (ownership-gated — inert everywhere else).

Pins: the rung ORDER (end_of_work → after_work → start_of_returning_home →
returning_home → the reset → after_returning_home → end_of_round), the
pre/post-reset boundary (returning_home reads the live board; the later rungs
see it cleared), harvest rounds running the ladder before the harvest, the
skip-guard bypass (a Layabout-latched round still fires round-end windows),
and the Family fast path (no frames, no cursor, canonical unchanged).
"""
from agricola.actions import FireTrigger, Proceed
from agricola.canonical import dumps
from agricola.cards.round_end import ROUND_END_STEPS
from agricola.cards.triggers import register, register_auto
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.setup import setup


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _record(state, idx, key, item):
    p = state.players[idx]
    seq = p.card_state.get(key, ())
    return _edit_player(state, idx, card_state=p.card_state.set(key, seq + (item,)))


# Synthetic AUTOS on every ladder window, recording (window, board-occupancy)
# so one card pins both the ORDER and the pre/post-reset boundary.
def _occupied(state, idx):
    return sum(1 for sp in state.board.action_spaces
               for w in sp.workers if w) or sum(sp.workers[idx] for sp in
                                                state.board.action_spaces)


REC = "_test_re_recorder"
for _w in ROUND_END_STEPS:
    if _w != "__reset__":
        register_auto(_w, REC, lambda s, i: True,
                      lambda s, i, _w=_w: _record(
                          s, i, "_test_re_trace",
                          (_w, sum(sp.workers[i]
                                   for sp in s.board.action_spaces))))

# A synthetic optional TRIGGER on returning_home (+1 food), hosting a frame.
TRIG = "_test_re_trigger"
register("returning_home", TRIG, lambda s, i, resolved: True,
         lambda s, i: _edit_player(
             s, i, resources=fast_replace(
                 s.players[i].resources,
                 food=s.players[i].resources.food + 1)))


def _drained_work_state(seed=0, round_number=1):
    """A WORK state with every person placed (people_home=0) and one worker
    recorded on the board for player 0 (so occupancy is visible pre-reset)."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    spaces = list(state.board.action_spaces)
    for j, sp in enumerate(spaces):
        if sp.revealed:
            spaces[j] = fast_replace(sp, workers=(1, 0))
            break
    state = fast_replace(state, board=fast_replace(
        state.board, action_spaces=tuple(spaces)))
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def test_ladder_order_and_reset_boundary():
    state = _own_occ(_drained_work_state(), 0, REC)
    state = _advance_until_decision(state)
    trace = state.players[0].card_state.get("_test_re_trace", ())
    names = [w for w, _occ in trace]
    assert names == ["end_of_work", "after_work", "start_of_returning_home",
                     "returning_home", "after_returning_home", "end_of_round"]
    occ = dict(trace)
    # Pre-reset rungs see player 0's placed worker; post-reset rungs see none.
    assert occ["end_of_work"] == 1
    assert occ["returning_home"] == 1        # the Swimming Class boundary
    assert occ["after_returning_home"] == 0
    assert occ["end_of_round"] == 0
    assert state.phase == Phase.PREPARATION  # round 1: no harvest
    assert state.round_end_cursor is None


def test_trigger_frame_pauses_and_resumes():
    state = _own_occ(_drained_work_state(), 0, TRIG)
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "returning_home" and top.player_idx == 0
    assert state.round_end_cursor is not None
    food = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=TRIG))
    assert state.players[0].resources.food == food + 1
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert state.round_end_cursor is None


def test_harvest_round_runs_ladder_then_harvest():
    state = _own_occ(_drained_work_state(round_number=4), 0, REC)
    state = _advance_until_decision(state)
    trace = state.players[0].card_state.get("_test_re_trace", ())
    assert [w for w, _ in trace][:4] == [
        "end_of_work", "after_work", "start_of_returning_home",
        "returning_home"]
    # The round end completed BEFORE the harvest (the returning-home phase is
    # distinct from and precedes the harvest — ruling 49).
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_layabout_skip_does_not_swallow_round_end():
    import agricola.cards.layabout  # noqa: F401
    state = _drained_work_state(round_number=4)
    state = _own_occ(state, 0, REC)
    state = _own_occ(state, 0, "layabout")
    # Latch layabout's skip for THIS round (the on-play targets round 4).
    p = state.players[0]
    state = _edit_player(state, 0, card_state=p.card_state.set(
        "layabout_skip_round", 4))
    state = _advance_until_decision(state)
    trace = state.players[0].card_state.get("_test_re_trace", ())
    # Every round-end window still fired despite the harvest-total skip.
    assert [w for w, _ in trace] == [
        "end_of_work", "after_work", "start_of_returning_home",
        "returning_home", "after_returning_home", "end_of_round"]


def test_family_fast_path_unchanged():
    state = _drained_work_state()           # no synthetic ownership
    out = _advance_until_decision(state)
    assert out.round_end_cursor is None
    assert not out.pending_stack or out.phase != Phase.RETURN_HOME
    # Canonical omits the cursor at None (the Family JSON is untouched).
    assert '"round_end_cursor"' not in dumps(out)
