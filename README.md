# AgricolaBot

A from-scratch Python implementation of the board game **Agricola** (2-player Family variant), built as the environment for training a strong AI agent via Monte Carlo Tree Search and reinforcement learning.

The long-term goal is an AlphaZero-style self-play agent. The current focus is the engine, heuristic baselines, and an MCTS scaffold that will eventually carry a learned value network.

---

## Status

The engine is complete and well-tested. The entirity of the Family game — the version without cards — is fully implemented. The pending-decision stack handles multi-step turns and card triggers, with one card (Potter Ceramics) wired in to validate the trigger machinery end-to-end.

On top of the engine sits a stack of AI agents you can play against in the browser:

| Agent | What it is |
|---|---|
| `random` | Picks legal actions uniformly at random. |
| `simple` | Small hand-tuned evaluation function. |
| `hubris` | Round-2 CMA-ES-tuned V1 heuristic. |
| `hubris_v3` | Larger ~250-parameter heuristic, iteratively tuned via block-coordinate descent. The strongest heuristic agents. |
| `nn` | The trained network used as a 1-turn-lookahead evaluator. The default checkpoint (`nn_models/best`) is the **joint shared-trunk model** — one network producing both a value estimate and a policy — used here for value only. Stronger than every heuristic. |
| `mcts` | **PUCT** (AlphaZero-style: value + policy prior + DAG with transpositions), using the joint network for both the leaf value and the search prior. Amplifies the network with tree search; stronger with more simulations, at the cost of speed. **The strongest agent to date**, and the default opponent online. Backed by a fast C++ search binary when available (≈4× the Python search). |

Cards, occupation/minor-improvement support, and the AlphaZero-style training loop are future work.

---

## Quick start

Requires **Python 3.10+** and two packages:

```bash
pip install numpy cma
```

Then either play in the browser or watch a game in the terminal:

```bash
# Browser UI — play as human against the strongest heuristic
python play_web.py --seats human hubris

# Browser UI — watch two AIs play (step-through with Enter / Advance button)
python play_web.py --seats hubris hubris_v3

# Terminal — watch a random-vs-random game with a per-round narrative
python play_random_game.py --trace

# Terminal — any agent matchup
python play_heuristic_game.py --p0 hubris --p1 hubris_v3
```

The browser UI opens at `http://127.0.0.1:8000` and renders the farmyard, action board, resource counts, and a per-round score breakdown. Click an action to take it; press Enter (or the Advance button) when both seats are AI.

To run the test suite:

```bash
pytest
```

---

## Playing against the AI

All play happens in the browser UI (`play_web.py`). You take one seat as `human`; the other is an AI. The game can run **online** (deployed to Fly.io as a single always-on container — see [`DEPLOY.md`](DEPLOY.md)) or **locally**.

### Running it

Locally:

```bash
# Default: you (P0) vs the MCTS bot (the strongest agent)
python play_web.py

# Pick your opponent and seat explicitly
python play_web.py --seats human nn        # vs the 1-turn network
python play_web.py --seats human hubris_v3 # vs the strongest heuristic
python play_web.py --seats nn human        # play as the second player
```

Seats are passed as `--seats <P0> <P1>`, where P0 acts first in the turn order assigned at setup (the seat with the starting-player advantage is decided randomly per game). The UI opens at `http://127.0.0.1:8000`. Click an action to take your turn.

The AI network is fixed at startup via `--nn-model PATH` (default `nn_models/best`, the joint shared-trunk champion) — either a checkpoint directory or an explicit stem. It applies to both the `nn` seat and the `mcts` leaf+prior. To switch checkpoints, restart the UI; to change seats or any of the per-game parameters below, just use the in-browser **New game** button.

### New-game parameters

Clicking **New game** prompts for three values (each has a sensible default — press Enter to accept):

- **Seed** — fixes the random setup (card reveal order + who gets the starting-player advantage). Leave blank for a random game; reuse a seed to replay the same setup.
- **Sims/move** — the MCTS simulation budget per move (default **800**). More simulations mean stronger but slower bot moves. If the bot feels sluggish on your machine, lower it (e.g. 300–500).
- **Opponent explore (prior-mix)** — blends the bot's policy prior with a uniform distribution by this weight (default **0**, i.e. pure policy). A small value (e.g. 0.05) makes the bot consider a wider set of moves; testing found it **not stronger**, so it's off by default and mostly useful if you want a less predictable opponent.

