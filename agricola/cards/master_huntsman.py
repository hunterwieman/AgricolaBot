"""Master Huntsman (occupation, E165; Ephipparius Expansion; players 4+; Livestock
Provider).

Card text (verbatim): "When you play this card and each time you build a major
improvement, you get 1 wild boar."
No clarifications / errata printed.

Two mandatory, choice-free +1 wild boar grants:

- **On play** — a one-time boar gain at play time (`on_play`), routed through
  `helpers.grant_animals` so an over-capacity farm is reconciled by the
  accommodation barrier (1 boar fits a default farm's house-pet slot).

- **Each major-improvement build** — "each time you build a major improvement" is
  a flat reward (a fixed boar, independent of WHICH major was built), so by the
  Trigger-Timing ruling it fires in the BEFORE phase: `before_build_major`, the
  event `engine._fire_subaction_before_auto` fires at the moment ChooseSubAction
  pushes the PendingBuildMajor leaf (uniformly across every build-major entry
  point — the Major Improvement space, House Redevelopment, Meeting Place). Only
  MAJOR improvements count (not minors), so it registers on `before_build_major`
  alone — Wood Workshop's scope, minus the `before_play_minor` half. MANDATORY and
  choice-free → an automatic effect (`register_auto`), granting through
  `grant_animals`. Self-play is not a concern: playing Master Huntsman is an
  occupation play, not a major build, so it never fires this auto for itself.

Played via Lessons. The registry is empty in the Family game, so it stays
byte-identical and the C++ gates are untouched. See wood_workshop.py (the flat
`before_build_major` grant) and shepherds_crook.py (grant_animals).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import grant_animals
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "master_huntsman"


def _on_play(state: GameState, idx: int) -> GameState:
    """"When you play this card ... you get 1 wild boar."""
    return grant_animals(state, idx, Animals(boar=1))


def _eligible(state: GameState, idx: int) -> bool:
    # before_build_major fires only for a major-improvement build; the flat +1
    # boar has nothing to gate on.
    return True


def _apply(state: GameState, idx: int) -> GameState:
    """"...each time you build a major improvement, you get 1 wild boar."""
    return grant_animals(state, idx, Animals(boar=1))


register_occupation(CARD_ID, _on_play)
register_auto("before_build_major", CARD_ID, _eligible, _apply)
