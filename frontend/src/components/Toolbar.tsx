import * as ToggleGroup from "@radix-ui/react-toggle-group";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Pencil, PaintBucket, Eraser, Pipette, Undo2, Redo2, Trash2, Grid3X3 } from "lucide-react";
import "./Toolbar.css";

export type Tool = "pencil" | "fill" | "eraser" | "eyedropper";

interface ToolbarProps {
  tool: Tool;
  onToolChange: (tool: Tool) => void;
  canUndo?: boolean;
  canRedo?: boolean;
  onUndo?: () => void;
  onRedo?: () => void;
  onClear?: () => void;
  showGrid?: boolean;
  onToggleGrid?: () => void;
}

export function Toolbar({
  tool,
  onToolChange,
  canUndo = false,
  canRedo = false,
  onUndo,
  onRedo,
  onClear,
  showGrid = true,
  onToggleGrid,
}: ToolbarProps) {
  return (
    <Tooltip.Provider delayDuration={300}>
      <div className="toolbar">
        <ToggleGroup.Root
          type="single"
          value={tool}
          onValueChange={(value) => value && onToolChange(value as Tool)}
          className="toolbar__tools"
        >
          <ToolButton value="pencil" icon={<Pencil size={14} />} label="Pencil (1)" />
          <ToolButton value="fill" icon={<PaintBucket size={14} />} label="Fill (2)" />
          <ToolButton value="eraser" icon={<Eraser size={14} />} label="Eraser (3)" />
          <ToolButton value="eyedropper" icon={<Pipette size={14} />} label="Eyedropper (4)" />
        </ToggleGroup.Root>

        <ActionButton
          icon={<Grid3X3 size={14} />}
          label="Toggle grid (G)"
          onClick={onToggleGrid}
          active={showGrid}
        />

        <div className="toolbar__divider" />

        <div className="toolbar__actions">
          <ActionButton
            icon={<Undo2 size={14} />}
            label="Undo (⌘Z)"
            onClick={onUndo}
            disabled={!canUndo}
          />
          <ActionButton
            icon={<Redo2 size={14} />}
            label="Redo (⌘⇧Z)"
            onClick={onRedo}
            disabled={!canRedo}
          />
        </div>

        <div className="toolbar__divider" />

        <ActionButton
          icon={<Trash2 size={14} />}
          label="Clear canvas"
          onClick={onClear}
          className="toolbar__btn--danger"
        />
      </div>
    </Tooltip.Provider>
  );
}

function ToolButton({
  value,
  icon,
  label,
}: {
  value: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <ToggleGroup.Item value={value} className="toolbar__btn toolbar__tool-btn">
          {icon}
        </ToggleGroup.Item>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tooltip" sideOffset={5}>
          {label}
          <Tooltip.Arrow className="tooltip__arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  disabled,
  className,
  active,
}: {
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
  active?: boolean;
}) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <button
          className={`toolbar__btn ${active ? "toolbar__btn--active" : ""} ${className || ""}`}
          onClick={onClick}
          disabled={disabled}
        >
          {icon}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tooltip" sideOffset={5}>
          {label}
          <Tooltip.Arrow className="tooltip__arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
