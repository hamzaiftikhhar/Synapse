"use client";

import { useMemo, useState } from "react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePlatformSubscriptions } from "@/hooks/api";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";
import { formatCents, formatWhen } from "@/features/platform/format";
import { StatusPill } from "@/features/platform/status-pill";
import { CreditCard } from "lucide-react";

const FILTERS = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "trialing", label: "Trial" },
  { value: "incomplete", label: "Incomplete" },
  { value: "past_due", label: "Past due" },
  { value: "canceled", label: "Canceled" },
] as const;

export default function PlatformSubscriptionsPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const { data, isLoading } = usePlatformSubscriptions(
    { status: status || undefined, search: q || undefined },
    ready
  );

  const rows = useMemo(() => data ?? [], [data]);
  const paying = useMemo(
    () =>
      rows.filter((r) => r.status === "active" || r.status === "trialing").length,
    [rows]
  );
  const listedMrr = useMemo(
    () =>
      rows
        .filter((r) => r.status === "active")
        .reduce((sum, r) => sum + (r.display_price_cents ?? 0), 0),
    [rows]
  );

  if (!allowed) return null;

  return (
    <div>
      <PageHeader
        title="Subscriptions"
        description="Paddle is the billing source of truth. This list is the local mirror used for access."
      />

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <Card>
          <CardContent className="px-5 py-4">
            <p className="text-xs text-muted-foreground">Listed MRR</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-navy">
              {formatCents(listedMrr)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="px-5 py-4">
            <p className="text-xs text-muted-foreground">In good standing</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-navy">{paying}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="px-5 py-4">
            <p className="text-xs text-muted-foreground">Subscriptions</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-navy">{rows.length}</p>
          </CardContent>
        </Card>
      </div>

      <DataTableShell
        toolbar={
          <div className="flex w-full flex-wrap items-center gap-2">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                setQ(search.trim());
              }}
            >
              <Input
                placeholder="Search clinic…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-52"
              />
              <Button type="submit" size="sm" variant="outline">
                Search
              </Button>
            </form>
            <Tabs value={status} onValueChange={setStatus}>
              <TabsList>
                {FILTERS.map((f) => (
                  <TabsTrigger key={f.label} value={f.value} className="px-3">
                    {f.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>
        }
      >
        {isLoading ? (
          <p className="px-5 py-8 text-sm text-muted-foreground">Loading subscriptions…</p>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={CreditCard}
            title="No subscriptions"
            description="Approving an application attaches a plan. Payment still comes from Paddle."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Clinic</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Period end</TableHead>
                <TableHead className="pr-5 text-right">Price</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="pl-5">
                    <p className="font-medium text-navy">{s.clinic_name}</p>
                    <p className="text-[11px] text-muted-foreground">{s.clinic_slug}</p>
                  </TableCell>
                  <TableCell>{s.plan_name}</TableCell>
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <StatusPill value={s.status} />
                      {s.cancel_at_period_end ? (
                        <span className="text-[11px] text-muted-foreground">Cancels at period end</span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatWhen(s.current_period_end)}
                  </TableCell>
                  <TableCell className="pr-5 text-right tabular-nums">
                    {formatCents(s.display_price_cents, s.display_currency)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DataTableShell>
    </div>
  );
}
