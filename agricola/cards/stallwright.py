"""Stallwright (occupation, E89; Ephipparius Expansion; players 1+).

Card text: "After you play your 2nd, 3rd, 5th, and 7th occupation (including this
one), you can build 1 stable at no cost."

User confirmation (2026-07-14): the grant is OPTIONAL ("you can"), and it is only
offered while the player has stable pieces left in supply.

An OPTIONAL trigger on `after_play_occupation` — the card says "After you play",
so it hooks the play-occupation host's AFTER window (explicit "after" wording; the
before-fires-by-default rule does not apply). The grant is keyed to the GAME-TOTAL
occupation count: at the after window the just-played occupation — including
Stallwright itself, per "(including this one)" — is already in `p.occupations`
(resolution.py `_execute_play_occupation` adds it before the after phase), so
`len(p.occupations)` IS the 1-based ordinal of the play that just happened.

- **Eligibility**: the ordinal is one of {2, 3, 5, 7}, AND the free stable is
  actually buildable right now — `_can_build_stable` with a zero cost checks
  >= 1 stable piece in supply (`stables_in_supply`, the card-removal-aware count,
  per the user's explicit supply condition) plus a legal empty cell — AND the
  trigger has not already fired this play (`triggers_resolved`). Never a dead-end.
- **Firing** pushes the reusable `PendingBuildStables` primitive with a FREE cost
  (`Resources()`) and `max_builds=1` — one free stable (mirrors Mining Hammer's
  free-stable push). `build_stables_action=False`: this is a card effect, not the
  literal Build Stables action, so action-scoped stable-build triggers do not fire
  on it (mirrors Stable C2's push; today the flag has no consumer — forward-compat).
- **Declining** = not firing (the play host's Stop pops the after phase). A
  declined ordinal is gone forever — the occupation count only moves forward — so
  no latch is needed beyond the host's per-visit `triggers_resolved`.

Note (ruling 60, 2026-07-14 — the deferred after-flip): the after window surfaces
only once the played occupation's own on_play (and everything it pushed) has fully
resolved, so if the qualifying occupation is itself an on-play-pushing card,
Stallwright's offer comes after that chain completes. Correct per the rules.

Ordinals count LIFETIME occupation plays, not plays-while-owned: like Education
Bonus, the hook fires only on the ACT of playing an occupation while Stallwright
is in the tableau, but the ordinal it checks is `len(p.occupations)` — so with
Stallwright played 4th, the next play is the 5th and qualifies.

See CARD_AUTHORING_GUIDE.md §3 (firing model) / Mining Hammer + Education Bonus
(templates).
"""
from __future__ import annotations

from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "stallwright"
_FREE = Resources()

# Qualifying 1-based occupation-play ordinals, from the printed text.
_ORDINALS = frozenset({2, 3, 5, 7})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in triggers_resolved
            and len(p.occupations) in _ORDINALS
            and _can_build_stable(state, p, _FREE))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id="card:stallwright",
        cost=_FREE, max_builds=1, build_stables_action=False))


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (trigger-only card)
register("after_play_occupation", CARD_ID, _eligible, _apply)
