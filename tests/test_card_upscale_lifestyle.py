import agricola.cards.upscale_lifestyle  # noqa: F401

"""Tests for Upscale Lifestyle (minor improvement, B1; Bubulcus) — the +5 clay and
optional on-play renovation.

Card text: "You immediately get 5 clay and a "Renovation" action. If you take the
action, you must pay the renovation cost." (cost 3 Wood, traveling/passing)

A PASSING minor whose on_play adds 5 clay then pushes the generic
`PendingGrantedSubAction(subaction="renovate")` choose-or-decline wrapper (the
Dwelling Plan pattern). The renovate is at NORMAL cost — the wrapper gates the offer
on `_can_renovate`, so it appears only when payable.
"""
from agricola.actions import ChooseSubAction, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingGrantedSubAction, PendingPlayMinor, PendingRenovate
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor, sole_renovate

_RENOVATE = ChooseSubAction(name="renovate")

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("upscale_lifestyle",) + tuple(f"m{i}" for i in range(20)),
)


def _play(res):
    """Own + afford upscale_lifestyle, play it through a PendingPlayMinor host;
    return the state at the granted-renovate wrapper + the active player index."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"upscale_lifestyle"}),
                     resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, "upscale_lifestyle"))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "upscale_lifestyle" in MINORS
    spec = MINORS["upscale_lifestyle"]
    assert spec.cost == Cost(resources=Resources(wood=3))
    assert spec.passing_left is True
    assert spec.vps == 0
    # Grant is pushed from on_play, not a trigger.
    for entries in TRIGGERS.values():
        assert "upscale_lifestyle" not in {e.card_id for e in entries}


# ---------------------------------------------------------------------------
# On play: +5 clay, wrapper pushed, card passes
# ---------------------------------------------------------------------------

def test_play_gives_5_clay_pushes_wrapper_and_passes():
    # 3 wood to play; reed to renovate; start with 0 clay to see the +5 cleanly.
    cs, cp = _play(Resources(wood=3, reed=2))
    assert cs.players[cp].resources.clay == 5          # immediately get 5 clay
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.subactions == ("renovate",)
    assert top.initiated_by_id == "card:upscale_lifestyle"
    # Traveling: passed to the opponent, not kept.
    assert "upscale_lifestyle" not in cs.players[cp].minor_improvements
    assert "upscale_lifestyle" in cs.players[1 - cp].hand_minors
    la = legal_actions(cs)
    assert _RENOVATE in la
    assert Stop() in la


# ---------------------------------------------------------------------------
# Choose -> renovate upgrades the house and charges the NORMAL cost
# ---------------------------------------------------------------------------

def test_choose_renovate_upgrades_house_at_normal_cost():
    cs, cp = _play(Resources(wood=3, reed=2))
    assert cs.players[cp].house_material is HouseMaterial.WOOD
    clay0 = cs.players[cp].resources.clay              # 5 (from the card)
    reed0 = cs.players[cp].resources.reed              # 2
    cs = step(cs, _RENOVATE)
    assert isinstance(cs.pending_stack[-1], PendingRenovate)
    cs = step(cs, sole_renovate(cs))                   # wood -> clay
    cs = step(cs, Stop())                              # pop PendingRenovate after-phase
    assert cs.players[cp].house_material is HouseMaterial.CLAY
    # Default 2-room wood house -> 1 clay per room + 1 reed (paid, NOT free).
    assert cs.players[cp].resources.clay == clay0 - 2
    assert cs.players[cp].resources.reed == reed0 - 1


# ---------------------------------------------------------------------------
# Decline -> house unchanged, the 5 clay is kept
# ---------------------------------------------------------------------------

def test_decline_via_stop_keeps_clay_unrenovated():
    cs, cp = _play(Resources(wood=3, reed=2))
    cs = step(cs, Stop())                              # decline the renovate
    assert cs.players[cp].house_material is HouseMaterial.WOOD
    assert cs.players[cp].resources.clay == 5          # the +5 clay stays
    cs = step(cs, Stop())                              # pop the play-minor host
    assert not any(isinstance(f, PendingGrantedSubAction) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Eligibility boundary — unaffordable normal renovate is not offered
# ---------------------------------------------------------------------------

def test_no_renovate_when_reed_missing():
    # +5 clay covers the clay, but a wood->clay renovate also needs 1 reed; with
    # none, the NORMAL cost is unaffordable, so only Stop (decline) is offered.
    cs, cp = _play(Resources(wood=3))                  # no reed
    assert isinstance(cs.pending_stack[-1], PendingGrantedSubAction)
    la = legal_actions(cs)
    assert _RENOVATE not in la
    assert Stop() in la
