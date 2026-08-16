# CLAUDE.md

Live Tesserae — a collaborative pixel-art mosaic: 1000×1000 grid of 32×32 tiles, real-time sync, no accounts. FastAPI + PostgreSQL backend, React 19 + Vite frontend (Bun), deployed on AWS (ECS Fargate, S3, CloudFront).

## Commands

### Backend (`backend/`, Python 3.12, venv at `backend/venv`)
```bash
docker compose up -d                  # local Postgres on :5433 (from repo root)
uvicorn app.main:app --reload         # API on :8000; schema auto-created on startup
python -m pytest tests/unit -q        # fast, no external deps (~5s)
python -m pytest tests/integration -q # requires Postgres + tesserae_test DB (see below)
black app tests scripts               # formatting
```
Integration tests need a separate test database. No code creates it — `conftest` only creates the *schema*, so without this every integration test errors at setup with `InvalidCatalogNameError`:
```bash
docker compose exec postgres createdb -U tesserae tesserae_test
```

**Check your interpreter before trusting a green suite.** Production is Python 3.12 (`Dockerfile: python:3.12-slim`, `.python-version: 3.12.8`); a local venv may well be a newer Python, and 3.13+ changed relevant asyncio behaviour (`Semaphore.locked()` counts waiters; `create_task` accepts what `shield()` returns). To run the suite on the real production interpreter without installing anything:
```bash
docker run --rm -v "$PWD/backend":/app -w /app -e TEST_DATABASE_URL="postgresql://tesserae:tesserae_local@host.docker.internal:5433/tesserae_test" python:3.12-slim bash -c "pip install -q -r requirements.txt -r requirements-test.txt && python -m pytest tests -q"
```

**Run only one integration session at a time.** The autouse `clean_db` fixture `TRUNCATE`s the tables before *every* test, so two concurrent runs against `tesserae_test` silently corrupt each other and produce phantom failures.

### Frontend (`frontend/`, Bun)
```bash
bun install
bun run dev            # :5173
bun run build          # tsc -b && vite build — this is the typecheck; run it before considering work done
bun run lint           # eslint
bun run format         # prettier
```
There is no frontend test framework yet. If adding tests, use Vitest; start with the pure utils (`src/utils/`).

### Deploy (requires `.env.deploy`, never committed)
```bash
cd backend && ./deploy.sh              # Docker buildx → ECR → force ECS redeploy
cd backend && ./register-task-def.sh   # only when the task definition changes
cd frontend && ./deploy.sh             # bun build → S3 sync → CloudFront invalidation
backend/pause.sh | resume.sh           # scale ECS to 0 / stop-start RDS (cost saving)
```
Both deploy scripts `set -a` before sourcing `.env.deploy` — plain `source` sets shell variables that never reach a subprocess, which is why the built bundle used to point at `http://localhost:8000`. `frontend/deploy.sh` refuses to build when `VITE_API_BASE_URL` is missing, localhost, or non-https (override the last with `ALLOW_INSECURE_API_URL=1`), and greps the built bundle afterwards to prove the value landed.

`task-def.json` is a **template**, not a registerable document: `${...}` placeholders are filled by `register-task-def.sh`, and `DATABASE_URL` comes from Secrets Manager via `secrets`/`valueFrom`, never `environment`. `tests/unit/test_task_definition.py` fails the build if a describe-dump field, an inline credential, or a missing `TRUSTED_PROXY_HOPS` reappears. `backend/deploy.sh` passes `minimumHealthyPercent=0,maximumPercent=100` so a rollout never runs two tasks at once.

**AWS status (as of Aug 2026): the original AWS account (199264265773) is permanently closed** — every identifier in `backend/task-def.json` and both `.env.deploy.example` flows (ECR repo, RDS endpoint, S3 buckets, CloudFront distributions, IAM roles) is defunct. A redeploy to a fresh account is planned for mid-Aug 2026. `.cursor/plans/aws-deployment.md` is the from-scratch setup guide (account → S3 → RDS → CloudFront → storage config); `step12a/b` plans cover frontend/backend deployment. When redeploying: new account ID, new RDS password **via Secrets Manager, not task-def environment**, new bucket/distribution names, fresh `.env.deploy` files.

## Plans & project docs

