"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Read-only by default, editable only after an explicit "Edit" click —
 * the pattern used across the dashboard's profile-style pages (Clinic,
 * Business hours, Account, Settings → Booking/Widget) so a value already
 * saved can't be changed by a stray click, and once editing starts, Save
 * and Cancel are the only way out (see edit-mode-actions.tsx).
 */
export function useEditMode() {
  const [editing, setEditing] = useState(false);

  // A hard browser navigation (refresh, close tab, external link) is the
  // one exit this hook can't intercept with a Cancel click — warn instead
  // of silently discarding a mid-edit change.
  useEffect(() => {
    if (!editing) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [editing]);

  const edit = useCallback(() => setEditing(true), []);

  /** Restores local field state to the last-saved values, then exits edit
   * mode. Pass the setter calls (or a single reset callback) that put
   * every editable field back to what was last loaded/saved. */
  const cancel = useCallback((reset: () => void) => {
    reset();
    setEditing(false);
  }, []);

  /** Call once a save succeeds — fields already match what was just
   * saved, so there's nothing to reset. */
  const done = useCallback(() => setEditing(false), []);

  return { editing, edit, cancel, done };
}
