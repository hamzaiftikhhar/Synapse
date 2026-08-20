"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { format } from "date-fns";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/api/client";
import { documentsService } from "@/services";
import type { KnowledgeDocument } from "@/types/api";
import { DocumentStatusBadge } from "./document-status-badge";
import {
  formatBytes,
  formatDurationMs,
  openBlobInNewTab,
  processingDurationMs,
  triggerBlobDownload,
} from "./utils";

const PdfViewer = dynamic(
  () => import("./pdf-viewer").then((m) => m.PdfViewer),
  {
    ssr: false,
    loading: () => (
      <div className="flex min-h-[28rem] items-center justify-center rounded-[6px] border border-border bg-zinc-50 text-sm text-muted-foreground">
        Loading viewer…
      </div>
    ),
  }
);

type DetailProps = {
  document: KnowledgeDocument | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit: (doc: KnowledgeDocument) => void;
};

export function DocumentDetailDialog({
  document,
  open,
  onOpenChange,
  onEdit,
}: DetailProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [loadingPdf, setLoadingPdf] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);

  const documentId = document?.id;

  useEffect(() => {
    if (!open || !documentId) {
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
      setBlob(null);
      setPdfError(null);
      return;
    }

    let revoked = false;
    let objectUrl: string | null = null;
    setLoadingPdf(true);
    setPdfError(null);

    documentsService
      .downloadBlob(documentId, true)
      .then((data) => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(data);
        setBlob(data);
        setBlobUrl(objectUrl);
      })
      .catch((e) => {
        if (!revoked) setPdfError(getApiErrorMessage(e));
      })
      .finally(() => {
        if (!revoked) setLoadingPdf(false);
      });

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [open, documentId]);

  if (!document) return null;

  const duration = processingDurationMs(document);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[92vh] w-[min(1100px,calc(100%-1.5rem))] max-w-none flex-col gap-0 overflow-hidden rounded-[8px] p-0 sm:max-w-none"
        showCloseButton
      >
        <DialogHeader className="shrink-0 border-b border-border px-5 py-4 text-left">
          <div className="pr-8">
            <DialogTitle className="truncate text-base font-semibold text-navy">
              {document.title || document.file_name}
            </DialogTitle>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <DocumentStatusBadge document={document} />
              <span>{formatBytes(document.file_size_bytes)}</span>
              <span>·</span>
              <span>{document.chunk_count} chunks</span>
              {duration != null ? (
                <>
                  <span>·</span>
                  <span>{formatDurationMs(duration)}</span>
                </>
              ) : null}
            </div>
          </div>
        </DialogHeader>

        <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[240px_minmax(0,1fr)]">
          <aside className="space-y-4 overflow-y-auto border-b border-border p-5 lg:border-r lg:border-b-0">
            <MetaRow label="File name" value={document.file_name} />
            <MetaRow
              label="Uploaded"
              value={format(new Date(document.created_at), "MMM d, yyyy HH:mm")}
            />
            <MetaRow
              label="Uploaded by"
              value={
                document.uploaded_by_name ||
                document.uploaded_by_email ||
                "—"
              }
            />
            <MetaRow
              label="Last processed"
              value={format(
                new Date(document.updated_at),
                "MMM d, yyyy HH:mm"
              )}
            />
            {document.routing_summary ? (
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Summary
                </p>
                <p className="mt-1 text-xs leading-relaxed text-navy">
                  {document.routing_summary}
                </p>
              </div>
            ) : null}
            {document.error_message ? (
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wide text-red-600">
                  Error
                </p>
                <p className="mt-1 text-xs leading-relaxed text-red-600">
                  {document.error_message}
                </p>
              </div>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full rounded-[6px]"
              onClick={() => onEdit(document)}
            >
              Edit metadata
            </Button>
          </aside>

          <div className="flex h-full min-h-0 flex-col p-4">
            <PdfViewer
              fileUrl={blobUrl}
              fileName={document.file_name}
              loading={loadingPdf}
              error={pdfError}
              onDownload={() => {
                if (blob) {
                  triggerBlobDownload(blob, document.file_name);
                  return;
                }
                documentsService
                  .downloadBlob(document.id)
                  .then((b) => triggerBlobDownload(b, document.file_name))
                  .catch((e) => toast.error(getApiErrorMessage(e)));
              }}
              onOpenExternal={() => {
                if (blob) {
                  openBlobInNewTab(blob);
                  return;
                }
                documentsService
                  .downloadBlob(document.id, true)
                  .then((b) => openBlobInNewTab(b))
                  .catch((e) => toast.error(getApiErrorMessage(e)));
              }}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 break-words text-xs text-navy">{value}</p>
    </div>
  );
}

type EditProps = {
  document: KnowledgeDocument | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (input: {
    title?: string;
    routing_summary?: string;
    routing_keywords?: string[];
  }) => Promise<void>;
  saving?: boolean;
};

export function EditDocumentDialog({
  document,
  open,
  onOpenChange,
  onSave,
  saving,
}: EditProps) {
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [keywords, setKeywords] = useState("");

  useEffect(() => {
    if (!document || !open) return;
    setTitle(document.title || "");
    setSummary(document.routing_summary || "");
    setKeywords((document.routing_keywords || []).join(", "));
  }, [document, open]);

  async function handleSave() {
    const kw = keywords
      .split(",")
      .map((k) => k.trim())
      .filter(Boolean);
    await onSave({
      title: title.trim(),
      routing_summary: summary.trim(),
      routing_keywords: kw,
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-[8px] sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit document</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-1">
          <div className="space-y-1.5">
            <Label htmlFor="kb-title">Title</Label>
            <Input
              id="kb-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="rounded-[6px]"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="kb-summary">Routing summary</Label>
            <Textarea
              id="kb-summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              rows={4}
              className="rounded-[6px]"
              placeholder="Short description used for chatbot routing"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="kb-keywords">Keywords</Label>
            <Input
              id="kb-keywords"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              className="rounded-[6px]"
              placeholder="Comma-separated"
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            className="rounded-[6px]"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            className="rounded-[6px]"
            disabled={saving || !title.trim()}
            onClick={() => void handleSave()}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
