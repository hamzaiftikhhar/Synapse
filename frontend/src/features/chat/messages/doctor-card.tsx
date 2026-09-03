"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import type { ChatActionHandler, DoctorCardData } from "@/types/chat";

function initials(name: string): string {
  const parts = name.replace(/^dr\.?\s*/i, "").trim().split(/\s+/);
  return parts.slice(0, 2).map((p) => p[0]?.toUpperCase() || "").join("") || "?";
}

export function DoctorCard({
  doctor,
  onAction,
}: {
  doctor: DoctorCardData;
  onAction?: ChatActionHandler;
}) {
  return (
    <div className="rounded-[6px] border border-border bg-card p-3">
      <div className="flex items-start gap-2.5">
        <Avatar>
          {doctor.photo_url ? (
            <AvatarImage src={doctor.photo_url} alt={doctor.name} />
          ) : null}
          <AvatarFallback>{initials(doctor.name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-navy">{doctor.name}</p>
          {doctor.title ? (
            <p className="truncate text-xs text-primary">{doctor.title}</p>
          ) : null}
          {doctor.specialties?.length ? (
            <p className="truncate text-xs text-muted-foreground">
              {doctor.specialties.join(", ")}
            </p>
          ) : null}
        </div>
      </div>
      {doctor.bio ? (
        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{doctor.bio}</p>
      ) : null}
      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          {doctor.languages?.join(", ") || "Languages vary"}
        </p>
        {doctor.select_message || doctor.message ? (
          <Button
            size="xs"
            className="rounded-[6px]"
            onClick={() => onAction?.("select_doctor", doctor)}
          >
            Select
          </Button>
        ) : null}
      </div>
    </div>
  );
}

// Below this many cards, the list is already scannable at a glance — a
// search box would just be one more thing to look at for no benefit. A
// typical small clinic's whole roster (4-6 doctors) is common enough that
// this stays low rather than only kicking in for large rosters.
const SEARCH_THRESHOLD = 4;

export function DoctorCards({
  doctors,
  onAction,
  messageId,
}: {
  doctors: DoctorCardData[];
  onAction?: ChatActionHandler;
  messageId?: string;
}) {
  // Same fix as TimeSlotsMessage (Phase 22): once a doctor is picked, the
  // booking wizard it launches becomes the one live card in the transcript
  // — this list must not stay behind it with every other doctor's Select
  // button still clickable. See ROADMAP.md "Chat card collapse-on-
  // supersede" / Phase 24's follow-up report for the reproduction.
  const [picked, setPicked] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return doctors;
    return doctors.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        (d.title || "").toLowerCase().includes(q) ||
        (d.specialties || []).some((s) => s.toLowerCase().includes(q))
    );
  }, [doctors, query]);

  if (picked) return null;

  return (
    <ChatInlineCard className="grid gap-2">
      {doctors.length > SEARCH_THRESHOLD ? (
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name or specialty"
            className="h-8 pl-8 text-xs"
          />
        </div>
      ) : null}
      {filtered.length === 0 ? (
        <p className="px-1 py-2 text-xs text-muted-foreground">
          No doctors match &quot;{query}&quot;.
        </p>
      ) : (
        <div className="grid max-h-96 gap-2 overflow-y-auto pr-0.5">
          {filtered.map((d, i) => (
            <DoctorCard
              key={d.id || i}
              doctor={d}
              onAction={(action, data) => {
                if (action === "select_doctor") {
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
