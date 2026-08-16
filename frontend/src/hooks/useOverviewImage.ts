import { useCallback, useEffect, useRef, useState } from "react";
import { loadOverviewImage, getOverviewVersion } from "../api/chunks";
import type { RenderLevel } from "../config";
import type { OverviewUpdatedMessage } from "../types";

/**
 * Minimum gap between overview refetches, in milliseconds.
 *
 * The overview is ~0.5 MiB and `overview_updated` is a global broadcast, so
 * refetching on every message meant every connected client re-downloaded the
 * whole mosaic after every single edit anyone made. At Level 0 one tile is
 * about two pixels — nobody can see an individual edit land — so trading some
 * latency for that bandwidth costs nothing visible.
 */
const OVERVIEW_REFRESH_DEBOUNCE_MS = 12000;

interface UseOverviewImageOptions {
  /** Current render level; the overview is only refreshed while this is 0. */
  renderLevel: RenderLevel;
  overviewUpdate?: OverviewUpdatedMessage | null;
  onOverviewUpdateProcessed?: () => void;
  onOverviewLoad?: (image: HTMLImageElement) => void;
}

/**
 * Owns the Level-0 overview image: initial load, and debounced refreshes that
 * only happen while the overview is actually on screen.
 *
 * At Levels 1 and 2 the overview is just a blurry backdrop behind sharper chunk
 * and tile layers, so a newer copy changes nothing the user can see. Updates
 * that arrive there are remembered, not fetched, and applied on return to
 * Level 0.
 */
export function useOverviewImage({
  renderLevel,
  overviewUpdate,
  onOverviewUpdateProcessed,
  onOverviewLoad,
}: UseOverviewImageOptions): HTMLImageElement | null {
  const [overview, setOverview] = useState<HTMLImageElement | null>(null);

  const loadedVersionRef = useRef(-1);
  const pendingVersionRef = useRef<number | null>(null);
  const lastLoadAtRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const hasLoadedOnceRef = useRef(false);

  // Held in refs so a new callback identity doesn't restart the debounce, and
  // so a queued timer can see the level the user is on when it actually fires.
  const onOverviewLoadRef = useRef(onOverviewLoad);
  const renderLevelRef = useRef(renderLevel);
  useEffect(() => {
    onOverviewLoadRef.current = onOverviewLoad;
    renderLevelRef.current = renderLevel;
  }, [onOverviewLoad, renderLevel]);

  const load = useCallback(async (version: number) => {
    try {
      const img = await loadOverviewImage(version >= 0 ? version : undefined);
      lastLoadAtRef.current = Date.now();
      loadedVersionRef.current = version;
      setOverview(img);
      onOverviewLoadRef.current?.(img);
    } catch (error) {
      console.error("Failed to load overview:", error);
    }
  }, []);

  /** Fetch the newest known version, no sooner than the debounce allows. */
  const scheduleRefresh = useCallback(() => {
    if (timerRef.current !== null) return; // already queued; it reads the latest
    if (renderLevel !== 0) return; // not visible — wait until it is
    const pending = pendingVersionRef.current;
    if (pending === null || pending <= loadedVersionRef.current) return;

    const elapsed = Date.now() - lastLoadAtRef.current;
    const delay = Math.max(0, OVERVIEW_REFRESH_DEBOUNCE_MS - elapsed);

    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      // Zoomed away while we waited: keep the pending version for the next
      // return to Level 0 rather than spending the download now.
      if (renderLevelRef.current !== 0) return;

      const version = pendingVersionRef.current;
      if (version !== null && version > loadedVersionRef.current) {
        pendingVersionRef.current = null;
        void load(version);
      }
    }, delay);
  }, [renderLevel, load]);

  // Initial load on mount
  useEffect(() => {
    if (hasLoadedOnceRef.current) return;
    hasLoadedOnceRef.current = true;

    (async () => {
      try {
        const versionInfo = await getOverviewVersion();
        await load(versionInfo.version);
      } catch (error) {
        console.error("Failed to load overview:", error);
      }
    })();
  }, [load]);

  // Record incoming updates; fetch only if we are at Level 0.
  useEffect(() => {
    if (!overviewUpdate) return;

    const { version } = overviewUpdate;
    if (version > (pendingVersionRef.current ?? -1)) {
      pendingVersionRef.current = version;
    }
    onOverviewUpdateProcessed?.();

    scheduleRefresh();
  }, [overviewUpdate, onOverviewUpdateProcessed, scheduleRefresh]);

  // Returning to Level 0 picks up whatever arrived while we were zoomed in.
  useEffect(() => {
    scheduleRefresh();
  }, [scheduleRefresh]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  return overview;
}
