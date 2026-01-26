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

- [ ] Create FastAPI app with health check endpoint
- [ ] Set up database connection with asyncpg
- [ ] Create project structure (api/, services/, models/)
- [ ] Add basic logging
- [ ] Test endpoint works

---

## Step 3: Tile API

Build the core tile CRUD operations.

- [ ] Create database schema (tiles table)
- [ ] Implement `PUT /api/tiles/{x}/{y}` - save tile
- [ ] Implement `GET /api/tiles/{x}/{y}` - get tile
- [ ] Implement `DELETE /api/tiles/{x}/{y}` - reset to default
- [ ] Local filesystem storage for tile images
- [ ] Input validation (32×32, valid PNG)
- [ ] Test all endpoints

---

## Step 4: Frontend Skeleton

Basic React app that displays something.

- [ ] Initialize Vite + React + TypeScript project
- [ ] Create basic App component
- [ ] Add a Canvas element
- [ ] Render a simple grid (just lines for now)
- [ ] Click detection - log which tile was clicked
- [ ] Basic styling

---

## Step 5: Pixel Editor

Build the 32×32 drawing interface.

- [ ] Create TileEditor component
- [ ] 32×32 canvas for drawing
- [ ] Mouse/touch drawing (click and drag)
- [ ] Color picker (basic palette or full RGB)
- [ ] Clear/reset button
- [ ] Export canvas as PNG data
- [ ] Save button (calls API later)

---

## Step 6: Connect Frontend ↔ Backend

Wire up the editor to save tiles.

- [ ] Frontend calls `PUT /api/tiles/{x}/{y}` on save
- [ ] Handle loading/error states
- [ ] Fetch existing tile when editor opens
- [ ] Display saved tiles on the main canvas
- [ ] Test full loop: draw → save → refresh → see tile

---

## Step 7: WebSocket Real-Time Updates

Add live updates so changes appear for all users.

- [ ] Add WebSocket endpoint in FastAPI (`/ws`)
- [ ] Connection manager (track connected clients)
- [ ] Broadcast tile updates when saved
- [ ] Frontend WebSocket connection
- [ ] Handle incoming `tile_update` messages
- [ ] Render updates without page refresh
- [ ] Handle disconnect/reconnect

---

## Step 8: Chunk Subscriptions

Optimize WebSocket to only send relevant updates.

- [ ] Define chunk system (10×10 grid of chunks)
- [ ] Add `subscribe`/`unsubscribe` messages
- [ ] Track subscriptions per connection
- [ ] Only broadcast to subscribers of affected chunk
- [ ] Frontend sends subscription based on viewport
- [ ] Update subscription on pan/zoom

---

## Step 9: Zoom & Pan

Make the mosaic navigable at different scales.

- [ ] Viewport state (center position, zoom level)
- [ ] Pan with mouse drag
- [ ] Zoom with scroll wheel
- [ ] Zoom buttons (+/-)
- [ ] Constrain to mosaic bounds
- [ ] Smooth animations (optional)

---

## Step 10: Chunk Rendering

Pre-render zoom levels for performance.

- [ ] Define zoom levels (0=full, 1=100×100, 2=20×20, 3=individual)
- [ ] Chunk renderer function (composite tiles → chunk image)
- [ ] Trigger re-render when tiles update
- [ ] Store chunk images locally
- [ ] Serve chunks via API
- [ ] Frontend loads chunks at appropriate zoom level
- [ ] Version tracking for cache busting

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
| 2. Backend Skeleton | ⬜ Not started | |
| 3. Tile API | ⬜ Not started | |
| 4. Frontend Skeleton | ⬜ Not started | |
| 5. Pixel Editor | ⬜ Not started | |
| 6. Connect FE ↔ BE | ⬜ Not started | |
| 7. WebSocket | ⬜ Not started | |
| 8. Chunk Subscriptions | ⬜ Not started | |
| 9. Zoom & Pan | ⬜ Not started | |
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
