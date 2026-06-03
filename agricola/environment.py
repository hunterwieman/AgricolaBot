"""The hidden ground truth + nature policy for one game.

The `Environment` holds the per-game stage-card reveal order — hidden
information that does NOT live in `GameState`. The game driver consults it to
resolve nature decisions (today: round-card reveals); agents and MCTS never
see it. See HIDDEN_INFO_DESIGN.md §3.4 / §3.6.
"""
from __future__ import annotations

from dataclasses import dataclass

from agricola.actions import Action, RevealCard
from agricola.state import GameState


@dataclass(frozen=True)
class Environment:
    """Hidden ground truth + nature policy. Today: the round-card order.

    Forward-compat (§3.6): future hidden state (each player's private hand, the
    draw deck) joins `round_card_order` here, and a per-player
    `observe(state, env, i)` projection splices player i's own slice back into
    their view (identity today, since the only hidden info is symmetric). The
    driver-facing seam is `resolve(state)`: whenever `decider_of(state) is None`
    (nature decides), the driver calls `env.resolve(state)` for the true action.
    """

    round_card_order: tuple  # length 14; order[i] is round i+1's card

    def resolve(self, state: GameState) -> Action:
        """Nature policy: the true action for the pending nature decision.

        Today the only nature decision is a stage-card reveal, so this delegates
        to `reveal_action`. Future nature events (card draft, draw) add branches
        here, dispatching on whatever nature pending is on top of the stack.
        """
        return self.reveal_action(state)

    def reveal_action(self, state: GameState) -> RevealCard:
        """The true `RevealCard` for the round being entered.

        `state.round_number` is the round just completed — the reveal turns up
        the NEXT round's card, `order[round_number]` (since `order[i]` is round
        `i + 1`'s card). At game start `round_number == 0`, so this turns up
        round 1's card, `order[0]` (the round-1 reveal `setup_env` resolves).
        """
        return RevealCard(self.round_card_order[state.round_number])
