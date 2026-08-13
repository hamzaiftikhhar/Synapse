"use client";

import { useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ImportRecordType } from "@/types/api";
import { ImportDialog } from "./import-dialog";
import { RECORD_TYPE_LABEL } from "./utils";

export function ImportTriggerButton({
  recordType,
  variant = "outline",
}: {
  recordType: ImportRecordType;
  variant?: "outline" | "ghost";
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button type="button" variant={variant} onClick={() => setOpen(true)}>
        <Upload className="size-4" />
        Import {RECORD_TYPE_LABEL[recordType].toLowerCase()}
      </Button>
      <ImportDialog recordType={recordType} open={open} onOpenChange={setOpen} />
    </>
  );
}
