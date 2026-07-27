"""Engine-driven pins for the placement-ordinal counter — ruling 79 (2026-07-26), the
"PHYSICAL" interpretation of "the Nth person you place this round".

The semantics under test (`PlayerState.placements_this_round`, read via
`helpers.placements_this_round` — THE single definition every ordinal card consumes):

- Each act of PLACING a worker from home or supply mints the round's next number.
- A worker RETURNED home mid-round (Tea Time here) is anonymized: the return never
  touches the counter, and re-placing that worker mints a FRESH number — it is a new
  "person you place". This is the pin that separates PHYSICAL from the retired derived
  expression `(people_total − newborns) − people_home + ...`, which computed "workers
  currently deployed" and under-read after every return.
- Newborns never mint ("Newborns are not placed"): a Wish placement ticks once, for the
  parent, though the newborn also gets a board marker.
- The counter is per-round (reset at the returning-home reset) and CARDS-mode-only (the
  Family game holds it at 0 — the byte-identity guard).

Then four card-level scenarios pin the OBSERVABLE behavior changes the ruling makes to
shipped cards, each driving the full real flow (Grain Utilization sow → Meeting Place
playing Tea Time → the returned worker re-placed):

- Fir Cutter pays the re-placement as the 3rd person (2 wood), not the old
  deployed-count 2nd (1 wood).
- Catcher's tier-3 condition (exactly 3 building resources) matches the re-placement.
- Plow Hero does NOT offer its first-person bonus on the re-placed first worker.
- Skillful Renovator pays 3 wood — matching its own clarification ("renovate with your
  3rd placed person → 3 wood") — not the old deployed-count 2.
"""
import agricola.cards  # noqa: F401  -- populate the registries

from agricola.actions import (
    ChooseSubAction,
    CommitSow,
    FireTrigger,
    PlaceWorker,
)
# (Phase import not needed — the reset test bounds by round number)
from agricola.engine import step
from agricola.helpers import placements_this_round
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import (
    with_fields,
    with_people,
    with_resources,
    with_space,
)
from tests.test_utils import sole_play_minor, sole_renovate

GU = "grain_utilization"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("tea_time",) + tuple(f"m{i}" for i in range(20)),
)


def _setup(seed=5, *, own_occupations=frozenset()):
    """Card-mode round-1 WORK state: Tea Time (only) in the current player's hand,
    both hands otherwise empty, sow-capable, 3 food. Returns (state, cp)."""
    state, _env = setup_env(seed, card_pool=_POOL)
    cp = state.current_player
    state = with_space(state, GU, revealed=True)
    p = fast_replace(state.players[cp], hand_minors=frozenset({"tea_time"}),
                     hand_occupations=frozenset(),
                     occupations=frozenset(own_occupations))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset(),
                       hand_occupations=frozenset())
    state = fast_replace(
        state, players=tuple(p if i == cp else opp for i in range(2)))
    for i in (cp, 1 - cp):
        state = with_resources(state, i, food=3, grain=2)
        state = with_fields(state, i, [(0, 0), (0, 1)])
    return state, cp


def _drain_turn(state):
    """Step through the trailing forced close-out until the stack empties."""
    while state.pending_stack:
        acts = legal_actions(state)
        assert len(acts) == 1, f"expected a forced close-out, got {acts!r}"
        state = step(state, acts[0])
    return state


def _sole_sow(state, grain):
    opts = [a for a in legal_actions(state)
            if isinstance(a, CommitSow) and a.grain == grain and a.veg == 0]
    assert len(opts) == 1
    return opts[0]


def _use_grain_utilization(state):
    state = step(state, PlaceWorker(space=GU))
    state = step(state, ChooseSubAction(name="sow"))
    state = step(state, _sole_sow(state, 1))
    return _drain_turn(state)


def _returned_via_tea_time(state, cp):
    """The canonical return script: the owner's worker A sows at Grain Utilization
    (act 1), the opponent goes to the Forest, the owner's worker B places on Meeting
    Place and plays Tea Time (act 2) — returning A home — and the turn is drained.
    Leaves the OPPONENT to move (their second worker)."""
    state = _use_grain_utilization(state)                 # act 1: A -> GU
    assert state.current_player == 1 - cp
    state = step(state, PlaceWorker(space="forest"))      # opponent's first
    assert state.current_player == cp
    state = step(state, PlaceWorker(space="meeting_place"))
    state = step(state, ChooseSubAction(name="play_minor"))
    state = step(state, sole_play_minor(state, "tea_time"))   # act 2 + A comes home
    state = _drain_turn(state)
    p = state.players[cp]
    assert p.people_home == p.people_total - 1, "Tea Time should have returned A home"
    assert placements_this_round(p) == 2, "the return must not un-tick the counter"
    return state


def _opp_final_placement(state, cp):
    assert state.current_player == 1 - cp
    return step(state, PlaceWorker(space="clay_pit"))     # opponent's second (last)


# ---------------------------------------------------------------------------
# The counter itself
# ---------------------------------------------------------------------------

def test_each_placement_mints_the_next_number():
    state, cp = _setup()
    assert placements_this_round(state.players[cp]) == 0
    state = _use_grain_utilization(state)
    assert placements_this_round(state.players[cp]) == 1
    assert placements_this_round(state.players[1 - cp]) == 0    # per-player numbering
    state = step(state, PlaceWorker(space="forest"))            # opponent's act 1
    assert placements_this_round(state.players[1 - cp]) == 1
    assert placements_this_round(state.players[cp]) == 1        # unchanged


