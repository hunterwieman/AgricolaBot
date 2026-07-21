"""Firewood (minor improvement, C75; Corbarius Expansion; players -).

Card text: "In the returning home phase of each round, place 1 wood on this
card. Each time before you build a Fireplace, Cooking Hearth, or oven, move up
to 4 wood from this card to your supply."
Cost: 2 Food. No printed VPs; no prerequisite. Not passing.

Category: Building Resource Provider. Two mechanisms, both governed by user
rulings 2026-07-21:

- THE DEPOSIT ("place 1 wood on this card") — a mandatory, choice-free effect
  each returning-home phase -> an automatic effect on the round-end ladder's
  ``returning_home`` window (`register_auto`; the Swimming Class exemplar,
  rulings 21/49). The wood comes from the GENERAL supply (user ruling
  2026-07-21: the text does not say "from your supply"), so the fire is a pure
  increment of the per-card CardStore stock counter — no player debit.
  Unconditioned on the round kind: it fires on harvest rounds too (the
  returning-home phase precedes the harvest, ruling 49).

- THE WITHDRAWAL ("Each time before you build a Fireplace, Cooking Hearth, or
  oven, move up to 4 wood from this card to your supply") — an optional
  trigger registered on BOTH ``before_build_major`` and ``before_play_minor``
  (both host enumerators surface before-phase triggers), because "Fireplace",
  "Cooking Hearth", and "oven" are the RULES.md COLLECTIVE terms (user ruling
  2026-07-21): they cover the majors — Fireplace (indices 0/1), Cooking Hearth
  (2/3), Clay Oven (5), Stone Oven (6) — AND the minor improvements whose slug
  ends ``_oven`` / ``_fireplace`` (today iron_oven and simple_oven are
  implemented; earth_oven / oriental_fireplace exist in the catalog for
  later). The qualifying-minor set is DERIVED by the slug-suffix rule, never a
  hardcoded id list, so future oven/fireplace minors qualify automatically —
  and "Oven Site" (``oven_site``) is correctly NOT an oven under the suffix
  rule.

  TAKE-MAX (user ruling 2026-07-21): "up to 4" is offered only as
  move-min(4, stock). Card wood is strictly less liquid than supply wood —
  this trigger is its only exit — so moving fewer than the maximum is
  dominated; the same loss-less action-shaping as Field Cultivator's
  ruling-41 take-the-maximum.

  FIRING RESTRICTS THE PENDING BUILD (user ruling 2026-07-21): the withdrawal
  is licensed only by a qualifying build, so the fire's apply intersects the
  frame's menu down to the qualifying targets — on `PendingBuildMajor`,
  ``allowed_majors`` ∩ {0, 1, 2, 3, 5, 6}; on `PendingPlayMinor`,
  ``allowed_cards`` set to the qualifying hand minors (∩ any existing
  restriction). Both frames are no-decline (their before-phase offers only
  commits), so ELIGIBILITY must guarantee a qualifying commit remains legal
  AFTER the restriction: it checks payability on a DOCTORED state with the
  withdrawn wood already added (`can_pay` / `playable_minors` on
  +min(4, stock) wood — the gate↔frontier-agreeing existence views the
  enumerators themselves use), threading the frame's ``granted_by`` provenance
  and ``min_spend`` exactly as `_enumerate_pending_build_major` does. (Base
  oven/fireplace costs contain no wood, but a conversion cost card could make
  wood load-bearing — the doctored check is the general form.)

MACHINERY NOTE — one card on two trigger events (the Merchant pattern):
`FireTrigger` dispatch is id-keyed (`_apply_fire_trigger` reads
``CARDS[card_id]``, one entry per card), so the second `register` call
overwrites the first's CARDS entry. That is benign here because BOTH
registrations share the SAME eligibility/apply pair — the shared fns dispatch
on the top frame's type (`PendingBuildMajor` vs `PendingPlayMinor`) — and
per-event eligibility surfacing reads the event-keyed ``TRIGGERS`` registry,
which keeps both entries.

KNOWN BOUNDARY (CARD_ENGINE_IMPLEMENTATION.md §8 — placement-time speculative
legality; documented, deliberately not worked around): if a player's ONLY
playable minor would need Firewood's wood FIRST, the parent's branch gate
(`playable_minors` on the un-doctored state) never offers the minor branch at
all, so the trigger has no frame to fire from — the accepted engine-wide
Pan-Baker/Potter shape. Currently unreachable: neither implemented oven minor
has wood in its cost (iron_oven costs 3 stone, simple_oven costs 2 clay). The
build-major side has the same shape (`_can_afford_any_major_improvement` on
the un-doctored state gates the branch), equally unreachable on printed costs
(no qualifying major's printed cost contains wood).

Played via an improvement space; on_play stays the default no-op (the deposit
and withdrawal are the whole card). The 2-food cost flows through the
food-payment layer automatically.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_auto
from agricola.legality import _build_major_ctx, can_pay, playable_minors
from agricola.pending import PendingBuildMajor, PendingPlayMinor, replace_top
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "firewood"

# The collective terms' major indices (user ruling 2026-07-21): Fireplace (0, 1),
# Cooking Hearth (2, 3), Clay Oven (5), Stone Oven (6). Well (4), Joinery (7),
# Pottery (8), and Basketmaker's Workshop (9) do not qualify.
QUALIFYING_MAJORS: tuple[int, ...] = (0, 1, 2, 3, 5, 6)

MAX_MOVE = 4


def _is_oven_or_fireplace_minor(cid: str) -> bool:
    """The slug-suffix rule (user ruling 2026-07-21): a minor is an "oven" /
    "Fireplace" iff its slug ends ``_oven`` / ``_fireplace``. Derived, never a
    hardcoded list — and it correctly excludes ``oven_site``."""
    return cid.endswith("_oven") or cid.endswith("_fireplace")


def _stock(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


# --- The deposit: the returning_home auto ------------------------------------

def _deposit_eligible(state: GameState, idx: int) -> bool:
    return True     # unconditional, every round (ownership gated by the registry)


def _deposit_apply(state: GameState, idx: int) -> GameState:
    """"Place 1 wood on this card" — from the GENERAL supply (user ruling
    2026-07-21), so no player debit: increment the CardStore stock counter."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, _stock(state, idx) + 1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- The withdrawal: shared eligibility/apply on both before-events ----------

