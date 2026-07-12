"""Card-fields — the shared machinery for "this card is a field" cards.

Nine catalog cards print some form of "this card is a field" (Beanfield,
Lettuce Patch, Melon Patch, Cherry Orchard, Artichoke Field, Crop Rotation
Field, Patch Caregiver, Wood Field, Rock Garden): crops — or, on three of
them, wood/stone — are sown onto the CARD and harvested from it by the
field-phase take, exactly like a board field except that the card occupies no
farmyard cell. This module is the one place that knows what a card-field is:
the registry of specs, the CardStore crop-state shape, and the read helpers
every consumer (the sow enumerator/executor, `resolution.field_take`, the
take-modifier folds, scoring's field/crop counts, the ~20 implemented
"N fields"-reading cards) goes through.

The governing user rulings (CARD_DEFERRED_PLANS.md, all dated):

- **Ruling 45 (2026-07-12)** — the lexicon: "field TILES" means the plowed
  fields on the farmyard grid; "field" is the BROADER category and includes
  card-fields. A card-field therefore counts for field-count readers (the
  Fields scoring category, "N fields" requirements, "grain field" tests) —
  each card counting as exactly 1 field — while per-TILE readers exclude it
  (ruling 32, 2026-07-06: a card-field is NEVER a "field tile"; its manifest
  entries have source "card:<id>", and tile counters filter to "cell:" —
  Field Cultivator, Lynchet). Bale of Straw's printed text confirms the
  reading in the catalog's own words: "at least 3 grain fields (including
  field cards with planted grain)".
- **Ruling 46 (2026-07-12)** — per-FIELD harvest modifiers (Scythe Worker,
  Stable Manure, Grain Thief, Scythe E73) reach card-fields holding the
  qualifying crop. Their folds address a card stack by the take-target key
  ("card", card_id, stack_idx) — the card-side analog of the grid's
  (row, col).
- **Ruling 47 (2026-07-12)** — Wood Field's "as though it were 2 fields" /
  Rock Garden's "3 fields" = that many independently-sowable STACKS; the
  field-phase take harvests 1 from EACH non-empty stack; "but it is
  considered 1 field" scopes only the ruling-45 field-count readers (the
  card counts once, however many stacks it has).
- **Ruling 48 (2026-07-12)** — the sow-grant lexicon: a GENERIC "Sow" grant
  (even capped, "for exactly 1 field") may sow wood/stone card-fields; a
  CROPS-EXPLICIT grant ("sow crops") may not (`PendingSow.crops_only`). Cap
  accounting: a card-field consumes exactly ONE field-unit of a capped sow's
  budget regardless of stacks, and that one unit may fill any subset of its
  empty stacks.
- **Rulings 43/44 (2026-07-12)** — the card-fields' own "immediately"
  reactions (Lettuce Patch's convert, Crop Rotation Field's re-sow) surface
  on the take occasion's optional-trigger stretch, alongside Food Merchant.

THE STATE SHAPE. A card-field's contents live in the owner's `CardStore`
under the card's own id, as a tuple of per-stack 4-tuples
``(grain, veg, wood, stone)`` — one 4-tuple per stack, ``(0, 0, 0, 0)`` for
an empty stack. A stack mirrors a grid cell's crop capacity rather than
holding a single tagged good because a card-field IS a field, and implemented
cards already create MIXED fields: Heresy Teacher places "1 vegetable ...
below the grain" in any field with 3+ grain (per ruling 45 a grain-holding
card-field qualifies), exactly as it does on a grid cell. Take precedence
within a stack follows the grid cell's: grain, then veg (RULES.md — the elif
in `field_take`), then wood, then stone (a stack never mixes a crop with
wood/stone: the specs' sow whitelists forbid it, and no card adds one to the
other).

The stack tuple is kept SORTED DESCENDING (`_canon_stacks`): stacks carry no
identity anywhere in the rules (the cards' self-triggers are all card-level),
so two stores with the same multiset of stacks must be structurally identical
for state hashing. An ALL-EMPTY card-field is stored as NO entry at all
(`stacks_to_store` removes it): a never-sown Beanfield and a
sown-then-harvested-out one are the same logical state and must hash alike.
All of this is card-only CardStore content — the Family game never constructs
any of it, the canonical serialization is untouched at default, and the C++
engine needs no change.

MANIFEST SHAPE. The take emits one `HarvestEntry(source="card:<id>", crop,
amount, emptied)` per non-empty stack, `emptied` meaning the take removed the
last of THAT crop from THAT stack (the grid entries' semantics). Every
current per-FIELD consumer is safe with per-stack entries: the only
multi-stack cards (Wood Field, Rock Garden) grow wood/stone, which no
grain/veg reader counts. A FUTURE per-FIELD reader that could see a
multi-stack card's entries must dedupe by source (the card is ONE field,
ruling 47). Card-level "last X from this card" self-triggers (Cherry
Orchard, Melon Patch, Crop Rotation Field) read the post-take store
(`card_holds` == 0) alongside the occasion's entry for their card.

"Remove the last crop" reactors (Crop Rotation Field's "remove" — the E-deck
verb, ANY departure): the take is today's ONLY path that removes crops from a
card-field, and it emits an occasion — so the reactor rides the standard
occasion-trigger seam, and no separate removal chokepoint exists yet. A
future non-take remover (Game Provider's field-crop discard) must host the
reactor at its own instant; build the chokepoint then, with that consumer.
"""
from __future__ import annotations

