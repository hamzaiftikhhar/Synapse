"use client";

import { useEffect, useMemo, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Textarea } from "@/components/ui/textarea";
import {
  useAvailableSlots,
  useCreateAppointment,
  useCreatePatient,
  useDoctors,
  useDoctorSchedule,
  useInsurancePlans,
  usePatients,
  useServices,
  useUpdateAppointment,
} from "@/hooks/api";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { getApiErrorMessage } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import {
  addMinutesIso,
  clinicLocalToIso,
  clinicTodayDate,
  durationMinutes,
  isoToClinicParts,
  mondayFirstWeekday,
} from "@/lib/timezone";
import type { Appointment } from "@/types/api";
import {
  APPOINTMENT_STATUSES,
  BOOKING_SOURCES,
  CREATE_SOURCES,
  SOURCE_LABEL,
  STATUS_LABEL,
} from "./constants";

const NONE = "none";

const schema = z.object({
  patient_id: z.string().min(1, "Choose a patient"),
  service_id: z.string(),
  doctor_id: z.string().min(1, "Choose a doctor"),
  date: z.string().min(1, "Choose a date"),
  time: z.string().regex(/^\d{2}:\d{2}$/, "Choose a time"),
  duration_min: z.coerce.number().min(5).max(480),
  status: z.string(),
  source: z.string(),
  insurance_plan_id: z.string(),
  notes: z.string(),
});

type FormValues = z.infer<typeof schema>;

type SelectOption = { value: string; label: string };

