# Live Tesserae

A collaborative mosaic where anyone can contribute pixel art. The grid is 1000 x 1000 tiles and each tile is a 32 x 32 pixel canvas — **1 million tiles, just over a billion pixels**. At full resolution the mosaic is a 32,000 x 32,000 image. All changes sync in real time.

No accounts, no signup — just draw. Live at **[tesserae.live](https://tesserae.live)**.

## Architecture

Everything runs as three containers on a single VM. Caddy is the only process bound to the public internet; the app and the database have no published ports.

```mermaid
flowchart LR
    B["Browser<br/>canvas renderer · pixel editor · WS client"]
    subgraph box ["one Lightsail VM (us-east-2), docker compose"]
        C["Caddy :80 :443<br/>TLS · reverse proxy"]
        A["FastAPI + uvicorn<br/>:8000"]
        S["built frontend<br/>(static files)"]
        P[("PostgreSQL 16<br/>tile pixel bytes")]
        V[("chunk images<br/>WebP on a volume")]
    end
    B -->|HTTPS / WSS| C
    C -->|"/api/*, /health, /ws"| A
    C -->|everything else| S
    A -->|asyncpg pool| P
    A -->|read / write| V
```

| Layer | Tech |
|-------|------|
| Frontend | React 19, TypeScript, Vite, HTML5 Canvas (Bun toolchain) |
| Backend | FastAPI, uvicorn, asyncpg, Pillow |
| Database | PostgreSQL 16 — tile pixels stored as raw RGB in a `BYTEA` column |
| Image storage | WebP files on a Docker volume (an S3 backend exists but is unused) |
| Real-time | WebSocket, chunk-scoped pub/sub with 50 ms message batching |
| Hosting | One AWS Lightsail VM (2 vCPU / 2 GB), Caddy + app + Postgres under `docker compose` |
| TLS / DNS | Let's Encrypt issued automatically by Caddy; DNS at Namecheap |

There is **no load balancer, CDN, managed database, or second instance — deliberately**. The WebSocket registry, the render permit, the rate limiter and the image version tracking all live in process memory, so the app must run as exactly one instance. An earlier ECS Fargate + ALB + RDS + NAT + CloudFront deployment cost roughly 7x more per month to provide horizontal scaling this design cannot use.

## Getting Started

### Prerequisites

- [Bun](https://bun.sh/) (frontend)
- Python 3.12 (backend — production is 3.12, and 3.13 changed asyncio behaviour this code depends on)
- Docker (local PostgreSQL)

### 1. Start the database

```bash
docker compose up -d
```

### 2. Start the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt -r requirements-test.txt
cp .env.example .env        # defaults work for local dev
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`. The database schema is created automatically on startup.

### 3. Start the frontend

```bash
cd frontend
bun install
cp .env.example .env        # points to localhost:8000
bun run dev
```

The app runs at `http://localhost:5173`.

### Tests

```bash
cd backend
python -m pytest tests/unit -q          # fast, no external deps
python -m pytest tests/integration -q   # needs Postgres + a tesserae_test database
```

The integration suite needs its own database, which nothing creates for you:

```bash
docker compose exec postgres createdb -U tesserae tesserae_test
```

Run only one integration session at a time — an autouse fixture truncates the tables before every test.

The frontend has no test framework yet; `bun run build` runs the TypeScript check.

## How It Works

**Tile storage is sparse.** A tile with no row is default white and costs nothing. Pixel data is raw RGB — exactly **3072 bytes** (32 x 32 x 3, row-major) — stored in a `BYTEA` column and sent to the browser unchanged. There is no image encoding or decoding anywhere on the write path. That byte count is a contract enforced on both sides.

**Three render levels** keep the mosaic navigable at any zoom. The client picks a level from how many screen pixels one tile currently occupies:

| Level | Engages at | What loads | Detail |
|-------|-----------|------------|--------|
| 0 | below 3 px/tile | one 2000 x 2000 WebP, ~515 KB | 2 px per tile |
| 1 | 3–24 px/tile | 100 chunk WebPs (10 x 10 grid), ~18 MB total | 20 px per tile |
| 2 | 24 px/tile and up | individual tiles as raw RGB from Postgres | full 32 x 32 |

So the zoomed-out view of a billion pixels is a single half-megabyte image.

Both preview sizes must divide their grid exactly (2000 / 100 tiles = 20 px, 2000 / 10 chunks = 200 px). Every tile is resampled and pasted individually, so a fractional stride gives neighbouring tiles different cell sizes and shifts anything continuous across a tile edge by half a pixel — which draws a visible line on every tile boundary. For the same reason the pyramid downscales with a box filter rather than a windowed sinc: Lanczos overshoot gets clamped at the tile border instead of continuing into the neighbour, painting a grid over the artwork.

**Saving a tile** is fast because almost nothing happens synchronously:

1. In one transaction, the 3072 bytes are upserted and the chunk's version is bumped. The request returns in ~37 ms.
2. The new pixels are broadcast immediately over WebSocket, inline as base64 — no follow-up fetch. The client also paints its own save straight into its canvas cache, so artwork never depends on the echo arriving.
3. In the background, only that chunk's Level 1 image is re-rendered, and the chunk is flagged dirty.
4. On a separate timer, the Level 0 overview is rebuilt at most once every 5 seconds, folding in every chunk that went dirty in that window.

Step 4 is the reason this is quick. The overview used to be re-encoded inside every save, costing 1726 ms and capping the whole site at ~0.5 saves/sec — invisible to the person drawing, whose request still returned in 20 ms, but everyone else fell tens of seconds behind. Coalescing makes the cost of the overview independent of the edit rate.

**Every image render in the process is serialised behind one semaphore**, both to bound memory (a 2000 x 2000 RGB buffer is ~12 MB and a render holds several) and because read → composite → save must not interleave, or one writer silently drops another's tile. The rules around that permit are load-bearing and documented in `chunk_renderer.py` and `CLAUDE.md`.

**Real-time updates** use chunk-scoped subscriptions: a client subscribes only to the chunks it can see, capped at the 50 nearest the viewport centre, and the server keeps a reverse index so a broadcast is an O(1) lookup. Updates to the same chunk within 50 ms are batched into a single message.

## Performance

Measured on the live box — 8 concurrent WebSocket clients all subscribed to the same 9 chunks, writers on two source IPs, ~50 s:

| | |
|---|---|
| Saves | 469 total, 0 errors, 0 rate-limited |
| Delivery | 319/319 saves reached all 8 clients |
| Save latency | p50 **37 ms**, p95 58 ms, p99 74 ms |
| Broadcast latency | p50 **88 ms**, p95 112 ms, max 186 ms |
| App container | ~100% of one core (of two), 157 MB of its 1 GB limit |

CPU is the constraint, not memory; the practical write ceiling is roughly **12 saves/sec**. Configured limits are 1000 concurrent WebSocket connections (100 per IP), 50 chunk subscriptions per connection, and 10 tile saves/sec per IP.

Past the write ceiling the failure mode is not an outage. Saves keep succeeding and Levels 1 and 2 stay current — the render queue backs up, so the zoomed-out overview goes stale, rebuilding roughly every 30 s instead of the nominal 5 while heavy editing is happening.

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI entry point, lifespan, health check
│   │   ├── api/               # REST routes: tiles, chunks, mosaic stats
│   │   ├── services/          # tiles, chunk_renderer, overview, storage, database
│   │   └── websocket/         # connection manager, chunk subscriptions, batching
│   ├── scripts/               # render_chunks.py, init_mosaic.py, map generators
│   ├── tests/                 # unit (mocked) and integration (real Postgres)
│   ├── deploy.sh              # ssh → git pull → docker build → restart app
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/             # LandingPage, MosaicEditor
│   │   ├── components/        # MosaicCanvas, TileEditorPanel, MiniMap, etc.
│   │   ├── hooks/             # useWebSocket, useViewport, useOverviewImage
│   │   ├── api/               # API client functions
│   │   └── utils/             # pixels, chunks, tileLoader, lruCache
│   └── deploy.sh              # bun build → rsync to the box
├── docker-compose.yml         # local PostgreSQL only
└── LICENSE
```

## Deployment

Two scripts, both reading config from gitignored `.env.deploy` files (see `.env.deploy.example` in each directory):

```bash
cd backend && ./deploy.sh     # ssh → git pull on the box → docker build → compose up -d app
cd frontend && ./deploy.sh    # bun build → rsync --delete → the Caddy webroot
```

`backend/deploy.sh` pulls `origin/main` **on the box**, so commit and push first. It replaces the app container rather than running two — a few seconds of deliberate downtime, because two app containers could not see each other's WebSocket clients and would clobber each other's image writes.

`frontend/deploy.sh` refuses to build when `VITE_API_BASE_URL` is missing, localhost, or non-HTTPS, and greps the built bundle afterwards to prove the value landed. Its `rsync --delete` means `DEPLOY_PATH` must be the Caddy webroot and nothing else.

Things worth knowing before changing the deployment:

- **`TRUSTED_PROXY_HOPS` must be 1 in production** (Caddy is the only proxy). The app reads `X-Forwarded-For` from the right, since only the rightmost entries are appended by infrastructure you control. At 0 behind a proxy, every request carries Caddy's IP and all per-IP limits silently become site-wide.
- **Run `scripts/render_chunks.py` after any restore and before opening traffic.** A chunk with no image is absent from Level 0 until something builds it, and on a cold store every render serialises behind the single permit.
- **Chunk images are derived data and are never backed up** — the nightly `pg_dump` covers the database, and all 100 chunks rebuild in ~90 s.

Full operational detail lives in `.cursor/plans/infrastructure.md` (steady state, request flow, backups, troubleshooting) and `.cursor/plans/deployment.md` (how the box was built, and the traps hit along the way).

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://tesserae:tesserae_local@localhost:5433/tesserae` |
| `TRUSTED_PROXY_HOPS` | Reverse proxies you control in front of the app. 0 for local dev, 1 behind Caddy | `0` |
| `STORAGE_MODE` | `local` or `s3` | `local` |
| `CHUNKS_PATH` | Where chunk images are written in local mode | `storage/chunks` |
| `OVERVIEW_COALESCE_SECONDS` | How long an overview rebuild waits to collect dirty chunks | `5` |
| `CORS_ORIGINS` | Allowed frontend origins (unused in production — the API is same-origin) | `http://localhost:5173` |
| `AWS_S3_BUCKET` | Bucket for images when `STORAGE_MODE=s3` | — |

### Frontend (`frontend/.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_BASE_URL` | Backend API URL, baked into the bundle at build time | `http://localhost:8000` |
| `VITE_CDN_BASE_URL` | Optional separate origin for chunk images. Unset in production | — |

## License

[MIT](LICENSE)
