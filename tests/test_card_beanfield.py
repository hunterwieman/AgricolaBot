"""Beanfield (B68) — per-card pins over the card-field seam.

The generic card-field machinery is covered by tests/test_card_fields_seam.py
(synthetic registrations); these tests pin Beanfield's OWN facts: the
registered spec rows (cost / prereq / VP; 1 stack, veg-only), the printed
"can only grow vegetables" restriction, sowing through legal_actions + step,
the field-phase take, and scoring (1 field + its planted vegetables —
rulings 45/32).
"""
import agricola.cards.beanfield  # noqa: F401 — registers at import

from agricola.actions import CommitSow
from agricola.cards.card_fields import (
    CARD_FIELDS,
    card_field_stacks,
    stacks_to_store,
)
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingSow
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Cost, Resources
from agricola.scoring import score
from agricola.setup import setup

from tests.factories import with_fields, with_pending_stack, with_resources

CARD = "beanfield"


def _own(state, idx, card_ids):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | set(card_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, cid, stacks):
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration facts
# ---------------------------------------------------------------------------

def test_registration():
    spec = MINORS[CARD]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 2 and spec.max_occupations is None
    assert spec.prereq is None
    assert spec.vps == 1
    assert not spec.passing_left

    cf = CARD_FIELDS[CARD]
    assert cf.stacks == 1
    assert cf.sow_amounts == (("veg", 2),)


# ---------------------------------------------------------------------------
# Sow — through legal_actions + step
# ---------------------------------------------------------------------------

def test_sow_veg_through_legal_actions_and_step():
    state = _own(setup(7), 0, [CARD])
    state = with_resources(state, 0, veg=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    commit = CommitSow(grain=0, veg=0, card_sows=((CARD, "veg"),))
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert sows == [commit]   # the one legal sow: the card's veg stack
    nxt = step(state, commit)
    p = nxt.players[0]
    assert card_field_stacks(p, CARD) == ((0, 2, 0, 0),)   # 1 veg plants 2
    assert p.resources.veg == 0                            # spent from supply


def test_grain_cannot_be_sown_on_beanfield():
    # "can only grow vegetables": grain in supply, no empty board field ->
    # nothing sowable at all (no grain sow onto the card is ever offered).
    state = _own(setup(7), 0, [CARD])
    state = with_resources(state, 0, grain=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert sows == []


# ---------------------------------------------------------------------------
# The take
# ---------------------------------------------------------------------------

def test_field_take_harvests_one_veg():
    state = _own(setup(7), 0, [CARD])
    state = _set_stacks(state, 0, CARD, [(0, 2, 0, 0)])
    v0 = state.players[0].resources.veg
    nxt, occasion = field_take(state, 0)
    entries = [e for e in occasion.entries if e.source == f"card:{CARD}"]
    assert len(entries) == 1
    e = entries[0]
    assert (e.crop, e.amount, e.emptied) == ("veg", 1, False)
    assert nxt.players[0].resources.veg - v0 == 1
    assert card_field_stacks(nxt.players[0], CARD) == ((0, 1, 0, 0),)


# ---------------------------------------------------------------------------
# Scoring (ruling 45, 2026-07-12)
# ---------------------------------------------------------------------------

def test_scoring_counts_one_field_and_its_vegetables():
    state = with_fields(setup(7), 0, [(2, 0)])   # 1 board field
    _, base_bd = score(state, 0)
    owned = _own(state, 0, [CARD])
    owned = _set_stacks(owned, 0, CARD, [(0, 2, 0, 0)])
    _, bd = score(owned, 0)
    # 1 field -> 2 fields: the card counts as exactly 1 field.
    assert base_bd.field_tiles == -1 and bd.field_tiles == 1
    # Its 2 planted vegetables join the crop total.
    assert base_bd.vegetables == -1 and bd.vegetables == 2
