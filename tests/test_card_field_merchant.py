import agricola.cards.field_merchant  # noqa: F401  (registers the card — must be first)
import agricola.cards.market_stall  # noqa: F401  (a cheap minor for the play/decline branches)
import agricola.cards.merchant      # noqa: F401  (the repeat, for the no-double clarification)
import agricola.cards.angler        # noqa: F401  (ruling-76 granting cards below)
import agricola.cards.vegetable_vendor      # noqa: F401
import agricola.cards.sample_stable_maker   # noqa: F401
import agricola.cards.task_artisan          # noqa: F401
import agricola.cards.tree_farm_joiner      # noqa: F401

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
from agricola.cards.triggers import (
    IMPROVEMENT_DECLINE_INCOME,
    NAMED_ACTION_GRANTS,
)
from agricola.constants import CellType, Phase, STAGE_CARDS, stage_of_round
from agricola.engine import _advance_until_decision, _complete_preparation, step
from agricola.legality import legal_actions, legal_placements
from agricola.pending import (
    PendingActionSpace,
    PendingGrantedSubAction,
    PendingHarvestWindow,
    PendingMajorMinorImprovement,
    PendingReveal,
    PendingSubActionSpace,
    push,
)
from agricola.actions import RevealCard
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, FutureReward, get_space
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

# ===========================================================================
# RULING 76 (2026-07-21): declining-to-fire a trigger that would GRANT a named
# improvement action counts as declining the action — including when the
# trigger was withheld as unaffordable. Fired grants stay on the frames' own
# decline seams (no double pay).
# ===========================================================================

def test_ruling76_grant_registrations():
    entries = {(e.card_id, e.kind) for e in NAMED_ACTION_GRANTS}
    assert {("angler", "major_or_minor"),
            ("vegetable_vendor", "major_or_minor"),
            ("sample_stable_maker", "minor"),
            ("task_artisan", "minor"),
            ("tree_farm_joiner", "minor")} <= entries  # subset — the registry grows
    ids = {e.card_id for e in NAMED_ACTION_GRANTS}
    assert "stone_company" not in ids                  # not declinable (clarifications)
    assert "harvest_festival_planning" not in ids      # on-play grant, no trigger
    # Merchant is EXCLUDED (user ruling 77 item 3, 2026-07-21): "Merchant
    # requires the player to pay 1 food and then take the relevant action. I
    # don't think declining this bundle counts as declining the action."
    assert "merchant" not in ids
    # The window-hosted grants carry their window ids for the walk extension.
    windows = {e.card_id: e.window for e in NAMED_ACTION_GRANTS}
    assert windows["sample_stable_maker"] == "start_of_returning_home"
    assert windows["task_artisan"] == "reveal"
    assert windows["tree_farm_joiner"] == "round_space_collection"
    assert windows["angler"] is None


# --- Angler (frame-hosted, "major_or_minor") --------------------------------

def _fishing_used(cs, *, food_on_space=2):
    """Drive the hosted Fishing lifecycle to its after-phase (take included)."""
    cs = with_space(cs, "fishing", workers=(0, 0), accumulated_amount=food_on_space)
    cs = step(cs, PlaceWorker(space="fishing"))
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    cs = step(cs, Proceed())                          # the take
    assert cs.pending_stack[-1].phase == "after"
    return cs


def test_angler_unfired_offered_pays_veg():
    cs, cp = _card_state(res=Resources(clay=2), occ=("angler",))
    cs = _fishing_used(cs)
    assert FireTrigger(card_id="angler") in legal_actions(cs)   # affordable, offered
    cs = step(cs, Stop())                              # decline-to-fire
    assert cs.players[cp].resources.veg == 1
    assert cs.players[cp].resources.food == 2          # the take only


def test_angler_withheld_unaffordable_still_pays():
    # Nothing buildable/playable -> the trigger is never offered; the grant's
    # CONDITION (fishing, pre-take food <= 2) still held -> declined -> pays.
    cs, cp = _card_state(occ=("angler",))              # zero resources, no hand
    cs = _fishing_used(cs)
    assert FireTrigger(card_id="angler") not in legal_actions(cs)
    cs = step(cs, Stop())
    assert cs.players[cp].resources.veg == 1


def test_angler_condition_false_pays_nothing():
    cs, cp = _card_state(res=Resources(clay=2), occ=("angler",))
    cs = _fishing_used(cs, food_on_space=3)            # pre-take food > 2
    cs = step(cs, Stop())
    assert cs.players[cp].resources.veg == 0


