# AgricolaBot

A from-scratch Python implementation of the board game **Agricola** (2-player Family variant), built as the environment for training a strong AI agent via Monte Carlo Tree Search and reinforcement learning.

The long-term goal is an AlphaZero-style self-play agent. The current focus is the engine, heuristic baselines, and an MCTS scaffold that will eventually carry a learned value network.

---

## Status

The engine is complete and well-tested. Every action space in the Family game — including the heavyweight ones like Fencing, Farm Expansion, the harvest sub-phases, and Major Improvements — is fully implemented. The pending-decision stack handles multi-step turns and card triggers, with one card (Potter Ceramics) wired in to validate the trigger machinery end-to-end.

On top of the engine sits a stack of AI agents you can play against in the browser:

| Agent | What it is |
|---|---|
| `random` | Picks legal actions uniformly at random. |
| `simple` | Small hand-tuned evaluation function. |
| `hubris` | Round-2 CMA-ES-tuned V1 heuristic. **Currently the strongest standalone agent.** |
| `hubris_v3` | Larger ~250-parameter heuristic, iteratively tuned via block-coordinate descent. |
| `mcts` | Vanilla UCT + FPU + DAG with transpositions + macro-enumeration for Fencing. Currently weaker than the heuristic alone at low sim counts — the natural follow-up is PUCT with a learned value network. |

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
