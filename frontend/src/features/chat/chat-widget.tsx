"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, MoreVertical, Send, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { BookingSheet } from "@/features/booking";
import { StarterChips } from "@/features/chat/components/action-buttons";
import { ChatHeader } from "@/features/chat/components/chat-chrome";
import { RobotAvatar, RobotLauncherIcon } from "@/features/chat/components/robot-avatar";
import { MessageRenderer } from "@/features/chat/messages";
import {
  CONNECTION_ERROR,
  parseChatResponse,
  systemErrorMessage,
  uid,
  userTextMessage,
} from "@/features/chat/message-parser";
import type { BackendAction } from "@/features/chat/types";
import {
  useGuestChat,
  useMarketingChat,
  usePatientChat,
  useStaffChat,
} from "@/hooks/api";
import { useAuth } from "@/providers/auth-provider";
import { useWidget, type AssistantMode } from "@/providers/widget-provider";
import type { BookingStepPayload } from "@/types/api";
import type { ChatMessage } from "@/types/chat";

export type ChatWidgetProps = {
  mode?: "widget" | "embedded";
  clinicName?: string;
  useStaffApi?: boolean;
  assistantMode?: AssistantMode;
  clinicSlug?: string;
  className?: string;
  defaultOpen?: boolean;
};

const CLINIC_STARTERS = [
  {
    id: "book",
    label: "Book Appointment",
    message: "I would like to book an appointment",
    icon: "Calendar",
  },
  {
    id: "doctor",
    label: "Find a Doctor",
    message: "Help me find a doctor",
    icon: "Stethoscope",
  },
  {
    id: "hours",
    label: "Clinic Hours",
    message: "What are your clinic hours?",
    icon: "Clock",
  },
  {
    id: "insurance",
    label: "Check Insurance",
    message: "Do you accept my insurance?",
    icon: "Shield",
  },
];

const MARKETING_STARTERS = [
  {
    id: "features",
    label: "Features",
    message: "What features does Synapse offer?",
    icon: "Search",
  },
  {
    id: "pricing",
    label: "Pricing",
    message: "Tell me about pricing",
    icon: "Calendar",
  },
  {
    id: "demo",
    label: "Book a Demo",
    message: "I want to book a demo",
    icon: "Phone",
  },
];

function runBackendAction(
  action: BackendAction,
  sendText: (text: string) => void,
  launchBooking?: (seed?: string) => void
) {
  const behavior = action.behavior ?? "message";

  if (behavior === "launch_booking") {
    launchBooking?.(action.message || undefined);
    return;
  }

  if (behavior === "open_url") {
    const url = action.url ?? action.href;
    if (url) window.open(url, "_blank", "noopener");
    return;
  }

  if (behavior === "call") {
    if (action.phone) {
      window.location.href = `tel:${action.phone.replace(/\D/g, "")}`;
    }
    return;
  }

  if (action.message) sendText(action.message);
}

