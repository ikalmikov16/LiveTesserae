/**
 * Wheel gesture classification.
 *
 * The mosaic wants three behaviours from one event: a mouse wheel zooms, a
 * trackpad two-finger swipe pans, and a trackpad pinch zooms. Telling them
 * apart is the whole problem.
 *
 * `deltaMode` cannot carry it. Chrome and Safari report `0` for a mouse wheel
 * *and* for a trackpad swipe, so gating zoom on `deltaMode === 1` made wheel
 * zoom Firefox-only — the bug this module exists to fix.
 *
 * `wheelDeltaY` can. It is non-standard and deprecated, but it is the only
 * signal that separates the two on those engines: a real mouse wheel reports
 * multiples of 120 (one notch = 120), while trackpads report the finer,
 * acceleration-scaled values that a physical detent never produces.
 *
 * The delta-shape heuristic this replaces — "deltaX is 0 and deltaY is a large
 * integer" — was rejected in `pre-redeploy-hardening.md` §1.8 as "unsound both
 * ways on macOS", and it is: macOS and Windows both axis-lock trackpad scrolls,
 * so `deltaX === 0` does not identify a mouse, and macOS applies acceleration
 * to mice, so the same wheel clears a magnitude threshold when spun fast and
 * falls under it when spun slowly.
 */

/** One mouse-wheel detent, in `wheelDelta` units. */
const WHEEL_DETENT = 120;

const DELTA_MODE_LINE = 1;
const DELTA_MODE_PAGE = 2;

/**
 * The parts of a `WheelEvent` this decision depends on.
 *
 * Declared structurally so the classifier can be exercised without a DOM.
 * `wheelDeltaY` is absent from the standard `WheelEvent` type because it is
 * non-standard — Firefox does not implement it, which is harmless here since
 * Firefox reports `deltaMode === 1` for a wheel anyway.
 */
export interface WheelLike {
  ctrlKey: boolean;
  metaKey: boolean;
  deltaMode: number;
  deltaX: number;
  deltaY: number;
  wheelDeltaY?: number;
}

export type WheelIntent = "zoom" | "pan";

/**
 * Decide whether a wheel event should zoom the mosaic or pan it.
 *
 * Read `deltaMode` before `deltaX`/`deltaY`: per §1.8, touching the deltas
 * first changes what Firefox reports for the mode.
 */
export function classifyWheel(e: WheelLike): WheelIntent {
  const deltaMode = e.deltaMode;

  // Trackpad pinch arrives as ctrl+wheel. `metaKey` is the deliberate escape
  // hatch: when the heuristic below misfires on hardware we have not seen,
  // Cmd/Ctrl+wheel still zooms.
  if (e.ctrlKey || e.metaKey) return "zoom";

  // Firefox reports line mode for a wheel. Page mode is rare, but it must not
  // fall through to the pan branch, which would feed a page count to a
  // function expecting pixels.
  if (deltaMode === DELTA_MODE_LINE || deltaMode === DELTA_MODE_PAGE) return "zoom";

  const wheelDeltaY = e.wheelDeltaY;
  if (
    typeof wheelDeltaY === "number" &&
    wheelDeltaY !== 0 &&
    Math.abs(wheelDeltaY) % WHEEL_DETENT === 0
  ) {
    return "zoom";
  }

  return "pan";
}
