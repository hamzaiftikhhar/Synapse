"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Loader2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Document, Page, pdfjs } from "react-pdf";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

type Props = {
  fileUrl: string | null;
  fileName?: string;
  loading?: boolean;
  error?: string | null;
  onDownload?: () => void;
  onOpenExternal?: () => void;
  className?: string;
};

export function PdfViewer({
  fileUrl,
  fileName,
  loading,
  error,
  onDownload,
  onOpenExternal,
  className,
}: Props) {
  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  const [scale, setScale] = useState(1.1);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    setPage(1);
    setNumPages(0);
    setRenderError(null);
  }, [fileUrl]);

  const file = useMemo(
    () => (fileUrl ? { url: fileUrl } : null),
    [fileUrl]
  );

  return (
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col overflow-hidden rounded-[6px] border border-border bg-zinc-50",
        className
      )}
    >
      <div className="flex flex-wrap items-center gap-1 border-b border-border bg-background px-2 py-1.5">
        <div className="mr-auto min-w-0 truncate px-1 text-xs text-muted-foreground">
          {fileName || "Document"}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="rounded-[4px]"
          disabled={page <= 1}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          aria-label="Previous page"
        >
          <ChevronLeft className="size-4" />
        </Button>
        <span className="min-w-[4.5rem] text-center text-xs tabular-nums text-muted-foreground">
          {numPages ? `${page} / ${numPages}` : "—"}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="rounded-[4px]"
          disabled={!numPages || page >= numPages}
          onClick={() => setPage((p) => Math.min(numPages, p + 1))}
          aria-label="Next page"
        >
          <ChevronRight className="size-4" />
        </Button>
        <div className="mx-1 h-4 w-px bg-border" />
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="rounded-[4px]"
          onClick={() => setScale((s) => Math.max(0.6, Number((s - 0.1).toFixed(2))))}
          aria-label="Zoom out"
        >
          <ZoomOut className="size-4" />
        </Button>
        <span className="min-w-[3rem] text-center text-xs tabular-nums text-muted-foreground">
          {Math.round(scale * 100)}%
        </span>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="rounded-[4px]"
          onClick={() => setScale((s) => Math.min(2.5, Number((s + 0.1).toFixed(2))))}
          aria-label="Zoom in"
        >
          <ZoomIn className="size-4" />
        </Button>
        {onDownload ? (
          <>
            <div className="mx-1 h-4 w-px bg-border" />
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="rounded-[4px]"
              onClick={onDownload}
              aria-label="Download"
            >
              <Download className="size-4" />
            </Button>
          </>
        ) : null}
        {onOpenExternal ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="rounded-[4px]"
            onClick={onOpenExternal}
            aria-label="Open in new tab"
          >
            <ExternalLink className="size-4" />
          </Button>
        ) : null}
      </div>

      <div className="relative min-h-[28rem] flex-1 overflow-auto">
        {loading ? (
          <div className="flex h-full min-h-[28rem] items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading PDF…
          </div>
        ) : error || renderError ? (
          <div className="flex h-full min-h-[28rem] items-center justify-center px-6 text-center text-sm text-red-600">
            {error || renderError}
          </div>
        ) : file ? (
          <div className="flex justify-center p-4">
            <Document
              file={file}
              loading={
                <div className="flex items-center gap-2 py-24 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Rendering…
                </div>
              }
              onLoadSuccess={({ numPages: n }) => setNumPages(n)}
              onLoadError={(err) =>
                setRenderError(err.message || "Failed to render PDF")
              }
            >
              <Page
                pageNumber={page}
                scale={scale}
                className="shadow-sm"
                renderTextLayer
                renderAnnotationLayer
              />
            </Document>
          </div>
        ) : (
          <div className="flex h-full min-h-[28rem] items-center justify-center text-sm text-muted-foreground">
            No preview available
          </div>
        )}
      </div>
    </div>
  );
}