export function ChatWidget({
  mode = "widget",
  clinicName,
  useStaffApi = true,
  assistantMode,
  clinicSlug: clinicSlugProp,
  className,
  defaultOpen = false,
}: ChatWidgetProps) {
  const { clinic, isAuthenticated } = useAuth();
  const widgetCtx = useWidget();
  const resolvedMode = assistantMode ?? widgetCtx.mode;
  const clinicSlug = clinicSlugProp ?? widgetCtx.clinicSlug;
  const widgetConfig = widgetCtx.config;

  const displayName =
    clinicName ||
    widgetConfig?.clinic_name ||
    clinic?.name ||
    (resolvedMode === "marketing" ? "Synapse" : "Clinic Assistant");

  const greeting =
    widgetConfig?.configuration?.widget?.greeting ||
    (resolvedMode === "marketing"
      ? "Hi! Ask me about Synapse features, pricing, or book a demo."
      : `Hi! I'm the assistant for ${displayName}. How can I help you today?`);

  const starters =
    resolvedMode === "marketing" ? MARKETING_STARTERS : CLINIC_STARTERS;

  const [open, setOpen] = useState(mode === "embedded" || defaultOpen);
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [typing, setTyping] = useState(false);
  const [showJumpDown, setShowJumpDown] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const staffChat = useStaffChat();
  const patientChat = usePatientChat();
  const guestChat = useGuestChat();
  const marketingChat = useMarketingChat();
  const staffMode =
    resolvedMode === "staff" || (useStaffApi && isAuthenticated);

  const lastActionMessageId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (
        m?.role === "assistant" &&
        m.type === "text" &&
        Array.isArray(m.payload?.actions) &&
        (m.payload.actions as unknown[]).length > 0
      ) {
        return m.id;
      }
    }
    return null;
  }, [messages]);

  const resetChat = useCallback(() => {
    setMessages([]);
    stickToBottom.current = true;
  }, []);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth && !expanded ? "smooth" : "auto",
    });
    stickToBottom.current = true;
    setShowJumpDown(false);
  }, [expanded]);

  useEffect(() => {
    if (stickToBottom.current) scrollToBottom(messages.length > 0);
  }, [messages, typing, scrollToBottom]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = distance < 48;
    setShowJumpDown(
      !stickToBottom.current && el.scrollHeight > el.clientHeight + 80
    );
  }

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || typing) return;
      setInput("");
      stickToBottom.current = true;
      setMessages((prev) => [...prev, userTextMessage(trimmed)]);
      setTyping(true);

      try {
        let res;
        if (staffMode) {
          res = await staffChat.mutateAsync({ message: trimmed });
        } else if (resolvedMode === "marketing") {
          res = await marketingChat.mutateAsync({ message: trimmed });
        } else if (resolvedMode === "clinic" && clinicSlug) {
          res = await guestChat.mutateAsync({
            clinic_slug: clinicSlug,
            message: trimmed,
            session_token: widgetCtx.sessionToken,
          });
          const token = res.meta?.session_token;
          if (typeof token === "string") widgetCtx.setSessionToken(token);
        } else {
          res = await patientChat.mutateAsync({
            message: trimmed,
            session_token: widgetCtx.sessionToken,
          });
        }
        const parsed = parseChatResponse(res);
        setMessages((prev) => [...prev, ...parsed.messages]);
      } catch {
        setMessages((prev) => [...prev, systemErrorMessage(CONNECTION_ERROR)]);
      } finally {
        setTyping(false);
      }
    },
    [
      typing,
      staffMode,
      resolvedMode,
      clinicSlug,
      staffChat,
      patientChat,
      guestChat,
      marketingChat,
      widgetCtx,
    ]
  );

  function handleBackendAction(action: BackendAction) {
    runBackendAction(action, (msg) => void sendText(msg));
  }

  function handleAction(action: string, data?: unknown) {
    if (action === "suggested" || action === "quick_reply") {
      if (typeof data === "string") {
        void sendText(data);
        return;
      }
      const reply = data as { message?: string; label?: string };
      if (reply.message) void sendText(reply.message);
      else if (reply.label) void sendText(reply.label);
      return;
    }

    if (action === "button") {
      const btn = data as BackendAction & { label?: string };
      runBackendAction(
        {
          id: btn.id,
          label: btn.label ?? "",
          behavior: btn.behavior,
          message: btn.message ?? btn.label,
          url: btn.url,
          href: btn.href,
          phone: btn.phone,
        },
        (msg) => void sendText(msg)
      );
      return;
    }

    if (action === "menu") {
      const item = data as { prompt?: string; message?: string };
      const text = item.message ?? item.prompt;
      if (text) void sendText(text);
      return;
    }

    if (action === "select_doctor") {
      const doctor = data as { select_message?: string; message?: string };
      const text = doctor.select_message ?? doctor.message;
      if (text) void sendText(text);
    }
  }

  function closeAll() {
    setOpen(false);
    setExpanded(false);
  }

  const emptyState = (
    <div className="flex flex-col gap-1">
      <div className="flex gap-2">
        <RobotAvatar size="sm" className="mt-0.5 shrink-0" />
        <div className="min-w-0 max-w-[85%]">
          <div className="rounded-2xl rounded-bl-md bg-[#ececf0] px-3.5 py-2.5 text-sm leading-relaxed text-foreground">
            {greeting}
          </div>
          <p className="mt-1 px-1 text-[10px] text-muted-foreground">Just now</p>
        </div>
      </div>
      <StarterChips
        items={starters}
        onSelect={(msg) => void sendText(msg)}
      />
    </div>
  );

  const chatBody = (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-[#f3f3f5] px-3 py-4 sm:px-4"
      >
        <div
          className={cn(
            "mx-auto flex w-full flex-col gap-4",
            expanded ? "max-w-3xl" : "max-w-xl"
          )}
        >
          {messages.length === 0 && !typing ? emptyState : null}
          {messages.map((m) => (
            <MessageRenderer
              key={m.id}
              message={m}
              onAction={handleAction}
              onBackendAction={handleBackendAction}
              showContextActions={m.id === lastActionMessageId && !typing}
            />
          ))}
          {typing ? (
            <MessageRenderer
              message={{
                id: "typing",
                role: "assistant",
                type: "typing",
                createdAt: new Date().toISOString(),
              }}
            />
          ) : null}
        </div>
      </div>

      {showJumpDown ? (
        <button
          type="button"
          onClick={() => scrollToBottom(true)}
          className="absolute bottom-[4.25rem] left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-white px-3 py-1.5 text-[11px] font-medium text-navy shadow-sm"
        >
          <ArrowDown className="size-3" />
          Latest
        </button>
      ) : null}

      <form
        className="flex shrink-0 items-center gap-2 border-t border-border/60 bg-white px-3 py-2.5"
        onSubmit={(e) => {
          e.preventDefault();
          void sendText(input);
        }}
      >
        <div className="relative flex min-w-0 flex-1 items-center">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Enter your question here…"
            className="h-11 flex-1 rounded-full border-neutral-200 bg-white pr-11 shadow-none"
            disabled={typing}
            autoComplete="off"
          />
          <button
            type="submit"
            disabled={typing || !input.trim()}
            aria-label="Send"
            className="absolute right-1.5 flex size-8 items-center justify-center rounded-full text-[#5b8def] transition-opacity disabled:opacity-40"
          >
            <Send className="size-4" />
          </button>
        </div>
        <button
          type="button"
          aria-label="More options"
          className="flex size-9 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-neutral-100"
          onClick={resetChat}
          title="Restart chat"
        >
          <MoreVertical className="size-4" />
        </button>
      </form>
    </div>
  );

  const panel = (
    <div
      className={cn(
        "relative flex flex-col overflow-hidden border border-border/80 bg-white shadow-[0_16px_48px_-16px_rgba(11,14,46,0.35)]",
        mode === "embedded" && "h-full min-h-[420px] w-full rounded-[8px]",
        // Compact default — slightly larger than before
        mode === "widget" &&
          !expanded &&
          "h-[min(700px,calc(100dvh-5.5rem))] w-[min(480px,calc(100vw-1.25rem))] rounded-[8px]",
        // Expanded — ~75–80% of viewport
        mode === "widget" &&
          expanded &&
          "h-[min(80dvh,900px)] w-[min(78vw,1080px)] rounded-[8px]",
        // Mobile sheet
        mode === "widget" &&
          "max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:top-auto max-sm:h-[min(92dvh,820px)] max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:rounded-t-[14px]",
        expanded &&
          mode === "widget" &&
          "max-sm:inset-0 max-sm:h-[100dvh] max-sm:rounded-none",
        className
      )}
    >
      <ChatHeader
        clinicName={displayName}
        expanded={expanded}
        onToggleExpand={() => setExpanded((v) => !v)}
        onRestart={resetChat}
        onClose={closeAll}
        showExpand={mode === "widget"}
      />
      {chatBody}
    </div>
  );

  if (mode === "embedded") return panel;

  return (
    <>
      {open && expanded ? (
        <div
          className="pointer-events-auto fixed inset-0 z-[55] bg-black/20"
          onClick={() => setExpanded(false)}
          aria-hidden
        />
      ) : null}

      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-end p-3 sm:inset-x-auto sm:right-5 sm:bottom-5 sm:p-0">
        {open ? (
          <div
            className={cn(
              "pointer-events-auto mb-3 w-full sm:mb-3",
              expanded &&
                "sm:fixed sm:inset-0 sm:z-[60] sm:m-0 sm:flex sm:items-center sm:justify-center sm:p-5"
            )}
          >
            {panel}
          </div>
        ) : null}

        <button
          type="button"
          onClick={() => (open ? closeAll() : setOpen(true))}
          className="pointer-events-auto flex size-14 items-center justify-center rounded-[10px] shadow-lg ring-2 ring-white"
          aria-label={open ? "Close chat" : "Open Synapse Assistant"}
        >
          {open ? (
            <span className="flex size-full items-center justify-center rounded-[10px] bg-navy text-white">
              <X className="size-5" />
            </span>
          ) : (
            <RobotLauncherIcon />
          )}
        </button>
      </div>
    </>
  );
}
