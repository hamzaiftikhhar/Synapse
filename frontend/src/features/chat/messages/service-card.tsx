"use client";

import { Button } from "@/components/ui/button";
import type { ChatActionHandler, ServiceCardData } from "@/types/chat";

function price(cents?: number | null) {
  if (cents == null) return null;
  return `$${(cents / 100).toFixed(2)}`;
}

export function ServiceCard({
  service,
  onAction,
}: {
  service: ServiceCardData;
  onAction?: ChatActionHandler;
}) {
  return (
    <div className="rounded-[6px] border border-border bg-white p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-navy">{service.name}</p>
          {service.description ? (
            <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
              {service.description}
            </p>
          ) : null}
          <p className="mt-1 text-[11px] text-muted-foreground">
            {[service.duration_min ? `${service.duration_min} min` : null, price(service.price_cents)]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <Button
          size="xs"
          variant="outline"
          className="rounded-[6px]"
          onClick={() => onAction?.("select_service", service)}
        >
          Choose
        </Button>
      </div>
    </div>
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
    <div className="grid gap-2">
      {services.map((s, i) => (
        <ServiceCard key={s.id || i} service={s} onAction={onAction} />
      ))}
    </div>
  );
}
