"use client";

import { useRef } from "react";
import { format } from "date-fns";
import { toast } from "sonner";
import { RefreshCw, Upload } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDocuments, useReindexDocument, useUploadDocument } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";

export default function KnowledgePage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const { data, isLoading } = useDocuments();
  const upload = useUploadDocument();
  const reindex = useReindexDocument();
  const rows = data ?? [];

  async function onFile(file: File | undefined) {
    if (!file) return;
    try {
      await upload.mutateAsync({ file, title: file.name });
      toast.success("Document uploaded — indexing started");
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  async function onReindex(id: string) {
    try {
      await reindex.mutateAsync(id);
      toast.success("Reindex started");
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Knowledge Base"
        description="Upload clinic PDFs for RAG answers in the patient chatbot."
        actions={
          <>
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={(e) => onFile(e.target.files?.[0])}
            />
            <Button
              className="rounded-[6px]"
              onClick={() => inputRef.current?.click()}
              disabled={upload.isPending}
            >
              <Upload className="size-4" />
              {upload.isPending ? "Uploading…" : "Upload PDF"}
            </Button>
          </>
        }
      />
      <DataTableShell>
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">Loading…</p>
        ) : !rows.length ? (
          <EmptyState
            title="No documents"
            description="Upload a PDF to power knowledge answers."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Chunks</TableHead>
                <TableHead>Updated</TableHead>
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>
                    <div className="font-medium">{d.title || d.file_name}</div>
                    <div className="text-xs text-muted-foreground">{d.file_name}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="rounded-[6px] capitalize">
                      {d.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{d.chunk_count}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {format(new Date(d.updated_at), "MMM d, yyyy")}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-[6px]"
                      onClick={() => onReindex(d.id)}
                    >
                      <RefreshCw className="size-3.5" /> Reindex
                    </Button>
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
