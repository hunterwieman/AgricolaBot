import agricola.cards.field_merchant  # noqa: F401  (registers the card — must be first)
import agricola.cards.market_stall  # noqa: F401  (a cheap minor for the play/decline branches)
import agricola.cards.merchant      # noqa: F401  (the repeat, for the no-double clarification)

"""Tests for Field Merchant (occupation, Bubulcus Expansion; deck B #103).

Card text: "When you play this card, you immediately get 1 wood and 1 reed.
Each time you decline a \"Minor/Major Improvement\" action, you get 1
food/vegetable instead."

USER RULING 74 (2026-07-21, CARD_DEFERRED_PLANS.md): declining a "Minor
Improvement" action -> 1 food; declining a "Major or Minor Improvement" action
-> 1 vegetable. Detection keys on the NAMED actions wherever they occur;
exiting an improvement action you could not use counts as declining; placing on
the Major Improvement space just to decline must be legal (ownership-gated
placement extension + a decline route on the composite host); a min-spend
composite (Stone Company) is NOT declinable (both cards' printed
clarifications).
"""
from agricola.actions import (
    ChooseSubAction,
    CommitFamilyGrowth,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import IMPROVEMENT_DECLINE_INCOME
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
from agricola.pending import (
    PendingGrantedSubAction,
    PendingMajorMinorImprovement,
    PendingSubActionSpace,
    push,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell
from tests.factories import (
    with_current_player,
    with_grid,
    with_resources,
    with_space,
)
from tests.test_utils import sole_build_major, sole_play_minor, sole_renovate

CARD_ID = "field_merchant"
FIREPLACE_0 = 0   # 2 clay — the cheapest major

_POOL = CardPool(
    occupations=(CARD_ID, "merchant") + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)

_DECLINE = ChooseSubAction(name="decline_improvement")


def _card_state(*, seed=5, res=None, hand=(), occ=(), played=True):
    """Card-mode state: the active player has played Field Merchant (or holds it
    in hand when played=False) plus `occ` extra occupations, holds `hand` minors,
    with resources `res`. Both hands and the opponent's resources are zeroed so
    every goods delta in the asserts is the card's."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(
        p,
        occupations=(p.occupations | {CARD_ID} if played else p.occupations)
        | set(occ),
        hand_occupations=frozenset() if played else frozenset({CARD_ID}),
        hand_minors=frozenset(hand),
        resources=res if res is not None else Resources())
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset(),
                       hand_occupations=frozenset(), resources=Resources())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _wish_ready(cs, cp):
    """Reveal Basic Wish and give player `cp` a 3rd room so growth is legal."""
    cs = with_space(cs, "basic_wish_for_children", revealed=True, workers=(0, 0))
    return with_grid(cs, cp, {(0, 4): Cell(cell_type=CellType.ROOM)})


def _do_growth(cs):
    """Drive Basic Wish's mandatory growth back to the parent's before-phase."""
    cs = step(cs, ChooseSubAction(name="family_growth"))
    cs = step(cs, CommitFamilyGrowth())
    return step(cs, Stop())     # pop PendingFamilyGrowth's after-phase


def _renovate(cs):
    """Drive House Redevelopment's mandatory renovate back to the parent."""
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, sole_renovate(cs))
    return step(cs, Stop())     # pop PendingRenovate's after-phase


# ---------------------------------------------------------------------------
# Registration + on-play
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in IMPROVEMENT_DECLINE_INCOME


def test_on_play_grants_wood_and_reed():
    # "When you play this card, you immediately get 1 wood and 1 reed" —
    # end-to-end through Lessons (the first occupation is free).
    cs, cp = _card_state(played=False)
    cs = with_space(cs, "lessons", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=CARD_ID))
    p = cs.players[cp]
    assert CARD_ID in p.occupations
    assert p.resources.wood == 1 and p.resources.reed == 1


# ---------------------------------------------------------------------------
# The "Minor Improvement" action — Meeting Place / Basic Wish (kind "minor")
# ---------------------------------------------------------------------------

