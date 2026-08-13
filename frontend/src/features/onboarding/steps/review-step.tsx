"use client";

import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Check, CircleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  useBusinessHours,
  useClinicProfile,
  useCompleteOnboarding,
  useOnboardingStatus,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import { cn } from "@/lib/utils";
import { CLINIC_TYPE_OPTIONS } from "../clinic-types";
import { StepHint } from "../step-hint";
import type { OnboardingStepSlug } from "../steps";

const REQUIRED_ITEMS: Array<{
  key: "clinic" | "location" | "providers" | "services" | "hours" | "availability";
  label: string;
  step: OnboardingStepSlug;
}> = [
  { key: "clinic", label: "Clinic information", step: "clinic" },
  { key: "location", label: "Location", step: "location" },
  { key: "providers", label: "Providers", step: "providers" },
  { key: "services", label: "Services", step: "services" },
  { key: "hours", label: "Business hours", step: "hours" },
  { key: "availability", label: "Provider availability", step: "availability" },
];

function SummaryRow({
  label,
  value,
  ok,
  onEdit,
}: {
  label: string;
  value: string;
  ok: boolean;
  onEdit: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border py-3 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium text-navy">{label}</p>
        <p className="truncate text-sm text-muted-foreground">{value}</p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {ok ? (
          <Check className="size-4 text-success" />
        ) : (
          <CircleAlert className="size-4 text-warning" />
        )}
        <Button type="button" variant="ghost" size="sm" onClick={onEdit}>
          Edit
        </Button>
      </div>
    </div>
  );
}

export function ReviewStep({
  onGoToStep,
}: {
  onGoToStep: (slug: OnboardingStepSlug) => void;
}) {
  const router = useRouter();
  const { refreshMe } = useAuth();
  const { data: clinic } = useClinicProfile();
  const { data: hours } = useBusinessHours();
  const { data: status, isLoading } = useOnboardingStatus();
  const complete = useCompleteOnboarding();

  const clinicTypeLabel = CLINIC_TYPE_OPTIONS.find((o) => o.value === clinic?.clinic_type)?.label;
  const openDays = hours?.filter((h) => !h.is_closed).length ?? 0;
  const cityState = [clinic?.address?.city, clinic?.address?.state].filter(Boolean).join(", ");

  const checklist = status?.checklist;
  const missing = REQUIRED_ITEMS.filter((item) => checklist && !checklist[item.key]);
  const ready = Boolean(status?.ready);

  async function onFinish() {
    let updated;
    try {
      updated = await complete.mutateAsync();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
      return;
    }

    // A clinic provisioned from a paid application isn't activated by the
    // checklist alone — the backend leaves it in onboarding and points the
    // resume cursor at "billing" instead (see apps/api/clinics/router.py
    // complete_onboarding). Continue into the wizard's payment step rather
    // than trying to leave onboarding.
    if (updated.status !== "active") {
      onGoToStep("billing");
      return;
    }

    // Completion succeeded server-side at this point — refreshMe() itself
    // never throws (it deliberately swallows transient failures elsewhere
    // so a network blip doesn't log someone out), so success has to be read
    // from its return value rather than a try/catch.
    const refreshed = await refreshMe();
    if (!refreshed) {
      // Client's cached clinic.status is now stale ("onboarding"), which
      // would bounce us straight back into onboarding via the dashboard
      // layout guard on a plain client-side route change. Force a full
      // reload instead — that re-derives auth state from scratch rather
      // than trusting the failed refresh.
      window.location.assign("/dashboard");
      return;
    }
    toast.success("Your clinic is ready");
    router.replace("/dashboard");
  }

  return (
    <div className="space-y-8">
      <StepHint>
        Check each section before activating. Edit anything that looks off —
        you can still change all of this later from the dashboard.
      </StepHint>
      <div className="rounded-2xl border border-border bg-card">
        <div className="divide-y divide-border px-5">
          <SummaryRow
            label="Clinic"
            value={clinic?.name ? `${clinic.name}${clinicTypeLabel ? ` · ${clinicTypeLabel}` : ""}` : "Not set"}
            ok={Boolean(checklist?.clinic)}
            onEdit={() => onGoToStep("clinic")}
          />
          <SummaryRow
            label="Location"
            value={cityState || "Not set"}
            ok={Boolean(checklist?.location)}
            onEdit={() => onGoToStep("location")}
          />
          <SummaryRow
            label="Providers"
            value={`${status?.counts.providers ?? 0} provider${status?.counts.providers === 1 ? "" : "s"}`}
            ok={Boolean(checklist?.providers)}
            onEdit={() => onGoToStep("providers")}
          />
          <SummaryRow
            label="Specialties"
            value={
              status?.counts.specialties
                ? `${status.counts.specialties} specialt${status.counts.specialties === 1 ? "y" : "ies"}`
                : "None — optional"
            }
            ok
            onEdit={() => onGoToStep("specialties")}
          />
          <SummaryRow
            label="Services"
            value={`${status?.counts.services ?? 0} service${status?.counts.services === 1 ? "" : "s"}`}
            ok={Boolean(checklist?.services)}
            onEdit={() => onGoToStep("services")}
          />
          <SummaryRow
            label="Business hours"
            value={openDays > 0 ? `Open ${openDays} day${openDays === 1 ? "" : "s"} a week` : "Not set"}
            ok={Boolean(checklist?.hours)}
            onEdit={() => onGoToStep("hours")}
          />
          <SummaryRow
            label="Provider availability"
            value={checklist?.availability ? "Configured" : "Not set"}
            ok={Boolean(checklist?.availability)}
            onEdit={() => onGoToStep("availability")}
          />
        </div>
      </div>

      <div
        className={cn(
          "rounded-2xl border px-5 py-4",
          ready ? "border-success/30 bg-success/5" : "border-warning/30 bg-warning/5"
        )}
      >
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Checking your setup…</p>
        ) : ready ? (
          <div className="flex items-center gap-2">
            <Check className="size-4 text-success" />
            <p className="text-sm font-medium text-navy">Your clinic is ready</p>
          </div>
        ) : (
          <div>
            <div className="flex items-center gap-2">
              <CircleAlert className="size-4 text-warning" />
              <p className="text-sm font-medium text-navy">A few things still need attention</p>
            </div>
            <ul className="mt-2 space-y-1">
              {missing.map((item) => (
                <li key={item.key}>
                  <button
                    type="button"
                    onClick={() => onGoToStep(item.step)}
                    className="text-sm text-primary hover:underline"
                  >
                    → Complete {item.label.toLowerCase()}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div>
        <h2 className="text-lg font-semibold tracking-tight text-navy">You&apos;re ready to go.</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Synapse now has the information it needs to help patients find
          services, understand your clinic, and book appointments.
        </p>
        <Button
          type="button"
          className="mt-4"
          onClick={onFinish}
          disabled={!ready || complete.isPending}
        >
          {complete.isPending ? "Finishing setup…" : "Go to Dashboard"}
        </Button>
      </div>
    </div>
  );
}
