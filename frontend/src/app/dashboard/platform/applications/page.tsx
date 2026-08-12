"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/providers/auth-provider";
import { getApiErrorMessage } from "@/lib/api/client";
import { platformService } from "@/services";
import type { ClinicApplication } from "@/types/api";

const STATUS_FILTERS = ["pending", "reviewing", "converted", "rejected", ""] as const;
const STATUS_LABEL: Record<string, string> = {
  pending: "Pending review",
  reviewing: "Reviewing",
  approved: "Approved",
  rejected: "Rejected",
  converted: "Provisioned",
};
const STATUS_TONE: Record<string, string> = {
  pending: "bg-warning/15 text-warning",
  reviewing: "bg-warning/15 text-warning",
  approved: "bg-emerald-100 text-emerald-700",
  converted: "bg-emerald-100 text-emerald-700",
  rejected: "bg-destructive/10 text-destructive",
};

export default function PlatformApplicationsPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("pending");
  const [rows, setRows] = useState<ClinicApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await platformService.listApplications(statusFilter));
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    if (user && user.role !== "SUPER_ADMIN") {
      router.replace("/dashboard");
      return;
    }
    void load();
  }, [user, router, load]);

  async function approve(id: string) {
    setBusyId(id);
    try {
      const result = await platformService.approveApplication(id);
      toast.success(`${result.clinic?.name ?? "Clinic"} provisioned — invite sent`);
      setExpandedId(null);
      void load();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function reject(id: string) {
    setBusyId(id);
    try {
      await platformService.rejectApplication(id, { reason: rejectReason.trim() });
      toast.success("Application rejected");
      setExpandedId(null);
      setRejectReason("");
      void load();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  if (user && user.role !== "SUPER_ADMIN") return null;

  return (
    <div>
      <PageHeader
        title="Clinic applications"
        description="Review Get Started submissions and provision approved clinics."
      />
      <div className="mb-4 flex flex-wrap gap-1.5">
        {STATUS_FILTERS.filter((s) => s !== "").map((s) => (
          <Button
            key={s}
            type="button"
            size="sm"
            variant={statusFilter === s ? "default" : "outline"}
            onClick={() => setStatusFilter(s)}
          >
            {STATUS_LABEL[s] ?? s}
          </Button>
        ))}
        <Button
          type="button"
          size="sm"
          variant={statusFilter === "" ? "default" : "outline"}
          onClick={() => setStatusFilter("")}
        >
          All
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading applications…</p>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border bg-muted/30 p-8 text-center text-sm text-muted-foreground">
          No applications here.
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((app) => {
            const expanded = expandedId === app.id;
            const actionable = app.status === "pending" || app.status === "reviewing";
            return (
              <div key={app.id} className="rounded-2xl border border-border bg-card p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-navy">{app.clinic_name}</p>
                    <p className="text-xs text-muted-foreground">
                      {app.plan_slug} plan · {app.owner_name} · {app.work_email}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[app.status] ?? ""}`}
                    >
                      {STATUS_LABEL[app.status] ?? app.status}
                    </span>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => setExpandedId(expanded ? null : app.id)}
                    >
                      {expanded ? "Hide" : "Review"}
                    </Button>
                  </div>
                </div>

                {expanded ? (
                  <div className="mt-4 space-y-3 border-t border-border pt-4 text-sm">
                    <div className="grid gap-2 sm:grid-cols-2">
                      <p><span className="text-muted-foreground">Phone:</span> {app.phone || "—"}</p>
                      <p><span className="text-muted-foreground">Website:</span> {app.website || "—"}</p>
                      <p>
                        <span className="text-muted-foreground">Doctors:</span>{" "}
                        {app.num_doctors ?? "—"}
                      </p>
                      <p>
                        <span className="text-muted-foreground">Current system:</span>{" "}
                        {app.current_scheduling_system || "—"}
                      </p>
                    </div>
                    {app.notes ? (
                      <p className="text-muted-foreground">
                        <span className="text-foreground">Notes:</span> {app.notes}
                      </p>
                    ) : null}
                    {app.status === "rejected" && app.rejection_reason ? (
                      <p className="text-destructive">Rejected: {app.rejection_reason}</p>
                    ) : null}

                    {actionable ? (
                      <div className="space-y-2 pt-1">
                        <Textarea
                          rows={2}
                          placeholder="Rejection reason (optional)"
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                        />
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            disabled={busyId === app.id}
                            onClick={() => void approve(app.id)}
                          >
                            {busyId === app.id ? "Provisioning…" : "Approve & provision clinic"}
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            disabled={busyId === app.id}
                            onClick={() => void reject(app.id)}
                          >
                            Reject
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
