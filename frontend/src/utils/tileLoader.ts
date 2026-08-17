/**
 * Tile loading queue with concurrency limits, cancellation, and request deduplication.
 * Prevents ERR_INSUFFICIENT_RESOURCES by limiting parallel requests.
 */

import { API_BASE_URL } from "../config";

/**
 * Maximum concurrent tile fetches.
 *
 * This was 6, citing the browser's per-origin connection limit — an HTTP/1.1
 * rule. Production is HTTP/2 (Caddy; verified `http_version=2` on
 * /api/tiles/{x}/{y}), where one connection multiplexes ~100 streams and there
 * is no six-socket ceiling to respect. The ERR_INSUFFICIENT_RESOURCES this
 * module was written to avoid was socket exhaustion, which cannot occur here.
 *
 * It matters because Level 2 costs one round trip per tile and a tile GET is
 * almost pure latency — ~28 ms warm, of which the server contributes ~0. Fill
 * rate is therefore just MAX_CONCURRENT / RTT. Measured against production,
 * 300 tiles per run: 6 -> 150 tiles/s, 24 -> 276 tiles/s, 48 -> 895 tiles/s,
 * with zero non-200 responses at every level. A 1440x900 Level 2 screen needs
 * ~2100 tiles, so this is the difference between a ~14 s fill and a ~7 s one,
 * and it is why a large window used to sit half-rendered on the chunk image.
 *
 * Held at 24 rather than 48: a burst of 400 GETs at concurrency 32 left the
 * box's /health p50 unmoved (92.3 ms against a 92.0 ms baseline), so the server
 * has room, but 24 already captures most of the win and keeps the request
 * burst modest for a single small instance.
 */
const MAX_CONCURRENT = 24;

// Special symbol to distinguish cancelled requests from 404 (null)
export const TILE_CANCELLED = Symbol("TILE_CANCELLED");

export type TileLoadResult = Uint8Array | null | typeof TILE_CANCELLED;

interface QueuedTile {
  x: number;
  y: number;
  resolve: (data: TileLoadResult) => void;
  reject: (error: Error) => void;
  abortController: AbortController;
}

// Pending request tracking for deduplication
interface PendingRequest {
  promise: Promise<TileLoadResult>;
  subscribers: Array<(data: TileLoadResult) => void>;
  abortController: AbortController;
}

class TileLoader {
  private queue: QueuedTile[] = [];
  private activeCount = 0;
  private abortControllers = new Map<string, AbortController>();

  // Track in-flight requests to deduplicate concurrent requests for the same tile
  private pendingRequests = new Map<string, PendingRequest>();

  private getKey(x: number, y: number): string {
    return `${x}:${y}`;
  }

  /**
   * Load tile pixel data with request deduplication.
   * Multiple concurrent requests for the same tile share a single network request.
   * Returns:
   * - Uint8Array (3072 bytes) if tile exists
   * - null if tile doesn't exist (404)
   * - TILE_CANCELLED if request was cancelled
   */
  async loadTile(x: number, y: number): Promise<TileLoadResult> {
    const key = this.getKey(x, y);

    // Check for existing pending request - deduplicate by sharing the promise
    const pending = this.pendingRequests.get(key);
    if (pending) {
      // Return a new promise that resolves when the existing request completes
      return new Promise((resolve) => {
        pending.subscribers.push(resolve);
      });
    }

    // No pending request - create a new one
    return new Promise((resolve, reject) => {
      const abortController = new AbortController();
      this.abortControllers.set(key, abortController);

      // Create pending request entry for deduplication
      const pendingRequest: PendingRequest = {
        promise: null as unknown as Promise<TileLoadResult>, // Will be set below
        subscribers: [resolve],
        abortController,
      };
      this.pendingRequests.set(key, pendingRequest);

      const queuedTile: QueuedTile = {
        x,
        y,
        resolve: (result) => {
          // Resolve all subscribers when the request completes
          const subscribers = this.pendingRequests.get(key)?.subscribers || [];
          this.pendingRequests.delete(key);
          subscribers.forEach((sub) => sub(result));
        },
        reject,
        abortController,
      };

      this.queue.push(queuedTile);
      this.processQueue();
    });
  }

