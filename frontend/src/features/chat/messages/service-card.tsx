"use client";

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
      className="flex w-[140px] shrink-0 snap-start flex-col gap-1 rounded-lg border border-border bg-white p-2.5 text-left transition-colors hover:border-primary/30 hover:bg-accent/40"
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
  return (
    <div className="flex snap-x snap-mandatory gap-2 overflow-x-auto pb-1 [-webkit-overflow-scrolling:touch] [scrollbar-width:thin]">
      {services.map((s, i) => (
        <ServiceCard key={s.id || i} service={s} onAction={onAction} />
      ))}
    </div>
  );
}
