# Live Tesserae

## What Is It?

A collaborative website where anyone can contribute to a massive shared mosaic. The mosaic contains **1 million tiles** (1000×1000 grid), and each tile is a tiny **32×32 pixel canvas** that users can draw on.

Think of it as a giant shared canvas – anyone can zoom in, pick a tile, and create pixel art. All changes appear in real-time for everyone viewing the mosaic.

---

## Core Experience

1. **Visit the site** → See the entire mosaic at a glance
2. **Zoom in** → Navigate to any region
3. **Click a tile** → Open a simple pixel editor
4. **Draw** → Your creation appears live for everyone

No accounts. No signup. Just draw.

---

## Technical Highlights

- **1 million tiles** (1000×1000 grid)
- **32×32 pixels per tile** (1,024 pixels of creative space)
- **Instant real-time updates** via WebSocket with inline image data
- **Sparse storage** – only modified tiles are stored
- **Zoom levels** – pre-rendered chunks for smooth navigation at any scale
- **AWS-native** – Fargate, RDS, S3, CloudFront, Lambda

---

## What Makes It Different?

Unlike r/place (one pixel per tile, long cooldowns), Live Tesserae gives each tile enough space for actual pixel art. A single tile can be a face, a logo, a tiny landscape – not just a colored dot.

---

## Guiding Principles

- **Open** – No barriers to participation
- **Live** – Changes appear instantly across all clients
- **Scalable** – Architected for millions of tiles and thousands of users
- **Simple** – Minimal UI, maximum canvas

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│         Canvas rendering, pixel editor, WebSocket client     │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         CloudFront         Fargate        WebSocket
         (chunks)          (REST API)     (real-time)
              │               │               │
              └───────────────┼───────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
       S3                    RDS               Lambda
   (tile images)         (PostgreSQL)      (chunk rendering)
```

---

## Implementation Phases

| Phase | Features |
|-------|----------|
| 1 – MVP | 1M tiles, pixel drawing, real-time sync, AWS deployment |
| 2 | Rate limiting & abuse prevention |
| 3 | AI moderation |
| 4 | Image uploads |
| 5 | Horizontal scaling (Redis pub/sub, multiple instances) |

Each phase delivers a working product. The MVP is fully usable on day one.