def _doctored(state: GameState, idx: int) -> GameState:
    """`state` with the would-be withdrawal (min(4, stock) wood) already added
    to player `idx`'s supply — the payability probe for eligibility."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=min(MAX_MOVE, _stock(state, idx))))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _restricted_majors(top: PendingBuildMajor) -> tuple[int, ...]:
    """The post-fire build-major menu: QUALIFYING_MAJORS ∩ any existing
    ``allowed_majors`` restriction (None = the full board)."""
    if top.allowed_majors is None:
        return QUALIFYING_MAJORS
    return tuple(i for i in QUALIFYING_MAJORS if i in top.allowed_majors)


def _restricted_cards(state: GameState, idx: int, top: PendingPlayMinor) -> tuple[str, ...]:
    """The post-fire play-minor menu: the qualifying hand minors (slug-suffix
    rule) ∩ any existing ``allowed_cards`` restriction. Sorted -> canonical."""
    cids = [c for c in state.players[idx].hand_minors if _is_oven_or_fireplace_minor(c)]
    if top.allowed_cards is not None:
        cids = [c for c in cids if c in top.allowed_cards]
    return tuple(sorted(cids))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Stock >= 1 AND a qualifying commit remains legal AFTER the restriction,
    checked on the doctored (wood-added) state — never strand the no-decline
    frame. Dispatches on the top frame's type."""
    if _stock(state, idx) < 1:
        return False
    top = state.pending_stack[-1]
    if isinstance(top, PendingBuildMajor):
        owners = state.board.major_improvement_owners
        granted_by = (top.initiated_by_id
                      if top.initiated_by_id.startswith("card:") else None)
        doctored = _doctored(state, idx)
        return any(
            owners[i] is None
            and can_pay(doctored, idx,
                        _build_major_ctx(i, granted_by=granted_by,
                                         min_spend=top.min_spend))
            for i in _restricted_majors(top)
        )
    if isinstance(top, PendingPlayMinor):
        qualifying = _restricted_cards(state, idx, top)
        if not qualifying:
            return False
        composite = top.initiated_by_id == "major_minor_improvement"
        playable = playable_minors(_doctored(state, idx), idx,
                                   composite_only_ok=composite,
                                   min_spend=top.min_spend)
        return any(c in playable for c in qualifying)
    return False


def _apply(state: GameState, idx: int) -> GameState:
    """Move min(4, stock) wood from the card to the supply (take-max, user
    ruling 2026-07-21), then restrict the frame's menu to the qualifying
    targets. The firing machinery has already stamped `triggers_resolved`; this
    apply pushes nothing — it only edits the player and `replace_top`s."""
    stock = _stock(state, idx)
    take = min(MAX_MOVE, stock)
    p = state.players[idx]
    remaining = stock - take
    # Emptied stock -> remove the entry (the wild_greens "reset -> no entry"
    # idiom): logical-default-empty must hash like never-deposited.
    store = (p.card_state.remove(CARD_ID) if remaining == 0
             else p.card_state.set(CARD_ID, remaining))
    p = fast_replace(p, resources=p.resources + Resources(wood=take),
                     card_state=store)
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    top = state.pending_stack[-1]
    if isinstance(top, PendingBuildMajor):
        return replace_top(state, fast_replace(
            top, allowed_majors=_restricted_majors(top)))
    assert isinstance(top, PendingPlayMinor), (
        f"firewood fired on unexpected frame {type(top).__name__}")
    return replace_top(state, fast_replace(
        top, allowed_cards=_restricted_cards(state, idx, top)))


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)))
register_auto("returning_home", CARD_ID, _deposit_eligible, _deposit_apply)
# One card, two before-events, ONE shared eligibility/apply pair (the Merchant
# pattern — see the machinery note in the module docstring): the second call
# overwrites CARDS[CARD_ID] with an identical-apply entry, which is benign.
register("before_build_major", CARD_ID, _eligible, _apply)
register("before_play_minor", CARD_ID, _eligible, _apply)
