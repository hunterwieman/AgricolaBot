import agricola.cards.education_bonus  # noqa: F401  (registers the card)
"""Education Bonus (minor improvement, D42; Consul Dirigens; cost 1 food).

Card text: "After you play your 1st/2nd/3rd/4th/5th/6th occupation this game, you
immediately get 1 grain/clay/reed/stone/vegetable/field (not retroactively)."
Prerequisite: "2 Improvements" (minors + owned majors).

The first five rewards are pure goods (mandatory automatic effects on
`after_play_occupation`); the sixth is "1 field" — a free, declinable plow surfaced
as an optional FireTrigger that pushes the PendingPlow primitive. The good is keyed
to the GAME-TOTAL occupation count, and the hook fires only on the ACT of playing an
occupation while the card is owned ("not retroactively").

These tests drive the real Lessons -> play-occupation flow (no direct frame pokes)
so the firing points are exercised end-to-end.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_majors, with_space

# Six clean filler occupations: each has a no-op on_play and registers no
# hook/trigger/auto, so playing them changes only the lifetime occupation count
# (no stray resource grants of their own to pollute the reward assertions).
_FILLERS = (
    "bricklayer",
    "carpenter",
    "clay_plasterer",
    "conservator",
    "frame_builder",
    "master_bricklayer",
)

_POOL = CardPool(
    occupations=_FILLERS + tuple(f"o{i}" for i in range(20)),
    minors=("education_bonus",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    # Drop both hands so deterministic plays come only from what a test grants.
    # Give player 0 ample food: playing occupations via Lessons costs 1 food each
    # after the first, and a food shortfall would detour through PendingFoodPayment
    # (an unrelated mechanic) — the food bank keeps the play flow clean. Food is not
    # one of the rewards, so it never confounds the grain/clay/reed/stone/veg checks.
    p0 = fast_replace(
        cs.players[0],
        hand_occupations=frozenset(),
        hand_minors=frozenset(),
        resources=fast_replace(cs.players[0].resources, food=10),
    )
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _give_hand_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _play_occupation(cs, idx, card_id):
    """Drive the real Lessons -> play-occupation flow for player `idx`.

    Stops short of popping the play-occupation host's after-phase, so the caller
    can inspect any after-phase FireTriggers. Use `_play_and_finish` to also pop.
    """
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=card_id))
    return cs


def _play_and_finish(cs, idx, card_id):
    """Play an occupation and pop both the after-phase and the Lessons host."""
    cs = _play_occupation(cs, idx, card_id)
    cs = step(cs, Stop())   # pop the play-occupation host's after-phase
    cs = step(cs, Stop())   # pop the Lessons host frame
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_education_bonus_registered():
    assert "education_bonus" in MINORS
    spec = MINORS["education_bonus"]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    # The goods rewards are mandatory automatic effects on after_play_occupation.
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("after_play_occupation", ())}
    assert "education_bonus" in auto_ids
    # The 6th "field" reward is an optional (declinable) trigger on the same event.
    trig_ids = {e.card_id for e in TRIGGERS.get("after_play_occupation", ())}
    assert "education_bonus" in trig_ids


# ---------------------------------------------------------------------------
# Prerequisite: 2 Improvements (minors + owned majors)
# ---------------------------------------------------------------------------

def test_prereq_needs_two_improvements():
    spec = MINORS["education_bonus"]
    cs = _card_state()
    # 0 improvements -> unmet.
    assert not prereq_met(spec, cs, 0)
    # 1 minor improvement -> still unmet.
    p = fast_replace(cs.players[0], minor_improvements=frozenset({"m1"}))
    cs1 = fast_replace(cs, players=tuple(p if i == 0 else cs.players[i] for i in range(2)))
    assert not prereq_met(spec, cs1, 0)
    # 2 minor improvements -> met.
    p = fast_replace(cs.players[0], minor_improvements=frozenset({"m1", "m2"}))
    cs2 = fast_replace(cs, players=tuple(p if i == 0 else cs.players[i] for i in range(2)))
    assert prereq_met(spec, cs2, 0)


def test_prereq_counts_minors_and_majors_together():
    spec = MINORS["education_bonus"]
    cs = _card_state()
    # 1 minor + 1 owned major = 2 improvements -> met.
    p = fast_replace(cs.players[0], minor_improvements=frozenset({"m1"}))
    cs = fast_replace(cs, players=tuple(p if i == 0 else cs.players[i] for i in range(2)))
    cs = with_majors(cs, owner_by_idx={0: 0})   # owns a Fireplace
    assert prereq_met(spec, cs, 0)


def test_prereq_ignores_opponent_improvements():
    spec = MINORS["education_bonus"]
    cs = _card_state()
    # Opponent owns two improvements; player 0 owns none -> prereq fails for 0.
    p1 = fast_replace(cs.players[1], minor_improvements=frozenset({"m1", "m2"}))
    cs = fast_replace(cs, players=(cs.players[0], p1))
    assert not prereq_met(spec, cs, 0)


# ---------------------------------------------------------------------------
# The good reward is keyed to the 1st..5th occupation, in order
# ---------------------------------------------------------------------------

def test_rewards_track_occupation_count_in_order():
    cs = _card_state()
    cs = _own_minor(cs, 0, "education_bonus")
    for cid in _FILLERS:
        cs = _give_hand_occ(cs, 0, cid)

    r0 = cs.players[0].resources

    # 1st occupation -> +1 grain.
    cs = _play_and_finish(cs, 0, _FILLERS[0])
    r = cs.players[0].resources
    assert r.grain == r0.grain + 1
    assert (r.clay, r.reed, r.stone, r.veg) == (r0.clay, r0.reed, r0.stone, r0.veg)

    # 2nd occupation -> +1 clay (cumulative).
    cs = _play_and_finish(cs, 0, _FILLERS[1])
    r = cs.players[0].resources
    assert (r.grain, r.clay) == (r0.grain + 1, r0.clay + 1)
    assert (r.reed, r.stone, r.veg) == (r0.reed, r0.stone, r0.veg)

    # 3rd occupation -> +1 reed.
    cs = _play_and_finish(cs, 0, _FILLERS[2])
    r = cs.players[0].resources
    assert (r.grain, r.clay, r.reed) == (r0.grain + 1, r0.clay + 1, r0.reed + 1)
    assert (r.stone, r.veg) == (r0.stone, r0.veg)

    # 4th occupation -> +1 stone.
    cs = _play_and_finish(cs, 0, _FILLERS[3])
    r = cs.players[0].resources
    assert (r.grain, r.clay, r.reed, r.stone) == (
        r0.grain + 1, r0.clay + 1, r0.reed + 1, r0.stone + 1)
    assert r.veg == r0.veg

    # 5th occupation -> +1 veg.
    cs = _play_and_finish(cs, 0, _FILLERS[4])
    r = cs.players[0].resources
    assert (r.grain, r.clay, r.reed, r.stone, r.veg) == (
        r0.grain + 1, r0.clay + 1, r0.reed + 1, r0.stone + 1, r0.veg + 1)
    assert len(cs.players[0].occupations) == 5


def test_goods_grant_is_choiceless_no_firetrigger_for_first_five():
    # Playing the 1st occupation grants grain automatically; the optional
    # FireTrigger (the field grant) is NOT surfaced (it only arms on the 6th).
    cs = _card_state()
    cs = _own_minor(cs, 0, "education_bonus")
    cs = _give_hand_occ(cs, 0, _FILLERS[0])
    cs = _play_occupation(cs, 0, _FILLERS[0])   # leaves the after-phase open
    assert FireTrigger(card_id="education_bonus") not in legal_actions(cs)


# ---------------------------------------------------------------------------
# "not retroactively": only occupations played WHILE owned grant a reward,
# but the reward is keyed to the lifetime total
# ---------------------------------------------------------------------------

def test_not_retroactive_but_keyed_to_lifetime_count():
    # Two occupations already in the tableau (played before the card was owned);
    # the card is now owned; playing the 3rd occupation grants the 3rd reward
    # (reed), NOT the 1st (grain), and the earlier two grant nothing now.
    cs = _card_state()
    cs = _own_minor(cs, 0, "education_bonus")
    p = fast_replace(cs.players[0], occupations=frozenset({"x0", "x1"}))
    cs = fast_replace(cs, players=tuple(p if i == 0 else cs.players[i] for i in range(2)))
    cs = _give_hand_occ(cs, 0, _FILLERS[0])
    r0 = cs.players[0].resources

    cs = _play_and_finish(cs, 0, _FILLERS[0])   # the 3rd lifetime occupation
    r = cs.players[0].resources
    assert r.reed == r0.reed + 1                  # 3rd reward = reed
    assert (r.grain, r.clay, r.stone, r.veg) == (r0.grain, r0.clay, r0.stone, r0.veg)


# ---------------------------------------------------------------------------
# 6th occupation: "1 field" = an optional, declinable plow
# ---------------------------------------------------------------------------

def _at_sixth(cs):
    """Own the card with 5 occupations already played; hand has a 6th to play."""
    cs = _own_minor(cs, 0, "education_bonus")
    p = fast_replace(cs.players[0], occupations=frozenset(f"x{i}" for i in range(5)))
    cs = fast_replace(cs, players=tuple(p if i == 0 else cs.players[i] for i in range(2)))
    cs = _give_hand_occ(cs, 0, _FILLERS[0])
    return cs


def test_sixth_occupation_offers_optional_plow():
    cs = _card_state()
    cs = _at_sixth(cs)
    fields0 = sum(
        1 for row in cs.players[0].farmyard.grid for cell in row
        if cell.cell_type.name == "FIELD"
    )

    cs = _play_occupation(cs, 0, _FILLERS[0])   # 6th lifetime occupation
    # The field reward is OPTIONAL: a FireTrigger is surfaced (declinable), and
    # Stop (decline) is available alongside it.
    acts = legal_actions(cs)
    assert FireTrigger(card_id="education_bonus") in acts
    assert Stop() in acts

    # Fire it -> a PendingPlow is pushed; commit a plow on the legal cell.
    cs = step(cs, FireTrigger(card_id="education_bonus"))
    plow_actions = [a for a in legal_actions(cs) if isinstance(a, CommitPlow)]
    assert plow_actions, "firing the field grant should offer a plow"
    cs = step(cs, plow_actions[0])

    fields1 = sum(
        1 for row in cs.players[0].farmyard.grid for cell in row
        if cell.cell_type.name == "FIELD"
    )
    assert fields1 == fields0 + 1   # one new field plowed


def test_sixth_occupation_plow_is_declinable():
    cs = _card_state()
    cs = _at_sixth(cs)
    fields0 = sum(
        1 for row in cs.players[0].farmyard.grid for cell in row
        if cell.cell_type.name == "FIELD"
    )

    cs = _play_occupation(cs, 0, _FILLERS[0])   # 6th lifetime occupation
    # Decline the plow by Stopping out of the after-phase.
    cs = step(cs, Stop())   # pop the play-occupation host's after-phase
    cs = step(cs, Stop())   # pop the Lessons host frame

    fields1 = sum(
        1 for row in cs.players[0].farmyard.grid for cell in row
        if cell.cell_type.name == "FIELD"
    )
    assert fields1 == fields0   # no field plowed (declined)


def test_sixth_trigger_fires_once_per_play():
    # After firing the field grant once, it is recorded in triggers_resolved and
    # is not offered again within the same occupation play.
    cs = _card_state()
    cs = _at_sixth(cs)
    cs = _play_occupation(cs, 0, _FILLERS[0])
    cs = step(cs, FireTrigger(card_id="education_bonus"))
    plow_actions = [a for a in legal_actions(cs) if isinstance(a, CommitPlow)]
    cs = step(cs, plow_actions[0])
    # Back in the after-phase: the field grant must not re-arm.
    assert FireTrigger(card_id="education_bonus") not in legal_actions(cs)


# ---------------------------------------------------------------------------
# Scoping: owner + own-action only
# ---------------------------------------------------------------------------

def test_does_not_fire_when_unowned():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, _FILLERS[0])   # owns no Education Bonus
    r0 = cs.players[0].resources
    cs = _play_and_finish(cs, 0, _FILLERS[0])
    r = cs.players[0].resources
    assert (r.grain, r.clay, r.reed, r.stone, r.veg) == (
        r0.grain, r0.clay, r0.reed, r0.stone, r0.veg)


def test_does_not_fire_on_opponents_play():
    # Player 0 owns Education Bonus; player 1 plays an occupation -> 0 gets nothing.
    cs = _card_state()
    cs = _own_minor(cs, 0, "education_bonus")
    cs = _give_hand_occ(cs, 1, _FILLERS[0])
    r0_p0 = cs.players[0].resources
    cs = _play_and_finish(cs, 1, _FILLERS[0])
    assert _FILLERS[0] in cs.players[1].occupations
    r_p0 = cs.players[0].resources
    assert (r_p0.grain, r_p0.clay, r_p0.reed, r_p0.stone, r_p0.veg) == (
        r0_p0.grain, r0_p0.clay, r0_p0.reed, r0_p0.stone, r0_p0.veg)
