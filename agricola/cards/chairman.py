"""Chairman (occupation, D139; Dulcinaria Expansion; players 3+).

Card text: "Each time another player uses the 'Meeting Place' action space, both
they and you get 1 food (before taking the actions). If you use it, you get 1
food."

An opponent-action hook (the Milk Jug shape) on Meeting Place, fired in the BEFORE
phase — the parenthetical "before taking the actions" makes the timing explicit,
and it matches the "each time [someone] uses [a space]" → before ruling. Mandatory
and choiceless → an automatic effect (register_auto) with ``any_player=True`` so it
runs for its OWNER on either player's Meeting Place turn.

The two clauses collapse to: the owner always gets 1 food; if the ACTOR is not the
owner, the actor also gets 1 food. (Actor == owner is the "if you use it" clause:
the owner gets 1 food, once.)

Meeting Place is NON-ATOMIC and SELF-HOSTING in the card game
(engine._apply_place_worker dispatches it to _initiate_meeting_place_cards, which
pushes PendingMeetingPlace and fires before_action_space at the push), so it must
NOT be given a register_action_space_hook — hooking a self-hosting space
double-hosts it and soft-locks the turn (milk_jug.py / sugar_baker.py note the same
rule). On-play is a no-op. Card-game only (ownership-gated registries), so the
Family trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "chairman"


def _eligible(state: GameState, owner: int) -> bool:
    # owner is the any-player owner ("you"); fire on any Meeting Place use.
    return state.pending_stack[-1].space_id == "meeting_place"


def _apply(state: GameState, owner: int) -> GameState:
    actor = state.pending_stack[-1].player_idx
    players = list(state.players)
    players[owner] = fast_replace(
        players[owner], resources=players[owner].resources + Resources(food=1))
    if actor != owner:
        players[actor] = fast_replace(
            players[actor], resources=players[actor].resources + Resources(food=1))
    return fast_replace(state, players=tuple(players))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply, any_player=True)
# NO register_action_space_hook: Meeting Place is self-hosting in the card game.
