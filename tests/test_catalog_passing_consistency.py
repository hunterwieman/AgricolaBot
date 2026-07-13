"""Guard: every implemented minor's `passing_left` matches the catalog.

A traveling (passing) minor — the number-001-009 cards in each deck, marked
`passing_left="X"` — passes to the opponent's hand after its effect instead of
staying in the tableau. Getting this wrong is silent: the card looks played, but
it scores/stays for the wrong player. Five traveling minors (Beating Rod, Storage
Barn, Excursion to the Quarry, Trident, Dwelling Plan) shipped as NON-passing
because `scripts/card_text.py` hid the `passing_left="X"` flag (it swept "X" into
its absent-placeholder skip), so implementers never saw it.

This test is the systemic backstop the tooling fix pairs with: it cross-checks the
LIVE registry against the raw catalog, so any future passing misclassification
fails here regardless of what the lookup tool shows.
"""
import json
from collections import defaultdict
from pathlib import Path

import agricola.cards  # noqa: F401  (populate registries)
from agricola.cards.specs import MINORS
from scripts.card_text import card_slug

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
_ROWS = json.load(open(_DATA / "revised_minor_improvements.json"))


def test_catalog_passing_matches_number_rule():
    """Data integrity: the catalog's `passing_left` flag is exactly the RULES
    'minors 001-009 are traveling cards' rule, for the whole minor catalog."""
    mismatches = [
        f"{r['deck']}{r['number']} {r['name']}"
        for r in _ROWS
        if bool(r.get("passing_left")) != (r["number"] <= 9)
    ]
    assert not mismatches, f"catalog passing_left disagrees with the #1-9 rule: {mismatches}"


# Traveling minors known to still disagree with the catalog, with the reason they
# aren't a one-line fix. REMOVE an entry when its card is corrected. (Empty: the
# dwelling_plan case was fixed 2026-07-13 via the generic PendingGrantedSubAction
# wrapper — a passing card's optional renovate can't ride an ownership-gated
# after_play_minor trigger, so its grant is now pushed from on_play.)
_KNOWN_PENDING = frozenset()


def test_implemented_minors_passing_matches_catalog():
    """Every implemented minor's spec.passing_left agrees with the catalog. For a
    duplicated card NAME (a slug that maps to >1 catalog row — e.g. the two
    'Market Stall's), the slug can't disambiguate which row is implemented, so we
    accept any of that name's catalog values; a UNIQUE name must match exactly."""
    by_slug = defaultdict(set)
    for r in _ROWS:
        by_slug[card_slug(r["name"])].add(bool(r.get("passing_left")))

    bad = []
    for slug, spec in MINORS.items():
        if slug in _KNOWN_PENDING:
            continue
        expected = by_slug.get(slug)
        if not expected:
            continue                       # e.g. a test-only fixture minor
        if spec.passing_left not in expected:
            bad.append(f"{slug}: spec.passing_left={spec.passing_left}, catalog={sorted(expected)}")
    assert not bad, "implemented minors whose passing flag disagrees with the catalog:\n" + "\n".join(bad)
