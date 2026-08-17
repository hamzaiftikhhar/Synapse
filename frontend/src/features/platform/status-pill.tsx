"use client";

import { Badge } from "@/components/ui/badge";
import { toneFor } from "@/features/platform/format";

export function StatusPill({ value }: { value: string }) {
  const label = value.replaceAll("_", " ");
  return (
    <Badge variant={toneFor(value)} className="capitalize">
      {label}
    </Badge>
  );
}
