import agricola.cards.hill_cultivator  # noqa: F401  (registers the card)

"""Hill Cultivator (occupation, E121): "Each time you use the 'Grain Seeds' or
'Vegetable Seeds' action space, you also get 2 or 3 clay, respectively."

Before-window automatic income on two atomic (hosted) spaces; "respectively"
pairs Grain Seeds -> 2 clay and Vegetable Seeds -> 3 clay.
"""
from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=("hill_cultivator",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, occupations=frozenset({"hill_cultivator"})):
    """A card-mode round-1 WORK state with the current player's tableau set
    deterministically (hand emptied so plays are reproducible)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset(),
                     occupations=occupations)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _reveal(state, space_id):
    """Turn up a stage space (Vegetable Seeds is Stage 3 — not up at round 1)."""
    sp = get_space(state.board, space_id)
    return fast_replace(state, board=with_space(state.board, space_id,
                                                fast_replace(sp, revealed=True)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_hill_cultivator_registered():
    assert "hill_cultivator" in OCCUPATIONS
    # "Each time you use" = BEFORE-window automatic effect.
    before_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "hill_cultivator" in before_ids
    after_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert "hill_cultivator" not in after_ids
    # Both hooked spaces are atomic → both must be explicitly hosted.
    assert "hill_cultivator" in OWN_ACTION_HOOK_CARDS["grain_seeds"]
    assert "hill_cultivator" in OWN_ACTION_HOOK_CARDS["vegetable_seeds"]


# ---------------------------------------------------------------------------
# Grain Seeds → +2 clay (fires in the before window, at the host push)
# ---------------------------------------------------------------------------

def test_grain_seeds_grants_two_clay():
    cs, cp = _card_state()
    cs = fast_replace(cs, current_player=cp)
    before_clay = cs.players[cp].resources.clay
    before_grain = cs.players[cp].resources.grain

    cs = step(cs, PlaceWorker(space="grain_seeds"))
    # Owned hook card → the atomic space is hosted by a PendingActionSpace.
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    assert cs.pending_stack[-1].phase == "before"
    # Choiceless automatic → no optional trigger surfaces.
    assert legal_actions(cs) == [Proceed()]
    # Before-window auto fired at the push: +2 clay already landed.
    assert cs.players[cp].resources.clay == before_clay + 2

    cs = step(cs, Proceed())   # run Grain Seeds' primary effect (+1 grain)
    cs = step(cs, Stop())
    assert cs.pending_stack == ()
    assert cs.players[cp].resources.clay == before_clay + 2
    assert cs.players[cp].resources.grain == before_grain + 1


# ---------------------------------------------------------------------------
# Vegetable Seeds (Stage 3 — revealed for the test) → +3 clay
# ---------------------------------------------------------------------------

def test_vegetable_seeds_grants_three_clay():
    cs, cp = _card_state()
    cs = fast_replace(cs, current_player=cp)
    cs = _reveal(cs, "vegetable_seeds")
    before_clay = cs.players[cp].resources.clay
    before_veg = cs.players[cp].resources.veg

    assert PlaceWorker(space="vegetable_seeds") in legal_actions(cs)
    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    assert legal_actions(cs) == [Proceed()]
    assert cs.players[cp].resources.clay == before_clay + 3

    cs = step(cs, Proceed())   # run Vegetable Seeds' primary effect (+1 veg)
    cs = step(cs, Stop())
    assert cs.pending_stack == ()
    assert cs.players[cp].resources.clay == before_clay + 3
    assert cs.players[cp].resources.veg == before_veg + 1


# ---------------------------------------------------------------------------
# Eligibility boundary: does NOT fire on an unrelated space
# ---------------------------------------------------------------------------

def test_does_not_fire_on_unrelated_space():
    # Owns hill_cultivator; uses Forest (not a seeds space). Forest is atomic
    # and hill_cultivator does not hook it, so it stays on the atomic fast
    # path and grants no clay.
    cs, cp = _card_state()
    cs = fast_replace(cs, current_player=cp)
    before_clay = cs.players[cp].resources.clay
    assert "hill_cultivator" not in OWN_ACTION_HOOK_CARDS.get("forest", set())

    cs = step(cs, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].resources.clay == before_clay


# ---------------------------------------------------------------------------
# Only the ACTING player's owned card fires (any_player=False default)
# ---------------------------------------------------------------------------

def test_opponents_hill_cultivator_does_not_fire_on_my_grain_seeds():
    cs, cp = _card_state(occupations=frozenset())
    opp = 1 - cp
    op = fast_replace(cs.players[opp], occupations=frozenset({"hill_cultivator"}))
    cs = fast_replace(cs, players=tuple(op if i == opp else cs.players[i] for i in range(2)),
                      current_player=cp)
    before_cp_clay = cs.players[cp].resources.clay
    before_opp_clay = cs.players[opp].resources.clay

    # cp does NOT own hill_cultivator → Grain Seeds is not hosted for cp's use.
    cs = step(cs, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].resources.clay == before_cp_clay
    assert cs.players[opp].resources.clay == before_opp_clay


# ---------------------------------------------------------------------------
# Hand-only card is inert (a hand card cannot fire)
# ---------------------------------------------------------------------------

def test_hand_only_is_inert():
    cs, cp = _card_state(occupations=frozenset())
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"hill_cultivator"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)),
                      current_player=cp)
    before_clay = cs.players[cp].resources.clay

    cs = step(cs, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].resources.clay == before_clay
