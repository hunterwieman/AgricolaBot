"""Tests for Bookshelf (minor improvement D49): a MANDATORY, unconditional
`before_play_occupation` automatic effect — each time you play an occupation, BEFORE its cost
is paid, you get 3 food. It is ALSO an occupation-cost food source (the 3 free food is usable
for the play cost). Covers: registration (minor spec, auto, food source); the 3-food grant
landing automatically at frame-push (before the cost debit); banking surplus over the cost;
firing on EVERY occupation play (scoping); and the Lessons-gate offering a play payable only
via Bookshelf's 3 food. The auto is choiceless, so there is no FireTrigger / decline path.
"""
import agricola.cards.bookshelf  # noqa: F401

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
)
from agricola.cards.specs import MINORS, OCCUPATION_FOOD_SOURCES
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

# The committed cards in the tests must be REAL registered occupations (committing one calls
# OCCUPATIONS[cid].on_play): childless / soldier / stable_architect / priest / consultant all have
# pending-free on_play effects (or none), so the play flow stays a single CommitPlayOccupation.
# The `o{i}` fillers only pad the pool to the >= 2*HAND_SIZE deal requirement; every test
# overwrites the dealt hands via fast_replace, so the fillers are never actually played.
_OCCS = ("priest", "stable_architect", "consultant", "childless", "soldier") \
    + tuple(f"o{i}" for i in range(20))
_POOL = CardPool(
    occupations=_OCCS,
    minors=("bookshelf",) + tuple(f"m{i}" for i in range(20)),
)


def _state(*, owned_minors=("bookshelf",), owned_occ=("priest", "stable_architect", "consultant"),
           hand=("childless",), food=0, wood=0):
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=frozenset(owned_occ),
                     minor_improvements=frozenset(owned_minors),
                     hand_occupations=frozenset(hand),
                     resources=Resources(food=food, wood=wood))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _spaces(cs):
    return {a.space for a in legal_placements(cs)}


def _to_play_occupation(cs):
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    return cs


# --------------------------------------------------------------------------- registration

def test_bookshelf_registered():
    spec = MINORS["bookshelf"]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.min_occupations == 3
    assert spec.vps == 1
    assert "bookshelf" in OCCUPATION_FOOD_SOURCES
    assert any(e.card_id == "bookshelf" for e in AUTO_EFFECTS.get("before_play_occupation", []))


# --------------------------------------------------------------------------- the auto effect

def test_food_lands_automatically_at_frame_push():
    # Own Bookshelf, play a later occupation. The 3 food must appear automatically (no
    # FireTrigger step) the instant the play-occupation frame is pushed.
    cs, cp = _state(food=0, wood=0)
    assert cs.players[cp].resources.food == 0
    cs = _to_play_occupation(cs)
    assert cs.players[cp].resources.food == 3          # 0 + 3, granted before the cost is paid


def test_no_firetrigger_for_mandatory_auto():
    # The grant is mandatory/choiceless: it never surfaces a FireTrigger and never blocks the
    # commit — the only action at the frame is the commit itself.
    cs, _cp = _state(food=0, wood=0)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert FireTrigger(card_id="bookshelf") not in la
    assert CommitPlayOccupation(card_id="childless") in la


def test_banks_surplus_over_cost():
    # The later occupation costs 1 food; the 3 free food pays it and banks 2.
    cs, cp = _state(food=0, wood=0)
    cs = _to_play_occupation(cs)
    assert cs.players[cp].resources.food == 3
    cs = step(cs, CommitPlayOccupation(card_id="childless"))
    p = cs.players[cp]
    assert "childless" in p.occupations
    assert p.resources.food == 2                        # 3 raised, 1 paid, 2 banked


# --------------------------------------------------------------------------- scoping

def test_fires_each_time_an_occupation_is_played():
    # Two separate occupation plays each grant 3 food (the effect is per-play, not once-only).
    cs, cp = _state(owned_occ=("priest", "stable_architect", "consultant"),
                    hand=("childless", "soldier"), food=0, wood=0)
    cs = _to_play_occupation(cs)
    assert cs.players[cp].resources.food == 3
    cs = step(cs, CommitPlayOccupation(card_id="childless"))
    # food after first play: 3 - 1 (cost) = 2
    assert cs.players[cp].resources.food == 2
    cs = _to_play_occupation(cs)                          # a second, independent play
    assert cs.players[cp].resources.food == 5            # 2 + 3 granted again


def test_grants_only_to_the_owning_seat():
    # Bookshelf fires only for its OWNER's seat. The active owner plays an occupation and gains
    # the 3 food; the other seat (which owns nothing) gains nothing — confirming the per-seat
    # ownership scope of the auto.
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    opp = 1 - cp
    owner = fast_replace(cs.players[cp],
                         occupations=frozenset({"priest", "stable_architect", "consultant"}),
                         minor_improvements=frozenset({"bookshelf"}),
                         hand_occupations=frozenset({"childless"}),
                         resources=Resources(food=0, wood=0))
    other = fast_replace(cs.players[opp], minor_improvements=frozenset(),
                         resources=Resources(food=0))
    cs = fast_replace(cs, players=tuple(owner if i == cp else other for i in range(2)))
    cs = _to_play_occupation(cs)                          # the OWNER (active seat) plays
    assert cs.players[cp].resources.food == 3            # acting owner gained the 3 food
    assert cs.players[opp].resources.food == 0           # the other seat gained nothing


def test_does_not_fire_for_nonowner():
    # The acting player does NOT own Bookshelf, so no food is granted. Zero owned occupations
    # makes the (free) first play reachable without any food source — isolating the no-grant.
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    actor = fast_replace(cs.players[cp],
                         occupations=frozenset(),           # first play is free (cost 0 food)
                         minor_improvements=frozenset(),    # does NOT own Bookshelf
                         hand_occupations=frozenset({"childless"}),
                         resources=Resources(food=0, wood=0))
    cs = fast_replace(cs, players=tuple(actor if i == cp else cs.players[i] for i in range(2)))
    cs = _to_play_occupation(cs)
    assert cs.players[cp].resources.food == 0            # not owned -> no grant


# --------------------------------------------------------------------------- affordability gate

def test_lessons_offered_only_via_bookshelf_food():
    # 0 food, no liquidation fuel, own Bookshelf, 3 occupations already played: the next
    # occupation's 1-food cost is payable only because Bookshelf supplies 3 free food. Lessons
    # must be offered (the gate consults the food source). Without owning Bookshelf it must NOT.
    cs, _ = _state(owned_minors=("bookshelf",), food=0, wood=0)
    assert "lessons" in _spaces(cs)
    cs_no, _ = _state(owned_minors=(), food=0, wood=0)
    assert "lessons" not in _spaces(cs_no)