- **Implementation plans live in `.cursor/plans/`** (gitignored, local only). When asked to plan a feature, write the plan as a markdown file there; move finished plans to `.cursor/plans/archive/`. Follow the house style of the existing plans: goal, current state, phased steps with file paths, effort estimates.
- Existing plans are the project's design history and still-relevant backlog: `aws-deployment.md` (AWS from-scratch guide — the weekend redeploy playbook), `mobile-support.md` (touch pan/pinch for MosaicCanvas, phased), `production-hardening.md` + `hardening-tests.md` (mostly implemented), `IMPLEMENTATION_ORDER.md` / `OVERVIEW.md` (original roadmap; its progress tracker is stale).
- `.cursor/rules/*.mdc` are legacy Cursor rules. Their conventions are folded into this file; treat the rules themselves as historical. Known-stale claims in them: tiles are **not** stored as PNG files (they're raw RGB `BYTEA` in Postgres), WS `tile_update` carries base64 RGB bytes (not a `data:image/png` URL), there is no Lambda chunk renderer, and the S3 layout is flat `{cx}_{cy}.webp` keys (no `tiles/`/`level*/` prefixes).

## Architecture

**Data flow for a tile save** (`PUT /api/tiles/{x}/{y}`):
1. Raw 3072-byte RGB body → validated → upserted into Postgres (`tiles` table) in a transaction with a `chunks` row bump
2. `tile_update` broadcast immediately to WebSocket subscribers of that chunk (pixels inline, base64). The client also paints its own save straight into the canvas cache, so artwork never depends on the echo coming back
3. Background task (`_update_chunk_image`, serialized by a `Semaphore(1)`) re-renders **only the chunk image**, broadcasts `chunk_updated`, and sets `chunks.dirty = TRUE`
4. Separately, `services/overview.py` rebuilds the Level-0 overview at most once every `overview_coalesce_seconds` (default 5), folding in every chunk that went dirty in that window, then broadcasts `overview_updated`

**Three render levels** (client picks by zoom in `MosaicCanvas.tsx`):
- Level 0: single 2048×2048 overview WebP
- Level 1: 10×10 grid of 2048×2048 chunk WebPs (each chunk = 100×100 tiles)
- Level 2: individual tiles fetched as raw RGB bytes from Postgres

**Key modules:**
- `backend/app/services/tiles.py` — save/delete + background chunk render scheduling
- `backend/app/services/chunk_renderer.py` — PIL compositing (runs in thread pool)
- `backend/app/services/overview.py` — coalesced Level-0 rebuilds, driven by `chunks.dirty`
- `backend/app/services/storage.py` — local-vs-S3 abstraction + version tracking (`chunk_versions.json`)
- `backend/app/websocket/manager.py` — connections, chunk subscriptions, 50ms message batching
- `frontend/src/components/MosaicCanvas.tsx` — main canvas: viewport, all 3 levels, LRU caches (~880 lines; extract hooks rather than grow it)
- `frontend/src/hooks/useOverviewImage.ts` — Level-0 image: initial load + debounced, level-gated refresh
- `frontend/src/utils/tileLoader.ts` — tile fetch queue: max 6 concurrent, dedup, cancellation

## Critical invariants

- **Tile pixel format is a contract**: exactly 3072 bytes = 32×32×3 RGB, row-major. Enforced in `api/tiles.py`, `utils/pixels.ts`, and the DB `BYTEA` column. Never change one side alone.
- **Grid constants exist in three places and must match**: `backend/app/config.py`, `frontend/src/config.ts`, and `backend/scripts/render_chunks.py` (also `CHUNK_PREVIEW_SIZE`/`MOSAIC_PREVIEW_SIZE` duplicated between `chunk_renderer.py` and `render_chunks.py`). Prefer deduplicating over adding a fourth copy.
- **ID formats differ by context**: DB/WS ids use colons (`tile_id "x:y"`, `chunk_id "cx:cy"`); storage/S3 file keys use underscores (`{cx}_{cy}.webp`). Easy to mix up.
- **Single-instance assumption**: rate limiter, WS manager, stats cache, and `chunk_versions.json` version tracking are all in-process/file state. ECS desired-count must stay 1 unless these move to shared storage (Postgres already has an unused `chunks.version` column — the natural home).
- **Schema changes**: no migration tool. `schema.sql` runs idempotently on startup (`CREATE ... IF NOT EXISTS`); manual `ALTER`s for existing deployments are documented as comments in that file.
- **Route ordering**: in `api/chunks.py`, `/overview` routes must stay declared before `/{cx}/{cy}`.
- **Tile URLs carry no version, so they must never be cached by age.** `/api/tiles/{x}/{y}` sends `no-cache, must-revalidate` plus an ETag built from `tiles.version`, and answers 304 to a matching `If-None-Match`; the client fetches with `cache: "no-cache"`. Both sides must keep agreeing — a `max-age` here becomes permanently stale pixels the moment a CDN fronts `/api`.
- **`chunks.dirty` is owned by the render path, not the save transaction.** It means "this chunk's image is newer than the overview". Only `overview.mark_chunk_dirty` sets it (after the image is written) and only `overview.flush_pending` clears it. The save/delete upserts must leave the column alone — they used to write `FALSE` on every save, which is why the partial index built for it never did anything.
- **The WS subscription cap is duplicated**: `ws_max_subscriptions` in `backend/app/config.py` and `MAX_SUBSCRIBED_CHUNKS` in `frontend/src/config.ts`. The client must never ask for more than the server keeps, or the two silently disagree about what is subscribed.
- **The mosaic re-fits to the canvas on resize until the user pans or zooms** (`hasUserAdjustedView` in `MosaicCanvas`). Any new code path that moves the viewport on the user's behalf must call `markViewAdjusted`, or a later resize will yank the view back to fit-to-screen. Clicking Fit to screen deliberately does not set it.

## Conventions

- Backend: black formatting, type hints, module-level `logger = logging.getLogger(__name__)`, docstrings on public functions. Services layer owns DB/storage access; API layer owns validation and HTTP concerns.
- Frontend: strict TS, prettier (100-char lines), CSS files co-located per component, refs + version counters for canvas state that shouldn't trigger React re-renders.
- UI: Radix primitives (`@radix-ui/react-*`) wrapped in custom-styled components; Lucide icons imported individually at `size={18}`; BEM-ish class names (`.tile-editor-panel__header`); design tokens are CSS variables in `index.css` (colors, spacing, radii, shadows) — use tokens, don't hard-code values; glass panels use `--color-bg-glass` + `backdrop-filter`. Icon-only buttons get `aria-label` and `title`.
- Tests mirror the split: `tests/unit` (mocked DB/WS, `tmp_storage` fixture) vs `tests/integration` (real Postgres via ASGI transport, autouse fixtures reset all global state — keep that pattern when adding global state). Placement: new endpoint → `tests/integration/test_<router>_api.py`; pure function → `tests/unit/`; don't reuse a filename across unit/ and integration/ (pytest collects by name). Tests asserting on rendered chunk/overview output must `await drain_background_tasks()` first.
- Commits: imperative summary line, occasionally with a short body. No PR workflow — direct commits to `main`.
- **Commit messages must not mention Claude, AI assistance, or co-authorship.** No `Co-Authored-By: Claude` trailer, no "generated with" footer, no mention in the body. This overrides any default trailer the tooling would otherwise add. The same applies to PR descriptions if a PR workflow is ever added.

## Security & secrets

- **Never commit real credentials.** `task-def.json` leaked the old RDS password into this public repo's git history. The working copy is now a placeholder template that pulls `DATABASE_URL` from Secrets Manager, and `tests/unit/test_task_definition.py` guards that — **but the password is still in the git history**. Purge it before or during the redeploy, and check whether that password was reused anywhere else. For the new account keep secrets in `.env` / `.env.deploy` (gitignored) or Secrets Manager.
- The app is deliberately auth-less; abuse controls are per-IP rate limiting (`_check_rate_limit`) and WS connection caps in `config.py`. `get_client_ip` indexes `X-Forwarded-For` from the **right** using `settings.trusted_proxy_hops` — only entries appended by our own proxies are trustworthy. **`TRUSTED_PROXY_HOPS` must be set in production** (1 = ALB only, 2 = CloudFront→ALB); left at 0 behind a proxy, every request carries the load balancer's IP and the per-IP limits silently become site-wide. Note `hops=2` is only sound if the ALB cannot be reached directly — otherwise a client bypassing CloudFront controls the entry we read.

## Render concurrency rules (load-bearing — read before touching the render path)

`chunk_renderer.render_semaphore` serialises every image render in the process. Two independent reasons: a 2048x2048 RGB buffer is ~12.6 MB and decode + resize + encode holds several at once on a 1 GB task, and the read → composite → save sequence must not interleave.

- **Acquire it at the outermost call site only.** `asyncio.Semaphore` is not reentrant; a nested acquire deadlocks permanently with no timeout and no recovery (verified on 3.12).
- **The hold must span read → composite → save.** Releasing between the render call and the caller's save lets a second writer read the same pre-image and silently drop the first writer's tile.
- **Never await a WebSocket send while holding it.** `manager.broadcast` awaits every connection in turn, so one backpressured client would pin the permit — and every HTTP request waiting on it. Schedule broadcasts as background tasks instead.
- **A request must never render an image that already exists.** A stale overview is served as-is and the coalescer nudged; in-request rendering happens only when nothing is cached, and then via the single-flight helpers in `api/chunks.py` so concurrent callers share one render.
- **Waiters must `asyncio.shield` a shared render.** Starlette cancels a handler when its client disconnects, and that cancellation propagates into the awaited task — aborting the render for every other waiter (verified on 3.12).
- **Mark dirty inside the permit, after the image is written; clear dirty inside the permit, after the overview is written.** That pairing is the only thing making the coalescer's dirty set safe — clear it outside and any chunk saved in the gap loses its overview update silently.
- Adding module-level state to the render path means adding a reset to the autouse fixtures in `tests/integration/conftest.py` and teaching `drain_background_tasks()` about it.

## Throughput reality (measured, 0.5 vCPU / 1 GB)

The overview used to be re-encoded inside every tile save at 5000×5000, costing **1726 ms** — 9.4× the chunk render — and capping the *whole site* at ~0.5 saves/sec. Five people drawing one tile per 2 s each saw updates arrive 27 s after they stopped; the person drawing never noticed (their PUT returns in ~20 ms). Two changes removed it:

- **2048×2048 + `method=0` WebP**: the same incremental overview update measured **1726 ms → 291 ms** (encode alone 1563 → 112 ms) for ~40 KB more per image. Zoom level 0 only engages below 3 px/tile, so the overview is never displayed wider than ~3000 px — 5000×5000 was ~2.8× more pixels than could ever reach a screen.
- **Coalescing**: a save no longer renders the overview at all. It marks `chunks.dirty` and `services/overview.py` rebuilds once per window, so the cost is now independent of the edit rate (verified: 6 saves → 1 overview render).

Per-save cost is now the chunk render alone. `WEBP_METHOD` in `chunk_renderer.py` is the dial if bytes ever matter more than latency.

**Never re-render a chunk from a blank canvas.** If a chunk image is missing, compositing a tile onto fresh white wipes every other tile in that chunk from Levels 0–1 — permanently, since a chunk is only rebuilt when its image is *missing*. Verified: 6 pre-existing tiles erased by one unrelated edit on a cold image store. Fixed by `chunk_renderer.load_or_render_chunk_image` (rebuilds from the DB) and the equivalent fallback in `update_overview_chunks`; guarded by `tests/integration/test_cold_storage.py`. Still run `render_chunks.py` after a restore and before opening traffic — a chunk with no image at all is absent from Level 0 until something rebuilds it.

## Sharp edges (known, unfixed)

- Cold-chunk renders share the one render permit, so a cold cache under traffic serialises. Run `scripts/render_chunks.py` before opening traffic.
- `MosaicCanvas` has no touch handlers — mobile users cannot pan/zoom the mosaic (the tile editor itself works on touch).
- `MosaicCanvas` wheel-zoom only triggers on `deltaMode === 1`, which is Firefox-only; Chrome/Safari mouse wheels pan instead of zooming.
- **All canvas painting goes through `requestAnimationFrame`**, which browsers pause for a hidden document. A backgrounded or non-visible pane shows a blank canvas with perfectly correct viewport state — check `document.visibilityState` before chasing a "nothing renders" bug.
- There is still no Save button — a tile only reaches the server when the editor closes or another tile is clicked, so "live" means per-close, not per-stroke. See §1.8 of `.cursor/plans/pre-redeploy-hardening.md` for the rest of the editor input bugs.
