"use client";

import { format, isToday, isYesterday } from "date-fns";
import { Maximize2, Minimize2, MoreHorizontal, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { RobotAvatar } from "@/features/chat/components/robot-avatar";
import { isoToClinicParts } from "@/lib/timezone";

export function formatMessageTime(iso: string) {
  const d = new Date(iso);
  if (isToday(d)) return format(d, "h:mm a");
  if (isYesterday(d)) return `Yesterday ${format(d, "h:mm a")}`;
  return format(d, "MMM d, h:mm a");
}

/** Calendar-day arithmetic on already clinic-local "YYYY-MM-DD" strings —
 * UTC-anchored so month/year rollover is handled by Date's own
 * normalization without ever touching a real timezone offset. */
function shiftDateString(dateStr: string, deltaDays: number): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + deltaDays)).toISOString().slice(0, 10);
}

/**
 * WhatsApp-style day-separator label, grouped by the *clinic's* timezone
 * — deliberately distinct from formatMessageTime above, which is
 * browser-local and meant for a single message's timestamp, not for
 * deciding which day a history separator belongs to.
 */
export function clinicDayLabel(iso: string, timeZone: string): string {
  const { date } = isoToClinicParts(iso, timeZone);
  const todayDate = isoToClinicParts(new Date().toISOString(), timeZone).date;
  if (date === todayDate) return "Today";
  if (date === shiftDateString(todayDate, -1)) return "Yesterday";
  const [y, m, d] = date.split("-").map(Number);
  // Noon UTC avoids the display Date crossing a calendar boundary once
  // date-fns' `format` reads it back out in the *browser's* local zone.
  return format(new Date(Date.UTC(y, m - 1, d, 12)), "MMMM d, yyyy");
}

/** Presentation-only — never persisted as a message. Groups consecutive
 * history rows that fall on the same clinic-local calendar day. */
export function DateSeparator({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center py-1" role="separator" aria-label={label}>
      <span className="rounded-full bg-muted px-3 py-1 text-[11px] font-medium text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

export function ChatHeader({
  clinicName,
  expanded,
  onToggleExpand,
  onRestart,
  onClose,
  showExpand = true,
}: {
  clinicName?: string;
  expanded: boolean;
  onToggleExpand: () => void;
  onRestart: () => void;
  onClose: () => void;
  showExpand?: boolean;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDoc(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  const title = clinicName ? `${clinicName} Assistant` : "Synapse Assistant";

  return (
    <div className="shrink-0 border-b border-border/70 bg-card px-4 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <RobotAvatar size="md" className="mt-0.5 rounded-full bg-primary shadow-sm" />
          <div className="min-w-0">
            <p className="truncate text-[15px] font-semibold tracking-tight text-foreground">
              {title}
            </p>
            <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
              Messages may be processed to improve care. See our{" "}
              <a
                href="/privacy"
                className="text-primary underline-offset-2 hover:underline"
                target="_blank"
                rel="noreferrer"
              >
                privacy policy
              </a>
              .
            </p>
          </div>
        </div>

        <div className="relative flex shrink-0 items-center gap-0.5" ref={menuRef}>
          {showExpand ? (
            <button
              type="button"
              title={expanded ? "Compact view" : "Expand"}
              onClick={onToggleExpand}
              className="rounded-lg p-1.5 text-muted-foreground transition-[background-color,color] duration-150 hover:bg-accent hover:text-foreground"
              aria-label={expanded ? "Compact" : "Expand"}
            >
              {expanded ? (
                <Minimize2 className="size-4" />
              ) : (
                <Maximize2 className="size-4" />
              )}
            </button>
          ) : null}

          <button
            type="button"
            title="More"
            onClick={() => setMenuOpen((v) => !v)}
            className="rounded-lg p-1.5 text-muted-foreground transition-[background-color,color] duration-150 hover:bg-accent hover:text-foreground"
            aria-expanded={menuOpen}
            aria-label="More options"
          >
            <MoreHorizontal className="size-4" />
          </button>

          <button
            type="button"
            title="Close"
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted-foreground transition-[background-color,color] duration-150 hover:bg-accent hover:text-foreground"
            aria-label="Close chat"
          >
            <X className="size-4" />
          </button>

          {menuOpen ? (
            <div
              className="absolute right-0 top-full z-20 mt-1 min-w-[148px] origin-top-right rounded-xl border border-border bg-popover p-1 shadow-lg"
              style={{
                animation: "synapse-panel-in 200ms ease-out both",
              }}
              role="menu"
            >
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  onRestart();
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-foreground transition-[background-color] duration-150 hover:bg-accent"
              >
                <RotateCcw className="size-3.5 opacity-70" />
                Restart chat
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function BotMetaRow({
  name,
  time,
}: {
  name?: string;
  time?: string;
}) {
  return (
    <div className="mb-1 flex flex-wrap items-center gap-1.5 px-0.5">
      <span className="text-[12px] font-medium text-muted-foreground">
        {name || "Assistant"}
      </span>
      <span className="rounded-full bg-neutral-200/90 px-1.5 py-px text-[9px] font-semibold tracking-wide text-neutral-600">
        BOT
      </span>
      {time ? (
        <span className="text-[10px] text-muted-foreground/80">{time}</span>
      ) : null}
    </div>
  );
}
