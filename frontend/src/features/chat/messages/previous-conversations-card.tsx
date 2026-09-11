"use client";

import { useState } from "react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import { hydrateHistoryMessages } from "@/features/chat/message-parser";
import { widgetService } from "@/services";
import type { ChatConversationSummary } from "@/types/api";
import type { ChatMessage } from "@/types/chat";
import { MessageRenderer } from "./message-renderer";

function formatConversationDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : format(d, "EEE d MMM");
}

/** One other verified conversation, expandable in place to a read-only
 * transcript. Never merges into the live thread — `authSessionToken`
 * (the *current*, already-verified session) is only ever used as proof of
 * identity to read this *other* session's messages, per the backend's
 * `_owns_via_verified_patient` check. */
function PreviousConversationRow({
  conversation,
  clinicSlug,
  currentSessionToken,
}: {
  conversation: ChatConversationSummary;
  clinicSlug: string;
  currentSessionToken: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [transcript, setTranscript] = useState<ChatMessage[] | null>(null);

  async function handleToggle() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (transcript || loading) return;
    setLoading(true);
    setError(false);
    try {
      const page = await widgetService.getMessages(
        conversation.session_token,
        clinicSlug,
        { authSessionToken: currentSessionToken }
      );
      setTranscript(hydrateHistoryMessages(page.messages));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">
            Conversation from {formatConversationDate(conversation.last_active_at)}
          </p>
          {conversation.preview ? (
            <p className="truncate text-xs text-muted-foreground">
              {conversation.preview}
            </p>
          ) : null}
        </div>
        <Button
          type="button"
          size="xs"
          variant="outline"
          className="shrink-0"
          onClick={() => void handleToggle()}
        >
          {expanded ? "Hide" : "View"}
        </Button>
      </div>
      {expanded ? (
        <div className="mt-2.5 max-h-64 space-y-2 overflow-y-auto border-t border-border pt-2.5">
          {loading ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : error ? (
            <p className="text-xs text-destructive">
              Couldn&apos;t load this conversation.
            </p>
          ) : (
            (transcript ?? []).map((m) => <MessageRenderer key={m.id} message={m} />)
          )}
        </div>
      ) : null}
    </div>
  );
}

export function PreviousConversationsCard({
  conversations,
  clinicSlug,
  currentSessionToken,
  onDismiss,
}: {
  conversations: ChatConversationSummary[];
  clinicSlug: string;
  currentSessionToken: string;
  onDismiss?: () => void;
}) {
  if (conversations.length === 0) return null;
  return (
    <ChatInlineCard className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-muted-foreground">
          {conversations.length === 1
            ? "You have a previous conversation"
            : `You have ${conversations.length} previous conversations`}
        </p>
        {onDismiss ? (
          <button
            type="button"
            onClick={onDismiss}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Dismiss
          </button>
        ) : null}
      </div>
      {conversations.map((c) => (
        <PreviousConversationRow
          key={c.session_token}
          conversation={c}
          clinicSlug={clinicSlug}
          currentSessionToken={currentSessionToken}
        />
      ))}
    </ChatInlineCard>
  );
}
