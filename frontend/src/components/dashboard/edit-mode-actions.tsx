"use client";

import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Header actions for a view/edit-gated section — pairs with useEditMode.
 * Not editing: a single "Edit" affordance. Editing: Cancel and Save are
 * the only actions shown, so there's nothing else to click until one of
 * them resolves the pending change.
 */
export function EditModeActions({
  editing,
  pending,
  onEdit,
  onSave,
  onCancel,
  saveLabel = "Save",
  savingLabel = "Saving…",
}: {
  editing: boolean;
  pending?: boolean;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
  saveLabel?: string;
  savingLabel?: string;
}) {
  if (!editing) {
    return (
      <Button type="button" variant="outline" onClick={onEdit}>
        <Pencil className="size-3.5" /> Edit
      </Button>
    );
  }
  return (
    <div className="flex gap-2">
      <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
        Cancel
      </Button>
      <Button type="button" onClick={onSave} disabled={pending}>
        {pending ? savingLabel : saveLabel}
      </Button>
    </div>
  );
}