### Toggles (top bar)

- **Fast mode** — automatically submits any turn that has exactly one legal action (and forced/singleton sub-actions), so you only stop on real decisions. Recommended on.
- **Confirm turns** — pauses after each of *your* non-forced turns, showing **Confirm** / **Undo** before the bot replies. Forced/singleton turns are never paused. Harvest **feeding** and **breeding** count as separate turns. **Undo is only available when this is on** (it rewinds your in-progress turn). The Confirm/Undo controls appear above the player boards.
- **Show analysis** — overlays the bot's read on *your* options: for each legal move, its MCTS **Q-value** (higher = better for you) and **visit count**. It is read-only (never changes the game), runs in the background (never blocks your move), and is cancelled the moment you move. To get coverage of more than the top few moves, analysis mixes a little uniform prior into the search.
  - **explore** (under the toggle) — the analysis search's exploration constant (`c_uct`, default **0.5**, matching how the bot itself plays). Raise it to make the analysis explore more widely. Analysis-only; it does not affect how the bot plays.

### Notes on the MCTS opponent

MCTS amplifies the network by wrapping it in tree search — more simulations generally mean stronger play, at the cost of speed. It uses the joint network for **both** the leaf value and the search prior (PUCT). When the bundled C++ search binary is present it runs there (≈4× faster than the Python search); otherwise it falls back to Python MCTS automatically.

---

## Project layout

```
agricola/           Game engine package — frozen-dataclass state, pure-function transitions,
                    legal-action enumeration, pending-decision stack, card framework.
agricola/agents/    Agent implementations: random, heuristics (V1/V2/V3), MCTS, plus the
                    `restricted_legal_actions` strategic-prior wrapper.
scripts/            Tooling — CMA-ES tuner, profilers, match drivers, MCTS sweeps.
tests/              636 pytest tests with shared factories / scripted-action helpers.
tuned_configs/      Persistent artifacts from tuning runs (configs, logs, CMA-ES state).
static/, templates/ Browser UI assets served by play_web.py.
task_files/         Historical design specs, frozen at the time each task landed.
play*.py            Top-level entry points (terminal play, browser play, random / heuristic drivers).
```

---

## Design documentation

This project has unusually thorough documentation. If you want to dig in:

| Doc | What it covers |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Master architectural reference — design principles, engine internals, pending stack, conventions. The first thing to read. |
| [`STRATEGY.md`](STRATEGY.md) | AI strategy and algorithm decisions; rationale behind each project phase. |
| [`RULES.md`](RULES.md) | Complete rules reference for the 2-player Family game, with design clarifications. |
| [`MCTS_DESIGN.md`](MCTS_DESIGN.md) | Comprehensive design spec for the MCTS phase. |
| [`HUBRIS_V1_NOTES.md`](HUBRIS_V1_NOTES.md) | Per-term breakdown of the V1 heuristic, the first non-random AI player. |
| [`V3_DESIGN.md`](V3_DESIGN.md) | Architecture of the V3 heuristic evaluator, the second non-random AI player. |
| [`V3_TRAINING_PIPELINE.md`](V3_TRAINING_PIPELINE.md) | Operational guide to the CMA-ES tuning pipeline. |
| [`SESSION_HISTORY.md`](SESSION_HISTORY.md) | Running log of what was built each session, including design decisions and bugs caught. |
| [`FILE_DESCRIPTIONS.md`](FILE_DESCRIPTIONS.md) | Per-file descriptions for every module. |
| [`TEST_DESCRIPTIONS.md`](TEST_DESCRIPTIONS.md) | Per-file coverage descriptions for the test suite. |

---

## License & game rights

This is a fan-built engine for personal learning and AI research. *Agricola* is a board game designed by Uwe Rosenberg, published by Lookout Games / Z-Man Games. This project includes none of the original game's copyrighted text, art, or rulebook content — only mechanics necessary for a working engine.
