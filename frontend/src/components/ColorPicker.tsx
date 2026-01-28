import { useState, useEffect } from "react";
import * as Popover from "@radix-ui/react-popover";
import * as Slider from "@radix-ui/react-slider";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Settings2 } from "lucide-react";
import { hexToHsl, hslToHex, isValidHex } from "../utils/color";
import "./ColorPicker.css";

// Quick preset colors - 10 essential pixel art colors
const QUICK_COLORS = [
  "#000000", // Black
  "#FFFFFF", // White
  "#FF0000", // Red
  "#00CC00", // Green
  "#0066FF", // Blue
  "#FFCC00", // Yellow
  "#FF6600", // Orange
  "#CC00FF", // Purple
  "#00CCCC", // Cyan
  "#FF66CC", // Pink
];

// Default custom palette - start empty
const DEFAULT_CUSTOM_PALETTE: (string | null)[] = [
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
];

// Extended palette - organized by hue with better color selection
const EXTENDED_COLORS = [
  // Grayscale (6)
  "#000000",
  "#444444",
  "#888888",
  "#AAAAAA",
  "#DDDDDD",
  "#FFFFFF",
  // Reds (6)
  "#330000",
  "#660000",
  "#CC0000",
  "#FF0000",
  "#FF6666",
  "#FFCCCC",
  // Oranges (6)
  "#331A00",
  "#663300",
  "#CC6600",
  "#FF9900",
  "#FFBB66",
  "#FFE5CC",
  // Yellows (6)
  "#333300",
  "#666600",
  "#CCCC00",
  "#FFFF00",
  "#FFFF66",
  "#FFFFCC",
  // Greens (6)
  "#003300",
  "#006600",
  "#00CC00",
  "#00FF00",
  "#66FF66",
  "#CCFFCC",
  // Cyans (6)
  "#003333",
  "#006666",
  "#00CCCC",
  "#00FFFF",
  "#66FFFF",
  "#CCFFFF",
  // Blues (6)
  "#000033",
  "#000066",
  "#0000CC",
  "#0066FF",
  "#66AAFF",
  "#CCE5FF",
  // Purples (6)
  "#330033",
  "#660066",
  "#9900CC",
  "#CC00FF",
  "#DD66FF",
  "#EECCFF",
  // Magentas (6)
  "#330022",
  "#660044",
  "#CC0088",
  "#FF00CC",
  "#FF66DD",
  "#FFCCEE",
  // Browns/Skin tones (6)
  "#3D2817",
  "#6B4423",
  "#A67C52",
  "#D4A574",
  "#E8C9A0",
  "#F5E6D3",
];

const STORAGE_KEY = "tesserae-custom-palette";

// Load custom palette from localStorage
function loadCustomPalette(): (string | null)[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed) && parsed.length === 10) {
        return parsed;
      }
    }
  } catch {
    // Ignore errors
  }
  return [...DEFAULT_CUSTOM_PALETTE];
}

// Save custom palette to localStorage
function saveCustomPalette(palette: (string | null)[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(palette));
  } catch {
    // Ignore errors
  }
}

interface ColorPickerProps {
  color: string;
  onChange: (color: string) => void;
  recentColors?: string[];
}

