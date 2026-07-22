"""Task Artisan (occupation, A96; Artifex Expansion; players 1+).

Card text: "When you play this card and each time a stone accumulation space
appears on a round space in the preparation phase, you get 1 wood and a
\"Minor Improvement\" action."
Prerequisite: none. VPs: none. Played via Lessons.

Two halves, one package each time — a MANDATORY +1 wood ("you get") plus an
OPTIONAL "Minor Improvement" action (a granted sub-action is the player's to
take or decline; only "you must" is mandatory):

**The recurring half** rides the preparation ladder's `reveal` window (ruling
54, 2026-07-14 as revised — the window immediately after the round-card reveal
and the `__round_setup__` increment; `agricola/cards/preparation.py` names this
card as an intended member). "A stone accumulation space appears on a round
space" = a quarry (`western_quarry` / `eastern_quarry` — the only stone
accumulation spaces) was revealed by THIS round's preparation, which is
directly derivable from `ActionSpaceState.revealed_round` (user decision
2026-07-15: every reveal stamps the round it belongs to; permanents carry 0,
unrevealed None). At the `reveal` window the round increment has already
happened (`__round_setup__` precedes it), so the just-revealed quarry
satisfies `revealed_round == state.round_number`; a quarry revealed in an
earlier round has `revealed_round < round_number` and never re-fires.

- The wood is a mandatory, choice-free income → `register_auto("reveal", …)`.
  Window autos fire BEFORE the window's trigger frames are hosted
  (`_process_simple_window`), so the wood is on hand to pay the minor —
  it can itself make a hand minor affordable.
- The Minor Improvement action is an OPTIONAL trigger → `register("reveal", …)`
  surfaced as a FireTrigger at the window's choice host
  (`PendingHarvestWindow`); the host's Proceed IS the decline. Firing is the
  acceptance, so the apply pushes the reusable `PendingPlayMinor` directly
  (it has no decline of its own — it forces exactly one minor once pushed —
  so eligibility ALSO requires >= 1 playable hand minor,
  `legality.playable_minors`, never offering a dead-end). `triggers_resolved`
  on the host gives once-per-window automatically.

**The on-play half** ("When you play this card"): `on_play` grants the +1 wood
outright, then — because there is no host FireTrigger moment at play time to
carry the optionality — pushes the generic choose-or-decline wrapper
`PendingGrantedSubAction(subactions=("play_minor",))` (the Dwelling Plan
shape: the wrapper hosts the decline via Stop, and its enumerator re-gates the
offer on `playable_minors`). The wood lands BEFORE the playability check, so a
minor affordable only via the granted wood still gets the offer; with no
playable hand minor the wrapper is not pushed at all (nothing to offer but
Stop).

Hosting on the recurring half is eligibility-driven (the preparation ladder's
model — no hook registration): a window frame appears only on a round whose
reveal was a quarry, and only while a hand minor is playable.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_auto,
    register_named_action_grant,
)
from agricola.legality import playable_minors
from agricola.pending import PendingGrantedSubAction, PendingPlayMinor, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "task_artisan"

# The stone accumulation spaces (the only ones in the game).
_QUARRIES = ("western_quarry", "eastern_quarry")


def _quarry_appeared_this_round(state: GameState) -> bool:
    """Did THIS round's preparation reveal a quarry? At the `reveal` window the
    round increment has already run, so the just-revealed card's
    `revealed_round` equals `state.round_number` (permanents carry 0,
    earlier-round reveals a smaller number, unrevealed None)."""
    return any(
        get_space(state.board, q).revealed_round == state.round_number
        for q in _QUARRIES
    )


def _grant_wood(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _wood_eligible(state: GameState, idx: int) -> bool:
    return _quarry_appeared_this_round(state)


def _minor_eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # The window's wood auto has already fired (autos before frames), so this
    # affordability check sees the granted wood. `triggers_resolved` filtering
    # (once per window visit) is handled by the firing machinery.
    return (_quarry_appeared_this_round(state)
            and bool(playable_minors(state, idx)))


def _fire_minor(state: GameState, idx: int) -> GameState:
    # Firing IS the acceptance (the host's Proceed was the decline moment);
    # eligibility guaranteed a playable minor, so the no-decline
    # PendingPlayMinor never dead-ends.
    return push(state, PendingPlayMinor(
        player_idx=idx, initiated_by_id="card:task_artisan",
        minor_improvement_action=True))   # the named "Minor Improvement" action


def _on_play(state: GameState, idx: int) -> GameState:
    # Wood first — it may itself make a hand minor affordable for the grant.
    state = _grant_wood(state, idx)
    if playable_minors(state, idx):
        state = push(state, PendingGrantedSubAction(
            player_idx=idx, initiated_by_id="card:task_artisan",
            subactions=("play_minor",), minor_is_action=True))
    return state


def _grant_condition(state: GameState, idx: int, host) -> bool:
    """The recurring half's grant CONDITION for the unfired-decline seam (user
    ruling 76, 2026-07-21): a quarry appeared this round, read at the `reveal`
    window. Deliberately WITHOUT the playable-minor gate — that is DOABILITY,
    and a grant withheld as unaffordable still counts as declined per the
    ruling. (The ON-PLAY half is outside this seam — like Harvest Festival
    Planning, an on-play grant has no trigger to decline; its wrapper, when
    pushed, carries its own decline seam.)"""
    return (getattr(host, "window_id", None) == "reveal"
            and _quarry_appeared_this_round(state))


register_occupation(CARD_ID, _on_play)
# "each time a stone accumulation space appears on a round space in the
# preparation phase" — the preparation ladder's `reveal` window (ruling 54,
# 2026-07-14 as revised), read off `revealed_round` (user decision 2026-07-15).
register_auto("reveal", CARD_ID, _wood_eligible, _grant_wood)
register("reveal", CARD_ID, _minor_eligible, _fire_minor)
# The reveal-path granted named action's condition, for decline income
# (ruling 76, 2026-07-21).
register_named_action_grant(CARD_ID, "minor", _grant_condition, window="reveal")