def test_angler_fired_and_taken_pays_nothing():
    cs, cp = _card_state(res=Resources(clay=2), occ=("angler",))
    cs = _fishing_used(cs)
    cs = step(cs, FireTrigger(card_id="angler"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, FIREPLACE_0))
    cs = step(cs, Stop())                              # pop build-major after-phase
    cs = step(cs, Stop())                              # pop the granted composite
    cs = step(cs, Stop())                              # pop the fishing host
    assert cs.players[cp].resources.veg == 0           # taken, not declined
    assert cs.board.major_improvement_owners[FIREPLACE_0] == cp


def test_angler_fired_then_declined_pays_exactly_once():
    # Fired-then-frame-declined: the composite's own decline route pays; the
    # fishing host's exit must NOT pay again ("angler" is in triggers_resolved).
    cs, cp = _card_state(res=Resources(clay=2), occ=("angler",))
    cs = _fishing_used(cs)
    cs = step(cs, FireTrigger(card_id="angler"))
    cs = step(cs, _DECLINE)
    assert cs.players[cp].resources.veg == 1
    cs = step(cs, Stop())                              # pop the fishing host
    assert cs.players[cp].resources.veg == 1           # exactly once


def test_angler_without_decline_income_pays_nothing():
    cs, cp = _card_state(res=Resources(clay=2), occ=("angler",), played=False)
    cs = _fishing_used(cs)
    cs = step(cs, Stop())                              # decline-to-fire
    assert cs.players[cp].resources.veg == 0           # FM is hand-only


def test_opponent_granting_card_decline_pays_fm_owner_nothing():
    # "YOU decline": the opponent owns Angler (no decline income) and declines;
    # the Field Merchant owner was not the decliner — nobody is paid.
    cs, cp = _card_state()                             # cp owns FM only
    opp = 1 - cp
    o = cs.players[opp]
    cs = fast_replace(cs, players=tuple(
        fast_replace(o, occupations=o.occupations | {"angler"}) if i == opp
        else cs.players[i] for i in range(2)))
    cs = fast_replace(cs, current_player=opp)
    cs = _fishing_used(cs)
    cs = step(cs, Stop())
    assert cs.players[cp].resources.veg == 0
    assert cs.players[opp].resources.veg == 0


# --- Vegetable Vendor (frame-hosted before-window, "major_or_minor") --------

def _veg_seeds_state(**kw):
    cs, cp = _card_state(occ=("vegetable_vendor",), **kw)
    return with_space(cs, "vegetable_seeds", revealed=True, workers=(0, 0)), cp


def test_vegetable_vendor_unfired_offered_pays_veg():
    cs, cp = _veg_seeds_state(res=Resources(clay=2))
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    assert FireTrigger(card_id="vegetable_vendor") in legal_actions(cs)
    cs = step(cs, Proceed())                           # the take closes the window
    cs = step(cs, Stop())
    assert cs.players[cp].resources.veg == 2           # 1 take + 1 decline income


def test_vegetable_vendor_withheld_unaffordable_still_pays():
    cs, cp = _veg_seeds_state()                        # zero resources, no hand
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    assert FireTrigger(card_id="vegetable_vendor") not in legal_actions(cs)
    cs = step(cs, Proceed())
    cs = step(cs, Stop())
    assert cs.players[cp].resources.veg == 2           # 1 take + 1 decline income


def test_vegetable_vendor_fired_and_taken_pays_nothing():
    cs, cp = _veg_seeds_state(res=Resources(clay=2))
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    cs = step(cs, FireTrigger(card_id="vegetable_vendor"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, FIREPLACE_0))
    cs = step(cs, Stop())                              # pop build-major after-phase
    cs = step(cs, Stop())                              # pop the granted composite
    cs = step(cs, Proceed())                           # the space's own take
    cs = step(cs, Stop())                              # pop the host — no decline pay
    assert cs.players[cp].resources.veg == 1           # the take only


def test_vegetable_vendor_fired_then_declined_pays_exactly_once():
    cs, cp = _veg_seeds_state(res=Resources(clay=2))
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    cs = step(cs, FireTrigger(card_id="vegetable_vendor"))
    cs = step(cs, _DECLINE)                            # the composite's own seam
    assert cs.players[cp].resources.veg == 1
    cs = step(cs, Proceed())                           # take: +1 veg
    cs = step(cs, Stop())                              # host exit: no second pay
    assert cs.players[cp].resources.veg == 2           # 1 take + exactly 1 income


