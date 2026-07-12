"""Rock Garden (E80) — per-card pins over the card-field seam.

The generic card-field machinery is covered by tests/test_card_fields_seam.py
(synthetic registrations); these tests pin Rock Garden's OWN facts: the
registered spec rows (no cost / no prereq / no printed VP; 3 stacks,
stone-only, stone-as-vegetables = 2 per sow), sowing through legal_actions +
step (a stone sow spends supply stone; supply-bounded across the commit),
the take harvesting each non-empty stack (ruling 47), scoring (the 3-stack
card counts as exactly 1 field; planted stone scores no crop points), and
the crops_only exclusion (ruling 48).
"""
import agricola.cards.rock_garden  # noqa: F401 — registers at import

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
from agricola.resources import Cost
from agricola.scoring import score
from agricola.setup import setup

from tests.factories import with_fields, with_pending_stack, with_resources

CARD = "rock_garden"


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
    assert spec.cost == Cost()   # no cost
    assert spec.alt_costs == () and spec.cost_fn is None
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert spec.prereq is None   # no prerequisite
    assert spec.vps == 0         # no printed VP
    assert not spec.passing_left

    cf = CARD_FIELDS[CARD]
    assert cf.stacks == 3
    assert cf.sow_amounts == (("stone", 2),)   # stone-as-vegetables: 2 per sow


# ---------------------------------------------------------------------------
# Sow — through legal_actions + step (stone spends supply stone)
# ---------------------------------------------------------------------------

def test_sow_stone_spends_supply_stone():
    state = _own(setup(7), 0, [CARD])
    state = with_resources(state, 0, stone=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    commit = CommitSow(grain=0, veg=0, card_sows=((CARD, "stone"),))
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    # 1 supply stone -> only the single-stack sow (supply-bounded).
    assert sows == [commit]
    nxt = step(state, commit)
    p = nxt.players[0]
    assert card_field_stacks(p, CARD) == (
        (0, 0, 0, 2), (0, 0, 0, 0), (0, 0, 0, 0))   # 1 stone plants 2
    assert p.resources.stone == 0                   # spent from supply


def test_all_three_stacks_sowable_in_one_commit():
    state = _own(setup(7), 0, [CARD])
    state = with_resources(state, 0, stone=3)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    triple = CommitSow(grain=0, veg=0, card_sows=(
        (CARD, "stone"), (CARD, "stone"), (CARD, "stone")))
    assert triple in legal_actions(state)
    nxt = step(state, triple)
    p = nxt.players[0]
    assert card_field_stacks(p, CARD) == (
        (0, 0, 0, 2), (0, 0, 0, 2), (0, 0, 0, 2))
    assert p.resources.stone == 0


def test_crops_only_sow_offers_rock_garden_nothing():
    # Ruling 48 (2026-07-12): a crops-explicit grant ("sow crops") may not
    # plant here at all.
    state = _own(setup(7), 0, [CARD])
    state = with_resources(state, 0, stone=5)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test",
                           crops_only=True)])
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert sows == []


# ---------------------------------------------------------------------------
# The take (ruling 47 — 1 from EACH non-empty stack)
# ---------------------------------------------------------------------------

def test_field_take_harvests_each_nonempty_stack():
    state = _own(setup(7), 0, [CARD])
    state = _set_stacks(state, 0, CARD,
                        [(0, 0, 0, 2), (0, 0, 0, 1), (0, 0, 0, 0)])
    s0 = state.players[0].resources.stone
    nxt, occasion = field_take(state, 0)
    entries = [e for e in occasion.entries if e.source == f"card:{CARD}"]
    assert len(entries) == 2   # one entry per non-empty stack; empty skipped
    assert all(e.crop == "stone" and e.amount == 1 for e in entries)
    assert sorted(e.emptied for e in entries) == [False, True]
    assert nxt.players[0].resources.stone - s0 == 2
    assert card_field_stacks(nxt.players[0], CARD) == (
        (0, 0, 0, 1), (0, 0, 0, 0), (0, 0, 0, 0))


# ---------------------------------------------------------------------------
# Scoring (rulings 45 + 47: counts once; stone is not a crop)
# ---------------------------------------------------------------------------

def test_scoring_counts_card_once_and_stone_scores_no_crop_points():
    state = with_fields(setup(7), 0, [(2, 0)])   # 1 board field
    _, base_bd = score(state, 0)
    owned = _own(state, 0, [CARD])
    owned = _set_stacks(owned, 0, CARD,
                        [(0, 0, 0, 2), (0, 0, 0, 2), (0, 0, 0, 2)])
    _, bd = score(owned, 0)
    # 1 field -> 2 fields: the 3-stack card is "considered 1 field".
    assert base_bd.field_tiles == -1 and bd.field_tiles == 1
    # Planted stone contributes no grain/vegetable points.
    assert bd.grain == base_bd.grain == -1
    assert bd.vegetables == base_bd.vegetables == -1
