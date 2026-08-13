"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Pencil, Plus, Trash2 } from "lucide-react";
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
import { ImportGuide } from "@/features/importer/import-guide";
import { ImportTriggerButton } from "@/features/importer/import-trigger-button";
import { ensureDoctorCatalogLinks } from "@/features/onboarding/doctor-catalog-links";
import { StepHint } from "@/features/onboarding/step-hint";
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

  async function onContinue(e: React.FormEvent) {
    e.preventDefault();
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
      <StepHint>
        Services are what patients actually book. Add them by hand or import a
        spreadsheet — download the sample to see the exact columns.
      </StepHint>

      <div className="space-y-3 rounded-2xl border border-border bg-card p-5">
        {suggestions.length > 0 ? (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">Suggested for you</p>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((template) => (
                <button
                  key={template.name}
                  type="button"
                  onClick={() => openCreate(template)}
                  className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                >
                  <Plus className="size-3" />
                  {template.name}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : services.length === 0 ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={() => openCreate()}>
                <Plus className="size-4" /> Add service
              </Button>
              <ImportTriggerButton recordType="services" />
            </div>
            <ImportGuide recordType="services" compact />
          </div>
        ) : (
          <div className="space-y-2">
            {services.map((service) => (
              <div
                key={service.id}
                className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3"
              >
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
              <Input
                id="service-category"
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                placeholder="e.g. Cosmetic Dermatology"
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
