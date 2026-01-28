# Implementation Order

A high-level roadmap for building Live Tesserae. Each step builds on the previous.

---

## Step 1: Local Development Setup

Set up the development environment so we can run everything locally.

- [x] Create project folder structure
- [x] Set up Python virtual environment
- [x] Create `docker-compose.yml` for local Postgres
- [x] Set up Bun for frontend (Vite + React)
- [x] Verify everything runs

---

## Step 2: Backend Skeleton

Get a basic FastAPI server running.

- [x] Create FastAPI app with health check endpoint
- [x] Set up database connection with asyncpg
- [x] Create project structure (api/, services/, models/)
- [x] Add basic logging
- [x] Test endpoint works

---

## Step 3: Tile API

Build the core tile CRUD operations.

- [x] Create database schema (tiles table)
- [x] Implement `PUT /api/tiles/{x}/{y}` - save tile
- [x] Implement `GET /api/tiles/{x}/{y}` - get tile
- [x] Implement `DELETE /api/tiles/{x}/{y}` - reset to default
- [x] Local filesystem storage for tile images
- [x] Input validation (32×32, valid PNG)
- [x] Test all endpoints

---

## Step 4: Frontend Skeleton

Basic React app that displays something.

- [x] Initialize Vite + React + TypeScript project
- [x] Create basic App component
- [x] Add a Canvas element
- [x] Render a simple grid (just lines for now)
- [x] Click detection - log which tile was clicked
- [x] Basic styling

---

## Step 5: Pixel Editor

Build the 32×32 drawing interface.

- [x] Create TileEditor component
- [x] 32×32 canvas for drawing
- [x] Mouse/touch drawing (click and drag)
- [x] Color picker (basic palette or full RGB)
- [x] Clear/reset button
- [x] Export canvas as PNG data
- [x] Save button (calls API later)

---

## Step 6: Connect Frontend ↔ Backend

Wire up the editor to save tiles.

- [x] Frontend calls `PUT /api/tiles/{x}/{y}` on save
- [x] Handle loading/error states
- [x] Fetch existing tile when editor opens
- [x] Display saved tiles on the main canvas
- [x] Test full loop: draw → save → refresh → see tile

---

## Step 7: WebSocket Real-Time Updates ✅

Add live updates so changes appear for all users.

- [x] Add WebSocket endpoint in FastAPI (`/ws`)
- [x] Connection manager (track connected clients)
- [x] Broadcast tile updates when saved
- [x] Frontend WebSocket connection
- [x] Handle incoming `tile_update` messages
- [x] Render updates without page refresh
- [x] Handle disconnect/reconnect

---

## Step 8: Chunk Subscriptions ✅

Optimize WebSocket to only send relevant updates.

- [x] Define chunk system (10×10 grid of chunks)
- [x] Add `subscribe`/`unsubscribe` messages
- [x] Track subscriptions per connection
- [x] Only broadcast to subscribers of affected chunk
- [x] Frontend sends subscription based on viewport
- [x] Update subscription on pan/zoom (deferred to Step 9)

---

## Step 9: Zoom & Pan ✅

Make the mosaic navigable at different scales.

- [x] Viewport state (center position, zoom level)
- [x] Pan with mouse drag
- [x] Zoom with scroll wheel
- [x] Zoom buttons (+/-)
- [x] Initial view: fit entire mosaic centered with padding
- [x] Update chunk subscriptions on viewport change

---

## Step 10: Chunk Rendering ✅

Pre-render zoom levels for performance using a 3-level pyramid.

- [x] Define zoom levels (0=overview 1000×1000, 1=chunks 320×320, 2=tiles 32×32)
- [x] Chunk renderer function (composite tiles → chunk image)
- [x] Trigger re-render when tiles update (sync on save)
- [x] Store chunk images locally with version tracking
- [x] Serve chunks via API with cache headers
- [x] Frontend loads chunks at appropriate zoom level
- [x] Version tracking for cache busting

---

## Step 11: AWS Infrastructure

Set up cloud deployment.

- [ ] Create S3 bucket for tile/chunk storage
- [ ] Create RDS PostgreSQL instance
- [ ] Refactor storage service to use S3
- [ ] Create CloudFront distribution
- [ ] Test locally with S3 (AWS credentials)
- [ ] Update environment config

---

## Step 12: Containerize & Deploy

Get it running on AWS.

- [ ] Write Dockerfile for backend
- [ ] Test container locally
- [ ] Set up ECS cluster and Fargate task definition
- [ ] Deploy backend to Fargate
- [ ] Create Lambda for chunk rendering
- [ ] Connect Lambda to S3 events or API trigger
- [ ] Deploy frontend to S3 + CloudFront
- [ ] Test full system on AWS

---

## Step 13: Polish & Optimize

Final touches for MVP.

- [ ] Error handling and user feedback
- [ ] Loading states and skeletons
- [ ] Performance profiling
- [ ] Mobile touch support (basic)
- [ ] Favicon and meta tags
- [ ] Final testing

---

## Progress Tracker

| Step | Status | Notes |
|------|--------|-------|
| 1. Local Setup | ✅ Complete | |
| 2. Backend Skeleton | ✅ Complete | |
| 3. Tile API | ✅ Complete | |
| 4. Frontend Skeleton | ✅ Complete | |
| 5. Pixel Editor | ✅ Complete | |
| 6. Connect FE ↔ BE | ✅ Complete | |
| 7. WebSocket | ✅ Complete | |
| 8. Chunk Subscriptions | ✅ Complete | |
| 9. Zoom & Pan | ✅ Complete | |
| 10. Chunk Rendering | ⬜ Not started | |
| 11. AWS Infrastructure | ⬜ Not started | |
| 12. Deploy | ⬜ Not started | |
| 13. Polish | ⬜ Not started | |

**Legend:** ⬜ Not started | 🟡 In progress | ✅ Complete

---

## Milestones

```
Steps 1-3:   [Backend working locally]     → Can save/load tiles via API
Steps 4-6:   [Full loop working]           → Can draw and save tiles from UI
Steps 7-8:   [Real-time working]           → Changes appear live for all users
Steps 9-10:  [Scale working]               → Can navigate 1M tile mosaic
Steps 11-12: [Deployed on AWS]             → Live on the internet
Step 13:     [MVP complete]                → Ready for users
```
