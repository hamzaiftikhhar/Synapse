"use client";

import { useState } from "react";
import Link from "next/link";
import { MessageSquare } from "lucide-react";
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
  greetingForHour,
  seriesHasValues,
  type AnalyticsRange,
} from "@/components/dashboard/charts";
import { CHART } from "@/components/dashboard/charts/colors";
import { InsightCard, GlyphStat, KpiSparkCard } from "@/components/dashboard/insights";
import { useAnalyticsOverview, useConversations } from "@/hooks/api";
import { useAuth } from "@/providers/auth-provider";

function hourInZone(timeZone: string): number {
  const hour = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "numeric",
    hourCycle: "h23",
  }).format(new Date());
  const parsed = Number(hour);
  return Number.isFinite(parsed) ? parsed : new Date().getHours();
}

export default function DashboardHomePage() {
  const { clinic, user } = useAuth();
  const [range, setRange] = useState<AnalyticsRange>("30d");
  const overview = useAnalyticsOverview(range);
  const conversations = useConversations({ limit: 8 });

  const timeZone = clinic?.timezone || "UTC";
  const name =
    user?.first_name?.trim() || clinic?.name?.trim() || "there";
  const data = overview.data;
  const summary = data?.summary;
  const trend = data?.conversation_appointment_trend ?? [];
  const specialties = data?.appointments_by_specialty ?? [];
  const recentChats = conversations.data?.results ?? [];

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

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {overview.isLoading || !summary ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-[104px] animate-pulse rounded-[10px] bg-muted/70" />
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

      <div className="mt-4 flex flex-col gap-4 lg:flex-row">
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
          isLoading={overview.isLoading}
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
            height={280}
          />
        </ChartPanel>
        <AppointmentSourceRadarCard
          data={data?.appointment_source_radar ?? []}
          isLoading={overview.isLoading}
          isError={overview.isError}
          onRetry={() => void overview.refetch()}
          className="lg:w-[38%]"
        />
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <GlyphStat
          label="Appointments today"
          value={(data?.ops.appointments_today ?? 0).toLocaleString()}
          glyph="calendar"
        />
        <GlyphStat
          label="Patients with upcoming visits"
          value={(data?.ops.patients_upcoming ?? 0).toLocaleString()}
          glyph="people"
        />
        <GlyphStat
          label="Providers with upcoming visits"
          value={(data?.ops.doctors_with_upcoming ?? 0).toLocaleString()}
          glyph="stethoscope"
        />
        <GlyphStat
          label="Escalated conversations"
          value={(data?.ops.inbox.escalated ?? 0).toLocaleString()}
          glyph="chat"
        />
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

      <div className="mt-4 flex flex-col gap-4 lg:flex-row">
        <InsightCard overflow="hidden" className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
            <p className="text-sm font-medium text-navy">Recent conversations</p>
            <Link
              href="/dashboard/conversations"
              className="inline-flex h-7 items-center rounded-[8px] border border-border px-2.5 text-[0.8rem] hover:bg-muted"
            >
              Inbox
            </Link>
          </div>
          {conversations.isLoading ? (
            <div className="h-48 animate-pulse bg-muted/50" />
          ) : !recentChats.length ? (
            <EmptyState
              icon={MessageSquare}
              title="No conversations yet"
              description="Patient chats from the widget will show up here."
            />
          ) : (
            <ul>
              {recentChats.map((c) => (
                <li key={c.id} className="border-b border-border/70 px-5 py-3 last:border-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-navy">{c.display_name}</p>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {formatDistanceToNow(new Date(c.last_active_at), { addSuffix: true })}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-[12px] text-muted-foreground">
                    {c.last_message_preview || "No messages yet"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </InsightCard>

        <BookingCalendarCard timeZone={timeZone} className="w-full lg:w-[33%] lg:shrink-0" />
      </div>
    </div>
  );
}
