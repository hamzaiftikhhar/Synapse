"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ImportGuide } from "@/features/importer/import-guide";
import { ImportTriggerButton } from "@/features/importer/import-trigger-button";
import { StepHint } from "@/features/onboarding/step-hint";
import {
  useCreateInsurancePlan,
  useDeleteInsurancePlan,
  useInsurancePlans,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { InsurancePlan } from "@/types/api";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

function planLabel(plan: InsurancePlan) {
  return [plan.provider_name, plan.plan_name, plan.plan_type].filter(Boolean).join(" · ");
}

export function InsuranceStep({ onNext }: OnboardingStepProps) {
  const { data } = useInsurancePlans({ limit: 100 });
  const create = useCreateInsurancePlan();
  const remove = useDeleteInsurancePlan();
  const [provider, setProvider] = useState("");
  const [planName, setPlanName] = useState("");
  const [planType, setPlanType] = useState("");

  const plans = data?.results ?? [];

  async function addPlan() {
    const name = provider.trim();
    if (!name) return;
    try {
      await create.mutateAsync({
        provider_name: name,
        plan_name: planName.trim(),
        plan_type: planType.trim(),
      });
      setProvider("");
      setPlanName("");
      setPlanType("");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  function onContinue(e: React.FormEvent) {
    e.preventDefault();
    onNext();
  }

  return (
    <div className="space-y-6">
      <form id={ONBOARDING_FORM_ID} onSubmit={onContinue} />
      <StepHint>
        Insurance is optional. A payer name is enough — plan and network help
        the chatbot answer coverage questions more precisely. You can skip this
        and add them later, or import a spreadsheet.
      </StepHint>

      <div className="space-y-4 rounded-2xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            What patients ask about — e.g. Aetna, Blue Cross, Cigna.
          </p>
          <ImportTriggerButton recordType="insurance" />
        </div>
        <div className="flex flex-wrap gap-2">
          {plans.map((plan) => (
            <span
              key={plan.id}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 py-1 pr-1.5 pl-3 text-sm"
            >
              {planLabel(plan)}
              <button
                type="button"
                aria-label={`Remove ${planLabel(plan)}`}
                onClick={() => remove.mutate(plan.id)}
                className="flex size-5 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Input
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addPlan();
              }
            }}
            placeholder="Insurance name *"
            className="min-w-[10rem] flex-1"
            aria-label="Insurance name"
          />
          <Input
            value={planName}
            onChange={(e) => setPlanName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addPlan();
              }
            }}
            placeholder="Plan name (optional)"
            className="min-w-[8rem] flex-1"
            aria-label="Plan name"
          />
          <Input
            value={planType}
            onChange={(e) => setPlanType(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addPlan();
              }
            }}
            placeholder="Network / type (optional)"
            className="min-w-[8rem] flex-1"
            aria-label="Network or type"
          />
          <Button type="button" variant="outline" onClick={addPlan} disabled={!provider.trim()}>
            <Plus className="size-4" /> Add
          </Button>
        </div>
        {plans.length === 0 ? <ImportGuide recordType="insurance" compact /> : null}
      </div>
    </div>
  );
}
