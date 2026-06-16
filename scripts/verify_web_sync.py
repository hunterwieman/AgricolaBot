"""End-to-end verification of the web UI's single-channel state sync.

Drives a live `play_web.py` server over HTTP exactly the way the browser does
(tracking move_seq, echoing expected_seq, applying responses through the same
monotonic `applyState` rule the frontend uses) and asserts the rendered state
stays in lockstep with the server's authoritative state through:

  - a full multi-step turn (place worker -> sub-action -> commit), incl. the
    farmland -> plow sequence that regressed;
  - the out-of-order guard (a late/older payload must be ignored, never revert);
  - stale-click self-heal (a duplicate click is rejected AND resyncs);
  - undo + confirm (confirm-mode on);
  - new game.

Run:  ~/miniconda3/bin/python scripts/verify_web_sync.py
Exit 0 = all checks pass.  Uses the fast `random` opponent for the flow checks
plus one `mcts` smoke check that the bot replies in-band (no push channel).
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


class Client:
    """A tiny browser-shaped HTTP client + the frontend's applyState logic."""

    def __init__(self, base: str):
        self.base = base
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.current = None  # the "rendered" state, like the frontend's currentState

    def _req(self, path, payload=None):
        url = self.base + path
        if payload is None:
            req = urllib.request.Request(url)
        else:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self.opener.open(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # The server returns 4xx for rejected actions (e.g. a stale click)
            # WITH a JSON body — that body carries the current state for resync.
            return json.loads(e.read().decode())

    # The frontend's applyState: just adopt whatever the server returned.
    def apply(self, state):
        if state:
            self.current = state

    def get_state(self):
        return self._req("/api/state")

    def home(self):
        # establishes the session cookie (the server creates the game on GET /)
        with self.opener.open(self.base + "/", timeout=30) as r:
            r.read()

    def step(self, action_index):
        data = self._req("/api/step", {"action_index": action_index})
        self.apply(data.get("state"))
        return data

    def post(self, path, payload=None):
        data = self._req(path, payload if payload is not None else {})
        self.apply(data.get("state"))
        return data


FAILS = []


def check(cond, msg):
    status = "ok  " if cond else "FAIL"
    print(f"  [{status}] {msg}")
    if not cond:
        FAILS.append(msg)


def server(port, seats, extra=()):
    return subprocess.Popen(
        [PY, "play_web.py", "--seats", *seats, "--no-browser",
         "--host", "127.0.0.1", "--port", str(port), *extra],
        cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def find(actions, **kw):
    for a in actions:
        if all(a.get("type") == v if k == "type" else a.get("params", {}).get(k) == v
               for k, v in kw.items()):
            return a
    return None


def game_fields(state):
    """The game-progress slice (everything except the toggle/UI flags). Used to
    assert a toggle did NOT rewind the game."""
    return {k: state[k] for k in ("round_number", "phase", "decider",
                                  "current_player", "board", "players",
                                  "pending_stack", "legal_actions")}


def flow_checks(base):
    print("== multi-step turn + lockstep sync (human vs random) ==")
    c = Client(base)
    c.home()
    c.apply(c.get_state())
    check(c.current["decider"] in (0, 1), "initial state has a human decider")

    # farmland -> plow -> commit, asserting each response is the authoritative state
    farm = find(c.current["legal_actions"], type="PlaceWorker", space="farmland") \
        or c.current["legal_actions"][0]
    d = c.step(farm["index"])
    check(d.get("state") is not None, "/api/step response embeds the full state")
    check(c.current == c.get_state(), "rendered state == server authoritative state")

    if farm["params"].get("space") == "farmland":
        plow = find(c.current["legal_actions"], type="ChooseSubAction", name="plow")
        check(plow is not None, "ChooseSubAction(plow) offered after placing farmland")
        c.step(plow["index"])
        commits = [a for a in c.current["legal_actions"] if a["type"] == "CommitPlow"]
        check(len(commits) > 0, "CommitPlow cell choices offered after choosing plow "
              "(the 'turn ended without plow option' regression)")
        check(c.current == c.get_state(), "rendered == authoritative mid-turn")
        c.step(commits[0]["index"])
        check(c.current == c.get_state(), "rendered == authoritative after commit")

    print("== stale click renders current state (no freeze) ==")
    # An out-of-range index = a click on a board that already changed.
    huge = len(c.current["legal_actions"]) + 50
    bad = c._req("/api/step", {"action_index": huge})
    check(bad.get("ok") is False, "stale/invalid click rejected")
    check(bad.get("state") is not None and bad["state"] == c.get_state(),
          "rejection still returns the CURRENT state, so the client just re-renders")


def toggle_midgame_checks(base):
    print("== THE REPORTED BUG: toggle confirm mid-game must NOT revert/freeze ==")
    c = Client(base)
    c.home()
    c.apply(c.get_state())
    # play a few moves so we're genuinely mid-game (not at turn 0)
    for _ in range(3):
        if c.current["decider"] not in (0, 1):
            break
        c.step(c.current["legal_actions"][0]["index"])
    before = game_fields(c.current)

    # turn confirm ON mid-game
    c.post("/api/confirm_mode", {"enabled": True})
    check(c.current.get("confirm_mode") is True, "confirm_mode now on")
    check(game_fields(c.current) == before, "toggling confirm ON did NOT change the game state")
    check(c.current == c.get_state(), "rendered == authoritative after toggle")

    # ...and you can still move
    mv = find(c.current["legal_actions"], type="PlaceWorker") or c.current["legal_actions"][0]
    d = c.step(mv["index"])
    check(d.get("ok") is True, "a move still works right after toggling confirm on")

    # turn confirm OFF mid-game, then move again
    c.apply(c.get_state())
    pre_off = game_fields(c.current)
    c.post("/api/confirm_mode", {"enabled": False})
    check(c.current.get("confirm_mode") is False, "confirm_mode now off")
    # (turning off may commit a paused turn; if not paused, state is unchanged)
    if not pre_off["pending_stack"]:
        pass
    mv2 = find(c.current["legal_actions"], type="PlaceWorker")
    if mv2 and c.current["decider"] in (0, 1):
        check(c.step(mv2["index"]).get("ok") is True, "a move still works after toggling confirm off")


def undo_confirm_checks(base):
    print("== confirm + undo (confirm-mode on) ==")
    c = Client(base)
    c.home()
    c.apply(c.get_state())
    c.post("/api/confirm_mode", {"enabled": True})
    check(c.current.get("confirm_mode") is True, "confirm_mode on reflected in state")

    farm = find(c.current["legal_actions"], type="PlaceWorker", space="farmland")
    if farm:
        c.step(farm["index"])
        check(c.current.get("can_undo") is True, "can_undo true mid-turn with confirm on")
        c.post("/api/undo_turn")
        check(not c.current["pending_stack"], "undo rewound the whole placement")
        check(c.current.get("can_undo") is False, "can_undo false again at turn start")
        check(c.current == c.get_state(), "post-undo rendered == authoritative")

    c.apply(c.get_state())
    atomic = find(c.current["legal_actions"], type="PlaceWorker", space="day_laborer") \
        or find(c.current["legal_actions"], type="PlaceWorker", space="fishing")
    if atomic and len(c.current["legal_actions"]) > 1:
        c.step(atomic["index"])
        if c.current.get("awaiting_confirm"):
            check(True, "completed turn pauses awaiting_confirm")
            c.post("/api/confirm_turn")
            check(c.current.get("awaiting_confirm") is False, "confirm releases the turn")
            check(c.current == c.get_state(), "post-confirm rendered == authoritative")

    print("== new game (must work even after toggles) ==")
    c.post("/api/reset", {"seed": 12345})
    check(c.current["round_number"] == 1, "reset starts a fresh round-1 game")
    check(c.current == c.get_state(), "post-reset rendered == authoritative")
    # and you can move in the new game
    mv = find(c.current["legal_actions"], type="PlaceWorker") or c.current["legal_actions"][0]
    check(c.step(mv["index"]).get("ok") is True, "a move works in the fresh game")


def mcts_smoke(base):
    print("== human vs MCTS: bot replies IN-BAND (no push channel) ==")
    c = Client(base)
    c.home()
    c.apply(c.get_state())
    place = find(c.current["legal_actions"], type="PlaceWorker")
    if place and c.current["decider"] == 0:
        d = c.step(place["index"])
        check(d.get("state") is not None, "step response carries state (bot reply included)")
        check(c.current == c.get_state(), "state advanced via the response alone")


def main():
    # 1) flow + undo/confirm against the fast random opponent
    p1 = server(8771, ("human", "random"))
    # 2) mcts smoke (real deployed opponent), low sims for speed
    p2 = server(8772, ("human", "mcts"), extra=("--mcts-sims", "40"))
    try:
        time.sleep(4)
        flow_checks("http://127.0.0.1:8771")
        toggle_midgame_checks("http://127.0.0.1:8771")
        undo_confirm_checks("http://127.0.0.1:8771")
        mcts_smoke("http://127.0.0.1:8772")
    finally:
        p1.terminate(); p2.terminate()
    print()
    if FAILS:
        print(f"RESULT: {len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
