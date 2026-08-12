"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
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

export function DoctorCards({
  doctors,
  onAction,
}: {
  doctors: DoctorCardData[];
  onAction?: ChatActionHandler;
}) {
  return (
    <ChatInlineCard className="grid gap-2">
      {doctors.map((d, i) => (
        <DoctorCard key={d.id || i} doctor={d} onAction={onAction} />
      ))}
    </ChatInlineCard>
  );
}