export function ColorPicker({ color, onChange, recentColors = [] }: ColorPickerProps) {
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [hexInput, setHexInput] = useState(color.toUpperCase());
  const [customPalette, setCustomPalette] = useState<(string | null)[]>(loadCustomPalette);
  const [editingSlot, setEditingSlot] = useState<number | null>(null);
  // Preview color for sliders - only committed when popover closes
  const [previewColor, setPreviewColor] = useState<string | null>(null);

  // Sync hex input when color changes externally
  useEffect(() => {
    setHexInput(color.toUpperCase());
  }, [color]);

  // Initialize preview color when opening advanced picker
  useEffect(() => {
    if (isAdvancedOpen) {
      setPreviewColor(color.toUpperCase());
    }
  }, [isAdvancedOpen, color]);

  // Parse color to HSL for sliders - use preview color when available
  const displayColor = previewColor || color;
  const hsl = hexToHsl(displayColor);

  const handleHexSubmit = () => {
    const normalized = hexInput.startsWith("#") ? hexInput : `#${hexInput}`;
    if (isValidHex(normalized)) {
      const upperColor = normalized.toUpperCase();
      // In advanced picker, just update preview (will commit on close)
      if (isAdvancedOpen) {
        setPreviewColor(upperColor);
      } else {
        handleColorSelect(upperColor);
      }
    } else {
      setHexInput(displayColor.toUpperCase());
    }
  };

  // Assign color to editing slot
  const assignToEditingSlot = (newColor: string) => {
    if (editingSlot === null) return;

    const upperColor = newColor.toUpperCase();
    const newPalette = [...customPalette];
    newPalette[editingSlot] = upperColor;
    setCustomPalette(newPalette);
    saveCustomPalette(newPalette);
    setEditingSlot(null);
    setIsAdvancedOpen(false);
  };

  const handleColorSelect = (newColor: string) => {
    const upperColor = newColor.toUpperCase();

    // If we're editing a custom slot, assign the color to that slot
    if (editingSlot !== null) {
      assignToEditingSlot(upperColor);
    }

    // Always set as current color
    onChange(upperColor);
    setHexInput(upperColor);
  };

  const handleSliderChange = (newHsl: { h: number; s: number; l: number }) => {
    const newColor = hslToHex(newHsl).toUpperCase();
    // Only update preview - don't commit to recents yet
    setPreviewColor(newColor);
    setHexInput(newColor);
  };

  // Handle closing the advanced picker - commit the preview color
  const handleAdvancedOpenChange = (open: boolean) => {
    if (!open && previewColor && previewColor !== color.toUpperCase()) {
      // Closing the popover - commit the preview color
      if (editingSlot !== null) {
        // Save to custom palette
        const newPalette = [...customPalette];
        newPalette[editingSlot] = previewColor;
        setCustomPalette(newPalette);
        saveCustomPalette(newPalette);
        setEditingSlot(null);
      }
      // Set as current color and add to recents
      onChange(previewColor);
      setHexInput(previewColor);
    }
    if (!open) {
      setPreviewColor(null);
      // Clear editing state if we didn't commit (e.g., user cancelled without changing)
      if (editingSlot !== null) {
        setEditingSlot(null);
      }
    }
    setIsAdvancedOpen(open);
  };

  // Handle clicking a custom slot
  const handleCustomSlotClick = (index: number) => {
    const slotColor = customPalette[index];

    if (slotColor && editingSlot === null) {
      // If slot has a color and we're not in edit mode, select it for drawing
      onChange(slotColor);
      setHexInput(slotColor);
    } else {
      // If slot is empty or we want to edit, enter edit mode
      setEditingSlot(index);
      setIsAdvancedOpen(true);
    }
  };

  // Handle right-click to edit a slot (even if it has a color)
  const handleCustomSlotEdit = (index: number, e: React.MouseEvent) => {
    e.preventDefault();
    setEditingSlot(index);
    setIsAdvancedOpen(true);
  };

  // Cancel editing
  const cancelEditing = () => {
    setEditingSlot(null);
    setIsAdvancedOpen(false);
  };

  return (
    <Tooltip.Provider delayDuration={300}>
      <div className="color-picker">
        {/* Current color preview with advanced button */}
        <div className="color-picker__current">
          <div className="color-picker__preview" style={{ backgroundColor: displayColor }} />
          <span className="color-picker__hex">{displayColor.toUpperCase()}</span>

          {/* Advanced color picker trigger */}
          <Popover.Root open={isAdvancedOpen} onOpenChange={handleAdvancedOpenChange}>
            <Tooltip.Root>
              <Tooltip.Trigger asChild>
                <Popover.Trigger asChild>
                  <button className="color-picker__advanced-icon-btn" aria-label="Advanced colors">
                    <Settings2 size={16} />
                  </button>
                </Popover.Trigger>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content className="color-picker__tooltip" sideOffset={5}>
                  Advanced Colors
                  <Tooltip.Arrow className="color-picker__tooltip-arrow" />
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>

            <Popover.Portal>
              <Popover.Content
                className="color-picker__popover"
                side="right"
                sideOffset={12}
                align="start"
                alignOffset={-8}
                onInteractOutside={(e) => {
                  // Don't close if clicking on a color swatch (for editing mode)
                  const target = e.target as HTMLElement;
                  if (
                    target.closest(".color-picker__swatch") ||
                    target.closest(".color-picker__cancel-btn")
                  ) {
                    e.preventDefault();
                  }
                }}
              >
                <div className="color-picker__popover-content">
                  {editingSlot !== null && (
                    <div className="color-picker__edit-hint">
                      Pick a color for slot {editingSlot + 1}
                    </div>
                  )}

                  {/* Hue slider */}
                  <div className="color-picker__slider-group">
                    <label className="color-picker__slider-label">Hue</label>
                    <Slider.Root
                      className="color-picker__slider color-picker__hue-slider"
                      value={[hsl.h]}
                      onValueChange={([h]) => handleSliderChange({ ...hsl, h })}
                      min={0}
                      max={360}
                      step={1}
                    >
                      <Slider.Track className="color-picker__track color-picker__hue-track">
                        <Slider.Range />
                      </Slider.Track>
                      <Slider.Thumb className="color-picker__thumb" />
                    </Slider.Root>
                  </div>

                  {/* Saturation slider */}
                  <div className="color-picker__slider-group">
                    <label className="color-picker__slider-label">Saturation</label>
                    <Slider.Root
                      className="color-picker__slider"
                      value={[hsl.s * 100]}
                      onValueChange={([s]) => handleSliderChange({ ...hsl, s: s / 100 })}
                      min={0}
                      max={100}
                      step={1}
                    >
                      <Slider.Track
                        className="color-picker__track"
                        style={{
                          background: `linear-gradient(to right, ${hslToHex({ ...hsl, s: 0 })}, ${hslToHex({ ...hsl, s: 1 })})`,
                        }}
                      >
                        <Slider.Range />
                      </Slider.Track>
                      <Slider.Thumb className="color-picker__thumb" />
                    </Slider.Root>
                  </div>

                  {/* Lightness slider */}
                  <div className="color-picker__slider-group">
                    <label className="color-picker__slider-label">Lightness</label>
                    <Slider.Root
                      className="color-picker__slider"
                      value={[hsl.l * 100]}
                      onValueChange={([l]) => handleSliderChange({ ...hsl, l: l / 100 })}
                      min={0}
                      max={100}
                      step={1}
                    >
                      <Slider.Track
                        className="color-picker__track"
                        style={{
                          background: `linear-gradient(to right, #000, ${hslToHex({ ...hsl, l: 0.5 })}, #fff)`,
                        }}
                      >
                        <Slider.Range />
                      </Slider.Track>
                      <Slider.Thumb className="color-picker__thumb" />
                    </Slider.Root>
                  </div>

                  {/* Hex input */}
                  <div className="color-picker__hex-input-group">
                    <label className="color-picker__slider-label">Hex</label>
                    <input
                      type="text"
                      className="color-picker__hex-input"
                      value={hexInput}
                      onChange={(e) => setHexInput(e.target.value.toUpperCase())}
                      onBlur={handleHexSubmit}
                      onKeyDown={(e) => e.key === "Enter" && handleHexSubmit()}
                      maxLength={7}
                    />
                  </div>

                  {/* Extended palette */}
                  <div className="color-picker__extended">
                    <label className="color-picker__slider-label">Palette</label>
                    <div className="color-picker__extended-grid">
                      {EXTENDED_COLORS.map((c, i) => (
                        <button
                          key={`${c}-${i}`}
                          className={`color-picker__swatch color-picker__swatch--tiny ${c.toUpperCase() === color.toUpperCase() ? "selected" : ""}`}
                          style={{ backgroundColor: c }}
                          onClick={() => handleColorSelect(c)}
                          title={c}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>

        {/* Quick color palette */}
        <div className="color-picker__quick">
          {QUICK_COLORS.map((c) => (
            <button
              key={c}
              className={`color-picker__swatch ${c.toUpperCase() === color.toUpperCase() ? "selected" : ""}`}
              style={{ backgroundColor: c }}
              onClick={() => handleColorSelect(c)}
              title={c}
            />
          ))}
        </div>

        {/* Custom palette - 10 slots */}
        <div className="color-picker__custom-palette">
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <span className="color-picker__label color-picker__label--with-tooltip">
                Custom{" "}
                {editingSlot !== null && (
                  <span className="color-picker__editing-badge">
                    Editing slot {editingSlot + 1}
                  </span>
                )}
              </span>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content className="color-picker__tooltip" sideOffset={5}>
                Click empty slot to set color
                <br />
                Right-click any slot to change it
                <Tooltip.Arrow className="color-picker__tooltip-arrow" />
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>

          <div className="color-picker__custom-colors">
            {customPalette.map((c, i) => {
              // Show preview color in the slot being edited
              const slotColor = editingSlot === i && previewColor ? previewColor : c;
              const isEditing = editingSlot === i;

              return slotColor ? (
                <button
                  key={`custom-${i}`}
                  className={`color-picker__swatch ${slotColor.toUpperCase() === color.toUpperCase() ? "selected" : ""} ${isEditing ? "editing" : ""}`}
                  style={{ backgroundColor: slotColor }}
                  onClick={() => handleCustomSlotClick(i)}
                  onContextMenu={(e) => handleCustomSlotEdit(i, e)}
                  title={slotColor}
                />
              ) : (
                <button
                  key={`custom-empty-${i}`}
                  className={`color-picker__swatch color-picker__swatch--empty ${isEditing ? "editing" : ""}`}
                  onClick={() => handleCustomSlotClick(i)}
                  onContextMenu={(e) => handleCustomSlotEdit(i, e)}
                  title="Click to set color"
                />
              );
            })}
          </div>

          {editingSlot !== null && (
            <button className="color-picker__cancel-btn" onClick={cancelEditing}>
              Cancel
            </button>
          )}
        </div>

        {/* Recent colors - always show 10 slots */}
        <div className="color-picker__recent">
          <span className="color-picker__label">Recent</span>
          <div className="color-picker__recent-colors">
            {Array.from({ length: 10 }).map((_, i) => {
              const c = recentColors[i];
              return c ? (
                <button
                  key={`recent-${i}`}
                  className={`color-picker__swatch ${c.toUpperCase() === color.toUpperCase() ? "selected" : ""}`}
                  style={{ backgroundColor: c }}
                  onClick={() => handleColorSelect(c)}
                  title={c.toUpperCase()}
                />
              ) : (
                <div
                  key={`empty-${i}`}
                  className="color-picker__swatch color-picker__swatch--empty color-picker__swatch--disabled"
                />
              );
            })}
          </div>
        </div>
      </div>
    </Tooltip.Provider>
  );
}
