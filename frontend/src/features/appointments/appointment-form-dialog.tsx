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
  useCreateAppointment,
  useDoctors,
  useDoctorSchedule,
  useInsurancePlans,
  usePatients,
  useServices,
  useUpdateAppointment,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
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
  const { data: patientsData } = usePatients({ limit: 100 });
  const { data: doctorsData } = useDoctors({ limit: 100 });
  const { data: servicesData } = useServices({ is_active: true, limit: 100 });
  const { data: insuranceData } = useInsurancePlans({ limit: 100 });
  const create = useCreateAppointment();
  const update = useUpdateAppointment();
  const [patientQuery, setPatientQuery] = useState("");

  const patients = patientsData?.results ?? [];
  const doctors = doctorsData?.results ?? [];
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

  const patientItems: SelectOption[] = useMemo(() => {
    const q = patientQuery.trim().toLowerCase();
    return patients
      .filter((p) => {
        if (p.id === selectedPatientId) return true;
        if (!q) return true;
        return (
          p.full_name.toLowerCase().includes(q) ||
          p.phone.toLowerCase().includes(q) ||
          p.email.toLowerCase().includes(q)
        );
      })
      .map((p) => ({
        value: p.id,
        label: p.phone ? `${p.full_name} · ${p.phone}` : p.full_name,
      }));
  }, [patients, patientQuery, selectedPatientId]);

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
            {patients.length > 8 ? (
              <Input
                placeholder="Filter patients…"
                value={patientQuery}
                onChange={(e) => setPatientQuery(e.target.value)}
              />
            ) : null}
            <Controller
              control={form.control}
              name="patient_id"
              render={({ field }) => (
                <FieldSelect
                  value={field.value}
                  onChange={field.onChange}
                  items={patientItems}
                  placeholder="Select patient"
                />
              )}
            />
            {errors.patient_id ? (
              <p className="text-xs text-destructive">{errors.patient_id.message}</p>
            ) : !patients.length ? (
              <p className="text-xs text-muted-foreground">
                No patients yet — add one from the Patients page first.
              </p>
            ) : null}
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
          {hoursHint ? (
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
