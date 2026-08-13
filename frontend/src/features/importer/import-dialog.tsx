"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { UploadDropzone } from "@/features/knowledge/upload-dropzone";
import {
  useCommitImportJob,
  useCreateImportJob,
  useImportJob,
  useImportJobRecords,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { ImportRecordType } from "@/types/api";
import { ImportGuide } from "./import-guide";
import { MappingEditor, RecordsTable } from "./import-review";
import { isSpreadsheetFile, RECORD_TYPE_LABEL, SPREADSHEET_ACCEPT } from "./utils";

export function ImportDialog({
  recordType,
  open,
  onOpenChange,
}: {
  recordType: ImportRecordType;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const createJob = useCreateImportJob();
  const commit = useCommitImportJob();
  const { data: job } = useImportJob(jobId);
  // Records are created by the background pipeline alongside the
  // uploaded->mapped transition — only fetch them once that's done, and
  // gate on job.status (not just jobId) so they load as soon as
  // processing finishes instead of being stuck on the pre-processing
  // empty result forever (useImportJob polls the job, not this query).
  const isProcessing = !job || job.status === "uploaded" || job.status === "parsing";
  const { data: recordsPage } = useImportJobRecords(isProcessing ? null : jobId);

  useEffect(() => {
    if (!open) {
      setJobId(null);
      setUploading(false);
    }
  }, [open]);

  async function onFiles(files: File[]) {
    const file = files[0];
    if (!file) return;
    setUploading(true);
    try {
      const created = await createJob.mutateAsync({ recordType, file });
      setJobId(created.id);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setUploading(false);
    }
  }

  async function onCommit() {
    if (!jobId) return;
    try {
      const result = await commit.mutateAsync({ jobId, recordType });
      toast.success(
        `Imported ${result.created_count} ${RECORD_TYPE_LABEL[recordType].toLowerCase()}`
      );
      onOpenChange(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  const records = recordsPage?.results ?? [];
  const outstanding = records.filter(
    (r) => r.status !== "approved" && r.status !== "rejected" && r.status !== "committed"
  ).length;
  const approvedCount = records.filter((r) => r.status === "approved").length;

  const phase: "upload" | "processing" | "review" | "failed" = !job
    ? "upload"
    : job.status === "failed"
      ? "failed"
      : job.status === "uploaded" || job.status === "parsing"
        ? "processing"
        : "review";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden duration-0 data-open:animate-none data-closed:animate-none sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>Import {RECORD_TYPE_LABEL[recordType].toLowerCase()}</DialogTitle>
          <DialogDescription>
            Use the sample below, or upload your own CSV / Excel. Nothing is added until you
            confirm.
          </DialogDescription>
        </DialogHeader>

        {phase === "upload" ? (
          <div className="space-y-4">
            <ImportGuide recordType={recordType} />
            <UploadDropzone
              disabled={uploading}
              onFiles={onFiles}
              accept={SPREADSHEET_ACCEPT}
              validate={isSpreadsheetFile}
              title="Drop your spreadsheet here"
              hint="or click to browse · CSV or XLSX"
              rejectionLabel="Only CSV and XLSX files are supported."
            />
          </div>
        ) : null}

        {phase === "processing" || uploading ? (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <Loader2 className="size-6 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">
              Reading your file and mapping columns…
            </p>
          </div>
        ) : null}

        {phase === "failed" && job ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-destructive/40 bg-destructive/5 px-6 py-10 text-center">
            <AlertTriangle className="size-6 text-destructive" />
            <p className="text-sm font-medium text-navy">We couldn&apos;t import this file</p>
            <p className="max-w-sm text-sm text-muted-foreground">{job.error_message}</p>
            <Button type="button" variant="outline" size="sm" onClick={() => setJobId(null)}>
              Try a different file
            </Button>
          </div>
        ) : null}

        {phase === "review" && job ? (
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain">
            {job.metadata.mapping_source === "heuristic_fallback" ? (
              <p className="rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
                We couldn&apos;t map some columns automatically — check the mapping before
                importing.
              </p>
            ) : null}
            <MappingEditor job={job} recordType={recordType} />
            <RecordsTable
              jobId={job.id}
              records={records}
              recordType={recordType}
            />
          </div>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {phase === "review" ? (
            <Button
              type="button"
              onClick={onCommit}
              disabled={commit.isPending || outstanding > 0 || approvedCount === 0}
            >
              {commit.isPending
                ? "Importing…"
                : outstanding > 0
                  ? `${outstanding} still need approval`
                  : `Import ${approvedCount} approved`}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