def test_meeting_place_decline_no_playable_minor_pays_food():
    # "Exiting an improvement action you could not use counts as declining"
    # (ruling 74): the Meeting Place host is always pushed in card mode, so
    # proceeding past its minor with NOTHING playable still pays 1 food.
    cs, cp = _card_state()
    cs = step(cs, PlaceWorker(space="meeting_place"))
    assert ChooseSubAction(name="play_minor") not in legal_actions(cs)
    cs = step(cs, Proceed())
    assert cs.players[cp].resources.food == 1
    assert cs.players[cp].resources.veg == 0    # the "minor" kind pays food
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


def test_meeting_place_decline_with_playable_minor_pays_food():
    cs, cp = _card_state(hand=("market_stall",), res=Resources(grain=1))
    cs = step(cs, PlaceWorker(space="meeting_place"))
    assert ChooseSubAction(name="play_minor") in legal_actions(cs)
    cs = step(cs, Proceed())                    # decline the playable minor
    assert cs.players[cp].resources.food == 1


def test_meeting_place_play_minor_pays_nothing():
    cs, cp = _card_state(hand=("market_stall",), res=Resources(grain=1))
    cs = step(cs, PlaceWorker(space="meeting_place"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())                       # pop the play-minor after-phase
    cs = step(cs, Proceed())                    # the branch was TAKEN — no decline
    p = cs.players[cp]
    assert p.resources.food == 0
    assert p.resources.veg == 1                 # Market Stall's own grant only


def test_opponent_decline_pays_owner_nothing():
    # "YOU decline" — the non-owner declining pays the owner nothing.
    cs, cp = _card_state()
    cs = fast_replace(cs, current_player=1 - cp)
    cs = step(cs, PlaceWorker(space="meeting_place"))
    cs = step(cs, Proceed())
    assert cs.players[cp].resources.food == 0
    assert cs.players[1 - cp].resources.food == 0


def test_basic_wish_decline_pays_food():
    cs, cp = _card_state()
    cs = _wish_ready(cs, cp)
    cs = step(cs, PlaceWorker(space="basic_wish_for_children"))
    cs = _do_growth(cs)
    cs = step(cs, Proceed())                    # exit with the minor unchosen
    assert cs.players[cp].resources.food == 1
    assert cs.players[cp].resources.veg == 0


def test_basic_wish_play_minor_pays_nothing():
    cs, cp = _card_state(hand=("market_stall",), res=Resources(grain=1))
    cs = _wish_ready(cs, cp)
    cs = step(cs, PlaceWorker(space="basic_wish_for_children"))
    cs = _do_growth(cs)
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())
    cs = step(cs, Proceed())
    assert cs.players[cp].resources.food == 0


# ---------------------------------------------------------------------------
# The "Minor Improvement" action — granted named-minor wrapper (kind "minor")
# ---------------------------------------------------------------------------

def test_named_minor_wrapper_declined_via_stop_pays_food():
    # A granted NAMED minor action (minor_is_action=True — Sample Stable Maker /
    # Task Artisan's shape) popped via Stop untaken IS a decline.
    cs, cp = _card_state(hand=("market_stall",), res=Resources(grain=1))
    cs = push(cs, PendingGrantedSubAction(
        player_idx=cp, initiated_by_id="card:sample_stable_maker",
        subactions=("play_minor",), minor_is_action=True))
    acts = legal_actions(cs)
    assert ChooseSubAction(name="play_minor") in acts and Stop() in acts
    cs = step(cs, Stop())
    assert cs.players[cp].resources.food == 1


def test_named_minor_wrapper_taken_pays_nothing():
    cs, cp = _card_state(hand=("market_stall",), res=Resources(grain=1))
    cs = push(cs, PendingGrantedSubAction(
        player_idx=cp, initiated_by_id="card:sample_stable_maker",
        subactions=("play_minor",), minor_is_action=True))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())                       # pop the play-minor after-phase
    cs = step(cs, Stop())                       # pop the wrapper — branch TAKEN
    assert cs.players[cp].resources.food == 0


def test_flag_false_grant_declined_pays_nothing():
    # A card's own "play a minor" grant (Scholar / Beneficiary / Equipper —
    # minor_is_action=False) is NOT the named action; Equipper's printed
    # clarification ("This effect is not a 'Minor Improvement' action") is
    # excluded structurally by the flag.
    cs, cp = _card_state(hand=("market_stall",), res=Resources(grain=1))
    cs = push(cs, PendingGrantedSubAction(
        player_idx=cp, initiated_by_id="card:scholar",
        subactions=("play_minor",), minor_is_action=False))
    cs = step(cs, Stop())
    assert cs.players[cp].resources.food == 0


