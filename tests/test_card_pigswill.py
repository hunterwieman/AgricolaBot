"""Tests for Pigswill (minor D83): "Each time you use the 'Fencing' action
space, you also get 1 wild boar." Cost 2 Food / 1 Grain (alternative).

Timing is user-ruled (2026-07-13): BEFORE — the boar lands at the Fencing
host's push, before any fence is built, so a player at capacity resolves the
accommodation barrier's keep-which choice before the new pasture exists.
"""
import agricola.cards.pigswill  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitPlayMinor,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_resources
from tests.test_fencing import _fencing_setup, _with_initial_pasture

CARD_ID = "pigswill"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

# A top-right 2x2 (4 cells, 8 fence pieces) — in the default RESTRICTED universe.
_2X2_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4)})


def _own(state, idx, *, minors=()):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements
                     | set(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _fencing_state(*, owner=0, current_player=0):
    """Family fencing scaffold (Fencing revealed, 8 wood) flipped to CARDS
    mode with Pigswill in the owner's tableau."""
    s = _fencing_setup(wood=8, current_player=current_player)
    s = fast_replace(s, mode=GameMode.CARDS)
    return _own(s, owner, minors=(CARD_ID,))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(food=2)
    assert spec.alt_costs == (Cost(resources=Resources(grain=1)),)
    assert spec.vps == 0
    assert spec.passing_left is False
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID in auto_ids


# ---------------------------------------------------------------------------
# The boar fires BEFORE the fence work (user ruling 2026-07-13)
# ---------------------------------------------------------------------------

def test_boar_granted_at_fencing_placement_before_any_build():
    s = _fencing_state()
    out = step(s, PlaceWorker(space="fencing"))
    # At the host push — no fence built yet — the boar is already there.
    assert out.players[0].animals.boar == 1
    assert not out.players[0].farmyard.pastures


def test_full_fencing_turn_keeps_the_boar():
    s = _fencing_state()
    s = step(s, PlaceWorker(space="fencing"))
    s = step(s, ChooseSubAction(name="build_fences"))
    commit = next(a for a in legal_actions(s)
                  if isinstance(a, CommitBuildPasture) and a.cells == _2X2_TR)
    s = step(s, commit)
    s = step(s, Proceed())
    s = step(s, Stop())        # build_fences host
    s = step(s, Stop())        # fencing space host
    assert s.players[0].animals.boar == 1
    assert len(s.players[0].farmyard.pastures) == 1


def test_at_capacity_boar_forces_accommodation_before_fence_commits():
    # Farm already full: a 1x2 pasture (cap 4) with 4 sheep + a house-pet
    # sheep. The boar granted at the Fencing push cannot fit, so the barrier
    # surfaces the keep-which frame BEFORE the player builds anything —
    # exactly the ruled downside ("too bad for players who were hoping to
    # store the boar in the newly built fences").
    s = _fencing_state()
    s = _with_initial_pasture(s, 0, frozenset({(0, 3), (0, 4)}))
    p = s.players[0]
    p = fast_replace(p, animals=fast_replace(p.animals, sheep=5))
    s = fast_replace(s, players=(p, s.players[1]))
    out = step(s, PlaceWorker(space="fencing"))
    assert isinstance(out.pending_stack[-1], PendingAccommodate)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_opponent_fencing_use_grants_owner_nothing():
    # Player 1 uses Fencing; player 0 owns Pigswill → "each time YOU use":
    # the auto routes to the acting player, who doesn't own the card.
    s = _fencing_state(owner=0, current_player=1)
    s = with_resources(s, 1, wood=8)
    out = step(s, PlaceWorker(space="fencing"))
    assert out.players[0].animals.boar == 0
    assert out.players[1].animals.boar == 0


def test_other_spaces_do_not_fire():
    s = _fencing_state()
    out = step(s, PlaceWorker(space="farmland"))
    assert out.players[0].animals.boar == 0


def test_farm_redevelopment_fences_do_not_fire():
    # Building fences via Farm Redevelopment's optional step is not "using
    # the 'Fencing' action space".
    from tests.factories import with_space
    s = _fencing_state()
    s = with_space(s, "farm_redevelopment", revealed=True)
    s = with_resources(s, 0, wood=8, clay=8, reed=2)
    out = step(s, PlaceWorker(space="farm_redevelopment"))
    assert out.players[0].animals.boar == 0


# ---------------------------------------------------------------------------
# The alternative cost: 2 food OR 1 grain
# ---------------------------------------------------------------------------

def _at_play_minor_frame(res):
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}),
                     resources=res)
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp,
                                 initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _minor_commits(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


def test_both_alternatives_offered_pay_one_not_both():
    state, cp = _at_play_minor_frame(Resources(food=2, grain=1))
    payments = sorted((c.payment.food, c.payment.grain) for c in _minor_commits(state))
    assert payments == [(0, 1), (2, 0)]
    # Paying the grain alternative leaves the food untouched.
    grain_commit = next(c for c in _minor_commits(state) if c.payment.grain == 1)
    out = step(state, grain_commit)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.grain == 0 and p.resources.food == 2


def test_only_affordable_alternative_offered():
    state, _cp = _at_play_minor_frame(Resources(grain=1))
    commits = _minor_commits(state)
    assert len(commits) == 1 and commits[0].payment.grain == 1
