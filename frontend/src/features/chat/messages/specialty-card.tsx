"use client";

import { useState } from "react";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import type { ChatActionHandler, SpecialtyCardData } from "@/types/chat";

/**
 * Specialty suggestion cards. Unlike the old generic CardsMessage
 * treatment, selecting one dispatches a structured "select_specialty"
 * action carrying the specialty_id — never a synthesized "I need a {name}
 * doctor" chat message. The frontend already knows exactly which
 * specialty was picked, so there is nothing for NLU/LLM to resolve; see
 * chat-widget.tsx's handling of this action.
 */
export function SpecialtyCard({
  specialty,
  onAction,
}: {
  specialty: SpecialtyCardData;
  onAction?: ChatActionHandler;
}) {
  return (
    <button
      type="button"
      onClick={() => onAction?.("select_specialty", specialty)}
      className="w-full rounded-[18px] border border-border/80 bg-card p-3 text-left shadow-[0_2px_12px_rgb(11_14_46/0.06)] transition-colors hover:bg-accent/40"
    >
      <p className="text-sm font-semibold text-navy">{specialty.name}</p>
      {specialty.description ? (
        <p className="mt-0.5 text-xs text-muted-foreground">{specialty.description}</p>
      ) : null}
    </button>
  );
}

export function SpecialtyCards({
  specialties,
  onAction,
  messageId,
}: {
  specialties: SpecialtyCardData[];
  onAction?: ChatActionHandler;
  messageId?: string;
}) {
  // Same collapse-on-supersede convention as DoctorCards/ServiceCards —
  // once a specialty is picked, the search result that replaces this
  // card becomes the one live thing in the transcript.
  const [picked, setPicked] = useState(false);

  if (picked) return null;

  return (
    <ChatInlineCard className="grid gap-2">
      {specialties.map((s, i) => (
        <SpecialtyCard
          key={s.id || i}
          specialty={s}
          onAction={(action, data) => {
            if (action === "select_specialty") {
              setPicked(true);
              onAction?.(action, { ...(data as object), messageId });
              return;
            }
            onAction?.(action, data);
          }}
        />
      ))}
    </ChatInlineCard>
  );
}
