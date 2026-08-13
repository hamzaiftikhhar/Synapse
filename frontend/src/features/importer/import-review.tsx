"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Check, Pencil, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useApproveAllImportRecords,
  useApproveImportRecord,
  useRejectImportRecord,
  useUpdateImportMapping,
  useUpdateImportRecord,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { ImportJob, ImportRecord, ImportRecordType } from "@/types/api";
import {
  formatFieldValue,
  isDefaultedImportValue,
  targetFieldOptions,
  TARGET_FIELD_LABELS,
} from "./utils";

const UNMAPPED = "__unmapped__";

const STATUS_BADGE: Record<
  ImportRecord["status"],
  { label: string; variant: "success" | "warning" | "destructive" | "info" | "secondary" }
> = {
  ready: { label: "Ready", variant: "success" },
  needs_review: { label: "Needs review", variant: "warning" },
  duplicate: { label: "Duplicate", variant: "warning" },
  approved: { label: "Approved", variant: "success" },
  rejected: { label: "Rejected", variant: "secondary" },
  committed: { label: "Imported", variant: "info" },
};

export function MappingEditor({
  job,
  recordType,
}: {
  job: ImportJob;
  recordType: ImportRecordType;
}) {
  const updateMapping = useUpdateImportMapping();
  const options = targetFieldOptions(recordType);
  const headers = Object.keys(job.column_mapping);
  const unmappedCount = headers.filter((h) => !job.column_mapping[h]?.target).length;

  function setTarget(header: string, target: string) {
    const next: Record<string, string | null> = {};
    for (const h of headers) {
      next[h] =
        h === header
          ? target === UNMAPPED
            ? null
            : target
          : job.column_mapping[h]?.target ?? null;
    }
    updateMapping.mutate(
      { jobId: job.id, input: { mapping: next } },
      { onError: (err) => toast.error(getApiErrorMessage(err)) }
    );
  }

  return (
    <div className="rounded-2xl border border-border">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <p className="text-sm font-medium text-navy">Column mapping</p>
        {unmappedCount > 0 ? (
          <span className="text-xs text-muted-foreground">
            {unmappedCount} unmapped
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">Looks good</span>
        )}
      </div>
      <div className="grid gap-px bg-border sm:grid-cols-2">
        {headers.map((header) => {
          const info = job.column_mapping[header];
          return (
            <div
              key={header}
              className="flex items-center gap-3 bg-card px-4 py-2.5"
            >
              <span
                className="min-w-0 flex-1 truncate text-xs text-muted-foreground"
                title={header}
              >
                {header}
              </span>
              <Select
                value={info?.target ?? UNMAPPED}
                onValueChange={(v) => v && setTarget(header, v)}
              >
                <SelectTrigger className="h-8 w-40 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={UNMAPPED}>Don&apos;t import</SelectItem>
                  {options.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function draftFromRecord(record: ImportRecord, fields: string[]) {
  const next: Record<string, string> = {};
  for (const field of fields) {
    const value = record.canonical_data[field]?.value;
    if (field === "price_cents") {
      next[field] =
        value != null && value !== "" ? (Number(value) / 100).toFixed(2) : "";
    } else if (Array.isArray(value)) {
      next[field] = value.join(", ");
    } else {
      next[field] = value != null ? String(value) : "";
    }
  }
  return next;
}

function payloadFromDraft(draft: Record<string, string>, fields: string[]) {
  const values: Record<string, unknown> = {};
  for (const field of fields) {
    const raw = draft[field] ?? "";
    if (field === "price_cents") {
      const parsed = raw.trim() ? Number(raw) : null;
      values[field] =
        parsed !== null && !Number.isNaN(parsed) ? Math.round(parsed * 100) : null;
    } else if (field === "languages") {
      values[field] = raw
        ? raw.split(",").map((s) => s.trim()).filter(Boolean)
        : [];
    } else if (field === "duration_min") {
      const parsed = raw.trim() ? Number(raw) : null;
      values[field] =
        parsed !== null && !Number.isNaN(parsed) ? Math.round(parsed) : null;
    } else {
      values[field] = raw;
    }
  }
  return values;
}

function RecordTableRow({
  jobId,
  record,
  fields,
  labels,
}: {
  jobId: string;
  record: ImportRecord;
  fields: string[];
  labels: Record<string, string>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const approve = useApproveImportRecord();
  const reject = useRejectImportRecord();
  const updateRecord = useUpdateImportRecord();
  const badge = STATUS_BADGE[record.status];
  const isTerminal =
    record.status === "approved" ||
    record.status === "rejected" ||
    record.status === "committed";

  function startEdit() {
    setDraft(draftFromRecord(record, fields));
    setEditing(true);
  }

  async function saveEdit() {
    try {
      await updateRecord.mutateAsync({
        jobId,
        recordId: record.id,
        input: { values: payloadFromDraft(draft, fields) },
      });
      setEditing(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function onApprove() {
    try {
      await approve.mutateAsync({ jobId, recordId: record.id });
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function onReject() {
    try {
      await reject.mutateAsync({ jobId, recordId: record.id });
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  const issue =
    record.validation_errors[0]?.message ||
    (record.duplicate_match
      ? `Possible duplicate of “${record.duplicate_match.label}”`
      : null);

  return (
    <TableRow className="hover:bg-transparent">
      <TableCell className="text-muted-foreground tabular-nums">
        {record.row_number}
      </TableCell>
      {fields.map((field) => (
        <TableCell key={field} className="max-w-[180px]">
          {editing ? (
            <Input
              value={draft[field] ?? ""}
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, [field]: e.target.value }))
              }
              aria-label={labels[field]}
              className="h-8 min-w-[8rem]"
            />
          ) : (
            <span
              className="block truncate text-navy"
              title={
                isDefaultedImportValue(record.canonical_data[field]?.reason)
                  ? record.canonical_data[field]?.reason
                  : formatFieldValue(record.canonical_data[field]?.value, field)
              }
            >
              {formatFieldValue(record.canonical_data[field]?.value, field)}
              {isDefaultedImportValue(record.canonical_data[field]?.reason) ? (
                <span className="ml-1 text-[11px] font-normal text-muted-foreground">
                  default
                </span>
              ) : null}
            </span>
          )}
        </TableCell>
      ))}
      <TableCell>
        <div className="flex flex-col gap-1">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          {issue && !editing ? (
            <span className="flex max-w-[12rem] items-start gap-1 text-[11px] leading-snug text-muted-foreground">
              <AlertTriangle className="mt-0.5 size-3 shrink-0 text-warning" />
              <span className="line-clamp-2">{issue}</span>
            </span>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="text-right">
        {editing ? (
          <div className="flex justify-end gap-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void saveEdit()}
              disabled={updateRecord.isPending}
            >
              Save
            </Button>
          </div>
        ) : isTerminal ? null : (
          <div className="flex justify-end gap-0.5">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={startEdit}
              aria-label="Edit row"
            >
              <Pencil className="size-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => void onApprove()}
              disabled={approve.isPending || record.validation_errors.length > 0}
              aria-label="Approve row"
            >
              <Check className="size-3.5 text-success" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => void onReject()}
              disabled={reject.isPending}
              aria-label="Reject row"
            >
              <X className="size-3.5 text-destructive" />
            </Button>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

export function RecordsTable({
  jobId,
  records,
  recordType,
}: {
  jobId: string;
  records: ImportRecord[];
  recordType: ImportRecordType;
}) {
  const approveAll = useApproveAllImportRecords();
  const labels = TARGET_FIELD_LABELS[recordType];
  const fields = Object.keys(labels);

  const summary = useMemo(() => {
    const pending = records.filter(
      (r) => r.status !== "approved" && r.status !== "rejected" && r.status !== "committed"
    );
    const approvable = pending.filter((r) => r.validation_errors.length === 0);
    const blocked = pending.length - approvable.length;
    const approved = records.filter((r) => r.status === "approved").length;
    return { pending: pending.length, approvable: approvable.length, blocked, approved };
  }, [records]);

  async function onApproveAll() {
    try {
      const result = await approveAll.mutateAsync(jobId);
      if (result.skipped_count > 0) {
        toast.success(
          `Approved ${result.approved_count}. ${result.skipped_count} still need edits.`
        );
      } else {
        toast.success(`Approved ${result.approved_count}`);
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <p className="text-sm text-foreground">
          <span className="font-medium text-navy">{records.length}</span>
          <span className="text-muted-foreground">
            {" "}
            row{records.length === 1 ? "" : "s"}
            {summary.approved ? ` · ${summary.approved} approved` : ""}
            {summary.blocked ? ` · ${summary.blocked} need edits` : ""}
          </span>
        </p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void onApproveAll()}
          disabled={approveAll.isPending || summary.approvable === 0}
        >
          {approveAll.isPending
            ? "Approving…"
            : `Approve all${summary.approvable ? ` (${summary.approvable})` : ""}`}
        </Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-12">#</TableHead>
            {fields.map((field) => (
              <TableHead key={field}>{labels[field]}</TableHead>
            ))}
            <TableHead>Status</TableHead>
            <TableHead className="w-28 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {records.map((record) => (
            <RecordTableRow
              key={record.id}
              jobId={jobId}
              record={record}
              fields={fields}
              labels={labels}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
