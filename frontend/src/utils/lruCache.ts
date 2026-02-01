/**
 * Simple LRU (Least Recently Used) cache implementation.
 * When the cache exceeds maxSize, the least recently accessed items are evicted.
 */
export class LRUCache<K, V> {
  private cache = new Map<K, V>();
  private maxSize: number;

  constructor(maxSize: number) {
    this.maxSize = maxSize;
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
    // If key exists, delete it first (to update position)
    if (this.cache.has(key)) {
      this.cache.delete(key);
    }

    // Add the new item
    this.cache.set(key, value);

    // Evict oldest items if over capacity
    while (this.cache.size > this.maxSize) {
      // Map preserves insertion order, so first key is oldest
      const oldestKey = this.cache.keys().next().value;
      if (oldestKey !== undefined) {
        this.cache.delete(oldestKey);
      }
    }
  }

  has(key: K): boolean {
    return this.cache.has(key);
  }

  delete(key: K): boolean {
    return this.cache.delete(key);
  }

  clear(): void {
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
