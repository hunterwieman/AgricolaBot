"""Terminal UI for AgricolaBot. Play interactively against a random agent or another human.

Usage:
    python play.py [--seed N] [--players 1|2] [--human-seat 0|1]

Slash commands at any prompt: /quit /help /score /state /board
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from typing import Callable

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    CommitSubAction,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    FOOD_ANIMAL_ACCUMULATION_RATES,
    HARVEST_ROUNDS,
    NUM_ROUNDS,
    STAGE_CARDS,
    STAGE_ROUNDS,
    CellType,
    HouseMaterial,
    Phase,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.scoring import score, tiebreaker
from agricola.setup import setup, setup_env
from agricola.state import GameState, get_space

# ---------------------------------------------------------------------------
# Display constants
# ---------------------------------------------------------------------------

SPACE_DISPLAY_NAMES: dict[str, str] = {
    "forest": "Forest",
    "clay_pit": "Clay Pit",
    "reed_bank": "Reed Bank",
    "fishing": "Fishing",
    "meeting_place": "Meeting Place",
    "grain_seeds": "Grain Seeds",
    "farmland": "Farmland",
    "lessons": "Lessons",
    "day_laborer": "Day Laborer",
    "side_job": "Side Job",
    "farm_expansion": "Farm Expansion",
    "sheep_market": "Sheep Market",
    "pig_market": "Pig Market",
    "cattle_market": "Cattle Market",
    "western_quarry": "Western Quarry",
    "eastern_quarry": "Eastern Quarry",
    "major_improvement": "Major Improvement",
    "fencing": "Fencing",
    "grain_utilization": "Grain Utilization",
    "vegetable_seeds": "Vegetable Seeds",
    "basic_wish_for_children": "Basic Wish for Children",
    "urgent_wish_for_children": "Urgent Wish for Children",
    "house_redevelopment": "House Redevelopment",
    "cultivation": "Cultivation",
    "farm_redevelopment": "Farm Redevelopment",
}

PERMANENT_DISPLAY_ORDER = [
    "forest", "clay_pit", "reed_bank", "fishing", "meeting_place",
    "grain_seeds", "farmland", "day_laborer", "side_job", "farm_expansion",
]

MAJOR_NAMES = [
    "Fireplace(2c)", "Fireplace(3c)",
    "CookingHearth(4c)", "CookingHearth(5c)",
    "Well", "ClayOven", "StoneOven",
    "Joinery", "Pottery", "Basketmaker",
]

HOUSE_MATERIAL_NAME = {
    HouseMaterial.WOOD: "wood",
    HouseMaterial.CLAY: "clay",
    HouseMaterial.STONE: "stone",
}

ENUMERATE_THRESHOLD = 8


# ---------------------------------------------------------------------------
# Decider + header
# ---------------------------------------------------------------------------

def decider_of(state: GameState) -> "int | None":
    # None at a round-card reveal (a PendingReveal — nature decides).
    return state.pending_stack[-1].player_idx if state.pending_stack else state.current_player


def render_header(state: GameState) -> str:
    sp = state.starting_player
    dec = decider_of(state)
    phase = state.phase.name
    note = ""
    if state.phase == Phase.WORK and state.round_number in HARVEST_ROUNDS:
        note = " | harvest after this round"
    elif state.phase == Phase.WORK and (state.round_number + 1) in HARVEST_ROUNDS:
        note = " | harvest next round"
    return (
        f"=== Round {state.round_number}/{NUM_ROUNDS} | Phase {phase} | "
        f"SP=P{sp} | Deciding: P{dec}{note} ==="
    )


# ---------------------------------------------------------------------------
# Action-space board
# ---------------------------------------------------------------------------

def _fmt_workers(workers: tuple) -> str:
    bits = []
    for p in (0, 1):
        if workers[p] > 0:
            bits.append(f"P{p}" + (f"x{workers[p]}" if workers[p] > 1 else ""))
    return f" [{','.join(bits)}]" if bits else ""


def _fmt_accumulation(space_id: str, sp_state) -> str:
    if space_id in BUILDING_ACCUMULATION_RATES:
        r = sp_state.accumulated
        parts = []
        for fld in ("wood", "clay", "reed", "stone"):
            v = getattr(r, fld)
            if v:
                parts.append(f"{v}{fld[0]}")
        return " ".join(parts)
    if space_id in FOOD_ANIMAL_ACCUMULATION_RATES:
        fld, _ = FOOD_ANIMAL_ACCUMULATION_RATES[space_id]
        v = sp_state.accumulated_amount
        return f"{v} {fld}" if v else ""
    return ""


def render_action_board(state: GameState) -> list[str]:
    lines = ["Action spaces:"]
    board = state.board

    def emit(sid: str) -> None:
        ss = get_space(board, sid)
        name = SPACE_DISPLAY_NAMES.get(sid, sid)
        accum = _fmt_accumulation(sid, ss)
        occ = _fmt_workers(ss.workers)
        accum_str = f"  ({accum})" if accum else ""
        lines.append(f"  {name:<24}{accum_str}{occ}")

    lines.append("  -- permanent --")
    for sid in PERMANENT_DISPLAY_ORDER:
        if sid in spaces:
            emit(sid)

    rnd = state.round_number
    for stage in range(1, 7):
        first, last = STAGE_ROUNDS[stage]
        if rnd < first:
            break
        lines.append(f"  -- stage {stage} --")
        revealed_in_stage = sorted(
            sid for sid in STAGE_CARDS[stage]
            if spaces[sid].revealed
        )
        for sid in revealed_in_stage:
            emit(sid)
    return lines


# ---------------------------------------------------------------------------
# Player panel + farmyard
# ---------------------------------------------------------------------------

def _fmt_resources(r) -> str:
    return (
        f"W: {r.wood}, C: {r.clay}, R: {r.reed}, S: {r.stone} | "
        f"F: {r.food}, g: {r.grain}, v: {r.veg}"
    )


def _fmt_animals(a) -> str:
    return f"Sh: {a.sheep}, Bo: {a.boar}, Ca: {a.cattle}"


def _fmt_majors(state: GameState, player_idx: int) -> str:
    owned = [
        f"{i}:{MAJOR_NAMES[i]}"
        for i, owner in enumerate(state.board.major_improvement_owners)
        if owner == player_idx
    ]
    return ",".join(owned) if owned else "-"


def _fmt_minors(p) -> str:
    return ",".join(sorted(p.minor_improvements)) if p.minor_improvements else "-"


def render_player_panel(state: GameState, player_idx: int) -> list[str]:
    p = state.players[player_idx]
    sp_tag = "[SP]" if state.starting_player == player_idx else "    "
    active_tag = "[*]" if decider_of(state) == player_idx else "   "
    line1 = (
        f"P{player_idx} {sp_tag}{active_tag}: "
        f"{_fmt_resources(p.resources)} | {_fmt_animals(p.animals)} | "
        f"Maj:{_fmt_majors(state, player_idx)} | Min:{_fmt_minors(p)}"
    )
    placed = p.people_total - p.people_home
    line2 = (
        f"            Ppl {p.people_total}/{p.people_home}h ({placed} placed) | "
        f"Newborns {p.newborns} | Beg {p.begging_markers} | "
        f"House: {HOUSE_MATERIAL_NAME[p.house_material]}"
    )
    return [line1, line2]


def _cell_content(cell) -> str:
    if cell.cell_type == CellType.EMPTY:
        return " . "
    if cell.cell_type == CellType.ROOM:
        return " R "
    if cell.cell_type == CellType.STABLE:
        return " S "
    if cell.cell_type == CellType.FIELD:
        if cell.grain > 0:
            return f"g{cell.grain} "
        if cell.veg > 0:
            return f"v{cell.veg} "
        return " F "
    return " ? "


def render_farmyard(farmyard) -> list[str]:
    """3x5 grid; cells 3 chars wide. Fence rendering:

      Player-placed fence (boundary or internal): '---' / '|'
      Unfenced boundary edge:                     '···' / ':'
      Unfenced internal edge:                     '   ' / ' '
    """
    grid = farmyard.grid
    h = farmyard.horizontal_fences  # shape (4, 5): h[0]=top boundary, h[3]=bottom boundary
    v = farmyard.vertical_fences    # shape (3, 6): v[r][0]=left boundary, v[r][5]=right boundary
    out: list[str] = []

    def h_boundary(row: int) -> str:
        parts = ["+"]
        for c in range(5):
            parts.append("---" if h[row][c] else "···")
            parts.append("+")
        return "".join(parts)

    out.append(h_boundary(0))
    for r in range(3):
        parts = ["|" if v[r][0] else ":"]
        for c in range(5):
            parts.append(_cell_content(grid[r][c]))
            if c == 4:
                parts.append("|" if v[r][5] else ":")
            else:
                parts.append("|" if v[r][c + 1] else " ")
        out.append("".join(parts))
        if r == 2:
            out.append(h_boundary(3))
        else:
            sep_parts = ["+"]
            for c in range(5):
                sep_parts.append("---" if h[r + 1][c] else "   ")
                sep_parts.append("+")
            out.append("".join(sep_parts))
    return out


def render_pastures(farmyard) -> str:
    if not farmyard.pastures:
        return "Pastures: none"
    grid = farmyard.grid
    parts = []
    for i, past in enumerate(farmyard.pastures):
        cells = sorted(past.cells)
        cell_str = ",".join(f"({r},{c})" for r, c in cells)
        fs = sum(1 for (r, c) in past.cells if grid[r][c].cell_type == CellType.STABLE)
        suffix = f" {fs}fS" if fs else ""
        parts.append(f"{chr(ord('A')+i)}={{{cell_str}}}{suffix} cap={past.capacity}")
    return "Pastures: " + " | ".join(parts)


def render_player_block(state: GameState, player_idx: int) -> list[str]:
    out = render_player_panel(state, player_idx)
    out.extend(render_farmyard(state.players[player_idx].farmyard))
    out.append(render_pastures(state.players[player_idx].farmyard))
    return out


# ---------------------------------------------------------------------------
# Pending breadcrumb
# ---------------------------------------------------------------------------

def _fmt_cost(r) -> str:
    parts = []
    for fld in ("wood", "clay", "reed", "stone", "food", "grain", "veg"):
        v = getattr(r, fld)
        if v:
            parts.append(f"{v}{fld[0]}")
    return " ".join(parts) if parts else "0"


def _pending_detail(frame, state: GameState) -> str:
    """Short summary of the top pending's relevant state fields.

    Some details are derived from live player state rather than stored on
    the pending — `food_owed` for PendingHarvestFeed is the canonical
    example (see PendingHarvestFeed docstring).
    """
    cls = type(frame).__name__
    if cls == "PendingHarvestFeed":
        p = state.players[frame.player_idx]
        need = 2 * p.people_total - p.newborns
        food_owed = max(0, need - p.resources.food)
        return f"food_owed={food_owed}, conversion_done={frame.conversion_done}"
    if cls == "PendingHarvestBreed":
        return f"breed_chosen={frame.breed_chosen}"
    if cls == "PendingBuildFences":
        bits = [f"pastures_built={frame.pastures_built}",
                f"fences_built={frame.fences_built}"]
        if frame.subdivision_started:
            bits.append("subdivision_started")
        return ", ".join(bits)
    if cls in ("PendingBuildStables", "PendingBuildRooms"):
        cap = "inf" if frame.max_builds is None else str(frame.max_builds)
        detail = f"num_built={frame.num_built}, cap={cap}"
        # Build Stables still carries a caller-supplied base cost on the frame; Build
        # Rooms now resolves cost through the cost-modifier chokepoint
        # (`effective_payments`), so it no longer stores one (COST_MODIFIER_DESIGN.md).
        if hasattr(frame, "cost"):
            detail += f", cost/build={_fmt_cost(frame.cost)}"
        return detail
    if cls in ("PendingSheepMarket", "PendingPigMarket", "PendingCattleMarket"):
        return f"gained={frame.gained}"
    if cls == "PendingAccommodate":
        p = state.players[frame.player_idx]
        return f"over capacity ({p.animals}) — choose which to keep, excess cooked"
    if cls == "PendingRenovate":
        # Cost is resolved via `effective_payments` / `CommitRenovate.payment`
        # (cost-modifier system); it is not stored on the frame.
        return ""
    return ""


def render_pending(state: GameState) -> str:
    if not state.pending_stack:
        return ""
    chain = " > ".join(type(f).__name__.removeprefix("Pending") for f in state.pending_stack)
    detail = _pending_detail(state.pending_stack[-1], state)
    if detail:
        return f"Pending: {chain}  ({detail})"
    return f"Pending: {chain}"


# ---------------------------------------------------------------------------
# Action menu — grouped by Commit class with enumerate/prompt threshold
# ---------------------------------------------------------------------------

_ALWAYS_ENUMERATE = (PlaceWorker, ChooseSubAction, FireTrigger, Stop)


def _action_class_key(action: Action) -> str:
    if isinstance(action, PlaceWorker):
        return "PlaceWorker"
    if isinstance(action, ChooseSubAction):
        return "ChooseSubAction"
    if isinstance(action, FireTrigger):
        return "FireTrigger"
    if isinstance(action, Stop):
        return "Stop"
    return type(action).__name__


def _fmt_action_inline(action: Action) -> str:
    if isinstance(action, PlaceWorker):
        nice = SPACE_DISPLAY_NAMES.get(action.space, action.space)
        return f"PlaceWorker({action.space}) - {nice}"
    if isinstance(action, ChooseSubAction):
        return f"ChooseSubAction({action.name!r})"
    if isinstance(action, FireTrigger):
        return f"FireTrigger({action.card_id!r})"
    if isinstance(action, Stop):
        return "Stop"
    if isinstance(action, Proceed):
        return "Proceed"
    if isinstance(action, CommitSow):
        base = f"CommitSow(grain={action.grain}, veg={action.veg})"
        if action.card_sows:
            cards = ", ".join(f"{cid}: {good}" for cid, good in action.card_sows)
            return f"{base} + {cards}"
        return base
    if isinstance(action, CommitBake):
        return f"CommitBake(grain={action.grain})"
    if isinstance(action, CommitPlow):
        return f"CommitPlow(row={action.row}, col={action.col})"
    if isinstance(action, CommitBuildStable):
        return f"CommitBuildStable(row={action.row}, col={action.col})"
    if isinstance(action, CommitBuildRoom):
        return f"CommitBuildRoom(row={action.row}, col={action.col})"
    if isinstance(action, CommitBuildMajor):
        from agricola.cost import ReturnImprovement
        name = MAJOR_NAMES[action.major_idx]
        ret = (f", return_fireplace_idx={action.payment.improvement_idx}"
               if isinstance(action.payment, ReturnImprovement) else "")
        return f"CommitBuildMajor(major_idx={action.major_idx}{ret}) - {name}"
    if isinstance(action, CommitRenovate):
        return "CommitRenovate"
    if isinstance(action, CommitAccommodate):
        return f"CommitAccommodate(sheep={action.sheep}, boar={action.boar}, cattle={action.cattle})"
    if isinstance(action, CommitBuildPasture):
        cells = sorted(action.cells)
        cs = ",".join(f"({r},{c})" for r, c in cells)
        return f"CommitBuildPasture(cells={{{cs}}})"
    if isinstance(action, CommitHarvestConversion):
        return f"CommitHarvestConversion(conversion_id={action.conversion_id!r})"
    if isinstance(action, CommitConvert):
        return (
            f"CommitConvert(grain={action.grain}, veg={action.veg}, "
            f"sheep={action.sheep}, boar={action.boar}, cattle={action.cattle})"
        )
    if isinstance(action, CommitBreed):
        return f"CommitBreed(sheep={action.sheep}, boar={action.boar}, cattle={action.cattle})"
    return repr(action)


# ---------------------------------------------------------------------------
# Parameter parsing for prompt-style commits
# ---------------------------------------------------------------------------

def _parse_cell(tok: str) -> tuple[int, int]:
    """'13' -> (1, 3). Single digit per coord."""
    s = tok.replace(",", "").replace("(", "").replace(")", "")
    if len(s) != 2 or not s.isdigit():
        raise ValueError(f"expected 2-digit cell code like '13', got {tok!r}")
    return int(s[0]), int(s[1])


def _parse_cells(tokens: list[str]) -> frozenset:
    if not tokens:
        raise ValueError("expected at least one cell code")
    return frozenset(_parse_cell(t) for t in tokens)


def _parse_ints(tokens: list[str], n: int) -> list[int]:
    if len(tokens) != n:
        raise ValueError(f"expected {n} integers, got {len(tokens)}")
    try:
        return [int(t) for t in tokens]
    except ValueError as e:
        raise ValueError(f"non-integer token: {e}")


def _p_plow(toks):
    if len(toks) != 1:
        raise ValueError("expected 1 cell code")
    r, c = _parse_cell(toks[0])
    return CommitPlow(row=r, col=c)


def _p_build_stable(toks):
    if len(toks) != 1:
        raise ValueError("expected 1 cell code")
    r, c = _parse_cell(toks[0])
    return CommitBuildStable(row=r, col=c)


def _p_build_room(toks):
    if len(toks) != 1:
        raise ValueError("expected 1 cell code")
    r, c = _parse_cell(toks[0])
    return CommitBuildRoom(row=r, col=c)


def _p_build_pasture(toks):
    return CommitBuildPasture(cells=_parse_cells(toks))


def _p_sow(toks):
    v = _parse_ints(toks, 2)
    return CommitSow(grain=v[0], veg=v[1])


def _p_bake(toks):
    v = _parse_ints(toks, 1)
    return CommitBake(grain=v[0])


def _p_accommodate(toks):
    v = _parse_ints(toks, 3)
    return CommitAccommodate(sheep=v[0], boar=v[1], cattle=v[2])


def _p_breed(toks):
    v = _parse_ints(toks, 3)
    return CommitBreed(sheep=v[0], boar=v[1], cattle=v[2])


def _p_convert(toks):
    v = _parse_ints(toks, 5)
    return CommitConvert(grain=v[0], veg=v[1], sheep=v[2], boar=v[3], cattle=v[4])


def _p_build_major(toks):
    # Terminal UI (Family game, no cost cards): the payment is the printed cost for a
    # standard buy, or a ReturnImprovement(fireplace) for the Cooking-Hearth route.
    from agricola.constants import MAJOR_IMPROVEMENT_COSTS
    from agricola.cost import ReturnImprovement
    if not (1 <= len(toks) <= 2):
        raise ValueError("expected 1 or 2 integers")
    major_idx = int(toks[0])
    payment = (ReturnImprovement(int(toks[1])) if len(toks) == 2
               else MAJOR_IMPROVEMENT_COSTS[major_idx])
    return CommitBuildMajor(major_idx=major_idx, payment=payment)


def _p_harvest_conversion(toks):
    if len(toks) != 1:
        raise ValueError("expected '<conversion_id>'")
    return CommitHarvestConversion(conversion_id=toks[0])


_PROMPT_FORMATS: dict[type, tuple[str, Callable[[list[str]], Action]]] = {
    CommitPlow:              ("rc cell code (e.g. '13' = row 1 col 3)", _p_plow),
    CommitBuildStable:       ("rc cell code (e.g. '13')", _p_build_stable),
    CommitBuildRoom:         ("rc cell code (e.g. '13')", _p_build_room),
    CommitBuildPasture:      ("space-separated rc cell codes (e.g. '13 23')", _p_build_pasture),
    CommitSow:               ("'grain veg' (e.g. '1 0')", _p_sow),
    CommitBake:              ("'grain' (e.g. '1')", _p_bake),
    CommitAccommodate:       ("'sheep boar cattle' (e.g. '1 0 2')", _p_accommodate),
    CommitBreed:             ("'sheep boar cattle' (post-breed counts, e.g. '3 0 1')", _p_breed),
    CommitConvert:           ("'g v sh bo ca' consumed (e.g. '0 1 2 0 0')", _p_convert),
    CommitBuildMajor:        ("'major_idx' or 'major_idx return_fireplace_idx'", _p_build_major),
    CommitHarvestConversion: ("'<conversion_id>'", _p_harvest_conversion),
}


def _group_actions(actions: list[Action]) -> dict[str, list[Action]]:
    groups: dict[str, list[Action]] = {}
    for a in actions:
        groups.setdefault(_action_class_key(a), []).append(a)
    return groups


def _placeworker_sort_key(space_id: str, state: GameState) -> tuple:
    if space_id in PERMANENT_DISPLAY_ORDER:
        return (0, PERMANENT_DISPLAY_ORDER.index(space_id))
    return (1, space_id)


def render_action_menu(actions: list[Action], state: GameState) -> tuple[list[str], list]:
    """Return (menu_lines, entries). Each entry is ('enum', Action) or ('prompt', cls, [opts])."""
    groups = _group_actions(actions)
    if "PlaceWorker" in groups:
        groups["PlaceWorker"].sort(key=lambda a: _placeworker_sort_key(a.space, state))
    entries: list = []
    lines: list[str] = []
    next_idx = 1

    def add_enum(action: Action) -> None:
        nonlocal next_idx
        lines.append(f"  {next_idx}. {_fmt_action_inline(action)}")
        entries.append(("enum", action))
        next_idx += 1

    def add_prompt(cls: type, opts: list[Action]) -> None:
        nonlocal next_idx
        hint, _ = _PROMPT_FORMATS[cls]
        lines.append(
            f"  {next_idx}. {cls.__name__} ({len(opts)} options) "
            f"- type '{next_idx} <params>'; format: {hint}"
        )
        entries.append(("prompt", cls, opts))
        next_idx += 1

    head_keys = ["PlaceWorker", "ChooseSubAction"]
    tail_keys = ["FireTrigger", "Stop"]
    middle_keys = sorted(k for k in groups if k not in head_keys + tail_keys)
    ordered = [k for k in head_keys if k in groups] + middle_keys + [k for k in tail_keys if k in groups]

    for key in ordered:
        opts = groups[key]
        sample = opts[0]
        cls = type(sample)
        if isinstance(sample, _ALWAYS_ENUMERATE) or len(opts) <= ENUMERATE_THRESHOLD or cls not in _PROMPT_FORMATS:
            for a in opts:
                add_enum(a)
        else:
            add_prompt(cls, opts)

    return lines, entries


# ---------------------------------------------------------------------------
# Full state render
# ---------------------------------------------------------------------------

def render_state(state: GameState) -> None:
    print()
    print(render_header(state))
    for line in render_action_board(state):
        print(line)
    print()
    for pidx in (0, 1):
        for line in render_player_block(state, pidx):
            print(line)
        print()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

SCORE_ROWS = [
    ("Fields",          "field_tiles"),
    ("Pastures",        "pastures"),
    ("Grain",           "grain"),
    ("Veg",             "vegetables"),
    ("Sheep",           "sheep"),
    ("Boar",            "boar"),
    ("Cattle",          "cattle"),
    ("Unused",          "unused_spaces"),
    ("Fenced stables",  "fenced_stables"),
    ("Clay rooms",      "clay_rooms"),
    ("Stone rooms",     "stone_rooms"),
    ("People",          "people"),
    ("Begging",         "begging_markers"),
    ("Major imp.",      "major_improvement_points"),
    ("Craft bonus",     "bonus_points"),
]


def render_scoring(state: GameState, header: str = "=== Game over ===") -> None:
    t0, b0 = score(state, 0)
    t1, b1 = score(state, 1)
    print()
    print(header)
    print(f"                   P0    P1")
    for label, attr in SCORE_ROWS:
        v0 = getattr(b0, attr)
        v1 = getattr(b1, attr)
        print(f"  {label:<16}{v0:>4}  {v1:>4}")
    print(f"  {'--- TOTAL ---':<16}{t0:>4}  {t1:>4}")
    if t0 == t1:
        tb0 = tiebreaker(state, 0)
        tb1 = tiebreaker(state, 1)
        winner = "tie" if tb0 == tb1 else f"P{0 if tb0 > tb1 else 1} (tiebreak {tb0}-{tb1})"
        print(f"Tiebreaker (resources): P0={tb0} P1={tb1}")
        print(f"Winner: {winner}")
    else:
        winner = 0 if t0 > t1 else 1
        print(f"Winner: P{winner} ({max(t0, t1)} to {min(t0, t1)})")


# ---------------------------------------------------------------------------
# Round log — one line per "turn" (placement + all sub-actions joined with ' -> ')
# ---------------------------------------------------------------------------

class RoundLog:
    """Accumulates actions of the current round, one line per turn.

    A new turn starts when a PlaceWorker is taken or when the decider changes
    (the latter covers harvest sub-pending handoffs, where there is no
    PlaceWorker but each player's pending is its own turn).

    On round transition, the log keeps any *trailing AI turns* (turns whose
    decider is not in `humans`) that came after the last human turn — so the
    human can see AI moves that happened during the round-transition gap.
    """

    def __init__(self, humans: set[int]) -> None:
        self.humans = humans
        # entries: (round_num, decider, parts_string)
        self.entries: list[tuple[int, int, str]] = []
        self._buf_round: int | None = None
        self._buf_decider: int | None = None
        self._buf_parts: list[str] = []

    def add(self, decider: int, action: Action, round_num: int) -> None:
        is_new_turn = isinstance(action, PlaceWorker) or self._buf_decider != decider
        if is_new_turn and self._buf_parts:
            self._flush()
        if decider in self.humans:
            # The human has acted in the current round — carryover from prior
            # rounds has been seen and can be dropped.
            self.entries = [e for e in self.entries if e[0] == round_num]
        if not self._buf_parts:
            self._buf_decider = decider
            self._buf_round = round_num
        self._buf_parts.append(_fmt_action_inline(action))

    def _flush(self) -> None:
        if self._buf_parts:
            self.entries.append(
                (self._buf_round, self._buf_decider, " -> ".join(self._buf_parts))
            )
            self._buf_parts = []
            self._buf_decider = None
            self._buf_round = None

    def round_transition(self) -> None:
        """Flush any in-progress turn, then drop everything up to and including
        the last human turn. The remaining (AI) tail carries into the new round
        so the human can see AI moves that happened during the gap.
        """
        self._flush()
        last_human = -1
        for i, (_r, decider, _p) in enumerate(self.entries):
            if decider in self.humans:
                last_human = i
        self.entries = self.entries[last_human + 1:]

    def render_lines(self, current_round: int) -> list[str]:
        out: list[str] = []
        for r, decider, parts in self.entries:
            prefix = f"  P{decider}" if r == current_round else f"  (R{r}) P{decider}"
            out.append(f"{prefix} {parts}")
        if self._buf_parts:
            out.append(f"  P{self._buf_decider} {' -> '.join(self._buf_parts)}")
        return out


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

def _handle_slash(state: GameState, line: str) -> bool:
    cmd = line.strip().lower()
    if cmd in ("/quit", "/q"):
        print("Game aborted.")
        sys.exit(0)
    if cmd in ("/help", "/h"):
        print("Commands: /quit /help /score /state /board")
        print("Input: type a menu number (e.g. '3'), or for prompt rows 'N <params>'.")
        print("Cell codes are rc (e.g. '13' = row 1 col 3). Multi-cell: '13 23'.")
        print("For PlaceWorker rows, you may type the space_id (e.g. 'forest') instead of the number.")
        print("Farmyard rendering: '---'/'|' = your fence (incl. on boundary); "
              "'···'/':' = unfenced boundary edge; ' ' = unfenced internal edge.")
        return True
    if cmd == "/score":
        render_scoring(state, header="=== Interim score ===")
        return True
    if cmd in ("/state", "/s"):
        render_state(state)
        return True
    if cmd in ("/board", "/b"):
        for line in render_action_board(state):
            print(line)
        return True
    return False


# ---------------------------------------------------------------------------
# Human input prompt
# ---------------------------------------------------------------------------

def _get_human_action(state: GameState, actions: list[Action]) -> Action:
    menu_lines, entries = render_action_menu(actions, state)
    pend = render_pending(state)
    print()
    if pend:
        print(pend)
    print(f"Decider: P{decider_of(state)}")
    print("Menu (type number or '/help'):")
    for line in menu_lines:
        print(line)

    legal_set = set(actions)
    space_ids = {a.space: a for a in actions if isinstance(a, PlaceWorker)}

    while True:
        try:
            raw = input("> ").strip()
        except EOFError:
            print()
            sys.exit(0)
        if not raw:
            continue
        if raw.startswith("/"):
            if _handle_slash(state, raw):
                continue
            print(f"Unknown slash command: {raw}")
            continue
        if raw in space_ids:
            return space_ids[raw]
        tokens = raw.split()
        try:
            n = int(tokens[0])
        except ValueError:
            print(f"Couldn't parse '{tokens[0]}' as a menu number or space_id.")
            continue
        if n < 1 or n > len(entries):
            print(f"Number out of range: {n} (valid 1..{len(entries)}).")
            continue
        entry = entries[n - 1]
        if entry[0] == "enum":
            action = entry[1]
            if len(tokens) > 1:
                print(f"  (ignoring extra params for enumerated row {n})")
            if action in legal_set:
                return action
            print(f"Action {_fmt_action_inline(action)} not in legal set (engine bug?).")
            continue
        _, cls, opts = entry
        if len(tokens) > 1:
            params = tokens[1:]
        else:
            hint, _ = _PROMPT_FORMATS[cls]
            print(f"  Format: {hint}")
            print(f"  Legal {cls.__name__} options ({len(opts)}):")
            for o in opts[:20]:
                print(f"    - {_fmt_action_inline(o)}")
            if len(opts) > 20:
                print(f"    ... and {len(opts) - 20} more (type 'all' to see all)")
            try:
                inner = input("  params> ").strip()
            except EOFError:
                print()
                sys.exit(0)
            if not inner:
                print("  (cancelled — pick again)")
                continue
            if inner == "all":
                for o in opts:
                    print(f"    - {_fmt_action_inline(o)}")
                continue
            if inner.startswith("/"):
                if _handle_slash(state, inner):
                    continue
            params = inner.split()
        try:
            _, parser = _PROMPT_FORMATS[cls]
            candidate = parser(params)
        except (ValueError, IndexError, TypeError) as e:
            print(f"  Could not parse: {e}. Try again.")
            continue
        if candidate in legal_set:
            return candidate
        print(f"  Built {_fmt_action_inline(candidate)} but it's not legal.")
        for o in opts[:6]:
            print(f"    legal: {_fmt_action_inline(o)}")
        if len(opts) > 6:
            print(f"    ... and {len(opts) - 6} more")


# ---------------------------------------------------------------------------
# Random agent
# ---------------------------------------------------------------------------

def _get_random_action(rng: random.Random, actions: list[Action]) -> Action:
    return rng.choice(actions)


# ---------------------------------------------------------------------------
# Screen clear
# ---------------------------------------------------------------------------

def clear_screen() -> None:
    # ANSI: clear screen + move cursor to home. Works on macOS/Linux terminals
    # and modern Windows Terminal. Falls back to extra newlines if needed.
    print("\x1b[2J\x1b[H", end="")


def render_round_log(round_number: int, log: RoundLog) -> None:
    lines = log.render_lines(round_number)
    if not lines:
        return
    print(f"=== Round {round_number} log ===")
    for line in lines:
        print(line)
    print()


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def play(seed: int, humans: set[int]) -> None:
    rng = random.Random(seed ^ 0xA6C01A)  # decorrelate from engine RNG
    state, env = setup_env(seed)
    log = RoundLog(humans)
    current_round = state.round_number

    while state.phase != Phase.BEFORE_SCORING:
        dec = decider_of(state)
        if dec is None:
            # Nature's round-card reveal — resolved by the env dealer, not shown
            # as a player turn.
            state = step(state, env.resolve(state))
            continue

        actions = legal_actions(state)
        if not actions:
            print("(no legal actions — engine state)")
            break

        if state.round_number != current_round:
            log.round_transition()
            current_round = state.round_number

        if dec in humans:
            clear_screen()
            render_round_log(current_round, log)
            render_state(state)
            action = _get_human_action(state, actions)
        else:
            action = _get_random_action(rng, actions)

        log.add(dec, action, current_round)
        state = step(state, action)

    clear_screen()
    render_round_log(current_round, log)
    render_scoring(state)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Play AgricolaBot in the terminal.")
    ap.add_argument("--seed", type=int, default=None,
                    help="Engine RNG seed (default: time-based).")
    ap.add_argument("--players", type=int, choices=(1, 2), default=2,
                    help="Number of human players (default: 2).")
    ap.add_argument("--human-seat", type=int, choices=(0, 1), default=0,
                    help="Seat for the human in 1-player mode (default: 0).")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    seed = args.seed if args.seed is not None else int(time.time())
    humans = {0, 1} if args.players == 2 else {args.human_seat}
    print(f"AgricolaBot - seed={seed} | humans={sorted(humans)}")
    try:
        play(seed, humans)
    except KeyboardInterrupt:
        print("\nGame interrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
