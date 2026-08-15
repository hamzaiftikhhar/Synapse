"use client";

import { useMemo, useState } from "react";
import { Ban, Calendar, Pencil, Plus, Search } from "lucide-react";
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
import { groupAppointmentsByDay } from "@/features/appointments/group";
import {
  useAppointments,
  useCancelAppointment,
  useDoctors,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import {
  clinicTodayDate,
  endOfClinicDayIso,
  formatClinicDayHeading,
  formatClinicTimeRange,
  startOfClinicDayIso,
} from "@/lib/timezone";
import { cn } from "@/lib/utils";
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

  const dayGroups = useMemo(() => {
    const groups = groupAppointmentsByDay(visible, timeZone);
    if (preset !== "past") return groups;
    return [...groups].reverse().map((group) => ({
      ...group,
      rows: [...group.rows].reverse(),
    }));
  }, [visible, timeZone, preset]);

  const statusItems = [
    { value: ALL, label: "Status" },
    ...APPOINTMENT_STATUSES.map((value) => ({
      value,
      label: STATUS_LABEL[value],
    })),
  ];
  const doctorItems = [
    { value: ALL, label: "Doctor" },
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

  const filtered =
    query || status !== ALL || doctorId !== ALL || preset !== "all";

  return (
    <div>
      <PageHeader
        title="Appointments"
        description={`Front desk board · ${timeZone}`}
        actions={
          <Button onClick={openCreate}>
            <Plus className="size-4" /> New appointment
          </Button>
        }
      />
      <DataTableShell
        toolbar={
          <div className="flex w-full flex-col gap-3 lg:flex-row lg:items-center">
            <div className="flex flex-wrap items-center gap-3">
              <Tabs
                value={preset}
                onValueChange={(value) => setPreset(value as DatePreset)}
                className="gap-0"
              >
                <TabsList aria-label="Date range">
                  <TabsTrigger value="today" className="px-3">
                    Today
                  </TabsTrigger>
                  <TabsTrigger value="upcoming" className="px-3">
                    Upcoming
                  </TabsTrigger>
                  <TabsTrigger value="past" className="px-3">
                    Past
                  </TabsTrigger>
                  <TabsTrigger value="all" className="px-3">
                    All
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              <p className="text-xs text-muted-foreground tabular-nums">
                {visible.length} {visible.length === 1 ? "visit" : "visits"}
              </p>
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 lg:justify-end">
              <div className="relative min-w-[12rem] flex-1 lg:max-w-xs">
                <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Patient, doctor, or code"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-8"
                />
              </div>
              <Select
                value={status}
                onValueChange={(value) => value && setStatus(value)}
                items={statusItems}
              >
                <SelectTrigger size="sm" className="w-[8.5rem]">
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
                <SelectTrigger size="sm" className="w-[9.5rem]">
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
            </div>
          </div>
        }
      >
        {isLoading ? (
          <p className="px-5 py-8 text-sm text-muted-foreground">Loading schedule…</p>
        ) : !visible.length ? (
          <EmptyState
            icon={Calendar}
            title={filtered ? "No visits match" : "No appointments yet"}
            description={
              filtered
                ? "Clear a filter or search to see more of the board."
                : "Book from the front desk, or chatbot bookings will land here."
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
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-36 pl-5">Time</TableHead>
                <TableHead>Patient</TableHead>
                <TableHead>With</TableHead>
                <TableHead className="w-28">Status</TableHead>
                <TableHead className="w-20 pr-4 text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            {dayGroups.map((group) => (
              <TableBody key={group.dateKey}>
                <TableRow className="hover:bg-transparent">
                  <TableCell
                    colSpan={5}
                    className="bg-muted/40 py-2 pl-5 text-xs font-medium tracking-wide text-navy whitespace-normal"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span>{formatClinicDayHeading(group.sampleIso, timeZone)}</span>
                      <span className="font-normal text-muted-foreground tabular-nums">
                        {group.rows.length}{" "}
                        {group.rows.length === 1 ? "visit" : "visits"}
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
                {group.rows.map((row) => {
                  const cancelled = row.status === "cancelled";
                  return (
                    <TableRow
                      key={row.id}
                      className={cn(cancelled && "opacity-60")}
                    >
                      <TableCell className="pl-5 font-medium tabular-nums text-navy">
                        {formatClinicTimeRange(
                          row.start_time,
                          row.end_time,
                          timeZone
                        )}
                      </TableCell>
                      <TableCell className="whitespace-normal">
                        <p className="font-medium text-foreground">
                          {row.patient_name}
                        </p>
                        <p className="mt-0.5 font-mono text-[11px] tracking-wide text-muted-foreground">
                          {row.confirmation_code}
                          <span className="font-sans">
                            {" · "}
                            {SOURCE_LABEL[row.source] ?? row.source}
                          </span>
                        </p>
                      </TableCell>
                      <TableCell className="whitespace-normal">
                        <p className="text-foreground">{row.doctor_name}</p>
                        {row.service_name ? (
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {row.service_name}
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={STATUS_BADGE_VARIANT[row.status] ?? "secondary"}
                        >
                          {STATUS_LABEL[row.status] ?? row.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="pr-3">
                        <div className="flex justify-end gap-0.5">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => openEdit(row)}
                            aria-label="Edit appointment"
                          >
                            <Pencil className="size-3.5" />
                          </Button>
                          {!cancelled ? (
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
            ))}
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
