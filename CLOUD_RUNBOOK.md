# Cloud Runbook — running code on GCP without wasting money

Paste this into any session when you want to run compute-heavy work (e.g. self-play
data generation) on a Google Cloud VM instead of the laptop.

## The one thing to understand about cost

**A VM bills per second for as long as it exists — even when idle, even when you've
closed the chat.** The chat session itself is free. **Deleting the VM is the only thing
that stops the charges.** There is no other "off switch." So the rule is: *every VM you
create, you delete when the job is done.*

## Your Google Cloud setup — the facts

**Account & credit.** GCP project `project-b06e1d45-2668-4fee-b71`, region
**us-central1**, billing active on a paid account. You have a **$300 free-trial credit
that expires 2026-09-20** — every run below is drawn from that first, so this is
effectively free for the foreseeable future. Budget alerts email you at **$25 / $45 /
$50** so you'll hear about any runaway spend long before it matters. The `gcloud` CLI is
installed and authenticated on this Mac.

**Compute you can use.** Up to **96 on-demand ARM vCPUs** in us-central1. These are
**T2A** machines (Ampere Altra ARM, the same architecture as your M1, which is why the
binary just rebuilds). They come in fixed sizes; 96 vCPUs is e.g. 2× `t2a-standard-48`
or 12× `t2a-standard-8` (same total throughput — fewer, bigger boxes are simpler to
manage):

| Machine type | vCPUs | RAM | ~On-demand price |
|---|---|---|---|
| `t2a-standard-8` | 8 | 32 GB | ~$0.30/hr |
| `t2a-standard-16` | 16 | 64 GB | ~$0.60/hr |
| `t2a-standard-48` | 48 | 192 GB | ~$1.80/hr |
| **Full 96-vCPU fleet** | **96** | — | **~$3.5/hr** |

Prices are approximate (~$0.037/vCPU-hr), grounded in an actual run, not list-price
guesses. Disk and same-region storage/egress are negligible.

