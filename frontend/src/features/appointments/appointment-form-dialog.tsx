"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Check, Plus, Search, UserRound } from "lucide-react";
import { BirthDatePicker } from "@/components/dob-picker";
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
import { dobIssueMessage, validateDobIso } from "@/lib/dob";
import { normalizePhone, phoneIssueMessage, validatePhone } from "@/lib/phone";
import { cn } from "@/lib/utils";
import {
  addMinutesIso,
  clinicLocalToIso,
  clinicTodayDate,
  durationMinutes,
  isoToClinicParts,
  mondayFirstWeekday,
} from "@/lib/timezone";
import type { Appointment, Patient } from "@/types/api";
import {
  APPOINTMENT_STATUSES,
  BOOKING_SOURCES,
  CREATE_SOURCES,
  SOURCE_LABEL,
  STATUS_LABEL,
} from "./constants";
import { DoctorAvailabilityCalendar } from "./doctor-availability-calendar";

const NONE = "none";

const schema = z.object({
  patient_id: z.string().min(1, "Choose or add a patient"),
  service_id: z.string(),
  doctor_id: z.string().min(1, "Choose a doctor"),
  date: z.string().min(1, "Choose a date"),
  time: z.string().regex(/^\d{2}:\d{2}$/, "Choose an available time"),
  duration_min: z.coerce.number().min(5).max(480),
  status: z.string(),
  source: z.string(),
  insurance_plan_id: z.string(),
  notes: z.string(),
});

type FormValues = z.infer<typeof schema>;
type SelectOption = { value: string; label: string };
type CareLead = "service" | "doctor";

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

function patientLabel(p: Pick<Patient, "full_name" | "phone" | "first_name" | "last_name">) {
  const name =
    p.full_name ||
    [p.first_name, p.last_name].filter(Boolean).join(" ").trim() ||
    "Patient";
  return p.phone ? `${name} · ${p.phone}` : name;
}

