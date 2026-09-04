"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, MessageSquare } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState } from "@/components/dashboard/shell";
import { SetupChecklistCard } from "@/components/dashboard/setup-checklist";
import {
  AnalyticsLegend,
  AnalyticsLineChart,
  AppointmentSourceRadarCard,
  AppointmentStatusCard,
  BookingCalendarCard,
  SpecialtyMixCard,
  ChartPanel,
  DateRangeSelector,
  MetricChange,
  greetingForHour,
  seriesHasValues,
  type AnalyticsRange,
} from "@/components/dashboard/charts";
import { CHART } from "@/components/dashboard/charts/colors";
import {
  InsightCard,
  KpiSparkCard,
  NeedsAttentionCard,
  SynapseInsightCard,
  TodayScheduleCard,
} from "@/components/dashboard/insights";
import {
  ListCardSkeleton,
  MetricCardSkeleton,
  PanelSkeleton,
} from "@/components/dashboard/skeletons";
import { useAnalyticsOverview, useConversations } from "@/hooks/api";
import { useAuth } from "@/providers/auth-provider";
import { cn } from "@/lib/utils";

function hourInZone(timeZone: string): number {
  const hour = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "numeric",
    hourCycle: "h23",
  }).format(new Date());
  const parsed = Number(hour);
  return Number.isFinite(parsed) ? parsed : new Date().getHours();
}

const CONVERSATION_STATUS_DOT: Record<string, string> = {
  active: "bg-info",
  escalated: "bg-destructive",
  closed: "bg-muted-foreground/40",
};

/** Quiet primary-metric tile for the Clinic Pulse row — bigger, plainer
 * number than the historical KpiSparkCard row below it (no sparkline):
 * this is "what's true right now," not a trend. */
function PulseTile({
  label,
  value,
  hint,
  href,
}: {
  label: string;
  value: string | number;
  hint?: string;
  href?: string;
}) {
  const inner = (
    <InsightCard className="h-full p-5">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="mt-2 text-[1.9rem] font-semibold leading-none tracking-tight text-navy tabular-nums">
        {value}
      </p>
      {hint ? <p className="mt-2 text-[12px] text-muted-foreground">{hint}</p> : null}
    </InsightCard>
  );
  if (!href) return inner;
  return (
    <Link
      href={href}
      className="block h-full rounded-[10px] outline-none transition-shadow hover:shadow-[0_1px_0_0_rgba(0,0,0,0.02),0_4px_16px_-4px_rgba(15,23,42,0.12)] focus-visible:ring-2 focus-visible:ring-ring"
    >
      {inner}
    </Link>
  );
}

