# Live Tesserae – Detailed Technical Plan

## 1. Project Summary

A collaborative mosaic website featuring 1 million tiles (1000×1000 grid). Each tile is a 32×32 pixel canvas that any visitor can edit. All changes sync in real-time across all connected clients.

---

## 2. Mosaic Specifications

| Property | Value |
|----------|-------|
| Grid size | 1000 × 1000 tiles |
| Total tiles | 1,000,000 |
| Tile resolution | 32 × 32 pixels |
| Total canvas size | 32,000 × 32,000 pixels |
| Coordinate system | (0,0) at top-left, (999,999) at bottom-right |

---

## 3. Architecture Decisions

These decisions were made upfront because they're difficult to change later:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Compute** | ECS Fargate | Managed containers, auto-restart, no server maintenance |
| **Database** | RDS PostgreSQL | Flexible queries for chunk rendering, simple schema |
| **WebSocket** | Self-managed in FastAPI | Full control, learn the internals, in-memory pub/sub for MVP |
| **Tile update delivery** | Inline image data over WebSocket | Truly instant updates, no extra fetch round-trip |
| **Storage** | S3 with versioned URLs | Cache-busting without invalidation, infinite CDN cache |
| **CDN** | CloudFront | Global edge caching for chunks and tiles |
| **Chunk rendering** | Async via Lambda | Non-blocking tile updates, auto-scaling |
| **Subscriptions** | Chunk-based | Clients subscribe to chunks they're viewing, efficient bandwidth |

---

## 4. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Canvas    │  │   Pixel     │  │   WebSocket Client      │  │
│  │   Renderer  │  │   Editor    │  │   (chunk subscriptions) │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
    ┌────────────┐     ┌────────────┐     ┌────────────┐
    │ CloudFront │     │  Fargate   │     │  Fargate   │
    │   (CDN)    │     │  REST API  │     │ WebSocket  │
    └────────────┘     └────────────┘     └────────────┘
           │                  │                  │
           │                  └────────┬─────────┘
           │                           │
           ▼                           ▼
    ┌────────────┐              ┌────────────┐
    │     S3     │              │    RDS     │
    │  (images)  │              │ PostgreSQL │
    └────────────┘              └────────────┘
           ▲
           │
    ┌────────────┐
    │   Lambda   │
    │  (chunk    │
    │  renderer) │
    └────────────┘
