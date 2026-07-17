import agricola.cards.furniture_maker  # noqa: F401
"""Furniture Maker (occupation, deck C #116; Corbarius Expansion).

Card text: "When you play this card, you immediately get 1 wood. Each time you
play an occupation after this one, you get 1 wood for each food paid as
occupation cost."

Covered: registration (subset checks); the on-play wood through the real
Lessons flow; the self-play exclusion ("after this one" — playing Furniture
Maker itself as a food-costing second occupation grants EXACTLY the on-play
wood, no after-payout); a later 1-food occupation play pays 1 wood; a free
(0-food) play pays nothing; the Roof Ballaster scoping pin (the play-variant
SURCHARGE is an effect price, not occupation cost — wood equals the occupation
cost's food only); opponent plays never fire; hand-only inert.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_current_player,
    with_pending_stack,
    with_resources,
    with_space,
)

_POOL = CardPool(
    occupations=("furniture_maker", "consultant", "roof_ballaster")
    + tuple(f"o{i}" for i in range(20)),
    minors=("forest_school",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=3):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    # Drop both hands so plays come only from what a test grants explicitly.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _edit_player(state, idx, **kwargs):
    p = fast_replace(state.players[idx], **kwargs)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_hand_occ(state, idx, card_id):
    return _edit_player(
        state, idx,
        hand_occupations=state.players[idx].hand_occupations | {card_id})


def _give_tableau_occ(state, idx, card_id):
    """Put an occupation directly in the tableau (raises the Lessons ramp)."""
    return _edit_player(
        state, idx, occupations=state.players[idx].occupations | {card_id})


def _play_occupation(cs, idx, card_id, variant=None):
    """Drive the real Lessons -> play-occupation flow for player `idx`."""
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=card_id, variant=variant))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_furniture_maker_registered():
    assert "furniture_maker" in OCCUPATIONS
    # Subset checks, never exact-set.
    assert any(e.card_id == "furniture_maker" and not e.any_player
               for e in AUTO_EFFECTS["after_play_occupation"])


# ---------------------------------------------------------------------------
# On-play + the self-play exclusion ("after this one")
# ---------------------------------------------------------------------------

def test_on_play_grants_one_wood_first_free_play():
    # First Lessons occupation is free (cost 0): the on-play wood arrives,
    # and there is trivially nothing for the recurring clause to pay.
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "furniture_maker")
    cs = with_resources(cs, 0, food=5)          # wood 0 — clean counting
    cs = _play_occupation(cs, 0, "furniture_maker")
    assert "furniture_maker" in cs.players[0].occupations
    assert cs.players[0].resources.wood == 1    # the on-play only
    assert cs.players[0].resources.food == 5    # free first play


def test_own_food_costing_play_pays_no_second_wood():
    # Furniture Maker played as the SECOND occupation costs 1 food, so the
    # self-exclusion is load-bearing: without the played_card_id guard the
    # deferred after-flip (card already in the tableau) would pay a 2nd wood.
    cs = _card_state()
    cs = _give_tableau_occ(cs, 0, "o0")         # ramp: next play costs 1 food
    cs = _give_hand_occ(cs, 0, "furniture_maker")
    cs = with_resources(cs, 0, food=5)
    cs = _play_occupation(cs, 0, "furniture_maker")
    assert cs.players[0].resources.food == 4    # the 1-food occupation cost
    assert cs.players[0].resources.wood == 1    # EXACTLY the on-play wood


# ---------------------------------------------------------------------------
# Later occupation plays: 1 wood per food of the occupation cost
# ---------------------------------------------------------------------------

def test_later_one_food_play_pays_one_wood():
    cs = _card_state()
    cs = _give_tableau_occ(cs, 0, "furniture_maker")
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = with_resources(cs, 0, food=5)
    cs = _play_occupation(cs, 0, "consultant")
    assert "consultant" in cs.players[0].occupations
    assert cs.players[0].resources.food == 4    # the Lessons ramp's 1 food
    assert cs.players[0].resources.wood == 1    # 1 wood per food paid
    assert cs.players[0].resources.clay == 3    # consultant's own effect ran


def test_free_play_pays_nothing():
    # A 0-food occupation cost pays no wood. No Lessons route is free once
    # Furniture Maker is in the tableau (it raises the ramp itself), so the
    # free play is constructed directly on the play-occupation host.
    cs = _card_state()
    cs = _give_tableau_occ(cs, 0, "furniture_maker")
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = with_resources(cs, 0)                  # no food, no wood
    cs = with_pending_stack(cs, (PendingPlayOccupation(
        player_idx=0, initiated_by_id="test:free_play", cost=Resources()),))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    assert "consultant" in cs.players[0].occupations
    assert cs.players[0].resources.wood == 0    # nothing paid, nothing earned


# ---------------------------------------------------------------------------
# The scoping pin: a play-variant SURCHARGE is not "occupation cost"
# ---------------------------------------------------------------------------

def test_roof_ballaster_surcharge_adds_no_wood():
    # Roof Ballaster's "pay" variant charges 1 food ON TOP of the 1-food
    # occupation cost (2 food debited in all), but the surcharge is an effect
    # price, not occupation cost — the payout counts the occupation cost only.
    cs = _card_state()
    cs = _give_tableau_occ(cs, 0, "furniture_maker")
    cs = _give_hand_occ(cs, 0, "roof_ballaster")
    cs = with_resources(cs, 0, food=5)
    cs = with_current_player(cs, 0)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    pay = [a for a in legal_actions(cs)
           if isinstance(a, CommitPlayOccupation)
           and a.card_id == "roof_ballaster" and a.variant == "pay"]
    assert len(pay) == 1
    cs = step(cs, pay[0])
    assert cs.players[0].resources.food == 3    # 1 occupation cost + 1 surcharge
    assert cs.players[0].resources.stone == 2   # the variant ran (2 rooms)
    assert cs.players[0].resources.wood == 1    # occupation cost's food ONLY


# ---------------------------------------------------------------------------
# Scoping: own plays only; hand-only inert
# ---------------------------------------------------------------------------

def test_opponents_play_never_fires():
    cs = _card_state()
    cs = _give_tableau_occ(cs, 0, "furniture_maker")
    cs = _give_tableau_occ(cs, 1, "o1")         # opponent's play costs 1 food
    cs = _give_hand_occ(cs, 1, "consultant")
    cs = with_resources(cs, 0, food=5)
    cs = with_resources(cs, 1, food=5)
    cs = _play_occupation(cs, 1, "consultant")
    assert "consultant" in cs.players[1].occupations
    assert cs.players[1].resources.food == 4    # the opponent paid the food
    assert cs.players[0].resources.wood == 0    # owner got nothing
    assert cs.players[1].resources.wood == 0    # non-owner got nothing


def test_hand_only_furniture_maker_is_inert():
    cs = _card_state()
    cs = _give_hand_occ(cs, 0, "furniture_maker")   # in hand, never played
    cs = _give_tableau_occ(cs, 0, "o0")             # ramp: play costs 1 food
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = with_resources(cs, 0, food=5)
    cs = _play_occupation(cs, 0, "consultant")
    assert cs.players[0].resources.food == 4
    assert cs.players[0].resources.wood == 0


# ---------------------------------------------------------------------------
# Consecutive later plays: each food-costing play pays again (no once-per latch)
# ---------------------------------------------------------------------------

def test_each_later_play_pays_again():
    cs = _card_state()
    cs = _give_tableau_occ(cs, 0, "furniture_maker")
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = _give_hand_occ(cs, 0, "o0")            # unimplemented — never offered
    cs = with_resources(cs, 0, food=5)
    cs = _play_occupation(cs, 0, "consultant")
    cs = step(cs, Stop())                       # pop the play-occupation host
    cs = _give_hand_occ(cs, 0, "roof_ballaster")
    cs = _play_occupation(cs, 0, "roof_ballaster", variant="decline")
    assert cs.players[0].resources.food == 3    # 1 food per play, no surcharge
    assert cs.players[0].resources.wood == 2    # 1 wood per food-costing play


def test_forest_school_substituted_food_pays_no_wood():
    """User ruling 2026-07-15: food replaced with wood by Forest School is paid
    in WOOD, not food, so Furniture Maker grants nothing for that play."""
    import agricola.cards.forest_school  # noqa: F401
    cs = _card_state()
    cs = _give_tableau_occ(cs, 0, "furniture_maker")
    cs = _edit_player(cs, 0,
                      minor_improvements=cs.players[0].minor_improvements | {"forest_school"})
    cs = _give_hand_occ(cs, 0, "consultant")
    # 0 food + 1 wood: the 1-food occupation cost is payable ONLY by firing
    # Forest School (wood -> food), forcing the substitution path.
    cs = with_resources(cs, 0, wood=1, food=0)
    cs = with_current_player(cs, 0)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    # Before the play, the commit is withheld (food short) — fire Forest School
    # (a play-variant trigger since ruling 65: variant = the replacement count k).
    assert FireTrigger(card_id="forest_school", variant="1") in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id="forest_school", variant="1"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))

    assert "consultant" in cs.players[0].occupations
    assert cs.players[0].resources.food == 0    # 1 produced from wood, 1 paid
    # Wood: started 1, Forest School spent it, Furniture Maker granted 0.
    assert cs.players[0].resources.wood == 0
