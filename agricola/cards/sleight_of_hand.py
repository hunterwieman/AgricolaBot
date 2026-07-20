"""Sleight of Hand (minor improvement, E78; Ephipparius Expansion;
Building Resource Provider).

Card text (verbatim): "When you play this card, you can immediately exchange up
to 4 building resources for an equal number of other building resources."
Clarifications (verbatim): "It is a single exchange.  You can't trade
wood-for-wood, for example."

Cost: none. Prerequisite: 3 Occupations. VPs: none. Not passing.

A one-shot, on-play exchange over the four building resources
(wood / clay / reed / stone). At the moment the card is played the player may
hand back up to four building resources and receive an equal number of *other*
building resources — a single, atomic swap ("you can", so declining is legal,
including when the player holds no building resource at all).

Timing/mechanism — "When you play this card, you can immediately exchange ..." is
an OPTIONAL on-play choice, so it surfaces WIDE via the `PLAY_MINOR_VARIANTS`
seam (`specs.register_play_minor_variant`), the same idiom as Facades Carving:
one `CommitPlayMinor` per legal exchange plus an always-present zero-surcharge
DECLINE variant. This keeps the whole choice inside the single play action rather
than as an after-play trigger that could interleave with other cards.

USER RULINGS (2026-07-20):
  - Wide one-shot: one variant per canonical exchange plus a zero-surcharge
    decline variant (the "you can" — the card must stay playable with no
    exchange, including when the player holds no building resources).
  - A canonical exchange is a pair (give-multiset, get-multiset) over the four
    building resources with |give| = |get| = k for k in 1..4, the GIVE side
    bounded by the player's current holdings, and DISJOINT type support — no
    resource type appears on both sides. Disjoint support is lossless: an
    exchange with a type on both sides cancels to a smaller disjoint one that is
    already enumerated, and it is exactly the "can't trade wood-for-wood"
    clarification.
  - The enumeration may reach ~300 variants under very large holdings (308
    exchanges + the decline, when every building resource is held >= 4); that is
    accepted — the list is neither truncated nor sampled.

Implementation shape. The GIVE side rides each variant's SURCHARGE
(`Resources`): the play-minor enumerator folds the surcharge into the commit's
`payment`, gates it against holdings (`_payable`, liquidation-aware — but a
building-resource surcharge has no food component, so it must be held outright),
and `_execute_play_minor` debits it. The card's own cost is empty, so the play
payment is exactly the surcharge (the GIVE side). `_on_play` (3-arg) grants the
GET side only — the GIVE side was already debited. The decline variant ("none")
carries a zero surcharge and a no-op `_on_play`.

Variant string format: "<give>><get>", each side a canonical-order concatenation
of "<letter><count>" tokens over wood(w) / clay(c) / reed(r) / stone(s), e.g.
"w2c1>r3" = give 2 wood + 1 clay, get 3 reed. The decline route is the literal
"none". The string fully encodes both sides and is decoded in `_on_play` by
parsing the GET side — there is no module-level state carried between enumeration
and execution. The variant list is sorted by string for a deterministic, stable
order (action identity matters for search).

Family-inertness: minors exist only under GameMode.CARDS; the
PLAY_MINOR_VARIANTS registry entry is card-only, so the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "sleight_of_hand"

# The four building resources, in canonical order, with their one-letter codes.
BUILDING_RESOURCES = ("wood", "clay", "reed", "stone")
_LETTER = {"wood": "w", "clay": "c", "reed": "r", "stone": "s"}
_NAME = {v: k for k, v in _LETTER.items()}

# "up to 4 building resources" -> the exchange size k ranges 1..MAX_EXCHANGE.
MAX_EXCHANGE = 4

# The always-present decline route (the "you can": play with no exchange).
DECLINE = "none"


def _multisets(types: list[str], k: int, caps: dict[str, int]) -> list[dict[str, int]]:
    """All multisets of size `k` drawn from `types`, where each type `t` is used at
    most `caps[t]` times (default cap `k` = unbounded within the size). Returned as
    dicts {type: count} holding only positive counts. Deterministic order (fixed
    recursion over `types`)."""
    if not types:
        return [{}] if k == 0 else []
    head, rest = types[0], types[1:]
    out: list[dict[str, int]] = []
    cap = min(k, caps.get(head, k))
    for n in range(cap + 1):
        for tail in _multisets(rest, k - n, caps):
            d = dict(tail)
            if n > 0:
                d[head] = n
            out.append(d)
    return out


def _encode(ms: dict[str, int]) -> str:
    """Canonical-order "<letter><count>" concatenation, e.g. {wood:2, clay:1} ->
    "w2c1"."""
    return "".join(f"{_LETTER[t]}{ms[t]}" for t in BUILDING_RESOURCES if ms.get(t, 0) > 0)


def _parse_side(s: str) -> dict[str, int]:
    """Inverse of `_encode`: "r3" -> {reed: 3}, "w2c1" -> {wood: 2, clay: 1}."""
    out: dict[str, int] = {}
    i = 0
    while i < len(s):
        letter = s[i]
        j = i + 1
        while j < len(s) and s[j].isdigit():
            j += 1
        out[_NAME[letter]] = int(s[i + 1:j])
        i = j
    return out


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """One (variant-string, GIVE-surcharge) per canonical exchange, plus the
    zero-surcharge decline route (user ruling 2026-07-20).

    For each size k in 1..4: enumerate every GIVE multiset of size k bounded by the
    player's current holdings, then every GET multiset of size k over the building
    resources NOT in GIVE's support (disjoint support -> "can't trade
    wood-for-wood"). GIVE bounded by holdings means a player who holds 1 wood is
    never offered a give of 2 wood, and k self-limits to the total resources held.
    The GET side is unbounded within the size (you are receiving). The GIVE side
    becomes the surcharge; the GET side is granted in `_on_play`. The list is
    sorted by variant string for a deterministic, stable order."""
    r = state.players[idx].resources
    holdings = {t: getattr(r, t) for t in BUILDING_RESOURCES}
    out: list[tuple[str, Resources]] = [(DECLINE, Resources())]
    for k in range(1, MAX_EXCHANGE + 1):
        for give in _multisets(list(BUILDING_RESOURCES), k, holdings):
            allowed = [t for t in BUILDING_RESOURCES if give.get(t, 0) == 0]
            for get in _multisets(allowed, k, {}):
                if not get:               # no disjoint target of this size (give uses all 4)
                    continue
                vstr = f"{_encode(give)}>{_encode(get)}"
                out.append((vstr, Resources(**give)))
    out.sort(key=lambda pair: pair[0])
    return out


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Grant the GET side of the chosen exchange. The GIVE side rode the variant's
    surcharge and was already debited (folded into the commit payment at
    enumeration), so this only credits the received resources. The decline route
    ("none", or a missing variant) is a no-op."""
    if not variant or variant == DECLINE:
        return state
    _give_s, _, get_s = variant.partition(">")
    get = _parse_side(get_s)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(**get))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# No cost, no printed VPs, not passing; prereq "3 Occupations" is a HAVE-check.
