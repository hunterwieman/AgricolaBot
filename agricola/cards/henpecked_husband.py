"""Henpecked Husband (occupation, Dulcinaria Expansion; deck D #94; players 1+).

Card text (verbatim): "Each time you take a "Build Rooms" action with the
second person you place, return the first person you placed home, unless it
is on the "Meeting Place" action space."
No cost / prerequisite / printed VPs; not a passing card. On-play is a no-op —
the effect is purely recurring.

GOVERNING RULINGS (user 2026-07-21, ruling 74 — CARD_DEFERRED_PLANS.md):

- It is an **``after_build_rooms`` AUTO** (mandatory — no "can" in the text).
- The gate: a **named** Build Rooms action — the frame's
  ``build_rooms_action == True`` — taken on the turn initiated by the owner's
  **second placement** this round. Card-granted named Build Rooms actions
  riding that turn are INCLUDED (the House Artist A149 × Traveling Players
  case); room-effect builds with the flag False (the Cottager shape) never
  count.
- Personless named builds (Wood Saw E14's "take a Build Rooms action without
  placing a person") are EXCLUDED via the explicit module-level exclusion
  frozenset of card ids below (``_PERSONLESS_BUILD_CARDS``) — **empty today**;
  any future personless-build card must add its id here (breadcrumb also
  recorded in ruling 74).
- The first placement's space is recorded per-round in the card's own
  CardStore; no return when that space is ``meeting_place`` (the printed
  exception).

MECHANISM — two pieces:

1. **Recording.** ``register_action_space_hook`` over the full canonical
   ``SPACE_IDS`` (the Work Certificate every-space hook: atomic spaces are
   hosted only when hooked, so every own placement gains a host frame while
   the card is owned — non-atomic ids in the set are harmless) + a
   ``before_action_space`` AUTO that, when the owner's placement ordinal this
   round == 1, stores ``(round_number, space_id)`` in CardStore. The ordinal
   is the standard "Nth WORKER placed this round" idiom
   ``(people_total − newborns) − people_home`` — ``before_action_space`` fires
   AFTER ``_apply_worker_placement`` decremented ``people_home`` for the
   placement now resolving, and subtracting same-round newborns is
   load-bearing (the Catcher bug: a Wish-for-Children birth bumps
   ``people_total`` without consuming a ``people_home`` worker;
   CARD_ENGINE_IMPLEMENTATION.md §6).

2. **The return.** An ``after_build_rooms`` AUTO (fires at the
   ``PendingBuildRooms`` host's after-flip, the frame still on top).
   Eligible iff: the top build-rooms frame belongs to the owner AND
   ``frame.build_rooms_action`` AND the frame's provenance is not a
   personless-build card AND the owner's placement ordinal this round == 2
   AND a first-placement record exists for THIS round (a stale prior-round
   record never fires) AND that space is not ``meeting_place`` AND the owner
   still has a worker on that space — if the first person already went home
   some other way, there is nothing to return and the auto silently doesn't
   fire. Applying returns that worker home with Tea Time's exact semantics
   (``people_home`` +1, the space's owner worker count −1, the vacated space
   OPEN — placement legality is solely worker-presence, user ruling
   2026-07-20 on Tea Time).

Card-game only (ownership-gated registries; CardStore is default-skipped in
canonical), so the Family game is byte-identical and the C++ differential
gates are untouched. See CARD_ENGINE_IMPLEMENTATION.md §2/§6 and
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import SPACE_IDS
from agricola.pending import PendingBuildRooms
from agricola.replace import fast_replace
from agricola.state import GameState, get_space, with_space

CARD_ID = "henpecked_husband"

_MEETING_PLACE = "meeting_place"

# Personless named Build Rooms actions (Wood Saw E14's "take a Build Rooms
# action without placing a person") do NOT count as taken "with the second
# person you place" (user ruling 74, 2026-07-21): a frame whose provenance
# card id is in this set never fires the return. EMPTY today — any future
# personless-build card must add its id here (the breadcrumb is also recorded
# in CARD_DEFERRED_PLANS.md, ruling 74).
_PERSONLESS_BUILD_CARDS: frozenset[str] = frozenset()


def _placement_ordinal(p) -> int:
    """The "Nth WORKER placed this round" index, including the placement now
    resolving: ``(people_total − newborns) − people_home``. The ``− newborns``
    term cancels the ``people_total`` growth of a same-round birth that did
    not consume a ``people_home`` worker (the Catcher bug —
    CARD_ENGINE_IMPLEMENTATION.md §6)."""
    return (p.people_total - p.newborns) - p.people_home


def _update_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


# ---------------------------------------------------------------------------
# (1) Recording — the first placement's space, per round
# ---------------------------------------------------------------------------

def _record_eligible(state: GameState, idx: int) -> bool:
    # before_action_space fires right after _apply_worker_placement decremented
    # people_home for this placement, with the just-pushed space host on top —
    # ordinal == 1 IS "the first person you place this round".
    return _placement_ordinal(state.players[idx]) == 1


def _record_apply(state: GameState, idx: int) -> GameState:
    """Stamp (round_number, space_id) of the owner's first placement this
    round. Every space-host frame exposes the uniform ``space_id`` accessor
    (read off ``initiated_by_id``)."""
    sid = state.pending_stack[-1].space_id
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, (state.round_number, sid)))
    return _update_player(state, idx, p)


# ---------------------------------------------------------------------------
# (2) The return — after a named Build Rooms action on the second placement
# ---------------------------------------------------------------------------

def _return_eligible(state: GameState, idx: int) -> bool:
    if not state.pending_stack:
        return False
    top = state.pending_stack[-1]
    if not isinstance(top, PendingBuildRooms):
        return False
    # The owner's own frame, and the NAMED Build Rooms action only (ruling 74 /
    # the §9.6 flag contract): a room-effect build (Cottager, flag False)
    # never counts.
    if top.player_idx != idx or not top.build_rooms_action:
        return False
    # A personless named build (provenance in the exclusion set) was not taken
    # "with the second person you place" (ruling 74). Card-grant provenance is
    # "card:<id>"; the trailing id is what the set holds.
    if top.initiated_by_id.split(":", 1)[-1] in _PERSONLESS_BUILD_CARDS:
        return False
    p = state.players[idx]
    # "with the second person you place": the turn was initiated by the
    # owner's second placement this round.
    if _placement_ordinal(p) != 2:
        return False
    rec = p.card_state.get(CARD_ID)
    if rec is None:
        return False
    rec_round, first_space = rec
    if rec_round != state.round_number:
        return False                    # stale prior-round record never fires
    if first_space == _MEETING_PLACE:
        return False                    # the printed exception
    # If the first person already went home some other way, there is nothing
    # to return — silently don't fire.
    if first_space.startswith("card:"):
        # The first placement was on a CARD action space (ruling 74,
        # 2026-07-21 — card spaces count as action spaces for other cards'
        # hooks; Collector / Tree Inspector). That person is a placed person
        # like any other and Collector is not Meeting Place, so the printed
        # return applies; the worker record is the on-card marker, not a
        # board `workers` tuple.
        from agricola.cards.card_spaces import card_space_worker_count
        return card_space_worker_count(p, first_space.split(":", 1)[1]) >= 1
    return get_space(state.board, first_space).workers[idx] >= 1


def _return_apply(state: GameState, idx: int) -> GameState:
    """Return the first person placed this round home (Tea Time's semantics:
    the space's owner worker count −1, ``people_home`` +1, the space OPEN)."""
    _rec_round, first_space = state.players[idx].card_state.get(CARD_ID)
    if first_space.startswith("card:"):
        # A CARD action space (ruling 74): the machinery's return helper —
        # marker cleared, people_home +1, and the vacated card space is OPEN
        # (occupancy is solely worker presence, the Tea Time ruling).
        from agricola.cards.card_spaces import return_card_space_worker
        return return_card_space_worker(state, idx, first_space.split(":", 1)[1])
    sp = get_space(state.board, first_space)
    workers = tuple(
        n - 1 if i == idx else n for i, n in enumerate(sp.workers))
    state = fast_replace(
        state,
        board=with_space(state.board, first_space,
                         fast_replace(sp, workers=workers)))
    p = state.players[idx]
    return _update_player(state, idx, fast_replace(
        p, people_home=p.people_home + 1))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# Recording: every own placement is hosted (the Work Certificate full-SPACE_IDS
# hook) and the before-auto stamps the first placement's space per round.
register_auto("before_action_space", CARD_ID, _record_eligible, _record_apply)
register_action_space_hook(CARD_ID, SPACE_IDS)
# The return: mandatory, at the named Build Rooms action's after-flip.
register_auto("after_build_rooms", CARD_ID, _return_eligible, _return_apply)
