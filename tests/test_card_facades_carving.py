"""Tests for Facades Carving (minor improvement, A36; Artifex Expansion).

Card text: "When you play this card, you can exchange any number of food for
1 bonus point each, up to the number of completed harvests."

The on-play choice surfaces WIDE (user ruling 2026-07-06, the minor analog of
Baker's occupation pattern): one CommitPlayMinor per food amount f in
0..completed_harvests, each variant "f<k>" folding a k-food surcharge into the
play payment at enumeration (liquidation-aware affordability). The on-play
banks f bonus points in the CardStore; a scoring term reads them back.
Prerequisite: Wood in Your Supply >= Current Round (a HAVE-check, never
spent). Tests drive the real PendingPlayMinor frame through legal_actions /
step, pin the variant sets per round (completed harvests derived from
round_number against HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}), the
liquidation-aware withholding, the end-to-end debit + banked points + scoring,
and that ordinary (variant-less) minors are untouched by the seam.
"""
import json
from pathlib import Path

import agricola.cards.facades_carving  # noqa: F401  -- registers the card
import agricola.cards.social_benefits  # noqa: F401  -- ordinary-minor control

from agricola.actions import CommitPlayMinor
from agricola.cards.facades_carving import CARD_ID, _completed_harvests
from agricola.cards.social_benefits import CARD_ID as SOCIAL_BENEFITS
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup_env

from tests.factories import with_pending_stack, with_resources, with_round

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, SOCIAL_BENEFITS) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Facades Carving")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _at_play_minor_frame(round_number=1, hand=(CARD_ID,), **res):
    """A prefabricated state at a PendingPlayMinor frame for the current
    player, holding `hand` and exactly the given resources (others zero)."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset(hand))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_round(state, round_number)
    state = with_resources(state, cp, **res)
    state = with_pending_stack(
        state,
        (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state, cid=CARD_ID):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == cid]


def _variants_offered(state, cid=CARD_ID):
    return {a.variant for a in _plays(state, cid)}


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON row)
# ---------------------------------------------------------------------------

def test_json_row():
    """Pin the catalog row this module encodes (cost / prereq / text verbatim)."""
    assert _ROW["cost"] == "2 Clay,1 Reed"
    assert _ROW["prerequisites"] == "Wood in Your Supply >= Current Round"
    assert _ROW["text"] == (
        "When you play this card, you can exchange any number of food for "
        "1 bonus point each, up to the number of completed harvests.")
    assert _ROW["vps"] is None
    assert _ROW["passing_left"] is None
    # The module docstring quotes the printed text verbatim (line-wrapped, so
    # compare whitespace-normalized).
    import agricola.cards.facades_carving as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(Resources(clay=2, reed=1))   # "2 Clay,1 Reed"
    assert spec.alt_costs == ()
    assert spec.cost_fn is None
    assert spec.min_occupations == 0                      # no occupation prereq
    assert spec.max_occupations is None
    assert spec.prereq is not None                        # the wood-vs-round check
    assert spec.vps == 0                                  # points are earned, not printed
    assert spec.passing_left is False
    assert CARD_ID in PLAY_MINOR_VARIANTS                 # the wide on-play choice


# ---------------------------------------------------------------------------
# Prerequisite: Wood in Your Supply >= Current Round (boundaries)
# ---------------------------------------------------------------------------

def test_prereq_wood_boundaries():
    spec = MINORS[CARD_ID]
    for rnd in (1, 8, 14):
        below, cp = _at_play_minor_frame(
            round_number=rnd, wood=rnd - 1, clay=2, reed=1)
        assert not prereq_met(spec, below, cp)            # wood == round-1: no
        at, cp = _at_play_minor_frame(
            round_number=rnd, wood=rnd, clay=2, reed=1)
        assert prereq_met(spec, at, cp)                   # wood == round: yes


def test_prereq_gates_the_real_frame():
    """wood == round-1 -> the card is not offered at all; wood == round -> it is."""
    state, cp = _at_play_minor_frame(round_number=3, wood=2, clay=2, reed=1, food=9)
    assert CARD_ID not in playable_minors(state, cp)
    assert not _plays(state)
    state, cp = _at_play_minor_frame(round_number=3, wood=3, clay=2, reed=1, food=9)
    assert CARD_ID in playable_minors(state, cp)
    assert _plays(state)


# ---------------------------------------------------------------------------
# Completed harvests derived from round_number (HARVEST_ROUNDS = 4,7,9,11,13,14)
# ---------------------------------------------------------------------------

def test_completed_harvests_derivation():
    expected = {1: 0, 4: 0, 5: 1, 7: 1, 8: 2, 9: 2, 10: 3, 11: 3, 12: 4, 13: 4, 14: 5}
    for rnd, n in expected.items():
        state, _cp = _at_play_minor_frame(round_number=rnd, wood=rnd, clay=2, reed=1)
        assert _completed_harvests(state) == n, rnd


def test_round_1_only_f0():
    """0 completed harvests: the sole play is the zero-surcharge route."""
    state, _cp = _at_play_minor_frame(round_number=1, wood=1, clay=2, reed=1, food=9)
    assert _variants_offered(state) == {"f0"}


def test_round_8_offers_f0_f1_f2():
    """Round 8 (harvests of rounds 4 and 7 completed) with ample food."""
    state, _cp = _at_play_minor_frame(round_number=8, wood=8, clay=2, reed=1, food=9)
    assert _variants_offered(state) == {"f0", "f1", "f2"}


def test_round_14_offers_up_to_f5():
    """Round 14: five completed harvests (4, 7, 9, 11, 13)."""
    state, _cp = _at_play_minor_frame(round_number=14, wood=14, clay=2, reed=1, food=9)
    assert _variants_offered(state) == {"f0", "f1", "f2", "f3", "f4", "f5"}


# ---------------------------------------------------------------------------
# Affordability: the surcharge folds into the payment, liquidation-aware
# ---------------------------------------------------------------------------

def test_food_limited_variants_withheld():
    """1 food, no convertibles: f2 is unpayable and withheld; f0/f1 offered."""
    state, _cp = _at_play_minor_frame(round_number=8, wood=8, clay=2, reed=1, food=1)
    assert _variants_offered(state) == {"f0", "f1"}


def test_liquidation_reaches_higher_variants():
    """1 food + 1 grain (raw grain converts 1:1): f2 becomes payable via
    liquidation, so the seam offers it."""
    state, _cp = _at_play_minor_frame(
        round_number=8, wood=8, clay=2, reed=1, food=1, grain=1)
    assert _variants_offered(state) == {"f0", "f1", "f2"}


def test_surcharge_folded_into_payment():
    """The f2 commit's payment carries base cost + 2 food in one vector."""
    state, _cp = _at_play_minor_frame(round_number=8, wood=8, clay=2, reed=1, food=9)
    (f2,) = [a for a in _plays(state) if a.variant == "f2"]
    assert f2.payment == Resources(clay=2, reed=1, food=2)
    (f0,) = [a for a in _plays(state) if a.variant == "f0"]
    assert f0.payment == Resources(clay=2, reed=1)


