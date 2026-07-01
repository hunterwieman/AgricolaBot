"""Tests for Dwelling Plan (minor improvement, D2) — the optional on-play renovate grant.

Card text: "You can immediately take a 'Renovation' action." (cost 1 food)

Dwelling Plan is a Category-4 granted-sub-action card whose grant — a single Renovate
primitive — is OPTIONAL ("You can ... take"). It is modeled as an OPTIONAL
`after_play_minor` trigger: after this minor is played, the play-minor host pivots to
its after-phase, which surfaces `FireTrigger("dwelling_plan")` (= renovate) alongside
`Stop` (= decline). Eligibility gates on `_can_renovate` so the renovate is never
offered when it would dead-end on the no-Stop `PendingRenovate` frame, and the host's
`triggers_resolved` fires it at most once.

The tests push `PendingPlayMinor` directly (the established factory pattern for driving
the play-minor machinery) with `dwelling_plan` in hand, then exercise the play → fire /
decline flow.
"""
import agricola.cards.dwelling_plan  # noqa: F401

from agricola.actions import FireTrigger, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, TRIGGERS
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor, PendingRenovate
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor, sole_renovate

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
    host, returning the after-phase state + active player index."""
    cs, cp = _card_state(res=res)
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "dwelling_plan"))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_dwelling_plan_registered():
    assert "dwelling_plan" in MINORS
    spec = MINORS["dwelling_plan"]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.passing_left is False
    assert spec.vps == 0
    # Optional after_play_minor trigger, not an automatic effect.
    apm = {e.card_id for e in TRIGGERS.get("after_play_minor", [])}
    assert "dwelling_plan" in apm
    assert CARDS["dwelling_plan"].mandatory is False


# ---------------------------------------------------------------------------
# The card is owned + offered at the after-phase, alongside the decline (Stop)
# ---------------------------------------------------------------------------

def test_after_play_offers_renovate_and_decline():
    # 1 food to play + clay/reed to renovate the default 2-room wood house (2 clay + 1 reed).
    cs, cp = _play_dwelling_plan(Resources(food=1, clay=2, reed=1))
    # Played: in tableau, host in after-phase.
    assert "dwelling_plan" in cs.players[cp].minor_improvements
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayMinor) and top.phase == "after"
    la = legal_actions(cs)
    assert FireTrigger(card_id="dwelling_plan") in la   # the optional renovate grant
    assert Stop() in la                                 # decline path


# ---------------------------------------------------------------------------
# Fire → renovate upgrades the house and charges the renovate cost
# ---------------------------------------------------------------------------

def test_fire_renovate_upgrades_house():
    cs, cp = _play_dwelling_plan(Resources(food=1, clay=5, reed=2))
    assert cs.players[cp].house_material is HouseMaterial.WOOD
    clay0 = cs.players[cp].resources.clay
    reed0 = cs.players[cp].resources.reed
    cs = step(cs, FireTrigger(card_id="dwelling_plan"))
    assert isinstance(cs.pending_stack[-1], PendingRenovate)
    cs = step(cs, sole_renovate(cs))   # the unique CommitRenovate (wood->clay)
    cs = step(cs, Stop())              # pop PendingRenovate's after-phase
    assert cs.players[cp].house_material is HouseMaterial.CLAY
    # Default 2-room wood house → 1 clay per room + 1 reed.
    assert cs.players[cp].resources.clay == clay0 - 2
    assert cs.players[cp].resources.reed == reed0 - 1


def test_fire_then_back_at_host_and_once_only():
    # After the renovate completes and PendingRenovate pops, control returns to the
    # play-minor host's after-phase; the grant is spent (once-per-play) so only Stop remains.
    cs, cp = _play_dwelling_plan(Resources(food=1, clay=5, reed=2))
    cs = step(cs, FireTrigger(card_id="dwelling_plan"))
    cs = step(cs, sole_renovate(cs))
    cs = step(cs, Stop())   # pop PendingRenovate
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayMinor) and top.phase == "after"
    la = legal_actions(cs)
    assert FireTrigger(card_id="dwelling_plan") not in la   # already fired
    assert Stop() in la


# ---------------------------------------------------------------------------
# Optionality — declining via Stop leaves the house unchanged
# ---------------------------------------------------------------------------

def test_decline_via_stop_leaves_house_unchanged():
    cs, cp = _play_dwelling_plan(Resources(food=1, clay=5, reed=2))
    mat0 = cs.players[cp].house_material
    clay0 = cs.players[cp].resources.clay
    cs = step(cs, Stop())   # decline the renovate, pop the host
    assert cs.players[cp].house_material is mat0          # not renovated
    assert cs.players[cp].resources.clay == clay0         # no cost charged
    assert not any(isinstance(f, PendingPlayMinor) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Eligibility boundary — no renovate offered when it can't be afforded
# ---------------------------------------------------------------------------

def test_no_renovate_grant_when_unaffordable():
    # Enough food to play the card, but no building materials → renovate is not
    # affordable → the grant is not offered, only Stop (decline) remains.
    cs, cp = _play_dwelling_plan(Resources(food=1))
    assert "dwelling_plan" in cs.players[cp].minor_improvements
    la = legal_actions(cs)
    assert FireTrigger(card_id="dwelling_plan") not in la
    assert Stop() in la
