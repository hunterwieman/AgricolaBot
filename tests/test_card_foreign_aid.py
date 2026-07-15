"""Tests for Foreign Aid (minor improvement, D50; Consul Dirigens Expansion).

Card text (verbatim): "When you play this card, you immediately get 6 food. You
may no longer use the action spaces of rounds 12 to 14." Free; prereq "Play in
Round 11 or Before"; VPs 0; not passing.

Two effects:
- ON PLAY — +6 food immediately (driven through the real CommitPlayMinor flow).
- A STANDING PROHIBITION — the owner may no longer place a worker on any action
  space revealed for rounds 12/13/14 (``revealed_round in {12, 13, 14}``), via the
  subtractive ``register_placement_forbid`` seam; permanents (revealed_round 0)
  and rounds-≤11 spaces stay placeable, and non-owners are untouched.
"""
import agricola.cards.foreign_aid  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor, PlaceWorker
from agricola.cards.foreign_aid import CARD_ID, _FORBIDDEN_ROUNDS, _forbid
from agricola.cards.specs import MINORS, prereq_met
from agricola.legality import PLACEMENT_FORBID_EXTENSIONS, legal_placements
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_current_player,
    with_minors,
    with_pending_stack,
    with_round,
    with_space,
)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _cards_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _at_play_minor_frame():
    """A CARDS state at a PendingPlayMinor with Foreign Aid in the current
    player's hand (round 1, so its "round 11 or before" prereq is met)."""
    state = _cards_state()
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(
        state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp,
                                 initiated_by_id="space:meeting_place_cards"),))
    return state, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()            # cost null -> free
    assert spec.vps == 0                  # none printed
    assert spec.prereq is not None        # "Play in Round 11 or Before"
    assert spec.passing_left is False
    # The prohibition predicate is on the subtractive placement seam.
    assert _forbid in PLACEMENT_FORBID_EXTENSIONS
    assert _FORBIDDEN_ROUNDS == frozenset({12, 13, 14})


# ---------------------------------------------------------------------------
# Prerequisite: "Play in Round 11 or Before"
# ---------------------------------------------------------------------------

def test_prereq_round_11_or_before():
    spec = MINORS[CARD_ID]
    state = _cards_state()
    assert prereq_met(spec, with_round(state, 11), 0)      # round 11: allowed
    assert prereq_met(spec, with_round(state, 1), 0)       # earlier: allowed
    assert not prereq_met(spec, with_round(state, 12), 0)  # round 12: blocked
    assert not prereq_met(spec, with_round(state, 14), 0)  # later: blocked


# ---------------------------------------------------------------------------
# On play: +6 food (real CommitPlayMinor flow)
# ---------------------------------------------------------------------------

def test_play_grants_six_food():
    from agricola.engine import step
    from agricola.legality import legal_actions

    state, cp = _at_play_minor_frame()
    before = state.players[cp].resources.food
    commit = next(a for a in legal_actions(state)
                  if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID)
    out = step(state, commit)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.food == before + 6


# ---------------------------------------------------------------------------
# The prohibition: rounds-12–14 action spaces
# ---------------------------------------------------------------------------

def _board_with_space_revealed_for(state, space_id, round_number):
    """Reveal `space_id` for `round_number` and stock it so its placement
    predicate holds (Sheep Market: revealed + unoccupied + goods on it)."""
    return with_space(state, space_id, revealed=True,
                      revealed_round=round_number, accumulated_amount=1)


def test_owner_cannot_place_on_round_12_14_space():
    """A space revealed for round 12 is dropped from the OWNER's placements
    but stays for the non-owner and for a player who does not own the card."""
    base = _board_with_space_revealed_for(_cards_state(), "sheep_market", 12)
    target = PlaceWorker(space="sheep_market")

    # Player 0 owns Foreign Aid.
    owned = with_minors(base, 0, frozenset({CARD_ID}))
    # (a) The owner is placing → the round-12 space is forbidden.
    assert target not in legal_placements(with_current_player(owned, 0))
    # (b) The NON-owner (player 1) is placing → the space is still offered
    #     (the forbid self-gates on the acting player's ownership).
    assert target in legal_placements(with_current_player(owned, 1))
    # (c) Nobody owns Foreign Aid → the space is offered as normal.
    assert target in legal_placements(with_current_player(base, 0))


def test_owner_cannot_place_on_any_of_rounds_12_13_14():
    target = PlaceWorker(space="sheep_market")
    for rnd in (12, 13, 14):
        state = _board_with_space_revealed_for(_cards_state(), "sheep_market", rnd)
        state = with_current_player(with_minors(state, 0, frozenset({CARD_ID})), 0)
        assert target not in legal_placements(state), f"round {rnd} not forbidden"


def test_owner_keeps_round_le_11_and_permanent_spaces():
    """The prohibition names ONLY rounds 12–14: a rounds-≤11 space and the
    permanents (revealed_round 0) stay placeable for the owner."""
    # A round-8 stage space (revealed_round 8) is not in {12,13,14}.
    state = _board_with_space_revealed_for(_cards_state(), "sheep_market", 8)
    state = with_current_player(with_minors(state, 0, frozenset({CARD_ID})), 0)
    placements = legal_placements(state)
    assert PlaceWorker(space="sheep_market") in placements
    # Day Laborer is a permanent (revealed_round 0) → never forbidden.
    assert PlaceWorker(space="day_laborer") in placements


def test_forbid_predicate_self_gates_on_ownership():
    """The predicate returns False for a non-owner and for a non-12–14 space,
    True only for an owner on a 12/13/14 space."""
    state = _board_with_space_revealed_for(_cards_state(), "sheep_market", 13)
    owned = with_minors(state, 0, frozenset({CARD_ID}))
    assert _forbid(owned, 0, "sheep_market") is True          # owner, round 13
    assert _forbid(state, 0, "sheep_market") is False         # not owned
    assert _forbid(owned, 0, "day_laborer") is False          # permanent (0)
