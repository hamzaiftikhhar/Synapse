"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Layers, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ImportTriggerButton } from "@/features/importer/import-trigger-button";
import { StepHint } from "@/features/onboarding/step-hint";
import { SuggestionChip } from "@/features/onboarding/suggestion-chip";
import { suggestedSpecialtyNames } from "@/features/onboarding/specialty-templates";
import {
  useCreateSpecialty,
  useDeleteSpecialty,
  useSpecialties,
  useUpdateSpecialty,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import type { Specialty } from "@/types/api";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

type SpecialtyForm = {
  name: string;
  description: string;
};

const EMPTY_FORM: SpecialtyForm = { name: "", description: "" };

export function SpecialtiesStep({ onNext }: OnboardingStepProps) {
  const { clinic } = useAuth();
  const { data, isLoading } = useSpecialties({ limit: 100 });
  const create = useCreateSpecialty();
  const update = useUpdateSpecialty();
  const remove = useDeleteSpecialty();

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Specialty | null>(null);
  const [form, setForm] = useState<SpecialtyForm>(EMPTY_FORM);
  const [nameError, setNameError] = useState("");
  const [addingName, setAddingName] = useState<string | null>(null);

  const specialties = data?.results ?? [];
  const existing = new Set(specialties.map((s) => s.name.toLowerCase()));
  const suggestions = suggestedSpecialtyNames(clinic?.clinic_type).filter(
    (name) => !existing.has(name.toLowerCase())
  );

  function openCreate(name = "") {
    setEditing(null);
    setForm({ name, description: "" });
    setNameError("");
    setOpen(true);
  }

  function openEdit(specialty: Specialty) {
    setEditing(specialty);
    setForm({ name: specialty.name, description: specialty.description ?? "" });
    setNameError("");
    setOpen(true);
  }

  async function addSuggested(name: string) {
    setAddingName(name);
    try {
      await create.mutateAsync({ name });
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setAddingName(null);
    }
  }

  async function saveSpecialty(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setNameError("Please enter the specialty name.");
      return;
    }
    setNameError("");
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
    };
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: payload });
        toast.success("Specialty updated");
      } else {
        await create.mutateAsync(payload);
        toast.success("Specialty added");
      }
      setOpen(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function onRemove(id: string) {
    try {
      await remove.mutateAsync(id);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  function onContinue(e: React.FormEvent) {
    e.preventDefault();
    onNext();
  }

  return (
    <div className="space-y-4">
      <form id={ONBOARDING_FORM_ID} onSubmit={onContinue} />
      <StepHint>A name is enough. Description helps patients pick the right area.</StepHint>

      {suggestions.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            Suggested for your clinic
          </p>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((name) => (
              <SuggestionChip
                key={name}
                label={name}
                disabled={addingName === name}
                onClick={() => void addSuggested(name)}
              />
            ))}
          </div>
        </div>
      ) : null}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : specialties.length === 0 ? (
        <div className="rounded-2xl border border-border bg-card p-5">
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                <Layers className="size-5" strokeWidth={1.75} />
              </div>
              <div>
                <p className="text-sm font-medium text-navy">Add an area of care</p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  Skip this if you don&apos;t use specialties. You can add them later.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={() => openCreate()}>
                <Plus className="size-4" /> Add specialty
              </Button>
              <ImportTriggerButton recordType="specialties" />
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-2 rounded-2xl border border-border bg-card p-4">
          {specialties.map((specialty) => (
            <div
              key={specialty.id}
              className="flex items-center justify-between rounded-xl border border-border px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-navy">{specialty.name}</p>
                {specialty.description ? (
                  <p className="truncate text-xs text-muted-foreground">
                    {specialty.description}
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  type="button"
                  onClick={() => openEdit(specialty)}
                >
                  <Pencil className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  type="button"
                  onClick={() => void onRemove(specialty.id)}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => openCreate()}>
              <Plus className="size-4" /> Add another specialty
            </Button>
            <ImportTriggerButton recordType="specialties" />
          </div>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit specialty" : "Add specialty"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={saveSpecialty} className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="specialty-name">Name</Label>
              <Input
                id="specialty-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Cosmetic Dermatology"
                aria-invalid={Boolean(nameError)}
              />
              {nameError ? <p className="text-xs text-destructive">{nameError}</p> : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="specialty-description">
                Description{" "}
                <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Textarea
                id="specialty-description"
                rows={3}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="A short note patients might see — you can leave this blank."
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={create.isPending || update.isPending}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
