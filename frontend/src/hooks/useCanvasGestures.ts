import { useEffect, useRef } from "react";

/**
 * Touch gestures for the mosaic canvas: one finger pans, two pinch, a tap acts.
 *
 * Lives in a hook rather than inline in `MosaicCanvas` because that file is
 * already ~950 lines and CLAUDE.md says to extract rather than grow it.
 *
 * The listeners are registered natively with `{ passive: false }`, following
 * `PixelCanvas.tsx`. React registers touch listeners as passive, so
 * `preventDefault()` from a React `onTouchMove` is ignored and the page scrolls
 * out from under the finger.
 */

/**
 * Movement allowed during a tap, in CSS pixels.
 *
 * The mouse path uses 5 px, which is a mouse number. Thumbs routinely travel
 * 8-12 px during what the user experiences as a tap, so touch gets its own
 * threshold rather than sharing that constant.
 *
 * Measured as the *maximum* distance from the start point, not the distance at
 * release: a finger that loops out and comes back is a drag, and a
 * distance-at-release test would call it a tap.
 */
const TAP_MAX_TRAVEL_PX = 10;

/** Longest a touch can last and still count as a tap. */
const TAP_MAX_DURATION_MS = 500;

/** Window and slop for pairing two taps into a double tap. */
const DOUBLE_TAP_MAX_GAP_MS = 300;
const DOUBLE_TAP_MAX_DIST_PX = 30;

interface Point {
  x: number;
  y: number;
}

export interface CanvasGestureHandlers {
  /** Pan by a screen-pixel delta. Matches `useViewport`'s `pan`. */
  pan: (deltaX: number, deltaY: number) => void;
  /**
   * Zoom by an incremental factor about a canvas-relative point.
   * Matches `useViewport`'s `zoomAt`, which multiplies the current zoom.
   */
  zoomAt: (canvasX: number, canvasY: number, factor: number) => void;
  /** A tap that was not a drag. Client coordinates. */
  onTap?: (clientX: number, clientY: number) => void;
  /** Two taps in quick succession at the same spot. Client coordinates. */
  onDoubleTap?: (clientX: number, clientY: number) => void;
  /**
   * Called as soon as a gesture actually moves the viewport, so the caller can
   * record that the view is now the user's. Without it the next orientation
   * change snaps the mosaic back to fit-to-screen.
   */
  onViewportGesture?: () => void;
}

const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);
const midpoint = (a: Point, b: Point): Point => ({
  x: (a.x + b.x) / 2,
  y: (a.y + b.y) / 2,
});
const touchPoint = (t: Touch): Point => ({ x: t.clientX, y: t.clientY });

