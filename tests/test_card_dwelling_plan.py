"""Tests for Dwelling Plan (minor improvement, D2) — the optional on-play renovate grant.

Card text: "You can immediately take a 'Renovation' action." (cost 1 food)

Dwelling Plan is a TRAVELING (passing) minor whose optional renovate is granted via the
generic `PendingGrantedSubAction(subaction="renovate")` choose-or-decline wrapper, pushed
from `on_play`. Because the card is passing it leaves the tableau before the after-phase,
so an ownership-gated `after_play_minor` trigger cannot host the grant — the wrapper (a
pushed frame, not ownership-gated) can. The wrapper offers `ChooseSubAction("renovate")`
when a renovate is legal + payable (its enumerator gates on `_can_renovate`, so the no-Stop
`PendingRenovate` never dead-ends) alongside `Stop` (= decline).

The tests push `PendingPlayMinor` directly (the established factory pattern) with
`dwelling_plan` in hand, then exercise play → (card passes) → fire / decline the renovate.
"""
import agricola.cards.dwelling_plan  # noqa: F401

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
    minors=("dwelling_plan",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, res=None):
    """A 2-player card-mode state with `dwelling_plan` in the active player's hand and
    the given resources; opponent hand cleared so only our card is in play."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    changes = {"hand_minors": frozenset({"dwelling_plan"})}
    if res is not None:
        changes["resources"] = res
    p = fast_replace(cs.players[cp], **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


def _play_dwelling_plan(res):
    """Drive: own + afford `dwelling_plan` (1 food), play it through a PendingPlayMinor
    host, returning the state at the granted-renovate wrapper + active player index."""
    cs, cp = _card_state(res=res)
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "dwelling_plan"))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration — a passing minor, granted via on_play (not a trigger)
# ---------------------------------------------------------------------------

def test_dwelling_plan_registered():
    assert "dwelling_plan" in MINORS
    spec = MINORS["dwelling_plan"]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.passing_left is True                 # D2 is a traveling minor
    assert spec.vps == 0
    # No longer a trigger card — the grant is pushed from on_play.
    for entries in TRIGGERS.values():
        assert "dwelling_plan" not in {e.card_id for e in entries}


# ---------------------------------------------------------------------------
# Play pushes the wrapper; the card passes; renovate + decline both offered
# ---------------------------------------------------------------------------

def test_play_pushes_wrapper_and_passes_the_card():
    # 1 food to play + clay/reed to renovate the default 2-room wood house (2 clay + 1 reed).
    cs, cp = _play_dwelling_plan(Resources(food=1, clay=2, reed=1))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.subactions == ("renovate",) and top.initiated_by_id == "card:dwelling_plan"
    # Traveling: passed to the opponent's hand, not kept in the tableau.
    assert "dwelling_plan" not in cs.players[cp].minor_improvements
    assert "dwelling_plan" in cs.players[1 - cp].hand_minors
    la = legal_actions(cs)
    assert _RENOVATE in la          # the optional renovate grant
    assert Stop() in la             # decline path


# ---------------------------------------------------------------------------
# Choose → renovate upgrades the house and charges the renovate cost
# ---------------------------------------------------------------------------

def test_choose_renovate_upgrades_house():
    cs, cp = _play_dwelling_plan(Resources(food=1, clay=5, reed=2))
    assert cs.players[cp].house_material is HouseMaterial.WOOD
    clay0 = cs.players[cp].resources.clay
    reed0 = cs.players[cp].resources.reed
    cs = step(cs, _RENOVATE)
    assert isinstance(cs.pending_stack[-1], PendingRenovate)
    cs = step(cs, sole_renovate(cs))   # the unique CommitRenovate (wood->clay)
    cs = step(cs, Stop())              # pop PendingRenovate's after-phase
    assert cs.players[cp].house_material is HouseMaterial.CLAY
    # Default 2-room wood house → 1 clay per room + 1 reed.
    assert cs.players[cp].resources.clay == clay0 - 2
    assert cs.players[cp].resources.reed == reed0 - 1


def test_choose_then_back_at_wrapper_and_once_only():
    # After the renovate completes and PendingRenovate pops, control returns to the wrapper
    # (chosen=True), so the renovate is spent (once) and only Stop remains.
    cs, cp = _play_dwelling_plan(Resources(food=1, clay=5, reed=2))
    cs = step(cs, _RENOVATE)
    cs = step(cs, sole_renovate(cs))
    cs = step(cs, Stop())   # pop PendingRenovate
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction) and top.chosen == frozenset({"renovate"})
    la = legal_actions(cs)
    assert _RENOVATE not in la   # already taken
    assert Stop() in la
    # Stop the wrapper, then the play-minor host — turn ends cleanly.
    cs = step(cs, Stop())   # pop the wrapper
    cs = step(cs, Stop())   # pop PendingPlayMinor
    assert not any(isinstance(f, (PendingGrantedSubAction, PendingPlayMinor))
                   for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Optionality — declining via Stop at the wrapper leaves the house unchanged
# ---------------------------------------------------------------------------

def test_decline_via_stop_leaves_house_unchanged():
    cs, cp = _play_dwelling_plan(Resources(food=1, clay=5, reed=2))
    mat0 = cs.players[cp].house_material
    clay0 = cs.players[cp].resources.clay
    cs = step(cs, Stop())   # decline the renovate (pop the wrapper)
    assert cs.players[cp].house_material is mat0          # not renovated
    assert cs.players[cp].resources.clay == clay0         # no cost charged
    cs = step(cs, Stop())   # pop the play-minor host
    assert not any(isinstance(f, PendingGrantedSubAction) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Eligibility boundary — no renovate offered when it can't be afforded
# ---------------------------------------------------------------------------

def test_no_renovate_grant_when_unaffordable():
    # Enough food to play the card, but no building materials → renovate is not
    # affordable → the wrapper offers only Stop (decline).
    cs, cp = _play_dwelling_plan(Resources(food=1))
    assert isinstance(cs.pending_stack[-1], PendingGrantedSubAction)
    la = legal_actions(cs)
    assert _RENOVATE not in la
    assert Stop() in la
