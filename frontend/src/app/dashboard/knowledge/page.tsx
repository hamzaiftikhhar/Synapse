"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import {
  ACCEPTED_KNOWLEDGE_UPLOAD,
  DocumentDetailDialog,
  DocumentsTable,
  EditDocumentDialog,
  ProcessingPanel,
  UploadDropzone,
  type UploadItemState,
  isKnowledgeUploadFile,
  openBlobInNewTab,
  triggerBlobDownload,
} from "@/features/knowledge";
import {
  useCancelDocument,
  useDeleteDocument,
  useDocuments,
  useReindexDocument,
  useUpdateDocument,
  useUploadDocument,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { documentsService } from "@/services";
import type { KnowledgeDocument } from "@/types/api";

export default function KnowledgePage() {
  const { data, isLoading } = useDocuments();
  const upload = useUploadDocument();
  const update = useUpdateDocument();
  const remove = useDeleteDocument();
  const cancel = useCancelDocument();
  const reindex = useReindexDocument();

  const [uploads, setUploads] = useState<UploadItemState[]>([]);
  const [selected, setSelected] = useState<KnowledgeDocument | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [editDoc, setEditDoc] = useState<KnowledgeDocument | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const rows = data ?? [];

  const syncSelected = useCallback(
    (doc: KnowledgeDocument | null) => {
      if (!doc) return;
      const fresh = rows.find((r) => r.id === doc.id) ?? doc;
      setSelected(fresh);
    },
    [rows]
  );

  // Keep detail dialog document fresh while polling
  const detailDoc =
    (selected && rows.find((r) => r.id === selected.id)) || selected;

  const updateUpload = useCallback(
    (id: string, patch: Partial<UploadItemState>) => {
      setUploads((prev) =>
        prev.map((u) => (u.id === id ? { ...u, ...patch } : u))
      );
    },
    []
  );

  const runUploads = useCallback(
    async (files: File[]) => {
      const items: UploadItemState[] = files.map((file) => ({
        id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
        file,
        progress: 0,
        status: "queued",
      }));
      setUploads((prev) => [...items, ...prev]);

      for (const item of items) {
        updateUpload(item.id, { status: "uploading", progress: 0 });
        try {
          await upload.mutateAsync({
            file: item.file,
            title: item.file.name.replace(/\.pdf$/i, ""),
            onProgress: (percent) =>
              updateUpload(item.id, { progress: percent }),
          });
          updateUpload(item.id, { status: "done", progress: 100 });
          toast.success(`Uploaded ${item.file.name}`);
          window.setTimeout(() => {
            setUploads((prev) => prev.filter((u) => u.id !== item.id));
          }, 800);
        } catch (e) {
          updateUpload(item.id, {
            status: "error",
            error: getApiErrorMessage(e),
          });
          toast.error(getApiErrorMessage(e));
        }
      }
    },
    [upload, updateUpload]
  );

  async function handleDownload(doc: KnowledgeDocument) {
    try {
      const blob = await documentsService.downloadBlob(doc.id);
      triggerBlobDownload(blob, doc.file_name);
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  async function handleOpenExternal(doc: KnowledgeDocument) {
    try {
      const blob = await documentsService.downloadBlob(doc.id, true);
      openBlobInNewTab(blob);
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  async function handleDelete(doc: KnowledgeDocument) {
    if (
      !confirm(
        `Delete “${doc.title || doc.file_name}”? This removes it from the knowledge base.`
      )
    ) {
      return;
    }
    try {
      await remove.mutateAsync(doc.id);
      toast.success("Document deleted");
      if (selected?.id === doc.id) {
        setDetailOpen(false);
        setSelected(null);
      }
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  async function handleReindex(doc: KnowledgeDocument) {
    try {
      await reindex.mutateAsync(doc.id);
      toast.success("Reindex started");
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  async function handleCancel(id: string) {
    try {
      await cancel.mutateAsync(id);
      toast.success("Processing cancelled");
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  function openDetail(doc: KnowledgeDocument) {
    setSelected(doc);
    setDetailOpen(true);
  }

  function openEdit(doc: KnowledgeDocument) {
    setEditDoc(doc);
    setEditOpen(true);
  }

  return (
    <div>
      <PageHeader
        title="Knowledge Base"
        description="Upload clinic documents for RAG answers in the patient chatbot."
      />

      <div className="mb-6">
        <UploadDropzone
          onFiles={(files) => void runUploads(files)}
          accept={ACCEPTED_KNOWLEDGE_UPLOAD.accept}
          validate={isKnowledgeUploadFile}
          title="Drag & drop documents here"
          hint="or click to browse · PDF, CSV, XLSX · multiple files supported"
          rejectionLabel="Supported formats: PDF, CSV, XLSX."
        />
      </div>

      <ProcessingPanel
        uploads={uploads}
        documents={rows}
        onCancel={(id) => void handleCancel(id)}
        cancellingId={cancel.isPending ? cancel.variables ?? null : null}
      />

      <DataTableShell title="Documents">
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">Loading…</p>
        ) : !rows.length ? (
          <EmptyState
            title="No documents yet"
            description="Drop a PDF above to start building your clinic knowledge base."
          />
        ) : (
          <DocumentsTable
            documents={rows}
            onOpen={openDetail}
            onEdit={openEdit}
            onDownload={(doc) => void handleDownload(doc)}
            onOpenExternal={(doc) => void handleOpenExternal(doc)}
            onReindex={(doc) => void handleReindex(doc)}
            onDelete={(doc) => void handleDelete(doc)}
          />
        )}
      </DataTableShell>

      <DocumentDetailDialog
        document={detailDoc}
        open={detailOpen}
        onOpenChange={setDetailOpen}
        onEdit={(doc) => {
          openEdit(doc);
        }}
      />

      <EditDocumentDialog
        document={editDoc}
        open={editOpen}
        onOpenChange={setEditOpen}
        saving={update.isPending}
        onSave={async (input) => {
          if (!editDoc) return;
          try {
            const updated = await update.mutateAsync({
              id: editDoc.id,
              input,
            });
            toast.success("Document updated");
            setEditOpen(false);
            syncSelected(updated);
            setEditDoc(updated);
          } catch (e) {
            toast.error(getApiErrorMessage(e));
          }
        }}
      />
    </div>
  );
}
