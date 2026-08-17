"use client";

import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState } from "@/components/dashboard/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePlatformApplications } from "@/hooks/api";
import { platformService } from "@/services";
import { getApiErrorMessage } from "@/lib/api/client";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";
import { formatWhen } from "@/features/platform/format";
import { StatusPill } from "@/features/platform/status-pill";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/api";
import { ClipboardList } from "lucide-react";

const FILTERS = [
  { value: "pending", label: "Pending" },
  { value: "reviewing", label: "Reviewing" },
  { value: "converted", label: "Provisioned" },
  { value: "rejected", label: "Rejected" },
  { value: "", label: "All" },
] as const;

export default function PlatformApplicationsPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const qc = useQueryClient();
  const [status, setStatus] = useState("pending");
  const { data, isLoading } = usePlatformApplications(status, ready);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function refresh() {
    await qc.invalidateQueries({ queryKey: queryKeys.platformApplications(status) });
  }

  async function run(id: string, fn: () => Promise<unknown>, ok: string) {
    setBusyId(id);
    try {
      await fn();
      toast.success(ok);
      setExpandedId(null);
      setReason("");
      await refresh();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  if (!allowed) return null;
  const rows = data ?? [];

  return (
    <div>
      <PageHeader
        title="Applications"
        description="Review Get Started submissions and provision a clinic when they’re a fit."
        actions={
          <Tabs value={status} onValueChange={setStatus}>
            <TabsList aria-label="Application status">
              {FILTERS.map((f) => (
                <TabsTrigger key={f.label} value={f.value} className="px-3">
                  {f.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading applications…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="Nothing in this queue"
          description="New Get Started forms land here for review."
        />
      ) : (
        <div className="space-y-3">
          {rows.map((app) => {
            const open = expandedId === app.id;
            const actionable = app.status === "pending" || app.status === "reviewing";
            return (
              <Card key={app.id}>
                <CardContent className="px-5 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-navy">{app.clinic_name}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {app.plan_slug} · {app.owner_name} · {app.work_email}
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {formatWhen(app.created_at)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusPill value={app.status === "converted" ? "converted" : app.status} />
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setExpandedId(open ? null : app.id)}
                      >
                        {open ? "Close" : "Review"}
                      </Button>
                    </div>
                  </div>

                  {open ? (
                    <div className="mt-4 space-y-3 border-t border-border pt-4 text-sm">
                      <dl className="grid gap-2 sm:grid-cols-2">
                        <div>
                          <dt className="text-xs text-muted-foreground">Phone</dt>
                          <dd>{app.phone || "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-xs text-muted-foreground">Website</dt>
                          <dd className="truncate">{app.website || "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-xs text-muted-foreground">Doctors</dt>
                          <dd>{app.num_doctors ?? "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-xs text-muted-foreground">Current system</dt>
                          <dd>{app.current_scheduling_system || "—"}</dd>
                        </div>
                      </dl>
                      {app.notes ? <p className="text-muted-foreground">{app.notes}</p> : null}
                      {app.rejection_reason ? (
                        <p className="text-destructive">Rejected: {app.rejection_reason}</p>
                      ) : null}
                      {actionable ? (
                        <div className="space-y-2 pt-1">
                          <Textarea
                            rows={2}
                            placeholder="Rejection reason (optional)"
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                          />
                          <div className="flex flex-wrap gap-2">
                            {app.status === "pending" ? (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busyId === app.id}
                                onClick={() =>
                                  void run(
                                    app.id,
                                    () => platformService.reviewApplication(app.id),
                                    "Marked as reviewing"
                                  )
                                }
                              >
                                Mark reviewing
                              </Button>
                            ) : null}
                            <Button
                              size="sm"
                              disabled={busyId === app.id}
                              onClick={() =>
                                void run(
                                  app.id,
                                  () => platformService.approveApplication(app.id),
                                  "Clinic provisioned — invite sent"
                                )
                              }
                            >
                              {busyId === app.id ? "Provisioning…" : "Approve & provision"}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={busyId === app.id}
                              onClick={() =>
                                void run(
                                  app.id,
                                  () =>
                                    platformService.rejectApplication(app.id, {
                                      reason: reason.trim(),
                                    }),
                                  "Application rejected"
                                )
                              }
                            >
                              Reject
                            </Button>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
