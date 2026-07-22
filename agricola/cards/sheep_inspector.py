"""Sheep Inspector (occupation, deck D #93; Dulcinaria Expansion; players 1+).

Card text (verbatim): "Once per work phase, after you complete a person action,
you can pay 1 sheep and 2 food to return another person you placed home."
Category: Actions Booster. No printed VPs. On-play is a no-op.

GOVERNING RULINGS (all dated):

- USER RULING (2026-07-21, ruling 74, CARD_DEFERRED_PLANS.md): "after you
  complete a person action" = the ``after_action_space`` window of the OWNER's
  own action. The card hooks every space id (the Work Certificate full-
  ``SPACE_IDS`` shape), so each own placement gains a host frame whose
  after-phase offers the trigger.
- USER RULING (2026-07-21): NEWBORNS DO NOT COUNT as "another person you
  placed" — a newborn meeple must never be a return target. (Derivation of the
  exclusion below.)
- "Once per work phase" = the ``used_this_round`` latch (cleared at each round
  entry by ``engine._enter_new_round``).
- Return semantics mirror Tea Time (``agricola/cards/tea_time.py``): the person
  goes home (``people_home`` +1, so it may be placed again later this round),
  the target space's worker marker for the owner decrements, and the vacated
  space is OPEN — per the USER RULING (2026-07-20, Tea Time): what makes a
  space illegal to place on is the presence of a worker on it, nothing else.
- USER RULING (2026-07-21, ruling 74, CARD_DEFERRED_PLANS.md): the worker
  parked on Canal Boatman CAN be returned by this card. Implemented as the
  card-space extension below: the return targets also cover the owner's
  ``card_space_worker:`` markers (``agricola/cards/card_spaces.py``) — the one
  namespace recording every of the owner's workers sitting on a card, whether
  PLACED there (a registered card action space — Collector, Tree Inspector) or
  PARKED there by a card effect (Canal Boatman). A card holds no newborns (a
  wish-space growth puts its meeple on the BOARD), so every on-card marker is
  a returnable person; returning one is marker -1 + ``people_home`` +1
  (``card_spaces.return_card_space_worker`` — the same Tea Time semantics, and
  the vacated card space is OPEN).

MECHANICS. An OPTIONAL play-variant trigger (the Work Certificate idiom) on
``after_action_space``: one ``FireTrigger("sheep_inspector", variant=
"<space_id>")`` per legal return target (a board space id, or
``"card:<card_id>"`` for an on-card worker). A target is a space OTHER than the
one just used (the host frame's ``space_id`` — "another person") where the
owner has at least one returnable PLACED person (newborns excluded, below).
Eligibility: not latched this round, sheep >= 1 (on the farm) AND food >= 2 on
hand AND >= 1 legal target. Firing debits 1 sheep + 2 food, latches
``used_this_round``, credits ``people_home`` +1, and decrements the owner's
worker count on the chosen space (the Tea Time board edit). Declining is the
host's after-phase Stop. Own use only: the hook is own-use and the enumerator
routes on the host frame's player.

THE NEWBORN EXCLUSION — how "returnable placed persons on a space" is derived
from ``GameState``:

- A newborn meeple reaches the BOARD through exactly one mechanism:
  ``resolution._resolve_wish_for_children`` — shared by the two wish spaces
  (``basic_wish_for_children``, ``urgent_wish_for_children``) — which adds the
  newborn's marker to the wish space next to the parent (the owner's count
  there becomes 2). A card-granted growth (``PendingFamilyGrowth.
  place_on_space=False``) puts NO meeple on any space, and no other code path
  adds board workers beyond the one-per-placement of ``PlaceWorker``.
- On a NON-wish space every own meeple is therefore a placed person:
  returnable count = ``workers[idx]``.
- On a WISH space, growth is mandatory once placed (Basic Wish's card-mode host
  makes family growth the mandatory first sub-action; Urgent Wish's atomic
  resolver grows unconditionally) and placement is gated on the growth being
  legal — so a COMPLETED own use always leaves exactly 2 own meeples there:
  1 placed parent + 1 newborn. Returnable count = ``max(workers[idx] - 1, 0)``.
  This floor also classifies the one other reachable shape correctly: a LONE
  newborn (``workers[idx] == 1``, after this very card returned the parent —
  the only implemented effect that can vacate a parent from a wish space;
  Tea Time is Grain-Utilization-only) counts as 0 returnable.
- No reachable state is ambiguous: an under-count would need a wish space
  holding a placed parent and no newborn (impossible — growth is mandatory and
  nothing removes only the newborn before the round-end reset), and an
  over-count would need two placed own persons on one space (impossible — the
  occupancy-override cards, Imitator / Second Spouse / Forest School, all
  require ``workers[ap] == 0`` on the target, so an owner never stacks a
  second placed person on their own space; opponents' meeples live in the
  other ``workers`` slot). Variants are only computed inside an
  ``after_action_space`` window, i.e. between completed own turns — never
  mid-wish-turn.

Card-game only (ownership-gated registries; no new engine state), so the
Family trace and the C++ differential gates are untouched. See
CARD_ENGINE_IMPLEMENTATION.md §2 and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.card_spaces import (
    card_space_worker_count,
    return_card_space_worker,
)
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.constants import SPACE_IDS
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "sheep_inspector"

# The two spaces on which a newborn meeple can sit — exactly the spaces resolved
# by `resolution._resolve_wish_for_children`, the sole mechanism that puts a
# newborn on the board (a card-granted growth places no meeple anywhere).
_WISH_SPACES = frozenset({"basic_wish_for_children", "urgent_wish_for_children"})


def _returnable_count(state: GameState, idx: int, space_id: str) -> int:
    """How many of `idx`'s meeples on `space_id` are returnable PLACED persons.

    Non-wish space: every own meeple there is a placed person. Wish space: one
    meeple is the newborn (never a target — user ruling 2026-07-21), so one is
    subtracted, floored at 0 (a lone meeple on a wish space is the newborn —
    see the module docstring's derivation)."""
    w = get_space(state.board, space_id).workers[idx]
    if space_id in _WISH_SPACES:
        return max(w - 1, 0)
    return w


def _variants(state: GameState, idx: int) -> list[str]:
    """The currently-legal return targets, one variant per space OTHER than
    the just-used one (the host frame's space — "another person") where the
    owner has >= 1 returnable person. Board targets first (canonical
    SPACE_IDS order), then card-space targets — ``"card:<card_id>"`` for each
    of the owner's on-card workers (USER RULING 2026-07-21, ruling 74: the
    worker parked on Canal Boatman can be returned; the same markers cover a
    worker placed on a Collector / Tree Inspector card space). The host
    exclusion is uniform because a card-space host's ``space_id`` is
    ``"card:<id>"`` — the exact card-variant format."""
    host_space = getattr(state.pending_stack[-1], "space_id", None)
    board = [
        space_id
        for space_id in SPACE_IDS
        if space_id != host_space and _returnable_count(state, idx, space_id) >= 1
    ]
    # A ``card_space_worker:`` marker can exist only for a card in the OWNER's
    # own tableau: a card-space placement is enumerated only for an owned,
    # played, registered card, and Canal Boatman parks on itself (it must be
    # played to fire). Scanning the played-card ids through card_spaces'
    # public counter is therefore a complete enumeration of the marker
    # namespace. Sorted for a deterministic variant order.
    p = state.players[idx]
    cards = [
        f"card:{cid}"
        for cid in sorted(p.occupations | p.minor_improvements)
        if f"card:{cid}" != host_space and card_space_worker_count(p, cid) >= 1
    ]
    return board + cards


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "after YOU complete a person action": the hook is own-use and the
    # enumerator routes on the host frame's player, so idx is the acting player
    # whenever this runs — the guard is belt-and-braces (Work Certificate's
    # shape). Once per work phase via the used_this_round latch; the payment
    # (1 sheep from the farm + 2 food on hand) must be affordable; and there
    # must be a legal target (never a dead-end fire).
    top = state.pending_stack[-1]
    if getattr(top, "player_idx", None) != idx:
        return False
    p = state.players[idx]
    return (
        CARD_ID not in p.used_this_round
        and p.animals.sheep >= 1
        and p.resources.food >= 2
        and bool(_variants(state, idx))
    )


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one return: pay 1 sheep + 2 food, latch the round, and bring the
    chosen person home. Two target kinds share the payment (both are the Tea
    Time return idiom — person home, marker off, the vacated space OPEN,
    occupancy being solely worker presence):

    - board target (variant = a space id): the owner's worker marker on that
      space decrements; ``people_home`` +1.
    - card target (variant = ``"card:<card_id>"`` — USER RULING 2026-07-21,
      ruling 74: the worker parked on Canal Boatman can be returned): the
      on-card worker marker decrements and ``people_home`` +1, both via
      ``card_spaces.return_card_space_worker``.
    """
    # The payment edit: pay the cost, latch once-per-work-phase.
    p = state.players[idx]
    p = fast_replace(
        p,
        animals=p.animals - Animals(sheep=1),
        resources=p.resources - Resources(food=2),
        used_this_round=p.used_this_round | {CARD_ID},
    )
    state = fast_replace(
        state,
        players=tuple(
            p if i == idx else state.players[i] for i in range(len(state.players))
        ),
    )
    if variant.startswith("card:"):
        # Card target: marker -1 + people_home +1 in the one helper.
        return return_card_space_worker(state, idx, variant.split(":", 1)[1])
    # Board target: the person home + the owner's worker marker off the space.
    space_id = variant
    p = state.players[idx]
    state = fast_replace(
        state,
        players=tuple(
            fast_replace(p, people_home=p.people_home + 1) if i == idx
            else state.players[i]
            for i in range(len(state.players))
        ),
    )
    sp = get_space(state.board, space_id)
    workers = tuple(n - 1 if i == idx else n for i, n in enumerate(sp.workers))
    return fast_replace(
        state,
        board=with_space(state.board, space_id, fast_replace(sp, workers=workers)),
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# Optional after-window trigger on the owner's every action-space use
# (ruling 74: "after you complete a person action" = after_action_space).
register("after_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
# "a person action" = every space: hook the whole canonical list (atomic spaces
# are hosted only when hooked; non-atomic ids in the hook set are harmless).
register_action_space_hook(CARD_ID, SPACE_IDS)