# ---------------------------------------------------------------------------
# The "Major or Minor Improvement" action — House Redevelopment (kind
# "major_or_minor")
# ---------------------------------------------------------------------------

def test_house_redev_skip_improvement_pays_veg():
    cs, cp = _card_state(res=Resources(clay=2, reed=1))   # 2 rooms -> 2c + 1r
    cs = with_space(cs, "house_redevelopment", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = _renovate(cs)
    cs = step(cs, Proceed())                    # composite step never entered
    assert cs.players[cp].resources.veg == 1
    assert cs.players[cp].resources.food == 0   # the "major_or_minor" kind pays veg
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


def test_house_redev_take_improvement_pays_nothing():
    cs, cp = _card_state(res=Resources(clay=4, reed=1))
    cs = with_space(cs, "house_redevelopment", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = _renovate(cs)
    cs = step(cs, ChooseSubAction(name="improvement"))
    # The composite offers the ownership-gated decline route alongside the build.
    acts = legal_actions(cs)
    assert _DECLINE in acts and ChooseSubAction(name="build_major") in acts
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, FIREPLACE_0))
    cs = step(cs, Stop())                       # pop the build-major after-phase
    cs = step(cs, Stop())                       # pop the composite after-phase
    cs = step(cs, Proceed())                    # improvement_chosen -> no decline
    p = cs.players[cp]
    assert p.resources.veg == 0 and p.resources.food == 0
    assert cs.board.major_improvement_owners[FIREPLACE_0] == cp


def test_house_redev_composite_entered_then_declined_pays_once():
    # Entering the composite and declining it pays at the composite; House
    # Redevelopment's own Proceed (improvement_chosen=True) must not pay again.
    cs, cp = _card_state(res=Resources(clay=4, reed=1))
    cs = with_space(cs, "house_redevelopment", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = _renovate(cs)
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, _DECLINE)                     # decline INSIDE the composite
    assert cs.players[cp].resources.veg == 1
    cs = step(cs, Proceed())                    # back at the HR host — no re-pay
    assert cs.players[cp].resources.veg == 1
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# The Major Improvement space (kind "major_or_minor"), incl. place-just-to-decline
# ---------------------------------------------------------------------------

def test_major_space_declined_pays_veg_and_builds_nothing():
    cs, cp = _card_state(res=Resources(clay=2))   # a Fireplace IS affordable
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    assert isinstance(cs.pending_stack[-1], PendingSubActionSpace)
    cs = step(cs, ChooseSubAction(name="improvement"))
    acts = legal_actions(cs)
    assert _DECLINE in acts and ChooseSubAction(name="build_major") in acts
    cs = step(cs, _DECLINE)
    # The composite popped un-flipped; the space wrapper auto-advanced to after.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace) and top.phase == "after"
    assert cs.players[cp].resources.veg == 1
    assert cs.players[cp].resources.clay == 2     # nothing spent
    assert cs.board.major_improvement_owners[FIREPLACE_0] is None
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


def test_place_just_to_decline_with_zero_resources():
    # The printed clarification: "You can place onto the 'Major Improvement'
    # ... action space just to decline it" — legal with NOTHING affordable.
    cs, cp = _card_state()                        # zero resources, empty hand
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    assert "major_improvement" in {a.space for a in legal_placements(cs)}
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    assert legal_actions(cs) == [_DECLINE]        # nothing affordable: only the decline
    cs = step(cs, _DECLINE)
    assert cs.players[cp].resources.veg == 1
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


def test_placement_stays_gated_without_the_card():
    # A hand-only copy grants no affordance ("a hand card cannot fire").
    cs, _cp = _card_state(played=False)           # zero resources, empty hand
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    assert "major_improvement" not in {a.space for a in legal_placements(cs)}


def test_normal_major_build_pays_nothing():
    cs, cp = _card_state(res=Resources(clay=2))
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, FIREPLACE_0))
    cs = step(cs, Stop())                         # pop the build-major after-phase
    cs = step(cs, Stop())                         # pop the composite after-phase
    cs = step(cs, Stop())                         # pop the space wrapper
    p = cs.players[cp]
    assert p.resources.veg == 0 and p.resources.food == 0
    assert cs.board.major_improvement_owners[FIREPLACE_0] == cp


