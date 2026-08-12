"use client";

import {
  BriefcaseMedical,
  Calendar,
  CircleHelp,
  Clock,
  MapPin,
  Phone,
  Shield,
  Stethoscope,
  type LucideIcon,
} from "lucide-react";
import type { ChatActionHandler, ChatMessage, MainMenuItem } from "@/types/chat";

const ICONS: Record<string, LucideIcon> = {
  Calendar,
  Stethoscope,
  BriefcaseMedical,
  Shield,
  Clock,
  MapPin,
  Phone,
  CircleHelp,
};

export function MainMenuMessage({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const items = (message.payload?.items as MainMenuItem[]) || [];
  if (!items.length) return null;

  return (
    <div className="w-full overflow-hidden rounded-[6px] border border-border bg-card">
      <div className="border-b border-border px-3 py-2.5">
        <p className="text-xs font-semibold tracking-tight text-navy">
          How can we help?
        </p>
      </div>
      <div className="grid grid-cols-1 gap-px bg-border sm:grid-cols-2">
        {items.map((item) => {
          const Icon = (item.icon && ICONS[item.icon]) || CircleHelp;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onAction?.("menu", item)}
              className="flex items-start gap-2.5 bg-card px-3 py-3 text-left transition-colors hover:bg-accent/50"
            >
              <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-[6px] bg-accent text-primary">
                <Icon className="size-3.5" />
              </span>
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-navy">
                  {item.label}
                </span>
                {item.description ? (
                  <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                    {item.description}
                  </span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