# --- Sample Stable Maker (window-hosted, "minor") ----------------------------

def _ssm_drained_state(*, fm=True, stable=True, owner=0, hand=()):
    """A drained Family-setup WORK state (the round-end ladder runs next);
    player `owner` owns Sample Stable Maker (+ Field Merchant when fm) with an
    (optional) standalone stable and the given hand minors."""
    state = setup(0)
    state = fast_replace(state, phase=Phase.WORK, round_number=1,
                         starting_player=0)
    p = state.players[owner]
    occs = p.occupations | {"sample_stable_maker"} | ({CARD_ID} if fm else set())
    state = fast_replace(state, players=tuple(
        fast_replace(state.players[i], people_home=0,
                     **({"occupations": occs, "hand_minors": frozenset(hand)}
                        if i == owner else {}))
        for i in range(2)))
    if stable:
        state = with_grid(state, owner, {(0, 4): Cell(cell_type=CellType.STABLE)})
    return state


def test_ssm_unfired_window_decline_pays_food():
    state = _ssm_drained_state()
    food0 = state.players[0].resources.food
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_returning_home" and top.player_idx == 0
    state = step(state, Proceed())                     # decline the whole package
    assert state.players[0].resources.food == food0 + 1


def test_ssm_no_stable_is_no_grant_no_pay():
    # Condition-vs-doability (recorded in the card module): a built stable is
    # the exchange's ENABLING CONDITION — without one no improvement action was
    # on offer, so no window frame is hosted and nothing pays.
    state = _ssm_drained_state(stable=False)
    food0 = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert not any(isinstance(f, PendingHarvestWindow)
                   and f.window_id == "start_of_returning_home"
                   for f in state.pending_stack)
    assert state.players[0].resources.food == food0


def test_ssm_fired_no_playable_minor_pays_decline_income():
    # RULING 78 item 3: SSM fired (returns a stable, +1 wood/grain/food) with no
    # playable minor -> the granted named minor is UNUSABLE, so the push site
    # pays the "minor" decline income directly (matching Meeting Place's
    # no-playable-minor payment). +1 food goods + +1 food income = +2.
    state = _ssm_drained_state()                       # empty hand
    food0 = state.players[0].resources.food
    state = _advance_until_decision(state)
    state = step(state, FireTrigger(card_id="sample_stable_maker", variant="0,4"))
    # The decline income is paid AT THE FIRE (no wrapper pushed).
    assert state.players[0].resources.food == food0 + 2
    # No wrapper on the stack — back at the window, only Proceed remains.
    assert not any(isinstance(f, PendingGrantedSubAction) for f in state.pending_stack)
    state = step(state, Proceed())                     # SSM latched -> no re-pay
    assert state.players[0].resources.food == food0 + 2


def test_ssm_fired_with_playable_minor_pays_exactly_once():
    # No-double check: SSM fired WITH a playable minor -> the wrapper is pushed
    # (helper does NOT pay), and Stopping the wrapper pays once via the existing
    # ruling-74 wrapper-Stop seam. The granted +1 grain makes Market Stall (1
    # grain) playable, so the wrapper appears.
    state = _ssm_drained_state(hand=("market_stall",))
    food0 = state.players[0].resources.food
    state = _advance_until_decision(state)
    state = step(state, FireTrigger(card_id="sample_stable_maker", variant="0,4"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction) and top.minor_is_action
    assert state.players[0].resources.food == food0 + 1   # goods only — helper didn't pay
    state = step(state, Stop())                        # decline the minor via the wrapper
    assert state.players[0].resources.food == food0 + 2   # wrapper-Stop pays once
    state = step(state, Proceed())                     # window: SSM latched -> no third pay
    assert state.players[0].resources.food == food0 + 2


def test_ssm_fired_no_minor_without_decline_income_pays_nothing():
    # The new push-site pay is registry/owner-gated: no Field Merchant -> only
    # the goods land.
    state = _ssm_drained_state(fm=False)               # empty hand, no FM
    food0 = state.players[0].resources.food
    state = _advance_until_decision(state)
    state = step(state, FireTrigger(card_id="sample_stable_maker", variant="0,4"))
    assert state.players[0].resources.food == food0 + 1   # goods only, no income


def test_ssm_fired_no_minor_opponent_owner_pays_fm_owner_nothing():
    # "YOU decline": P1 owns SSM and fires with no playable minor; P0 owns Field
    # Merchant but was not the granting/declining player -> nobody is paid.
    state = _ssm_drained_state(fm=False, owner=1)
    o = state.players[0]
    state = fast_replace(state, players=tuple(
        fast_replace(o, occupations=o.occupations | {CARD_ID}) if i == 0
        else state.players[i] for i in range(2)))
    food_fm = state.players[0].resources.food
    food_ssm = state.players[1].resources.food
    state = _advance_until_decision(state)
    state = step(state, FireTrigger(card_id="sample_stable_maker", variant="0,4"))
    assert state.players[0].resources.food == food_fm         # FM owner unpaid
    assert state.players[1].resources.food == food_ssm + 1    # SSM owner: goods only


def test_ssm_without_decline_income_unchanged():
    state = _ssm_drained_state(fm=False)
    food0 = state.players[0].resources.food
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)       # trigger-eligible hosting
    state = step(state, Proceed())
    assert state.players[0].resources.food == food0


