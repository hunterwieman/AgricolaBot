"""Tests for the web-UI card-state display registry (`agricola.cards.display`).

The load-bearing test is `test_scoring_cards_are_classified`: it asserts the
history-VP / public-VP sets partition every registered scoring term. This is what
turns "a new banked-points card silently gets no +X vp emblem" (which happened
once — Home Brewer and 11 others were missed) into a loud failure.
"""
from __future__ import annotations

import agricola.cards  # noqa: F401 — populate the card registries
from agricola.cards import display as d
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup


def _scoring_ids() -> set[str]:
    return {cid for cid, _ in SCORING_TERMS}


def test_scoring_cards_are_classified():
    """Every registered scoring card is classified as exactly one of history-VP
    (reads card_state → emblem) or public-VP (reads the board → no emblem). A new
    scoring card that isn't added to one set fails here."""
    hist, pub = d.HISTORY_VP_CARDS, d.PUBLIC_VP_CARDS
    assert not (hist & pub), f"cards in BOTH sets: {sorted(hist & pub)}"
    classified = hist | pub
    scoring = _scoring_ids()
    unclassified = scoring - classified
    stale = classified - scoring
    assert not unclassified, f"scoring cards missing a display classification: {sorted(unclassified)}"
    assert not stale, f"classified ids that are not registered scoring cards: {sorted(stale)}"


def test_bonus_vps_history_vs_public():
    s = setup(0)
    # A history card resolves to an int via its scoring term (0 with no store yet).
    assert d.bonus_vps("mantlepiece", s, 0) == 0
    # A public-info card and an unknown id get no emblem.
    assert d.bonus_vps("loom", s, 0) is None
    assert d.bonus_vps("not_a_card", s, 0) is None


def test_bonus_vps_reads_banked_value():
    s = setup(0)
    p = s.players[0]
    p = fast_replace(p, card_state=p.card_state.set("home_brewer", 3))
    s = fast_replace(s, players=(p, s.players[1]))
    assert d.bonus_vps("home_brewer", s, 0) == 3


def test_state_text_resource_and_counter():
    s = setup(0)
    p = s.players[0]
    # Empty store → no badge.
    assert d.state_text("interim_storage", p) is None
    # Default moldboard counter shows even before use.
    assert d.state_text("moldboard_plow", p) == "2 field-plows left"
    p = fast_replace(
        p,
        card_state=p.card_state.set("interim_storage", Resources(wood=2, clay=1))
        .set("moldboard_plow", 1),
    )
    assert d.state_text("interim_storage", p) == "Holding: 2 wood, 1 clay"
    assert d.state_text("moldboard_plow", p) == "1 field-plow left"  # singular
    # A card with no formatter returns None.
    assert d.state_text("loom", p) is None