# ---------------------------------------------------------------------------
# End-to-end commits: debit, banked points, scoring
# ---------------------------------------------------------------------------

def test_commit_f2_debits_and_banks_two_points():
    state, cp = _at_play_minor_frame(round_number=8, wood=8, clay=2, reed=1, food=5)
    before, _ = score(state, cp)
    (f2,) = [a for a in _plays(state) if a.variant == "f2"]
    state = step(state, f2)
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements
    assert CARD_ID not in p.hand_minors
    assert p.resources.clay == 0                          # card cost paid
    assert p.resources.reed == 0
    assert p.resources.food == 3                          # 5 - 2 exchanged
    assert p.resources.wood == 8                          # prereq is a HAVE-check, never spent
    assert p.card_state.get(CARD_ID, 0) == 2              # 2 points banked
    after, _ = score(state, cp)
    assert after - before == 2                            # exactly the 2 bonus points
    # (food does not score and the card has no printed VP)


def test_commit_f0_banks_nothing():
    state, cp = _at_play_minor_frame(round_number=8, wood=8, clay=2, reed=1, food=5)
    before, _ = score(state, cp)
    (f0,) = [a for a in _plays(state) if a.variant == "f0"]
    state = step(state, f0)
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.food == 5                          # no food exchanged
    assert p.card_state.get(CARD_ID) is None              # nothing banked
    after, _ = score(state, cp)
    assert after == before                                # no bonus points


def test_unplayed_scores_nothing():
    """The scoring term is ownership-gated: a banked entry without the played
    card (never producible in real play) contributes nothing."""
    state, cp = _at_play_minor_frame(round_number=8, wood=8, clay=2, reed=1, food=5)
    base, _ = score(state, cp)
    p = state.players[cp]
    tainted = fast_replace(p, card_state=p.card_state.set(CARD_ID, 3))
    s2 = fast_replace(state, players=tuple(
        tainted if i == cp else state.players[i] for i in range(2)))
    got, _ = score(s2, cp)
    assert got == base


# ---------------------------------------------------------------------------
# The seam does not widen ordinary minors
# ---------------------------------------------------------------------------

def test_ordinary_minor_unaffected():
    """Social Benefits (no variants_fn): exactly one play, variant=None."""
    state, _cp = _at_play_minor_frame(round_number=1, hand=(SOCIAL_BENEFITS,), reed=1)
    plays = _plays(state, SOCIAL_BENEFITS)
    assert len(plays) == 1
    assert plays[0].variant is None


def test_both_cards_in_hand_coexist():
    """Facades Carving surfaces wide while a sibling ordinary minor keeps its
    single variant-less play in the same enumeration."""
    state, _cp = _at_play_minor_frame(
        round_number=8, hand=(CARD_ID, SOCIAL_BENEFITS),
        wood=8, clay=2, reed=1, food=9)
    assert _variants_offered(state) == {"f0", "f1", "f2"}
    sb = _plays(state, SOCIAL_BENEFITS)
    assert len(sb) == 1 and sb[0].variant is None


# ---------------------------------------------------------------------------
# Web-UI variant labels (so the buttons read as the exchange, not "[f1]")
# ---------------------------------------------------------------------------

def test_variant_labels():
    """The wide play variants carry mechanical, terse web-UI labels: the
    exchange amount and points (singular/plural), with "f0" the no-exchange
    play. Unknown encodings fall through (None)."""
    from agricola.cards.display import variant_label
    assert variant_label(CARD_ID, "f0") == "no exchange"
    assert variant_label(CARD_ID, "f1") == "exchange 1 food → 1 bonus point"
    assert variant_label(CARD_ID, "f2") == "exchange 2 food → 2 bonus points"
    assert variant_label(CARD_ID, "f5") == "exchange 5 food → 5 bonus points"
    assert variant_label(CARD_ID, "bogus") is None