# --- Task Artisan, on-play grant (push site — ruling 78 item 3) --------------

def test_task_artisan_on_play_no_playable_minor_pays_food():
    # RULING 78 item 3: Task Artisan's ON-PLAY grant (+1 wood + a named "Minor
    # Improvement" action) with no playable minor -> the named action is
    # unusable, so the push site pays +1 food decline income (matching Meeting
    # Place). Driven directly via on_play (the Task Artisan suite's own idiom),
    # with Field Merchant already owned so the income has a payee.
    cs, cp = _card_state(occ=("task_artisan",))        # owns FM + TA, empty hand
    food0 = cs.players[cp].resources.food
    wood0 = cs.players[cp].resources.wood
    out = OCCUPATIONS["task_artisan"].on_play(cs, cp)
    assert out.players[cp].resources.wood == wood0 + 1     # the grant's wood
    assert out.players[cp].resources.food == food0 + 1     # the decline income
    assert not any(isinstance(f, PendingGrantedSubAction) for f in out.pending_stack)


def test_task_artisan_on_play_with_playable_minor_pushes_wrapper_no_pay():
    # With a playable minor the wrapper is pushed and the helper does NOT pay
    # (the wrapper-Stop seam would, if declined) — the no-double invariant.
    cs, cp = _card_state(occ=("task_artisan",), hand=("market_stall",),
                         res=Resources(grain=1))
    food0 = cs.players[cp].resources.food
    out = OCCUPATIONS["task_artisan"].on_play(cs, cp)
    top = out.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction) and top.minor_is_action
    assert out.players[cp].resources.food == food0         # helper didn't pay


def test_task_artisan_on_play_no_fm_pays_nothing():
    # Owner-gated: without Field Merchant, the unusable on-play grant pays no
    # income (only the wood lands).
    cs, cp = _card_state(occ=("task_artisan",), played=False)   # FM in hand, not owned
    food0 = cs.players[cp].resources.food
    wood0 = cs.players[cp].resources.wood
    out = OCCUPATIONS["task_artisan"].on_play(cs, cp)
    assert out.players[cp].resources.wood == wood0 + 1
    assert out.players[cp].resources.food == food0             # no income


# --- Task Artisan, reveal path (window-hosted, "minor") ----------------------

def _mark_revealed(state, card_id, round_number):
    return with_space(state, card_id, revealed=True, revealed_round=round_number)


def _reveal_pause(state, prev_round):
    """Advance to the reveal nature pause entering round prev_round+1 (the
    Task Artisan test-file idiom): mark rounds 2..prev_round's stage cards
    revealed, then run the preparation walk to the PendingReveal."""
    for r in range(2, prev_round + 1):
        stage = stage_of_round(r)
        cid = next(c for c in STAGE_CARDS[stage]
                   if not get_space(state.board, c).revealed)
        state = _mark_revealed(state, cid, r)
    state = fast_replace(state, phase=Phase.PREPARATION, round_number=prev_round)
    state = _advance_until_decision(state)
    assert isinstance(state.pending_stack[-1], PendingReveal)
    return state


def _ta_state(*, fm=True, hand=()):
    state = setup(0)
    p = state.players[0]
    occs = p.occupations | {"task_artisan"} | ({CARD_ID} if fm else set())
    p = fast_replace(p, occupations=occs, hand_minors=frozenset(hand))
    state = fast_replace(state, players=(p,) + state.players[1:])
    return _reveal_pause(state, prev_round=4)


