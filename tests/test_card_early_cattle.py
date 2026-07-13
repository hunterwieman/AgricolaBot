"""Tests for Early Cattle (minor C83): "When you play this card, you
immediately get 2 cattle." Free, prereq 1 Pasture, printed VPs -3, kept.

The 2 cattle route through `helpers.grant_animals`, so an overflow surfaces the
accommodation barrier's keep-which choice (`PendingAccommodate`) at the next
decision boundary rather than silently inflating the count.
"""
import agricola.cards.early_cattle  # noqa: F401  (registers the card)

from agricola.actions import CommitAccommodate, CommitPlayMinor
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_fencing import _with_initial_pasture

CARD_ID = "early_cattle"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _at_play_minor_frame(*, pasture_cells=frozenset({(0, 3), (0, 4)})):
    """A CARDS state at a PendingPlayMinor with the card in the current
    player's hand and (by default) one enclosed pasture on their farm."""
    state = _card_state()
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    if pasture_cells:
        state = _with_initial_pasture(state, cp, pasture_cells)
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp,
                                 initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _minor_commits(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()
    assert spec.vps == -3
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# Prerequisite: 1 Pasture
# ---------------------------------------------------------------------------

def test_prereq_requires_a_pasture():
    s = _card_state()
    spec = MINORS[CARD_ID]
    assert not prereq_met(spec, s, 0)               # fresh farm: no pasture
    s = _with_initial_pasture(s, 0, frozenset({(0, 3), (0, 4)}))
    assert prereq_met(spec, s, 0)


def test_not_offered_without_pasture():
    state, _cp = _at_play_minor_frame(pasture_cells=None)
    assert _minor_commits(state) == []


# ---------------------------------------------------------------------------
# On-play: 2 cattle, via the accommodation machinery
# ---------------------------------------------------------------------------

def test_play_grants_two_cattle_that_fit():
    # A 2-cell pasture (capacity 4) houses both cattle: no barrier frame.
    state, cp = _at_play_minor_frame()
    (commit,) = _minor_commits(state)
    out = step(state, commit)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.animals.cattle == 2
    assert not any(isinstance(f, PendingAccommodate) for f in out.pending_stack)


def test_overflow_surfaces_accommodation_barrier():
    # Fill the pasture with 4 sheep first: the 2 granted cattle cannot fit
    # (house pet takes 1 animal at most), so the barrier must surface the
    # keep-which choice instead of silently keeping everything.
    state, cp = _at_play_minor_frame()
    p = state.players[cp]
    p = fast_replace(p, animals=fast_replace(p.animals, sheep=4))
    state = fast_replace(state, players=tuple(
        p if i == cp else state.players[i] for i in range(2)))
    (commit,) = _minor_commits(state)
    out = step(state, commit)
    assert isinstance(out.pending_stack[-1], PendingAccommodate)
    options = [a for a in legal_actions(out) if isinstance(a, CommitAccommodate)]
    assert options
    # Every offered keep-config actually fits the farm (≤ 4 pasture + 1 pet).
    for a in options:
        assert a.sheep + a.boar + a.cattle <= 5


# ---------------------------------------------------------------------------
# Scoring: printed -3 VPs
# ---------------------------------------------------------------------------

def test_printed_negative_vps_scored():
    state, cp = _at_play_minor_frame()
    (commit,) = _minor_commits(state)
    out = step(state, commit)
    # The -3 printed VPs land in the owner's score; measure the card's own
    # delta by scoring the same state with and without the card in tableau.
    with_card, _ = score(out, cp)
    p = fast_replace(out.players[cp],
                     minor_improvements=out.players[cp].minor_improvements - {CARD_ID})
    stripped = fast_replace(out, players=tuple(
        p if i == cp else out.players[i] for i in range(2)))
    without_card, _ = score(stripped, cp)
    assert with_card == without_card - 3