export default function DashboardHomePage() {
  const { clinic, user } = useAuth();
  const [range, setRange] = useState<AnalyticsRange>("30d");
  const overview = useAnalyticsOverview(range);
  const conversations = useConversations({ limit: 6 });

  const timeZone = clinic?.timezone || "UTC";
  const name =
    user?.first_name?.trim() || clinic?.name?.trim() || "there";
  const data = overview.data;
  const summary = data?.summary;
  const trend = data?.conversation_appointment_trend ?? [];
  const specialties = data?.appointments_by_specialty ?? [];
  const recentChats = conversations.data?.results ?? [];

  const pendingAppointments =
    data?.appointment_status.find((row) => row.status === "pending")?.count ?? 0;
  const escalatedConversations = data?.ops.inbox.escalated ?? 0;
  const needsAttentionCount = pendingAppointments + escalatedConversations;

  return (
    <div>
      <PageHeader
        title={greetingForHour(hourInZone(timeZone), name)}
        description="Here's what's happening with your clinic."
        actions={<DateRangeSelector value={range} onChange={setRange} />}
      />
      <SetupChecklistCard />

      {overview.isError ? (
        <InsightCard className="mb-4 p-5">
          <p className="text-sm font-medium text-navy">Unable to load analytics</p>
          <button
            type="button"
            className="mt-2 text-[13px] font-medium text-primary hover:underline"
            onClick={() => void overview.refetch()}
          >
            Try again
          </button>
        </InsightCard>
      ) : null}

      {/* Clinic Pulse — what's true right now, not a trend. */}
      <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
        Clinic pulse
      </p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {overview.isLoading || !data ? (
          Array.from({ length: 4 }).map((_, i) => (
            <MetricCardSkeleton key={i} />
          ))
        ) : (
          <>
            <PulseTile
              label="Appointments today"
              value={data.ops.appointments_today.toLocaleString()}
              href="/dashboard/appointments"
            />
            <PulseTile
              label="Upcoming"
              value={data.ops.appointments_upcoming.toLocaleString()}
              hint="Confirmed or pending visits ahead"
              href="/dashboard/appointments"
            />
            <PulseTile
              label="Conversations"
              value={data.ops.inbox.active.toLocaleString()}
              hint="Currently active"
              href="/dashboard/conversations"
            />
            <PulseTile
              label="Needs attention"
              value={needsAttentionCount.toLocaleString()}
              hint={needsAttentionCount > 0 ? "Requires action" : "All clear"}
              href="/dashboard/conversations"
            />
          </>
        )}
      </div>

      {/* Secondary, historical metrics — same period, trend-oriented. */}
      <p className="mb-2.5 mt-6 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
        This period
      </p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {overview.isLoading || !summary ? (
          Array.from({ length: 4 }).map((_, i) => (
            <MetricCardSkeleton key={i} lines={3} />
          ))
        ) : (
          <>
            <KpiSparkCard
              label="Conversations"
              value={summary.conversations.toLocaleString()}
              change={summary.conversations_change_pct}
              spark={data?.conversations_daily}
              color="var(--insight-royal)"
            />
            <KpiSparkCard
              label="Appointments"
              value={summary.appointments.toLocaleString()}
              change={summary.appointments_change_pct}
              spark={data?.appointments_daily}
              color="var(--chart-3)"
            />
            <KpiSparkCard
              tone="ink"
              label="Total patients"
              value={summary.patients_total.toLocaleString()}
              spark={data?.patients_daily}
              color="var(--chart-2)"
            />
            <KpiSparkCard
              label="Completed appointments"
              value={summary.completed_appointments.toLocaleString()}
              change={summary.completed_change_pct}
              spark={data?.completed_daily}
              color="var(--insight-magenta)"
            />
          </>
        )}
      </div>

      {/* Synapse insight + needs attention — the "why" and the "what now." */}
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <SynapseInsightCard data={data} isLoading={overview.isLoading} />
        <NeedsAttentionCard
          escalatedConversations={escalatedConversations}
          pendingAppointments={pendingAppointments}
          isLoading={overview.isLoading}
        />
      </div>

      <div className="mt-4 flex flex-col gap-4 lg:flex-row">
        {overview.isLoading ? (
          <PanelSkeleton className="lg:w-[60%]" chartHeight={260} />
        ) : (
          <ChartPanel
            title="Conversations & Appointments"
            description="Daily volume in the clinic timezone"
            action={
              <AnalyticsLegend
                items={[
                  { label: "Conversations", color: CHART.purple },
                  { label: "Appointments", color: CHART.green },
                ]}
              />
            }
            metrics={
              summary ? (
                <div className="flex flex-wrap gap-x-8 gap-y-3">
                  <div>
                    <p className="text-[1.4rem] font-semibold leading-none tracking-tight text-navy tabular-nums">
                      {summary.conversations.toLocaleString()}
                    </p>
                    <p className="mt-1.5 flex items-center gap-1.5 text-[12px] text-muted-foreground">
                      conversations
                      <MetricChange value={summary.conversations_change_pct} />
                    </p>
                  </div>
                  <div>
                    <p className="text-[1.4rem] font-semibold leading-none tracking-tight text-navy tabular-nums">
                      {summary.appointments.toLocaleString()}
                    </p>
                    <p className="mt-1.5 flex items-center gap-1.5 text-[12px] text-muted-foreground">
                      appointments
                      <MetricChange value={summary.appointments_change_pct} />
                    </p>
                  </div>
                </div>
              ) : null
            }
            footer={
              <Link
                href="/dashboard/analytics"
                className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline"
              >
                View analytics
                <ArrowRight className="size-3" />
              </Link>
            }
            isLoading={false}
            isError={overview.isError}
            onRetry={() => void overview.refetch()}
            hasData={seriesHasValues(trend, ["conversations", "appointments"])}
            emptyTitle="No activity yet"
            emptyDescription="Conversations and bookings in this window will appear here."
            className="lg:w-[60%]"
          >
            <AnalyticsLineChart
              data={trend}
              series={[
                { key: "conversations", label: "Conversations", color: CHART.purple },
                { key: "appointments", label: "Appointments", color: CHART.green },
              ]}
              height={260}
            />
          </ChartPanel>
        )}
        <AppointmentSourceRadarCard
          data={data?.appointment_source_radar ?? []}
          isLoading={overview.isLoading}
          isError={overview.isError}
          onRetry={() => void overview.refetch()}
          className="lg:w-[38%]"
        />
      </div>

      {/* Today's operational picture + the inbox. */}
      <div className="mt-4 flex flex-col gap-4 lg:flex-row">
        <TodayScheduleCard
          todaySchedule={data?.today_schedule}
          nextAppointment={data?.next_appointment}
          timeZone={timeZone}
          patientsUpcoming={data?.ops.patients_upcoming}
          doctorsWithUpcoming={data?.ops.doctors_with_upcoming}
          isLoading={overview.isLoading}
          className="lg:w-[58%]"
        />

        {conversations.isLoading ? (
          <ListCardSkeleton className="min-w-0 flex-1 lg:w-[42%]" rows={5} />
        ) : (
          <InsightCard overflow="hidden" className="min-w-0 flex-1 lg:w-[42%]">
            <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
              <p className="text-sm font-medium text-navy">Recent conversations</p>
              <Link
                href="/dashboard/conversations"
                className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline"
              >
                View all
                <ArrowRight className="size-3" />
              </Link>
            </div>
            {!recentChats.length ? (
              <EmptyState
                icon={MessageSquare}
                title="No conversations yet"
                description="Patient chats from the widget will show up here."
              />
            ) : (
              <ul>
                {recentChats.map((c) => (
                  <li key={c.id} className="border-b border-border/70 last:border-0">
                    <Link
                      href="/dashboard/conversations"
                      className="block px-5 py-3 transition-colors hover:bg-muted/50"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-2">
                          <span
                            className={cn(
                              "size-1.5 shrink-0 rounded-full",
                              CONVERSATION_STATUS_DOT[c.status] ?? "bg-muted-foreground/40"
                            )}
                            aria-hidden
                          />
                          <span className="truncate text-sm font-medium text-navy">
                            {c.display_name}
                          </span>
                        </span>
                        <span className="shrink-0 text-[11px] text-muted-foreground">
                          {formatDistanceToNow(new Date(c.last_active_at), { addSuffix: true })}
                        </span>
                      </div>
                      <p className="mt-0.5 truncate pl-3.5 text-[12px] text-muted-foreground">
                        {c.last_message_preview || "No messages yet"}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </InsightCard>
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <AppointmentStatusCard
          data={data?.appointment_status}
          isLoading={overview.isLoading}
          isError={overview.isError}
          onRetry={() => void overview.refetch()}
        />
        <SpecialtyMixCard
          data={specialties}
          more={data?.appointments_by_specialty_more ?? 0}
          isLoading={overview.isLoading}
          isError={overview.isError}
          onRetry={() => void overview.refetch()}
        />
      </div>

      <div className="mt-4">
        <BookingCalendarCard timeZone={timeZone} className="w-full lg:max-w-[420px]" />
      </div>
    </div>
  );
}