def test_task_artisan_withheld_no_playable_minor_pays_food():
    # The withheld-as-unaffordable case THROUGH THE WALK EXTENSION: no hand
    # minor -> the trigger is ineligible and would host no frame; the grant
    # condition (a quarry appeared) held and P0 owns decline income, so the
    # frame IS hosted for the decline alone and Proceed pays.
    state = _ta_state()                                # empty hand
    food0 = state.players[0].resources.food
    state = step(state, RevealCard(card="western_quarry"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == "reveal"
    assert legal_actions(state) == [Proceed()]         # nothing to fire — decline only
    state = step(state, Proceed())
    assert state.players[0].resources.food == food0 + 1
    assert state.phase is Phase.WORK


def test_task_artisan_offered_unfired_pays_food():
    # Handplow costs exactly the granted wood, so the trigger IS offered;
    # proceeding past it declines the named action -> +1 food.
    state = _ta_state(hand=("handplow",))
    food0 = state.players[0].resources.food
    state = step(state, RevealCard(card="western_quarry"))
    assert FireTrigger(card_id="task_artisan") in legal_actions(state)
    state = step(state, Proceed())
    assert state.players[0].resources.food == food0 + 1


def test_task_artisan_fired_and_played_pays_nothing():
    state = _ta_state(hand=("handplow",))
    food0 = state.players[0].resources.food
    state = step(state, RevealCard(card="western_quarry"))
    state = step(state, FireTrigger(card_id="task_artisan"))
    state = step(state, sole_play_minor(state, "handplow"))
    state = step(state, Stop())                        # pop the play-minor after-phase
    state = step(state, Proceed())                     # window exit — grant was fired
    assert state.players[0].resources.food == food0
    assert "handplow" in state.players[0].minor_improvements


def test_task_artisan_no_fm_reveals_straight_to_work():
    # Without decline income the walk extension is off: ineligible trigger,
    # no frame, no pay — the pre-ruling hosting exactly.
    state = _ta_state(fm=False)                        # empty hand
    food0 = state.players[0].resources.food
    state = step(state, RevealCard(card="western_quarry"))
    assert state.pending_stack == ()
    assert state.phase is Phase.WORK
    assert state.players[0].resources.food == food0


def test_task_artisan_non_quarry_reveal_no_frame_no_pay():
    state = _ta_state()                                # FM owned, empty hand
    food0 = state.players[0].resources.food
    reveal = next(a for a in legal_actions(state)
                  if isinstance(a, RevealCard)
                  and a.card not in ("western_quarry", "eastern_quarry"))
    state = step(state, reveal)
    assert not any(isinstance(f, PendingHarvestWindow)
                   and f.window_id == "reveal" for f in state.pending_stack)
    assert state.players[0].resources.food == food0


# --- Tree Farm Joiner (window-hosted, "minor") -------------------------------

def _tfj_prep_state(*, fm=True, scheduled=True, hand=(), grain=0):
    """A PREPARATION state about to enter round 2, with the Tree Farm Joiner
    grant (wood + named minor action) scheduled for round 2 (slot 1)."""
    state = setup(0)
    p = state.players[0]
    occs = p.occupations | {"tree_farm_joiner"} | ({CARD_ID} if fm else set())
    rewards = list(p.future_rewards)
    resources = list(p.future_resources)
    if scheduled:
        rewards[1] = FutureReward(effect_card_ids=frozenset({"tree_farm_joiner"}))
        resources[1] = resources[1] + Resources(wood=1)
    p = fast_replace(p, occupations=occs, hand_minors=frozenset(hand),
                     future_rewards=tuple(rewards),
                     future_resources=tuple(resources),
                     resources=p.resources + Resources(grain=grain))
    return fast_replace(state, players=(p,) + state.players[1:],
                        round_number=1, phase=Phase.PREPARATION)


def test_tree_farm_joiner_withheld_no_playable_minor_pays_food():
    # Scheduled round, empty hand: the trigger is ineligible (no playable
    # minor), so only the walk extension hosts the frame; Proceed pays.
    state = _tfj_prep_state()
    food0 = state.players[0].resources.food
    state = _complete_preparation(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "round_space_collection" and top.player_idx == 0
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.players[0].resources.food == food0 + 1


def test_tree_farm_joiner_offered_unfired_pays_food():
    state = _tfj_prep_state(hand=("market_stall",), grain=1)
    food0 = state.players[0].resources.food
    state = _complete_preparation(state)
    assert FireTrigger(card_id="tree_farm_joiner") in legal_actions(state)
    state = step(state, Proceed())                     # decline the named action
    assert state.players[0].resources.food == food0 + 1


def test_tree_farm_joiner_fired_and_played_pays_nothing():
    state = _tfj_prep_state(hand=("market_stall",), grain=1)
    food0 = state.players[0].resources.food
    state = _complete_preparation(state)
    state = step(state, FireTrigger(card_id="tree_farm_joiner"))
    state = step(state, sole_play_minor(state, "market_stall"))
    state = step(state, Stop())                        # pop the play-minor after-phase
    state = step(state, Proceed())                     # window exit — grant was fired
    assert state.players[0].resources.food == food0


def test_tree_farm_joiner_unscheduled_round_no_frame_no_pay():
    state = _tfj_prep_state(scheduled=False)           # FM owned, nothing due
    food0 = state.players[0].resources.food
    state = _complete_preparation(state)
    assert not any(isinstance(f, PendingHarvestWindow)
                   and f.window_id == "round_space_collection"
                   for f in state.pending_stack)
    assert state.players[0].resources.food == food0


# --- Merchant: EXCLUDED from the seam (user ruling 77 item 3, 2026-07-21) ----
# "Merchant requires the player to pay 1 food and then take the relevant
# action. I don't think declining this bundle counts as declining the action."
# Leaving the pay-and-repeat bundle unfired pays NOTHING; a FIRED repeat's
# pushed composite stays on the frames' own decline seams as before.

def test_merchant_unfired_repeat_pays_nothing():
    # A TAKEN composite whose Merchant repeat goes unfired (declined-to-fire):
    # no decline income (ruling 77 item 3).
    cs, cp = _card_state(res=Resources(clay=2, food=1), occ=("merchant",))
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, FIREPLACE_0))
    cs = step(cs, Stop())                              # pop build-major after-phase
    assert FireTrigger(card_id="merchant") in legal_actions(cs)   # repeat offered
    cs = step(cs, Stop())                              # decline-to-fire the bundle
    cs = step(cs, Stop())                              # pop the space wrapper
    assert cs.players[cp].resources.veg == 0           # no decline income
    assert cs.players[cp].resources.food == 1          # the fee was never paid


def test_merchant_repeat_withheld_unaffordable_pays_nothing():
    # 0 food: the repeat trigger is withheld (can't pay the fee) — still no
    # decline income (the bundle is not a bare grant of the named action).
    cs, cp = _card_state(res=Resources(clay=2), occ=("merchant",))
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, FIREPLACE_0))
    cs = step(cs, Stop())
    assert FireTrigger(card_id="merchant") not in legal_actions(cs)
    cs = step(cs, Stop())
    cs = step(cs, Stop())                              # pop the space wrapper
    assert cs.players[cp].resources.veg == 0