function Section({
  step,
  title,
  children,
}: {
  step: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2.5">
      <h3 className="text-[13px] font-medium tracking-tight text-muted-foreground">
        <span className="mr-1.5 tabular-nums text-foreground/40">{step}.</span>
        {title}
      </h3>
      {children}
    </section>
  );
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

  const [careLead, setCareLead] = useState<CareLead>("service");
  const [addingPatient, setAddingPatient] = useState(false);
  const [pinnedPatient, setPinnedPatient] = useState<{
    id: string;
    label: string;
  } | null>(null);
  const [customTimeOpen, setCustomTimeOpen] = useState(false);
  const [newPatient, setNewPatient] = useState({
    first_name: "",
    last_name: "",
    phone: "",
    date_of_birth: "",
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
      time: "",
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
    setCustomTimeOpen(false);
    setCareLead("service");
    setNewPatient({
      first_name: "",
      last_name: "",
      phone: "",
      date_of_birth: "",
      email: "",
    });
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
      setPinnedPatient({
        id: editing.patient_id,
        label: editing.patient_name || "Selected patient",
      });
      setCustomTimeOpen(true);
      return;
    }
    setPinnedPatient(null);
    form.reset({
      patient_id: "",
      service_id: NONE,
      doctor_id: "",
      date: clinicTodayDate(timeZone),
      time: "",
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
  const currentTime = useWatch({ control: form.control, name: "time" });

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

  const eligibleServices = useMemo(() => {
    if (!doctorId) return services;
    const doctor = doctors.find((d) => d.id === doctorId);
    if (!doctor?.service_ids?.length) return services;
    const filtered = services.filter((s) => doctor.service_ids.includes(s.id));
    if (
      editing?.service_id &&
      !filtered.some((s) => s.id === editing.service_id)
    ) {
      const current = services.find((s) => s.id === editing.service_id);
      if (current) return [current, ...filtered];
    }
    return filtered.length ? filtered : services;
  }, [services, doctors, doctorId, editing]);

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
    if (!stillEligible) {
      form.setValue("doctor_id", "");
      form.setValue("time", "");
    }
  }

  function onDoctorChange(next: string) {
    form.setValue("doctor_id", next);
    form.setValue("time", "");
    const currentService = form.getValues("service_id");
    if (!currentService || currentService === NONE) return;
    const doctor = doctors.find((d) => d.id === next);
    if (
      doctor &&
      doctor.service_ids.length > 0 &&
      !doctor.service_ids.includes(currentService) &&
      !(editing && editing.doctor_id === next)
    ) {
      form.setValue("service_id", NONE);
    }
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
    return slot ? `Hours ${range} · ${slot} min grid` : `Hours ${range}`;
  }, [date, schedule]);

  const slotTimes = useMemo(() => {
    if (!availableSlots?.length) return [];
    return availableSlots.map((slot) => {
      const start = isoToClinicParts(slot.start, timeZone).time;
      const end = isoToClinicParts(slot.end, timeZone).time;
      const mins = durationMinutes(slot.start, slot.end);
      return { time: start, end, mins, label: slot.label };
    });
  }, [availableSlots, timeZone]);

  const selectedPatientLabel = useMemo(() => {
    if (!selectedPatientId) return null;
    if (pinnedPatient?.id === selectedPatientId) return pinnedPatient.label;
    const found = patients.find((p) => p.id === selectedPatientId);
    if (found) return patientLabel(found);
    if (editing?.patient_id === selectedPatientId) return editing.patient_name;
    return "Selected patient";
  }, [selectedPatientId, pinnedPatient, patients, editing]);

  function selectPatient(p: Patient) {
    form.setValue("patient_id", p.id, { shouldValidate: true });
    setPinnedPatient({ id: p.id, label: patientLabel(p) });
    setPatientQuery("");
    setAddingPatient(false);
  }

  function clearPatient() {
    form.setValue("patient_id", "");
    setPinnedPatient(null);
  }

  async function submitNewPatient() {
    const errors: Record<string, string> = {};
    if (!newPatient.first_name.trim()) errors.first_name = "Required";
    if (!newPatient.last_name.trim()) errors.last_name = "Required";
    const dobIssue = validateDobIso(newPatient.date_of_birth, { required: true });
    if (dobIssue) errors.date_of_birth = dobIssueMessage(dobIssue);
    const phoneIssue = validatePhone(newPatient.phone, { required: true });
    if (phoneIssue) errors.phone = phoneIssueMessage(phoneIssue);
    if (newPatient.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(newPatient.email.trim())) {
      errors.email = "Invalid email";
    }
    setNewPatientErrors(errors);
    if (Object.keys(errors).length > 0) return;
    try {
      const created = await createPatient.mutateAsync({
        first_name: newPatient.first_name.trim(),
        last_name: newPatient.last_name.trim(),
        phone: normalizePhone(newPatient.phone),
        date_of_birth: newPatient.date_of_birth.trim(),
        email: newPatient.email.trim() || undefined,
      });
      form.setValue("patient_id", created.id, { shouldValidate: true });
      setPinnedPatient({ id: created.id, label: patientLabel(created) });
      setAddingPatient(false);
      setPatientQuery("");
      setNewPatient({
        first_name: "",
        last_name: "",
        phone: "",
        date_of_birth: "",
        email: "",
      });
      setNewPatientErrors({});
      toast.success("Patient added to this booking");
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not add patient"));
    }
  }

  function pickSlot(time: string, mins?: number) {
    form.setValue("time", time, { shouldValidate: true });
    if (mins && mins >= 5) form.setValue("duration_min", mins);
    setCustomTimeOpen(false);
  }

  const clinicToday = clinicTodayDate(timeZone);
  const pickDate = useCallback(
    (next: string) => {
      form.setValue("date", next, { shouldValidate: true });
      form.setValue("time", "");
    },
    [form]
  );

  const serviceItems: SelectOption[] = [
    { value: NONE, label: "Any / no service" },
    ...eligibleServices.map((s) => ({
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
  const showPatientResults =
    !selectedPatientId && (patientQuery.trim().length > 0 || patientsLoading);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader className="pb-1">
          <DialogTitle>{editing ? "Edit appointment" : "New appointment"}</DialogTitle>
          <DialogDescription className="text-xs">
            Times in {timeZone}
            {editing?.confirmation_code
              ? ` · ${editing.confirmation_code}`
              : ""}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5">
          <Section step="1" title="Patient">
            {selectedPatientId && selectedPatientLabel ? (
              <div className="flex items-center gap-2.5 rounded-md border border-border/70 px-2.5 py-2">
                <UserRound className="size-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-foreground">{selectedPatientLabel}</p>
                </div>
                {!editing ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 shrink-0 px-2 text-xs text-muted-foreground"
                    onClick={clearPatient}
                  >
                    Change
                  </Button>
                ) : null}
              </div>
            ) : (
              <>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    placeholder="Search name, phone, or email…"
                    value={patientQuery}
                    onChange={(e) => setPatientQuery(e.target.value)}
                    className="h-9 pl-8"
                    autoFocus={!editing}
                  />
                </div>

                {showPatientResults ? (
                  <div className="max-h-40 overflow-y-auto rounded-md border border-border/70">
                    {patientsLoading ? (
                      <p className="px-2.5 py-2 text-xs text-muted-foreground">Searching…</p>
                    ) : patients.length === 0 ? (
                      <p className="px-2.5 py-2 text-xs text-muted-foreground">
                        No match — add them below.
                      </p>
                    ) : (
                      <ul>
                        {patients.map((p) => (
                          <li key={p.id}>
                            <button
                              type="button"
                              onClick={() => selectPatient(p)}
                              className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-sm hover:bg-muted/50"
                            >
                              <span className="min-w-0 flex-1 truncate">{patientLabel(p)}</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ) : null}

                {!addingPatient ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 gap-1 px-2 text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => {
                      setAddingPatient(true);
                      const q = patientQuery.trim();
                      if (q && !newPatient.first_name) {
                        const parts = q.split(/\s+/);
                        setNewPatient((p) => ({
                          ...p,
                          first_name: parts[0] ?? q,
                          last_name: parts.slice(1).join(" "),
                        }));
                      }
                    }}
                  >
                    <Plus className="size-3.5" />
                    New patient
                  </Button>
                ) : (
                  <div className="space-y-2.5 rounded-md border border-border/70 p-2.5">
                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">First name</Label>
                        <Input
                          className="h-9"
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
                        <Label className="text-xs text-muted-foreground">Last name</Label>
                        <Input
                          className="h-9"
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
                      <div className="space-y-1 sm:col-span-2">
                        <Label className="text-xs text-muted-foreground">Date of birth</Label>
                        <BirthDatePicker
                          id="appt-new-dob"
                          value={newPatient.date_of_birth}
                          onChange={(iso) => {
                            setNewPatient((p) => ({ ...p, date_of_birth: iso }));
                            if (newPatientErrors.date_of_birth) {
                              const issue = validateDobIso(iso, { required: true });
                              setNewPatientErrors((prev) => {
                                const next = { ...prev };
                                if (issue) next.date_of_birth = dobIssueMessage(issue);
                                else delete next.date_of_birth;
                                return next;
                              });
                            }
                          }}
                          invalid={Boolean(newPatientErrors.date_of_birth)}
                          className="w-full"
                        />
                        {newPatientErrors.date_of_birth ? (
                          <p className="text-xs text-destructive">
                            {newPatientErrors.date_of_birth}
                          </p>
                        ) : null}
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">Phone</Label>
                        <Input
                          className="h-9"
                          value={newPatient.phone}
                          onChange={(e) => {
                            const next = e.target.value;
                            setNewPatient((p) => ({ ...p, phone: next }));
                            if (newPatientErrors.phone) {
                              const issue = validatePhone(next, { required: true });
                              setNewPatientErrors((prev) => {
                                const copy = { ...prev };
                                if (issue) copy.phone = phoneIssueMessage(issue);
                                else delete copy.phone;
                                return copy;
                              });
                            }
                          }}
                          placeholder="+1 555 123 4567"
                          aria-invalid={Boolean(newPatientErrors.phone)}
                        />
                        {newPatientErrors.phone ? (
                          <p className="text-xs text-destructive">{newPatientErrors.phone}</p>
                        ) : null}
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">
                          Email <span className="font-normal">(optional)</span>
                        </Label>
                        <Input
                          className="h-9"
                          value={newPatient.email}
                          onChange={(e) =>
                            setNewPatient((p) => ({ ...p, email: e.target.value }))
                          }
                          aria-invalid={Boolean(newPatientErrors.email)}
                        />
                        {newPatientErrors.email ? (
                          <p className="text-xs text-destructive">{newPatientErrors.email}</p>
                        ) : null}
                      </div>
                    </div>
                    <div className="flex justify-end gap-1.5">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8"
                        onClick={() => setAddingPatient(false)}
                      >
                        Cancel
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        className="h-8"
                        disabled={createPatient.isPending}
                        onClick={() => void submitNewPatient()}
                      >
                        {createPatient.isPending ? "Saving…" : "Save & continue"}
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
            {errors.patient_id ? (
              <p className="text-xs text-destructive">{errors.patient_id.message}</p>
            ) : null}
          </Section>

          <Section step="2" title="Care">
            <div className="flex gap-3 text-xs">
              <button
                type="button"
                onClick={() => setCareLead("service")}
                className={cn(
                  "pb-0.5 transition-colors",
                  careLead === "service"
                    ? "border-b border-foreground font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                Service first
              </button>
              <button
                type="button"
                onClick={() => setCareLead("doctor")}
                className={cn(
                  "pb-0.5 transition-colors",
                  careLead === "doctor"
                    ? "border-b border-foreground font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                Doctor first
              </button>
            </div>

            <div className="grid gap-2.5 sm:grid-cols-2">
              {careLead === "service" ? (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Service</Label>
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
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Doctor</Label>
                    <Controller
                      control={form.control}
                      name="doctor_id"
                      render={({ field }) => (
                        <FieldSelect
                          value={field.value}
                          onChange={onDoctorChange}
                          items={doctorItems}
                          placeholder={
                            eligibleDoctors.length
                              ? "Select doctor"
                              : "No doctors for this service"
                          }
                          disabled={!eligibleDoctors.length}
                        />
                      )}
                    />
                    {errors.doctor_id ? (
                      <p className="text-xs text-destructive">{errors.doctor_id.message}</p>
                    ) : null}
                  </div>
                </>
              ) : (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Doctor</Label>
                    <Controller
                      control={form.control}
                      name="doctor_id"
                      render={({ field }) => (
                        <FieldSelect
                          value={field.value}
                          onChange={onDoctorChange}
                          items={doctorItems}
                          placeholder={
                            eligibleDoctors.length
                              ? "Select doctor"
                              : "No doctors available"
                          }
                          disabled={!eligibleDoctors.length}
                        />
                      )}
                    />
                    {errors.doctor_id ? (
                      <p className="text-xs text-destructive">{errors.doctor_id.message}</p>
                    ) : null}
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Service</Label>
                    <Controller
                      control={form.control}
                      name="service_id"
                      render={({ field }) => (
                        <FieldSelect
                          value={field.value}
                          onChange={onServiceChange}
                          items={serviceItems}
                          placeholder={
                            doctorId ? "Select service" : "Pick a doctor first"
                          }
                          disabled={!doctorId && careLead === "doctor"}
                        />
                      )}
                    />
                  </div>
                </>
              )}
            </div>
          </Section>

          <Section step="3" title="When">
            {!doctorId ? (
              <p className="text-xs text-muted-foreground">
                Choose a doctor to see which days have open times.
              </p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
                <DoctorAvailabilityCalendar
                  doctorId={doctorId}
                  selectedDate={date}
                  today={clinicToday}
                  minDate={
                    editing && date && date < clinicToday ? date : clinicToday
                  }
                  autoCorrectClosed={!editing}
                  onSelect={pickDate}
                />
                <div className="space-y-1 sm:pt-8">
                  <Label className="text-xs text-muted-foreground">Mins</Label>
                  <Input
                    type="number"
                    min={5}
                    step={5}
                    className="h-9 w-[4.75rem]"
                    {...form.register("duration_min")}
                  />
                </div>
              </div>
            )}

            {!doctorId ? null : !date ? (
              <p className="text-xs text-muted-foreground">Pick a date.</p>
            ) : slotsLoading ? (
              <div className="grid grid-cols-4 gap-1.5">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="h-8 animate-pulse rounded-md bg-muted/70" />
                ))}
              </div>
            ) : slotTimes.length > 0 ? (
              <div className="space-y-1.5">
                {hoursHint ? (
                  <p className="text-[11px] text-muted-foreground">{hoursHint}</p>
                ) : null}
                <div className="grid grid-cols-4 gap-1.5">
                  {slotTimes.map((slot) => {
                    const selected = currentTime === slot.time;
                    return (
                      <button
                        key={`${slot.time}-${slot.end}`}
                        type="button"
                        onClick={() => pickSlot(slot.time, slot.mins)}
                        className={cn(
                          "inline-flex h-8 items-center justify-center gap-1 rounded-md border text-[13px] transition-colors",
                          selected
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border/80 bg-background text-foreground hover:border-primary/35"
                        )}
                      >
                        {selected ? <Check className="size-3" strokeWidth={2.5} /> : null}
                        {slot.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : (
              <p className="text-xs text-destructive">
                {hoursHint === "This doctor has no hours on that day."
                  ? hoursHint
                  : "No open slots — try another day or a custom time."}
              </p>
            )}

            {errors.time ? (
              <p className="text-xs text-destructive">{errors.time.message}</p>
            ) : null}

            <div>
              {!customTimeOpen ? (
                <button
                  type="button"
                  className="text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => setCustomTimeOpen(true)}
                  disabled={!doctorId}
                >
                  Custom time…
                </button>
              ) : (
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Custom start</Label>
                  <Input type="time" className="h-9 max-w-[10rem]" {...form.register("time")} />
                </div>
              )}
            </div>
          </Section>

          <Section step="4" title="Details">
            <div className="grid gap-2.5 sm:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Status</Label>
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
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Source</Label>
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
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Insurance</Label>
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
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Notes</Label>
              <Textarea rows={2} {...form.register("notes")} placeholder="Optional" className="min-h-[2.75rem]" />
            </div>
          </Section>

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
