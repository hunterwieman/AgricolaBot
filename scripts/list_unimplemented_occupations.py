#!/usr/bin/env python
"""List the occupations that are NOT yet implemented and NOT decided against.

A card counts as *unimplemented* when its slug is absent from the live `OCCUPATIONS`
registry (no card module has registered it), and *not decided against* when the catalog
JSON does not mark it `wontfix`. Everything else — including cards merely *deferred*
pending a rules/infrastructure decision — is listed, because deferred is not the same as
rejected.

Because it reads the registry live at every run, the output always reflects the current
state of the catalog: implement a card, and it drops off this list automatically.

    python scripts/list_unimplemented_occupations.py                 # grouped terminal list
    python scripts/list_unimplemented_occupations.py --deck E         # only deck E
    python scripts/list_unimplemented_occupations.py --category "Food Provider"
    python scripts/list_unimplemented_occupations.py --players 1+     # by player-count band
    python scripts/list_unimplemented_occupations.py --count          # just the tallies
    python scripts/list_unimplemented_occupations.py --markdown out.md
    python scripts/list_unimplemented_occupations.py --html out.html  # filterable web page

The web page adds a Players filter (1+ / 3+ / 4+) on top of the deck and category filters.
The minors twin is scripts/list_unimplemented_minors.py; both share the rendering core in
scripts/_unimplemented_cards.py.
"""
from __future__ import annotations

from _unimplemented_cards import run

if __name__ == "__main__":
    run(
        json_filename="revised_occupations.json",
        registry_name="OCCUPATIONS",
        noun="Occupations",
    )
