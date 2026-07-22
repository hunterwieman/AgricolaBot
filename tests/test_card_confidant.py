"""Tests for Confidant (occupation, B93; Bubulcus Expansion).

Card text (verbatim): "Place 1 food from your supply on each of the next 2, 3, or 4
round spaces. At the start of these rounds, you get the food back and your choice of a
'sow' or 'Build Fences' action."
Clarification: "For example, if played in Round 9, you must place 1 food on each of
Rounds 10-11, 10-12, or 10-13."

Governing ruling 74 (2026-07-21). Verified here: registration (occupation + the
play-variant + the play-variant-trigger + the round_space_collection trigger); the
real-Lessons play flow (pick N -> N food debited, 1 food + the effect scheduled onto each
of the next N round spaces); the near-end dedupe + affordability gate; the food coming
back at round start; the round-start grant (both named-action routes offered when legal;
fire 'sow' -> a full PendingSow; fire 'build_fences' -> the literal PendingBuildFences;
Proceed declines); route eligibility boundaries; the grant firing on EACH scheduled round;
and the FLAGGED Lessons dead-end when a sole, unaffordable Confidant is the only playable
hand occupation.
"""
import agricola.cards.confidant  # noqa: F401

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
)
from agricola.cards.confidant import _placement_counts, _variants
from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBuildFences,
    PendingHarvestWindow,
    PendingPlayOccupation,
    PendingSow,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from agricola.constants import CellType

