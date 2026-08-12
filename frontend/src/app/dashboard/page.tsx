"use client";

import { useMemo } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  Calendar,
  FileText,
  Stethoscope,
  Users,
  BriefcaseMedical,
} from "lucide-react";
import { format } from "date-fns";
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

const STATUS_CHART_COLOR: Record<string, string> = {
  confirmed: "var(--success)",
  pending: "var(--warning)",
  cancelled: "var(--destructive)",
  completed: "var(--info)",
  no_show: "var(--destructive)",
  rescheduled: "var(--muted-foreground)",
};

const STATUS_LABEL: Record<string, string> = {
  confirmed: "Confirmed",
  pending: "Pending",
  cancelled: "Cancelled",
  completed: "Completed",
  no_show: "No-show",
  rescheduled: "Rescheduled",
};

const fadeUp = {
  hidden: { opacity: 0, y: 8 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.05, duration: 0.35, ease: "easeOut" as const },
  }),
};

export default function DashboardHomePage() {
  const { clinic, user } = useAuth();
  const doctors = useDoctors({ limit: 1 });
  const services = useServices({ limit: 1 });
  const patients = usePatients({ limit: 1 });
  const appointments = useAppointments({ limit: 8 });
  const appointmentsForCharts = useAppointments({ limit: 200 });
  const documents = useDocuments();

  const trend = useMemo<{ points: DailyPoint[]; total: number }>(() => {
    const rows = appointmentsForCharts.data?.results ?? [];
    if (rows.length === 0) return { points: [], total: 0 };

    const byDay = new Map<string, number>();
    for (const a of rows) {
      const d = new Date(a.start_time);
      const key = format(d, "yyyy-MM-dd");
      byDay.set(key, (byDay.get(key) ?? 0) + 1);
    }
    const sortedKeys = Array.from(byDay.keys()).sort();
    const points = sortedKeys.map((key) => ({
      label: format(new Date(key), "MMM d"),
      count: byDay.get(key) ?? 0,
    }));
    return { points, total: rows.length };
  }, [appointmentsForCharts.data]);

  const statusCounts = useMemo<StatusCount[]>(() => {
    const rows = appointmentsForCharts.data?.results ?? [];
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
      color: STATUS_CHART_COLOR[status],
    }));
  }, [appointmentsForCharts.data]);

  const statCards = [
    { label: "Doctors", value: doctors.data?.count, href: "/dashboard/doctors", icon: Stethoscope, tone: "primary" as const },
    { label: "Services", value: services.data?.count, href: "/dashboard/services", icon: BriefcaseMedical, tone: "info" as const },
    { label: "Patients", value: patients.data?.count, href: "/dashboard/patients", icon: Users, tone: "success" as const },
    { label: "Appointments", value: appointments.data?.count, href: "/dashboard/appointments", icon: Calendar, tone: "warning" as const },
    { label: "Documents", value: documents.data?.length, href: "/dashboard/knowledge", icon: FileText, tone: "primary" as const },
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
        {statCards.map((c, i) => (
          <motion.div
            key={c.label}
            custom={i}
            initial="hidden"
            animate="show"
            variants={fadeUp}
          >
            <StatCard
              label={c.label}
              value={c.value ?? "—"}
              href={c.href}
              icon={c.icon}
              tone={c.tone}
            />
          </motion.div>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <motion.div
          className="lg:col-span-2"
          custom={5}
          initial="hidden"
          animate="show"
          variants={fadeUp}
        >
          <TrendChartCard
            title="Appointment volume"
            subtitle="Booked visits by day, across your most recent appointments"
            data={trend.points}
            totalLabel="Appointments in view"
            total={trend.total}
          />
        </motion.div>
        <motion.div custom={6} initial="hidden" animate="show" variants={fadeUp}>
          <StatusBreakdownCard
            title="Appointment status"
            subtitle="Where things stand right now"
            counts={statusCounts}
          />
        </motion.div>
      </div>

      <motion.div
        className="mt-4"
        custom={7}
        initial="hidden"
        animate="show"
        variants={fadeUp}
      >
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
          {!appointments.data?.results.length ? (
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
                {appointments.data.results.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2.5">
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-semibold text-accent-foreground">
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
      </motion.div>
    </div>
  );
}