# ---------------------------------------------------------------------------
# Granted composites: Angler-style declined pays; Stone Company's is not
# declinable; a Merchant repeat declined pays exactly once
# ---------------------------------------------------------------------------

def test_granted_composite_declined_pays_veg():
    # An Angler-style card-granted "Major or Minor Improvement" action.
    cs, cp = _card_state(res=Resources(clay=2))
    cs = push(cs, PendingMajorMinorImprovement(
        player_idx=cp, initiated_by_id="card:angler"))
    assert _DECLINE in legal_actions(cs)
    cs = step(cs, _DECLINE)
    assert cs.players[cp].resources.veg == 1


def test_min_spend_composite_offers_no_decline():
    # Stone Company's constrained grant: "improvements are conditional on
    # spending stone and can't be declined" (Field Merchant's clarification) /
    # "Improvement action is not declinable in order to use Field Merchant
    # B103" (Stone Company's). The build IS affordable here (3 clay + 1 stone
    # pays the Clay Oven under the constraint), so the route's absence is the
    # min-spend gate, not poverty.
    cs, _cp = _card_state(res=Resources(clay=3, stone=1))
    cs = push(cs, PendingMajorMinorImprovement(
        player_idx=cs.current_player, initiated_by_id="card:stone_company",
        min_spend=Resources(stone=1)))
    acts = legal_actions(cs)
    assert ChooseSubAction(name="build_major") in acts
    assert _DECLINE not in acts


def test_merchant_repeat_declined_pays_exactly_once():
    # "Merchant C096 does not double a decline": a Merchant-repeated composite
    # declined is ONE decline event -> exactly 1 vegetable, never 2. (The base
    # action was TAKEN — a fireplace built — so it pays nothing itself; the
    # repeat, a fresh named composite, is declined once.)
    cs, cp = _card_state(res=Resources(clay=4, food=1), occ=("merchant",))
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, FIREPLACE_0))
    cs = step(cs, Stop())                         # pop the build-major after-phase
    # The base composite's after-phase: Merchant's repeat is offered (1 food).
    fire = FireTrigger(card_id="merchant")
    assert fire in legal_actions(cs)
    cs = step(cs, fire)
    top = cs.pending_stack[-1]
    assert (isinstance(top, PendingMajorMinorImprovement)
            and top.initiated_by_id == "card:merchant")
    cs = step(cs, _DECLINE)                       # decline the repeat
    p = cs.players[cp]
    assert p.resources.veg == 1                   # once, not doubled
    assert p.resources.food == 0                  # Merchant's fee was paid
    cs = step(cs, Stop())                         # pop the base composite
    cs = step(cs, Stop())                         # pop the space wrapper
    assert cs.players[cp].resources.veg == 1      # still exactly one payout


def test_decline_of_repeat_never_offered_off_a_declined_action():
    # A declined composite pops WITHOUT flipping: no after-window, so Merchant's
    # repeat (an after_major_minor_improvement trigger) is never offered off it.
    cs, _cp = _card_state(res=Resources(clay=4, food=1), occ=("merchant",))
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, _DECLINE)
    # Back at the space wrapper's after-phase — no Merchant FireTrigger anywhere.
    assert not any(isinstance(a, FireTrigger) and a.card_id == "merchant"
                   for a in legal_actions(cs))


# ---------------------------------------------------------------------------
# Family inertness: the seams are ownership-gated, so the one Family frame a
# seam touches (House Redevelopment's Proceed) pays nothing
# ---------------------------------------------------------------------------

def test_family_house_redev_proceed_unchanged():
    assert IMPROVEMENT_DECLINE_INCOME            # the registry IS populated...
    state = setup(seed=0)                        # ...but Family owns no cards
    state = with_current_player(state, 0)
    state = with_resources(state, 0, clay=2, reed=1)
    state = with_space(state, "house_redevelopment", revealed=True)
    veg0 = state.players[0].resources.veg
    food0 = state.players[0].resources.food
    state = step(state, PlaceWorker(space="house_redevelopment"))
    state = _renovate(state)
    state = step(state, Proceed())               # improvement skipped — no income
    assert state.players[0].resources.veg == veg0
    assert state.players[0].resources.food == food0
    state = step(state, Stop())
    assert state.pending_stack == ()
