"""Wood Field (D75) — per-card pins over the card-field seam.

The generic card-field machinery is covered by tests/test_card_fields_seam.py
(synthetic registrations); these tests pin Wood Field's OWN facts: the
registered spec rows (cost / prereq / VP; 2 stacks, wood-only per the
errata, wood-as-grain = 3 per sow), sowing BOTH stacks in one commit under a
1-field sow cap (ruling 48's cap accounting — the printed Chief Forester
clarification's 2-at-once), the take harvesting each non-empty stack (ruling
47), scoring (the 2-stack card counts as exactly 1 field; planted wood
scores no crop points), and the crops_only exclusion (ruling 48 — a
crops-explicit grant may not plant here at all).
"""
import agricola.cards.wood_field  # noqa: F401 — registers at import

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

CARD = "wood_field"


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
    assert spec.min_occupations == 1 and spec.max_occupations is None
    assert spec.prereq is None
    assert spec.vps == 1
    assert not spec.passing_left

    cf = CARD_FIELDS[CARD]
    assert cf.stacks == 2
    assert cf.sow_amounts == (("wood", 3),)   # wood-as-grain: 3 per sow


# ---------------------------------------------------------------------------
# Sow — both stacks in one commit (ruling 48's cap accounting)
# ---------------------------------------------------------------------------

def test_sow_both_stacks_in_one_commit_under_one_field_cap():
    state = _own(setup(7), 0, [CARD])
    state = with_resources(state, 0, wood=2)
    # A capped generic sow (max_fields=1): the whole card is ONE field-unit,
    # so filling BOTH stacks in the one commit is legal (ruling 48,
    # 2026-07-12 — the Chief Forester clarification's "2 wood at once").
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test", max_fields=1)])
    double = CommitSow(grain=0, veg=0,
                       card_sows=((CARD, "wood"), (CARD, "wood")))
    single = CommitSow(grain=0, veg=0, card_sows=((CARD, "wood"),))
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert double in sows and single in sows
    nxt = step(state, double)
    p = nxt.players[0]
    assert card_field_stacks(p, CARD) == ((0, 0, 3, 0), (0, 0, 3, 0))
    assert p.resources.wood == 0   # 2 supply wood spent, 1 per stack sown


def test_crops_only_sow_offers_wood_field_nothing():
    # Ruling 48 (2026-07-12): a crops-explicit grant ("sow crops") may not
    # plant here at all.
    state = _own(setup(7), 0, [CARD])
    state = with_resources(state, 0, wood=5)
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
    state = _set_stacks(state, 0, CARD, [(0, 0, 3, 0), (0, 0, 1, 0)])
    w0 = state.players[0].resources.wood
    nxt, occasion = field_take(state, 0)
    entries = [e for e in occasion.entries if e.source == f"card:{CARD}"]
    assert len(entries) == 2   # one entry per non-empty stack
    assert all(e.crop == "wood" and e.amount == 1 for e in entries)
    assert sorted(e.emptied for e in entries) == [False, True]
    assert nxt.players[0].resources.wood - w0 == 2
    assert card_field_stacks(nxt.players[0], CARD) == (
        (0, 0, 2, 0), (0, 0, 0, 0))


# ---------------------------------------------------------------------------
# Scoring (rulings 45 + 47: counts once; wood is not a crop)
# ---------------------------------------------------------------------------

def test_scoring_counts_card_once_and_wood_scores_no_crop_points():
    state = with_fields(setup(7), 0, [(2, 0)])   # 1 board field
    _, base_bd = score(state, 0)
    owned = _own(state, 0, [CARD])
    owned = _set_stacks(owned, 0, CARD, [(0, 0, 3, 0), (0, 0, 3, 0)])
    _, bd = score(owned, 0)
    # 1 field -> 2 fields: the 2-stack card is "considered 1 field".
    assert base_bd.field_tiles == -1 and bd.field_tiles == 1
    # Planted wood contributes no grain/vegetable points.
    assert bd.grain == base_bd.grain == -1
    assert bd.vegetables == base_bd.vegetables == -1
