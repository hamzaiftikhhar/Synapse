import type { KnowledgeDocument, ProcessingStage } from "@/types/api";

export const ACCEPTED_PDF = {
  mime: ["application/pdf"],
  extensions: [".pdf"],
};

export const ACCEPTED_KNOWLEDGE_UPLOAD = {
  mime: [
    "application/pdf",
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ],
  extensions: [".pdf", ".csv", ".xlsx"],
  accept: ".pdf,.csv,.xlsx,application/pdf,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

export const PROCESSING_STAGES: {
  id: ProcessingStage;
  label: string;
}[] = [
  { id: "queued", label: "Queued" },
  { id: "uploading", label: "Uploading" },
  { id: "extracting", label: "Extracting text" },
  { id: "chunking", label: "Chunking document" },
  { id: "embedding", label: "Generating embeddings" },
  { id: "storing", label: "Storing knowledge" },
  { id: "completed", label: "Completed" },
];

export function isPdfFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    file.type === "application/pdf" ||
    name.endsWith(".pdf") ||
    ACCEPTED_PDF.mime.includes(file.type)
  );
}

export function isKnowledgeUploadFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    ACCEPTED_KNOWLEDGE_UPLOAD.mime.includes(file.type) ||
    ACCEPTED_KNOWLEDGE_UPLOAD.extensions.some((ext) => name.endsWith(ext))
  );
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`;
  const mb = kb / 1024;
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
}

export function isDocumentActive(doc: KnowledgeDocument): boolean {
  return doc.status === "pending" || doc.status === "processing";
}

export function statusTone(
  status: KnowledgeDocument["status"]
): "queued" | "processing" | "completed" | "failed" | "cancelled" {
  switch (status) {
    case "pending":
      return "queued";
    case "processing":
      return "processing";
    case "chunked":
    case "indexed":
      return "completed";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    default:
      return "queued";
  }
}

export function statusLabel(doc: KnowledgeDocument): string {
  const tone = statusTone(doc.status);
  if (tone === "queued") return "Queued";
  if (tone === "processing") {
    const stage = String(doc.processing_stage || "");
    const found = PROCESSING_STAGES.find((s) => s.id === stage);
    return found?.label ?? "Processing";
  }
  if (tone === "completed") {
    return doc.status === "chunked" ? "Chunked" : "Completed";
  }
  if (tone === "failed") return "Failed";
  return "Cancelled";
}

export function stageIndex(stage: string | undefined): number {
  const idx = PROCESSING_STAGES.findIndex((s) => s.id === stage);
  return idx >= 0 ? idx : 0;
}

export function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  return rem ? `${min}m ${rem}s` : `${min}m`;
}

export function processingDurationMs(
  doc: KnowledgeDocument,
  now = Date.now()
): number | null {
  const start = doc.processing_started_at
    ? Date.parse(doc.processing_started_at)
    : Date.parse(doc.created_at);
  if (Number.isNaN(start)) return null;
  const endRaw = doc.processing_finished_at
    ? Date.parse(doc.processing_finished_at)
    : isDocumentActive(doc)
      ? now
      : Date.parse(doc.updated_at);
  if (Number.isNaN(endRaw)) return null;
  return Math.max(0, endRaw - start);
}

export function triggerBlobDownload(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName || "document.pdf";
  a.click();
  URL.revokeObjectURL(url);
}

export function openBlobInNewTab(blob: Blob) {
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  // Revoke after a delay so the tab can load
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
