"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    setPage(1);
    setNumPages(0);
    setRenderError(null);
    pageRefs.current = [];
  }, [fileUrl]);

  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !numPages) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        const n = Number(visible?.target.getAttribute("data-page"));
        if (n) setPage(n);
      },
      { root, threshold: [0.35, 0.6] }
    );

    pageRefs.current.forEach((el) => {
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [numPages, fileUrl]);

  const file = useMemo(
    () => (fileUrl ? { url: fileUrl } : null),
    [fileUrl]
  );

  function goToPage(next: number) {
    const clamped = Math.min(Math.max(next, 1), numPages || 1);
    setPage(clamped);
    pageRefs.current[clamped - 1]?.scrollIntoView({
      behavior: "auto",
      block: "start",
    });
  }

  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-[6px] border border-border bg-zinc-100",
        className
      )}
    >
      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-border bg-background px-2 py-1.5">
        <div className="mr-auto min-w-0 truncate px-1 text-xs text-muted-foreground">
          {fileName || "Document"}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="rounded-[4px]"
          disabled={page <= 1}
          onClick={() => goToPage(page - 1)}
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
          onClick={() => goToPage(page + 1)}
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

      <div
        ref={scrollRef}
        className="relative min-h-0 flex-1 overflow-auto"
      >
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
              <div className="flex flex-col items-center gap-3">
                {Array.from({ length: numPages }, (_, i) => (
                  <div
                    key={i + 1}
                    data-page={i + 1}
                    ref={(el) => {
                      pageRefs.current[i] = el;
                    }}
                  >
                    <Page
                      pageNumber={i + 1}
                      scale={scale}
                      className="shadow-sm"
                      renderTextLayer
                      renderAnnotationLayer
                    />
                  </div>
                ))}
              </div>
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
