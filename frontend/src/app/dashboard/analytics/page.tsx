"use client";

import { useState, type ReactNode } from "react";
import { format, parseISO } from "date-fns";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  AnalyticsAreaChart,
  AnalyticsLegend,
  AnalyticsLineChart,
  AppointmentStatusCard,
  SpecialtyMixCard,
  ChartPanel,
  DateRangeSelector,
  seriesHasValues,
  type AnalyticsRange,
} from "@/components/dashboard/charts";
import { CHART } from "@/components/dashboard/charts/colors";
import { GlyphStat, KpiSparkCard } from "@/components/dashboard/insights";
import { ModelMix } from "@/features/analytics/model-mix";
import { useAnalyticsInsights } from "@/hooks/api";
import { formatTokens, formatUsd } from "@/lib/analytics-format";

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-navy">{title}</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  );
}

function KpiSkeleton({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="h-[104px] animate-pulse rounded-[10px] bg-muted/70" />
      ))}
    </>
  );
}

export default function AnalyticsPage() {
  const [range, setRange] = useState<AnalyticsRange>("30d");
  const query = useAnalyticsInsights(range);
  const data = query.data;
  const retry = () => void query.refetch();
  const summary = data?.summary;

  const volume = data?.conversations_detail.volume ?? [];
  const outcomes = data?.conversations_detail.outcomes ?? [];
  const apptTrend = data?.appointment_trend ?? [];
  const specialties = data?.appointments_by_specialty ?? [];
  const patientTrend = data?.patients_detail.trend ?? [];
  const knowledgeGrowth = data?.knowledge.growth ?? [];
  const aiDaily = (data?.ai.daily ?? []).map((row) => ({
    date: row.date,
    count: row.calls,
  }));
  const aiSpark = (data?.ai.daily ?? []).map((row) => row.calls);

  return (
    <div className="space-y-10">
      <PageHeader
        title="Analytics"
        description="Understand conversations, appointments, patients, and AI performance."
        actions={<DateRangeSelector value={range} onChange={setRange} />}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {query.isLoading || !summary ? (
          <KpiSkeleton count={4} />
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

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
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

      <Section
        title="Conversations"
        description="Understand how patients interact with Synapse."
      >
        <ChartPanel
          title="Conversation volume"
          isLoading={query.isLoading}
          isError={query.isError}
          onRetry={retry}
          hasData={seriesHasValues(volume, ["count"])}
          emptyTitle="No conversations yet"
          emptyDescription="Widget chats in this window will draw a trend here."
        >
          <AnalyticsAreaChart data={volume} dataKey="count" label="Conversations" />
        </ChartPanel>
        <ChartPanel
          title="Conversation outcomes"
          description="Closed and escalated sessions by day"
          action={
            <AnalyticsLegend
              items={[
                { label: "Closed", color: CHART.green },
                { label: "Escalated", color: CHART.amber },
              ]}
            />
          }
          isLoading={query.isLoading}
          isError={query.isError}
          onRetry={retry}
          hasData={seriesHasValues(outcomes, ["closed", "escalated"])}
          emptyTitle="No outcomes yet"
          emptyDescription="Closed and escalated conversations will appear once sessions finish."
        >
          <AnalyticsLineChart
            data={outcomes}
            series={[
              { key: "closed", label: "Closed", color: CHART.green },
              { key: "escalated", label: "Escalated", color: CHART.amber },
            ]}
          />
        </ChartPanel>
      </Section>

      <Section title="Appointments" description="Are patients actually booking?">
        <ChartPanel
          title="Appointment trend"
          description="Appointments created per clinic day"
          isLoading={query.isLoading}
          isError={query.isError}
          onRetry={retry}
          hasData={seriesHasValues(apptTrend, ["count"])}
          emptyTitle="No appointment data yet"
          emptyDescription="Once patients book appointments, your appointment trends will appear here."
        >
          <AnalyticsAreaChart data={apptTrend} dataKey="count" label="Appointments" />
        </ChartPanel>
        <div className="grid gap-4 lg:grid-cols-2">
          <AppointmentStatusCard
            data={data?.appointment_status}
            isLoading={query.isLoading}
            isError={query.isError}
            onRetry={retry}
          />
          <SpecialtyMixCard
            data={specialties}
            more={data?.appointments_by_specialty_more ?? 0}
            isLoading={query.isLoading}
            isError={query.isError}
            onRetry={retry}
          />
        </div>
      </Section>

      <Section title="Patients" description="Are we gaining and retaining patients?">
        <div className="grid gap-4 sm:grid-cols-2">
          {query.isLoading || !data ? (
            <KpiSkeleton count={2} />
          ) : (
            <>
              <GlyphStat
                label="New patients"
                value={data.summary.patients_new.toLocaleString()}
                hint="Created in this period"
                glyph="people"
              />
              <GlyphStat
                label="Returning patients"
                value={data.patients_detail.returning.toLocaleString()}
                hint="Booked now, registered earlier"
                glyph="booking"
              />
            </>
          )}
        </div>
        <ChartPanel
          title="New vs returning patients"
          action={
            <AnalyticsLegend
              items={[
                { label: "New", color: CHART.purple },
                { label: "Returning", color: CHART.blue },
              ]}
            />
          }
          isLoading={query.isLoading}
          isError={query.isError}
          onRetry={retry}
          hasData={seriesHasValues(patientTrend, ["new", "returning"])}
          emptyTitle="No patient trend yet"
          emptyDescription="New registrations and returning bookings will appear here."
        >
          <AnalyticsLineChart
            data={patientTrend}
            series={[
              { key: "new", label: "New", color: CHART.purple },
              { key: "returning", label: "Returning", color: CHART.blue },
            ]}
          />
        </ChartPanel>
      </Section>

      <Section title="AI usage" description="Is Synapse being used effectively?">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {query.isLoading || !data ? (
            <KpiSkeleton count={4} />
          ) : (
            <>
              <KpiSparkCard
                label="AI requests"
                value={data.ai.calls.toLocaleString()}
                spark={aiSpark}
                color="var(--insight-royal)"
              />
              <GlyphStat
                label="Token usage"
                value={formatTokens(data.ai.total_tokens)}
                glyph="tokens"
              />
              {data.show_cost ? (
                <GlyphStat
                  label="Estimated AI cost"
                  value={formatUsd(data.ai.estimated_usd ?? 0)}
                  hint="OpenAI list price · this clinic"
                  glyph="pulse"
                />
              ) : (
                <GlyphStat
                  label="Prompt / completion"
                  value={`${formatTokens(data.ai.prompt_tokens)} / ${formatTokens(data.ai.completion_tokens)}`}
                  glyph="pulse"
                />
              )}
              <GlyphStat
                label="Avg. latency"
                value={data.ai.avg_latency_ms ? `${data.ai.avg_latency_ms} ms` : "—"}
                hint={`${data.ai.cached_calls.toLocaleString()} cached calls`}
                glyph="booking"
              />
            </>
          )}
        </div>
        <ChartPanel
          title="AI usage over time"
          description="Model calls per clinic day"
          isLoading={query.isLoading}
          isError={query.isError}
          onRetry={retry}
          hasData={seriesHasValues(aiDaily, ["count"])}
          emptyTitle="No AI usage yet"
          emptyDescription="Routing and reply calls will appear after the assistant is used."
        >
          <AnalyticsAreaChart data={aiDaily} dataKey="count" label="AI requests" />
        </ChartPanel>
        {data?.ai.models.length ? (
          <ChartPanel
            title="AI usage by model"
            hasData
            emptyTitle=""
            emptyDescription=""
          >
            <ModelMix rows={data.ai.models} showCost={data.show_cost} />
          </ChartPanel>
        ) : null}
      </Section>

      <Section title="Knowledge base" description="Clinic documents available to the assistant.">
        <div className="grid gap-4 sm:grid-cols-3">
          {query.isLoading || !data ? (
            <KpiSkeleton count={3} />
          ) : (
            <>
              <GlyphStat
                label="Documents"
                value={data.knowledge.documents.toLocaleString()}
                glyph="folder"
              />
              <GlyphStat
                label="Knowledge chunks"
                value={data.knowledge.chunks.toLocaleString()}
                glyph="tokens"
              />
              <GlyphStat
                label="Last updated"
                value={
                  data.knowledge.last_updated
                    ? format(parseISO(data.knowledge.last_updated), "MMM d, yyyy")
                    : "—"
                }
                glyph="calendar"
              />
            </>
          )}
        </div>
        <ChartPanel
          title="Knowledge base growth"
          description="Documents added per clinic day"
          isLoading={query.isLoading}
          isError={query.isError}
          onRetry={retry}
          hasData={seriesHasValues(knowledgeGrowth, ["count"])}
          emptyTitle="No document growth yet"
          emptyDescription="Uploaded clinic documents will appear as a growth trend here."
        >
          <AnalyticsAreaChart data={knowledgeGrowth} dataKey="count" label="Documents" />
        </ChartPanel>
      </Section>
    </div>
  );
}
