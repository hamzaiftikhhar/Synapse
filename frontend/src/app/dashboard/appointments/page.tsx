"use client";

import { useMemo, useState } from "react";
import { Ban, Calendar, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AppointmentFormDialog } from "@/features/appointments/appointment-form-dialog";
import {
  APPOINTMENT_STATUSES,
  SOURCE_LABEL,
  STATUS_BADGE_VARIANT,
  STATUS_LABEL,
} from "@/features/appointments/constants";
import {
  useAppointments,
  useCancelAppointment,
  useDoctors,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import {
  clinicTodayDate,
  endOfClinicDayIso,
  formatClinicDate,
  formatClinicTime,
  startOfClinicDayIso,
} from "@/lib/timezone";
import { useAuth } from "@/providers/auth-provider";
import type { Appointment } from "@/types/api";

type DatePreset = "today" | "upcoming" | "past" | "all";

const ALL = "all";

export default function AppointmentsPage() {
  const { clinic } = useAuth();
  const timeZone = clinic?.timezone || "UTC";
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState(ALL);
  const [doctorId, setDoctorId] = useState(ALL);
  const [preset, setPreset] = useState<DatePreset>("all");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Appointment | null>(null);
  const [cancelling, setCancelling] = useState<Appointment | null>(null);

  const today = clinicTodayDate(timeZone);
  const listParams = useMemo(() => {
    const now = new Date().toISOString();
    const params: {
      limit: number;
      status?: string;
      doctor_id?: string;
      from_date?: string;
      to_date?: string;
    } = { limit: 100 };
    if (status !== ALL) params.status = status;
    if (doctorId !== ALL) params.doctor_id = doctorId;
    if (preset === "today") {
      params.from_date = startOfClinicDayIso(today, timeZone);
      params.to_date = endOfClinicDayIso(today, timeZone);
    } else if (preset === "upcoming") {
      params.from_date = now;
    } else if (preset === "past") {
      params.to_date = now;
    }
    return params;
  }, [status, doctorId, preset, today, timeZone]);

  const { data, isLoading } = useAppointments(listParams);
  const { data: doctorsData } = useDoctors({ limit: 100 });
  const cancel = useCancelAppointment();

  const doctors = doctorsData?.results ?? [];
  const rows = data?.results ?? [];
  const query = search.trim().toLowerCase();
  const visible = query
    ? rows.filter((row) => {
        const haystack = [
          row.patient_name,
          row.doctor_name,
          row.service_name ?? "",
          row.confirmation_code,
          row.notes,
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(query);
      })
    : rows;

  const statusItems = [
    { value: ALL, label: "All statuses" },
    ...APPOINTMENT_STATUSES.map((value) => ({
      value,
      label: STATUS_LABEL[value],
    })),
  ];
  const doctorItems = [
    { value: ALL, label: "All doctors" },
    ...doctors.map((d) => ({ value: d.id, label: d.full_name })),
  ];

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(row: Appointment) {
    setEditing(row);
    setFormOpen(true);
  }

  async function onConfirmCancel() {
    if (!cancelling) return;
    try {
      await cancel.mutateAsync(cancelling.id);
      toast.success("Appointment cancelled");
      setCancelling(null);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not cancel appointment"));
    }
  }

  return (
    <div>
      <PageHeader
        title="Appointments"
        description={`Clinic schedule across chatbot, front desk, and other sources. Times shown in ${timeZone}.`}
        actions={
          <Button onClick={openCreate}>
            <Plus className="size-4" /> New appointment
          </Button>
        }
      />
      <DataTableShell
        title="Schedule"
        toolbar={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Input
              placeholder="Search patient, doctor, code…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 w-52"
            />
            <Select
              value={status}
              onValueChange={(value) => value && setStatus(value)}
              items={statusItems}
            >
              <SelectTrigger size="sm" className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {statusItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={doctorId}
              onValueChange={(value) => value && setDoctorId(value)}
              items={doctorItems}
            >
              <SelectTrigger size="sm" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {doctorItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Tabs
              value={preset}
              onValueChange={(value) => setPreset(value as DatePreset)}
            >
              <TabsList aria-label="Date range">
                <TabsTrigger value="today">Today</TabsTrigger>
                <TabsTrigger value="upcoming">Upcoming</TabsTrigger>
                <TabsTrigger value="past">Past</TabsTrigger>
                <TabsTrigger value="all">All</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        }
      >
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">Loading…</p>
        ) : !visible.length ? (
          <EmptyState
            icon={Calendar}
            title="No appointments"
            description={
              query || status !== ALL || doctorId !== ALL || preset !== "all"
                ? "Nothing matches these filters."
                : "Book from the front desk or wait for chatbot bookings to appear."
            }
            action={
              <Button onClick={openCreate}>
                <Plus className="size-4" /> New appointment
              </Button>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Patient</TableHead>
                <TableHead>Doctor</TableHead>
                <TableHead>Service</TableHead>
                <TableHead>When</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Code</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => {
                const canCancel = row.status !== "cancelled";
                return (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2.5">
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-semibold text-accent-foreground">
                          {row.patient_name.slice(0, 1).toUpperCase()}
                        </span>
                        {row.patient_name}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.doctor_name}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.service_name || "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <div className="text-sm text-foreground">
                        {formatClinicDate(row.start_time, timeZone)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatClinicTime(row.start_time, timeZone)} –{" "}
                        {formatClinicTime(row.end_time, timeZone)}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={STATUS_BADGE_VARIANT[row.status] ?? "secondary"}
                      >
                        {STATUS_LABEL[row.status] ?? row.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {SOURCE_LABEL[row.source] ?? row.source}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {row.confirmation_code}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => openEdit(row)}
                          aria-label="Edit appointment"
                        >
                          <Pencil className="size-3.5" />
                        </Button>
                        {canCancel ? (
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => setCancelling(row)}
                            aria-label="Cancel appointment"
                          >
                            <Ban className="size-3.5" />
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </DataTableShell>
      {data && data.count > visible.length && !query ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing {visible.length} of {data.count}. Narrow the date range to see more.
        </p>
      ) : null}

      <AppointmentFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        editing={editing}
        timeZone={timeZone}
      />

      <Dialog open={cancelling != null} onOpenChange={(open) => !open && setCancelling(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Cancel appointment</DialogTitle>
            <DialogDescription>
              {cancelling
                ? `Cancel ${cancelling.patient_name}'s visit with ${cancelling.doctor_name}? The slot will be freed for new bookings.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCancelling(null)}>
              Keep appointment
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={cancel.isPending}
              onClick={() => void onConfirmCancel()}
            >
              {cancel.isPending ? "Cancelling…" : "Cancel appointment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
