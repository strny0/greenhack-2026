# Docker / deployment

A single image runs all of Grid Pulse: one `uvicorn` process serves both the
API (`/api/*`) and the built frontend (`/`). The image is **lean** — it contains
only the backend + dependencies, the built React/Vite frontend, and the small,
version-controlled operator overrides.

The two heavy bits are prepared **once at first container start** (by
`entrypoint.sh`) into **mounted volumes**, so they persist across restarts and
image updates and are never re-fetched:

- the **ČEPS dataset** (~GBs) → downloaded into the `gridpulse-data` volume,
- the **gridstats bundle** (`python -m app.gridstats.build`) → built into the
  `gridpulse-gridstats` volume.

So the **first** `up` downloads the dataset and builds the bundle (several
minutes — the container shows `health: starting` meanwhile); **every start
after that is fast**, and pulling a newer `:latest` does **not** re-download the
dataset. To use an external dataset instead, mount it and set `GRID_DATA_DIR`
(see [Overriding the dataset](#overriding-the-dataset)).

---

## Run it

### A) Pull the prebuilt image from GHCR (no build)

```bash
docker compose -f docker/docker-compose.ghcr.yml up -d
# then open http://localhost:8099
```

Pulls `ghcr.io/strny0/greenhack-2026:latest` (published by CI on every merge to
`main`). Requires the package to be public, or `docker login ghcr.io` first.
The first run populates the dataset + bundle volumes (several minutes); after
that, `up -d` is instant even after a new image is pulled.

### B) Build locally from the repo

```bash
docker compose -f docker/docker-compose.build.yml up --build
# then open http://localhost:8099
```

The image build itself is quick (just deps + frontend); the dataset download
and bundle build happen at first container start, into the volumes.

### Plain `docker build` (no compose)

```bash
docker build -f docker/Dockerfile -t gridpulse .      # context = repo root
docker run -p 8099:8099 \
  -v gridpulse-data:/data/dataset \
  -v gridpulse-gridstats:/data/gridstats \
  -v gridpulse-traces:/data/traces \
  gridpulse
```

---

## Configuration

Every setting is an environment variable with a default, passed via the compose
`environment:` block. The entrypoint writes them into `/app/backend/.env` at
startup (mirroring [`../src/backend/.env.example`](../src/backend/.env.example))
and `app.config` also reads them directly — so **any** `GRID_*` / `AI_*` knob
from [`app/config.py`](../src/backend/app/config.py) works even if it isn't
listed in the compose file.

Common ones:

| Variable | Default | Purpose |
|---|---|---|
| `AI_API_KEY` | _(empty)_ | OpenAI-compatible key for the dispatcher chatbot. Empty ⇒ chat returns only the grounded context. |
| `AI_BASE_URL` | `https://openrouter.ai/api/v1` | Chat endpoint. |
| `AI_MODEL` | `anthropic/claude-sonnet-4.5` | Chat model id. |
| `GRID_ADMIN_TOKEN` | _(empty)_ | Secret for `GET /api/admin/traces`. Empty ⇒ that endpoint is disabled. |
| `PORT` | `8099` | In-container listen port. |
| `GRID_PRELOAD_FRAMES` | `48` | Frames solved at startup (warmup). |
| `DATASET_URL` | _(public ČEPS link)_ | Where the entrypoint downloads the dataset from. |
| `GRID_DATA_DIR` | `/data/dataset/data` | Dataset payload location (the `gridpulse-data` volume). |
| `GRIDSTATS_TARGET_DIR` | `/data/gridstats/target` | gridstats bundle location (the `gridpulse-gridstats` volume). |
| `GRIDSTATS_BUILD_WORKERS` | _(auto)_ | Worker processes for the one-time bundle build. Auto = CPUs−1 capped at 8, and honours a container `--cpus`/cpuset limit. Set e.g. `2` to cap it on a small host. |
| `GRID_CHAT_TRACE_FILE` | `/data/traces/chat_traces.jsonl` | Usage-trace log path (the `gridpulse-traces` volume). |

### Volumes

| Volume | Mount | Holds |
|---|---|---|
| `gridpulse-data` | `/data/dataset` | downloaded dataset payload (`data/…`) |
| `gridpulse-gridstats` | `/data/gridstats` | precomputed bundle (`target/…`) |
| `gridpulse-traces` | `/data/traces` | `chat_traces.jsonl` |

Wipe one to force a re-fetch/rebuild, e.g. `docker volume rm gridpulse-gridstats`
(it rebuilds on next start). `docker compose down -v` removes all three.

### Chat usage traces — access & persistence

- **Persistence:** traces are written to `/data/traces/chat_traces.jsonl` on the
  `gridpulse-traces` volume, so they survive restarts and image updates. Disable
  with `GRID_CHAT_TRACING=0`.
- **Access:** set `GRID_ADMIN_TOKEN` and read
  `GET /api/admin/traces?token=<token>` (or the `X-Admin-Token` header). Without
  the token the endpoint returns 404.

### Overriding the dataset

To point at an existing dataset on the host instead of downloading, bind-mount it
over the data volume's path — the entrypoint sees the snapshots and skips the
download:

```yaml
services:
  gridpulse:
    volumes:
      - /host/path/to/dataset:/data/dataset:ro   # must contain data/snapshots/…
```

`GRID_OVERRIDES_DIR` is independent and stays baked into the image, so only the
large payload needs mounting.

### Health & restart

The image has a `HEALTHCHECK` hitting `/api/health`; compose sets
`restart: unless-stopped`. `docker ps` shows `healthy` once the app is up. The
**first** start stays `health: starting` for several minutes while the dataset
downloads and the bundle builds (covered by a 10-min `--start-period`); later
starts go healthy within ~1–2 min.

---

## GitHub setup (one-time, for CI → GHCR)

The workflow [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml)
builds and pushes `ghcr.io/<owner>/<repo>:latest` on every push to `main` (and
via **Run workflow**). It authenticates with the automatic `GITHUB_TOKEN` — **no
secrets to create**. To make it work end-to-end:

1. **Allow Actions to write packages.**
   Repo → **Settings → Actions → General → Workflow permissions** →
   **Read and write permissions** → Save. (The workflow also declares
   `permissions: packages: write`, which is sufficient on most repos; this
   setting avoids edge cases.)

2. **Trigger the first build.**
   Merge to `main`, or run it manually: **Actions → Publish Docker image → Run
   workflow**. First run takes a while (downloads the dataset, builds the
   bundle, pushes a multi-GB image).

3. **Make the package public** (so `docker-compose.ghcr.yml` can pull without
   auth). After the first successful run a **greenhack-2026** package appears at
   `https://github.com/users/strny0/packages/container/package/greenhack-2026`
   → **Package settings → Danger Zone → Change visibility → Public**.
   _Private instead?_ consumers must `echo $PAT | docker login ghcr.io -u <user> --password-stdin`
   with a PAT that has `read:packages`.

4. **Link the package to the repo** (enables the auto-prune step and shows the
   package on the repo page): **Package settings → Connect repository →** select
   this repo. The `prune` job then deletes orphaned untagged layers via
   `GITHUB_TOKEN`, keeping only `:latest`.

That's it — afterwards every merge to `main` republishes `:latest`, and
`docker compose -f docker/docker-compose.ghcr.yml up -d` always pulls the newest.

### Notes

- CI builds are fast and the image is lean: the dataset is **not** baked in
  (it's downloaded at first container start into a volume), so the workflow only
  installs deps and builds the frontend — and those layers are reused between
  runs via the GitHub Actions build cache, so an unchanged `requirements.txt` /
  lockfile skips the slow `pip`/`npm` steps entirely.
- `DATASET_URL` is a runtime env var (with a public-link default), set per
  deployment via compose. If it ever becomes private, pass it through the compose
  `environment:` (e.g. from a host env var or secret) — no image rebuild needed.
