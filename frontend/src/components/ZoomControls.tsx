import * as Slider from "@radix-ui/react-slider";
import { ZoomIn, ZoomOut, Maximize } from "lucide-react";
import "./ZoomControls.css";

interface ZoomControlsProps {
  zoom: number;
  minZoom: number;
  maxZoom: number;
  onZoomChange: (zoom: number) => void;
  onReset: () => void;
}

// Step size for zoom buttons (5% on the logarithmic scale)
const ZOOM_STEP = 5;

export function ZoomControls({
  zoom,
  minZoom,
  maxZoom,
  onZoomChange,
  onReset,
}: ZoomControlsProps) {
  // Use logarithmic scale for percentage so equal % changes = equal visual changes
  // This maps the exponential zoom range to a linear 0-100 scale
  const logMin = Math.log(minZoom);
  const logMax = Math.log(maxZoom);
  const logZoom = Math.log(zoom);
  const normalizedZoom = ((logZoom - logMin) / (logMax - logMin)) * 100;

  // Convert normalized percentage back to zoom value
  const normalizedToZoom = (normalized: number) => {
    const logValue = logMin + (normalized / 100) * (logMax - logMin);
    return Math.exp(logValue);
  };

  const handleSliderChange = (value: number[]) => {
    onZoomChange(normalizedToZoom(value[0]));
  };

  // 5% increments on the logarithmic scale (consistent visual steps)
  const handleZoomIn = () => {
    const newNormalized = Math.min(normalizedZoom + ZOOM_STEP, 100);
    onZoomChange(normalizedToZoom(newNormalized));
  };

  const handleZoomOut = () => {
    const newNormalized = Math.max(normalizedZoom - ZOOM_STEP, 0);
    onZoomChange(normalizedToZoom(newNormalized));
  };

  return (
    <div className="zoom-controls glass-panel">
      <button
        className="zoom-controls__btn"
        onClick={handleZoomIn}
        title="Zoom in"
      >
        <ZoomIn size={18} />
      </button>

      <Slider.Root
        className="zoom-controls__slider"
        orientation="vertical"
        value={[normalizedZoom]}
        onValueChange={handleSliderChange}
        min={0}
        max={100}
        step={1}
      >
        <Slider.Track className="zoom-controls__track">
          <Slider.Range className="zoom-controls__range" />
        </Slider.Track>
        <Slider.Thumb className="zoom-controls__thumb" aria-label="Zoom level" />
      </Slider.Root>

      <button
        className="zoom-controls__btn"
        onClick={handleZoomOut}
        title="Zoom out"
      >
        <ZoomOut size={18} />
      </button>

      <span className="zoom-controls__label">{Math.round(normalizedZoom)}%</span>

      <button
        className="zoom-controls__btn zoom-controls__btn--reset"
        onClick={onReset}
        title="Fit to screen"
      >
        <Maximize size={16} />
      </button>
    </div>
  );
}
