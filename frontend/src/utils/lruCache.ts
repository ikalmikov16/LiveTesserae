/**
 * Simple LRU (Least Recently Used) cache implementation.
 * When the cache exceeds maxSize, the least recently accessed items are evicted.
 */
export class LRUCache<K, V> {
  private cache = new Map<K, V>();
  private maxSize: number;
  private onEvict?: (value: V, key: K) => void;

  /**
   * @param onEvict Called for every value the cache drops, from any path.
   *   Needed for values that own memory the GC will not reclaim on its own —
   *   an ImageBitmap stays resident until close(). There are five ways a value
   *   leaves this cache and all of them fire this: capacity overflow on set,
   *   replacing an existing key, shrinking via setMaxSize, delete, and clear.
   *   The replace-on-set path is the easiest to overlook and the most often
   *   hit, since every tile update overwrites a key that is already present.
   */
  constructor(maxSize: number, onEvict?: (value: V, key: K) => void) {
    this.maxSize = maxSize;
    this.onEvict = onEvict;
  }

  private evict(key: K): void {
    if (!this.onEvict) {
      this.cache.delete(key);
      return;
    }
    const value = this.cache.get(key);
    this.cache.delete(key);
    if (value !== undefined) this.onEvict(value, key);
  }

  /**
   * Change the capacity, evicting immediately if the cache is now over it.
   *
   * Exists because the tile cache's right size depends on the viewport: a
   * capacity below the number of tiles on screen makes the cache thrash rather
   * than help, so it has to be recomputed when the canvas resizes.
   */
  setMaxSize(maxSize: number): void {
    this.maxSize = maxSize;
    while (this.cache.size > this.maxSize) {
      const oldestKey = this.cache.keys().next().value;
      if (oldestKey === undefined) break;
      this.evict(oldestKey);
    }
  }

  get(key: K): V | undefined {
    const value = this.cache.get(key);
    if (value !== undefined) {
      // Move to end (most recently used)
      this.cache.delete(key);
      this.cache.set(key, value);
    }
    return value;
  }

  set(key: K, value: V): void {
    // If key exists, replace it — releasing the old value, which is not
    // necessarily the same object as the new one.
    if (this.cache.has(key)) {
      if (this.cache.get(key) !== value) {
        this.evict(key);
      } else {
        this.cache.delete(key);
      }
    }

    // Add the new item
    this.cache.set(key, value);

    // Evict oldest items if over capacity
    while (this.cache.size > this.maxSize) {
      // Map preserves insertion order, so first key is oldest
      const oldestKey = this.cache.keys().next().value;
      if (oldestKey === undefined) break;
      this.evict(oldestKey);
    }
  }

  has(key: K): boolean {
    return this.cache.has(key);
  }

  delete(key: K): boolean {
    if (!this.cache.has(key)) return false;
    this.evict(key);
    return true;
  }

  clear(): void {
    if (this.onEvict) {
      for (const key of [...this.cache.keys()]) this.evict(key);
    }
    this.cache.clear();
  }

  get size(): number {
    return this.cache.size;
  }

  /**
   * Iterate over all entries (for drawing, etc.)
   * Does NOT update access order.
   */
  forEach(callback: (value: V, key: K) => void): void {
    this.cache.forEach(callback);
  }

  /**
   * Get all keys (for cleanup operations)
   */
  keys(): IterableIterator<K> {
    return this.cache.keys();
  }
}
