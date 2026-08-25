"use client";

import { useState } from "react";
import { format, parseISO } from "date-fns";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  AnalyticsAreaChart,
  AnalyticsHorizontalBarChart,
  AnalyticsLegend,
  AnalyticsLineChart,
  AnalyticsStackedBarChart,
  AppointmentStatusCard,
  SpecialtyMixCard,
  ChartPanel,
  DateRangeSelector,
  MetricStat,
  formatDurationSeconds,
  seriesHasValues,
  type AnalyticsRange,
} from "@/components/dashboard/charts";
import { CHART } from "@/components/dashboard/charts/colors";
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
  children: React.ReactNode;
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

export default function AnalyticsPage() {
  const [range, setRange] = useState<AnalyticsRange>("30d");
  const query = useAnalyticsInsights(range);
  const data = query.data;
  const retry = () => void query.refetch();

  const volume = data?.conversations_detail.volume ?? [];
  const outcomes = data?.conversations_detail.outcomes ?? [];
  const apptTrend = data?.appointment_trend ?? [];
  const specialties = data?.appointments_by_specialty ?? [];
  const patientTrend = data?.patients_detail.trend ?? [];
  const frequency = data?.patients_detail.frequency ?? [];
  const providers = data?.appointments_by_provider ?? [];
  const providerStatus = data?.provider_status ?? [];
  const knowledgeGrowth = data?.knowledge.growth ?? [];
  const aiDaily = (data?.ai.daily ?? []).map((row) => ({
    date: row.date,
    count: row.calls,
  }));

  return (
    <div className="space-y-10">
      <PageHeader
        title="Analytics"
        description="Understand conversations, appointments, patients, and AI performance."
        actions={<DateRangeSelector value={range} onChange={setRange} />}
      />

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
        <div className="grid gap-4 lg:grid-cols-2">
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
          <div className="grid gap-4 sm:grid-cols-2">
            {query.isLoading || !data ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-[118px] animate-pulse rounded-[10px] bg-muted/70" />
              ))
            ) : (
              <>
                <MetricStat
                  label="Conversations"
                  value={data.summary.conversations.toLocaleString()}
                  hint={`${data.conversations_detail.active} active`}
                />
                <MetricStat
                  label="Avg. messages"
                  value={data.conversations_detail.avg_messages.toLocaleString()}
                  hint="Per conversation"
                />
                <MetricStat
                  label="Avg. duration"
                  value={formatDurationSeconds(data.conversations_detail.avg_duration_seconds)}
                  hint="Created to last activity"
                />
                <MetricStat
                  label="Escalated"
                  value={data.conversations_detail.escalated.toLocaleString()}
                  accent="amber"
                  hint="Handed to clinic staff"
                />
              </>
            )}
          </div>
        </div>
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
        <div className="grid gap-4 sm:grid-cols-3">
          {query.isLoading || !data ? (
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-[118px] animate-pulse rounded-[10px] bg-muted/70" />
            ))
          ) : (
            <>
              <MetricStat label="Total patients" value={data.summary.patients_total.toLocaleString()} />
              <MetricStat
                label="New patients"
                value={data.summary.patients_new.toLocaleString()}
                hint="Created in this period"
              />
              <MetricStat
                label="Returning patients"
                value={data.patients_detail.returning.toLocaleString()}
                hint="Booked now, registered earlier"
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
        <ChartPanel
          title="Patients by appointment count"
          description="Lifetime visits per patient"
          isLoading={query.isLoading}
          isError={query.isError}
          onRetry={retry}
          hasData={frequency.some((row) => row.count > 0)}
          emptyTitle="No repeat-visit data yet"
          emptyDescription="This fills in after patients start booking more than once."
        >
          <AnalyticsHorizontalBarChart data={frequency} height={200} />
        </ChartPanel>
      </Section>

      <Section title="Providers" description="Which providers are receiving appointments?">
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartPanel
            title="Appointments by provider"
            action={
              (data?.appointments_by_provider_more ?? 0) > 0 ? (
                <span className="text-[12px] text-muted-foreground">
                  +{data?.appointments_by_provider_more} more
                </span>
              ) : null
            }
            isLoading={query.isLoading}
            isError={query.isError}
            onRetry={retry}
            hasData={providers.some((row) => row.count > 0)}
            emptyTitle="No provider mix yet"
            emptyDescription="Booked visits will rank providers here."
          >
            <AnalyticsHorizontalBarChart data={providers} />
          </ChartPanel>
          <ChartPanel
            title="Provider performance"
            description="Completed, cancelled, and no-show"
            isLoading={query.isLoading}
            isError={query.isError}
            onRetry={retry}
            hasData={providerStatus.some(
              (row) => row.completed + row.cancelled + row.no_show > 0
            )}
            emptyTitle="No provider outcomes yet"
            emptyDescription="Status mix by provider appears after visits complete or cancel."
          >
            <AnalyticsStackedBarChart data={providerStatus} />
          </ChartPanel>
        </div>
      </Section>

      <Section title="AI usage" description="Is Synapse being used effectively?">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {query.isLoading || !data ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-[118px] animate-pulse rounded-[10px] bg-muted/70" />
            ))
          ) : (
            <>
              <MetricStat label="AI requests" value={data.ai.calls.toLocaleString()} />
              <MetricStat label="Token usage" value={formatTokens(data.ai.total_tokens)} />
              {data.show_cost ? (
                <MetricStat
                  label="Estimated AI cost"
                  value={formatUsd(data.ai.estimated_usd ?? 0)}
                  hint="OpenAI list price · this clinic"
                />
              ) : (
                <MetricStat
                  label="Prompt / completion"
                  value={`${formatTokens(data.ai.prompt_tokens)} / ${formatTokens(data.ai.completion_tokens)}`}
                />
              )}
              <MetricStat
                label="Avg. latency"
                value={data.ai.avg_latency_ms ? `${data.ai.avg_latency_ms} ms` : "—"}
                hint={`${data.ai.cached_calls.toLocaleString()} cached calls`}
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
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-[118px] animate-pulse rounded-[10px] bg-muted/70" />
            ))
          ) : (
            <>
              <MetricStat label="Documents" value={data.knowledge.documents.toLocaleString()} />
              <MetricStat label="Knowledge chunks" value={data.knowledge.chunks.toLocaleString()} />
              <MetricStat
                label="Last updated"
                value={
                  data.knowledge.last_updated
                    ? format(parseISO(data.knowledge.last_updated), "MMM d, yyyy")
                    : "—"
                }
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
