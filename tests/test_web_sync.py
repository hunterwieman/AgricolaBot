"""Pytest coverage for the web UI's server->client render + state sync.

Why this file exists: `scripts/verify_web_sync.py` drives a live `play_web.py`
server over HTTP and asserts the rendered state stays in lockstep with the
server's authoritative state — but it was a *standalone script*, never part of
`pytest`. So a change that broke only the web layer (e.g. a helper's signature
changing while a `play_web.py` call site was missed) passed the whole suite
green and shipped to production: every `snapshot()` -> `state_to_json` render
raised, 500'd the API, and the live board came up empty. This module wires the
core of that verification into `pytest` so the same class of break fails CI.

It spins up one fast `random`-opponent server (no model needed) on a free port
and exercises the full-render path in both game modes. The heavier `mcts`
smoke check stays in the standalone script (it needs the champion model).
"""
from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))

from verify_web_sync import Client, find  # noqa: E402  (script is import-safe)


def _free_port() -> int:
    """An OS-assigned free port, so parallel xdist workers never collide."""
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    """A live `play_web.py` (human vs the fast `random` opponent), torn down after."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "play_web.py", "--seats", "human", "random",
         "--no-browser", "--host", "127.0.0.1", "--port", str(port)],
        cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("play_web.py exited during startup")
            try:
                Client(base).home()          # succeeds once the server is serving
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("play_web.py did not become ready within 30s")
        yield base
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)


def _assert_full_render(state):
    """Both players rendered with a live decider — the render that used to 500."""
    assert state is not None
    assert len(state["players"]) == 2
    assert state["decider"] in (0, 1)


def test_family_snapshot_and_lockstep(base_url):
    """Family render + a multi-step turn stays in lockstep with the server.

    `get_state()` alone is the direct regression catch: on the broken build the
    snapshot raised and the request never completed, so this call would error
    rather than return a well-formed state.
    """
    c = Client(base_url)
    c.home()
    c.apply(c.get_state())
    _assert_full_render(c.current)

    # farmland -> plow -> commit, asserting each response IS the authoritative state.
    farm = find(c.current["legal_actions"], type="PlaceWorker", space="farmland") \
        or c.current["legal_actions"][0]
    d = c.step(farm["index"])
    assert d.get("state") is not None, "/api/step must embed the full state"
    assert c.current == c.get_state(), "rendered state == server authoritative state"

    if farm["params"].get("space") == "farmland":
        plow = find(c.current["legal_actions"], type="ChooseSubAction", name="plow")
        assert plow is not None, "ChooseSubAction(plow) offered after placing farmland"
        c.step(plow["index"])
        commits = [a for a in c.current["legal_actions"] if a["type"] == "CommitPlow"]
        assert commits, "CommitPlow cell choices offered after choosing plow"
        assert c.current == c.get_state(), "rendered == authoritative mid-turn"
        c.step(commits[0]["index"])
        assert c.current == c.get_state(), "rendered == authoritative after commit"


def test_cards_snapshot_renders(base_url):
    """The break was mode-independent (`_player_to_dict` runs for both modes);
    a Cards-mode reset exercises that render path too."""
    c = Client(base_url)
    c.home()
    d = c.post("/api/reset", {"game_mode": "cards", "seed": 1, "hand_mode": "random"})
    assert d.get("ok") is True, f"cards reset failed: {d.get('error')}"
    _assert_full_render(d.get("state"))


def test_legal_actions_grouped_small_groups_first():
    """The snapshot's legal-actions array is presentation-reordered (user
    directive 2026-07-14): actions group by card, groups sort by ascending
    size, and each dict keeps its ORIGINAL engine index — so a wide card's
    100+ variants never bury a 1-option card, and clicks still submit the
    right engine index. Pure-function test; no server needed."""
    from agricola.actions import CommitPlayOccupation, Stop
    from agricola.setup import setup
    import play_web

    # A 3-variant wide card, a 1-option card, and a non-card singleton (Stop),
    # in engine order.
    actions = [
        CommitPlayOccupation(card_id="wide_card", variant="a"),   # engine idx 0
        CommitPlayOccupation(card_id="wide_card", variant="b"),   # engine idx 1
        CommitPlayOccupation(card_id="wide_card", variant="c"),   # engine idx 2
        CommitPlayOccupation(card_id="narrow_card"),              # engine idx 3
        Stop(),                                                   # engine idx 4
    ]

    # Singletons first (non-card singleton keys sort before card keys), the
    # size-3 group last, within-group engine order preserved.
    assert play_web._grouped_action_order(actions) == [4, 3, 0, 1, 2]

    dicts = play_web._legal_actions_to_dicts(setup(0), actions)
    # Array order is the presentation order...
    assert [d["type"] for d in dicts] == [
        "Stop", "CommitPlayOccupation",
        "CommitPlayOccupation", "CommitPlayOccupation", "CommitPlayOccupation"]
    # ...but every index is still the action's position in the ENGINE list.
    assert [d["index"] for d in dicts] == [4, 3, 0, 1, 2]
    assert dicts[1]["params"]["card_id"] == "narrow_card"
    assert [d["params"]["card_id"] for d in dicts[2:]] == ["wide_card"] * 3