function FieldSelect({
  value,
  onChange,
  items,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  items: SelectOption[];
  placeholder: string;
  disabled?: boolean;
}) {
  return (
    <Select
      value={value || null}
      onValueChange={(next) => {
        if (next) onChange(next);
      }}
      items={items}
      disabled={disabled}
    >
      <SelectTrigger className="w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function hhmm(value: string): string {
  return value.slice(0, 5);
}

export function AppointmentFormDialog({
  open,
  onOpenChange,
  editing,
  timeZone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: Appointment | null;
  timeZone: string;
}) {
  const [patientQuery, setPatientQuery] = useState("");
  const debouncedPatientQuery = useDebouncedValue(patientQuery, 300);
  const { data: patientsData, isFetching: patientsLoading } = usePatients({
    search: debouncedPatientQuery || undefined,
    limit: 20,
  });
  const { data: doctorsData } = useDoctors({ limit: 100 });
  const { data: servicesData } = useServices({ is_active: true, limit: 100 });
  const { data: insuranceData } = useInsurancePlans({ limit: 100 });
  const create = useCreateAppointment();
  const update = useUpdateAppointment();
  const createPatient = useCreatePatient();
  const [addingPatient, setAddingPatient] = useState(false);
  const [newPatient, setNewPatient] = useState({
    first_name: "",
    last_name: "",
    phone: "",
    email: "",
  });
  const [newPatientErrors, setNewPatientErrors] = useState<Record<string, string>>({});

  const patients = useMemo(() => patientsData?.results ?? [], [patientsData]);
  const doctors = useMemo(() => doctorsData?.results ?? [], [doctorsData]);
  const services = servicesData?.results ?? [];
  const insurancePlans = insuranceData?.results ?? [];

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      patient_id: "",
      service_id: NONE,
      doctor_id: "",
      date: clinicTodayDate(timeZone),
      time: "09:00",
      duration_min: 30,
      status: "confirmed",
      source: "admin",
      insurance_plan_id: NONE,
      notes: "",
    },
  });

  useEffect(() => {
    if (!open) return;
    setPatientQuery("");
    setAddingPatient(false);
    setNewPatient({ first_name: "", last_name: "", phone: "", email: "" });
    setNewPatientErrors({});
    if (editing) {
      const parts = isoToClinicParts(editing.start_time, timeZone);
      form.reset({
        patient_id: editing.patient_id,
        service_id: editing.service_id || NONE,
        doctor_id: editing.doctor_id,
        date: parts.date,
        time: parts.time,
        duration_min: durationMinutes(editing.start_time, editing.end_time),
        status: editing.status,
        source: editing.source,
        insurance_plan_id: editing.insurance_plan_id || NONE,
        notes: editing.notes || "",
      });
      return;
    }
    form.reset({
      patient_id: "",
      service_id: NONE,
      doctor_id: "",
      date: clinicTodayDate(timeZone),
      time: "09:00",
      duration_min: 30,
      status: "confirmed",
      source: "admin",
      insurance_plan_id: NONE,
      notes: "",
    });
  }, [open, editing, timeZone, form]);

  const serviceId = useWatch({ control: form.control, name: "service_id" });
  const doctorId = useWatch({ control: form.control, name: "doctor_id" });
  const date = useWatch({ control: form.control, name: "date" });
  const selectedPatientId = useWatch({ control: form.control, name: "patient_id" });

  const { data: schedule } = useDoctorSchedule(doctorId || null);
  const { data: availableSlots, isFetching: slotsLoading } = useAvailableSlots(
    doctorId || null,
    date || null,
    editing?.id
  );

  const eligibleDoctors = useMemo(() => {
    const active = doctors.filter((d) => {
      if (editing && d.id === editing.doctor_id) return true;
      return d.is_active && d.is_accepting_patients;
    });
    if (!serviceId || serviceId === NONE) return active;
    return active.filter(
      (d) => d.service_ids.includes(serviceId) || (editing && d.id === editing.doctor_id)
    );
  }, [doctors, serviceId, editing]);

  function onServiceChange(next: string) {
    form.setValue("service_id", next);
    const service = services.find((s) => s.id === next);
    if (service?.duration_min) {
      form.setValue("duration_min", service.duration_min);
    }
    const currentDoctor = form.getValues("doctor_id");
    if (!currentDoctor) return;
    const stillEligible =
      next === NONE ||
      doctors.some(
        (d) =>
          d.id === currentDoctor &&
          (d.service_ids.includes(next) || (editing && d.id === editing.doctor_id))
      );
    if (!stillEligible) form.setValue("doctor_id", "");
  }

  const hoursHint = useMemo(() => {
    if (!date || !schedule?.length) return null;
    const weekday = mondayFirstWeekday(date);
    const windows = schedule.filter((s) => s.day_of_week === weekday && s.is_active);
    if (!windows.length) return "This doctor has no hours on that day.";
    const range = windows
      .map((w) => `${hhmm(w.start_time)}–${hhmm(w.end_time)}`)
      .join(", ");
    const slot = windows[0]?.slot_duration_min;
    return slot ? `Hours: ${range} · ${slot} min slots` : `Hours: ${range}`;
  }, [date, schedule]);

  // Real availability (schedule minus leave minus already-booked
  // appointments) -- previously the dialog only showed the doctor's
  // recurring weekly hours as text (hoursHint above), with no check
  // against actual bookings, so staff could double-book a doctor or pick
  // a time outside their hours with zero warning (see ROADMAP.md).
  const slotTimes = useMemo(() => {
    if (!availableSlots?.length) return [];
    return availableSlots.map((slot) => ({
      time: isoToClinicParts(slot.start, timeZone).time,
      label: slot.label,
    }));
  }, [availableSlots, timeZone]);

  const currentTime = useWatch({ control: form.control, name: "time" });

  const patientItems: SelectOption[] = useMemo(() => {
    // Search is server-side now (usePatients({ search }), debounced) --
    // this just shapes the results, plus keeps the currently-selected
    // patient visible even if a new search query no longer matches them
    // (e.g. editing an existing appointment, or just picked someone and
    // kept typing).
    const items = patients.map((p) => ({
      value: p.id,
      label: p.phone ? `${p.full_name} · ${p.phone}` : p.full_name,
    }));
    if (selectedPatientId && !items.some((i) => i.value === selectedPatientId)) {
      const pinnedName =
        editing && editing.patient_id === selectedPatientId ? editing.patient_name : null;
      if (pinnedName) items.unshift({ value: selectedPatientId, label: pinnedName });
    }
    return items;
  }, [patients, selectedPatientId, editing]);

  async function submitNewPatient() {
    const errors: Record<string, string> = {};
    if (!newPatient.first_name.trim()) errors.first_name = "First name is required.";
    if (!newPatient.last_name.trim()) errors.last_name = "Last name is required.";
    if (newPatient.phone.trim().length < 5) errors.phone = "A valid phone number is required.";
    if (newPatient.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(newPatient.email.trim())) {
      errors.email = "Enter a valid email, or leave it blank.";
    }
    setNewPatientErrors(errors);
    if (Object.keys(errors).length > 0) return;
    try {
      const created = await createPatient.mutateAsync({
        first_name: newPatient.first_name.trim(),
        last_name: newPatient.last_name.trim(),
        phone: newPatient.phone.trim(),
        email: newPatient.email.trim() || undefined,
      });
      form.setValue("patient_id", created.id);
      setAddingPatient(false);
      setNewPatient({ first_name: "", last_name: "", phone: "", email: "" });
      setNewPatientErrors({});
      toast.success("Patient added");
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not add patient"));
    }
  }

  const serviceItems: SelectOption[] = [
    { value: NONE, label: "No service" },
    ...services.map((s) => ({
      value: s.id,
      label: s.duration_min ? `${s.name} · ${s.duration_min} min` : s.name,
    })),
  ];

  const doctorItems: SelectOption[] = eligibleDoctors.map((d) => ({
    value: d.id,
    label: d.title ? `${d.full_name}, ${d.title}` : d.full_name,
  }));

  const insuranceItems: SelectOption[] = [
    { value: NONE, label: "None" },
    ...insurancePlans.map((plan) => ({
      value: plan.id,
      label: plan.plan_name
        ? `${plan.provider_name} — ${plan.plan_name}`
        : plan.provider_name,
    })),
  ];

  const statusItems: SelectOption[] = APPOINTMENT_STATUSES.map((status) => ({
    value: status,
    label: STATUS_LABEL[status],
  }));

  const sourceItems: SelectOption[] = (editing ? BOOKING_SOURCES : CREATE_SOURCES).map(
    (source) => ({ value: source, label: SOURCE_LABEL[source] })
  );

  async function onSubmit(values: FormValues) {
    const start = clinicLocalToIso(values.date, values.time, timeZone);
    const end = addMinutesIso(start, values.duration_min);
    const payload = {
      patient_id: values.patient_id,
      doctor_id: values.doctor_id,
      service_id: values.service_id === NONE ? null : values.service_id,
      insurance_plan_id:
        values.insurance_plan_id === NONE ? null : values.insurance_plan_id,
      start_time: start,
      end_time: end,
      status: values.status,
      source: values.source,
      notes: values.notes.trim(),
    };
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: payload });
        toast.success("Appointment updated");
      } else {
        await create.mutateAsync(payload);
        toast.success("Appointment booked");
      }
      onOpenChange(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not save appointment"));
    }
  }

  const saving = create.isPending || update.isPending;
  const errors = form.formState.errors;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit appointment" : "New appointment"}</DialogTitle>
          <DialogDescription>
            Times are in the clinic timezone ({timeZone}).
            {editing?.confirmation_code
              ? ` Confirmation ${editing.confirmation_code}.`
              : ""}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3">
          <div className="space-y-1.5">
            <Label>Patient</Label>
            <Input
              placeholder="Search by name, phone, or email…"
              value={patientQuery}
              onChange={(e) => setPatientQuery(e.target.value)}
            />
            <Controller
              control={form.control}
              name="patient_id"
              render={({ field }) => (
                <FieldSelect
                  value={field.value}
                  onChange={field.onChange}
                  items={patientItems}
                  placeholder={patientsLoading ? "Searching…" : "Select patient"}
                />
              )}
            />
            {errors.patient_id ? (
              <p className="text-xs text-destructive">{errors.patient_id.message}</p>
            ) : null}

            {!addingPatient ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setAddingPatient(true);
                  // A name typed to search is almost always this new
                  // patient's own name -- carry it over as a first name
                  // guess rather than making them retype it.
                  if (patientQuery.trim() && !newPatient.first_name) {
                    setNewPatient((p) => ({ ...p, first_name: patientQuery.trim() }));
                  }
                }}
              >
                + Add new patient
              </Button>
            ) : (
              <div className="space-y-2 rounded-lg border border-border p-3">
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">First name</Label>
                    <Input
                      value={newPatient.first_name}
                      onChange={(e) =>
                        setNewPatient((p) => ({ ...p, first_name: e.target.value }))
                      }
                      aria-invalid={Boolean(newPatientErrors.first_name)}
                    />
                    {newPatientErrors.first_name ? (
                      <p className="text-xs text-destructive">{newPatientErrors.first_name}</p>
                    ) : null}
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Last name</Label>
                    <Input
                      value={newPatient.last_name}
                      onChange={(e) =>
                        setNewPatient((p) => ({ ...p, last_name: e.target.value }))
                      }
                      aria-invalid={Boolean(newPatientErrors.last_name)}
                    />
                    {newPatientErrors.last_name ? (
                      <p className="text-xs text-destructive">{newPatientErrors.last_name}</p>
                    ) : null}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">Phone</Label>
                    <Input
                      value={newPatient.phone}
                      onChange={(e) => setNewPatient((p) => ({ ...p, phone: e.target.value }))}
                      placeholder="+1 555 123 4567"
                      aria-invalid={Boolean(newPatientErrors.phone)}
                    />
                    {newPatientErrors.phone ? (
                      <p className="text-xs text-destructive">{newPatientErrors.phone}</p>
                    ) : null}
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">
                      Email <span className="font-normal text-muted-foreground">(optional)</span>
                    </Label>
                    <Input
                      value={newPatient.email}
                      onChange={(e) => setNewPatient((p) => ({ ...p, email: e.target.value }))}
                      aria-invalid={Boolean(newPatientErrors.email)}
                    />
                    {newPatientErrors.email ? (
                      <p className="text-xs text-destructive">{newPatientErrors.email}</p>
                    ) : null}
                  </div>
                </div>
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => setAddingPatient(false)}>
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    disabled={createPatient.isPending}
                    onClick={() => void submitNewPatient()}
                  >
                    {createPatient.isPending ? "Adding…" : "Add patient"}
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Service</Label>
              <Controller
                control={form.control}
                name="service_id"
                render={({ field }) => (
                  <FieldSelect
                    value={field.value}
                    onChange={onServiceChange}
                    items={serviceItems}
                    placeholder="Select service"
                  />
                )}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Doctor</Label>
              <Controller
                control={form.control}
                name="doctor_id"
                render={({ field }) => (
                  <FieldSelect
                    value={field.value}
                    onChange={field.onChange}
                    items={doctorItems}
                    placeholder={
                      eligibleDoctors.length ? "Select doctor" : "No doctors for this service"
                    }
                    disabled={!eligibleDoctors.length}
                  />
                )}
              />
              {errors.doctor_id ? (
                <p className="text-xs text-destructive">{errors.doctor_id.message}</p>
              ) : null}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label>Date</Label>
              <Input type="date" {...form.register("date")} />
            </div>
            <div className="space-y-1.5">
              <Label>Start</Label>
              <Input type="time" {...form.register("time")} />
            </div>
            <div className="space-y-1.5">
              <Label>Duration (min)</Label>
              <Input type="number" min={5} step={5} {...form.register("duration_min")} />
            </div>
          </div>
          {doctorId && date ? (
            <div className="space-y-1.5">
              {slotsLoading ? (
                <p className="text-xs text-muted-foreground">Checking availability…</p>
              ) : slotTimes.length > 0 ? (
                <>
                  <Label className="text-xs text-muted-foreground">
                    Available times — or type a time above to override
                  </Label>
                  <div className="flex flex-wrap gap-1.5">
                    {slotTimes.map((slot) => (
                      <button
                        key={slot.time}
                        type="button"
                        onClick={() => form.setValue("time", slot.time)}
                        className={cn(
                          "rounded-full border px-2.5 py-1 text-xs transition-colors",
                          currentTime === slot.time
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
                        )}
                      >
                        {slot.label}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <p className="text-xs text-destructive">
                  {hoursHint === "This doctor has no hours on that day."
                    ? hoursHint
                    : "This doctor is fully booked that day."}{" "}
                  You can still enter a time above, but double-check with the doctor first.
                </p>
              )}
            </div>
          ) : hoursHint ? (
            <p className="text-xs text-muted-foreground">{hoursHint}</p>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Status</Label>
              <Controller
                control={form.control}
                name="status"
                render={({ field }) => (
                  <FieldSelect
                    value={field.value}
                    onChange={field.onChange}
                    items={statusItems}
                    placeholder="Status"
                  />
                )}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Source</Label>
              <Controller
                control={form.control}
                name="source"
                render={({ field }) => (
                  <FieldSelect
                    value={field.value}
                    onChange={field.onChange}
                    items={sourceItems}
                    placeholder="Source"
                  />
                )}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Insurance</Label>
            <Controller
              control={form.control}
              name="insurance_plan_id"
              render={({ field }) => (
                <FieldSelect
                  value={field.value}
                  onChange={field.onChange}
                  items={insuranceItems}
                  placeholder="Optional"
                />
              )}
            />
          </div>

          <div className="space-y-1.5">
            <Label>Notes</Label>
            <Textarea rows={3} {...form.register("notes")} />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : editing ? "Save changes" : "Book appointment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