from dataclasses import dataclass

# The goods a card-field can hold, in take-precedence order (grain before veg
# mirrors the grid cell's elif; wood/stone never co-reside with crops).
GOODS: tuple[str, ...] = ("grain", "veg", "wood", "stone")
_GOOD_IDX: dict[str, int] = {g: i for i, g in enumerate(GOODS)}
EMPTY_STACK: tuple = (0, 0, 0, 0)

# Sowing one crop plants the standard stack: 1 grain from supply -> 3 on the
# field, 1 veg -> 2 (RULES.md). A wood/stone card declares which behavior it
# copies via its printed "as you would grain/vegetables" clause, encoded in
# its spec's per-good planted amounts.
CROP_SOW_AMOUNTS: dict[str, int] = {"grain": 3, "veg": 2}


@dataclass(frozen=True)
class CardFieldSpec:
    """One registered card-field.

    stacks       — how many independently-sowable stacks the card holds
                   (ruling 47): 1 normally, Wood Field 2, Rock Garden 3.
    sow_amounts  — the goods this card can be SOWN with, each with the amount
                   one sow plants: (("grain", 3), ("veg", 2)) for an
                   unrestricted field, (("veg", 2),) for a vegetables-only
                   one, (("wood", 3),) for wood-as-grain, (("stone", 2),)
                   for stone-as-vegetables. (Non-sow additions — Heresy
                   Teacher's below-the-grain veg — are not bound by this
                   whitelist, exactly as a grid cell isn't.)
    """
    card_id: str
    stacks: int
    sow_amounts: tuple


CARD_FIELDS: dict[str, CardFieldSpec] = {}


def register_card_field(card_id: str, *, stacks: int = 1, sow_amounts) -> None:
    """Register a card-field spec (card-module import time)."""
    CARD_FIELDS[card_id] = CardFieldSpec(
        card_id=card_id, stacks=stacks, sow_amounts=tuple(sow_amounts))


def _canon_stacks(stacks) -> tuple:
    """The canonical (sorted-descending) stack tuple — stacks carry no
    identity, so equal multisets must be structurally equal."""
    return tuple(sorted((tuple(s) for s in stacks), reverse=True))


