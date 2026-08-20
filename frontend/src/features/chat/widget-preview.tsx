"use client";

import { ArrowUp } from "lucide-react";
import { RobotAvatar, RobotLauncherIcon } from "@/features/chat/components/robot-avatar";
import {
  WidgetThemeProvider,
  resolvedTextColor,
  parseHexColor,
  widgetThemeStyle,
  type WidgetAppearance,
} from "@/features/chat/widget-theme";

export function WidgetPreview({
  appearance,
  clinicName,
  greeting,
}: {
  appearance: WidgetAppearance;
  clinicName?: string;
  greeting?: string;
}) {
  const color = parseHexColor(appearance.primaryColor) ?? appearance.primaryColor;
  const onColor = resolvedTextColor(color, appearance.textColor);
  const title = clinicName ? `${clinicName} Assistant` : "Clinic Assistant";
  const hello = greeting?.trim() || `Hi! How can ${clinicName || "we"} help you today?`;
  const radius = appearance.cornerRadius;
  const bubbleTail = radius === 0 ? 0 : Math.max(4, Math.round(radius * 0.35));

  return (
    <WidgetThemeProvider appearance={appearance}>
      <div className="overflow-hidden rounded-2xl border border-border bg-[#efece7] shadow-[0_16px_40px_-24px_rgba(11,14,46,0.45)]">
        <div className="flex items-center gap-1.5 border-b border-black/5 bg-white/80 px-3 py-2">
          <span className="size-1.5 rounded-full bg-[#ff5f57]" />
          <span className="size-1.5 rounded-full bg-[#febc2e]" />
          <span className="size-1.5 rounded-full bg-[#28c840]" />
          <span className="ml-2 min-w-0 flex-1 truncate rounded-md bg-black/[0.04] px-2 py-0.5 text-[10px] text-muted-foreground">
            yourclinic.com
          </span>
        </div>
        <div className="relative h-[380px] p-3">
          <div className="absolute inset-x-6 top-8 h-2 rounded-full bg-black/[0.04]" />
          <div className="absolute inset-x-6 top-12 h-2 w-2/3 rounded-full bg-black/[0.04]" />
          <div
            className="absolute right-3 bottom-16 w-[min(100%,240px)] overflow-hidden border border-black/10 bg-card shadow-[0_12px_28px_-12px_rgba(11,14,46,0.35)]"
            style={{
              ...widgetThemeStyle(appearance),
              borderRadius: radius,
            }}
          >
            <div className="flex items-center gap-2 border-b border-border/70 px-2.5 py-2">
              <RobotAvatar size="sm" className="rounded-full shadow-none" />
              <div className="min-w-0">
                <p className="truncate text-[12px] font-semibold text-foreground">{title}</p>
                <p className="text-[9px] text-muted-foreground">Typically replies in a few seconds</p>
              </div>
            </div>
            <div className="space-y-2.5 bg-muted/20 px-2.5 py-2.5">
              <div className="flex gap-1.5">
                <RobotAvatar size="sm" className="mt-3 shrink-0 rounded-full shadow-none" />
                <div
                  className="max-w-[85%] border border-border/80 bg-card px-2.5 py-1.5 text-[11px] leading-relaxed text-foreground"
                  style={{
                    borderRadius: radius,
                    borderBottomLeftRadius: bubbleTail,
                  }}
                >
                  {hello}
                </div>
              </div>
              <div className="flex justify-end">
                <div
                  className="max-w-[80%] px-2.5 py-1.5 text-[11px] leading-relaxed"
                  style={{
                    backgroundColor: color,
                    color: onColor,
                    borderRadius: radius,
                    borderBottomRightRadius: bubbleTail,
                  }}
                >
                  Do you take my insurance?
                </div>
              </div>
            </div>
            <div className="px-2.5 pb-2.5 pt-1">
              <div
                className="flex items-center justify-between border border-border bg-background px-2.5 py-1.5"
                style={{ borderRadius: radius }}
              >
                <span className="text-[10px] text-muted-foreground">Write a message</span>
                <span
                  className="flex size-6 items-center justify-center rounded-full"
                  style={{ backgroundColor: color, color: onColor }}
                >
                  <ArrowUp className="size-3" strokeWidth={2.5} />
                </span>
              </div>
            </div>
          </div>
          <div className="absolute right-3 bottom-3 size-12 overflow-hidden rounded-full shadow-lg ring-2 ring-black/10">
            <RobotLauncherIcon className="rounded-full" />
          </div>
        </div>
      </div>
    </WidgetThemeProvider>
  );
}
