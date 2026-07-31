"use client";

import { format } from "date-fns";
import {
  Download,
  ExternalLink,
  Eye,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { KnowledgeDocument } from "@/types/api";
import { DocumentStatusBadge } from "./document-status-badge";
import { formatBytes, isDocumentActive } from "./utils";

type Props = {
  documents: KnowledgeDocument[];
  onOpen: (doc: KnowledgeDocument) => void;
  onEdit: (doc: KnowledgeDocument) => void;
  onDownload: (doc: KnowledgeDocument) => void;
  onOpenExternal: (doc: KnowledgeDocument) => void;
  onReindex: (doc: KnowledgeDocument) => void;
  onDelete: (doc: KnowledgeDocument) => void;
};

export function DocumentsTable({
  documents,
  onOpen,
  onEdit,
  onDownload,
  onOpenExternal,
  onReindex,
  onDelete,
}: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-4">File name</TableHead>
          <TableHead>Size</TableHead>
          <TableHead>Uploaded</TableHead>
          <TableHead>Uploaded by</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Chunks</TableHead>
          <TableHead>Last processed</TableHead>
          <TableHead className="w-12 pr-4" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.map((doc) => (
          <TableRow
            key={doc.id}
            className="cursor-pointer"
            onClick={() => onOpen(doc)}
          >
            <TableCell className="pl-4">
              <div className="min-w-0 max-w-[16rem]">
                <div className="truncate text-sm font-medium text-navy">
                  {doc.title || doc.file_name}
                </div>
                {doc.title && doc.title !== doc.file_name ? (
                  <div className="truncate text-xs text-muted-foreground">
                    {doc.file_name}
                  </div>
                ) : null}
              </div>
            </TableCell>
            <TableCell className="tabular-nums text-muted-foreground">
              {formatBytes(doc.file_size_bytes)}
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {format(new Date(doc.created_at), "MMM d, yyyy")}
            </TableCell>
            <TableCell className="max-w-[9rem] truncate text-muted-foreground">
              {doc.uploaded_by_name || doc.uploaded_by_email || "—"}
            </TableCell>
            <TableCell>
              <DocumentStatusBadge document={doc} />
            </TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground">
              {doc.chunk_count}
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {isDocumentActive(doc)
                ? "In progress"
                : format(new Date(doc.updated_at), "MMM d, yyyy HH:mm")}
            </TableCell>
            <TableCell className="pr-4" onClick={(e) => e.stopPropagation()}>
              <DropdownMenu>
                <DropdownMenuTrigger className="inline-flex size-7 items-center justify-center rounded-[4px] text-muted-foreground hover:bg-muted hover:text-foreground">
                  <MoreHorizontal className="size-4" />
                  <span className="sr-only">Document actions</span>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-40">
                  <DropdownMenuItem onClick={() => onOpen(doc)}>
                    <Eye className="size-3.5" />
                    View
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onEdit(doc)}>
                    <Pencil className="size-3.5" />
                    Edit metadata
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onDownload(doc)}>
                    <Download className="size-3.5" />
                    Download
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onOpenExternal(doc)}>
                    <ExternalLink className="size-3.5" />
                    Open in new tab
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={isDocumentActive(doc)}
                    onClick={() => onReindex(doc)}
                  >
                    <RefreshCw className="size-3.5" />
                    Reindex
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onClick={() => onDelete(doc)}
                  >
                    <Trash2 className="size-3.5" />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