def owned_card_fields(player_state) -> list[str]:
    """The registered card-fields this player has in play, sorted by card id
    (the canonical iteration order for the take and the sow)."""
    return sorted(
        cid for cid in CARD_FIELDS
        if cid in player_state.minor_improvements
        or cid in player_state.occupations)


def card_field_stacks(player_state, card_id: str) -> tuple:
    """The card's current per-stack (grain, veg, wood, stone) tuple —
    all-empty when the store has no entry (never sown, or harvested out)."""
    spec = CARD_FIELDS[card_id]
    return player_state.card_state.get(card_id, (EMPTY_STACK,) * spec.stacks)


def stacks_to_store(card_state, card_id: str, stacks):
    """The new CardStore with `stacks` recorded canonically — an all-empty
    tuple removes the entry (the no-entry default IS the all-empty state, and
    the two must hash alike)."""
    canon = _canon_stacks(stacks)
    if all(s == EMPTY_STACK for s in canon):
        return card_state.remove(card_id)
    return card_state.set(card_id, canon)


def stack_take_good(stack) -> tuple:
    """What the field-phase take removes from this stack: the first present
    good in take-precedence order, as (good, count) — ("", 0) for an empty
    stack. Mirrors the grid cell's grain-elif-veg."""
    for good, i in _GOOD_IDX.items():
        if stack[i] > 0:
            return good, stack[i]
    return "", 0


def stack_after_take(stack, good: str, n: int) -> tuple:
    """The stack with `n` of `good` removed."""
    i = _GOOD_IDX[good]
    assert stack[i] >= n, (stack, good, n)
    return stack[:i] + (stack[i] - n,) + stack[i + 1:]


def stack_with(stack, good: str, n: int) -> tuple:
    """The stack with `n` of `good` ADDED (a sow fill or a card effect like
    Heresy Teacher's below-the-grain vegetable)."""
    i = _GOOD_IDX[good]
    return stack[:i] + (stack[i] + n,) + stack[i + 1:]


def iter_card_field_units(state, idx: int):
    """Every non-empty stack of every owned card-field, as
    (key, good, count) with key = ("card", card_id, stack_idx) and (good,
    count) the stack's take-target (ruling 46 — the fold machinery's
    card-side view). Order: card id, then stack index (canonical)."""
    p = state.players[idx]
    out = []
    for cid in owned_card_fields(p):
        for i, stack in enumerate(card_field_stacks(p, cid)):
            good, n = stack_take_good(stack)
            if n > 0:
                out.append((("card", cid, i), good, n))
    return out


# ---------------------------------------------------------------------------
# Ruling-45 count helpers — the one vocabulary every "field"-reading card and
# scoring goes through. "Field tile" readers (ruling 32) use none of these.
# ---------------------------------------------------------------------------

def card_field_count(player_state) -> int:
    """Fields contributed to bare field-count readers ("N fields", the Fields
    scoring category) — exactly 1 per owned card (rulings 45 + 47), planted
    or not, exactly like a plowed grid field."""
    return len(owned_card_fields(player_state))


def _card_totals(player_state, card_id: str) -> tuple:
    """The card's total (grain, veg, wood, stone) across its stacks."""
    totals = [0, 0, 0, 0]
    for stack in card_field_stacks(player_state, card_id):
        for i in range(4):
            totals[i] += stack[i]
    return tuple(totals)


def card_holds(player_state, card_id: str, good: str) -> int:
    """How much of `good` the card currently holds (all stacks)."""
    return _card_totals(player_state, card_id)[_GOOD_IDX[good]]


def planted_card_field_count(player_state) -> int:
    """"Planted fields" contributed by card-fields: 1 per owned card holding
    ANYTHING (a wood-planted Wood Field is a planted field — its own text
    says "plant wood on this card")."""
    return sum(
        1 for cid in owned_card_fields(player_state)
        if any(_card_totals(player_state, cid)))


def unplanted_card_field_count(player_state) -> int:
    """"Unplanted/empty fields" contributed by card-fields: 1 per owned card
    holding nothing at all."""
    return sum(
        1 for cid in owned_card_fields(player_state)
        if not any(_card_totals(player_state, cid)))


