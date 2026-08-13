"use client";

import { cn } from "@/lib/utils";
import type { Service, Specialty } from "@/types/api";

/** Toggle-chip picker for linking a provider to services (booking) and
 * optional specialties (discovery). Booking filters doctors by services. */
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
    <div className="space-y-4">
      {services.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-foreground">Services offered</p>
          <p className="text-xs text-muted-foreground">
            Patients book these with this doctor.
          </p>
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
        </div>
      ) : null}
      {specialties.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-foreground">
            Specialties{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
          </p>
          <p className="text-xs text-muted-foreground">
            Used for search and the chatbot, not for booking.
          </p>
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
        </div>
      ) : null}
    </div>
  );
}
