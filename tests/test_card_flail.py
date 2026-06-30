"""Tests for Flail (minor improvement, C26; Consul Dirigens; Actions Booster).

Card text: "When you play this card, you immediately get 2 food. Each time you
use the 'Farmland' or 'Cultivation' action space, you can also take a 'Bake
Bread' action."

Two effects:
  - On play: +2 food (one-time; the food_basket idiom).
  - Each time you use Farmland or Cultivation: an OPTIONAL granted Bake Bread on
    the space's before-phase (the oven_firing_boy idiom). Both spaces are
    non-atomic, so no action-space host hook is needed.
"""
import agricola.cards.flail  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBakeBread, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import (
    with_current_player,
    with_majors,
    with_pending_stack,
    with_resources,
    with_space,
)
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("flail",) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# State builders
# ---------------------------------------------------------------------------

def _baker_state(seed=0, *, grain=2, own=True, reveal_cultivation=False):
    """A WORK state where P0 is active and owns Flail + a Fireplace (so
    `_can_bake_bread`) and has `grain` grain. Farmland is a legal placement from
    round 1; `reveal_cultivation` exposes the stage-2 Cultivation space too."""
    s = setup(seed=seed)
    s = with_current_player(s, 0)
    s = with_resources(s, 0, grain=grain)
    s = with_majors(s, owner_by_idx={0: 0})   # Fireplace (idx 0): grain -> 2 food
    if reveal_cultivation:
        s = with_space(s, "cultivation", revealed=True)
    if own:
        p = fast_replace(s.players[0], minor_improvements=s.players[0].minor_improvements | {"flail"})
        s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    return s


def _minor_play_state(seed=5):
    """A 2-player card state with P0 holding Flail in hand + reed/food, and a
    PendingPlayMinor frame on the stack (the play-minor decision point)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        hand_minors=frozenset({"flail"}),
        resources=Resources(wood=2),
    )
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "flail" in MINORS
    spec = MINORS["flail"]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0
    assert spec.passing_left is False
    # The recurring grant lives in the before_action_space trigger bucket.
    assert any(t.card_id == "flail" for t in TRIGGERS.get("before_action_space", []))


# ---------------------------------------------------------------------------
# On-play: +2 food via a real play-minor engine flow
# ---------------------------------------------------------------------------

def test_play_grants_two_food():
    cs, cp = _minor_play_state()
    food0 = cs.players[cp].resources.food
    assert legal_actions(cs) == [sole_play_minor(cs, "flail")]
    cs = step(cs, sole_play_minor(cs, "flail"))

    p = cs.players[cp]
    assert p.resources.food == food0 + 2          # +2 food
    assert p.resources.wood == 1                   # paid 1 of the 2 wood
    assert "flail" in p.minor_improvements         # kept (not passing)
    assert "flail" not in p.hand_minors            # left hand


# ---------------------------------------------------------------------------
# Recurring grant on Farmland (a Delegating non-atomic host, mandatory plow)
# ---------------------------------------------------------------------------

def test_grants_bake_on_farmland():
    s = _baker_state()
    food0 = s.players[0].resources.food
    assert PlaceWorker(space="farmland") in legal_actions(s)

    s = step(s, PlaceWorker(space="farmland"))
    la = legal_actions(s)
    # Before-phase: the optional grant is offered alongside the mandatory plow.
    assert FireTrigger(card_id="flail") in la
    assert ChooseSubAction(name="plow") in la

    s = step(s, FireTrigger(card_id="flail"))
    assert isinstance(s.pending_stack[-1], PendingBakeBread)
    s = step(s, CommitBake(grain=1))               # Fireplace: 1 grain -> 2 food
    assert s.players[0].resources.food == food0 + 2
    assert s.players[0].resources.grain == 1
    assert legal_actions(s) == [Stop()]            # PendingBakeBread after-phase
    s = step(s, Stop())                            # pop the bake frame
    # Back at the host before-phase; grant spent → only the mandatory plow remains.
    assert FireTrigger(card_id="flail") not in legal_actions(s)
    assert ChooseSubAction(name="plow") in legal_actions(s)


# ---------------------------------------------------------------------------
# Recurring grant on Cultivation (a Proceed-host non-atomic space)
# ---------------------------------------------------------------------------

def test_grants_bake_on_cultivation():
    s = _baker_state(reveal_cultivation=True)
    food0 = s.players[0].resources.food
    assert PlaceWorker(space="cultivation") in legal_actions(s)

    s = step(s, PlaceWorker(space="cultivation"))
    assert FireTrigger(card_id="flail") in legal_actions(s)
    s = step(s, FireTrigger(card_id="flail"))
    assert isinstance(s.pending_stack[-1], PendingBakeBread)
    s = step(s, CommitBake(grain=1))
    assert s.players[0].resources.food == food0 + 2
    assert s.players[0].resources.grain == 1
    s = step(s, Stop())                            # pop the bake frame
    # Spent for this use.
    assert FireTrigger(card_id="flail") not in legal_actions(s)


# ---------------------------------------------------------------------------
# Optionality: the grant is declinable
# ---------------------------------------------------------------------------

def test_grant_is_optional_on_farmland():
    s = _baker_state()
    food0 = s.players[0].resources.food
    grain0 = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="farmland"))
    # Decline the bake by taking the mandatory plow instead.
    assert FireTrigger(card_id="flail") in legal_actions(s)
    s = step(s, ChooseSubAction(name="plow"))
    s = step(s, legal_actions(s)[0])               # commit the plow
    s = step(s, Stop())                            # pop the plow frame
    s = step(s, Stop())                            # pop the host frame; turn ends
    assert not s.pending_stack
    # No bake taken: food and grain untouched.
    assert s.players[0].resources.food == food0
    assert s.players[0].resources.grain == grain0


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_without_a_usable_bake():
    # Owns Flail + a baker, but no grain -> _can_bake_bread is False.
    s = _baker_state(grain=0)
    s = step(s, PlaceWorker(space="farmland"))
    la = legal_actions(s)
    assert FireTrigger(card_id="flail") not in la
    # The space still proceeds normally (its mandatory plow remains offered).
    assert ChooseSubAction(name="plow") in la


def test_not_offered_without_card():
    s = _baker_state(own=False)
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id="flail") not in legal_actions(s)


def test_not_offered_on_unrelated_space():
    # Owns Flail + a usable bake, but Forest is not Farmland/Cultivation, and Flail
    # does not hook it (no register_action_space_hook), so no grant is offered.
    s = _baker_state()
    assert PlaceWorker(space="forest") in legal_actions(s)
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(a, FireTrigger) and a.card_id == "flail"
                   for a in legal_actions(s))
