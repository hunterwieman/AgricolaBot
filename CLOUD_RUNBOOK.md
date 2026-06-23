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
guesses. Disk and same-region storage/egress are negligible. **Spot** (interruptible)
machines would be ~3× cheaper but are **not approved yet** — Google auto-blocks them on
new accounts; re-request once the account has more history.

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

# 1. Create the VM. --scopes=cloud-platform lets it clean up / write to storage itself.
gcloud compute instances create $NAME --zone=$ZONE \
  --machine-type=t2a-standard-8 \
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

**Layer 2 — a hard time limit (the real backstop).** Even a self-deleting script fails
to delete if it hangs forever. This flag makes Google delete the VM after a set time no
matter what the code is doing — so a stuck job can never bill indefinitely:

```sh
gcloud compute instances create $NAME --zone=$ZONE \
  --machine-type=t2a-standard-8 \
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
