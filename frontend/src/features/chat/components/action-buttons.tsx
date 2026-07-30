"use client";

import {
  BriefcaseMedical,
  Calendar,
  Clock,
  MapPin,
  Menu,
  Phone,
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
};

type BtnProps = {
  icon: string;
  label: string;
  shortLabel?: string;
  variant: "message" | "action" | "emergency";
  filled?: boolean;
  onClick: () => void;
  className?: string;
};

export function ActionChip({
  icon,
  label,
  shortLabel,
  variant,
  filled,
  onClick,
  className,
}: BtnProps) {
  const Icon = ICONS[icon] ?? Calendar;
  const isEmergency = variant === "emergency";
  const isFilled = filled || variant === "action" || isEmergency;

  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={cn(
        "inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-full px-3 py-2 text-xs font-semibold transition-all",
        isEmergency && "bg-red-600 text-white shadow-sm hover:bg-red-700",
        !isEmergency &&
          isFilled &&
          "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
        !isEmergency &&
          !isFilled &&
          "border border-border bg-white text-navy hover:border-primary/30 hover:bg-accent/50",
        className
      )}
    >
      <Icon className="size-3.5 shrink-0" />
      <span className="truncate">{shortLabel ?? label}</span>
    </button>
  );
}

export function BackendActionBar({
  actions,
  onAction,
}: {
  actions: BackendAction[];
  onAction: (action: BackendAction) => void;
}) {
  if (!actions.length) return null;

  return (
    <div className="flex shrink-0 gap-2 border-t border-border bg-white px-3 py-2.5">
      {actions.map((a) => (
        <ActionChip
          key={a.id}
          icon={a.icon ?? "Calendar"}
          label={a.label}
          shortLabel={a.short_label}
          variant={a.variant ?? "message"}
          filled={a.filled}
          onClick={() => onAction(a)}
        />
      ))}
    </div>
  );
}