register_minor(CARD_ID, min_occupations=3, on_play=_on_play)

# The wide on-play exchange (user ruling 2026-07-20): one play variant per
# canonical exchange (GIVE surcharge folded into the payment) plus the decline.
register_play_minor_variant(CARD_ID, _variants)


def _fmt_side(ms: dict[str, int]) -> str:
    """Canonical-order human form of one exchange side: {wood:2, clay:1} ->
    "2 wood, 1 clay"."""
    return ", ".join(f"{ms[t]} {t}" for t in BUILDING_RESOURCES if ms.get(t, 0))


def _action_label(variant: str) -> str | None:
    """Web-UI label for an exchange variant (mechanical and terse per the label
    pass's style — the web layer prepends the card name): "w2c1>r3" -> "give
    2 wood, 1 clay → get 3 reed"; the decline route reads "no exchange". None
    (the generic fallback) on anything unrecognized."""
    if variant == DECLINE:
        return "no exchange"
    give_s, sep, get_s = variant.partition(">")
    if not sep or not give_s or not get_s:
        return None
    try:
        give, get = _parse_side(give_s), _parse_side(get_s)
    except (KeyError, ValueError):
        return None
    return f"give {_fmt_side(give)} → get {_fmt_side(get)}"


register_action_labeler(CARD_ID, _action_label)
