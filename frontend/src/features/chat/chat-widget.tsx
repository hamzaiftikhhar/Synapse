"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, Send, X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { BackendActionBar } from "@/features/chat/components/action-buttons";
import { ChatHeader } from "@/features/chat/components/chat-chrome";
import { RobotLauncherIcon } from "@/features/chat/components/robot-avatar";
import { MessageRenderer } from "@/features/chat/messages";
import {
  CONNECTION_ERROR,
  parseChatResponse,
  systemErrorMessage,
  userTextMessage,
} from "@/features/chat/message-parser";
import type { BackendAction } from "@/features/chat/types";
import { usePatientChat, useStaffChat } from "@/hooks/api";
import { useAuth } from "@/providers/auth-provider";
import type { ChatMessage } from "@/types/chat";

export type ChatWidgetProps = {
  mode?: "widget" | "embedded";
  clinicName?: string;
  useStaffApi?: boolean;
  className?: string;
  defaultOpen?: boolean;
};

function runBackendAction(
  action: BackendAction,
  sendText: (text: string) => void
) {
  const behavior = action.behavior ?? "message";

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
  className,
  defaultOpen = false,
}: ChatWidgetProps) {
  const { clinic, isAuthenticated } = useAuth();
  const displayName = clinicName || clinic?.name;

  const [open, setOpen] = useState(mode === "embedded" || defaultOpen);
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [persistentActions, setPersistentActions] = useState<BackendAction[]>(
    []
  );
  const [typing, setTyping] = useState(false);
  const [showJumpDown, setShowJumpDown] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const staffChat = useStaffChat();
  const patientChat = usePatientChat();
  const staffMode = useStaffApi && isAuthenticated;

  const resetChat = useCallback(() => {
    setMessages([]);
    setPersistentActions([]);
    stickToBottom.current = true;
  }, []);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    stickToBottom.current = true;
    setShowJumpDown(false);
  }, []);

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
        const res = staffMode
          ? await staffChat.mutateAsync({ message: trimmed })
          : await patientChat.mutateAsync({ message: trimmed });
        const parsed = parseChatResponse(res);
        setMessages((prev) => [...prev, ...parsed.messages]);
        setPersistentActions(parsed.persistentActions);
      } catch {
        setMessages((prev) => [...prev, systemErrorMessage(CONNECTION_ERROR)]);
        setPersistentActions([]);
      } finally {
        setTyping(false);
      }
    },
    [typing, staffMode, staffChat, patientChat]
  );

  function handleBackendAction(action: BackendAction) {
    runBackendAction(action, (msg) => void sendText(msg));
  }

  function handleAction(action: string, data?: unknown) {
    if (action === "quick_reply") {
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

  const chatBody = (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-[#f8f8fc] px-3 py-4 sm:px-4"
      >
        <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
          {messages.length === 0 && !typing ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Type a message to get started.
            </p>
          ) : null}
          {messages.map((m) => (
            <MessageRenderer
              key={m.id}
              message={m}
              onAction={handleAction}
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

      <AnimatePresence>
        {showJumpDown ? (
          <motion.button
            type="button"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
            onClick={() => scrollToBottom(true)}
            className="absolute bottom-[4.5rem] left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-white px-3 py-1.5 text-[11px] font-medium text-navy shadow-md"
          >
            <ArrowDown className="size-3" />
            Latest
          </motion.button>
        ) : null}
      </AnimatePresence>

      <form
        className="flex shrink-0 items-center gap-2 border-t border-border bg-white px-3 py-2.5"
        onSubmit={(e) => {
          e.preventDefault();
          void sendText(input);
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Enter your question here…"
          className="h-10 flex-1 rounded-full border-border bg-[#f8f8fc] px-4"
          disabled={typing}
          autoComplete="off"
        />
        <Button
          type="submit"
          size="icon"
          className="size-10 shrink-0 rounded-full"
          disabled={typing || !input.trim()}
          aria-label="Send"
        >
          <Send className="size-4" />
        </Button>
      </form>

      <BackendActionBar
        actions={persistentActions}
        onAction={handleBackendAction}
      />
    </div>
  );

  const panel = (
    <div
      className={cn(
        "relative flex flex-col overflow-hidden border border-border bg-white shadow-[0_20px_60px_-20px_rgba(11,14,46,0.45)]",
        mode === "embedded" && "h-full min-h-[400px] w-full rounded-[6px]",
        mode === "widget" &&
          !expanded &&
          "h-[min(640px,calc(100dvh-5rem))] w-[min(440px,calc(100vw-1.5rem))] rounded-[6px]",
        mode === "widget" &&
          expanded &&
          "h-[min(90dvh,900px)] w-[min(78vw,1100px)] rounded-[6px]",
        mode === "widget" &&
          "max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:top-auto max-sm:h-[min(94dvh,800px)] max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:rounded-t-[12px]",
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
      <AnimatePresence>
        {open && expanded ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-auto fixed inset-0 z-[55] bg-black/25 backdrop-blur-[2px]"
            onClick={() => setExpanded(false)}
            aria-hidden
          />
        ) : null}
      </AnimatePresence>

      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-end p-3 sm:inset-x-auto sm:right-5 sm:bottom-5 sm:p-0">
        <AnimatePresence>
          {open ? (
            <motion.div
              initial={{ opacity: 0, y: 20, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 12, scale: 0.98 }}
              transition={{ duration: 0.2 }}
              className={cn(
                "pointer-events-auto mb-3 w-full sm:mb-3",
                expanded &&
                  "sm:fixed sm:inset-0 sm:z-[60] sm:m-0 sm:flex sm:items-center sm:justify-center sm:p-4"
              )}
            >
              {panel}
            </motion.div>
          ) : null}
        </AnimatePresence>

        <button
          type="button"
          onClick={() => (open ? closeAll() : setOpen(true))}
          className="pointer-events-auto flex size-14 items-center justify-center rounded-[10px] shadow-lg ring-2 ring-white transition hover:scale-[1.02] active:scale-[0.98]"
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
