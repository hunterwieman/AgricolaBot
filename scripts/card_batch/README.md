# Card-batch tooling (the reusable "automatic process")

Durable copies of the generators that drive the at-scale card-implementation process
(full context: `CARD_BATCH_HANDOFF.md` at the repo root, which is the source of truth for
the process, machinery cheat-sheet, rulings, and current status). These were created in an
ephemeral session scratchpad and committed here so they survive compaction / a new session.

## Files
- **`gen_impl.py`** — the IMPLEMENT-workflow generator (the main reusable tool; used for deck
  C tier-1/tier-2 and deck D). `python gen_impl.py <scratchpad_dir> <DECK> <TIER|all>` reads
  the per-card triage specs under `<scratchpad_dir>/triage_cde/<DECK>_<num>.json` and emits a
  self-contained workflow `.js` (`<scratchpad_dir>/card-impl-<DECK><TIER>.js`): a
  `implement -> adversarial-verify` pipeline, one agent per implement card, SLIM 4-field impl
  schema + 3-field verify schema, with a "/"-cost auto-defer guard. Then `node --check` it and
  `Workflow({scriptPath})`. Agents do NOT touch `__init__.py`; wire that centrally afterward.
- **`reconstruct_specs.py`** — rebuilds the per-card triage spec files from the committed
  `card_triage_cde_specs.json` (the 256 C/D specs) into `<scratchpad_dir>/triage_cde/`, so
  `gen_impl.py` works after the original scratchpad is gone.
- **`card-triage-cde.example.js`** — a reference copy of the from-scratch TRIAGE workflow (one
  read-only agent per card: reads exact text, classifies implement/defer + tier, WRITES its
  spec JSON to `triage_cde/<DECK>_<num>.json`, returns a compact summary). To triage the
  un-triaged remainder (deck D-rest + deck E ≈ 233 cards), regenerate this shape's `CARDS`
  array to those cards (the generator that produced it is inlined in the session history; the
  pattern is documented in `CARD_BATCH_HANDOFF.md` §3 Phase B — it mirrors `gen_impl.py`).

## Typical resume (after compaction)
```
# 1) bring the triage specs back from the committed JSON
python scripts/card_batch/reconstruct_specs.py card_batch_work
# 2) generate + run the implement workflow for a deck/tier (e.g. deck D, all tiers)
python scripts/card_batch/gen_impl.py card_batch_work D all
node --check card_batch_work/card-impl-Dall.js     # then Workflow({scriptPath: ".../card-impl-Dall.js"})
# 3) integrate: wire passed cards into agricola/cards/__init__.py, run the full suite, commit (CARD_BATCH_HANDOFF.md §6)
```
