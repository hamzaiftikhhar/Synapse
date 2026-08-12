"use client";

import { useMemo } from "react";
import Link from "next/link";
import {
  Calendar,
  FileText,
  Stethoscope,
  Users,
  BriefcaseMedical,
} from "lucide-react";
import { format, subDays } from "date-fns";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { SetupChecklistCard } from "@/components/dashboard/setup-checklist";
import { StatCard } from "@/components/dashboard/stat-card";
import { TrendChartCard, type DailyPoint } from "@/components/dashboard/trend-chart-card";
import {
  StatusBreakdownCard,
  type StatusCount,
} from "@/components/dashboard/status-breakdown-card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useAppointments,
  useDoctors,
  useDocuments,
  usePatients,
  useServices,
} from "@/hooks/api";
import { useAuth } from "@/providers/auth-provider";
import type { AppointmentStatus } from "@/types/api";

const STATUS_BADGE_VARIANT: Record<
  string,
  "success" | "warning" | "destructive" | "info" | "secondary"
> = {
  confirmed: "success",
  pending: "warning",
  cancelled: "destructive",
  completed: "info",
  no_show: "destructive",
  rescheduled: "secondary",
};

const STATUS_BAR: Record<string, string> = {
  confirmed: "bg-success",
  pending: "bg-warning",
  cancelled: "bg-destructive",
  completed: "bg-info",
  no_show: "bg-destructive/70",
  rescheduled: "bg-muted-foreground/50",
};

const STATUS_LABEL: Record<string, string> = {
  confirmed: "Confirmed",
  pending: "Pending",
  cancelled: "Cancelled",
  completed: "Completed",
  no_show: "No-show",
  rescheduled: "Rescheduled",
};

const TREND_DAYS = 14;

export default function DashboardHomePage() {
  const { clinic, user } = useAuth();
  const doctors = useDoctors({ limit: 1 });
  const services = useServices({ limit: 1 });
  const patients = usePatients({ limit: 1 });
  const appointments = useAppointments({ limit: 100 });
  const documents = useDocuments();

  const rows = appointments.data?.results ?? [];

  const trend = useMemo<{ points: DailyPoint[]; total: number }>(() => {
    const byDay = new Map<string, number>();
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    for (let i = TREND_DAYS - 1; i >= 0; i--) {
      byDay.set(format(subDays(today, i), "yyyy-MM-dd"), 0);
    }
    for (const a of rows) {
      const key = format(new Date(a.start_time), "yyyy-MM-dd");
      if (byDay.has(key)) byDay.set(key, (byDay.get(key) ?? 0) + 1);
    }
    let points = Array.from(byDay.entries()).map(([key, count]) => ({
      label: format(new Date(`${key}T12:00:00`), "MMM d"),
      count,
    }));
    let total = points.reduce((sum, p) => sum + p.count, 0);

    if (total === 0 && rows.length > 0) {
      const historic = new Map<string, number>();
      for (const a of rows) {
        const key = format(new Date(a.start_time), "yyyy-MM-dd");
        historic.set(key, (historic.get(key) ?? 0) + 1);
      }
      points = Array.from(historic.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .slice(-TREND_DAYS)
        .map(([key, count]) => ({
          label: format(new Date(`${key}T12:00:00`), "MMM d"),
          count,
        }));
      total = points.reduce((sum, p) => sum + p.count, 0);
    }

    return { points, total };
  }, [rows]);

  const statusCounts = useMemo<StatusCount[]>(() => {
    const byStatus = new Map<string, number>();
    for (const a of rows) {
      const key = String(a.status);
      byStatus.set(key, (byStatus.get(key) ?? 0) + 1);
    }
    const order: AppointmentStatus[] = [
      "confirmed",
      "pending",
      "completed",
      "cancelled",
      "no_show",
      "rescheduled",
    ];
    return order.map((status) => ({
      status,
      label: STATUS_LABEL[status],
      count: byStatus.get(status) ?? 0,
      barClass: STATUS_BAR[status],
    }));
  }, [rows]);

  const recent = rows.slice(0, 8);

  const statCards = [
    { label: "Doctors", value: doctors.data?.count, href: "/dashboard/doctors", icon: Stethoscope },
    { label: "Services", value: services.data?.count, href: "/dashboard/services", icon: BriefcaseMedical },
    { label: "Patients", value: patients.data?.count, href: "/dashboard/patients", icon: Users },
    { label: "Appointments", value: appointments.data?.count, href: "/dashboard/appointments", icon: Calendar },
    { label: "Documents", value: documents.data?.length, href: "/dashboard/knowledge", icon: FileText },
  ];

  return (
    <div>
      <PageHeader
        title={`Welcome back${user?.first_name ? `, ${user.first_name}` : ""}`}
        description={`${clinic?.name ?? "Your clinic"} · manage operations and the patient chatbot from one workspace.`}
        actions={
          <Link
            href="/dashboard/chatbot"
            className="inline-flex h-8 items-center rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Open chatbot QA
          </Link>
        }
      />

      <SetupChecklistCard />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {statCards.map((c) => (
          <StatCard
            key={c.label}
            label={c.label}
            value={c.value ?? "—"}
            href={c.href}
            icon={c.icon}
          />
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <TrendChartCard
            title="Appointment volume"
            subtitle="Booked visits by day over the last 14 days"
            data={trend.points}
            totalLabel="Appointments in this window"
            total={trend.total}
          />
        </div>
        <StatusBreakdownCard
          title="Appointment status"
          subtitle="Where things stand right now"
          counts={statusCounts}
        />
      </div>

      <div className="mt-4">
        <DataTableShell
          title="Recent appointments"
          toolbar={
            <Link
              href="/dashboard/appointments"
              className="inline-flex h-7 items-center rounded-lg border border-border px-2.5 text-[0.8rem] hover:bg-muted"
            >
              Manage
            </Link>
          }
        >
          {!recent.length ? (
            <EmptyState
              icon={Calendar}
              title="No appointments yet"
              description="Create appointments from the Appointments page, or let the patient chatbot book them for you."
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Patient</TableHead>
                  <TableHead>Doctor</TableHead>
                  <TableHead>When</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recent.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2.5">
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold text-foreground">
                          {a.patient_name.slice(0, 1).toUpperCase()}
                        </span>
                        {a.patient_name}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{a.doctor_name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {format(new Date(a.start_time), "MMM d, yyyy · h:mm a")}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={STATUS_BADGE_VARIANT[a.status] ?? "secondary"}
                        className="capitalize"
                      >
                        {a.status}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </DataTableShell>
      </div>
    </div>
  );
}
