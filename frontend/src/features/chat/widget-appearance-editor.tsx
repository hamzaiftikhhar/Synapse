"use client";

import { useRef, type PointerEvent } from "react";
import { toast } from "sonner";
import { ImagePlus, Pipette, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { WidgetPreview } from "@/features/chat/widget-preview";
import {
  COLOR_PRESETS,
  MAX_AVATAR_ZOOM,
  MAX_WIDGET_RADIUS,
  MIN_AVATAR_ZOOM,
  MIN_WIDGET_RADIUS,
  clampAvatarOffset,
  clampAvatarZoom,
  clampWidgetRadius,
  parseHexColor,
  readAvatarFile,
  type WidgetAppearance,
} from "@/features/chat/widget-theme";
import { cn } from "@/lib/utils";

function ColorPickerControl({
  color,
  onChange,
  label = "Custom",
}: {
  color: string;
  onChange: (hex: string) => void;
  label?: string;
}) {
  const hex = parseHexColor(color) ?? "#5b21b6";
  return (
    <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-full border border-border bg-background px-2 pr-3 text-xs font-medium shadow-sm hover:bg-muted">
      <span
        className="relative size-6 overflow-hidden rounded-md border border-black/10"
        style={{
          backgroundImage:
            "linear-gradient(45deg, #d4d4d8 25%, transparent 25%), linear-gradient(-45deg, #d4d4d8 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #d4d4d8 75%), linear-gradient(-45deg, transparent 75%, #d4d4d8 75%)",
          backgroundSize: "8px 8px",
          backgroundPosition: "0 0, 0 4px, 4px -4px, -4px 0",
        }}
      >
        <span className="absolute inset-0" style={{ backgroundColor: hex }} />
        <input
          type="color"
          value={hex}
          onChange={(e) => onChange(e.target.value)}
          className="absolute -left-1/2 -top-1/2 h-[200%] w-[200%] cursor-pointer opacity-0"
          aria-label={label}
        />
      </span>
      <Pipette className="size-3.5 text-muted-foreground" />
      {label}
    </label>
  );
}

function AvatarCrop({
  value,
  onChange,
}: {
  value: WidgetAppearance;
  onChange: (next: WidgetAppearance) => void;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    x: number;
    y: number;
    ox: number;
    oy: number;
  } | null>(null);

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = {
      x: e.clientX,
      y: e.clientY,
      ox: value.avatarOffsetX,
      oy: value.avatarOffsetY,
    };
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    if (!drag.current || !frameRef.current) return;
    const size = frameRef.current.clientWidth || 96;
    const dx = ((e.clientX - drag.current.x) / size) * 100;
    const dy = ((e.clientY - drag.current.y) / size) * 100;
    onChange({
      ...value,
      avatarOffsetX: clampAvatarOffset(drag.current.ox + dx),
      avatarOffsetY: clampAvatarOffset(drag.current.oy + dy),
    });
  }

  function onPointerUp() {
    drag.current = null;
  }

  const zoomPct = Math.round(value.avatarZoom * 100);

  return (
    <div className="space-y-3 rounded-xl border border-border bg-muted/20 p-3">
      <div className="flex items-center gap-3">
        <div
          ref={frameRef}
          className="relative size-24 shrink-0 cursor-grab overflow-hidden rounded-full border border-black/10 bg-muted active:cursor-grabbing"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={value.avatarUrl}
            alt=""
            draggable={false}
            className="pointer-events-none select-none"
            style={{
              position: "absolute",
              left: `${50 + value.avatarOffsetX}%`,
              top: `${50 + value.avatarOffsetY}%`,
              width: `${value.avatarZoom * 100}%`,
              height: `${value.avatarZoom * 100}%`,
              maxWidth: "none",
              transform: "translate(-50%, -50%)",
              objectFit: "cover",
            }}
          />
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="avatar-zoom" className="text-xs">
              Zoom
            </Label>
            <span className="text-[11px] tabular-nums text-muted-foreground">{zoomPct}%</span>
          </div>
          <input
            id="avatar-zoom"
            type="range"
            min={MIN_AVATAR_ZOOM}
            max={MAX_AVATAR_ZOOM}
            step={0.1}
            value={value.avatarZoom}
            onChange={(e) =>
              onChange({ ...value, avatarZoom: clampAvatarZoom(Number(e.target.value)) })
            }
            className="synapse-range w-full"
            style={{
              ["--synapse-range-pct" as string]: `${((value.avatarZoom - MIN_AVATAR_ZOOM) / (MAX_AVATAR_ZOOM - MIN_AVATAR_ZOOM)) * 100}%`,
            }}
          />
          <p className="text-[11px] text-muted-foreground">Drag the preview to reposition.</p>
        </div>
      </div>
    </div>
  );
}

