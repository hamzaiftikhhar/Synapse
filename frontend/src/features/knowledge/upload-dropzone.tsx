"use client";

import { useCallback, useRef, useState } from "react";
import { FileUp, Upload } from "lucide-react";
import { cn } from "@/lib/utils";
import { isPdfFile } from "./utils";

export type UploadItemState = {
  id: string;
  file: File;
  progress: number;
  status: "queued" | "uploading" | "done" | "error";
  error?: string;
};

type Props = {
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  /** input[accept] — defaults to PDF-only (the knowledge base's original behavior). */
  accept?: string;
  /** Per-file validator — defaults to isPdfFile. */
  validate?: (file: File) => boolean;
  /** Overrides the default PDF copy. */
  title?: string;
  hint?: string;
  rejectionLabel?: string;
};

export function UploadDropzone({
  disabled,
  onFiles,
  accept = "application/pdf,.pdf",
  validate = isPdfFile,
  title,
  hint,
  rejectionLabel = "Only PDF is supported.",
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const acceptFiles = useCallback(
    (list: FileList | File[] | null) => {
      if (!list || disabled) return;
      const files = Array.from(list);
      const valid: File[] = [];
      const rejected: string[] = [];
      for (const file of files) {
        if (validate(file)) valid.push(file);
        else rejected.push(file.name);
      }
      if (rejected.length) {
        setLocalError(
          rejected.length === 1
            ? `"${rejected[0]}" isn't a supported file. ${rejectionLabel}`
            : `${rejected.length} files were skipped — ${rejectionLabel.toLowerCase()}`
        );
      } else {
        setLocalError(null);
      }
      if (valid.length) onFiles(valid);
    },
    [disabled, onFiles, validate, rejectionLabel]
  );

  return (
    <div className="space-y-2">
      <div
        role="button"
        tabIndex={0}
        aria-disabled={disabled}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (!disabled) inputRef.current?.click();
          }
        }}
        onClick={() => !disabled && inputRef.current?.click()}
        onDragEnter={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!disabled) setDragging(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setDragging(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setDragging(false);
          acceptFiles(e.dataTransfer.files);
        }}
        className={cn(
          "group flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-10 text-center",
          dragging
            ? "border-primary/50 bg-primary/[0.03]"
            : "border-border bg-muted/20 hover:border-border hover:bg-muted/35",
          disabled && "pointer-events-none opacity-60"
        )}
      >
        <div className="mb-3 flex size-10 items-center justify-center rounded-xl border border-border bg-background text-muted-foreground">
          {dragging ? (
            <FileUp className="size-4 text-primary" />
          ) : (
            <Upload className="size-4" />
          )}
        </div>
        <p className="text-sm font-medium text-navy">
          {dragging ? "Drop files to upload" : (title ?? "Drag & drop PDFs here")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {hint ?? "or click to browse · PDF only · multiple files supported"}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple
          className="hidden"
          disabled={disabled}
          onChange={(e) => {
            acceptFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {localError ? (
        <p className="text-xs text-red-600" role="alert">
          {localError}
        </p>
      ) : null}
    </div>
  );
}
