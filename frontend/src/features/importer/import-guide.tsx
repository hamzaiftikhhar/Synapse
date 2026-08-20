"use client";

import { FilePlus, FileSpreadsheet } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ImportRecordType } from "@/types/api";
import { downloadEmptyCsv, downloadSampleCsv, IMPORT_TEMPLATES } from "./templates";

export function ImportGuide({ recordType }: { recordType: ImportRecordType }) {
  const template = IMPORT_TEMPLATES[recordType];

  return (
    <div className="overflow-hidden rounded-xl border border-border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <p className="flex items-center gap-2 text-sm font-medium text-navy">
          <FileSpreadsheet className="size-4 text-muted-foreground" strokeWidth={1.75} />
          Sample file
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => downloadSampleCsv(recordType)}
          >
            <FileSpreadsheet className="size-3.5" />
            Sample with data
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => downloadEmptyCsv(recordType)}
          >
            <FilePlus className="size-3.5" />
            Blank template
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-left text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground">
              {template.columns.map((col) => (
                <th key={col.key} className="px-4 py-2.5 font-medium" title={col.hint}>
                  {col.header}
                  {col.required ? <span className="text-primary"> *</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {template.sampleRows.map((row, i) => (
              <tr key={i} className="border-b border-border last:border-0">
                {row.map((cell, idx) => (
                  <td key={idx} className="px-4 py-2.5 text-foreground">
                    {cell || <span className="text-muted-foreground">—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
