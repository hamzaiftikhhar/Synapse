"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
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
      className="flex w-full items-center justify-between gap-3 rounded-lg border border-border bg-card px-3 py-2.5 text-left transition-colors hover:border-primary/30 hover:bg-accent/40"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{service.name}</p>
        {service.category ? (
          <p className="truncate text-xs text-muted-foreground">{service.category}</p>
        ) : null}
      </div>
      {detail ? (
        <span className="shrink-0 text-xs font-medium text-muted-foreground">{detail}</span>
      ) : null}
    </button>
  );
}

// Below this many cards, the list is already scannable at a glance — a
// search box would just be one more thing to look at for no benefit.
const SEARCH_THRESHOLD = 4;

export function ServiceCards({
  services,
  onAction,
  messageId,
}: {
  services: ServiceCardData[];
  onAction?: ChatActionHandler;
  messageId?: string;
}) {
  // Same fix as DoctorCards/TimeSlotsMessage — picking a service launches
  // the booking wizard, which becomes the one live card; this list must
  // not stay behind it with every other service still clickable.
  const [picked, setPicked] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return services;
    return services.filter(
      (s) =>
        s.name.toLowerCase().includes(q) || (s.category || "").toLowerCase().includes(q)
    );
  }, [services, query]);

  if (picked) return null;

  return (
    <ChatInlineCard className="grid gap-2">
      {services.length > SEARCH_THRESHOLD ? (
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search services"
            className="h-8 pl-8 text-xs"
          />
        </div>
      ) : null}
      {filtered.length === 0 ? (
        <p className="px-1 py-2 text-xs text-muted-foreground">
          No services match &quot;{query}&quot;.
        </p>
      ) : (
        <div className="grid max-h-80 gap-1.5 overflow-y-auto pr-0.5">
          {filtered.map((s, i) => (
            <ServiceCard
              key={s.id || i}
              service={s}
              onAction={(action, data) => {
                if (action === "select_service") {
                  setPicked(true);
                  onAction?.(action, { ...(data as object), messageId });
                  return;
                }
                onAction?.(action, data);
              }}
            />
          ))}
        </div>
      )}
    </ChatInlineCard>
  );
}
