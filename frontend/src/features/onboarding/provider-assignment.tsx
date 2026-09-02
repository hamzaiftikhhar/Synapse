"use client";

import { cn } from "@/lib/utils";
import type { Doctor } from "@/types/api";

/**
 * "Which doctors offer this?" toggle row — used under a specialty or
 * service in onboarding once there's more than one provider to choose
 * from (a single-provider clinic has nothing to disambiguate, so this
 * never renders there; see doctor-catalog-links.ts).
 */
export function ProviderAssignmentChips({
  doctors,
  selectedIds,
  onToggle,
  pending,
}: {
  doctors: Doctor[];
  selectedIds: string[];
  onToggle: (doctorId: string) => void;
  pending?: boolean;
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] text-muted-foreground">Offered by:</span>
      {doctors.map((doctor) => {
        const active = selectedIds.includes(doctor.id);
        return (
          <button
            key={doctor.id}
            type="button"
            disabled={pending}
            onClick={() => onToggle(doctor.id)}
            aria-pressed={active}
            className={cn(
              "rounded-full border px-2 py-0.5 text-[11px] transition-colors disabled:opacity-50",
              active
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
            )}
          >
            {doctor.full_name}
          </button>
        );
      })}
    </div>
  );
}
