"use client";

import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { MessageSquare } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState } from "@/components/dashboard/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { hydrateHistoryMessages } from "@/features/chat/message-parser";
import { MessageRenderer } from "@/features/chat/messages";
import { useConversationMessages, useConversations, useAnalyticsOverview } from "@/hooks/api";
import { GlyphStat } from "@/components/dashboard/insights";
import type { ConversationSummary } from "@/types/api";

const PAGE_SIZE = 30;

function ConversationRow({
  conversation,
  active,
  onSelect,
}: {
  conversation: ConversationSummary;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full flex-col gap-0.5 border-b border-border/60 px-4 py-3 text-left transition-colors hover:bg-accent/50",
        active && "bg-accent"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-foreground">
          {conversation.display_name}
        </span>
        <span className="shrink-0 text-[11px] text-muted-foreground">
          {formatDistanceToNow(new Date(conversation.last_active_at), {
            addSuffix: true,
          })}
        </span>
      </div>
      <p className="truncate text-xs text-muted-foreground">
        {conversation.last_message_preview || "No messages yet"}
      </p>
      <div className="mt-1 flex items-center gap-1.5">
        <Badge variant="secondary" className="px-1.5 py-0 text-[10px] capitalize">
          {conversation.status}
        </Badge>
        {conversation.is_authenticated ? (
          <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
            Verified
          </Badge>
        ) : null}
      </div>
    </button>
  );
}

export default function ConversationsPage() {
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [selected, setSelected] = useState<ConversationSummary | null>(null);

  const { data, isLoading } = useConversations({
    search: search || undefined,
    limit,
  });
  const overview = useAnalyticsOverview("30d");
  const inbox = overview.data?.ops.inbox;
  const rows = data?.results ?? [];

  const messagesQuery = useConversationMessages(selected?.id ?? null);
  // Pages arrive newest-first (page 0 = latest, page 1 = the page before
  // it, ...); each page's own messages are already oldest-to-newest — so
  // the full ascending transcript is the pages reversed, each page's
  // internal order left untouched.
  const orderedRows = [...(messagesQuery.data?.pages ?? [])]
    .reverse()
    .flatMap((p) => p.messages);
  const transcript = hydrateHistoryMessages(orderedRows);

  return (
    <div>
      <PageHeader
        title="Conversations"
        description="Patient conversations from your chat widget — read-only."
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <GlyphStat
          label="Total conversations"
          value={(inbox?.total ?? data?.count ?? 0).toLocaleString()}
          glyph="chat"
        />
        <GlyphStat
          label="Active"
          value={(inbox?.active ?? 0).toLocaleString()}
          glyph="pulse"
        />
        <GlyphStat
          label="Closed"
          value={(inbox?.closed ?? 0).toLocaleString()}
          glyph="booking"
        />
        <GlyphStat
          label="Needs attention"
          value={(inbox?.escalated ?? 0).toLocaleString()}
          glyph="people"
        />
      </div>
      <div className="flex h-[calc(100vh-280px)] min-h-[480px] gap-4">
        <div className="flex w-80 shrink-0 flex-col overflow-hidden rounded-2xl border border-border bg-card">
          <div className="border-b border-border p-3">
            <Input
              placeholder="Search by name or email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8"
            />
          </div>
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <p className="p-4 text-sm text-muted-foreground">Loading…</p>
            ) : !rows.length ? (
              <EmptyState
                title="No conversations yet"
                description="Conversations appear here once patients start chatting on your widget."
                icon={MessageSquare}
              />
            ) : (
              rows.map((c) => (
                <ConversationRow
                  key={c.id}
                  conversation={c}
                  active={selected?.id === c.id}
                  onSelect={() => setSelected(c)}
                />
              ))
            )}
            {data && rows.length < data.count ? (
              <button
                type="button"
                className="w-full py-2.5 text-center text-xs font-medium text-primary hover:underline"
                onClick={() => setLimit((n) => n + PAGE_SIZE)}
              >
                Load more
              </button>
            ) : null}
          </div>
        </div>

        <div className="flex flex-1 flex-col overflow-hidden rounded-2xl border border-border bg-card">
          {!selected ? (
            <div className="flex flex-1 items-center justify-center">
              <EmptyState
                title="Select a conversation"
                description="Choose a conversation from the list to read its transcript."
                icon={MessageSquare}
              />
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-foreground">
                    {selected.display_name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {selected.email || "No email on file"}
                  </p>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto px-4 py-4">
                {messagesQuery.isLoading ? (
                  <p className="text-sm text-muted-foreground">Loading…</p>
                ) : (
                  <>
                    {messagesQuery.hasNextPage ? (
                      <div className="mb-3 flex justify-center">
                        <Button
                          type="button"
                          variant="outline"
                          size="xs"
                          disabled={messagesQuery.isFetchingNextPage}
                          onClick={() => void messagesQuery.fetchNextPage()}
                        >
                          {messagesQuery.isFetchingNextPage
                            ? "Loading…"
                            : "Load older messages"}
                        </Button>
                      </div>
                    ) : null}
                    <div className="mx-auto flex max-w-2xl flex-col gap-4">
                      {transcript.map((m) => (
                        <MessageRenderer key={m.id} message={m} />
                      ))}
                    </div>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
