import "./ColorPicker.css";

interface ColorPickerProps {
  color: string;
  onChange: (color: string) => void;
}

// Preset color palette
const PALETTE_COLORS = [
  // Row 1: Grayscale
  "#000000", // Black
  "#404040", // Dark gray
  "#808080", // Gray
  "#c0c0c0", // Light gray
  "#ffffff", // White
  // Row 2: Warm colors
  "#ff0000", // Red
  "#ff4500", // Orange red
  "#ff8c00", // Dark orange
  "#ffa500", // Orange
  "#ffff00", // Yellow
  // Row 3: Cool colors
  "#00ff00", // Green
  "#00fa9a", // Medium spring green
  "#00ffff", // Cyan
  "#0080ff", // Sky blue
  "#0000ff", // Blue
  // Row 4: Purple/Pink/Brown
  "#8000ff", // Purple
  "#ff00ff", // Magenta
  "#ff69b4", // Hot pink
  "#8b4513", // Saddle brown
  "#d2691e", // Chocolate
];

export function ColorPicker({ color, onChange }: ColorPickerProps) {
  return (
    <div className="color-picker">
      <div className="color-picker-palette">
        {PALETTE_COLORS.map((paletteColor) => (
          <button
            key={paletteColor}
            className={`color-swatch ${color === paletteColor ? "selected" : ""}`}
            style={{ backgroundColor: paletteColor }}
            onClick={() => onChange(paletteColor)}
            title={paletteColor}
            aria-label={`Select color ${paletteColor}`}
          />
        ))}
      </div>
      <div className="color-picker-custom">
        <label className="color-picker-label">
          Custom:
          <input
            type="color"
            value={color}
            onChange={(e) => onChange(e.target.value)}
            className="color-input-native"
          />
        </label>
        <div
          className="color-preview"
          style={{ backgroundColor: color }}
          title={`Current: ${color}`}
        />
      </div>
    </div>
  );
}