def crop_card_field_count(player_state, good: str) -> int:
    """"Grain fields" / "vegetable fields" (etc.) contributed by card-fields:
    1 per owned card holding >= 1 of `good` (card-level — ruling 47's
    "considered 1 field")."""
    return sum(
        1 for cid in owned_card_fields(player_state)
        if card_holds(player_state, cid, good) > 0)


def planted_card_crops(player_state) -> tuple:
    """(grain, veg) currently planted on the player's card-fields — planted
    crops on fields, joining the scoring totals and every "crops in your
    supply and fields" reader (ruling 45). Wood and stone stacks contribute
    nothing here (not crops; per Wood Field's printed clarification, planted
    wood is not in the player's supply either)."""
    grain = veg = 0
    for cid in owned_card_fields(player_state):
        g, v, _w, _s = _card_totals(player_state, cid)
        grain += g
        veg += v
    return grain, veg


def card_field_goods_total(player_state) -> int:
    """ALL goods currently on the player's card-fields (crops AND wood/stone)
    — the ""goods in your fields"" reading (Wood Rake)."""
    return sum(
        sum(_card_totals(player_state, cid))
        for cid in owned_card_fields(player_state))


# ---------------------------------------------------------------------------
# Sow support
# ---------------------------------------------------------------------------

def enumerate_card_sows(player_state, *, crops_only: bool = False) -> list:
    """Every distinct card-sow bundle currently possible on the player's
    card-fields, IGNORING supply and sow caps (the sow enumerator applies
    those where the board counts are known): each bundle is a sorted tuple of
    (card_id, good) pairs, one pair per stack sown; the empty bundle `()` is
    always first (the Family fast path — no owned card-fields yields just
    that). `crops_only` drops non-crop goods (ruling 48: a crops-explicit
    grant cannot sow wood/stone)."""
    bundles: list[tuple] = [()]
    p = player_state
    for cid in owned_card_fields(p):
        spec = CARD_FIELDS[cid]
        empty = sum(1 for s in card_field_stacks(p, cid) if s == EMPTY_STACK)
        if not empty:
            continue
        goods = [g for g, _amt in spec.sow_amounts
                 if not crops_only or g in CROP_SOW_AMOUNTS]
        if not goods:
            continue
        # All non-empty multisets of up to `empty` sows over `goods`.
        per_card: list[tuple] = [()]
        frontier: list[tuple] = [()]
        for _ in range(empty):
            frontier = [m + ((cid, g),) for m in frontier for g in goods
                        if not m or (cid, g) >= m[-1]]   # non-decreasing = multiset
            per_card.extend(frontier)
        bundles = [b + m for b in bundles for m in per_card]
    return [tuple(sorted(b)) for b in bundles]


def sow_amount(card_id: str, good: str) -> int:
    """How many units one sow of `good` plants on this card."""
    for g, amt in CARD_FIELDS[card_id].sow_amounts:
        if g == good:
            return amt
    raise AssertionError(f"{card_id} cannot grow {good}")


def can_sow_card_fields(player_state, *, crops_only: bool = False) -> bool:
    """Is at least one card-field sow currently possible — an owned card with
    an empty stack whose allowed goods (crop-filtered under `crops_only`,
    ruling 48) include one the player has in supply? Extends every "can a sow
    happen at all?" gate (`legality._can_sow`, the sow-granting cards'
    committable checks) beyond the board's empty-cell test."""
    for cid in owned_card_fields(player_state):
        if not any(s == EMPTY_STACK
                   for s in card_field_stacks(player_state, cid)):
            continue
        for good, _amt in CARD_FIELDS[cid].sow_amounts:
            if crops_only and good not in CROP_SOW_AMOUNTS:
                continue
            if getattr(player_state.resources, good) >= 1:
                return True
    return False
