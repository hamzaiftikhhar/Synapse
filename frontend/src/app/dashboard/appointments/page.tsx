"use client";

import { format } from "date-fns";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAppointments, useCancelAppointment } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";

export default function AppointmentsPage() {
  const { data, isLoading } = useAppointments({ limit: 100 });
  const cancel = useCancelAppointment();
  const rows = data?.results ?? [];

  async function onCancel(id: string) {
    if (!confirm("Cancel this appointment?")) return;
    try {
      await cancel.mutateAsync(id);
      toast.success("Appointment cancelled");
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Appointments"
        description="Clinic schedule across chatbot, admin, and other booking sources."
      />
      <DataTableShell>
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">Loading…</p>
        ) : !rows.length ? (
          <EmptyState
            title="No appointments"
            description="Appointments created via API or chatbot will appear here."
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
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="font-medium">{a.patient_name}</TableCell>
                  <TableCell>{a.doctor_name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {a.service_name || "—"}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {format(new Date(a.start_time), "MMM d, yyyy · h:mm a")}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="rounded-[6px] capitalize">
                      {a.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="capitalize text-muted-foreground">
                    {a.source}
                  </TableCell>
                  <TableCell>
                    {a.status !== "cancelled" ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="rounded-[6px]"
                        onClick={() => onCancel(a.id)}
                      >
                        Cancel
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DataTableShell>
    </div>
  );
}
