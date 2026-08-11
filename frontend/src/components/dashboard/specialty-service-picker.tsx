"use client";

import { cn } from "@/lib/utils";
import type { Service, Specialty } from "@/types/api";

/** Toggle-chip picker for linking a provider to specialties/services —
 * shared by onboarding's Catalog step and the dashboard Doctors page so a
 * provider can always be connected to what they treat, not just exist as a
 * standalone record. Booking (specialty-first mode) filters doctors by this
 * link, so an unlinked provider is invisible to patients. */
export function SpecialtyServicePicker({
  specialties,
  services,
  selectedSpecialtyIds,
  selectedServiceIds,
  onToggleSpecialty,
  onToggleService,
}: {
  specialties: Specialty[];
  services: Service[];
  selectedSpecialtyIds: string[];
  selectedServiceIds: string[];
  onToggleSpecialty: (id: string) => void;
  onToggleService: (id: string) => void;
}) {
  if (specialties.length === 0 && services.length === 0) return null;

  return (
    <div className="space-y-2">
      {specialties.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {specialties.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => onToggleSpecialty(s.id)}
              aria-pressed={selectedSpecialtyIds.includes(s.id)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                selectedSpecialtyIds.includes(s.id)
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted"
              )}
            >
              {s.name}
            </button>
          ))}
        </div>
      ) : null}
      {services.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {services.map((svc) => (
            <button
              key={svc.id}
              type="button"
              onClick={() => onToggleService(svc.id)}
              aria-pressed={selectedServiceIds.includes(svc.id)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                selectedServiceIds.includes(svc.id)
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted"
              )}
            >
              {svc.name}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
