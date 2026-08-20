"use client";

import { useState } from "react";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import type { ChatActionHandler, ServiceCardData } from "@/types/chat";

function price(cents?: number | null) {
  if (cents == null) return null;
  return `$${(cents / 100).toFixed(0)}`;
}

export function ServiceCard({
  service,
  onAction,
}: {
  service: ServiceCardData;
  onAction?: ChatActionHandler;
}) {
  const detail = [
    service.duration_min ? `${service.duration_min} min` : null,
    price(service.price_cents),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <button
      type="button"
      onClick={() => onAction?.("select_service", service)}
      className="flex w-[140px] shrink-0 snap-start flex-col gap-1 rounded-lg border border-border bg-card p-2.5 text-left transition-colors hover:border-primary/30 hover:bg-accent/40"
    >
      <p className="line-clamp-2 text-xs font-semibold leading-snug text-foreground">
        {service.name}
      </p>
      {detail ? <p className="text-[10px] text-muted-foreground">{detail}</p> : null}
    </button>
  );
}

export function ServiceCards({
  services,
  onAction,
}: {
  services: ServiceCardData[];
  onAction?: ChatActionHandler;
}) {
  // Same fix as DoctorCards/TimeSlotsMessage — picking a service launches
  // the booking wizard, which becomes the one live card; this list must
  // not stay behind it with every other service still clickable.
  const [picked, setPicked] = useState(false);

  if (picked) return null;

  return (
    <ChatInlineCard className="flex snap-x snap-mandatory gap-2 overflow-x-auto pb-1 [-webkit-overflow-scrolling:touch] [scrollbar-width:thin]">
      {services.map((s, i) => (
        <ServiceCard
          key={s.id || i}
          service={s}
          onAction={(action, data) => {
            if (action === "select_service") setPicked(true);
            onAction?.(action, data);
          }}
        />
      ))}
    </ChatInlineCard>
  );
}
