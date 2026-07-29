"use client";

import Link from "next/link";
import {
  Calendar,
  FileText,
  Stethoscope,
  Users,
  BriefcaseMedical,
  ArrowUpRight,
} from "lucide-react";
import { format } from "date-fns";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

function StatCard({
  label,
  value,
  href,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card className="rounded-[6px] border-border shadow-none">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
        <Icon className="size-4 text-primary/70" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold tracking-tight text-navy">
          {value}
        </div>
        <Link
          href={href}
          className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          View all <ArrowUpRight className="size-3" />
        </Link>
      </CardContent>
    </Card>
  );
}

export default function DashboardHomePage() {
  const { clinic, user } = useAuth();
  const doctors = useDoctors({ limit: 1 });
  const services = useServices({ limit: 1 });
  const patients = usePatients({ limit: 1 });
  const appointments = useAppointments({ limit: 8 });
  const documents = useDocuments();

  return (
    <div>
      <PageHeader
        title={`Welcome${user?.first_name ? `, ${user.first_name}` : ""}`}
        description={`${clinic?.name ?? "Your clinic"} · manage operations and patient chatbot from one workspace.`}
        actions={
          <Link
            href="/dashboard/chatbot"
            className="inline-flex h-8 items-center rounded-[6px] bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Open chatbot QA
          </Link>
        }
      />

      <div className="relative mb-6 overflow-hidden rounded-[6px] border border-border bg-white p-5">
        <div className="glow-purple pointer-events-none absolute inset-0 opacity-70" />
        <div className="relative">
          <p className="text-xs font-medium uppercase tracking-wider text-primary">
            Clinic overview
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Live counts from your Synapse API — doctors, services, patients,
            appointments, and knowledge documents.
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard
          label="Doctors"
          value={doctors.data?.count ?? "—"}
          href="/dashboard/doctors"
          icon={Stethoscope}
        />
        <StatCard
          label="Services"
          value={services.data?.count ?? "—"}
          href="/dashboard/services"
          icon={BriefcaseMedical}
        />
        <StatCard
          label="Patients"
          value={patients.data?.count ?? "—"}
          href="/dashboard/patients"
          icon={Users}
        />
        <StatCard
          label="Appointments"
          value={appointments.data?.count ?? "—"}
          href="/dashboard/appointments"
          icon={Calendar}
        />
        <StatCard
          label="Documents"
          value={documents.data?.length ?? "—"}
          href="/dashboard/knowledge"
          icon={FileText}
        />
      </div>

      <div className="mt-6">
        <DataTableShell
          title="Recent appointments"
          toolbar={
            <Link
              href="/dashboard/appointments"
              className="inline-flex h-7 items-center rounded-[6px] border border-border px-2.5 text-[0.8rem] hover:bg-muted"
            >
              Manage
            </Link>
          }
        >
          {!appointments.data?.results.length ? (
            <EmptyState
              title="No appointments yet"
              description="Create appointments from the Appointments page."
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
                    <TableCell className="font-medium">{a.patient_name}</TableCell>
                    <TableCell>{a.doctor_name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {format(new Date(a.start_time), "MMM d, yyyy · h:mm a")}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="rounded-[6px] capitalize">
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