export function WidgetAppearanceEditor({
  value,
  onChange,
  clinicName,
  greeting,
}: {
  value: WidgetAppearance;
  onChange: (next: WidgetAppearance) => void;
  clinicName?: string;
  greeting?: string;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const brand = parseHexColor(value.primaryColor) ?? value.primaryColor;
  const radiusPct =
    ((value.cornerRadius - MIN_WIDGET_RADIUS) /
      (MAX_WIDGET_RADIUS - MIN_WIDGET_RADIUS)) *
    100;
  const textMode =
    value.textColor === "auto"
      ? "auto"
      : value.textColor === "#ffffff" || value.textColor === "#fff"
        ? "white"
        : value.textColor === "#0b0e2e" || value.textColor === "#000000"
          ? "black"
          : "custom";

  async function onAvatar(file: File | undefined) {
    if (!file) return;
    try {
      const avatarUrl = await readAvatarFile(file);
      onChange({
        ...value,
        avatarUrl,
        avatarZoom: 1,
        avatarOffsetX: 0,
        avatarOffsetY: 0,
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't use that image.");
    }
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card">
      <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(260px,340px)]">
        <div className="space-y-6 p-5">
          <div className="space-y-2.5">
            <Label>Brand color</Label>
            <div className="flex flex-wrap items-center gap-2">
              {COLOR_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  aria-label={`Use ${preset}`}
                  aria-pressed={brand === preset}
                  onClick={() => onChange({ ...value, primaryColor: preset })}
                  className={cn(
                    "size-8 rounded-full border border-black/10 shadow-sm ring-2 ring-offset-2 ring-offset-background transition-shadow",
                    brand === preset ? "ring-foreground" : "ring-transparent"
                  )}
                  style={{ backgroundColor: preset }}
                />
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ColorPickerControl
                color={brand}
                onChange={(hex) => onChange({ ...value, primaryColor: hex })}
              />
              <Input
                value={value.primaryColor}
                onChange={(e) => onChange({ ...value, primaryColor: e.target.value })}
                className="h-9 w-28 font-mono text-xs"
                aria-label="Brand color hex"
              />
            </div>
          </div>

          <div className="space-y-2.5">
            <Label>Text on brand color</Label>
            <div className="flex flex-wrap items-center gap-2">
              {(
                [
                  { id: "auto", label: "Auto" },
                  { id: "black", label: "Black", color: "#0b0e2e" },
                  { id: "white", label: "White", color: "#ffffff" },
                ] as const
              ).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() =>
                    onChange({
                      ...value,
                      textColor: opt.id === "auto" ? "auto" : opt.color,
                    })
                  }
                  className={cn(
                    "inline-flex h-9 items-center gap-2 rounded-full border px-3 text-xs font-medium",
                    textMode === opt.id
                      ? "border-foreground bg-foreground text-background"
                      : "border-border bg-background hover:bg-muted"
                  )}
                >
                  {"color" in opt ? (
                    <span
                      className="size-3.5 rounded-full border border-black/15"
                      style={{ backgroundColor: opt.color }}
                    />
                  ) : null}
                  {opt.label}
                </button>
              ))}
              <ColorPickerControl
                color={textMode === "custom" ? value.textColor : "#f4f1ea"}
                onChange={(hex) => onChange({ ...value, textColor: hex })}
                label="Custom text"
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Auto picks black or white. Override if a logo color needs a different contrast.
            </p>
          </div>

          <div className="space-y-2.5">
            <Label htmlFor="widget-radius">Corner radius</Label>
            <div className="flex items-center gap-3">
              <input
                id="widget-radius"
                type="range"
                min={MIN_WIDGET_RADIUS}
                max={MAX_WIDGET_RADIUS}
                value={value.cornerRadius}
                onChange={(e) =>
                  onChange({ ...value, cornerRadius: clampWidgetRadius(Number(e.target.value)) })
                }
                className="synapse-range min-w-0 flex-1"
                style={{ ["--synapse-range-pct" as string]: `${radiusPct}%` }}
              />
              <div className="flex h-9 items-center rounded-lg border border-border bg-background pl-2">
                <input
                  type="number"
                  min={MIN_WIDGET_RADIUS}
                  max={MAX_WIDGET_RADIUS}
                  value={value.cornerRadius}
                  onChange={(e) =>
                    onChange({
                      ...value,
                      cornerRadius: clampWidgetRadius(Number(e.target.value)),
                    })
                  }
                  className="w-12 bg-transparent text-sm tabular-nums outline-none"
                  aria-label="Corner radius in pixels"
                />
                <span className="pr-2.5 text-xs text-muted-foreground">px</span>
              </div>
            </div>
            <div className="flex justify-between text-[11px] text-muted-foreground">
              <span>Sharp</span>
              <span>Round</span>
            </div>
          </div>

          <div className="space-y-2.5">
            <Label>Chat icon</Label>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileRef.current?.click()}
              >
                <ImagePlus className="size-3.5" />
                {value.avatarUrl ? "Replace image" : "Upload image"}
              </Button>
              {value.avatarUrl ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    onChange({
                      ...value,
                      avatarUrl: "",
                      avatarZoom: 1,
                      avatarOffsetX: 0,
                      avatarOffsetY: 0,
                    })
                  }
                >
                  <X className="size-3.5" />
                  Remove
                </Button>
              ) : null}
            </div>
            {value.avatarUrl ? (
              <AvatarCrop value={value} onChange={onChange} />
            ) : (
              <p className="text-xs text-muted-foreground">
                PNG, JPG, or WebP. After upload you can zoom and drag to frame it.
              </p>
            )}
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => {
                void onAvatar(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </div>
        </div>

        <div className="border-t border-border bg-muted/30 p-4 lg:border-t-0 lg:border-l">
          <p className="mb-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Live preview
          </p>
          <WidgetPreview
            appearance={value}
            clinicName={clinicName}
            greeting={greeting}
          />
        </div>
      </div>
    </div>
  );
}
