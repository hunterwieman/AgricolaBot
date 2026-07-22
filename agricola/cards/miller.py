"""Miller (occupation, Ephipparius deck E #95; players 1+; category Actions Booster).

Card text (verbatim): "You can immediately build a baking improvement by paying its
cost. Each time another player uses the "Grain Seeds" action space, you can take a
"Bake Bread" action."

GOVERNING RULINGS (ruling 74, 2026-07-21, CARD_DEFERRED_PLANS.md):

- Clause 1's buildable menu is "baking majors + baking minors in hand" (user): the
  baking majors are indices {0, 1, 2, 3, 5, 6} (both Fireplaces, both Cooking
  Hearths, Clay Oven, Stone Oven — RULES.md's baking improvements) via
  `PendingGrantedSubAction.major_allowed`; the baking minors are the hand minors
  registered in the baking-spec identity seam (`BAKING_SPEC_EXTENSION_CARD_IDS` —
  Iron Oven, Simple Oven, Baking Course today; future members join automatically)
  via the wrapper's `play_minor` category restricted with
  `PendingPlayMinor.allowed_cards` (threaded through the wrapper's
  `minor_allowed`). The build is the card's OWN effect: bare frames,
  `minor_is_action=False`, never the composite. ONE USE TOTAL: "build A baking
  improvement" (singular) — the player builds a baking major OR plays a baking
  minor, not one of each, expressed as the wrapper's use-budget shape
  `max_uses=1` (the legacy per-category-once shape would wrongly allow both).
- Clause 1 is on-play and optional ("you can") → the `PendingGrantedSubAction`
  wrapper pushed by on_play, at NORMAL cost ("by paying its cost").
- Clause 2 (user-approved mechanism): `register_action_space_hook("miller",
  {"grain_seeds"}, any_player=True)` so the opponent's Grain Seeds use is hosted,
  plus an `any_player` before-auto on `before_action_space` whose eligibility is
  (the acting player is NOT the owner) AND (space is grain_seeds) AND (the owner
  can bake — `legality._can_bake_bread`) and whose apply pushes
  `PendingGrantedSubAction(player_idx=OWNER_IDX, initiated_by_id="card:miller",
  subactions=("bake_bread",))` on top of the host. The decider rule then routes
  the decision to the owner DURING the opponent's turn; the wrapper's Stop
  declines. Per the user's explicit ruling, the owner's bake resolves BEFORE all
  of the acting player's before-action triggers — guaranteed structurally: the
  any_player before-autos fire at the host's push (`_apply_place_worker` →
  `apply_auto_effects`), and the acting player's own before-triggers are surfaced
  only by the host's enumerator, which cannot run until the owner's wrapper (on
  top of the host) has popped.
- "Another player" never includes you: your own Grain Seeds use fires nothing.

Mechanics notes:

- Clause 1 mirrors Oven Site's on-play grant shape (the wrapper pushed
  unconditionally; its eligibility gates offer each `ChooseSubAction` only while
  that category is currently doable — a menu major unbuilt AND payable, or a
  MENU hand minor playable at its printed/alternative cost — else only Stop:
  never a dead-end). No cost modifier is registered under this card's id, so the
  grant-scoped cost context resolves to the printed cost — "by paying its cost".
  Building Clay/Stone Oven through the grant is a real major build
  (`_execute_build_major` pushes the oven's own free-bake host as normal), and
  playing Iron/Simple Oven through it is a real minor play (their on_play
  free-bake wrappers fire as normal).
- The minor menu is derived AT PUSH TIME from `BAKING_SPEC_EXTENSION_CARD_IDS`
  (the baking-spec identity seam — a card providing a baking rate IS a baking
  improvement), never a hard-coded list, so a future member (e.g. Oriental
  Fireplace) joins the menu the moment its module registers.
- Clause 2's auto registers with `order=10` (the Museum Caretaker explicit-order
  mechanism) so it fires LAST among the event's automatic effects: its apply
  pushes a frame on top of the host, and same-event peer autos (Corn Scoop,
  Sheep Provider, …) read the host off `pending_stack[-1]` — the push must come
  after they have fired. This is pure auto-vs-auto sequencing of same-instant
  mandatory effects; the ruling's ordering constraint (owner's bake before the
  acting player's before-TRIGGERS) is unaffected, since triggers are only
  surfaced after every auto has fired and the wrapper has popped.
- The auto's eligibility locates the grain_seeds host by scanning the stack
  (innermost frame whose PENDING_ID is the action_space bucket with
  `space_id == "grain_seeds"`) rather than assuming `pending_stack[-1]`: after
  this card's own push for one owner, the top frame is the wrapper, and reading
  `.space_id` off it would crash the loop's remaining owner check.
- Once per use: the auto fires exactly once per hosting (the
  `before_action_space` seam runs once, at the host push).

Card-game only (ownership-gated registries): the Family game and the C++
differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import BAKING_IMPROVEMENTS
from agricola.legality import BAKING_SPEC_EXTENSION_CARD_IDS, _can_bake_bread
from agricola.pending import PendingGrantedSubAction, push
from agricola.state import GameState

CARD_ID = "miller"
FRAME_ID = "card:miller"           # provenance on both granted wrappers
SPACES = frozenset({"grain_seeds"})

# Ruling 74: the baking majors — both Fireplaces (0, 1), both Cooking Hearths
# (2, 3), Clay Oven (5), Stone Oven (6). BAKING_IMPROVEMENTS is exactly this set.
BAKING_MAJOR_MENU = tuple(sorted(BAKING_IMPROVEMENTS))


# --- clause 1: on-play optional build of a baking improvement ----------------

def _on_play(state: GameState, idx: int) -> GameState:
    """Push the optional build grant (menu = the baking majors + the baking hand
    minors; normal cost; ONE use total).

    The wrapper's ChooseSubAction("build_major") / ChooseSubAction("play_minor")
    / Stop is the take-or-decline (granted sub-actions are optional).
    `max_uses=1` makes the two categories one-of: "build A baking improvement"
    (singular) — after either resolves, only Stop remains. The minor menu is
    derived here, at push time, from the baking-spec identity seam."""
    return push(state, PendingGrantedSubAction(
        player_idx=idx, initiated_by_id=FRAME_ID,
        subactions=("build_major", "play_minor"),
        major_allowed=BAKING_MAJOR_MENU,
        minor_allowed=tuple(sorted(BAKING_SPEC_EXTENSION_CARD_IDS)),
        max_uses=1))


# --- clause 2: the opponent's Grain Seeds use grants the owner a bake --------

def _grain_seeds_host(state: GameState):
    """The innermost action-space host for a Grain Seeds use, or None.

    Grain Seeds is atomic, so its host is always in the `action_space` PENDING_ID
    bucket with `space_id == "grain_seeds"`. Scanned (not `pending_stack[-1]`)
    because an earlier same-event auto — including this card's own push for the
    other owner in the `apply_auto_effects` loop — may sit above the host."""
    for frame in reversed(state.pending_stack):
        if (type(frame).PENDING_ID == "action_space"
                and frame.space_id == "grain_seeds"):
            return frame
    return None


def _eligible(state: GameState, owner: int) -> bool:
    """(acting is another player) AND (space is grain_seeds) AND (owner can bake)."""
    host = _grain_seeds_host(state)
    if host is None:
        return False
    if host.player_idx == owner:      # "another player" never includes you
        return False
    return _can_bake_bread(state, state.players[owner])


def _apply(state: GameState, owner: int) -> GameState:
    """Push the owner's optional bake wrapper on top of the acting player's host.

    The decider rule routes the wrapper (player_idx=owner) to the OWNER during
    the opponent's turn; ChooseSubAction("bake_bread") pushes the real
    PendingBakeBread primitive at the owner's own baking rates, Stop declines."""
    return push(state, PendingGrantedSubAction(
        player_idx=owner, initiated_by_id=FRAME_ID,
        subactions=("bake_bread",)))


register_occupation(CARD_ID, _on_play)
register_action_space_hook(CARD_ID, SPACES, any_player=True)
# order=10: fire last among the event's autos — this apply PUSHES a frame, and
# same-event peer autos read the host off pending_stack[-1] (see docstring).
register_auto("before_action_space", CARD_ID, _eligible, _apply,
              any_player=True, order=10)
