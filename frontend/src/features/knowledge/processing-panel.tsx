"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { KnowledgeDocument } from "@/types/api";
import {
  formatDurationMs,
  isDocumentActive,
  PROCESSING_STAGES,
  processingDurationMs,
} from "./utils";
import type { UploadItemState } from "./upload-dropzone";

type Props = {
  uploads: UploadItemState[];
  documents: KnowledgeDocument[];
  onCancel?: (id: string) => void;
  cancellingId?: string | null;
};

export function ProcessingPanel({
  uploads,
  documents,
  onCancel,
  cancellingId,
}: Props) {
  const activeDocs = documents.filter(isDocumentActive);
  const activeUploads = uploads.filter(
    (u) => u.status === "queued" || u.status === "uploading" || u.status === "error"
  );

  if (!activeUploads.length && !activeDocs.length) return null;

  return (
    <div className="mb-6 space-y-3">
      {activeUploads.map((item) => (
        <UploadProgressCard key={item.id} item={item} />
      ))}
      {activeDocs.map((doc) => (
        <DocumentProcessingCard
          key={doc.id}
          document={doc}
          onCancel={onCancel}
          cancelling={cancellingId === doc.id}
        />
      ))}
    </div>
  );
}

function UploadProgressCard({ item }: { item: UploadItemState }) {
  return (
    <div className="rounded-[6px] border border-border bg-background px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-navy">
            {item.file.name}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {item.status === "error"
              ? item.error || "Upload failed"
              : item.status === "uploading"
                ? `Uploading… ${item.progress}%`
                : "Waiting to upload…"}
          </p>
        </div>
        {item.status === "uploading" || item.status === "queued" ? (
          <Loader2 className="size-4 shrink-0 animate-spin text-sky-600" />
        ) : null}
      </div>
      {item.status !== "error" ? (
        <div className="mt-3 h-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-sky-500 transition-[width] duration-200 ease-out"
            style={{ width: `${item.progress}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}

function DocumentProcessingCard({
  document,
  onCancel,
  cancelling,
}: {
  document: KnowledgeDocument;
  onCancel?: (id: string) => void;
  cancelling?: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const stages = PROCESSING_STAGES.filter((s) => s.id !== "uploading");
  const current = Math.max(
    0,
    stages.findIndex((s) => s.id === String(document.processing_stage))
  );
  const duration = processingDurationMs(document, now);

  return (
    <div className="rounded-[6px] border border-border bg-background px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-navy">
            {document.title || document.file_name}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Processing
            {duration != null ? ` · ${formatDurationMs(duration)}` : null}
          </p>
        </div>
        {onCancel ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 shrink-0 rounded-[4px] px-2 text-xs text-muted-foreground"
            disabled={cancelling}
            onClick={() => onCancel(document.id)}
          >
            <X className="size-3.5" />
            {cancelling ? "Cancelling…" : "Cancel"}
          </Button>
        ) : null}
      </div>

      <ol className="mt-4 space-y-2">
        {stages.map((stage, idx) => {
          const done =
            document.processing_stage === "completed" || idx < current;
          const active =
            String(document.processing_stage) === stage.id ||
            (document.status === "pending" && stage.id === "queued" && idx === 0);
          return (
            <li key={stage.id} className="flex items-center gap-2.5 text-xs">
              <span
                className={
                  done
                    ? "flex size-4 items-center justify-center rounded-full bg-emerald-500 text-white"
                    : active
                      ? "flex size-4 items-center justify-center"
                      : "flex size-4 items-center justify-center rounded-full border border-border"
                }
              >
                {done ? (
                  <Check className="size-2.5" strokeWidth={3} />
                ) : active ? (
                  <Loader2 className="size-3.5 animate-spin text-sky-600" />
                ) : null}
              </span>
              <span
                className={
                  done || active
                    ? "font-medium text-navy"
                    : "text-muted-foreground"
                }
              >
                {stage.label}
              </span>
            </li>
          );
        })}
      </ol>

      {document.error_message ? (
        <p className="mt-3 text-xs text-red-600" role="alert">
          {document.error_message}
        </p>
      ) : null}
    </div>
  );
}