```

---

## 5. Tile Model

### Single Tile Type (MVP)

Each tile is a 32×32 pixel bitmap image.

```json
{
  "tile_id": "512:384",
  "chunk_id": "5:3",
  "image_path": "tiles/512_384.png",
  "version": 17,
  "updated_at": 1700000000
}
```

**Note:** `chunk_id` is included for efficient chunk queries and potential future DynamoDB migration.

### Default Tile Optimization

- The mosaic starts with all tiles in a **default state** (blank/white)
- **Default tiles are NOT stored** in the database or file storage
- Only tiles that have been edited are stored
- If a tile is reset to default, its record and image are deleted

This keeps storage sparse – a mosaic with 10,000 edited tiles only stores 10,000 records, not 1 million.

---

## 6. Zoom Levels & Rendering

Users see the entire mosaic on page load via pre-rendered zoom levels:

### Zoom Level Strategy

| Level | Description | Tile Size on Screen | Source |
|-------|-------------|---------------------|--------|
| 0 | Full mosaic view | ~1-2px per tile | Single pre-rendered image |
| 1 | Region view | ~4-8px per tile | Chunked images (100×100 tile regions) |
| 2 | Neighborhood view | ~16px per tile | Smaller chunks (20×20 tile regions) |
| 3 | Tile view | 32px+ per tile | Individual tile images |

### Chunk System

- Mosaic divided into **100 chunks** (10×10 grid of 100×100 tile regions)
- Each chunk pre-rendered at multiple zoom levels
- Chunks stored in S3, served via CloudFront
- **Versioned URLs**: `chunks/5_3.png?v=42` – increment version on re-render, infinite cache

### Lambda Chunk Renderer

When a tile updates:
1. Backend marks chunk as dirty in database
2. Backend invokes Lambda asynchronously
3. Lambda loads all tiles in chunk from S3
4. Lambda composites tiles into chunk image
5. Lambda saves to S3 with new version
6. Lambda updates chunk version in database

---

## 7. Tech Stack

### Frontend
- **React** – UI framework
- **TypeScript** – Type safety
- **Bun** – Package manager and runtime
- **HTML5 Canvas** – Mosaic rendering
- **Native WebSocket** – Real-time updates

### Backend
- **FastAPI** (Python) – REST API + WebSocket server
- **Pillow** – Image processing
- **asyncpg** – Async PostgreSQL driver
- **boto3** – AWS SDK for S3 and Lambda

### AWS Services
- **ECS Fargate** – Container hosting (API + WebSocket)
- **RDS PostgreSQL** – Tile metadata database
- **S3** – Tile and chunk image storage
- **CloudFront** – CDN for global delivery
- **Lambda** – Async chunk rendering

### Future (Phase 5)
- **ElastiCache Redis** – Pub/sub for horizontal WebSocket scaling

---

## 8. Database Schema

### Tiles Table

```sql
CREATE TABLE tiles (
    tile_id VARCHAR(11) PRIMARY KEY,  -- "x:y" format, max "999:999"
    chunk_id VARCHAR(7) NOT NULL,     -- "cx:cy" format for efficient queries
    image_path VARCHAR(255) NOT NULL,
    version INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tiles_chunk ON tiles(chunk_id);
CREATE INDEX idx_tiles_updated ON tiles(updated_at);
```

### Chunks Table

```sql
CREATE TABLE chunks (
    chunk_id VARCHAR(7) PRIMARY KEY,  -- "cx:cy" format
    version INTEGER DEFAULT 0,
    dirty BOOLEAN DEFAULT FALSE,
    rendered_at TIMESTAMP
);
```

---

## 9. API Endpoints

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mosaic/info` | Returns mosaic dimensions, chunk info, versions |
| GET | `/api/chunks/{cx}/{cy}` | Redirects to versioned S3 URL |
| GET | `/api/tiles/{x}/{y}` | Redirects to versioned S3 URL |
| PUT | `/api/tiles/{x}/{y}` | Update tile (accepts PNG body) |
| DELETE | `/api/tiles/{x}/{y}` | Reset tile to default |

### WebSocket Protocol

**Connection:** `wss://api.livetesserae.com/ws`

**Client → Server:**

```json
{
  "type": "subscribe",
  "chunks": ["5:3", "5:4", "6:3", "6:4"]
}
```

```json
{
  "type": "unsubscribe",
  "chunks": ["5:3"]
}
```

**Server → Client:**

```json
{
  "type": "tile_update",
  "x": 512,
  "y": 384,
  "chunk_id": "5:3",
  "version": 18,
  "image": "data:image/png;base64,iVBORw0KGgo..."
}
```

```json
{
  "type": "chunk_ready",
  "chunk_id": "5:3",
  "version": 43
}
```

**Note:** Tile updates include the actual image data (base64 PNG, ~1-2KB) for instant rendering without an extra fetch.

---

## 10. Tile Update Flow

```
User draws on tile (512, 384)
         │
         ▼
┌─────────────────────────────────────┐
│  Client sends PUT /api/tiles/512/384│
│  with PNG body (32×32 image)        │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Backend validates image            │
│  - Must be valid PNG                │
│  - Must be exactly 32×32 pixels     │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Backend uploads to S3              │
│  tiles/512_384.png                  │
│  Increment version in DB            │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Backend marks chunk 5:3 as dirty   │
│  Invokes Lambda asynchronously      │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Backend broadcasts to WebSocket    │
│  clients subscribed to chunk 5:3    │
│  Includes base64 image data         │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  All clients instantly render       │
│  the new tile (no fetch needed)     │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Lambda renders chunk 5:3           │
│  Uploads to S3, updates version     │
│  Broadcasts chunk_ready event       │
└─────────────────────────────────────┘
```

---

## 11. Real-Time System

### WebSocket Connection Lifecycle

1. Client connects to `/ws`
2. Client sends `subscribe` with visible chunk IDs
3. Server tracks subscriptions in memory (dict of chunk_id → set of connections)
4. On tile update, server looks up subscribers for that chunk
5. Server sends `tile_update` with inline image to each subscriber
6. When user pans/zooms, client sends updated `subscribe`/`unsubscribe`

### Chunk-Based Subscriptions

- Mosaic has 100 chunks (10×10 grid)
- Client calculates which chunks are visible in viewport
- Typical viewport shows 4-9 chunks
- Only receives updates for subscribed chunks

### MVP: In-Memory Pub/Sub

For single Fargate instance:
- Subscriptions stored in Python dict
- Broadcasting is direct iteration over subscribers
- No Redis needed

### Phase 5: Redis Pub/Sub

For multiple Fargate instances:
- Each instance subscribes to Redis channels for its connected clients
- Tile update publishes to Redis channel
- All instances receive and forward to their local connections

---

## 12. Implementation Phases

### Phase 1 – MVP

**Goal:** Working mosaic with 1 million drawable tiles, deployed on AWS

**Features:**
- 1000×1000 tile grid
- 32×32 pixel editor per tile
- Real-time updates via WebSocket (inline images)
- Pre-rendered zoom levels via Lambda
- Sparse storage (only edited tiles stored)
- React frontend with zoom/pan
- Single Fargate instance

**AWS Services:**
- ECS Fargate (1 task, 0.5 vCPU, 1GB RAM)
- RDS PostgreSQL (db.t4g.micro)
- S3 (tile + chunk storage)
- CloudFront (CDN)
- Lambda (chunk renderer)

**Estimated Cost:** ~$30-40/month

---

### Phase 2 – Rate Limiting & Abuse Prevention

**Goal:** Prevent spam and griefing without hurting UX

**Features:**
- IP-based rate limiting (60 edits/minute)
- Anonymous session tokens for additional tracking
- Per-tile cooldown (same tile can't be edited twice within 5 seconds)
- Burst allowance (first 20 edits are instant)

**Implementation:**
- Add Redis (ElastiCache cache.t3.micro) for rate limit counters
- FastAPI middleware for enforcement
- Configurable limits via environment variables

**Additional Cost:** ~$12/month for Redis

---

### Phase 3 – AI Moderation

**Goal:** Automatically detect and remove inappropriate content

**Features:**
- Lightweight ML model (NudeNet) for tile scanning
- Periodic composite scanning for multi-tile patterns
- Automatic reversion of flagged content
- User reporting triggers immediate re-scan

**Implementation:**
- ML inference in Lambda (CPU-based)
- Scan on tile upload, before broadcasting
- Background worker for periodic full scans
- Optional: AWS Rekognition fallback

---

### Phase 4 – Image Uploads

**Goal:** Allow users to upload images instead of drawing pixel-by-pixel

**Features:**
- Upload any image, auto-resize to 32×32
- Same moderation pipeline as drawn tiles
- Drag-and-drop upload UI

**Implementation:**
- Image validation and resizing in backend
- Pillow for resize/crop operations

---

### Phase 5 – Horizontal Scaling

**Goal:** Handle high traffic and large concurrent user counts

**Features:**
- Redis pub/sub for WebSocket scaling across multiple Fargate tasks
- Auto-scaling based on CPU/connections
- Database connection pooling
- Read replicas if needed

**Implementation:**
- ElastiCache Redis for pub/sub
- Application Load Balancer with sticky sessions for WebSocket
- ECS Service auto-scaling

---

## 13. Storage & Versioning

### S3 Structure

```
s3://live-tesserae/
├── tiles/
│   ├── 0_0.png
│   ├── 512_384.png
│   └── ...
└── chunks/
    ├── level0/
    │   └── full.png           # Entire mosaic, low-res
    ├── level1/
    │   ├── 0_0.png            # 100×100 tile chunks
    │   ├── 0_1.png
    │   └── ...
    └── level2/
        ├── 0_0.png            # 20×20 tile chunks
        └── ...
```

### Versioned URLs (Cache-Busting)

URLs include version for infinite CDN caching:
- `https://cdn.livetesserae.com/tiles/512_384.png?v=17`
- `https://cdn.livetesserae.com/chunks/level1/5_3.png?v=43`

When tile updates:
1. Overwrite file in S3 (same path)
2. Increment version in database
3. Clients request new URL with new version
4. Old cached version naturally expires (never requested again)

**No storing old tiles.** Only one file per tile exists at any time.

---

## 14. Cost Breakdown

### MVP (Phase 1)

| Service | Specs | Monthly Cost |
|---------|-------|--------------|
| ECS Fargate | 0.5 vCPU, 1GB RAM, 1 task | ~$15 |
| RDS PostgreSQL | db.t4g.micro, 20GB | ~$15 |
| S3 | ~100MB storage | <$1 |
| CloudFront | Free tier (1TB) | $0 |
| Lambda | Free tier | $0 |
| **Total** | | **~$30-35/month** |

### With Rate Limiting (Phase 2+)

| Service | Addition | Monthly Cost |
|---------|----------|--------------|
| ElastiCache Redis | cache.t3.micro | +$12 |
| **Total** | | **~$45/month** |

### At Scale

| Service | Specs | Monthly Cost |
|---------|-------|--------------|
| ECS Fargate | 2 vCPU, 4GB, 2-3 tasks | ~$80 |
| RDS PostgreSQL | db.t4g.small | ~$30 |
| ElastiCache Redis | cache.t3.small | ~$25 |
| S3 + CloudFront | Higher traffic | ~$25 |
| Lambda | More invocations | ~$5 |
| **Total** | | **~$150-200/month** |

---

## 15. File Structure

```
live-tesserae/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── config.py            # Environment config
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── tiles.py         # Tile CRUD endpoints
│   │   │   ├── chunks.py        # Chunk endpoints
│   │   │   └── mosaic.py        # Mosaic info endpoint
│   │   ├── websocket/
│   │   │   ├── __init__.py
│   │   │   ├── handler.py       # WebSocket connection handler
│   │   │   └── broadcaster.py   # Pub/sub logic
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── storage.py       # S3 operations
│   │   │   ├── database.py      # PostgreSQL operations
│   │   │   └── chunks.py        # Chunk rendering trigger
│   │   └── models/
│   │       ├── __init__.py
│   │       └── tile.py          # Pydantic models
│   ├── requirements.txt
│   ├── Dockerfile
│   └── docker-compose.yml       # Local development
├── lambda/
│   ├── chunk_renderer/
│   │   ├── handler.py           # Lambda entry point
│   │   ├── renderer.py          # Image compositing logic
│   │   └── requirements.txt
│   └── template.yaml            # SAM template
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── MosaicCanvas.tsx    # Main canvas with zoom/pan
│   │   │   ├── TileEditor.tsx      # 32×32 pixel drawing UI
│   │   │   ├── ZoomControls.tsx    # Zoom buttons
│   │   │   └── Toolbar.tsx         # Color picker, tools
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts     # WebSocket connection
│   │   │   ├── useMosaic.ts        # Mosaic state management
│   │   │   └── useViewport.ts      # Viewport/zoom state
│   │   ├── utils/
│   │   │   ├── canvas.ts           # Canvas rendering helpers
│   │   │   └── coordinates.ts      # Tile/chunk coordinate math
│   │   └── types/
│   │       └── index.ts            # TypeScript types
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── infrastructure/
│   ├── terraform/                  # Or CDK/CloudFormation
│   │   ├── main.tf
│   │   ├── ecs.tf
│   │   ├── rds.tf
│   │   ├── s3.tf
│   │   └── cloudfront.tf
│   └── scripts/
│       └── deploy.sh
├── OVERVIEW.md
├── DETAILED_PLAN.md
└── README.md
```

---

## 16. Key Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Grid size | 1000×1000 | 1M tiles is ambitious but achievable |
| Tile size | 32×32 | Large enough for pixel art, small enough for collaboration |
| Coordinate format | "x:y" string | Simple, human-readable primary key |
| No history | Current state only | Simplifies storage, reduces costs |
| Sparse storage | Don't store defaults | Massive storage savings |
| Chunk-based rendering | Pre-render zoom levels | Only way to show 1M tiles at once |
| Inline WebSocket images | Send base64 PNG | Truly instant updates, no fetch latency |
| Versioned URLs | Query param versioning | Avoid CDN invalidation costs/delays |
| Lambda for chunks | Async rendering | Non-blocking, auto-scaling |
| Chunk subscriptions | Subscribe by chunk ID | Efficient bandwidth, simple model |

---

## 17. Open Questions

- **Chunk size:** 100×100 tiles (10×10 grid = 100 chunks) seems right. Revisit if needed.
- **Default tile appearance:** White? Light gray? Subtle grid pattern?
- **Pixel editor UI:** Modal overlay vs. inline expansion vs. sidebar?
- **Color palette:** Full RGB or curated palette for visual coherence?
- **Mobile support:** Touch-friendly editor? Pinch-to-zoom?

These can be decided during implementation.

---

## 18. Success Criteria for MVP

- [ ] User can view entire mosaic on page load (zoom level 0)
- [ ] User can zoom and pan smoothly across all zoom levels
- [ ] User can click any tile to open pixel editor
- [ ] User can draw and save a 32×32 image
- [ ] Changes appear instantly for all connected users (via WebSocket)
- [ ] Chunk images update within seconds of tile changes
- [ ] Unedited tiles show default state without consuming storage
- [ ] System handles 100+ concurrent users without issues
- [ ] Deployed and running on AWS (Fargate + RDS + S3 + CloudFront + Lambda)
