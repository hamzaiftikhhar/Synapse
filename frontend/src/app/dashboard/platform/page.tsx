"use client";

import Link from "next/link";
import {
  Building2,
  ClipboardList,
  CreditCard,
  FileWarning,
  Timer,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { StatCard } from "@/components/dashboard/stat-card";
import { StatusBreakdownCard } from "@/components/dashboard/status-breakdown-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePlatformOverview } from "@/hooks/api";
import { formatTokens } from "@/lib/analytics-format";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";

export default function PlatformOverviewPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const { data, isLoading } = usePlatformOverview(ready);

  if (!allowed) return null;

  const maxTokens = Math.max(
    ...(data?.top_clinics_by_tokens.map((c) => c.tokens_30d) ?? [1]),
    1
  );

  return (
    <div>
      <PageHeader
        title="Overview"
        description="Every clinic on Synapse — occupancy, billing, and assistant load in one place."
      />

      {isLoading || !data ? (
        <p className="text-sm text-muted-foreground">Loading platform…</p>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <StatCard
              label="Clinics"
              value={data.clinic_count}
              href="/dashboard/platform/clinics"
              icon={Building2}
            />
            <StatCard
              label="Applications in queue"
              value={data.pending_applications}
              href="/dashboard/platform/applications"
              icon={ClipboardList}
            />
            <StatCard
              label="Paying clinics"
              value={data.active_subscriptions}
              href="/dashboard/platform/subscriptions"
              icon={CreditCard}
            />
            <StatCard
              label="Staff accounts"
              value={data.staff_users}
              href="/dashboard/platform/users"
              icon={Users}
            />
            <StatCard
              label="Failed documents"
              value={data.failed_documents}
              href="/dashboard/platform/documents"
              icon={FileWarning}
            />
            <StatCard
              label="Avg AI latency (30d)"
              value={data.avg_latency_ms_30d ? `${data.avg_latency_ms_30d} ms` : "—"}
              href="/dashboard/platform/ai-monitoring"
              icon={Timer}
            />
          </div>

          <div className="grid gap-5 lg:grid-cols-5">
            <div className="lg:col-span-2">
              <StatusBreakdownCard
                title="Clinic status"
                subtitle="Live, setup, and paused tenants"
                emptyTitle="No clinics yet"
                emptyDescription="Approve an application or create a clinic to populate this."
                counts={[
                  {
                    status: "active",
                    label: "Active",
                    count: data.active_clinics,
                    barClass: "bg-success",
                  },
                  {
                    status: "onboarding",
                    label: "Onboarding",
                    count: data.onboarding_clinics,
                    barClass: "bg-primary",
                  },
                  {
                    status: "suspended",
                    label: "Suspended",
                    count: data.suspended_clinics,
                    barClass: "bg-destructive",
                  },
                ]}
              />
            </div>
            <Card className="lg:col-span-3">
              <CardHeader className="flex flex-row items-end justify-between space-y-0">
                <div>
                  <CardTitle>Top clinics by tokens</CardTitle>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Last 30 days · {formatTokens(data.tokens_30d)} across the platform
                  </p>
                </div>
                <Link
                  href="/dashboard/platform/ai-usage"
                  className="text-xs font-medium text-muted-foreground hover:text-foreground"
                >
                  AI usage
                </Link>
              </CardHeader>
              <CardContent>
                {data.top_clinics_by_tokens.length ? (
                  <ul className="space-y-3">
                    {data.top_clinics_by_tokens.map((c) => (
                      <li key={c.slug}>
                        <div className="mb-1.5 flex items-baseline justify-between gap-3">
                          <span className="text-[13px] font-medium text-navy">{c.name}</span>
                          <span className="text-[13px] tabular-nums text-muted-foreground">
                            {formatTokens(c.tokens_30d)}
                          </span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-primary/10">
                          <div
                            className="h-full rounded-full bg-primary"
                            style={{
                              width: `${Math.max((c.tokens_30d / maxTokens) * 100, c.tokens_30d ? 4 : 0)}%`,
                            }}
                          />
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">No model calls yet.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
