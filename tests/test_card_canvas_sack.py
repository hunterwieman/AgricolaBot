"""Tests for Canvas Sack (minor improvement, C40; Corbarius Expansion).

Card text: "When you play this card paying grain/reed for it, you immediately get
1 vegetable/4 wood."
Cost: 1 Grain / 1 Reed (alternative). Prereq: No Occupations. VPs: 1.

The reward is COUPLED to which alternative cost was paid (grain -> veg, reed ->
wood). Modeled on the `alt_costs` + `cost_labels` seam: the real alternative cost
flows through `effective_payments` (stays cost-modifier-visible), and the chosen
label reaches the 3-arg on_play. Tests drive the real PendingPlayMinor frame,
pin the wide enumeration, the label-coupled reward, and that the payment carries
the genuine alternative cost (not a surcharge on an empty base).
"""
import json
from pathlib import Path

import agricola.cards.canvas_sack  # noqa: F401  (registers the card)
import agricola.cards.social_benefits  # noqa: F401  (ordinary-minor control)

from agricola.actions import CommitPlayMinor
from agricola.cards.social_benefits import CARD_ID as SOCIAL_BENEFITS
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_resources

CARD_ID = "canvas_sack"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, SOCIAL_BENEFITS) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Canvas Sack")


def _at_play_minor_frame(hand=(CARD_ID,), occupations=frozenset(), **res):
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset(hand),
                     occupations=occupations)
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_resources(state, cp, **res)
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state, cid=CARD_ID):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == cid]


def _variants(state, cid=CARD_ID):
    return {a.variant for a in _plays(state, cid)}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["cost"] == "1 Grain/1 Reed"
    assert _ROW["prerequisites"] == "No Occupations"
    assert _ROW["vps"] == 1
    assert _ROW["text"] == (
        "When you play this card paying grain/reed for it, you immediately get "
        "1 vegetable/4 wood.")
    import agricola.cards.canvas_sack as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(grain=1))
    assert spec.alt_costs == (Cost(resources=Resources(reed=1)),)
    assert spec.cost_labels == ("grain", "reed")
    assert spec.max_occupations == 0
    assert spec.vps == 1


# ---------------------------------------------------------------------------
# Prerequisite: No Occupations
# ---------------------------------------------------------------------------

def test_prereq_no_occupations():
    spec = MINORS[CARD_ID]
    ok, cp = _at_play_minor_frame(grain=1, reed=1)
    assert prereq_met(spec, ok, cp)
    bad, cp = _at_play_minor_frame(occupations=frozenset({"o0"}), grain=1, reed=1)
    assert not prereq_met(spec, bad, cp)
    assert CARD_ID not in playable_minors(bad, cp)


# ---------------------------------------------------------------------------
# Wide enumeration: one play per affordable alternative
# ---------------------------------------------------------------------------

def test_both_alternatives_offered_wide():
    state, _cp = _at_play_minor_frame(grain=1, reed=1)
    assert _variants(state) == {"grain", "reed"}


def test_only_grain_when_only_grain_held():
    state, _cp = _at_play_minor_frame(grain=1)
    assert _variants(state) == {"grain"}


def test_only_reed_when_only_reed_held():
    state, _cp = _at_play_minor_frame(reed=1)
    assert _variants(state) == {"reed"}


def test_not_playable_with_neither():
    state, cp = _at_play_minor_frame()
    assert CARD_ID not in playable_minors(state, cp)
    assert _plays(state) == []


def test_payment_is_the_real_alternative_cost():
    """The cost is a genuine alternative (through effective_payments), not a
    surcharge on an empty base: the commit's payment IS the grain/reed cost."""
    state, _cp = _at_play_minor_frame(grain=1, reed=1)
    (grain_play,) = [a for a in _plays(state) if a.variant == "grain"]
    (reed_play,) = [a for a in _plays(state) if a.variant == "reed"]
    assert grain_play.payment == Resources(grain=1)
    assert reed_play.payment == Resources(reed=1)


# ---------------------------------------------------------------------------
# Coupled reward: grain -> veg, reed -> wood
# ---------------------------------------------------------------------------

def test_paying_grain_gives_vegetable():
    state, cp = _at_play_minor_frame(grain=1, reed=1)
    (grain_play,) = [a for a in _plays(state) if a.variant == "grain"]
    out = step(state, grain_play)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.grain == 0        # grain paid
    assert p.resources.reed == 1         # reed untouched
    assert p.resources.veg == 1          # +1 vegetable
    assert p.resources.wood == 0


def test_paying_reed_gives_four_wood():
    state, cp = _at_play_minor_frame(grain=1, reed=1)
    (reed_play,) = [a for a in _plays(state) if a.variant == "reed"]
    out = step(state, reed_play)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.reed == 0         # reed paid
    assert p.resources.grain == 1        # grain untouched
    assert p.resources.wood == 4         # +4 wood
    assert p.resources.veg == 0


def test_printed_vp_scored():
    state, cp = _at_play_minor_frame(grain=1, reed=1)
    (grain_play,) = [a for a in _plays(state) if a.variant == "grain"]
    out = step(state, grain_play)
    with_card, _ = score(out, cp)
    stripped_p = fast_replace(out.players[cp],
                              minor_improvements=out.players[cp].minor_improvements - {CARD_ID})
    stripped = fast_replace(out, players=tuple(
        stripped_p if i == cp else out.players[i] for i in range(2)))
    without_card, _ = score(stripped, cp)
    assert with_card == without_card + 1     # printed 1 VP


# ---------------------------------------------------------------------------
# The seam does not widen ordinary alt-cost-less minors
# ---------------------------------------------------------------------------

def test_ordinary_minor_unaffected():
    state, _cp = _at_play_minor_frame(hand=(SOCIAL_BENEFITS,), reed=1)
    plays = _plays(state, SOCIAL_BENEFITS)
    assert len(plays) == 1
    assert plays[0].variant is None
