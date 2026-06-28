#!/usr/bin/env python
"""Look up the EXACT text (and cost/prereq/status) of Agricola cards by name or slug.

The card-authoring discipline (CARD_AUTHORING_GUIDE.md §1 step 1) is: never reason from
memory or a paraphrase — read the authoritative card text from the data files before
classifying or implementing a card. This tool makes that one command:

    python scripts/card_text.py "frame builder"        # substring match on the name
    python scripts/card_text.py millwright feed_fence   # several at once (name or slug)
    python scripts/card_text.py --exact "Carpenter"     # exact-name (case-insensitive)

It searches both `agricola/cards/data/revised_{occupations,minor_improvements}.json`,
prints every match verbatim, and notes whether the card is already IMPLEMENTED (its slug
is registered in the OCCUPATIONS / MINORS registries). Dependency-light: stdlib + the JSON
data; the implemented-check imports the card registries and degrades gracefully if that
fails.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
_FILES = ("revised_occupations.json", "revised_minor_improvements.json")


def card_slug(name: str) -> str:
    """Mirror of play_web._card_slug — slug(json_name) == card_id for implemented cards.
    Apostrophes are dropped (Shepherd's Crook -> shepherds_crook); other non-alnum runs
    collapse to a single '_'."""
    bare = name.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", bare).strip("_")


def _load() -> list[dict]:
    cards: list[dict] = []
    for fname in _FILES:
        cards.extend(json.loads((_DATA / fname).read_text()))
    return cards


def _implemented_slugs() -> set[str]:
    """The set of card_ids actually registered (built). Empty set if the import fails."""
    try:
        repo_root = str(Path(__file__).resolve().parent.parent)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        import agricola.cards  # noqa: F401  (runs every card module's register_* calls)
        from agricola.cards.specs import MINORS, OCCUPATIONS
        return set(OCCUPATIONS) | set(MINORS)
    except Exception as exc:  # pragma: no cover - diagnostic convenience only
        print(f"(note: could not load registries to mark implemented cards: {exc})",
              file=sys.stderr)
        return set()


def _matches(card: dict, query: str, *, exact: bool) -> bool:
    name = card["name"].lower()
    q = query.lower()
    if exact:
        return name == q or card_slug(card["name"]) == card_slug(query)
    return q in name or card_slug(query) in card_slug(card["name"])


def _fmt(card: dict, implemented: set[str]) -> str:
    slug = card_slug(card["name"])
    mark = "IMPLEMENTED" if slug in implemented else "not implemented"
    head = (f"{card['name']}  [{slug}]  ({mark})\n"
            f"  {card.get('type', '?')} · {card.get('expansion', '?')} · "
            f"deck {card.get('deck', '?')} #{card.get('number', '?')} · "
            f"players {card.get('players', '-')} · category {card.get('card_category', '-')}"
            f" · status {card.get('status', '-')}")
    lines = [head]
    # Minor-only structured fields (None/"X" when absent).
    for key, label in (("cost", "cost"), ("prerequisites", "prereq"),
                       ("vps", "vps"), ("passing_left", "passing_left")):
        if key in card and card[key] not in (None, "X", ""):
            lines.append(f"  {label}: {card[key]}")
    lines.append(f"  text: {card['text']}")
    # Compendium rulings (added from the Unofficial Compendium): clarifications are
    # community/official rulings; errata are official corrections (may change the card).
    if card.get("clarifications"):
        lines.append(f"  clarifications: {card['clarifications']}")
    if card.get("errata"):
        lines.append(f"  errata: {card['errata']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("queries", nargs="+", help="card name(s) / substring(s) / slug(s)")
    ap.add_argument("--exact", action="store_true",
                    help="match the full name (or slug) exactly, not as a substring")
    args = ap.parse_args()

    cards = _load()
    implemented = _implemented_slugs()
    any_found = False
    for q in args.queries:
        hits = [c for c in cards if _matches(c, q, exact=args.exact)]
        print(f"\n### query: {q!r} — {len(hits)} match(es)")
        for c in hits:
            print(_fmt(c, implemented))
            print()
        any_found = any_found or bool(hits)
    return 0 if any_found else 1


if __name__ == "__main__":
    raise SystemExit(main())
