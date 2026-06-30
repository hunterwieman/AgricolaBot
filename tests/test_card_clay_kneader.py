"""Clay Kneader (occupation, C121): one-time +1 wood +2 clay when played, and +1
clay each time AFTER you use a Grain Seeds or Vegetable Seeds action space.

Card text: "When you play this card, you immediately get 1 wood and 2 clay. Each
time after you use a 'Grain Seeds' or 'Vegetable Seeds' action space, you get 1
clay."
"""
import agricola.cards.clay_kneader  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env

_POOL = CardPool(
    occupations=("clay_kneader",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, occupations=frozenset(), hand=frozenset({"clay_kneader"})):
    """A card-mode round-1 WORK state with the current player's hand/tableau set
    deterministically so plays are reproducible."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=hand, occupations=occupations)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_clay_kneader_registered():
    assert "clay_kneader" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert "clay_kneader" in auto_ids
    # Both hooked spaces are atomic → both must be explicitly hosted.
    assert "clay_kneader" in OWN_ACTION_HOOK_CARDS["grain_seeds"]
    assert "clay_kneader" in OWN_ACTION_HOOK_CARDS["vegetable_seeds"]
    # The recurring grant rides after_action_space, not before.
    before_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "clay_kneader" not in before_ids


# ---------------------------------------------------------------------------
# On-play grant: +1 wood +2 clay (one-time)
# ---------------------------------------------------------------------------

def test_on_play_grants_wood_and_clay():
    cs, cp = _card_state()
    before_wood = cs.players[cp].resources.wood
    before_clay = cs.players[cp].resources.clay

    # Play via Lessons (an occupation-play entry point).
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="clay_kneader"))

    assert "clay_kneader" in cs.players[cp].occupations
    assert cs.players[cp].resources.wood == before_wood + 1
    assert cs.players[cp].resources.clay == before_clay + 2

    cs = step(cs, Stop())   # pop PendingPlayOccupation's after-phase
    cs = step(cs, Stop())   # pop the Lessons host frame
    assert cs.pending_stack == ()
    # On-play is one-time: no further grant (Lessons is not a hooked space).
    assert cs.players[cp].resources.wood == before_wood + 1
    assert cs.players[cp].resources.clay == before_clay + 2


# ---------------------------------------------------------------------------
# After Grain Seeds (atomic → hosted) → +1 clay
# ---------------------------------------------------------------------------

def test_after_grain_seeds_grants_one_clay():
    cs, cp = _card_state(occupations=frozenset({"clay_kneader"}), hand=frozenset())
    cs = fast_replace(cs, current_player=cp)
    before_clay = cs.players[cp].resources.clay
    before_grain = cs.players[cp].resources.grain

    cs = step(cs, PlaceWorker(space="grain_seeds"))
    # Owned hook card → the atomic space is hosted by a PendingActionSpace.
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    assert cs.pending_stack[-1].phase == "before"
    # No optional trigger surfaces (the grant is an automatic after-effect).
    assert legal_actions(cs) == [Proceed()]

    cs = step(cs, Proceed())   # run Grain Seeds, flip to after, fire the auto
    assert cs.pending_stack[-1].phase == "after"
    # Grain Seeds grants a flat +1 grain; the after-phase flip adds +1 clay.
    assert cs.players[cp].resources.clay == before_clay + 1
    assert cs.players[cp].resources.grain == before_grain + 1

    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# After Vegetable Seeds (atomic → hosted) → +1 clay
# ---------------------------------------------------------------------------

def test_after_vegetable_seeds_grants_one_clay():
    cs, cp = _card_state(occupations=frozenset({"clay_kneader"}), hand=frozenset())
    cs = fast_replace(cs, current_player=cp)
    before_clay = cs.players[cp].resources.clay
    before_veg = cs.players[cp].resources.veg

    cs = step(cs, PlaceWorker(space="vegetable_seeds"))
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    assert legal_actions(cs) == [Proceed()]

    cs = step(cs, Proceed())
    assert cs.pending_stack[-1].phase == "after"
    # Vegetable Seeds grants a flat +1 veg; the after-phase flip adds +1 clay.
    assert cs.players[cp].resources.clay == before_clay + 1
    assert cs.players[cp].resources.veg == before_veg + 1

    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# Played on a Grain Seeds-unrelated entry point still grants on-play, and a
# SUBSEQUENT seed use grants the recurring clay (scoping: each use fires).
# ---------------------------------------------------------------------------

def test_on_play_then_seed_use_both_grant():
    cs, cp = _card_state()
    before_clay = cs.players[cp].resources.clay
    before_wood = cs.players[cp].resources.wood

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="clay_kneader"))
    cs = step(cs, Stop())   # pop occupation child
    cs = step(cs, Stop())   # pop Lessons host
    # On-play applied: +1 wood +2 clay.
    assert cs.players[cp].resources.wood == before_wood + 1
    assert cs.players[cp].resources.clay == before_clay + 2

    # Advance to that player's next turn and use Grain Seeds.
    cs = fast_replace(cs, current_player=cp)
    clay_mid = cs.players[cp].resources.clay
    cs = step(cs, PlaceWorker(space="grain_seeds"))
    cs = step(cs, Proceed())
    assert cs.players[cp].resources.clay == clay_mid + 1   # recurring +1
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# Eligibility boundary: does NOT fire on an unrelated space
# ---------------------------------------------------------------------------

def test_does_not_fire_on_unrelated_space():
    # Owns clay_kneader; uses Forest (not Grain/Vegetable Seeds). Forest is
    # atomic and clay_kneader does not hook it, so it stays on the atomic fast
    # path and grants no clay.
    cs, cp = _card_state(occupations=frozenset({"clay_kneader"}), hand=frozenset())
    cs = fast_replace(cs, current_player=cp)
    before_clay = cs.players[cp].resources.clay
    assert "clay_kneader" not in OWN_ACTION_HOOK_CARDS.get("forest", set())

    cs = step(cs, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].resources.clay == before_clay   # no +1 clay


# ---------------------------------------------------------------------------
# Only the ACTING player's owned hook fires (any_player=False default)
# ---------------------------------------------------------------------------

def test_opponents_clay_kneader_does_not_fire_on_my_grain_seeds():
    cs, cp = _card_state(hand=frozenset())
    opp = 1 - cp
    op = fast_replace(cs.players[opp], occupations=frozenset({"clay_kneader"}))
    cs = fast_replace(cs, players=tuple(op if i == opp else cs.players[i] for i in range(2)),
                      current_player=cp)
    # cp does NOT own clay_kneader → Grain Seeds is not hosted for cp's use.
    before_cp_clay = cs.players[cp].resources.clay
    before_opp_clay = cs.players[opp].resources.clay

    cs = step(cs, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].resources.clay == before_cp_clay      # no +1 clay
    assert cs.players[opp].resources.clay == before_opp_clay    # opponent: no +1
