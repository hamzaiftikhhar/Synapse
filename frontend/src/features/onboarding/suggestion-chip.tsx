"use client";

import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export function SuggestionChip({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={disabled}
      onClick={onClick}
      className="rounded-full"
    >
      <Plus className="size-3.5" />
      {label}
    </Button>
  );
}
