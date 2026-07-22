"""Tests for Social Benefits (minor improvement, D76; Dulcinaria Expansion).

Card text: "Immediately after the feeding phase of each harvest, if you have no
food left, you get 1 wood and 1 clay."

A harvest-window AUTO on the `after_feeding` window (ruling 2026-07-05:
"immediately after the feeding phase" = "after the feeding phase", one window)
— fired mechanically inside the harvest walk (`_process_simple_window`,
window-major, SP first) per owner, AFTER the FEED payment has resolved.
Eligibility reads the post-payment food (`resources.food == 0`, the "no food
left" instant), and the reward is a flat +1 wood +1 clay. Tests drive the real
walk so the fire-point (after feeding, before breeding) is exercised
end-to-end. The ruled ordering against Farm Store (the same window's optional
food-spending trigger) — Social Benefits FIRST, via autos-before-triggers — is
pinned by the interaction test at the bottom.
"""
import agricola.cards.social_benefits  # noqa: F401  -- registers the card

from agricola.cards.social_benefits import CARD_ID
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.actions import CommitPlayMinor
from agricola.pending import PendingHarvestBreed, PendingHarvestFeed, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env

from tests.factories import (
    with_current_player,
    with_pending_stack,
    with_phase,
    with_resources,
)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(seed=0):
    state, _env = setup_env(seed, card_pool=_POOL)
    p0 = fast_replace(state.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(state.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(state, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set(state, idx, **kw):
    """Set player fields (resources via **resource kwargs, or people_total)."""
    people = kw.pop("people_total", None)
    p = state.players[idx]
    if people is not None:
        p = fast_replace(p, people_total=people)
    if kw:
        p = fast_replace(p, resources=fast_replace(p.resources, **kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state; both players start with `food` food."""
    state = with_phase(_base_state(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = _set(state, idx, food=food)
    return state


def _starving_state(seed=0):
    """A HARVEST_FIELD state where player 0 has 2 people (need 4 food), NO food,
    and no convertible goods — so feeding leaves them at exactly 0 food (begging).
    Player 1 has ample food (feeds cleanly, keeps surplus)."""
    state = _harvest_state(seed, food=0)
    state = _set(state, 0, people_total=2, food=0, grain=0, veg=0)
    state = _set(state, 1, people_total=2, food=10)
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON)
# ---------------------------------------------------------------------------

def test_registered_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(Resources(reed=1))       # "1 Reed"
    assert spec.max_occupations == 1                  # "At Most 1 Occupation"
    assert spec.min_occupations == 0
    assert spec.vps == 0
    assert spec.passing_left is False
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("after_feeding", ())}
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("after_feeding", set())


# ---------------------------------------------------------------------------
# Fires when food runs out at feeding
# ---------------------------------------------------------------------------

def test_grants_when_no_food_left_after_feeding():
    state = _starving_state()
    state = _own_minor(state, 0, CARD_ID)
    wood0 = state.players[0].resources.wood
    clay0 = state.players[0].resources.clay
    state = _run_harvest(state)
    # Player 0 begged (0 food after feeding), so Social Benefits fired: +1 wood +1 clay.
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers > 0
    assert state.players[0].resources.wood == wood0 + 1
    assert state.players[0].resources.clay == clay0 + 1


def test_does_not_grant_when_food_remains():
    """Player 0 feeds cleanly with surplus food left -> no grant."""
    state = _harvest_state(food=10)                   # 2 people need 4, keeps 6
    state = _own_minor(state, 0, CARD_ID)
    wood0 = state.players[0].resources.wood
    clay0 = state.players[0].resources.clay
    state = _run_harvest(state)
    assert state.players[0].resources.food > 0
    assert state.players[0].resources.wood == wood0   # no wood
    assert state.players[0].resources.clay == clay0   # no clay


def test_grants_when_food_exactly_zero_no_begging():
    """"No food left" is about food==0, not about begging: a player who feeds to
    exactly 0 with no shortfall still gets the reward."""
    state = _harvest_state(food=0)
    # 2 people need 4 food; give exactly 4 -> feeds fully, ends at 0 food, no begging.
    state = _set(state, 0, people_total=2, food=4)
    state = _own_minor(state, 0, CARD_ID)
    wood0 = state.players[0].resources.wood
    state = _run_harvest(state)
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers == 0      # fed fully
    assert state.players[0].resources.wood == wood0 + 1


# ---------------------------------------------------------------------------
# Timing: fires AFTER feeding (post-payment), and only there
# ---------------------------------------------------------------------------

def test_not_granted_before_feeding_resolves():
    """At the FEED frame (payment not yet committed) the reward has not arrived —
    the food==0 read is the POST-payment food, granted only at after_feeding."""
    state = _starving_state()
    state = _own_minor(state, 0, CARD_ID)
    wood0 = state.players[0].resources.wood
    state = _advance_until_decision(state)
    # Walk until a PendingHarvestFeed frame is up (feeding not yet paid).
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            break
        state = step(state, legal_actions(state)[0])
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)
    # No reward yet — the after_feeding auto has not fired.
    assert state.players[0].resources.wood == wood0


def test_fires_before_breeding():
    """The grant lands before the breeding frames (after_feeding precedes breeding)."""
    state = _starving_state()
    state = _own_minor(state, 0, CARD_ID)
    wood0 = state.players[0].resources.wood
    state = _advance_until_decision(state)
    # Drive through feeding until a PendingHarvestBreed frame appears.
    saw_reward_before_breed = False
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestBreed):
            # By the time breeding frames are up, the reward has already landed.
            saw_reward_before_breed = state.players[0].resources.wood == wood0 + 1
            break
        state = step(state, legal_actions(state)[0])
    assert saw_reward_before_breed


# ---------------------------------------------------------------------------
# Owner-gating and negative cases
# ---------------------------------------------------------------------------

def test_unowned_never_fires():
    state = _starving_state()                          # player 0 begs, but no card
    wood0 = state.players[0].resources.wood
    clay0 = state.players[0].resources.clay
    state = _run_harvest(state)
    assert state.players[0].resources.food == 0
    assert state.players[0].resources.wood == wood0    # no grant without ownership
    assert state.players[0].resources.clay == clay0


def test_owner_gating_opponent_food_irrelevant():
    """Player 1 owns the card; player 0 is the one who begs. Player 1 fed cleanly
    (food remains), so player 1 does NOT get the reward off player 0's shortage."""
    state = _starving_state()
    state = _set(state, 1, people_total=2, food=10)    # player 1 keeps surplus
    state = _own_minor(state, 1, CARD_ID)
    wood1 = state.players[1].resources.wood
    state = _run_harvest(state)
    assert state.players[1].resources.food > 0
    assert state.players[1].resources.wood == wood1    # no grant (owner has food)


# ---------------------------------------------------------------------------
# Prerequisite + real play flow
# ---------------------------------------------------------------------------

def test_prereq_at_most_one_occupation():
    spec = MINORS[CARD_ID]
    state = _base_state()
    # 0 occupations: allowed.
    assert prereq_met(spec, state, 0)
    # 1 occupation: allowed (At Most 1).
    p = fast_replace(state.players[0], occupations=frozenset({"o0"}))
    s1 = fast_replace(state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
    assert prereq_met(spec, s1, 0)
    # 2 occupations: NOT allowed.
    p = fast_replace(state.players[0], occupations=frozenset({"o0", "o1"}))
    s2 = fast_replace(state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
    assert not prereq_met(spec, s2, 0)


def _at_play_minor_frame(occupations=frozenset(), reed=1):
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}),
                     occupations=occupations)
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_resources(state, cp, reed=reed)
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def test_real_play_with_prereq_met():
    state, cp = _at_play_minor_frame(occupations=frozenset())
    plays = [a for a in legal_actions(state)
             if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert len(plays) == 1
    state = step(state, plays[0])
    assert CARD_ID in state.players[cp].minor_improvements
    assert state.players[cp].resources.reed == 0       # paid 1 reed


def test_prereq_blocks_play_with_two_occupations():
    state, cp = _at_play_minor_frame(occupations=frozenset({"o0", "o1"}))
    assert not any(isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                   for a in legal_actions(state))


# ---------------------------------------------------------------------------
# The ruled ordering vs Farm Store (ruling 2026-07-05: same window, this first)
# ---------------------------------------------------------------------------

def test_social_benefits_resolves_before_farm_store():
    """Both cards share the after_feeding window; the ruling puts Social
    Benefits (an automatic effect) BEFORE Farm Store (an optional trigger) via
    the standing autos-before-triggers ordering. A player ending feeding with
    exactly 1 food therefore CANNOT spend it at Farm Store first and then
    collect the "no food left" grant: the check has already seen 1 food."""
    import agricola.cards.farm_store  # noqa: F401  -- registers Farm Store
    from agricola.actions import FireTrigger
    from agricola.cards.farm_store import CARD_ID as FARM_STORE
    from agricola.pending import PendingHarvestWindow

    # 2 people need 4 food; 5 food -> ends feeding with exactly 1.
    state = _harvest_state(food=0)
    state = _set(state, 0, people_total=2, food=5)
    state = _set(state, 1, people_total=2, food=10)
    state = _own_minor(state, 0, CARD_ID)
    state = _own_minor(state, 0, FARM_STORE)
    wood0 = state.players[0].resources.wood
    clay0 = state.players[0].resources.clay

    # Drive the walk to P0's after_feeding window frame.
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "after_feeding" and top.player_idx == 0):
            break
        state = step(state, legal_actions(state)[0])
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)

    # The auto already ran (autos fire before the trigger frame is hosted):
    # 1 food remained, so NO grant — and Farm Store's exchange is now offered.
    assert state.players[0].resources.food == 1
    assert state.players[0].resources.wood == wood0
    assert state.players[0].resources.clay == clay0
    veg_swap = [a for a in legal_actions(state)
                if isinstance(a, FireTrigger) and a.card_id == FARM_STORE
                and getattr(a, "variant", None) == "veg"]
    assert veg_swap

    # Spend the last food at Farm Store; the "no food left" check must NOT
    # re-fire — the wood/clay grant never arrives this harvest.
    state = step(state, veg_swap[0])
    assert state.players[0].resources.food == 0
    state = _run_harvest(state)
    assert state.players[0].resources.wood == wood0
    assert state.players[0].resources.clay == clay0
    assert state.players[0].resources.veg >= 1


# ---------------------------------------------------------------------------
# The converter-cluster interaction (rulings 34/36, 2026-07-12) — a buy at the
# payment frame can DELIBERATELY zero food before the after_feeding check.
# This is the very line whose profitability killed the late-anchor approach
# (ruling 36's derivation): keep 2 food after covering the need, spend it on
# Furniture Carpenter's point AT the payment frame (conversions fire before
# CommitConvert), end feeding at 0 food, and collect Social Benefits' grant.
# ---------------------------------------------------------------------------

import agricola.cards.furniture_carpenter  # noqa: F401,E402

from agricola.actions import CommitConvert, CommitHarvestConversion  # noqa: E402
from agricola.pending import PendingHarvestFeed  # noqa: E402


def test_deliberate_zero_via_payment_frame_buy_fires_social_benefits():
    state = _harvest_state(food=6)          # 2 people need 4; 2 would remain
    from agricola.replace import fast_replace
    p0 = state.players[0]
    p0 = fast_replace(p0, occupations=p0.occupations | {"furniture_carpenter"})
    state = fast_replace(state, players=tuple(
        p0 if i == 0 else state.players[i] for i in range(2)))
    state = _own_minor(state, 0, CARD_ID)
    from tests.factories import with_majors
    state = with_majors(state, owner_by_idx={7: 0})   # the Joinery condition
    wood0 = state.players[0].resources.wood
    clay0 = state.players[0].resources.clay

    def pick(acts):
        top_buy = [a for a in acts
                   if isinstance(a, CommitHarvestConversion)
                   and a.conversion_id == "furniture_carpenter"]
        if top_buy:
            return top_buy[0]
        # Decline the Joinery's craft-span window offers (the Cards-only span
        # surfaces, ruling 74 2026-07-21): this test's Joinery exists only as
        # Furniture Carpenter's condition, and firing its span conversion would
        # refill food past the deliberate zero this test constructs.
        from agricola.actions import FireTrigger
        non_span = [a for a in acts
                    if not (isinstance(a, FireTrigger)
                            and a.card_id.startswith("craft_span_"))]
        return (non_span or acts)[0]

    state = _run_harvest(state, pick)
    p = state.players[0]
    assert p.card_state.get("furniture_carpenter", 0) == 1   # the point bought
    assert p.resources.food == 0                              # fed to exactly 0
    assert p.begging_markers == 0                             # no shortfall
    # Social Benefits saw "no food left after feeding": +1 wood +1 clay.
    assert p.resources.wood == wood0 + 1
    assert p.resources.clay == clay0 + 1
