"use client";

import { useMemo, useState } from "react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ModelMix, OperationMix } from "@/features/analytics/model-mix";
import { TokenSparkline } from "@/features/analytics/token-sparkline";
import { useClinicAnalytics } from "@/hooks/api";
import { fillDailySeries, formatTokens, formatUsd } from "@/lib/analytics-format";

type Range = "7" | "30";

export default function AnalyticsPage() {
  const [range, setRange] = useState<Range>("30");
  const days = Number(range);
  const { data, isLoading } = useClinicAnalytics(days);

  const series = useMemo(
    () => fillDailySeries(data?.daily ?? [], days),
    [data?.daily, days]
  );

  const showCost = Boolean(data?.show_cost);

  return (
    <div>
      <PageHeader
        title="Analytics"
        description={
          showCost
            ? "Token volume and estimated OpenAI spend for this clinic."
            : "How the front-desk assistant is being used — tokens, routing, and bookings."
        }
        actions={
          <Tabs value={range} onValueChange={(v) => v && setRange(v as Range)}>
            <TabsList aria-label="Date range">
              <TabsTrigger value="7" className="px-3">
                7 days
              </TabsTrigger>
              <TabsTrigger value="30" className="px-3">
                30 days
              </TabsTrigger>
            </TabsList>
          </Tabs>
        }
      />

      {isLoading || !data ? (
        <p className="text-sm text-muted-foreground">Loading usage…</p>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi label="Tokens" value={formatTokens(data.total_tokens)} hint={`${data.calls.toLocaleString()} model calls`} />
            <Kpi
              label="Conversations"
              value={data.conversations.toLocaleString()}
              hint="Chat sessions started"
            />
            <Kpi
              label="Chatbot bookings"
              value={data.chatbot_bookings.toLocaleString()}
              hint="Appointments from the widget"
            />
            {showCost ? (
              <Kpi
                label="Estimated spend"
                value={formatUsd(data.estimated_usd ?? 0)}
                hint="OpenAI list price · this clinic"
              />
            ) : (
              <Kpi
                label="Prompt / completion"
                value={`${formatTokens(data.prompt_tokens)} / ${formatTokens(data.completion_tokens)}`}
                hint={data.avg_latency_ms ? `${data.avg_latency_ms} ms avg` : "Input vs output"}
              />
            )}
          </div>

          <Card>
            <CardHeader className="flex flex-row items-end justify-between gap-3 space-y-0">
              <div>
                <CardTitle>Daily tokens</CardTitle>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Each bar is one clinic day.
                </p>
              </div>
              <p className="font-mono text-sm tabular-nums text-navy">
                {formatTokens(data.total_tokens)}
              </p>
            </CardHeader>
            <CardContent className="pt-1 pb-5">
              <TokenSparkline points={series} />
            </CardContent>
          </Card>

          <div className="grid gap-5 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle>Models in use</CardTitle>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  gpt-4.1-nano routes intent. gpt-4.1-mini writes replies.
                </p>
              </CardHeader>
              <CardContent>
                <ModelMix rows={data.models} showCost={showCost} />
              </CardContent>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>By job</CardTitle>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Where tokens go — routing, replies, and knowledge.
                </p>
              </CardHeader>
              <CardContent>
                <OperationMix rows={data.operations} />
              </CardContent>
            </Card>
          </div>

          {showCost && data.rates.length ? (
            <p className="text-[11px] text-muted-foreground">
              Estimated from OpenAI list prices (standard, non-batch). Clinic owners
              see token counts only.
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <Card>
      <CardContent className="px-5 py-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tracking-tight text-navy tabular-nums">
          {value}
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );
}
