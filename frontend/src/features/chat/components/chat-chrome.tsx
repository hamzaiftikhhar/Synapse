"use client";

import { format, isToday, isYesterday } from "date-fns";
import {
  Maximize2,
  Minimize2,
  RotateCcw,
  X,
} from "lucide-react";
import { RobotAvatar } from "@/features/chat/components/robot-avatar";

export function formatMessageTime(iso: string) {
  const d = new Date(iso);
  if (isToday(d)) return format(d, "h:mm a");
  if (isYesterday(d)) return `Yesterday ${format(d, "h:mm a")}`;
  return format(d, "MMM d, h:mm a");
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
  return (
    <div className="flex shrink-0 items-center justify-between gap-2 bg-gradient-to-r from-[#5b21b6] via-[#6366f1] to-[#4f46e5] px-3.5 py-3 text-white">
      <div className="flex min-w-0 items-center gap-2.5">
        <RobotAvatar size="md" animate />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight">
            Synapse Assistant
          </p>
          {clinicName ? (
            <p className="truncate text-[11px] text-white/70">{clinicName}</p>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        {showExpand ? (
          <button
            type="button"
            title={expanded ? "Compact view" : "Expand"}
            onClick={onToggleExpand}
            className="rounded-[6px] p-1.5 hover:bg-white/15"
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
          title="Restart chat"
          onClick={onRestart}
          className="rounded-[6px] p-1.5 hover:bg-white/15"
          aria-label="Restart chat"
        >
          <RotateCcw className="size-4" />
        </button>
        <button
          type="button"
          title="Close"
          onClick={onClose}
          className="rounded-[6px] p-1.5 hover:bg-white/15"
          aria-label="Close chat"
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  );
}
