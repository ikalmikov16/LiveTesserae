/**
 * Tile loading queue with concurrency limits and cancellation.
 * Prevents ERR_INSUFFICIENT_RESOURCES by limiting parallel requests.
 */

import { API_BASE_URL } from "../config";

// Maximum concurrent tile fetches (browsers limit to ~6 per origin)
const MAX_CONCURRENT = 6;

interface QueuedTile {
  x: number;
  y: number;
  resolve: (dataUrl: string | null) => void;
  reject: (error: Error) => void;
  abortController: AbortController;
}

class TileLoader {
  private queue: QueuedTile[] = [];
  private activeCount = 0;
  private abortControllers = new Map<string, AbortController>();

  private getKey(x: number, y: number): string {
    return `${x}:${y}`;
  }

  /**
   * Load a tile image. Returns data URL or null if tile doesn't exist.
   * Requests are queued and processed with concurrency limits.
   */
  async loadTile(x: number, y: number): Promise<string | null> {
    const key = this.getKey(x, y);

    // Cancel any existing request for this tile
    const existing = this.abortControllers.get(key);
    if (existing) {
      existing.abort();
      this.abortControllers.delete(key);
    }

    return new Promise((resolve, reject) => {
      const abortController = new AbortController();
      this.abortControllers.set(key, abortController);

      const queuedTile: QueuedTile = {
        x,
        y,
        resolve,
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

      // Check if already aborted
      if (item.abortController.signal.aborted) {
        this.abortControllers.delete(key);
        continue;
      }

      this.activeCount++;

      try {
        const dataUrl = await this.fetchTile(item.x, item.y, item.abortController.signal);
        item.resolve(dataUrl);
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          // Request was cancelled, don't reject
          item.resolve(null);
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

  private async fetchTile(x: number, y: number, signal: AbortSignal): Promise<string | null> {
    const response = await fetch(`${API_BASE_URL}/api/tiles/${x}/${y}`, {
      signal,
    });

    if (response.status === 404) {
      return null;
    }

    if (!response.ok) {
      throw new Error(`Failed to get tile: ${response.status}`);
    }

    const blob = await response.blob();

    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
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
