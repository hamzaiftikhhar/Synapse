"use client";

import {
  createContext,
  useContext,
  type CSSProperties,
  type ReactNode,
} from "react";

export const DEFAULT_WIDGET_COLOR = "#5b21b6";
export const DEFAULT_WIDGET_RADIUS = 18;
export const MIN_WIDGET_RADIUS = 0;
export const MAX_WIDGET_RADIUS = 32;
export const MIN_AVATAR_ZOOM = 1;
export const MAX_AVATAR_ZOOM = 3;
export const COLOR_PRESETS = [
  "#5c67f2",
  "#0f766e",
  "#b45309",
  "#1d4ed8",
  "#be123c",
  "#1a1e26",
] as const;

export type WidgetAppearance = {
  primaryColor: string;
  textColor: string;
  cornerRadius: number;
  avatarUrl: string;
  avatarZoom: number;
  avatarOffsetX: number;
  avatarOffsetY: number;
};

export type WidgetThemeValue = WidgetAppearance & {
  resolvedText: string;
};

const defaultAppearance = (): WidgetAppearance => ({
  primaryColor: DEFAULT_WIDGET_COLOR,
  textColor: "auto",
  cornerRadius: DEFAULT_WIDGET_RADIUS,
  avatarUrl: "",
  avatarZoom: 1,
  avatarOffsetX: 0,
  avatarOffsetY: 0,
});

const WidgetThemeContext = createContext<WidgetThemeValue | null>(null);

export function WidgetThemeProvider({
  appearance,
  children,
}: {
  appearance?: WidgetAppearance | null;
  children: ReactNode;
}) {
  const value = appearance
    ? {
        ...appearance,
        resolvedText: resolvedTextColor(appearance.primaryColor, appearance.textColor),
      }
    : null;
  return (
    <WidgetThemeContext.Provider value={value}>{children}</WidgetThemeContext.Provider>
  );
}

export function useWidgetTheme() {
  return useContext(WidgetThemeContext);
}

export function useWidgetAvatarUrl(override?: string) {
  const theme = useContext(WidgetThemeContext);
  return override || theme?.avatarUrl || "";
}

export function clampWidgetRadius(value: number | undefined | null): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return DEFAULT_WIDGET_RADIUS;
  return Math.min(MAX_WIDGET_RADIUS, Math.max(MIN_WIDGET_RADIUS, Math.round(n)));
}

export function clampAvatarZoom(value: number | undefined | null): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return 1;
  return Math.min(MAX_AVATAR_ZOOM, Math.max(MIN_AVATAR_ZOOM, Math.round(n * 10) / 10));
}

export function clampAvatarOffset(value: number | undefined | null): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(40, Math.max(-40, Math.round(n)));
}

export function parseHexColor(input: string | undefined | null): string | null {
  if (!input) return null;
  const raw = input.trim();
  const hex = raw.startsWith("#") ? raw.slice(1) : raw;
  if (/^[0-9a-fA-F]{3}$/.test(hex)) {
    return `#${hex[0]}${hex[0]}${hex[1]}${hex[1]}${hex[2]}${hex[2]}`.toLowerCase();
  }
  if (/^[0-9a-fA-F]{6}$/.test(hex)) return `#${hex.toLowerCase()}`;
  return null;
}

function channelToLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const r = channelToLinear((n >> 16) & 255);
  const g = channelToLinear((n >> 8) & 255);
  const b = channelToLinear(n & 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(l1: number, l2: number): number {
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

/** Pick readable text for a brand color (white vs navy), not a fixed palette. */
export function contrastOn(hex: string): "#ffffff" | "#0b0e2e" {
  const parsed = parseHexColor(hex) ?? DEFAULT_WIDGET_COLOR;
  const bg = relativeLuminance(parsed);
  const white = contrastRatio(bg, 1);
  const navy = contrastRatio(bg, relativeLuminance("#0b0e2e"));
  return white >= navy ? "#ffffff" : "#0b0e2e";
}

export function resolvedTextColor(brand: string, textColor?: string): string {
  if (!textColor || textColor === "auto") return contrastOn(brand);
  return parseHexColor(textColor) ?? contrastOn(brand);
}

export function widgetThemeStyle(appearance: {
  primaryColor?: string;
  cornerRadius?: number;
  textColor?: string;
}): CSSProperties {
  const color = parseHexColor(appearance.primaryColor) ?? DEFAULT_WIDGET_COLOR;
  const on = resolvedTextColor(color, appearance.textColor);
  const radius = clampWidgetRadius(appearance.cornerRadius);
  return {
    ["--primary" as string]: color,
    ["--primary-foreground" as string]: on,
    ["--ring" as string]: color,
    ["--widget-radius" as string]: `${radius}px`,
    ["--widget-bubble-radius" as string]: `${radius}px`,
    ["--widget-composer-radius" as string]: `${radius}px`,
  };
}

export function avatarMediaStyle(
  zoom: number,
  offsetX: number,
  offsetY: number
): CSSProperties {
  const z = clampAvatarZoom(zoom);
  const x = clampAvatarOffset(offsetX);
  const y = clampAvatarOffset(offsetY);
  return {
    position: "absolute",
    left: `${50 + x}%`,
    top: `${50 + y}%`,
    width: `${z * 100}%`,
    height: `${z * 100}%`,
    maxWidth: "none",
    transform: "translate(-50%, -50%)",
    objectFit: "cover",
  };
}

const AVATAR_MAX = 512;

export async function readAvatarFile(file: File): Promise<string> {
  if (!file.type.startsWith("image/")) {
    throw new Error("Use a PNG, JPG, or WebP image.");
  }
  if (file.size > 4 * 1024 * 1024) {
    throw new Error("Keep the icon under 4 MB.");
  }
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, AVATAR_MAX / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Couldn't read that image.");
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  return canvas.toDataURL("image/jpeg", 0.9);
}

export function appearanceFromConfig(widget?: {
  primary_color?: string;
  text_color?: string;
  corner_radius?: number;
  avatar_url?: string;
  avatar_zoom?: number;
  avatar_offset_x?: number;
  avatar_offset_y?: number;
} | null): WidgetAppearance {
  const base = defaultAppearance();
  return {
    primaryColor: parseHexColor(widget?.primary_color) ?? base.primaryColor,
    textColor: widget?.text_color === "auto" || !widget?.text_color
      ? "auto"
      : parseHexColor(widget.text_color) ?? "auto",
    cornerRadius:
      widget?.corner_radius == null
        ? base.cornerRadius
        : clampWidgetRadius(widget.corner_radius),
    avatarUrl: widget?.avatar_url?.trim() || "",
    avatarZoom: clampAvatarZoom(widget?.avatar_zoom),
    avatarOffsetX: clampAvatarOffset(widget?.avatar_offset_x),
    avatarOffsetY: clampAvatarOffset(widget?.avatar_offset_y),
  };
}

export function appearanceToConfig(appearance: WidgetAppearance) {
  return {
    primary_color: appearance.primaryColor,
    text_color: appearance.textColor,
    corner_radius: appearance.cornerRadius,
    avatar_url: appearance.avatarUrl,
    avatar_zoom: appearance.avatarZoom,
    avatar_offset_x: appearance.avatarOffsetX,
    avatar_offset_y: appearance.avatarOffsetY,
  };
}
