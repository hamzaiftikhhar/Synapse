"use client";

import {
  BriefcaseMedical,
  Calendar,
  Clock,
  MapPin,
  Phone,
  Search,
  Shield,
  Siren,
  Stethoscope,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { BackendAction } from "@/features/chat/types";

const ICONS: Record<string, LucideIcon> = {
  Calendar,
  MapPin,
  Clock,
  Stethoscope,
  Shield,
  Phone,
  Siren,
  BriefcaseMedical,
  Search,
};

const chipBase =
  "synapse-chat-chip inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2.5 text-sm font-medium";

function ActionChipButton({
  action,
  onClick,
  size = "md",
}: {
  action: BackendAction;
  onClick: () => void;
  size?: "sm" | "md";
}) {
  const Icon = ICONS[action.icon ?? ""] ?? undefined;
  const isEmergency = action.variant === "emergency";
  const filled = Boolean(action.filled) || action.behavior === "launch_booking";

  return (
    <button
      type="button"
      title={action.label}
      onClick={onClick}
      className={cn(
        chipBase,
        size === "sm" && "px-3.5 py-2 text-xs gap-1.5",
        isEmergency
          ? "border-red-300 text-red-700 hover:bg-red-50"
          : filled
            ? "synapse-chat-chip--filled border-primary/20 bg-primary text-primary-foreground"
            : "border-neutral-300 text-neutral-800"
      )}
    >
      {Icon ? (
        <Icon
          className={cn(
            "size-4 shrink-0",
            filled ? "opacity-90" : "opacity-70",
            size === "sm" && "size-3.5"
          )}
        />
      ) : null}
      <span>{action.short_label ?? action.label}</span>
    </button>
  );
}

/** Homey-style contextual chips shown under an assistant reply. */
export function ContextActionChips({
  actions,
  onAction,
  className,
}: {
  actions: BackendAction[];
  onAction: (action: BackendAction) => void;
  className?: string;
}) {
  if (!actions.length) return null;

  return (
    <div className={cn("mt-2.5 flex flex-wrap gap-2 pl-9", className)}>
      {actions.map((a) => (
        <ActionChipButton
          key={a.id}
          action={a}
          onClick={() => onAction(a)}
        />
      ))}
    </div>
  );
}

/** Subtle sample prompts above the greeting. */
export function SamplePromptChips({
  items,
  onSelect,
}: {
  items: { id: string; label: string; message: string }[];
  onSelect: (message: string) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="mb-3 flex flex-wrap gap-1.5">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onSelect(item.message)}
          className="synapse-chat-chip rounded-full border border-dashed border-border bg-card px-2.5 py-1 text-[11px] font-medium text-muted-foreground"
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

/** Empty-state primary action chips — large Homey pills. */
export function StarterChips({
  items,
  onSelect,
}: {
  items: { id: string; label: string; message: string; icon?: string }[];
  onSelect: (
    message: string,
    item?: { id: string; label: string; message: string; icon?: string }
  ) => void;
}) {
  if (!items.length) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-2 pl-9">
      {items.map((item) => {
        const Icon = ICONS[item.icon ?? ""] ?? undefined;
        const filled = item.id === "book";
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.message, item)}
            className={cn(
              chipBase,
              filled
                ? "synapse-chat-chip--filled border-primary/20 bg-primary text-primary-foreground"
                : "border-neutral-300 text-neutral-800"
            )}
          >
            {Icon ? (
              <Icon
                className={cn(
                  "size-4 shrink-0",
                  filled ? "opacity-90" : "opacity-70"
                )}
              />
            ) : null}
            <span>{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Render meta.buttons as Homey chips (not primary purple blocks). */
export function ButtonChips({
  buttons,
  onAction,
}: {
  buttons: BackendAction[];
  onAction: (action: string, data?: unknown) => void;
}) {
  if (!buttons.length) return null;
  return (
    <div className="mt-2.5 flex flex-wrap gap-2 pl-9">
      {buttons.map((b) => (
        <ActionChipButton
          key={b.id}
          action={b}
          onClick={() => onAction("button", b)}
        />
      ))}
    </div>
  );
}
