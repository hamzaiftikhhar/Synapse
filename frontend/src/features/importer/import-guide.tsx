"use client";

import { Download, FileSpreadsheet } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ImportRecordType } from "@/types/api";
import {
  downloadEmptyCsv,
  downloadSampleCsv,
  IMPORT_TEMPLATES,
} from "./templates";

export function ImportGuide({
  recordType,
  compact = false,
}: {
  recordType: ImportRecordType;
  compact?: boolean;
}) {
  const template = IMPORT_TEMPLATES[recordType];
  const previewColumns = compact
    ? template.columns.filter(
        (c) => c.required || (c.key !== "bio" && c.key !== "description")
      )
    : template.columns;
  const previewIndexes = previewColumns.map((col) =>
    template.columns.findIndex((c) => c.key === col.key)
  );

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium text-navy">
            <FileSpreadsheet className="size-4 text-primary" strokeWidth={1.75} />
            Spreadsheet format
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{template.summary}</p>
          {template.notes?.length ? (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[11px] text-muted-foreground">
              {template.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <p className="shrink-0 text-[11px] text-muted-foreground">CSV or XLSX</p>
      </div>

      <div className="flex flex-wrap gap-1.5 px-4 py-3">
        {template.columns.map((col) => (
          <span
            key={col.key}
            className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] text-foreground"
            title={col.hint}
          >
            {col.header}
            {col.required ? (
              <span className="font-medium text-primary">Required</span>
            ) : (
              <span className="text-muted-foreground">Optional</span>
            )}
          </span>
        ))}
      </div>

      <div className="overflow-x-auto border-t border-border">
        <table className="w-full min-w-[420px] text-left text-xs">
          <thead>
            <tr className="bg-muted/60 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {previewColumns.map((col) => (
                <th key={col.key} className="px-4 py-2 font-medium">
                  {col.header}
                  {col.required ? <span className="text-primary"> *</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {template.sampleRows.map((row, i) => (
              <tr key={i} className="border-t border-border">
                {previewIndexes.map((idx) => (
                  <td key={idx} className="px-4 py-2.5 text-foreground">
                    {row[idx] ? (
                      row[idx]
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap gap-2 border-t border-border px-4 py-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => downloadSampleCsv(recordType)}
        >
          <Download className="size-3.5" />
          Sample with 3 rows
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => downloadEmptyCsv(recordType)}
        >
          Empty template
        </Button>
      </div>
    </div>
  );
}
