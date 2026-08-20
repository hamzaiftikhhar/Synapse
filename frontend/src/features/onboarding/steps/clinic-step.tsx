"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateClinicProfile } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import type { ClinicType } from "@/types/api";
import { CLINIC_TYPE_OPTIONS } from "../clinic-types";
import { StepHint } from "../step-hint";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";
import { cn } from "@/lib/utils";

export function ClinicStep({ onNext }: OnboardingStepProps) {
  const { clinic } = useAuth();
  const updateProfile = useUpdateClinicProfile();
  const [name, setName] = useState(clinic?.name ?? "");
  const [clinicType, setClinicType] = useState<ClinicType | "">(
    clinic?.clinic_type ?? ""
  );
  const [nameError, setNameError] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setNameError("Please enter the clinic name.");
      return;
    }
    if (!clinicType) {
      toast.error("Please choose the type that best fits your clinic.");
      return;
    }
    setNameError("");
    try {
      await updateProfile.mutateAsync({ name: name.trim(), clinic_type: clinicType });
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit} className="space-y-8">
      <StepHint>Use the name patients will recognize.</StepHint>
      <div className="space-y-2">
        <Label htmlFor="clinic-name">Clinic name</Label>
        <Input
          id="clinic-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Lumina Skin & Laser Dermatology"
          aria-invalid={Boolean(nameError)}
        />
        {nameError ? <p className="text-xs text-destructive">{nameError}</p> : null}
      </div>

      <div className="space-y-3">
        <Label>What kind of clinic is this?</Label>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {CLINIC_TYPE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setClinicType(option.value)}
              aria-pressed={clinicType === option.value}
              className={cn(
                "rounded-xl border px-3.5 py-3 text-left text-sm font-medium transition-colors",
                clinicType === option.value
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-foreground hover:bg-muted"
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          This helps us personalize your setup. You can change it later.
        </p>
      </div>
    </form>
  );
}
