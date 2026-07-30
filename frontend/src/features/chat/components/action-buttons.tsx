"use client";

import {
  BriefcaseMedical,
  Calendar,
  Clock,
  MapPin,
  Menu,
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
  Menu,
  MapPin,
  Clock,
  Stethoscope,
  Shield,
  Phone,
  Siren,
  BriefcaseMedical,
  Search,
};

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
    <div className={cn("mt-2 flex flex-wrap gap-2 pl-9", className)}>
      {actions.map((a) => {
        const Icon = ICONS[a.icon ?? ""] ?? undefined;
        const isEmergency = a.variant === "emergency";

        return (
          <button
            key={a.id}
            type="button"
            title={a.label}
            onClick={() => onAction(a)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border bg-white px-3 py-1.5 text-xs font-medium transition-colors",
              isEmergency
                ? "border-red-300 text-red-700 hover:bg-red-50"
                : "border-neutral-300 text-neutral-800 hover:border-neutral-400 hover:bg-neutral-50"
            )}
          >
            {Icon ? <Icon className="size-3.5 shrink-0 opacity-70" /> : null}
            <span>{a.short_label ?? a.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Empty-state starter chips — send the prompt to the backend on click. */
export function StarterChips({
  items,
  onSelect,
}: {
  items: { id: string; label: string; message: string; icon?: string }[];
  onSelect: (message: string) => void;
}) {
  if (!items.length) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-2 pl-9">
      {items.map((item) => {
        const Icon = ICONS[item.icon ?? ""] ?? undefined;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.message)}
            className="inline-flex items-center gap-1.5 rounded-full border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-800 transition-colors hover:border-neutral-400 hover:bg-neutral-50"
          >
            {Icon ? <Icon className="size-3.5 shrink-0 opacity-70" /> : null}
            <span>{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}