**Spot is the default — strongly prefer it (it's ~3× cheaper).** Spot (interruptible)
machines cost **~$0.012/vCPU-hr** — the **96-vCPU Spot cap runs ~$1/hr** versus ~$3.5/hr
on-demand for the same 96 cores. Google can reclaim a Spot box with ~30 seconds' notice,
but that's a non-issue here: the generation workload is interruption-tolerant, and its
resume logic simply re-runs any games a reclaimed box didn't finish. So **default every
run to Spot** by passing `--provisioning-model=SPOT`. Spot now covers the full T2A
regional capacity (96 cores ≈ ~12× the M1), so there's rarely a reason to use on-demand
at all — fall back to it only for a one-shot job that truly can't absorb an interruption.
Spot was auto-denied on the brand-new account, then granted (first 48, then 96) once it
had a few days + ~$20 of spend; jumps to 128 were still auto-denied, so raise the cap in
modest steps as the account ages.

**How fast it generates.** Measured at **~12 games/min per core at 800 sims** (roughly
halving to ~6/core at 1600 sims, since doubling the search doubles the work). So the
full 96-vCPU fleet does **~1,150 games/min at 800 sims** — about **13× your M1** (~85
games/min). Concretely, a **40,000-game run takes ~35 min at 800 sims** (~70 min at
1600) and costs **~$2**.

**Want more than 13×?** Two levers, both for later once the account is established:
re-request the on-demand cap above 96 (toward ~160 for the full 20×), or get Spot
approved for ~3× cheaper runs.

**Check current state anytime:**

```sh
gcloud compute instances list                      # what's running (and billing)
gcloud compute project-info describe \
  --format="value(quotas)" | tr ';' '\n' | grep CPUS_ALL_REGIONS   # your vCPU cap + usage
```

## The build/run recipe (this project)

The C++ `selfplay` binary is ARM-native, so it rebuilds cleanly on a GCP ARM box. It
needs only `build-essential cmake python3-pybind11` — no PyTorch. Upload `cpp/` (minus
`build/`) plus the current champion's weights. **Always reference the weights via the
`nn_models/cpp_export_best` symlink** (it auto-updates to whatever model is promoted —
never hardcode a specific export dir, which goes stale on the next promotion). Tar with
`-h` so the symlink is dereferenced into the real weight files for upload. Then:

```sh
cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release \
  -Dpybind11_DIR=/usr/lib/python3/dist-packages/pybind11/share/cmake/pybind11
cmake --build cpp/build --target selfplay -j$(nproc)
```

Generate games (single-threaded per process; run one process per core for parallelism):

```sh
cpp/build/selfplay --mcts --game-idxs "0,1,2,..." --base-seed B --sims 800 \
  --c-uct 1.0 --temperature 1.0 --prior-mix 0.0 --select-by visits \
  --model-dir nn_models/cpp_export_best --out-dir OUT
```

Each game writes a `trace_<idx>.json`. Replay them into training `GameRecord`s locally
with `agricola.agents.nn.trace_replay.replay_trace`.

## The full loop (create → run → COLLECT → DELETE)

```sh
ZONE=us-central1-a
NAME=agricola-job

# 1. Create the VM. Default to Spot (--provisioning-model=SPOT) — it's ~3x cheaper.
#    --scopes=cloud-platform lets it clean up / write to storage itself.
#    Drop --provisioning-model=SPOT (i.e. use on-demand) only if you need >48 vCPUs
#    in one run or the job truly can't tolerate a mid-run interruption.
gcloud compute instances create $NAME --zone=$ZONE \
  --machine-type=t2a-standard-8 \
  --provisioning-model=SPOT --instance-termination-action=DELETE \
  --image-family=debian-12-arm64 --image-project=debian-cloud \
  --boot-disk-size=20GB --scopes=cloud-platform

# 2. Push code up. ALWAYS tar first — far faster, and data/pickles compress ~9x.
#    -h dereferences the cpp_export_best symlink into the real weight files.
tar czhf /tmp/job.tgz --exclude='cpp/build' cpp nn_models/cpp_export_best
gcloud compute scp /tmp/job.tgz $NAME:~ --zone=$ZONE --quiet

# 3. Build + run over SSH (first SSH also generates your key — may take ~60s).
gcloud compute ssh $NAME --zone=$ZONE --quiet --command="<build + run commands>"

# 4. Collect results: tar on the VM, scp down.
gcloud compute ssh $NAME --zone=$ZONE --quiet --command="tar czf ~/out.tgz <out-dir>"
gcloud compute scp $NAME:~/out.tgz /tmp/out.tgz --zone=$ZONE --quiet

# 5. DELETE THE VM. This is the step that stops all billing.
gcloud compute instances delete $NAME --zone=$ZONE --quiet
```

## Self-deleting jobs (fire-and-forget — no babysitting)

For a long run you don't want to watch, make the VM **delete itself when done** so it
can't linger if you close the laptop or the chat ends. Two safety layers, used together:

**Layer 1 — the job script deletes the VM as its last step.** A VM learns its own name
and zone from the metadata server, then deletes itself. Wrap it so it deletes *even if
the work fails* (`trap ... EXIT`), and **upload results to durable storage first** —
once the VM is gone, its local disk is gone too:

```sh
#!/bin/bash
# runs ON the VM. Needs --scopes=cloud-platform at create time.
self_delete() {
  NAME=$(curl -s -H "Metadata-Flavor: Google" \
    http://metadata.google.internal/computeMetadata/v1/instance/name)
  ZONE=$(curl -s -H "Metadata-Flavor: Google" \
    http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $NF}')
  gcloud compute instances delete "$NAME" --zone="$ZONE" --quiet
}
trap self_delete EXIT          # delete on ANY exit — success, error, or crash

# ... build + run the job ...
gsutil -m cp -r OUT gs://YOUR_BUCKET/run_name/   # <-- save output BEFORE the VM dies
```

Pass this script at creation with `--metadata-from-file startup-script=job.sh` and the
VM runs it on boot, fully detached — you can close everything and it cleans up after
itself. (Output goes to a bucket you make once: `gsutil mb -l us-central1 gs://NAME`.)

**Refinement — gate self-delete on *success*, not on any exit, for a first-of-path run.**
`trap self_delete EXIT` deletes on success, error, *and* crash — which erases the very
evidence you need when a brand-new job fails (see "Self-deleting boxes erase their own
evidence" below). The best-of-both pattern: have the job print a `JOB DONE` marker only
*after* it has uploaded its output, then run a small detached watcher that deletes the box
**only once that marker appears**. A setup failure (no marker) leaves the box alive and
inspectable; the `--max-run-duration` backstop (Layer 2) still guarantees it can't bill
forever. This honors fire-and-forget for proven jobs without blinding you on new ones:

```sh
# armed AFTER the job is launched (needs --scopes=cloud-platform + the SA's
# compute.instanceAdmin.v1 role, same as any self-delete):
nohup setsid bash -c '
  while ! grep -q "JOB DONE" ~/job.out 2>/dev/null; do sleep 30; done
  N=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)
  Z=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ "{print \$NF}")
  gcloud compute instances delete "$N" --zone="$Z" --quiet
' >/dev/null 2>&1 < /dev/null &
```

**Layer 2 — a hard time limit (the real backstop).** Even a self-deleting script fails
to delete if it hangs forever. This flag makes Google delete the VM after a set time no
matter what the code is doing — so a stuck job can never bill indefinitely:

```sh
gcloud compute instances create $NAME --zone=$ZONE \
  --machine-type=t2a-standard-8 \
  --provisioning-model=SPOT \
  --image-family=debian-12-arm64 --image-project=debian-cloud \
  --scopes=cloud-platform \
  --max-run-duration=3h --instance-termination-action=DELETE
```

Set the duration comfortably above the expected runtime. Layer 1 handles the normal
case in seconds; Layer 2 guarantees you never pay for a hung box past the limit.

## Before you walk away — the money check

Run this and confirm it's empty. If it says "Listed 0 items," you are paying nothing:

```sh
gcloud compute instances list
```

If anything is listed, delete it: `gcloud compute instances delete NAME --zone=ZONE --quiet`.

## Gotchas

- **Stopping ≠ deleting.** A *stopped* VM still bills for its disk. Always **delete**.
- **Long unattended jobs:** have the VM delete *itself* when finished (a final
  `gcloud compute instances delete` in its own startup/run script). This needs
  `--scopes=cloud-platform` set at create time. That way an idle box never lingers if
  you close the laptop or the chat ends.
- Build with `-DCMAKE_BUILD_TYPE=Release` — debug builds measure throughput wrong.
- `tar` before every `scp`, both directions.
- Full project context (sizing, throughput numbers, costs) lives in the memory note
  `project-gcp-cloud-datagen`.

## Best practices — lessons from real failures

Each of these cost real debugging time on a live run; they're written down so the next
session starts ahead of where this one did.

### Resilience (the run *will* be interrupted — design for it)

- **Make every unit resumable and idempotent.** Give each box a fixed slice of the work,
  have it skip whatever it already uploaded, and write a completion marker only at the
  end. Then a restart re-does only the unfinished part. This is the real safety net: when
  the orchestrator died mid-run, **169k already-generated games survived untouched** and a
  restart finished the rest — a dead orchestrator cost *time, not data*.
- **Upload outputs incrementally** (e.g. `gsutil rsync` every ~3 min), so a preemption or
  kill loses minutes of work, not hours.
- **Build once, cache the artifact, download on relaunch.** Under heavy Spot preemption a
  campaign relaunched its boxes ~30 times — and each relaunch rebuilt the C++ binary from
  source (~4 min), so most of the wall-clock went to *compiling, not generating*. Have the
  first box upload its built binary to the bucket and every later box download it (~10–30 s,
  with a `selfplay -h` smoke-test fallback to rebuild if it won't run). Make relaunches cheap.
- **A laptop-side orchestrator loop is fragile.** A `run_in_background` bash loop got reaped
  when the session/auto-mode ended and the run stalled for hours unnoticed. Mitigations:
  launch it detached (`nohup`), keep a self-scheduled wakeup that re-checks and restarts it,
  and — because the work is resumable — treat its death as a time cost, not a data loss.
- **Spread a Spot fleet across zones — don't let every box pile into one.** An orchestrator
  that tries zones in a fixed order (`a` then `b` then …) lands *every* box in the first
  zone that has capacity, so all of them share that one zone's Spot pool. When that pool is
  contended the whole fleet gets preempted together, repeatedly — one box was relaunched ~5×
  in `us-central1-a` before a single epoch landed, because each relaunch went straight back
  into the same exhausted zone and was reclaimed mid-download. Fix: give each unit a
  *different home zone* (rotate `ZONES[idx % n]` as its first choice, fall through to the
  rest only if the home is full). 6 archs over 4 zones → ≤2 per zone instead of 6, so a
  zone's preemption wave takes out one or two boxes, not the fleet. Combine with cheap
  relaunches (pd-ssd + stubbed inputs, below) so the relaunches it *can't* avoid are fast.
- **Two independent teardown layers** so nothing bills forever: a self-delete `trap` on the
  job script *and* `--max-run-duration ... --instance-termination-action=DELETE`.

### Correctness pitfalls (these fail *silently* and corrupt output)

- **Never pass large data as a command-line argument.** Linux caps a single `argv` string at
  **128 KB** (`MAX_ARG_STRLEN`). Passing a 30k-element id list (~150 KB) to a helper made the
  command silently fail → empty output → downstream produced zero work yet reported success.
  Pass big lists via a **file or stdin**. Note this is *size-dependent*: a 10k-element slice
  (~50 KB) fit and "worked," so it passed in testing and only blew up at full scale.
- **`gsutil cp -I` silently consumed only ~2 of N stdin URLs (gsutil 5.37, ARM Debian 12).**
  Both `gsutil -m cp -I dest/ < urls.txt` and `cat urls.txt | gsutil cp -I dest/` copied just
  the first two objects of a 203-line list, then reported success — a partial download that
  reads as "done." This contradicts the "pass big lists via stdin" advice above for *this*
  gsutil. The reliable form for a few-hundred URLs is the **args form**: `gsutil -m cp
  $(cat urls.txt) dest/` (203 URLs ≈ 16 KB, well under the 128 KB argv cap). For truly huge
  lists where neither stdin nor argv is safe, `cp` a prefix and filter, or batch the args.
  **Always verify the downloaded file count against the expected count and abort if short** —
  the silent truncation is invisible otherwise.
- **`set -u` + a multi-var `local` reads the *outer* scope, not the just-assigned one.**
  `local P0=$1 P1=$2 LABEL="${P0}_${P1}"` expands `${P0}` *before* `local` creates the
  locals, so it reads an unset outer `P0` → under `set -u` the script dies with
  `P0: unbound variable` (here, before any work ran). Split it: `local P0=$1 P1=$2` then
  `local LABEL="${P0}_${P1}"`. This is exactly why the "dry-run logic-bearing scripts
  locally" rule below matters — `bash -n` plus a 3-line `set -uo pipefail` repro on the
  laptop catches it in seconds; shipping it cost a full create→ssh→fail cloud round-trip.
- **Make "done" earned, not assumed.** A completion marker was written even though the box
  generated *zero* output (the step before it had silently failed). A success signal must be
  gated on the actual work product existing — **count the output files and refuse to mark
  done if the count is short**. Otherwise a silent failure masquerades as success and the
  orchestrator skips real work.
- **Hard-guard degenerate inputs.** A bad/empty metadata value produced an empty work slice
  (`range [0,0)`) that silently wrote a bogus "done". Fail loudly on degenerate inputs; never
  let them no-op straight into a success state.
- **`gcloud --metadata` is comma-delimited.** A value containing commas (e.g.
  `sims-list=400,800,1600`) breaks parsing with a cryptic "Bad syntax for dict arg." Use the
  custom-delimiter form: `--metadata=^@^k1=v1@k2=v2,with,commas`.
- **A self-deleting box's startup crash looks exactly like a Spot preemption — distinguish them
  with the operations log before diagnosing.** A `trap self_delete EXIT` (the fire-and-forget
  pattern) fires on *any* script exit, including a crash. So a startup bug makes boxes vanish and
  the orchestrator relaunch them — indistinguishable, from the outside, from a preemption storm.
  The tell is in `gcloud compute operations list`: filter `operationType=compute.instances.preempted`
  vs the `insert`/`delete` counts. A run with **98 inserts, 33 deletes, but only 3 preemptions**
  was *crash-looping*, not being preempted — every box self-destructed in its own startup script.
  Don't theorize about capacity until you've checked the preemption count; it's one query and it
  settles the question.
- **`grep -c` + `|| echo 0` under `pipefail` emits TWO zeros, not one.** `x=$(… | grep -c PAT || echo 0)`
  on no match: `grep -c` prints `0` *and* exits 1, so under `set -o pipefail` the pipeline fails and the
  `|| echo 0` *also* runs — `x` becomes `"0\n0"`. The next `$(( N - x ))` is then a math syntax error,
  which (no `set -e`) silently leaves the downstream var empty → a CLI flag like `--max-epochs ""` →
  the program aborts → the box's EXIT trap self-deletes it. This is the bug that made every fresh Spot
  training box die in its resume logic *before training started* (0 epochs banked, ~30 self-deletes). Fix:
  `grep -c` already prints `0` on no match — drop the `|| echo 0` (use `|| true` only to swallow the exit
  code) and sanitize to a single integer (`x=${x//[^0-9]/}; x=${x:-0}`). Reproduce these one-liner shell
  bugs **locally** — it's instant and free, vs a multi-minute cloud round-trip per guess.

### Diagnosing a repeated failure — measure before you theorize

**The principle.** When units fail over and over, the costly mistake is not guessing wrong — it is
*acting* on a guess before measuring. A plausible theory ("the machines are getting preempted")
feels like understanding and licenses building fixes; if it is wrong, those fixes are hours spent
improving things *next to* a problem you never located. There is almost always one cheap measurement
that separates the real cause from the merely plausible one. Take that measurement **first**, before
writing any fix.

Worked example of getting this exactly wrong. A fleet of training boxes kept vanishing and being
relaunched — which looks identical to a Spot-preemption storm. So effort went into faster disks,
spreading boxes across zones, and slimming the download (all genuine improvements; none of them the
problem). The boxes were actually *self-deleting*, because a one-line shell bug crashed every box in
its startup script before training ever began. Two measurements would have caught it in minutes
instead of hours: (1) the cloud operations log showed **3 preemptions against ~30 self-deletes** —
proving it was not a capacity problem; (2) the offending shell line reproduced the crash **locally in
seconds**. The very plausibility of "preemption" is what stopped the search.

Handles that make the skepticism mechanical, so it does not depend on someone happening to doubt the
theory:

- **Name the alternatives and the discriminating test before building a fix.** When a diagnosis
  starts to form, write it down explicitly: *the candidate causes are X, Y, Z; the cheapest thing
  that tells them apart is ___* — then go run that, not a fix. For "boxes keep disappearing," the
  discriminator is the operations log (`compute.instances.preempted` count vs `insert`/`delete`
  counts). One query settles it.
- **Deterministic-zero is a code smell; partial/random is an environment smell.** *Zero* successes
  across *many* attempts means every unit is failing *identically* → look for a deterministic bug,
  not bad luck. A stochastic cause (preemption, transient capacity) would let *some* unit slip
  through occasionally; the total absence of any success is itself the clue that it is code, not
  environment.
- **A logic-bearing script is code — dry-run it locally before fanning it out to N machines.** Any
  startup or orchestration script with arithmetic, parsing, or conditionals can be exercised on the
  laptop in seconds. Shipping it untested to a fleet converts a free local bug into a
  minutes-per-iteration cloud bug, multiplied by every box and every relaunch.
- **"It kind of makes sense" is a yellow flag, not a green light.** Plausibility is not evidence.
  After forming a hypothesis, try to *falsify* it: "if it were preemption, the operations log would
  show preemptions — does it?" If you cannot point at the specific evidence that confirms a
  diagnosis, you are still guessing.
- **Motion is not progress.** A fix that does not address the *diagnosed root cause* is decoration —
  it can feel productive while the real failure is untouched. Every fix should trace back to the
  evidence that located the cause.

### Debugging on cloud boxes

- **`/root` is mode 700 — read startup logs with `sudo`.** Job scripts run as root and write
  under `/root`; a non-root SSH user's `ls`/`cat` there silently returns *nothing*, which
  reads as "empty / missing file" when it's really permission-denied. Don't trust a
  silent-empty result — re-check with `sudo`. Always `exec > >(tee /var/log/job.log) 2>&1`
  in the startup script so there's a log to read.
- **Reproduce the *actual* failing path, at production scale.** A simplified, no-build debug
  box failed to reproduce a bug that lived in the post-build path; and because the bug was
  size-dependent, small inputs passed. Run the real script with real inputs.
- **Self-deleting boxes erase their own evidence.** To inspect a box that fails-then-vanishes,
  launch one copy with self-delete disabled (swap the `trap self_delete EXIT` for a
  `sleep`) and SSH in while it's still alive.
- **A process that is "mysteriously slow" is not a mystery — `py-spy dump` shows the exact line
  it's on.** When a long-running step makes no progress and you're tempted to conclude "it's just
  slow," don't guess — `pip install py-spy` into the venv and `sudo py-spy dump --pid <pid>` prints
  the live Python stack (no restart, no code change). One dump caught a finalize step spending ~20
  min in a per-row `np.random.default_rng(...)` construction (a split mask that should have deduped
  to per-game) — a hotspot that *looked* like an inherent cost until the stack named the line. This
  is "measure before you theorize" for a single hot process: the dump is one command and it converts
  a guess into a fact.

### Performance & sizing

- **Estimate from data measured on the actual fleet shape, not a single-process
  microbenchmark.** Per-core throughput drops from (a) more processes per socket
  (memory-bandwidth contention — the vectorized inference inner loop is bandwidth-bound, so
  16 procs/socket run each core meaningfully slower than 8) and (b) preemption rebuild/boot
  overhead. Ignoring these made wall-clock estimates 2–4× optimistic.
- **The external-IP quota (default ~8/region) often binds before the CPU quota.** It caps the
  *number* of boxes, which forces fewer-but-bigger boxes — and bigger boxes then suffer more
  per-socket contention (above). Weigh both limits when choosing the fleet shape; the
  throughput-optimal shape is the smallest boxes that still fit under the IP cap.
- **Bake a golden machine image so boxes boot ready, not building.** Most per-box setup is
  *not* shipped from the operator's machine — torch is ~200 MB pulled from PyPI and the code is
  only a ~5 MB bucket tarball — so the slow part is installing the environment (Debian + a venv
  with torch/numpy), ~3–4 min of `pip install torch` + apt on every fresh box. Bake that
  environment into a custom image once (`gcloud compute images create`), then launch fleet boxes
  `--image <name>`; they skip the install entirely, so boot→ready drops to ~1 min and a
  spot-preemption relaunch is nearly free. Same principle as build-once-cache-the-binary
  (above), generalized from the one binary to the whole environment.
- **Parallelize prep across shards — don't serialize it.** A multi-shard replay/encode that
  loops over its run-dirs sequentially on one box leaves most CPUs idle while the remaining
  shards wait their turn. Run each shard's encode concurrently (separate boxes or processes)
  instead — the per-shard inputs already live in the bucket, so the shards don't depend on each
  other and there's nothing to serialize on.
- **For download-heavy boxes, use `--boot-disk-type=pd-ssd` — the default `pd-standard` is HDD
  and caps write throughput.** A box that pulls tens of GB from a bucket before training is
  bottlenecked on how fast it can *write* that data to its local disk, not the network or
  per-file request overhead. The default boot disk is `pd-standard` (spinning-disk-class):
  sustained write throughput scales with size and lands around **~12–30 MB/s for a 100 GB
  disk** — so a 62 GB pull takes ~35 min. `pd-ssd` (flash) does ~240+ MB/s for the same disk,
  ~10× faster, for a few cents more over a short-lived box. The tell that you're disk-bound and
  not request-bound: the files are already tens of MB each (so per-object HTTP overhead is
  negligible) yet `gsutil -m rsync` still crawls. **Consolidating many files into one tarball
  does NOT help here and makes it worse** — you write the same bytes to the same slow disk, then
  *extraction* reads + rewrites them a second time (2× the HDD I/O). Tarballs only win when the
  bottleneck is per-object *request* overhead (thousands of KB-scale files), which a throughput
  cap is not. This matters most for **preemption relaunches**, which re-download the full corpus
  to a fresh disk every time.
- **Don't download data the consumer only *counts*, never *reads*.** The joint-trunk encode
  cache (`shared_<tag>_chunks/*.npz`) IS the training data; the raw game pickles
  (`games/*.pkl`) that produced it are, on a cache HIT, only *counted* by the completeness check
  (one chunk per pickle — `shared_dataset.py` `_cache_complete`/`_iter_worker_pickles`), never
  opened. So a training box that has the chunk cache does not need the pickle *contents* at all —
  shipping them across the network (here ~26 GB of a ~62 GB pull) is pure waste. Replace them
  with empty **stub** files of the right names (`gsutil ls …/games/'worker_*.pkl' | sed
  's#.*/##' | while read n; do : > games/$n; done` — lists object names with no content
  transfer), which satisfies the count without the bytes. Safe because `snapshot-keep` thins
  *chunk rows*, not pickles, so nothing on the train path ever opens a stub. Before stubbing any
  "only-counted" input, confirm against the code that no path actually loads it — the value of
  the trick depends entirely on that read-vs-count distinction.

### The Python/torch path (training, encoding, eval) — NOT just the C++ binary

The "build/run recipe" above is for the **C++ `selfplay` binary**, which is torch-free and needs
only `build-essential cmake python3-pybind11`. But **training, dataset-encoding, and any eval that
uses a leaf/encoder with no C++ port** (e.g. a candidate encoder under evaluation) run the **Python
+ torch** path, which has its own setup pitfalls the C++ recipe never hits:

- **A fresh Debian-12 box may not have `pip`.** `python3 -m pip` fails with `No module named pip`.
  Run `sudo apt-get install -y python3-pip` first. (A box that has had a *prior* run can already
  have it from that run — which masks the missing step; see the fresh-box warning below.)
- **Debian 12 is PEP-668 "externally managed" — `pip install` refuses system-wide.** You get
  `error: externally-managed-environment`. For a throwaway box use `pip install
  --break-system-packages numpy torch`; for a reusable image, a venv. The ARM CPU torch wheel
  (~200 MB) installs fine on T2A.
- **A refused/failed dep install fails *silently* without `set -e`.** With `set -uo pipefail` but
  no `set -e`, a `pip install` that errors does **not** stop the script — it marches into training,
  which then dies on `import numpy`, and the traceback *looks like a code bug, not a setup bug*.
  **Guard deps explicitly**: `pip install --break-system-packages numpy torch || { echo FATAL; exit 1; }`
  then `python3 -c "import torch,numpy" || exit 1`. Same for the data download — count the files and
  abort if short — so the box never "succeeds" into garbage.
- **A box that has had a prior run is contaminated — test the clean script on a FRESH box.** One run
  appeared to work only because an *earlier failed* run on the same box had already `apt install`ed
  `python3-pip`; the streamlined script that dropped the explicit install then failed on the next
  *fresh* box. Leftover apt/pip state hides missing setup steps. Validate the end-to-end script on a
  brand-new instance, not the one you've been poking at.
- **Size from a *measured* throughput — measured with the SAME thread config you'll deploy.**
  Python-MCTS self-play/eval is much slower than the C++ binary. But the per-game time depends
  heavily on torch threads: a quick M1 timing with *multi-thread* torch read ~95 s/game at 800 sims,
  yet the production box runs `OMP_NUM_THREADS=1` (one thread per worker, see above), where each game
  is ~**366 s/game/core** on T2A — ~4× slower per game (more games run in parallel, but per-game time
  is what determines exposure). Sizing from the 95 s figure under-estimated a 1000-game matchup as
  ~33 min when it actually takes ~2 h. **Time a couple of games with `OMP_NUM_THREADS=1` set**, the
  way the real run will execute, not in a bare interactive shell.
- **A ~2 h Spot matchup *will* get preempted — keep games few and uploads incremental.** Two 48-core
  Spot eval boxes were both preempted mid-run (~70-90% done) precisely because each matchup sat in
  the preemption window for ~2 h. Mitigations that worked / would have: upload a partial result every
  ~30 s (the partials were the only reason the data survived); prefer a **smaller game count** (700
  games already gives a ±3-4% CI — 1000 buys little and doubles the exposure); or, for a *single*
  must-finish long matchup, fall back to **on-demand** (≈$3.60 for 2 h vs Spot's ~$1.16, but it can't
  be reclaimed). Resume-by-seed isn't supported by `play_mcts_match`, so a preempt restarts from
  seed 0 — which is why short+incremental beats long+all-or-nothing on Spot.
- **Pin OMP threads to 1 for any multiprocessing-`Pool` torch job, or it self-thrashes to a halt.**
  A torch process defaults its intra-op thread pool to the *core count*. So a `Pool(processes=nproc)`
  job where each worker also uses torch spawns **nproc × nproc** threads — on a 48-core box that's
  ~2300 threads, **load average ~500–600, and ~0 games completed** (it looks "hung," but it's
  oversubscription thrash). The data-gen scripts already call `torch.set_num_threads(1)` per worker,
  but **`play_mcts_match.py` does not** — and any ad-hoc Pool job won't either. Fix from the
  environment so it covers every worker regardless: `export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
  OPENBLAS_NUM_THREADS=1` before launching (set it before the parent imports torch). The tell is
  `ps -eo nlwp,comm` showing each `python3` at `NLWP=48` instead of `1`, and a load average many ×
  the core count.
- **`OMP_NUM_THREADS=1` makes `nproc` return 1 — use `nproc --all` for the core count.** GNU
  coreutils `nproc` *honors* `OMP_NUM_THREADS`/`OMP_THREAD_LIMIT`, so the moment you `export
  OMP_NUM_THREADS=1` (above), a `--jobs $(nproc)` becomes `--jobs 1` — the Pool runs a single worker
  and the whole job goes sequential (one game at a time, an ETA of *days*), which looks like "slow"
  rather than "misconfigured." These two fixes collide: pinning OMP threads silently zeroes your
  parallelism. Compute the job/worker count with **`nproc --all`** (it ignores `OMP_NUM_THREADS` and
  returns the installed CPU count) whenever you also pin OMP. The tell: the launched command shows
  `--jobs 1` and only one `python3` worker exists.

### Launching boxes & driving them over SSH

- **`gcloud ssh`/`scp` right after `instances create` races sshd coming up.** The first call often
  returns `255` / "Connection closed" while the box is still booting (and the first SSH also has to
  generate your key). Retry with backoff (3–4 tries, ~10 s apart). `scp` succeeding while `ssh`
  fails (or vice-versa) on the same box is just it still settling — **not** a dead box. Confirm the
  box is actually healthy with `gcloud compute instances get-serial-port-output NAME --zone=Z`
  before deeper debugging.
- **Never `pkill -f <scriptname>` inside a command you run over SSH.** `pkill -f` matches the *full
  command line*, and the remote shell executing your `--command` contains that script name in its
  argv — so `pkill -f job.sh` kills its own session and `ssh` returns `255`. This masquerades as
  "flaky SSH" and sends you debugging the wrong thing. Kill by pid, or by a pattern that can't match
  your own command.
- **GCE instance names must match `[a-z]([-a-z0-9]*[a-z0-9])?`** — lowercase only, no uppercase, no
  trailing dash. `agricola-evalA` is rejected; use `agricola-eval-a`.
- **Spot capacity is per-(zone, machine-type) and stocks out independently of quota.** `instances
  create` can return `STOCKOUT` for a size in one zone while another has it free (the error names
  `zonesAvailable`). **Loop over several zones at create time** rather than failing on the first.
- **The Spot vCPU quota (`PREEMPTIBLE_CPUS`) caps your *concurrent* cores.** With a 96-core Spot cap
  you cannot run 3×48-core Spot boxes at once (144 > 96) — plan the fleet against it. Check:
  `gcloud compute regions describe us-central1 --format="value(quotas)" | tr ';' '\n' | grep PREEMPTIBLE_CPUS`.
  (On-demand has a separate, usually larger `CPUS` cap, so a one-off can spill to on-demand.)
- **Launch detached jobs with stdin redirected from `/dev/null`:**
  `nohup setsid bash job.sh ARGS > ~/job.out 2>&1 < /dev/null &`. The script's stdout still reaches
  both `~/job.out` and (via `exec > >(sudo tee /var/log/job.log)`) the root log, so you can `tail`
  progress without `sudo`.