export function useCanvasGestures(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  handlers: CanvasGestureHandlers
) {
  // Held in a ref so the effect below can stay mounted for the life of the
  // canvas. Re-registering these listeners on every viewport change would drop
  // gesture state mid-pinch — and `pan`/`zoomAt` change identity on every pan
  // and every zoom, which is to say constantly during a gesture.
  //
  // Updated in an effect rather than during render: a render can be discarded
  // or replayed under concurrent rendering, and a ref written during one would
  // keep whatever the abandoned attempt put there.
  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Reference state for the in-flight gesture.
    let lastPanPoint: Point | null = null;
    let lastPinchDistance: number | null = null;
    let lastPinchMidpoint: Point | null = null;

    // Tap candidacy for the current touch, or null once disqualified.
    let tapStart: { point: Point; time: number } | null = null;
    let tapMaxTravel = 0;

    let lastTap: { point: Point; time: number } | null = null;

    const canvasPoint = (p: Point): Point => {
      const rect = canvas.getBoundingClientRect();
      return { x: p.x - rect.left, y: p.y - rect.top };
    };

    /**
     * Seed the reference state from whatever fingers are currently down.
     *
     * Called on every touch start and end rather than only at the beginning of
     * a gesture. Lifting one finger of a pinch must continue as a pan from the
     * remaining finger's *current* position; carrying the stale reference over
     * would apply the gap between the two as a single pan delta and the mosaic
     * would jump.
     */
    const reseed = (touches: TouchList) => {
      if (touches.length >= 2) {
        const a = touchPoint(touches[0]);
        const b = touchPoint(touches[1]);
        lastPinchDistance = distance(a, b);
        lastPinchMidpoint = midpoint(a, b);
        lastPanPoint = null;
      } else if (touches.length === 1) {
        lastPanPoint = touchPoint(touches[0]);
        lastPinchDistance = null;
        lastPinchMidpoint = null;
      } else {
        lastPanPoint = null;
        lastPinchDistance = null;
        lastPinchMidpoint = null;
      }
    };

    const handleTouchStart = (e: TouchEvent) => {
      e.preventDefault();

      if (e.touches.length === 1) {
        const p = touchPoint(e.touches[0]);
        tapStart = { point: p, time: e.timeStamp };
        tapMaxTravel = 0;
      } else {
        // A second finger means this was never a tap.
        tapStart = null;
      }

      reseed(e.touches);
    };

    const handleTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      const { pan, zoomAt, onViewportGesture } = handlersRef.current;

      if (e.touches.length >= 2) {
        const a = touchPoint(e.touches[0]);
        const b = touchPoint(e.touches[1]);
        const dist = distance(a, b);
        const mid = midpoint(a, b);

        if (lastPinchDistance === null || lastPinchMidpoint === null) {
          // Finger count changed since the last move; start fresh rather than
          // treating the change itself as gesture input.
          lastPinchDistance = dist;
          lastPinchMidpoint = mid;
          return;
        }

        onViewportGesture?.();

        // The factor is the change since the PREVIOUS move event, not since the
        // gesture began. `zoomAt` multiplies the current zoom, so feeding it a
        // cumulative ratio would compound every frame and the zoom would run
        // away within a few events.
        if (lastPinchDistance > 0 && dist > 0) {
          const factor = dist / lastPinchDistance;
          const c = canvasPoint(mid);
          zoomAt(c.x, c.y, factor);
        }

        // Pan by the midpoint travel in the same event, so the mosaic stays
        // anchored to the fingers rather than only to the zoom origin.
        pan(mid.x - lastPinchMidpoint.x, mid.y - lastPinchMidpoint.y);

        lastPinchDistance = dist;
        lastPinchMidpoint = mid;
        return;
      }

      if (e.touches.length === 1) {
        const p = touchPoint(e.touches[0]);

        if (tapStart) {
          tapMaxTravel = Math.max(tapMaxTravel, distance(p, tapStart.point));
        }

        if (lastPanPoint === null) {
          lastPanPoint = p;
          return;
        }

        onViewportGesture?.();
        pan(p.x - lastPanPoint.x, p.y - lastPanPoint.y);
        lastPanPoint = p;
      }
    };

    const handleTouchEnd = (e: TouchEvent) => {
      // Suppresses the synthesized mouse events (mousedown/click) that would
      // otherwise follow, which would reach the mouse handlers and defeat the
      // zoom gating that decides what a tap means.
      e.preventDefault();

      const { onTap, onDoubleTap } = handlersRef.current;

      const wasTap =
        tapStart !== null &&
        e.touches.length === 0 &&
        tapMaxTravel <= TAP_MAX_TRAVEL_PX &&
        e.timeStamp - tapStart.time <= TAP_MAX_DURATION_MS;

      if (wasTap && tapStart) {
        const p = tapStart.point;
        const isDoubleTap =
          lastTap !== null &&
          e.timeStamp - lastTap.time <= DOUBLE_TAP_MAX_GAP_MS &&
          distance(p, lastTap.point) <= DOUBLE_TAP_MAX_DIST_PX;

        if (isDoubleTap) {
          lastTap = null; // a third tap starts a new pair
          onDoubleTap?.(p.x, p.y);
        } else {
          lastTap = { point: p, time: e.timeStamp };
          onTap?.(p.x, p.y);
        }
      }

      if (e.touches.length === 0) {
        tapStart = null;
        tapMaxTravel = 0;
      }

      reseed(e.touches);
    };

    const handleTouchCancel = (e: TouchEvent) => {
      // iOS fires this for system gestures, incoming calls and notifications.
      // Without it the gesture state survives a cancellation and the next touch
      // resumes from a stale reference point.
      tapStart = null;
      tapMaxTravel = 0;
      reseed(e.touches);
    };

    // Safari's proprietary gesture events fire *in addition* to touch events
    // during a pinch. Left alone they zoom the whole page on top of the canvas
    // zoom, which `touch-action: none` does not prevent.
    const preventGesture = (e: Event) => e.preventDefault();

    canvas.addEventListener("touchstart", handleTouchStart, { passive: false });
    canvas.addEventListener("touchmove", handleTouchMove, { passive: false });
    canvas.addEventListener("touchend", handleTouchEnd, { passive: false });
    canvas.addEventListener("touchcancel", handleTouchCancel, { passive: false });
    canvas.addEventListener("gesturestart", preventGesture, { passive: false });
    canvas.addEventListener("gesturechange", preventGesture, { passive: false });
    canvas.addEventListener("gestureend", preventGesture, { passive: false });

    return () => {
      canvas.removeEventListener("touchstart", handleTouchStart);
      canvas.removeEventListener("touchmove", handleTouchMove);
      canvas.removeEventListener("touchend", handleTouchEnd);
      canvas.removeEventListener("touchcancel", handleTouchCancel);
      canvas.removeEventListener("gesturestart", preventGesture);
      canvas.removeEventListener("gesturechange", preventGesture);
      canvas.removeEventListener("gestureend", preventGesture);
    };
  }, [canvasRef]);
}
