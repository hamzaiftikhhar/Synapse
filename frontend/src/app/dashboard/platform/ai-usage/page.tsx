"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ModelMix } from "@/features/analytics/model-mix";
import { TokenSparkline } from "@/features/analytics/token-sparkline";
import { usePlatformAiUsage } from "@/hooks/api";
import { fillDailySeries, formatTokens, formatUsd } from "@/lib/analytics-format";
import { useAuth } from "@/providers/auth-provider";

type Range = "7" | "30";

export default function PlatformAiUsagePage() {
  const { user } = useAuth();
  const router = useRouter();
  const [range, setRange] = useState<Range>("30");
  const days = Number(range);
  const enabled = user?.role === "SUPER_ADMIN";
  const { data, isLoading } = usePlatformAiUsage(days, enabled);

  const series = useMemo(
    () => fillDailySeries(data?.daily ?? [], days),
    [data?.daily, days]
  );

  if (user && user.role !== "SUPER_ADMIN") {
    router.replace("/dashboard");
    return null;
  }

  const maxTokens = Math.max(...(data?.clinics.map((c) => c.total_tokens) ?? [1]), 1);

  return (
    <div>
      <PageHeader
        title="AI usage"
        description="Tokens and estimated OpenAI spend across every clinic."
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
          <div className="grid gap-3 sm:grid-cols-3">
            <Card className="sm:col-span-1">
              <CardContent className="px-5 py-5">
                <p className="text-xs tracking-wide text-muted-foreground uppercase">
                  Estimated spend
                </p>
                <p className="mt-2 font-mono text-4xl font-semibold tracking-tight text-navy tabular-nums">
                  {formatUsd(data.estimated_usd)}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  OpenAI list price · {data.days}d · {data.clinics.length} clinics
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="px-5 py-5">
                <p className="text-xs text-muted-foreground">Tokens</p>
                <p className="mt-2 text-3xl font-semibold tracking-tight text-navy tabular-nums">
                  {formatTokens(data.total_tokens)}
                </p>
                <p className="mt-2 text-xs tabular-nums text-muted-foreground">
                  {data.prompt_tokens.toLocaleString()} in ·{" "}
                  {data.completion_tokens.toLocaleString()} out
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="px-5 py-5">
                <p className="text-xs text-muted-foreground">Model calls</p>
                <p className="mt-2 text-3xl font-semibold tracking-tight text-navy tabular-nums">
                  {data.calls.toLocaleString()}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  gpt-4.1-nano routes · gpt-4.1-mini replies
                </p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Daily tokens</CardTitle>
            </CardHeader>
            <CardContent>
              <TokenSparkline
                points={series.map((p) => ({
                  label: p.label,
                  total_tokens: p.total_tokens,
                }))}
              />
              <div className="mt-2 flex justify-between text-[10px] text-muted-foreground">
                <span>{series[0]?.label}</span>
                <span>{series[series.length - 1]?.label}</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>By clinic</CardTitle>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Clinic owners never see these dollar amounts.
              </p>
            </CardHeader>
            <CardContent className="p-0">
              {data.clinics.length ? (
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="pl-5">Clinic</TableHead>
                      <TableHead className="text-right">Tokens</TableHead>
                      <TableHead className="hidden text-right sm:table-cell">
                        In / out
                      </TableHead>
                      <TableHead className="pr-5 text-right">Est. cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.clinics.map((clinic) => (
                      <TableRow key={clinic.clinic_id}>
                        <TableCell className="pl-5 whitespace-normal">
                          <p className="font-medium text-navy">{clinic.name}</p>
                          <p className="text-[11px] text-muted-foreground">{clinic.slug}</p>
                          <div className="mt-1.5 h-1 max-w-xs overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full rounded-full bg-navy"
                              style={{
                                width: `${Math.max((clinic.total_tokens / maxTokens) * 100, 2)}%`,
                              }}
                            />
                          </div>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatTokens(clinic.total_tokens)}
                          <span className="block text-[11px] text-muted-foreground">
                            {clinic.calls.toLocaleString()} calls
                          </span>
                        </TableCell>
                        <TableCell className="hidden text-right text-xs tabular-nums text-muted-foreground sm:table-cell">
                          {formatTokens(clinic.prompt_tokens)} /{" "}
                          {formatTokens(clinic.completion_tokens)}
                        </TableCell>
                        <TableCell className="pr-5 text-right font-mono text-sm tabular-nums text-navy">
                          {formatUsd(clinic.estimated_usd)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="px-5 py-8 text-sm text-muted-foreground">
                  No usage logged yet.
                </p>
              )}
            </CardContent>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Models</CardTitle>
              </CardHeader>
              <CardContent>
                <ModelMix rows={data.models} showCost />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Rate card</CardTitle>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  USD per 1M tokens · OpenAI standard pricing
                </p>
              </CardHeader>
              <CardContent>
                <ul className="divide-y divide-border font-mono text-[13px]">
                  {data.rates
                    .filter((r) =>
                      data.models.some((m) => m.model === r.model) ||
                      ["gpt-4.1-nano", "gpt-4.1-mini", "gpt-4o-mini", "text-embedding-3-small"].includes(
                        r.model
                      )
                    )
                    .map((r) => (
                      <li
                        key={r.model}
                        className="flex items-baseline justify-between gap-3 py-2 first:pt-0 last:pb-0"
                      >
                        <span className="text-navy">{r.model}</span>
                        <span className="tabular-nums text-muted-foreground">
                          ${r.input_usd_per_1m.toFixed(2)} / ${r.output_usd_per_1m.toFixed(2)}
                        </span>
                      </li>
                    ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
