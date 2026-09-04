"use client";

import { useState } from "react";
import { toast } from "sonner";
import { ClipboardList, Pencil, Plus, Trash2 } from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CARE_CATEGORIES } from "@/constants";
import { ImportTriggerButton } from "@/features/importer/import-trigger-button";
import { ensureDoctorCatalogLinks } from "@/features/onboarding/doctor-catalog-links";
import { ProviderAssignmentChips } from "@/features/onboarding/provider-assignment";
import { StepHint } from "@/features/onboarding/step-hint";
import { SuggestionChip } from "@/features/onboarding/suggestion-chip";
import {
  suggestedServiceTemplates,
  type ServiceTemplate,
} from "@/features/onboarding/service-templates";
import {
  useCreateService,
  useDeleteService,
  useDoctors,
  useServices,
  useSpecialties,
  useUpdateDoctor,
  useUpdateService,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import type { Service } from "@/types/api";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

function formatPrice(cents: number | null) {
  if (cents == null) return null;
  return `$${(cents / 100).toFixed(2)}`;
}

const NO_CATEGORY = "none";

type ServiceForm = {
  name: string;
  duration_min: string;
  price_dollars: string;
  category: string;
};

const EMPTY_SERVICE: ServiceForm = {
  name: "",
  duration_min: "30",
  price_dollars: "",
  category: "",
};

export function ServicesStep({ onNext }: OnboardingStepProps) {
  const { clinic } = useAuth();
  const { data, isLoading } = useServices({ limit: 100 });
  const { data: specialtiesData } = useSpecialties({ limit: 100 });
  const { data: doctorsData } = useDoctors({ limit: 100 });
  const create = useCreateService();
  const update = useUpdateService();
  const remove = useDeleteService();
  const updateDoctor = useUpdateDoctor();

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Service | null>(null);
  const [form, setForm] = useState<ServiceForm>(EMPTY_SERVICE);
  const [nameError, setNameError] = useState("");
  const [priceError, setPriceError] = useState("");

  const services = data?.results ?? [];
  const specialties = specialtiesData?.results ?? [];
  const doctors = doctorsData?.results ?? [];
  // With exactly one provider there's nothing to disambiguate, so the
  // auto-link-everything shortcut below still applies and no assignment
  // UI is shown. 2+ providers must be assigned explicitly — see
  // doctor-catalog-links.ts for why blanket-linking stopped being safe.
  const needsAssignment = doctors.length > 1;
  const [togglingKey, setTogglingKey] = useState<string | null>(null);
  const existingNames = new Set(services.map((s) => s.name.toLowerCase()));
  const suggestions = suggestedServiceTemplates(
    clinic?.clinic_type,
    specialties.map((s) => s.name)
  ).filter((t) => !existingNames.has(t.name.toLowerCase()));

  function openCreate(template?: ServiceTemplate) {
    setEditing(null);
    setForm(
      template
        ? {
            name: template.name,
            duration_min: String(template.duration_min),
            price_dollars: template.price_cents != null ? (template.price_cents / 100).toFixed(2) : "",
            category: template.category ?? "",
          }
        : EMPTY_SERVICE
    );
    setNameError("");
    setPriceError("");
    setOpen(true);
  }

  function openEdit(service: Service) {
    setEditing(service);
    setForm({
      name: service.name,
      duration_min: String(service.duration_min),
      price_dollars: service.price_cents != null ? (service.price_cents / 100).toFixed(2) : "",
      category: service.category ?? "",
    });
    setNameError("");
    setPriceError("");
    setOpen(true);
  }

  async function saveService(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setNameError("Please enter the service name.");
      return;
    }
    setNameError("");
    const price = form.price_dollars.trim();
    let priceCents: number | null = null;
    if (price) {
      const parsed = Number(price);
      if (!Number.isFinite(parsed) || parsed < 0) {
        setPriceError("Please enter a valid price, like 150.00.");
        return;
      }
      priceCents = Math.round(parsed * 100);
    }
    setPriceError("");
    const payload = {
      name: form.name.trim(),
      duration_min: Math.max(5, parseInt(form.duration_min, 10) || 30),
      price_cents: priceCents,
      category: form.category.trim(),
    };
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: payload });
        toast.success("Service updated");
      } else {
        await create.mutateAsync(payload);
        toast.success("Service added");
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

  async function toggleDoctorService(doctorId: string, serviceId: string) {
    const doctor = doctors.find((d) => d.id === doctorId);
    if (!doctor) return;
    const has = doctor.service_ids.includes(serviceId);
    const service_ids = has
      ? doctor.service_ids.filter((id) => id !== serviceId)
      : [...doctor.service_ids, serviceId];
    setTogglingKey(`${doctorId}:${serviceId}`);
    try {
      await updateDoctor.mutateAsync({ id: doctorId, input: { service_ids } });
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setTogglingKey(null);
    }
  }

  async function onContinue(e: React.FormEvent) {
    e.preventDefault();
    if (services.length === 0) {
      toast.error("Add at least one service before continuing.");
      return;
    }
    if (needsAssignment) {
      const unassigned = services.filter(
        (s) => !doctors.some((d) => d.service_ids.includes(s.id))
      );
      if (unassigned.length > 0) {
        toast.error(
          `Assign at least one provider to: ${unassigned.map((s) => s.name).join(", ")}.`
        );
        return;
      }
      onNext();
      return;
    }
    try {
      await ensureDoctorCatalogLinks({
        doctors,
        specialties: [],
        services,
        updateDoctor: (args) => updateDoctor.mutateAsync(args),
        kind: "services",
      });
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div className="space-y-6">
      <form id={ONBOARDING_FORM_ID} onSubmit={onContinue} />
      <StepHint>These are what patients actually book.</StepHint>

      <div className="space-y-3 rounded-2xl border border-border bg-card p-5">
        {suggestions.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Suggested for you</p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((template) => (
                <SuggestionChip
                  key={template.name}
                  label={template.name}
                  onClick={() => openCreate(template)}
                />
              ))}
            </div>
          </div>
        ) : null}

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : services.length === 0 ? (
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                <ClipboardList className="size-5" strokeWidth={1.75} />
              </div>
              <div>
                <p className="text-sm font-medium text-navy">Add a bookable service</p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  Name, duration, and an optional price. You can import a list instead.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={() => openCreate()}>
                <Plus className="size-4" /> Add service
              </Button>
              <ImportTriggerButton recordType="services" />
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {services.map((service) => (
              <div
                key={service.id}
                className="rounded-xl border border-border bg-card px-4 py-3"
              >
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-navy">{service.name}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {service.duration_min} min
                      {formatPrice(service.price_cents) ? ` · ${formatPrice(service.price_cents)}` : ""}
                      {service.category ? ` · ${service.category}` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button variant="ghost" size="icon-sm" type="button" onClick={() => openEdit(service)}>
                      <Pencil className="size-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon-sm" type="button" onClick={() => onRemove(service.id)}>
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </div>
                {needsAssignment ? (
                  <ProviderAssignmentChips
                    doctors={doctors}
                    selectedIds={doctors
                      .filter((d) => d.service_ids.includes(service.id))
                      .map((d) => d.id)}
                    onToggle={(doctorId) => void toggleDoctorService(doctorId, service.id)}
                    pending={doctors.some(
                      (d) => togglingKey === `${d.id}:${service.id}` && updateDoctor.isPending
                    )}
                  />
                ) : null}
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={() => openCreate()}>
                <Plus className="size-4" /> Add another service
              </Button>
              <ImportTriggerButton recordType="services" />
            </div>
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit service" : "Add service"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={saveService} className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="service-name">Service name</Label>
              <Input
                id="service-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Acne Consultation"
                aria-invalid={Boolean(nameError)}
              />
              {nameError ? <p className="text-xs text-destructive">{nameError}</p> : null}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="service-duration">Duration (min)</Label>
                <Input
                  id="service-duration"
                  type="number"
                  min={5}
                  value={form.duration_min}
                  onChange={(e) => setForm((f) => ({ ...f, duration_min: e.target.value }))}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="service-price">
                  Price <span className="font-normal text-muted-foreground">(optional)</span>
                </Label>
                <Input
                  id="service-price"
                  value={form.price_dollars}
                  onChange={(e) => setForm((f) => ({ ...f, price_dollars: e.target.value }))}
                  placeholder="150.00"
                  aria-invalid={Boolean(priceError)}
                />
                {priceError ? <p className="text-xs text-destructive">{priceError}</p> : null}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="service-category">
                Category <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Select
                value={form.category || NO_CATEGORY}
                onValueChange={(next) =>
                  setForm((f) => ({ ...f, category: next && next !== NO_CATEGORY ? next : "" }))
                }
                items={[
                  { value: NO_CATEGORY, label: "No category" },
                  ...CARE_CATEGORIES.map((c) => ({ value: c, label: c })),
                ]}
              >
                <SelectTrigger id="service-category" className="w-full">
                  <SelectValue placeholder="No category" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_CATEGORY}>No category</SelectItem>
                  {CARE_CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