def test_merchant_fired_repeat_taken_pays_nothing():
    # Fired and TAKEN repeat: no decline anywhere, no income anywhere.
    cs, cp = _card_state(res=Resources(clay=5, food=1), occ=("merchant",))
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, FIREPLACE_0))   # 2 clay
    cs = step(cs, Stop())
    cs = step(cs, FireTrigger(card_id="merchant"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 1))             # the second Fireplace (3 clay)
    cs = step(cs, Stop())                              # pop build-major after-phase
    cs = step(cs, Stop())                              # pop the repeat composite
    cs = step(cs, Stop())                              # pop the base composite
    cs = step(cs, Stop())                              # pop the space wrapper
    assert cs.players[cp].resources.veg == 0
    assert cs.players[cp].resources.food == 0          # the fee was paid


def test_merchant_bare_minor_unfired_repeat_pays_nothing():
    # The "minor" kind: a taken named Minor Improvement action (Meeting
    # Place's minor) whose Merchant repeat goes unfired pays nothing either
    # (ruling 77 item 3 covers both of Merchant's bundles).
    cs, cp = _card_state(hand=("market_stall",), res=Resources(grain=1),
                         occ=("merchant",))
    cs = step(cs, PlaceWorker(space="meeting_place"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "market_stall"))
    cs = step(cs, Stop())                              # play frame exit: no income
    assert cs.players[cp].resources.food == 0
    cs = step(cs, Proceed())                           # minor_chosen — no MP decline
    cs = step(cs, Stop())
    assert cs.players[cp].resources.food == 0


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