def test_wish_growth_mints_once_for_the_parent_only():
    """The newborn gets a board marker but is not PLACED — one tick, not two."""
    state, cp = _setup()
    state = with_space(state, "urgent_wish_for_children", revealed=True)
    state = step(state, PlaceWorker(space="urgent_wish_for_children"))
    state = _drain_turn(state)
    p = state.players[cp]
    assert p.newborns == 1
    assert placements_this_round(p) == 1


def test_return_does_not_untick_and_replacement_mints_fresh():
    """The core PHYSICAL pin: A (act 1) is returned by Tea Time; re-placing A is a NEW
    act and mints 3 — A is now 'the third person you place', not the first.

    The owner is given a THIRD family member (never placed) so the round is still in
    progress when the assert runs — with 2 family, act 3 is the round's last placement
    and the returning-home reset would have already zeroed the counter."""
    state, cp = _setup()
    state = with_people(state, cp, total=3, home=3, supply=2)
    state = _returned_via_tea_time(state, cp)
    state = _opp_final_placement(state, cp)
    assert state.current_player == cp
    state = step(state, PlaceWorker(space="day_laborer"))       # A again: act 3
    assert placements_this_round(state.players[cp]) == 3


def test_counter_resets_for_the_new_round():
    state, cp = _setup()
    start = state.round_number
    for _ in range(200):                       # safety bound; a round is far shorter
        if state.round_number != start:
            break
        acts = legal_actions(state)
        assert acts
        state = step(state, acts[0])
    assert state.round_number == start + 1
    for p in state.players:
        assert p.placements_this_round == 0


def test_family_game_never_ticks():
    """Byte-identity guard: the counter is Cards-mode-only, so a Family placement
    leaves it at the canonical-skipped default 0."""
    state = setup(3)
    cp = state.current_player
    state = step(state, PlaceWorker(space="forest"))
    assert state.players[cp].placements_this_round == 0


# ---------------------------------------------------------------------------
# The shipped ordinal cards, in the return scenario (the behavior the ruling changes)
# ---------------------------------------------------------------------------

def test_fir_cutter_pays_the_replacement_as_the_third_person():
    """Fir Cutter: "Each time after you use an animal accumulation space with your
    1st/2nd/3rd/4th/5th person, you get 1/1/2/2/3 wood." The re-placed A lands on the
    Sheep Market as act 3 → the 2-wood tier. (The retired deployed-count read 2 → 1
    wood.)"""
    state, cp = _setup(own_occupations={"fir_cutter"})
    state = with_space(state, "sheep_market", revealed=True, accumulated_amount=1)
    state = _returned_via_tea_time(state, cp)
    state = _opp_final_placement(state, cp)
    wood_before = state.players[cp].resources.wood
    state = step(state, PlaceWorker(space="sheep_market"))      # A again: act 3
    while state.pending_stack:
        state = step(state, legal_actions(state)[0])
    assert state.players[cp].resources.wood == wood_before + 2


def test_catcher_matches_the_replacement_against_the_third_tier():
    """Catcher: "Each time you place your 1st/2nd/3rd person in a round on a building
    resource accumulation space with exactly 5/4/3 building resources, you get 1
    food." The re-placed A is the 3rd person, so a Forest holding exactly 3 wood
    fires the tier (the retired count read A as the 2nd person → needed exactly 4 →
    no fire)."""
    state, cp = _setup(own_occupations={"catcher"})
    state = _returned_via_tea_time(state, cp)
    state = _opp_final_placement(state, cp)
    state = with_space(state, "forest", accumulated=Resources(wood=3))
    food_before = state.players[cp].resources.food
    state = step(state, PlaceWorker(space="forest"))            # A again: act 3
    while state.pending_stack:
        state = step(state, legal_actions(state)[0])
    assert state.players[cp].resources.food == food_before + 1


def test_plow_hero_does_not_fire_on_the_replaced_first_worker():
    """Plow Hero: "Each time you use the 'Farmland' or 'Cultivation' action space with
    the first person you place in a round, you can plow 1 additional field for 1
    food." A was the first person placed, but its return anonymized it — the
    re-placement is act 3, so the trigger must NOT be offered."""
    state, cp = _setup(own_occupations={"plow_hero"})
    state = _returned_via_tea_time(state, cp)
    state = _opp_final_placement(state, cp)
    state = step(state, PlaceWorker(space="farmland"))          # A again: act 3
    assert not any(isinstance(a, FireTrigger) and a.card_id == "plow_hero"
                   for a in legal_actions(state))


def test_plow_hero_still_fires_on_a_true_first_placement():
    """The positive control for the test above: same setup, no return — the first
    placement on Farmland IS offered the bonus plow."""
    state, cp = _setup(own_occupations={"plow_hero"})
    state = step(state, PlaceWorker(space="farmland"))          # act 1
    assert any(isinstance(a, FireTrigger) and a.card_id == "plow_hero"
               for a in legal_actions(state))


def test_skillful_renovator_pays_three_wood_per_its_own_clarification():
    """Skillful Renovator: "Each time after you renovate, you get a number of wood
    equal to the number of people you placed that round", clarified "If you renovate
    with your 3rd placed person of a round, this card triggers a payout of 3 wood."
    The re-placed A renovating IS the 3rd placed person → 3 wood. (The retired
    deployed count paid 2.)"""
    state, cp = _setup(own_occupations={"skillful_renovator"})
    state = with_space(state, "house_redevelopment", revealed=True)
    state = with_resources(state, cp, food=3, grain=2, clay=3, reed=2)
    state = _returned_via_tea_time(state, cp)
    state = _opp_final_placement(state, cp)
    wood_before = state.players[cp].resources.wood
    state = step(state, PlaceWorker(space="house_redevelopment"))   # A again: act 3
    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, sole_renovate(state))
    while state.pending_stack:
        state = step(state, legal_actions(state)[0])
    assert state.players[cp].resources.wood == wood_before + 3
