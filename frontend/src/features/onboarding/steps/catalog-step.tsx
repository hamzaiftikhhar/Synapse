"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Pencil, Plus, Trash2, X } from "lucide-react";
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
import { SpecialtyServicePicker } from "@/components/dashboard/specialty-service-picker";
import {
  useCreateService,
  useCreateSpecialty,
  useDeleteService,
  useDeleteSpecialty,
  useDoctors,
  useServices,
  useSpecialties,
  useUpdateDoctor,
  useUpdateService,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { Doctor, Service, Specialty } from "@/types/api";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

function formatPrice(cents: number | null) {
  if (cents == null) return null;
  return `$${(cents / 100).toFixed(2)}`;
}

function SpecialtiesSection() {
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

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-sm font-medium text-navy">Specialties</Label>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Broad areas of care — e.g. Dermatology, Orthodontics, Primary Care.
        </p>
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
    </div>
  );
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

function ServicesSection() {
  const { data, isLoading } = useServices({ limit: 100 });
  const create = useCreateService();
  const update = useUpdateService();
  const remove = useDeleteService();

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Service | null>(null);
  const [form, setForm] = useState<ServiceForm>(EMPTY_SERVICE);
  const [nameError, setNameError] = useState("");
  const [priceError, setPriceError] = useState("");

  const services = data?.results ?? [];

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_SERVICE);
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

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-sm font-medium text-navy">Services</Label>
        <p className="mt-0.5 text-xs text-muted-foreground">
          What patients can actually book — e.g. Acne Consultation, Botox, Teeth Cleaning.
        </p>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : services.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium text-navy">Add the services patients can book</p>
          <Button type="button" className="mt-4" onClick={openCreate}>
            <Plus className="size-4" /> Add service
          </Button>
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
          <Button type="button" variant="outline" onClick={openCreate}>
            <Plus className="size-4" /> Add another service
          </Button>
        </div>
      )}

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

type DoctorLinks = { specialtyIds: string[]; serviceIds: string[] };

/** Which providers offer what — closes the gap between "providers exist"
 * and "providers are actually bookable". Default booking mode filters
 * doctors by specialty (see apps/chatbot/booking/serializers.py), so a
 * provider left unlinked to any specialty/service is invisible to patients
 * even though onboarding shows both as "done". Untouched providers default
 * to everything checked (most small clinics have every provider do
 * everything) so simply clicking Continue still produces a bookable clinic;
 * the owner only needs to uncheck what doesn't apply. */
function ProviderLinksSection({
  doctors,
  specialties,
  services,
  edits,
  setEdits,
}: {
  doctors: Doctor[];
  specialties: Specialty[];
  services: Service[];
  edits: Record<string, DoctorLinks>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, DoctorLinks>>>;
}) {
  function effectiveLinks(doctor: Doctor): DoctorLinks {
    if (edits[doctor.id]) return edits[doctor.id];
    if (doctor.specialty_ids.length || doctor.service_ids.length) {
      return { specialtyIds: doctor.specialty_ids, serviceIds: doctor.service_ids };
    }
    return { specialtyIds: specialties.map((s) => s.id), serviceIds: services.map((s) => s.id) };
  }

  function toggle(doctor: Doctor, kind: "specialtyIds" | "serviceIds", id: string) {
    const current = effectiveLinks(doctor);
    const has = current[kind].includes(id);
    const next = has ? current[kind].filter((x) => x !== id) : [...current[kind], id];
    setEdits((prev) => ({ ...prev, [doctor.id]: { ...current, [kind]: next } }));
  }

  if (doctors.length === 0 || (specialties.length === 0 && services.length === 0)) return null;

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-sm font-medium text-navy">Which providers offer these?</Label>
        <p className="mt-0.5 text-xs text-muted-foreground">
          We&apos;ve checked everything by default — uncheck anything a provider doesn&apos;t offer.
        </p>
      </div>
      <div className="space-y-3">
        {doctors.map((doctor) => {
          const links = effectiveLinks(doctor);
          return (
            <div key={doctor.id} className="rounded-xl border border-border p-4">
              <p className="mb-2 text-sm font-medium text-navy">{doctor.full_name}</p>
              <SpecialtyServicePicker
                specialties={specialties}
                services={services}
                selectedSpecialtyIds={links.specialtyIds}
                selectedServiceIds={links.serviceIds}
                onToggleSpecialty={(id) => toggle(doctor, "specialtyIds", id)}
                onToggleService={(id) => toggle(doctor, "serviceIds", id)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CatalogStep({ onNext }: OnboardingStepProps) {
  const { data: doctorsData } = useDoctors({ limit: 100 });
  const { data: specialtiesData } = useSpecialties({ limit: 100 });
  const { data: servicesData } = useServices({ limit: 100 });
  const updateDoctor = useUpdateDoctor();

  const doctors = doctorsData?.results ?? [];
  const specialties = specialtiesData?.results ?? [];
  const services = servicesData?.results ?? [];

  const [linkEdits, setLinkEdits] = useState<Record<string, DoctorLinks>>({});

  async function onContinue(e: React.FormEvent) {
    e.preventDefault();
    try {
      await Promise.all(
        doctors.map((doctor) => {
          const edited = linkEdits[doctor.id];
          const links: DoctorLinks =
            edited ??
            (doctor.specialty_ids.length || doctor.service_ids.length
              ? { specialtyIds: doctor.specialty_ids, serviceIds: doctor.service_ids }
              : { specialtyIds: specialties.map((s) => s.id), serviceIds: services.map((s) => s.id) });
          return updateDoctor.mutateAsync({
            id: doctor.id,
            input: { specialty_ids: links.specialtyIds, service_ids: links.serviceIds },
          });
        })
      );
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div className="space-y-8">
      <form id={ONBOARDING_FORM_ID} onSubmit={onContinue} />
      <SpecialtiesSection />
      <div className="h-px bg-border" />
      <ServicesSection />
      {doctors.length > 0 && (specialties.length > 0 || services.length > 0) ? (
        <>
          <div className="h-px bg-border" />
          <ProviderLinksSection
            doctors={doctors}
            specialties={specialties}
            services={services}
            edits={linkEdits}
            setEdits={setLinkEdits}
          />
        </>
      ) : null}
    </div>
  );
}
