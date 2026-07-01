"""Tests for Roof Ladder (minor improvement, D81): "Each time you renovate, you pay 1
fewer reed and, at the end of the action, you get 1 stone." Cost 1 wood; no prereq; 0 VP.

Two clauses, both keyed on renovation:
- a `renovate` cost reduction of −1 reed (floored at 0 — a no-op on a reed-free cost);
- an unconditional `after_renovate` automatic effect granting +1 stone (mandatory,
  choiceless, fires once per renovate at the after-phase flip).

Covered: registration (minor spec + the renovate reduction + the after_renovate auto, and
NOT a declinable trigger), the chokepoint reduction effect (−1 reed; the floor-at-0 no-op
on a stone-renovate cost; scoping to the owner; build_room / build_major untouched), the
end-to-end +1 stone grant through House Redevelopment (wood→clay AND clay→stone), the
combined reduction-then-grant on a clay-house renovate, and the eligibility / per-player
scoping boundaries (unowned → no stone; opponent untouched).
"""
from __future__ import annotations

import agricola.cards.roof_ladder  # noqa: F401  (registers spec + reduction + auto)

from agricola.actions import ChooseSubAction, PlaceWorker, Proceed, Stop
from agricola.cards.cost_mods import REDUCTIONS
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import HouseMaterial
from agricola.cost import CostCtx
from agricola.legality import effective_payments
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

CARD_ID = "roof_ladder"
_GENEROUS = Resources(wood=20, clay=20, reed=20, stone=20)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _state_owning(*card_ids, resources: Resources = _GENEROUS):
    """A card-mode state with player 0 owning `card_ids` (as minors) and `resources`."""
    cs = _card_state()
    cs = with_resources(cs, 0, **{f: getattr(resources, f) for f in
                                  ("wood", "clay", "reed", "stone", "food", "grain", "veg")
                                  if getattr(resources, f)})
    for cid in card_ids:
        cs = _own(cs, 0, cid)
    return cs


def _as_set(frontier) -> set:
    return set(frontier)


