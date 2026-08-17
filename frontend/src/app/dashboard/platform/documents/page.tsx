"use client";

import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePlatformDocuments, queryKeys } from "@/hooks/api";
import { platformService } from "@/services";
import { getApiErrorMessage } from "@/lib/api/client";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";
import { formatWhen } from "@/features/platform/format";
import { StatusPill } from "@/features/platform/status-pill";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";

const FILTERS = [
  { value: "", label: "All" },
  { value: "failed", label: "Failed" },
  { value: "processing", label: "Processing" },
  { value: "pending", label: "Pending" },
  { value: "indexed", label: "Indexed" },
] as const;

export default function PlatformDocumentsPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const qc = useQueryClient();
  const [status, setStatus] = useState("failed");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const params = { status: status || undefined, search: q || undefined };
  const { data, isLoading } = usePlatformDocuments(params, ready);

  async function reload() {
    await qc.invalidateQueries({ queryKey: queryKeys.platformDocuments(params) });
  }

  async function reindex(id: string) {
    try {
      await platformService.reindexDocument(id);
      toast.success("Reindex queued");
      await reload();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Remove this document from the clinic knowledge base?")) return;
    try {
      await platformService.deleteDocument(id);
      toast.success("Document removed");
      await reload();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (!allowed) return null;
  const rows = data ?? [];

  return (
    <div>
      <PageHeader
        title="Documents"
        description="Knowledge files across every clinic. Reindex failed jobs or remove a broken upload."
      />
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
                placeholder="Search title or clinic…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-56"
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
          <p className="px-5 py-8 text-sm text-muted-foreground">Loading documents…</p>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={BookOpen}
            title="No documents here"
            description="Failed ingestions show up on the Failed tab so you can re-run them."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Document</TableHead>
                <TableHead>Clinic</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Chunks</TableHead>
                <TableHead className="pr-5 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="pl-5">
                    <p className="font-medium text-navy">{d.title}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {d.file_name} · {formatWhen(d.created_at)}
                    </p>
                    {d.error_message ? (
                      <p className="mt-1 max-w-sm truncate text-[11px] text-destructive">
                        {d.error_message}
                      </p>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <p className="text-sm">{d.clinic_name}</p>
                    <p className="text-[11px] text-muted-foreground">{d.clinic_slug}</p>
                  </TableCell>
                  <TableCell>
                    <StatusPill value={d.status} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{d.chunk_count}</TableCell>
                  <TableCell className="pr-5">
                    <div className="flex justify-end gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => void reindex(d.id)}>
                        Reindex
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => void remove(d.id)}>
                        Remove
                      </Button>
                    </div>
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