  /**
   * Cancel a pending tile request.
   */
  cancelTile(x: number, y: number): void {
    const key = this.getKey(x, y);
    const controller = this.abortControllers.get(key);
    if (controller) {
      controller.abort();
      this.abortControllers.delete(key);
    }

    // Settle anyone waiting on this key BEFORE dropping the entry.
    //
    // The queued item's resolve closure reads its subscriber list back out of
    // pendingRequests, so deleting first left that lookup returning undefined
    // and nobody was ever resolved: the promise loadTile handed out never
    // settled, so the caller's .then/.catch never ran and the tile stayed in
    // its loading set forever, skipped by every later pass. Nothing surfaced
    // it — no error, no log, just a tile that never appears.
    const pending = this.pendingRequests.get(key);
    if (pending) {
      this.pendingRequests.delete(key);
      pending.subscribers.forEach((sub) => sub(TILE_CANCELLED));
    }

    // Remove from queue if not yet started
    this.queue = this.queue.filter((item) => !(item.x === x && item.y === y));
  }

  /**
   * Cancel all pending tile requests.
   */
  cancelAll(): void {
    // Abort all active requests
    for (const controller of this.abortControllers.values()) {
      controller.abort();
    }
    this.abortControllers.clear();

    // Clear all pending request tracking
    this.pendingRequests.clear();

    // Reject all queued items
    for (const item of this.queue) {
      item.reject(new Error("Cancelled"));
    }
    this.queue = [];
  }

  /**
   * Cancel tiles that are no longer in the visible set.
   */
  cancelNotIn(visibleTiles: Set<string>): void {
    // Cancel queued tiles not in visible set
    const toCancel = this.queue.filter((item) => !visibleTiles.has(this.getKey(item.x, item.y)));

    for (const item of toCancel) {
      this.cancelTile(item.x, item.y);
    }
  }

  private async processQueue(): Promise<void> {
    while (this.queue.length > 0 && this.activeCount < MAX_CONCURRENT) {
      const item = this.queue.shift();
      if (!item) break;

      const key = this.getKey(item.x, item.y);

      // Check if already aborted (e.g., cancelled while in queue)
      if (item.abortController.signal.aborted) {
        this.abortControllers.delete(key);
        item.resolve(TILE_CANCELLED); // Must resolve so caller knows to retry
        continue;
      }

      this.activeCount++;

      try {
        const pixelData = await this.fetchTile(item.x, item.y, item.abortController.signal);
        item.resolve(pixelData);
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          // Request was cancelled - return special symbol so caller knows to retry later
          item.resolve(TILE_CANCELLED);
        } else {
          item.reject(error as Error);
        }
      } finally {
        this.activeCount--;
        this.abortControllers.delete(key);
        // Process next item in queue
        this.processQueue();
      }
    }
  }

  private async fetchTile(x: number, y: number, signal: AbortSignal): Promise<Uint8Array | null> {
    const response = await fetch(`${API_BASE_URL}/api/tiles/${x}/${y}`, {
      signal,
      // "no-cache", not "no-store": still never shows a stale tile, because the
      // browser always revalidates — but the server answers 304 from the tile's
      // version ETag when nothing changed, instead of resending 3072 bytes.
      // "no-store" skipped the cache entirely and made every revalidation a
      // full download.
      cache: "no-cache",
    });

    if (response.status === 404) {
      return null;
    }

    if (!response.ok) {
      throw new Error(`Failed to get tile: ${response.status}`);
    }

    const buffer = await response.arrayBuffer();
    return new Uint8Array(buffer);
  }

  /**
   * Get number of pending requests (queued + active).
   */
  get pendingCount(): number {
    return this.queue.length + this.activeCount;
  }
}

// Singleton instance
export const tileLoader = new TileLoader();
