"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Pencil, Plus, Trash2, UserRound } from "lucide-react";
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
import { ImportGuide } from "@/features/importer/import-guide";
import { ImportTriggerButton } from "@/features/importer/import-trigger-button";
import { StepHint } from "@/features/onboarding/step-hint";
import {
  useCreateDoctor,
  useDeleteDoctor,
  useDoctors,
  useUpdateDoctor,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { Doctor } from "@/types/api";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

type ProviderForm = {
  full_name: string;
  title: string;
  bio: string;
  languages: string;
};

const EMPTY_FORM: ProviderForm = { full_name: "", title: "", bio: "", languages: "" };

export function ProvidersStep({ onNext }: OnboardingStepProps) {
  const { data, isLoading } = useDoctors({ limit: 100 });
  const create = useCreateDoctor();
  const update = useUpdateDoctor();
  const remove = useDeleteDoctor();

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Doctor | null>(null);
  const [form, setForm] = useState<ProviderForm>(EMPTY_FORM);
  const [nameError, setNameError] = useState("");

  const providers = data?.results ?? [];

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setNameError("");
    setOpen(true);
  }

  function openEdit(doctor: Doctor) {
    setEditing(doctor);
    setForm({
      full_name: doctor.full_name,
      title: doctor.title,
      bio: doctor.bio,
      languages: doctor.languages?.join(", ") ?? "",
    });
    setNameError("");
    setOpen(true);
  }

  async function saveProvider(e: React.FormEvent) {
    e.preventDefault();
    if (!form.full_name.trim()) {
      setNameError("Please enter the provider's name.");
      return;
    }
    setNameError("");
    const payload = {
      full_name: form.full_name.trim(),
      title: form.title.trim(),
      bio: form.bio.trim(),
      languages: form.languages
        ? form.languages.split(",").map((s) => s.trim()).filter(Boolean)
        : [],
    };
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: payload });
        toast.success("Provider updated");
      } else {
        await create.mutateAsync(payload);
        toast.success("Provider added");
      }
      setOpen(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function onRemove(id: string) {
    try {
      await remove.mutateAsync(id);
      toast.success("Provider removed");
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
      <StepHint>
        Add the clinicians patients can book with. Name is enough to continue —
        credentials, bio, and languages are optional. You can type them in or
        import a spreadsheet.
      </StepHint>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : providers.length === 0 ? (
        <div className="space-y-4 rounded-2xl border border-border bg-card p-5">
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                <UserRound className="size-5" strokeWidth={1.75} />
              </div>
              <div>
                <p className="text-sm font-medium text-navy">Add your first provider</p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  One clinician is enough. You can add more later.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={openCreate}>
                <Plus className="size-4" /> Add provider
              </Button>
              <ImportTriggerButton recordType="providers" />
            </div>
          </div>
          <ImportGuide recordType="providers" compact />
        </div>
      ) : (
        <div className="space-y-2 rounded-2xl border border-border bg-card p-4">
          {providers.map((doctor) => (
            <div
              key={doctor.id}
              className="flex items-center justify-between rounded-xl border border-border px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-navy">
                  {doctor.full_name}
                </p>
                {doctor.title ? (
                  <p className="truncate text-xs text-muted-foreground">{doctor.title}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-1">
                <Button variant="ghost" size="icon-sm" type="button" onClick={() => openEdit(doctor)}>
                  <Pencil className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  type="button"
                  onClick={() => onRemove(doctor.id)}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={openCreate}>
              <Plus className="size-4" /> Add another provider
            </Button>
            <ImportTriggerButton recordType="providers" />
          </div>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit provider" : "Add provider"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={saveProvider} className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="provider-name">Name</Label>
              <Input
                id="provider-name"
                value={form.full_name}
                onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
                placeholder="Dr. Chloe Bennett"
                aria-invalid={Boolean(nameError)}
              />
              {nameError ? <p className="text-xs text-destructive">{nameError}</p> : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="provider-title">
                Credentials / title{" "}
                <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id="provider-title"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder="MD, FAAD — Medical & Surgical Dermatology"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="provider-bio">
                Bio <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Textarea
                id="provider-bio"
                rows={3}
                value={form.bio}
                onChange={(e) => setForm((f) => ({ ...f, bio: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="provider-languages">
                Languages{" "}
                <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id="provider-languages"
                value={form.languages}
                onChange={(e) => setForm((f) => ({ ...f, languages: e.target.value }))}
                placeholder="English, Spanish"
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
