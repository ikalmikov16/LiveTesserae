#!/usr/bin/env python3
"""
Render all chunks and the mosaic overview.

Run this after init_mosaic.py to generate the Level 1 chunks and Level 0 overview.

OPTIMIZED: Uses concurrent asyncio tasks to render multiple chunks in parallel.

Usage:
    python scripts/render_chunks.py
    python scripts/render_chunks.py --chunks-only  # Skip overview
    python scripts/render_chunks.py --overview-only  # Skip chunks
    python scripts/render_chunks.py --workers 8  # Concurrent chunks
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# Now we can import from the backend
from app.services import chunk_renderer, storage
from app.config import settings

# Number of concurrent chunk renders
DEFAULT_WORKERS = min(8, os.cpu_count() or 4)


async def render_chunk_task(cx: int, cy: int, semaphore: asyncio.Semaphore) -> tuple[int, int, bool]:
    """Render a single chunk with semaphore for concurrency control."""
    async with semaphore:
        chunk_data = await chunk_renderer.render_chunk(cx, cy)
        await storage.save_chunk_image(cx, cy, chunk_data)
        return (cx, cy, True)


async def render_all_chunks(workers: int = DEFAULT_WORKERS, skip_existing: bool = False) -> int:
    """Render all chunk preview images with concurrent processing."""
    chunks_per_row = settings.grid_width // settings.chunk_size
    total_chunks = chunks_per_row * chunks_per_row
    
    print(f"Rendering {total_chunks} chunks with {workers} concurrent workers...")
    print()
    
    start_time = time.time()
    
    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(workers)
    
    # Build list of chunks to render
    chunks_to_render = []
    for cy in range(chunks_per_row):
        for cx in range(chunks_per_row):
            if skip_existing:
                existing = await storage.get_chunk_image(cx, cy)
                if existing:
                    continue
            chunks_to_render.append((cx, cy))
    
    if not chunks_to_render:
        print("No chunks to render.")
        return 0
    
    # Create all tasks
    tasks = [
        render_chunk_task(cx, cy, semaphore)
        for cx, cy in chunks_to_render
    ]
    
    # Run with progress tracking
    rendered = 0
    for coro in asyncio.as_completed(tasks):
        cx, cy, success = await coro
        rendered += 1
        
        elapsed = time.time() - start_time
        rate = rendered / elapsed if elapsed > 0 else 0
        eta = (len(chunks_to_render) - rendered) / rate if rate > 0 else 0
        pct = (rendered / len(chunks_to_render)) * 100
        
        print(f"\rProgress: {pct:.0f}% ({rendered}/{len(chunks_to_render)}) "
              f"- {rate:.1f} chunks/sec - ETA: {eta:.0f}s", end="", flush=True)
    
    elapsed = time.time() - start_time
    print(f"\n\nRendered {rendered} chunks in {elapsed:.1f}s ({rendered/elapsed:.1f} chunks/sec)")
    return rendered


async def render_overview() -> None:
    """Render the mosaic overview image."""
    print("Rendering mosaic overview...")
    start_time = time.time()
    
    overview_data = await chunk_renderer.render_mosaic_overview()
    await storage.save_mosaic_overview(overview_data)
    
    elapsed = time.time() - start_time
    
    # Get file size
    overview_path = storage.get_mosaic_overview_path()
    size_kb = overview_path.stat().st_size / 1024
    
    print(f"Overview rendered: {size_kb:.0f} KB in {elapsed:.1f}s")


async def main(chunks_only: bool = False, overview_only: bool = False, workers: int = DEFAULT_WORKERS):
    """Main entry point."""
    # Ensure storage directories exist
    storage.ensure_storage_directories()
    
    if not overview_only:
        await render_all_chunks(workers=workers)
        print()
    
    if not chunks_only:
        await render_overview()
    
    print()
    print("Done! Refresh your browser to see the changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render chunks and overview (optimized)")
    parser.add_argument("--chunks-only", action="store_true", help="Only render chunks")
    parser.add_argument("--overview-only", action="store_true", help="Only render overview")
    parser.add_argument("--workers", "-w", type=int, default=DEFAULT_WORKERS,
                        help=f"Number of concurrent chunk renders (default: {DEFAULT_WORKERS})")
    
    args = parser.parse_args()
    
    asyncio.run(main(chunks_only=args.chunks_only, overview_only=args.overview_only, workers=args.workers))
