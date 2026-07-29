"""Full Peasant × Thresher (ruling 87, 2026-07-29): the jump's destination check
consults the space-enable registry on the POST-FEE state, so a Fencing → Grain
Utilization jump whose destination is usable only via Thresher's buy is priced
at fee + buy — 2 food offered, 1 food refused — and the arrival flow runs the
mandatory buy exactly like a placement would."""
from __future__ import annotations

from agricola.actions import ChooseSubAction, CommitSow, FireTrigger
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from tests.factories import with_resources
from tests.test_card_full_peasant import (
    _base,
    _offers,
    _use_fencing_to_after_window,
)


def _with_thresher_no_seed(state, *, food):
    p = state.players[0]
    p = fast_replace(p, occupations=p.occupations | {"thresher"})
    state = fast_replace(state, players=(p, state.players[1]))
    # with_resources REPLACES the bundle — keep the wood the fencing use needs.
    return with_resources(state, 0, food=food, grain=0, veg=0, wood=15)


def test_jump_into_gu_via_thresher_needs_fee_plus_buy():
    # 2 food: fee paid, the buy still payable on the post-fee state → offered.
    s = _use_fencing_to_after_window(_with_thresher_no_seed(_base(), food=2))
    assert _offers(s), "jump not offered though fee + buy are both payable"
    # 1 food: post-fee 0 food and nothing cookable — the buy is dead → refused.
    s1 = _use_fencing_to_after_window(_with_thresher_no_seed(_base(), food=1))
    assert not _offers(s1), "jump offered though the buy dies with the fee"
    # Without Thresher, 2 food doesn't help a seedless destination at all.
    s2 = _use_fencing_to_after_window(
        with_resources(_base(), 0, food=2, grain=0, veg=0, wood=15))
    assert not _offers(s2)


def test_jump_into_gu_via_thresher_end_to_end():
    s = _use_fencing_to_after_window(_with_thresher_no_seed(_base(), food=2))
    s = step(s, _offers(s)[0])                   # fee 2→1; relocate and use GU
    acts = legal_actions(s)
    assert acts == [FireTrigger(card_id="thresher")], acts   # mandatory buy
    s = step(s, acts[0])                         # 1→0 food, +1 grain
    s = step(s, ChooseSubAction(name="sow"))
    sows = [a for a in legal_actions(s) if isinstance(a, CommitSow)
            and a.grain == 1 and a.veg == 0]
    assert sows, "the bought grain is not sowable on arrival"
    s = step(s, sows[0])
    p = s.players[0]
    assert p.resources.food == 0 and p.resources.grain == 0
