"""Earthenware Potter (occupation, D99; Dulcinaria Expansion; players 1+).

Card text (verbatim): "If you play this card in round 4 or before, after the
final harvest, you get 1 bonus point for each person for which you then pay 1
clay."

Category: Points Provider. Occupation — no printed cost / prerequisite / VPs
(the JSON row carries only name / category / text).

What the card does in game terms: play it early (round 4 at the latest), and
after the game's last harvest you may buy bonus points at 1 clay per point, at
most one point per person in your family. Played round 5 or later it does
nothing — that is the PRINTED condition ("if you play this card in round 4 or
before"), not an engine limitation.

PLAY-ROUND SNAPSHOT — the round-4 gate is a play-TIME quantity: by the time the
effect fires the round is 14, so the play round cannot be reconstructed then.
``_on_play`` therefore snapshots ``state.round_number`` into the per-card
CardStore under ``CARD_ID`` (the Butler idiom — Butler C100 has the same
played-by-round-N shape). The stored value is the round itself, not the gate
bit, so the web UI can privately show the owner whether the bonus is still
available (Butler's ``PRIVATE_HISTORY_CARDS`` treatment; ``agricola.cards.display``
already names Earthenware Potter as belonging there when wired).

TIMING — "after the final harvest" IS the ``after_harvest`` window at round 14
(user ruling 2026-07-06): the same instant Elephantgrass Plant's "immediately
after each harvest" fires, which the harvest walk (``engine._advance_harvest``)
runs after the round-14 harvest completes — the ladder's last window, resolved
immediately before the walk exits into BEFORE_SCORING. The eligibility gate
``state.round_number == 14`` restricts it to the FINAL harvest (the walk runs
``after_harvest`` on every harvest round {4, 7, 9, 11, 13, 14}; round_number is
only incremented in the NEXT round's preparation, so during round 14's harvest
it still reads 14 — the Transactor D98 round-gate idiom).

THE CHOICE — "for each person for which you THEN pay 1 clay": the player freely
chooses how many people to pay for (user ruling 2026-07-06): k in
1..min(clay, people_total), one play-variant per k, surfaced as
``FireTrigger(card_id, variant=str(k))`` on the per-player
``PendingHarvestWindow`` host; declining entirely is the frame's ``Proceed``.
"Person" = ``people_total`` (home + placed), which INCLUDES newborns — they are
people (this module's reading, noted per the wave-3 brief). Firing k debits k
clay and banks k bonus points; the window trigger machinery carries no cost
layer, so ``_apply`` debits the clay itself, and affordability (>= 1 clay) is
checked in ``_eligible`` / ``_variants`` so no unpayable variant is ever
surfaced. Once-per-window comes free from the frame's ``triggers_resolved``
(and the round-14 window happens once per game anyway).

SCORING — there is no immediate-VP mechanism, so the banked points live in a
SECOND CardStore key, ``_VP_KEY`` (= "earthenware_potter_vp"; the Lunchtime
Beer two-key idiom — ``CARD_ID`` itself holds the play-round snapshot), read
back by the registered scoring term at end-game. No ``vps=`` spec field exists
for occupations, and the points are earned, not printed.

Card-only state (the two CardStore entries) is empty in the Family game, so the
Family engine stays byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "earthenware_potter"
WINDOW_ID = "after_harvest"
_VP_KEY = f"{CARD_ID}_vp"
_FINAL_ROUND = 14
_PLAY_DEADLINE = 4  # "in round 4 or before"


def _on_play(state: GameState, idx: int) -> GameState:
    """Snapshot the play round (the only moment it is visible — the effect fires
    in round 14). The <= 4 gate is applied at eligibility, not here: the round is
    recorded unconditionally (rounds are 1..14, so a stored value is always
    truthy), mirroring Butler."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, state.round_number))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the buy iff the owner played the card in round 4 or before, this is
    the FINAL harvest's after_harvest window (round 14), and at least 1 clay is
    held (the smallest buy is k=1). Ownership and the once-per-window guard are
    enforced by the host enumerator (``_owns`` / the frame's ``triggers_resolved``);
    ownership is also short-circuited here so the trigger is never surfaced — nor
    a window frame pushed — for a non-owner."""
    p = state.players[idx]
    if CARD_ID not in p.occupations:
        return False
    play_round = p.card_state.get(CARD_ID, 0)
    if not (1 <= play_round <= _PLAY_DEADLINE):
        return False  # played round 5+ (or never snapshotted): the printed condition fails
    if state.round_number != _FINAL_ROUND:
        return False
    return p.resources.clay >= 1


def _variants(state: GameState, idx: int) -> list[str]:
    """One variant per buyable count: k in 1..min(clay, people_total) — the
    player freely chooses how many people to pay for (user ruling 2026-07-06);
    declining entirely is the frame's Proceed, not a variant. Mirrors
    ``_eligible``'s gates so the enumerator never surfaces an unaffordable or
    mis-timed variant."""
    if not _eligible(state, idx, frozenset()):
        return []
    p = state.players[idx]
    k_max = min(p.resources.clay, p.people_total)
    return [str(k) for k in range(1, k_max + 1)]


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Pay k clay, bank k bonus points (1 point per person paid for). The window
    trigger machinery carries no cost layer, so the clay is debited here, in the
    same step that banks the points."""
    k = int(variant)
    p = state.players[idx]
    banked = p.card_state.get(_VP_KEY, 0)
    p = fast_replace(
        p,
        resources=p.resources + Resources(clay=-k),
        card_state=p.card_state.set(_VP_KEY, banked + k),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """The banked bonus points (0 if the buy never fired)."""
    return state.players[idx].card_state.get(_VP_KEY, 0)


# On-play: snapshot the play round (the round-4 gate is read back at round 14).
register_occupation(CARD_ID, _on_play)

# The round-14 after_harvest buy: an optional play-variant trigger — pay k clay
# for k bonus points, k in 1..min(clay, people_total) (user ruling 2026-07-06).
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, WINDOW_ID)

register_scoring(CARD_ID, _score)
