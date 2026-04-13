# Live Tesserae

A collaborative mosaic where anyone can contribute pixel art. The mosaic contains **1 million tiles** (1000 x 1000 grid), each a **32 x 32 pixel canvas**. All changes sync in real time.

No accounts, no signup — just draw.

## Architecture

```
Frontend (React)                 Backend (FastAPI)
┌─────────────────┐             ┌─────────────────┐
│  Canvas renderer │────REST────│  Tile API        │──── PostgreSQL
│  Pixel editor    │            │  Stats API       │
│  WebSocket client│────WS──────│  WebSocket server│──── S3 (images)
└─────────────────┘             └─────────────────┘
        │                               │
   CloudFront                      Lambda
   (CDN)                       (chunk renderer)
```

| Layer | Tech |
|-------|------|
| Frontend | React 19, TypeScript, Vite, HTML5 Canvas |
| Backend | FastAPI, asyncpg, Pillow, aioboto3 |
| Database | PostgreSQL |
| Storage | S3 (tiles + chunks), CloudFront (CDN) |
| Compute | ECS Fargate (API), Lambda (chunk rendering) |
| Real-time | WebSocket with chunk-based pub/sub |

## Getting Started

### Prerequisites

- [Bun](https://bun.sh/) (frontend)
- Python 3.12+ (backend)
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
pip install -r requirements.txt
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

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI entry point
│   │   ├── api/               # REST + WebSocket routes
│   │   ├── services/          # Business logic, DB, storage
│   │   └── websocket/         # Connection manager, broadcasting
│   ├── scripts/               # Chunk rendering scripts
│   ├── deploy.sh              # ECS deployment script
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/             # LandingPage, MosaicEditor
│   │   ├── components/        # MosaicCanvas, TileEditor, MiniMap, etc.
│   │   ├── hooks/             # useWebSocket, useViewport
│   │   ├── api/               # API client functions
│   │   └── utils/             # Pixels, chunks, session
│   └── deploy.sh              # S3 + CloudFront deployment
├── lambda/                    # Chunk renderer Lambda function
├── infrastructure/            # Terraform configs
├── docker-compose.yml         # Local PostgreSQL
└── LICENSE
```

## How It Works

**Tile storage is sparse** — only edited tiles are stored. The million default tiles don't consume any storage.

**Three rendering levels** keep the mosaic navigable at any zoom:

| Zoom out | Medium | Zoomed in |
|----------|--------|-----------|
| Single overview image | 100 chunk images (10x10 grid) | Individual 32x32 tiles |

**Real-time updates** use WebSocket with chunk-based subscriptions. Clients subscribe to the chunks they're viewing, so they only receive relevant updates. Tile pixel data is sent inline (base64) for instant rendering without extra fetches.

## Deployment

The app deploys to AWS with two scripts:

```bash
# Backend → ECR + ECS Fargate
cd backend && ./deploy.sh

# Frontend → S3 + CloudFront
cd frontend && ./deploy.sh
```

Both scripts read config from `.env.deploy` files (see `.env.deploy.example` in each directory).

**Important:** CloudFront needs custom error responses (403/404 → `/index.html` with 200) for client-side routing to work.

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://tesserae:tesserae_local@localhost:5433/tesserae` |
| `STORAGE_MODE` | `local` or `s3` | `local` |
| `AWS_S3_BUCKET` | S3 bucket for images (when `s3` mode) | — |
| `CORS_ORIGINS` | Allowed frontend origins | `http://localhost:5173` |

### Frontend (`frontend/.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_BASE_URL` | Backend API URL | `http://localhost:8000` |
| `VITE_CDN_BASE_URL` | CloudFront URL for chunks (optional) | — |

## License

[MIT](LICENSE)
