# Deploying the AgricolaBot web UI to Fly.io

A beginner-friendly, step-by-step guide to running the browser game on
[Fly.io](https://fly.io) as a single always-on container. No prior deployment
experience assumed.

The repo already contains everything you need:

- **`Dockerfile`** — builds the image: compiles the C++ AI binary for Linux,
  then installs the stdlib Python server (only extra dep is `numpy`).
- **`.dockerignore`** — keeps the upload small (skips tests, data, docs, etc.).
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
fly deploy
```

This uploads the build context, builds the Docker image on Fly's builders
(compiling the C++ binary inside the image), and starts one machine. The first
deploy takes a few minutes (the C++ compile is the slow part). When it finishes,
open the app:

```sh
fly open
```

…or visit `https://<your-app-name>.fly.dev`.

Every time you change the code, re-run `fly deploy` to ship the update.

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
fly deploy
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
