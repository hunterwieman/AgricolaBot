"""Tests for Beating Rod (minor improvement, B9; Bubulcus Expansion).

Card text: "You can immediately choose to either get 1 reed or exchange 1 reed for
1 cattle."
Free. No prereq. The player must take ONE of the two (user 2026-07-13), surfaced
WIDE via `register_play_minor_variant`: route "reed" (get 1 reed) and route
"cattle" (pay 1 reed -> 1 cattle, offered only with a reed on hand). The cattle
routes through `grant_animals`, so an overflow surfaces the accommodation barrier.
"""
import json
from pathlib import Path

import agricola.cards.beating_rod  # noqa: F401  (registers the card)

from agricola.actions import CommitAccommodate, CommitPlayMinor
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_animals, with_pending_stack, with_resources

CARD_ID = "beating_rod"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Beating Rod")


def _at_play_minor_frame(**res):
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_resources(state, cp, **res)
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


def _variants(state):
    return {a.variant for a in _plays(state)}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["text"] == (
        "You can immediately choose to either get 1 reed or exchange 1 reed for "
        "1 cattle.")
    import agricola.cards.beating_rod as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()
    assert CARD_ID in PLAY_MINOR_VARIANTS


# ---------------------------------------------------------------------------
# Wide enumeration; cattle route needs a reed
# ---------------------------------------------------------------------------

def test_both_routes_offered_with_a_reed():
    state, _cp = _at_play_minor_frame(reed=1)
    assert _variants(state) == {"reed", "cattle"}


def test_only_reed_route_without_a_reed():
    state, _cp = _at_play_minor_frame()      # no reed to exchange
    assert _variants(state) == {"reed"}


def test_always_playable_and_no_do_nothing():
    """The card is always playable (the zero-surcharge get-reed route), and the
    only options are the two routes — there is no play-and-do-nothing."""
    state, _cp = _at_play_minor_frame()
    assert len(_plays(state)) == 1
    assert _plays(state)[0].variant == "reed"


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------

def test_get_reed_route():
    state, cp = _at_play_minor_frame(reed=2)
    (reed_play,) = [a for a in _plays(state) if a.variant == "reed"]
    out = step(state, reed_play)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.reed == 3             # 2 + 1
    assert p.animals.cattle == 0


def test_exchange_reed_for_cattle_that_fits():
    state, cp = _at_play_minor_frame(reed=1)
    (cattle_play,) = [a for a in _plays(state) if a.variant == "cattle"]
    out = step(state, cattle_play)
    p = out.players[cp]
    assert p.resources.reed == 0             # reed spent
    assert p.animals.cattle == 1             # cattle gained (fits the house-pet slot)
    assert not any(isinstance(f, PendingAccommodate) for f in out.pending_stack)


def test_exchange_overflow_surfaces_barrier():
    """A cattle onto a farm whose only slot (the house pet) is taken overflows —
    the accommodation barrier surfaces the keep-which choice."""
    state, cp = _at_play_minor_frame(reed=1)
    state = with_animals(state, cp, sheep=1)   # fills the house-pet slot; no pastures
    (cattle_play,) = [a for a in _plays(state) if a.variant == "cattle"]
    out = step(state, cattle_play)
    assert isinstance(out.pending_stack[-1], PendingAccommodate)
    options = [a for a in legal_actions(out) if isinstance(a, CommitAccommodate)]
    assert options
    for a in options:
        assert a.sheep + a.boar + a.cattle <= 1   # only the pet slot houses one
