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
  useCreateSpecialty,
  useDeleteSpecialty,
  useSpecialties,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

export function SpecialtiesStep({ onNext }: OnboardingStepProps) {
  const { data } = useSpecialties({ limit: 100 });
  const create = useCreateSpecialty();
  const remove = useDeleteSpecialty();
  const [draft, setDraft] = useState("");

  const specialties = data?.results ?? [];

  async function addSpecialty() {
    const name = draft.trim();
    if (!name) return;
    try {
      await create.mutateAsync({ name });
      setDraft("");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function onContinue(e: React.FormEvent) {
    e.preventDefault();
    onNext();
  }

  return (
    <div className="space-y-6">
      <form id={ONBOARDING_FORM_ID} onSubmit={onContinue} />
      <StepHint>
        Specialties are optional areas of care — they help patients find the
        right provider and improve service suggestions next. You can skip this
        and add them later, or import a spreadsheet.
      </StepHint>

      <div className="space-y-4 rounded-2xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Broad areas of care — e.g. Dermatology, Orthodontics, Primary Care.
          </p>
          <ImportTriggerButton recordType="specialties" />
        </div>
        <div className="flex flex-wrap gap-2">
          {specialties.map((s) => (
            <span
              key={s.id}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 py-1 pr-1.5 pl-3 text-sm"
            >
              {s.name}
              <button
                type="button"
                aria-label={`Remove ${s.name}`}
                onClick={() => remove.mutate(s.id)}
                className="flex size-5 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addSpecialty();
              }
            }}
            placeholder="e.g. Cosmetic Dermatology"
            className="max-w-xs"
          />
          <Button type="button" variant="outline" onClick={addSpecialty} disabled={!draft.trim()}>
            <Plus className="size-4" /> Add
          </Button>
        </div>
        {specialties.length === 0 ? <ImportGuide recordType="specialties" compact /> : null}
      </div>
    </div>
  );
}