CARD_ID = "confidant"
_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _cards_state(seed=5, *, food=0, grain=0, wood=0, hand=(CARD_ID,)):
    """A card-mode round-1 WORK state: the given occupations in the current player's
    hand, resources set explicitly."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    cs = _edit_player(cs, cp,
                      hand_occupations=frozenset(hand),
                      resources=fast_replace(cs.players[cp].resources,
                                             food=food, grain=grain, wood=wood))
    return cs, cp


def _at_play_host(cs):
    """Walk a real Lessons placement to the PendingPlayOccupation host."""
    cs = step(cs, PlaceWorker(space="lessons"))
    return step(cs, ChooseSubAction(name="play_occupation"))


def _confidant_plays(cs):
    return sorted(a.variant for a in legal_actions(cs)
                  if isinstance(a, CommitPlayOccupation) and a.card_id == CARD_ID)


def _prep_state(idx=0, prev_round=1, *, effect_rounds=(), food_rounds=(),
                food=0, grain=0, wood=0, fields=()):
    """A PREPARATION state (round `prev_round`, about to enter prev_round+1) where player
    `idx` owns Confidant, with the effect grant scheduled on `effect_rounds`, 1 food
    scheduled on each of `food_rounds`, resources set, and `fields` plowed to empty
    FIELDs (so a sow can be legal)."""
    cs, _env = setup_env(0, card_pool=_POOL)
    p = cs.players[idx]
    rewards = list(p.future_rewards)
    for rnd in effect_rounds:
        rewards[rnd - 1] = fast_replace(
            rewards[rnd - 1],
            effect_card_ids=rewards[rnd - 1].effect_card_ids | {CARD_ID})
    resources_sched = list(p.future_resources)
    for rnd in food_rounds:
        resources_sched[rnd - 1] = resources_sched[rnd - 1] + Resources(food=1)
    grid = [list(row) for row in p.farmyard.grid]
    for (r, c) in fields:
        grid[r][c] = Cell(cell_type=CellType.FIELD)
    p = fast_replace(
        p,
        occupations=p.occupations | {CARD_ID},
        future_rewards=tuple(rewards),
        future_resources=tuple(resources_sched),
        resources=fast_replace(p.resources, food=food, grain=grain, wood=wood),
        farmyard=fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid)),
    )
    cs = fast_replace(
        cs, players=tuple(p if i == idx else cs.players[i] for i in range(2)),
        round_number=prev_round, phase=Phase.PREPARATION)
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_OCCUPATION_VARIANTS                 # the N-choice at play
    assert CARD_ID in PLAY_VARIANT_TRIGGERS                    # the sow/build_fences routes
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("round_space_collection", [])}


# ---------------------------------------------------------------------------
# The N-choice: near-end dedupe + affordability gate (pure)
# ---------------------------------------------------------------------------

def test_near_end_placement_counts():
    # R=9 (the printed clarification): 2/3/4 -> rounds 10-11, 10-12, 10-13.
    assert _placement_counts(9) == [2, 3, 4]
    assert _placement_counts(10) == [2, 3, 4]
    assert _placement_counts(11) == [2, 3]     # N=3 and N=4 collapse to 3 remaining
    assert _placement_counts(12) == [2]        # all collapse to 2 remaining
    assert _placement_counts(13) == [1]        # 1 remaining (flagged: <2 allowed)
    assert _placement_counts(14) == [0]        # 0 remaining (flagged: <2 allowed)


def test_variants_gated_on_raw_food_with_surcharge():
    # A play route per distinct count c the player can afford (raw food >= c), each with
    # a food surcharge of c.
    cs, cp = _cards_state(food=4)              # R=1 -> counts {2,3,4}
    assert _variants(cs, cp) == [
        ("place_2", Resources(food=2)),
        ("place_3", Resources(food=3)),
        ("place_4", Resources(food=4)),
    ]
    cs, cp = _cards_state(food=2)
    assert _variants(cs, cp) == [("place_2", Resources(food=2))]
    cs, cp = _cards_state(food=1)              # cannot afford even the minimum (2) placement
    assert _variants(cs, cp) == []


def test_near_end_play_allowed_FLAGGED():
    # FLAGGED reading (module docstring / session report): the printed "2, 3, or 4" is
    # treated as capped by the rounds remaining, so Confidant is ALLOWED with fewer than 2
    # round spaces left — round 13 places on 1, round 14 places on 0 (a free, inert play).
    # This documents that lean; the alternative reading would forbid the play entirely in
    # rounds 13-14. Awaiting the user's ruling.
    cs, cp = _cards_state(food=5)
    assert _variants(fast_replace(cs, round_number=13), cp) == [
        ("place_1", Resources(food=1))]
    assert _variants(fast_replace(cs, round_number=14), cp) == [
        ("place_0", Resources())]


# ---------------------------------------------------------------------------
# The play flow — a real Lessons placement mid-game
# ---------------------------------------------------------------------------

def test_real_lessons_play_debits_and_schedules():
    # Pick N=3: 3 food debited, and 1 food + the effect scheduled onto each of the next
    # 3 round spaces (rounds 2,3,4 = slots 1,2,3).
    cs, cp = _cards_state(food=5)
    cs = _at_play_host(cs)
    assert _confidant_plays(cs) == ["place_2", "place_3", "place_4"]
    cs = step(cs, CommitPlayOccupation(card_id=CARD_ID, variant="place_3"))
    p = cs.players[cp]
    assert CARD_ID in p.occupations
    assert p.resources.food == 2                              # 5 - 3 surcharge
    assert [p.future_resources[s].food for s in range(5)] == [0, 1, 1, 1, 0]
    assert [i for i, fr in enumerate(p.future_rewards)
            if CARD_ID in fr.effect_card_ids] == [1, 2, 3]


def test_real_lessons_affordability_limits_variants():
    # food < N -> that variant is not offered (real enumerator).
    cs, _ = _cards_state(food=2)
    assert _confidant_plays(_at_play_host(cs)) == ["place_2"]
    cs, _ = _cards_state(food=3)
    assert _confidant_plays(_at_play_host(cs)) == ["place_2", "place_3"]


def test_lessons_not_offered_when_sole_confidant_unaffordable():
    # Confidant's placement is MANDATORY (no decline variant), so an unaffordable Confidant
    # yields NO play commit. When it is the ONLY playable hand occupation, the Lessons
    # placement gate must NOT offer the space — otherwise the pushed PendingPlayOccupation
    # would be an empty-legal-set dead-end. The ruling-74 follow-up fix
    # (`_any_occupation_committable`, which mirrors the play-occupation enumerator's
    # per-variant filter) closes it: with 0 food the minimum 2-food placement is
    # unaffordable, so Lessons is withheld; with 2 food it is offered again.
    cs, _ = _cards_state(food=0)               # 1st occupation free, but surcharge >= 2 food
    assert PlaceWorker(space="lessons") not in legal_actions(cs)
    cs2, _ = _cards_state(food=2)
    assert PlaceWorker(space="lessons") in legal_actions(cs2)


# ---------------------------------------------------------------------------
# The food comes back at round start
# ---------------------------------------------------------------------------

def test_food_returns_at_scheduled_round_start():
    # 1 food scheduled onto the entered round (round 2) is collected at that round's start.
    cs = _prep_state(prev_round=1, food_rounds=(2,), food=0)
    before = cs.players[0].resources.food
    cs = _complete_preparation(cs)
    assert cs.round_number == 2
    assert cs.players[0].resources.food == before + 1


# ---------------------------------------------------------------------------
# The round-start grant at round_space_collection
# ---------------------------------------------------------------------------

def test_grant_offers_both_routes_when_legal():
    # Effect scheduled on the entered round, a sowable field + grain, and wood for a fence
    # -> both named-action routes surface as play-variant FireTriggers, plus Proceed.
    cs = _prep_state(prev_round=1, effect_rounds=(2,),
                     grain=1, wood=15, fields=[(0, 4)])
    cs = _complete_preparation(cs)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "round_space_collection" and top.player_idx == 0
    assert cs.phase is Phase.PREPARATION        # the ladder is paused at the window
    la = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID, variant="sow") in la
    assert FireTrigger(card_id=CARD_ID, variant="build_fences") in la
    assert Proceed() in la                       # the decline


def test_fire_sow_pushes_full_named_sow():
    cs = _prep_state(prev_round=1, effect_rounds=(2,),
                     grain=1, wood=15, fields=[(0, 4)])
    cs = _complete_preparation(cs)
    cs2 = step(cs, FireTrigger(card_id=CARD_ID, variant="sow"))
    top = cs2.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert top.max_fields == 0                   # the full, uncapped "Sow" action
    assert top.initiated_by_id == "card:confidant"
    # The grant is consumed on fire (removed from this round's slot).
    assert CARD_ID not in cs2.players[0].future_rewards[2 - 1].effect_card_ids


def test_fire_fences_pushes_literal_build_fences():
    cs = _prep_state(prev_round=1, effect_rounds=(2,),
                     grain=1, wood=15, fields=[(0, 4)])
    cs = _complete_preparation(cs)
    cs2 = step(cs, FireTrigger(card_id=CARD_ID, variant="build_fences"))
    top = cs2.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.build_fences_action is True       # the literal Build Fences action
    assert top.initiated_by_id == "card:confidant"
    assert CARD_ID not in cs2.players[0].future_rewards[2 - 1].effect_card_ids


def test_proceed_declines_the_grant():
    cs = _prep_state(prev_round=1, effect_rounds=(2,),
                     grain=1, wood=15, fields=[(0, 4)])
    cs = _complete_preparation(cs)
    cs2 = step(cs, Proceed())
    assert all(not isinstance(f, (PendingSow, PendingBuildFences))
               for f in cs2.pending_stack)
    # Declining does NOT push either named action; the round proceeds to work.


# ---------------------------------------------------------------------------
# Route eligibility — never a dead-end
# ---------------------------------------------------------------------------

def test_sow_route_withheld_when_no_sowable_field():
    # Wood for a fence but no empty field (and no grain) -> only build_fences is offered.
    cs = _prep_state(prev_round=1, effect_rounds=(2,), wood=15)   # no field, no grain
    cs = _complete_preparation(cs)
    la = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID, variant="build_fences") in la
    assert FireTrigger(card_id=CARD_ID, variant="sow") not in la


def test_fences_route_withheld_when_no_wood():
    # A sowable field + grain but 0 wood -> no legal pasture commit -> only sow is offered.
    cs = _prep_state(prev_round=1, effect_rounds=(2,),
                     grain=1, wood=0, fields=[(0, 4)])
    cs = _complete_preparation(cs)
    la = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID, variant="sow") in la
    assert FireTrigger(card_id=CARD_ID, variant="build_fences") not in la


def test_no_frame_when_neither_route_legal():
    # Scheduled but neither route is doable (no field/grain, no wood) -> no window frame is
    # pushed at all, and the ladder runs straight to WORK.
    cs = _prep_state(prev_round=1, effect_rounds=(2,))
    cs = _complete_preparation(cs)
    assert cs.pending_stack == ()
    assert cs.phase is Phase.WORK
    assert FireTrigger(card_id=CARD_ID, variant="sow") not in legal_actions(cs)


def test_no_frame_on_unscheduled_round():
    # Owning Confidant but with NO grant scheduled this round -> no window frame (the
    # eligibility is the schedule slot, not ownership).
    cs = _prep_state(prev_round=1, grain=1, wood=15, fields=[(0, 4)])  # no effect_rounds
    cs = _complete_preparation(cs)
    assert cs.pending_stack == ()
    assert cs.phase is Phase.WORK


# ---------------------------------------------------------------------------
# The grant fires on EACH scheduled round
# ---------------------------------------------------------------------------

def test_grant_offered_on_each_scheduled_round():
    # A grant scheduled on rounds 2, 3, and 4 is offered on each of them (one window per
    # round), not just the first.
    for entered in (2, 3, 4):
        cs = _prep_state(prev_round=entered - 1, effect_rounds=(entered,),
                         grain=1, wood=15, fields=[(0, 4)])
        cs = _complete_preparation(cs)
        assert cs.round_number == entered
        top = cs.pending_stack[-1]
        assert isinstance(top, PendingHarvestWindow)
        assert top.window_id == "round_space_collection"
        assert FireTrigger(card_id=CARD_ID, variant="sow") in legal_actions(cs)


def test_fire_consumes_only_this_rounds_slot():
    # Firing the round-2 grant consumes ONLY round 2's slot; rounds 3 and 4 stay scheduled
    # so their own windows still fire later.
    cs = _prep_state(prev_round=1, effect_rounds=(2, 3, 4),
                     grain=1, wood=15, fields=[(0, 4)])
    cs = _complete_preparation(cs)
    cs2 = step(cs, FireTrigger(card_id=CARD_ID, variant="sow"))
    fr = cs2.players[0].future_rewards
    assert CARD_ID not in fr[2 - 1].effect_card_ids
    assert CARD_ID in fr[3 - 1].effect_card_ids
    assert CARD_ID in fr[4 - 1].effect_card_ids
