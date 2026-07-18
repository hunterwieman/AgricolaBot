"""Night Loot (minor improvement, E5; Ephipparius Expansion; traveling).

Card text (verbatim):
  "Immediately remove exactly 2 different building resources from accumulation
  spaces and place them in your supply."

Cost: 2 Food. VPs: 0. PASSING (traveling minor — ``passing_left=True``: after the
immediate effect the card moves to the OPPONENT's hand rather than staying in the
tableau; the hand-transfer runs in ``_execute_play_minor`` BEFORE ``on_play``, so
the take resolves for the player who played it).

USER RULINGS (2026-07-17), quoted verbatim:
  - The effect is MANDATORY (a choice of WHAT to take, but no decline): the
    play-variants are the legal picks with NO skip variant. Playing the card at
    all is the parent host's optional decision (its Stop/Proceed); once the card
    is being played, exactly 2 different building resources MUST be taken.
  - "If fewer than two DIFFERENT building-resource types are available on the
    board's accumulation spaces, the card is NOT playable" — modeled as a
    ``prereq`` predicate (never a dead-end variant nor a partial take): the card
    is playable only when at least 2 distinct types among {wood, clay, reed,
    stone} each have >= 1 unit sitting on a REVEALED accumulation space.
  - Ruling 66: the on-play "immediately" adds/changes nothing — no separate,
    earlier instant; the effect is the ordinary on-play one-shot.

CLASSIFICATION. Category 2 (on-play one-shot) + passing, carrying a MANDATORY
WHAT-to-take choice. Per the standing "on-play choices surface WIDE" ruling
(``register_play_minor_variant`` — Facades Carving / Petrified Wood), each legal
pick is one ``CommitPlayMinor``:

  - A pick is an UNORDERED PAIR of two DIFFERENT resource types, each tagged with
    the accumulation space it is taken from. Wood / clay / reed have a single
    source each (forest / clay_pit / reed_bank at 2 players); STONE has two
    (western_quarry, eastern_quarry), so a pick that includes stone is offered
    once per quarry that currently holds stone. The variant string encodes both
    sources, e.g. ``"wood@forest+stone@western_quarry"`` (the two ``type@space``
    tokens in canonical wood < clay < reed < stone order, ``+``-joined).
  - No variant carries a SURCHARGE: the two resources are taken FROM the board,
    not paid for. The 2-food price is the ordinary ``cost`` (the food-payment
    layer covers a shortfall). Every variant's surcharge is ``Resources()``.
  - ``on_play`` (3-arg) decrements each named space's ``accumulated`` by 1 of its
    named resource and credits +1 of each to the player's supply. Editing an
    accumulation space's stock has precedent (Pet Lover restores an animal to a
    market space).

Only REVEALED accumulation spaces count (``sp.revealed``); an unrevealed quarry
carries no stock anyway, so the revealed filter is belt-and-suspenders. The
``prereq`` (>= 2 available types) and the variant enumeration are computed from
the same availability set, so the card appears in ``playable_minors`` exactly
when it yields >= 1 legal pick — the card never disappears with no commit and
never offers a dead-end. The source sets are derived from
``BUILDING_ACCUMULATION_RATES`` via the constants groupings, so they extend
automatically to the 3-4-player board's extra building-resource spaces.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.constants import (
    CLAY_ACCUMULATION_SPACES,
    REED_ACCUMULATION_SPACES,
    STONE_ACCUMULATION_SPACES,
    WOOD_ACCUMULATION_SPACES,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "night_loot"

# Canonical building-resource order (wood < clay < reed < stone) -> its source
# accumulation spaces. Derived from the constants groupings, so the 3-4-player
# board's extra spaces (Copse, Grove, Hollow, ...) extend it in one place.
_TYPE_SPACES: tuple[tuple[str, frozenset], ...] = (
    ("wood", WOOD_ACCUMULATION_SPACES),
    ("clay", CLAY_ACCUMULATION_SPACES),
    ("reed", REED_ACCUMULATION_SPACES),
    ("stone", STONE_ACCUMULATION_SPACES),
)


def _sources(state: GameState, rtype: str, spaces) -> list[str]:
    """Sorted revealed accumulation spaces holding >= 1 of `rtype`."""
    out = []
    for sid in spaces:
        sp = get_space(state.board, sid)
        if sp.revealed and getattr(sp.accumulated, rtype) >= 1:
            out.append(sid)
    return sorted(out)


def _available(state: GameState) -> list:
    """(type, [source spaces]) for each building-resource type with >= 1 revealed
    source, in canonical order. Types with no available source are omitted."""
    out = []
    for rtype, spaces in _TYPE_SPACES:
        srcs = _sources(state, rtype, spaces)
        if srcs:
            out.append((rtype, srcs))
    return out


def _prereq(state: GameState, idx: int) -> bool:
    """Playable only when >= 2 DIFFERENT building-resource types each have >= 1
    unit on a revealed accumulation space (user ruling 2026-07-17)."""
    return len(_available(state)) >= 2


def _variants(state: GameState, idx: int):
    """One zero-surcharge variant per legal pick: an unordered pair of two
    DIFFERENT types, each tagged with its source space. Stone contributes one
    variant per quarry that holds stone. Tokens are in canonical (i < j) order;
    there is NO decline variant — the effect is mandatory (only WHICH two is a
    choice)."""
    avail = _available(state)
    out = []
    for a in range(len(avail)):
        ta, srcs_a = avail[a]
        for b in range(a + 1, len(avail)):
            tb, srcs_b = avail[b]
            for sa in srcs_a:
                for sb in srcs_b:
                    out.append((f"{ta}@{sa}+{tb}@{sb}", Resources()))
    return out


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    """Take 1 unit of each named type from its named space into the player's
    supply: decrement each source's `accumulated`, credit the player's
    resources. The two source spaces are always distinct (the types differ and
    each type's spaces are disjoint)."""
    board = state.board
    gained = Resources()
    for token in variant.split("+"):
        rtype, _, sid = token.partition("@")
        one = Resources(**{rtype: 1})
        sp = get_space(board, sid)
        board = with_space(board, sid, fast_replace(sp, accumulated=sp.accumulated - one))
        gained = gained + one
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + gained)
    return fast_replace(
        state,
        board=board,
        players=tuple(p if i == idx else state.players[i] for i in range(2)),
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    prereq=_prereq,
    passing_left=True,
    on_play=_on_play,
)
# The WHAT-to-take choice surfaces WIDE (one CommitPlayMinor per legal pick) via
# the PLAY_MINOR_VARIANTS seam; there is no decline variant (the take is mandatory).
register_play_minor_variant(CARD_ID, _variants)


def _label(variant: str):
    """Web-UI label for a pick route: 'wood@forest+stone@western_quarry' ->
    'Take wood (Forest) + stone (Western Quarry)'."""
    parts = []
    for token in variant.split("+"):
        rtype, sep, sid = token.partition("@")
        if not rtype or sep != "@" or not sid:
            return None
        parts.append(f"{rtype} ({sid.replace('_', ' ').title()})")
    return "Take " + " + ".join(parts)


register_action_labeler(CARD_ID, _label)