def _renovate_setup(material, *, idx=0, **resources):
    """A card-mode state with house_redevelopment revealed and the given house."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    return cs


def _do_renovate(state):
    """Drive the real House Redevelopment renovate flow to a turn-complete state.
    The Proceed flips the host to its after-phase, firing after_renovate."""
    return run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,        # applies the renovate
        Stop(),               # pop PendingRenovate after-phase
        Proceed(),            # flip the host to after-phase → fires after_renovate
        Stop(),               # pop the host → turn complete
    ])


# --------------------------------------------------------------------------- #
# Registration                                                                 #
# --------------------------------------------------------------------------- #

def test_registered_as_minor_with_cost_and_no_vps():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))   # 1 wood
    assert spec.vps == 0
    assert spec.passing_left is False                       # kept, not traveling
    assert spec.prereq is None


def test_reduction_registered_on_renovate_only():
    assert any(cid == CARD_ID for cid, _ in REDUCTIONS.get("renovate", ()))
    # NOT on build_room / build_major / play_minor — only renovation is named.
    for kind in ("build_room", "build_major", "play_minor"):
        assert not any(cid == CARD_ID for cid, _ in REDUCTIONS.get(kind, ()))


def test_after_renovate_auto_registered_and_not_declinable():
    after = {e.card_id for e in AUTO_EFFECTS.get("after_renovate", [])}
    assert CARD_ID in after
    # Mandatory auto (no FireTrigger), so it is NOT in the declinable TRIGGERS list.
    declinable = {t.card_id for lst in TRIGGERS.values() for t in lst}
    assert CARD_ID not in declinable


# --------------------------------------------------------------------------- #
# Chokepoint effect — the −1 reed reduction                                    #
# --------------------------------------------------------------------------- #

def test_renovate_drops_one_reed():
    # 2-room wood house renovate = 2 clay + 2 reed -> drops 1 reed, leaving 2 clay + 1 reed.
    state = _state_owning(CARD_ID)
    ctx = CostCtx("renovate", Resources(clay=2, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=2, reed=1)}


def test_renovate_drops_only_one_reed_not_all():
    # A cost printing 2 reed loses exactly ONE (not the whole component — that's the
    # Straw-Thatched-Roof shape; here it is a fixed −1).
    state = _state_owning(CARD_ID)
    ctx = CostCtx("renovate", Resources(clay=3, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=3, reed=1)}


def test_renovate_reed_free_cost_is_no_op():
    # A clay->stone renovate cost prints no reed; the signed −1 floors to 0 (no-op).
    state = _state_owning(CARD_ID)
    ctx = CostCtx("renovate", Resources(stone=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(stone=2)}


def test_non_owner_pays_full_reed():
    # Without the card (Family game), the printed reed stays — byte-identical base.
    state = _state_owning()  # no cards
    ctx = CostCtx("renovate", Resources(clay=2, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=2, reed=2)}


def test_build_room_and_major_untouched():
    # The card registers ONLY on renovate; rooms / majors keep their full reed.
    state = _state_owning(CARD_ID)
    for kind in ("build_room", "build_major"):
        ctx = CostCtx(kind, Resources(clay=5, reed=2))
        assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=5, reed=2)}


# --------------------------------------------------------------------------- #
# after_renovate: +1 stone (real flow)                                         #
# --------------------------------------------------------------------------- #

def test_wood_to_clay_renovate_grants_one_stone():
    # Wood->clay renovate of the 2-room house prints 2 clay + 1 reed; the -1 discount
    # drops the reed, and at the end of the action the owner gets +1 stone.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own(cs, 0, CARD_ID)
    stone0 = cs.players[0].resources.stone
    cs = _do_renovate(cs)
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert cs.players[0].resources.stone == stone0 + 1


def test_reduction_actually_saves_a_reed_in_real_flow():
    # A wood->clay renovate of the default 2-room house prints 2 clay + 1 reed (renovate
    # charges 1 reed TOTAL, not per room — legality.py _renovate_base). The -1 reed
    # discount drops that lone reed to 0, so a player holding ZERO reed can renovate
    # paying only 2 clay, and afterward gets +1 stone.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=0)   # NO reed held
    cs = _own(cs, 0, CARD_ID)
    cs = _do_renovate(cs)
    assert cs.players[0].house_material == HouseMaterial.CLAY
    # Spent 2 clay, 0 reed (the discount made reed unnecessary); +1 stone gained.
    assert cs.players[0].resources.clay == 0
    assert cs.players[0].resources.reed == 0
    assert cs.players[0].resources.stone == 1


def test_clay_to_stone_renovate_also_grants_stone():
    # "Each time you renovate" covers clay->stone too — the +1 stone is unconditional.
    # Clay->stone costs 1 stone + 1 reed per room (2 rooms by default) -> 2 stone + 2 reed.
    cs = _renovate_setup(HouseMaterial.CLAY, stone=2, reed=2)
    cs = _own(cs, 0, CARD_ID)
    cs = _do_renovate(cs)
    assert cs.players[0].house_material == HouseMaterial.STONE
    # Spent 2 stone + 1 reed (reed discount), then +1 stone -> net stone = 2 - 2 + 1 = 1.
    assert cs.players[0].resources.stone == 1


# --------------------------------------------------------------------------- #
# Eligibility / scoping boundaries                                             #
# --------------------------------------------------------------------------- #

def test_unowned_grants_no_stone():
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=2)  # card not owned
    stone0 = cs.players[0].resources.stone
    cs = _do_renovate(cs)
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert cs.players[0].resources.stone == stone0           # no grant


def test_grant_is_per_player():
    # P0 owns the card and renovates; P1 owns it too but does not renovate, so P1's
    # stone is untouched (the auto is own-action, fired for the acting player only).
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=2)
    cs = _own(cs, 0, CARD_ID)
    cs = _own(cs, 1, CARD_ID)
    stone1 = cs.players[1].resources.stone
    cs = _do_renovate(cs)
    assert cs.players[1].resources.stone == stone1           # opponent untouched
