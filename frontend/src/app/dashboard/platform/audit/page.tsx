"use client";

import { useState } from "react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePlatformAudit } from "@/hooks/api";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";
import { formatWhen, humanAction } from "@/features/platform/format";
import { Shield } from "lucide-react";

export default function PlatformAuditPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const { data, isLoading } = usePlatformAudit({ search: q || undefined }, ready);

  if (!allowed) return null;
  const rows = data ?? [];

  return (
    <div>
      <PageHeader
        title="Audit logs"
        description="Who entered a clinic, changed status, invited staff, or touched billing."
      />
      <DataTableShell
        toolbar={
          <form
            className="flex w-full gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setQ(search.trim());
            }}
          >
            <Input
              placeholder="Search actor, clinic, or action…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-sm"
            />
            <Button type="submit" size="sm" variant="outline">
              Search
            </Button>
          </form>
        }
      >
        {isLoading ? (
          <p className="px-5 py-8 text-sm text-muted-foreground">Loading audit trail…</p>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Shield}
            title="No events yet"
            description="Sensitive platform actions append here as they happen."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">When</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Clinic</TableHead>
                <TableHead className="pr-5">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="pl-5 text-xs text-muted-foreground whitespace-nowrap">
                    {formatWhen(row.created_at)}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="capitalize">
                      {humanAction(row.action)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm">{row.actor_email}</TableCell>
                  <TableCell className="text-sm">{row.clinic_name || "—"}</TableCell>
                  <TableCell className="pr-5 max-w-[280px] truncate font-mono text-[11px] text-muted-foreground">
                    {row.object_type
                      ? `${row.object_type}${row.object_id ? ` ${row.object_id.slice(0, 8)}` : ""}`
                      : row.ip_address || "—"}
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
