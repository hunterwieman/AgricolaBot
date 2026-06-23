# Deploying the AgricolaBot web UI to Fly.io

A beginner-friendly, step-by-step guide to running the browser game on
[Fly.io](https://fly.io) as a single always-on container. No prior deployment
experience assumed. The live deployment is at <https://agricolabot.fly.dev/>.

The repo already contains everything you need:

- **`deploy.sh`** — the one command you run to ship. It figures out which AI
  model the image should bake in, then calls `fly deploy` for you (details in
  step 4).
- **`Dockerfile`** — builds the image: compiles the C++ AI binary for Linux,
  then installs the stdlib Python server (only extra dep is `numpy`). It copies
  in the current champion model via an `EXPORT_DIR` build argument that
  `deploy.sh` fills in.
- **`.dockerignore`** — keeps the upload small (skips tests, data, docs, etc.),
  while re-including every `cpp_export_*` model export so whichever champion is
  selected is available to the build.
- **`fly.toml`** — the Fly app config (always-on, 2 shared CPUs, 1 GB RAM).

You run the commands below from the repo root
(`.../Agricola/AgricolaBot`).

---

## 1. Install the Fly CLI (`flyctl`)

`flyctl` (also invokable as `fly`) is the command-line tool that talks to Fly.io.

**macOS / Linux:**

```sh
curl -L https://fly.io/install.sh | sh
```

After it installs, it prints a line about adding `flyctl` to your `PATH`. Either
follow that instruction or open a new terminal, then confirm:

```sh
fly version
```

(On macOS you can also `brew install flyctl`.)

---

## 2. Create a Fly account and log in

If you don't have an account yet:

```sh
fly auth signup
```

This opens your browser to finish signup. Fly requires a credit card on file
even for small apps (it's pay-as-you-go). If you already have an account:

```sh
fly auth login
```

---

## 3. Create the app on Fly (without deploying yet)

This registers the app with Fly and reuses the existing `fly.toml` instead of
generating a new one. Run it from the repo root:

```sh
fly launch --no-deploy
```

When prompted:

- **App name** — must be globally unique. If `agricolabot` is taken, pick
  another (e.g. `agricolabot-yourname`). The name you choose is updated in
  `fly.toml`.
- **Region** — pick one near you (see step 6 to change it later).
- **"Would you like to tweak these settings?"** — answer **No**; the committed
  `fly.toml` already has the right CPU/memory/always-on settings.
- If it asks about a Postgres database / Redis / etc., say **No** — this app
  has no database (game state is in memory).

`--no-deploy` means it only *creates* the app; it does not build or ship yet.

---

## 4. Deploy

```sh
./deploy.sh
```

`deploy.sh` is a small wrapper around `fly deploy`. The reason it exists: the
image needs to bake in the trained AI model, and we point at "the current
champion" through a symlink, `nn_models/cpp_export_best`. Docker's `COPY` can't
follow a symlink, so the script resolves the symlink to the concrete directory
it points at and passes that real directory name to the `Dockerfile` as an
`EXPORT_DIR` build argument. You don't have to think about any of that — just run
`./deploy.sh`.

It uploads the build context, builds the Docker image on Fly's builders
(compiling the C++ binary inside the image), and starts one machine. The first
deploy takes a few minutes (the C++ compile is the slow part). When it finishes,
open the app:

```sh
fly open
```

…or visit `https://<your-app-name>.fly.dev`.

Any extra arguments you give `deploy.sh` are passed straight through to
`fly deploy`. For example, to deploy immediately without the usual
release-confirmation step:

```sh
./deploy.sh --now
```

Every time you change the code, re-run `./deploy.sh` to ship the update.

### Shipping a new AI model

When a stronger model is trained, "promoting" it to the live site is two steps:
repoint the champion symlink, then deploy.

```sh
ln -sfn <cpp_export_dir> nn_models/cpp_export_best
./deploy.sh
```

`<cpp_export_dir>` is the C++ export directory of the new model (under
`nn_models/`). Because `deploy.sh` resolves the symlink for you and
`.dockerignore` already re-includes every `cpp_export_*` directory, you **don't**
need to touch the `Dockerfile` or `.dockerignore` to ship a different champion —
the symlink is the only thing that decides which weights get baked into the
image.

The model that's live today is the joint value+policy champion
`joint_outcome_44k`, run at the MCTS leaf in **MIX mode at α = 0.9** — its value
estimate is a blend of 90% from a points-margin head and 10% from a win/loss
"outcome" head.

---

## 5. View logs

To watch the server output (useful if the page won't load):

```sh
fly logs
```

You should see a `Serving at ...` line once the server is up. Other handy
checks:

```sh
fly status          # is the machine running?
fly apps open       # open the URL in your browser
```

---

## 6. Set / change the region

The region is the `primary_region` field in `fly.toml`. List available regions:

```sh
fly platform regions
```

Pick the 3-letter code closest to you (e.g. `ord` = Chicago, `sjc` = San Jose,
`lhr` = London), set it in `fly.toml`, then redeploy:

```sh
./deploy.sh
```

---

## 7. Rough cost

Ballpark **~$5–7 / month** for one always-on `shared-cpu-2x` machine with 1 GB
RAM, running 24/7. This is an estimate only — **confirm current pricing on
Fly's pricing page** (<https://fly.io/docs/about/pricing/>), since rates and any
free allowances change. To keep costs down you could scale the machine down to
`shared-cpu-1x` / 512 MB in `fly.toml`, at the risk of slower AI moves.

You can check your usage and bill anytime in the Fly dashboard
(<https://fly.io/dashboard>).

---

## A note on the "Show analysis" overlay

The game has a **Show analysis** toggle that overlays, on each of your possible
moves, what the bot thinks of it — a small badge showing the move's value and how
many search visits it got. The badge labels the value with its natural unit, so
you can read it directly:

- **`margin +1.2 · 80`** — the bot expects to come out about 1.2 points of
  final-score margin ahead from this move (the `· 80` is the visit count).
- **`outcome +0.31 · 80`** — a win-value on a [−1, 1] scale (−1 = certain loss,
  +1 = certain win).
- **`mix +0.34 · 80`** — the raw, unitless blend of the margin and outcome
  signals that the live MIX-leaf bot actually searches with. Unlike the other
  two, this number is **not** converted back into points; it's the internal
  blended score as-is.

Which label appears depends on the model: the C++ analysis path reports a small
`value_target` descriptor that tells the page the unit, so the overlay always
matches whatever leaf the live bot is using. Today's `joint_outcome_44k` MIX-leaf
bot shows the **`mix`** badge.

---

## A note on in-progress games

Game state lives **in the server's memory**, not in a database. That means:

- **Restarting or redeploying the app drops every in-progress game.** This is
  expected for now. Anyone mid-game would need to start a new one after a
  redeploy.
- The `fly.toml` is configured to keep exactly **one machine always on**
  (`min_machines_running = 1`, `auto_stop_machines = false`) so the app doesn't
  scale to zero and silently lose games between requests.

If persistent games ever become a requirement, that would need a real
datastore — out of scope for this single-container setup.
