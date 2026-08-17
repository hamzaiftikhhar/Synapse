"use client";

import { useState } from "react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
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
import { usePlatformMonitoring } from "@/hooks/api";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";
import { formatWhen } from "@/features/platform/format";
import { OPERATION_LABEL, formatTokens } from "@/lib/analytics-format";

export default function PlatformAiMonitoringPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const [days, setDays] = useState("7");
  const { data, isLoading } = usePlatformMonitoring(Number(days), ready);

  if (!allowed) return null;

  return (
    <div>
      <PageHeader
        title="AI monitoring"
        description="Latency, cache hits, and the slowest model calls across clinics."
        actions={
          <Tabs value={days} onValueChange={setDays}>
            <TabsList>
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
        <p className="text-sm text-muted-foreground">Loading traces…</p>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi label="Calls" value={data.calls.toLocaleString()} hint={`${data.cached_calls} cached`} />
            <Kpi label="Average" value={`${data.avg_latency_ms} ms`} hint="Mean latency" />
            <Kpi label="p95" value={`${data.p95_latency_ms} ms`} hint="Slow tail" />
            <Kpi
              label="Slow calls"
              value={data.slow_calls.toLocaleString()}
              hint="≥ 2 seconds"
            />
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>By job</CardTitle>
              </CardHeader>
              <CardContent>
                {data.by_operation.length ? (
                  <ul className="space-y-3">
                    {data.by_operation.map((row) => (
                      <li key={row.key} className="flex items-baseline justify-between gap-3 text-sm">
                        <span>{OPERATION_LABEL[row.key] ?? row.key}</span>
                        <span className="tabular-nums text-muted-foreground">
                          {row.avg_latency_ms} ms · {formatTokens(row.tokens)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">No calls in this window.</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>By model</CardTitle>
              </CardHeader>
              <CardContent>
                {data.by_model.length ? (
                  <ul className="space-y-3">
                    {data.by_model.map((row) => (
                      <li key={row.key} className="flex items-baseline justify-between gap-3 text-sm">
                        <span className="font-mono text-[13px]">{row.key}</span>
                        <span className="tabular-nums text-muted-foreground">
                          {row.calls.toLocaleString()} · {row.avg_latency_ms} ms
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">No models recorded.</p>
                )}
              </CardContent>
            </Card>
          </div>

          <DataTableShell title="Slowest calls">
            {data.slowest.length ? (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-5">When</TableHead>
                    <TableHead>Clinic</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead className="text-right">Latency</TableHead>
                    <TableHead className="pr-5 text-right">Tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.slowest.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="pl-5 text-xs text-muted-foreground">
                        {formatWhen(row.created_at)}
                      </TableCell>
                      <TableCell>{row.clinic_name}</TableCell>
                      <TableCell className="font-mono text-[12px]">{row.model}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.latency_ms} ms</TableCell>
                      <TableCell className="pr-5 text-right tabular-nums">
                        {row.total_tokens.toLocaleString()}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="No slow calls" description="Nothing over the usual latency yet." />
            )}
          </DataTableShell>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Card>
      <CardContent className="px-5 py-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums text-navy">{value}</p>
        <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );
}
