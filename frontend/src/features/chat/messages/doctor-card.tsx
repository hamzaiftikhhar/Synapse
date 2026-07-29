"use client";

import { Button } from "@/components/ui/button";
import type { ChatActionHandler, DoctorCardData } from "@/types/chat";

export function DoctorCard({
  doctor,
  onAction,
}: {
  doctor: DoctorCardData;
  onAction?: ChatActionHandler;
}) {
  return (
    <div className="rounded-[6px] border border-border bg-white p-3">
      <p className="text-sm font-semibold text-navy">{doctor.name}</p>
      {doctor.title ? (
        <p className="text-xs text-primary">{doctor.title}</p>
      ) : null}
      {doctor.bio ? (
        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{doctor.bio}</p>
      ) : null}
      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          {doctor.languages?.join(", ") || "Languages vary"}
        </p>
        <Button
          size="xs"
          className="rounded-[6px]"
          onClick={() => onAction?.("select_doctor", doctor)}
        >
          Select
        </Button>
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
    <div className="grid gap-2">
      {doctors.map((d, i) => (
        <DoctorCard key={d.id || i} doctor={d} onAction={onAction} />
      ))}
    </div>
  );
}
