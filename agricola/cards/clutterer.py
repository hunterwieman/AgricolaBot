"""Clutterer (occupation, B100; Bubulcus Expansion; players 1+).

Card text: "During scoring, you get 1 bonus point for each card played after
this on[e] that has "accumulation space(s)" in its text."
Clarification: "This card only refers to cards played by the owner."
Category: Points Provider. No printed VPs.

COUNT AT PLAY TIME, not snapshot-diff. Tutor's snapshot-diff idiom (count at
scoring minus count at play) would silently miss a qualifying TRAVELING minor —
Wood Pile both names accumulation spaces in its text AND is a passing minor, so
the owner plays it (it must count) and it leaves their tableau (a scoring-time
diff would never see it). So instead each qualifying play is counted AS IT
HAPPENS: automatic effects on ``after_play_occupation`` + ``after_play_minor``
read the just-played card id off the host frame (``played_card_id``, stamped by
the executors at the commit) and increment the per-card CardStore counter; a
``register_scoring`` term reads the bank (user-confirmed 2026-07-14: passed-on
travelers count).

THE QUALIFYING SET is built once at import by scanning the catalog JSON
(``agricola/cards/data/revised_*.json``) for the literal phrase "accumulation
space" (case-insensitive — it matches both "accumulation space" and
"accumulation space(s)" wordings; 87 occupations + 57 minors today, no majors),
slugged by the same rule the web UI's catalog join uses (apostrophes dropped,
non-alphanumerics collapse to "_"). Membership is by catalog TEXT, so
unimplemented qualifying cards count the moment they become playable — no
per-card maintenance.

SCOPING — "only … the owner": these are own-action autos (no ``any_player``),
so they fire exactly for the player who just played the card, and only while
that player OWNS Clutterer (the registry's ownership gate) — which is also
precisely "played after this one": before Clutterer lands, it isn't owned and
nothing counts. Clutterer's own text contains the phrase, so its own play is
explicitly excluded (``played_card_id != CARD_ID``).

Card-game only (ownership-gated registries; the two stamped frames are
card-only), so the Family trace and the C++ gates are untouched.
"""
from __future__ import annotations

import json
import os
import re

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.cards.triggers import register_auto
from agricola.state import GameState

CARD_ID = "clutterer"


def _slug(name: str) -> str:
    """The catalog-name → card_id bridge (the web UI's `_card_slug` rule):
    apostrophes dropped, every other non-alphanumeric run collapses to "_"."""
    bare = name.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", bare).strip("_")


def _qualifying_ids() -> frozenset:
    """Slugs of every catalog card whose text contains "accumulation space"
    (which also matches the "accumulation space(s)" wording)."""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    out = set()
    for fname in ("revised_occupations.json", "revised_minor_improvements.json"):
        with open(os.path.join(data_dir, fname)) as f:
            for row in json.load(f):
                if "accumulation space" in (row.get("text") or "").lower():
                    out.add(_slug(row["name"]))
    return frozenset(out)


QUALIFYING_IDS: frozenset = _qualifying_ids()


def _eligible(state: GameState, idx: int) -> bool:
    """The just-played card (stamped on the play host) qualifies and is not
    Clutterer itself (its own text contains the phrase, but "played AFTER this
    one" excludes it)."""
    played = getattr(state.pending_stack[-1], "played_card_id", None)
    return played is not None and played != CARD_ID and played in QUALIFYING_IDS


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_play_occupation", CARD_ID, _eligible, _apply)
register_auto("after_play_minor", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
