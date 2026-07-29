"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  Maximize2,
  Menu,
  MessageCircle,
  Minimize2,
  Send,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { MessageRenderer } from "@/features/chat/messages";
import {
  createWelcomeMessages,
  MAIN_MENU_ITEMS,
  parseChatResponse,
  uid,
  userTextMessage,
} from "@/features/chat/message-parser";
import { useStaffChat } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import type { ChatMessage, MainMenuItem } from "@/types/chat";

export type ChatWidgetProps = {
  /** widget = floating launcher; embedded = inline panel (hero mock) */
  mode?: "widget" | "embedded";
  clinicName?: string;
  useStaffApi?: boolean;
  demoMode?: boolean;
  className?: string;
  defaultOpen?: boolean;
};

function demoReply(text: string): ChatMessage[] {
  const lower = text.toLowerCase();
  const now = new Date().toISOString();
  const base: ChatMessage = {
    id: uid("demo"),
    role: "assistant",
    type: "text",
    content: "",
    createdAt: now,
  };

  if (lower.includes("doctor")) {
    return [
      {
        ...base,
        content: "Here are available providers:",
      },
      {
        id: uid("demo_docs"),
        role: "assistant",
        type: "doctor_cards",
        createdAt: now,
        payload: {
          doctors: [
            {
              name: "Dr. Ava Chen",
              title: "Cardiologist",
              bio: "Preventive cardiology and hypertension.",
              languages: ["English", "Mandarin"],
              accepting: true,
            },
            {
              name: "Dr. Marcus Reid",
              title: "Internal Medicine",
              bio: "Primary care for adults and chronic care.",
              languages: ["English", "Spanish"],
              accepting: true,
            },
          ],
        },
      },
    ];
  }
  if (lower.includes("insurance")) {
    return [
      { ...base, content: "We currently accept these plans:" },
      {
        id: uid("demo_ins"),
        role: "assistant",
        type: "insurance_cards",
        createdAt: now,
        payload: {
          plans: [
            { name: "Blue Cross Blue Shield", plan: "PPO & HMO" },
            { name: "Aetna", plan: "Most commercial plans" },
            { name: "UnitedHealthcare", plan: "Select networks" },
          ],
        },
      },
    ];
  }
  if (lower.includes("service")) {
    return [
      { ...base, content: "Popular services at this clinic:" },
      {
        id: uid("demo_svc"),
        role: "assistant",
        type: "service_cards",
        createdAt: now,
        payload: {
          services: [
            {
              name: "New Patient Visit",
              description: "Comprehensive intake and exam.",
              duration_min: 45,
              price_cents: 25000,
            },
            {
              name: "Follow-up Consultation",
              description: "Review results and adjust care.",
              duration_min: 20,
              price_cents: 15000,
            },
          ],
        },
      },
    ];
  }
  if (lower.includes("hour")) {
    return [
      {
        ...base,
        content:
          "Clinic hours: Mon–Fri 8:00 AM – 6:00 PM, Sat 9:00 AM – 1:00 PM. Closed Sunday.",
      },
    ];
  }
  if (lower.includes("location") || lower.includes("where")) {
    return [
      { ...base, content: "Here is our location:" },
      {
        id: uid("demo_loc"),
        role: "assistant",
        type: "clinic_location",
        createdAt: now,
        payload: {
          name: "Synapse Demo Clinic",
          address: "1200 Market Street, Suite 400, San Francisco, CA",
          phone: "(415) 555-0142",
        },
      },
    ];
  }
  if (lower.includes("contact") || lower.includes("phone")) {
    return [
      {
        ...base,
        content:
          "You can reach the front desk at (415) 555-0142 or email care@demo-clinic.example. Hours: Mon–Fri 8 AM – 6 PM.",
      },
    ];
  }
  if (lower.includes("faq") || lower.includes("frequent")) {
    return [
      {
        ...base,
        content:
          "Common questions: bring a photo ID and insurance card, arrive 15 minutes early for new patients, and cancel at least 24 hours ahead when possible.",
      },
      {
        id: uid("demo_qr"),
        role: "assistant",
        type: "quick_replies",
        createdAt: now,
        payload: {
          replies: [
            "Book an appointment",
            "What insurance do you accept?",
            "Clinic hours",
          ],
        },
      },
    ];
  }
  if (lower.includes("book") || lower.includes("appointment")) {
    return [
      { ...base, content: "Let's book a visit. Pick a preferred date:" },
      {
        id: uid("demo_cal"),
        role: "assistant",
        type: "date_picker",
        createdAt: now,
      },
      {
        id: uid("demo_slots"),
        role: "assistant",
        type: "time_slots",
        createdAt: now,
        payload: {
          slots: [
            { id: "1", label: "9:00 AM", start: "09:00" },
            { id: "2", label: "10:30 AM", start: "10:30" },
            { id: "3", label: "2:00 PM", start: "14:00" },
            { id: "4", label: "4:15 PM", start: "16:15" },
          ],
        },
      },
    ];
  }
  return [
    {
      ...base,
      content:
        "I can help with appointments, doctors, insurance, services, hours, and location. Choose an option below or type your question.",
    },
    {
      id: uid("demo_qr"),
      role: "assistant",
      type: "quick_replies",
      createdAt: now,
      payload: {
        replies: [
          "Book an appointment",
          "Find a doctor",
          "What insurance do you accept?",
          "Clinic hours",
        ],
      },
    },
  ];
}

export function ChatWidget({
  mode = "widget",
  clinicName,
  useStaffApi = true,
  demoMode = false,
  className,
  defaultOpen = false,
}: ChatWidgetProps) {
  const { clinic, isAuthenticated } = useAuth();
  const name = clinicName || clinic?.name || "Synapse Clinic";
  const [open, setOpen] = useState(mode === "embedded" || defaultOpen);
  const [expanded, setExpanded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [typing, setTyping] = useState(false);
  const [showJumpDown, setShowJumpDown] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const staffChat = useStaffChat();
  const staffMode = useStaffApi && isAuthenticated && !demoMode;

  useEffect(() => {
    setMessages(createWelcomeMessages(name));
    stickToBottom.current = true;
  }, [name]);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
    stickToBottom.current = true;
    setShowJumpDown(false);
  }, []);

  useEffect(() => {
    if (stickToBottom.current) {
      scrollToBottom(messages.length > 2);
    }
  }, [messages, typing, scrollToBottom]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const nearBottom = distance < 48;
    stickToBottom.current = nearBottom;
    setShowJumpDown(!nearBottom && el.scrollHeight > el.clientHeight + 80);
  }

  async function sendText(text: string) {
    const trimmed = text.trim();
    if (!trimmed || typing) return;
    setInput("");
    stickToBottom.current = true;
    setMessages((prev) => [...prev, userTextMessage(trimmed)]);
    setTyping(true);
    try {
      // Staff portal uses live API; marketing / unauthenticated uses demo replies.
      // Patient OTP chat needs a verified widget session (embed integration).
      if (!staffMode) {
        await new Promise((r) => setTimeout(r, 400));
        setMessages((prev) => [...prev, ...demoReply(trimmed)]);
        return;
      }
      const res = await staffChat.mutateAsync({ message: trimmed });
      setMessages((prev) => [...prev, ...parseChatResponse(res)]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: uid("err"),
          role: "system",
          type: "system",
          content: getApiErrorMessage(err),
          createdAt: new Date().toISOString(),
        },
      ]);
    } finally {
      setTyping(false);
    }
  }

  function handleAction(action: string, data?: unknown) {
    if (action === "suggested" || action === "quick_reply") {
      void sendText(String(data));
      return;
    }
    if (action === "menu") {
      const item = data as MainMenuItem;
      setMenuOpen(false);
      void sendText(item.prompt);
      return;
    }
    if (action === "select_doctor") {
      const d = data as { name?: string };
      void sendText(`I'd like to book with ${d.name ?? "this doctor"}`);
      return;
    }
    if (action === "select_service") {
      const s = data as { name?: string };
      void sendText(`Tell me more about ${s.name ?? "this service"}`);
      return;
    }
    if (action === "select_insurance") {
      const p = data as { name?: string };
      void sendText(`Do you accept ${p.name ?? "this insurance"}?`);
      return;
    }
    if (action === "select_date") {
      void sendText(`I'd like an appointment on ${String(data)}`);
      return;
    }
    if (action === "select_slot") {
      const slot = data as { label?: string };
      void sendText(`Book me for ${slot.label ?? "that time"}`);
      return;
    }
    if (action === "submit_appointment") {
      const form = data as {
        firstName?: string;
        lastName?: string;
        phone?: string;
      };
      void sendText(
        `Book appointment for ${form.firstName ?? ""} ${form.lastName ?? ""}, phone ${form.phone ?? ""}`
      );
    }
  }

  const panel = (
    <div
      className={cn(
        "flex flex-col overflow-hidden border border-border bg-white shadow-[0_12px_40px_-12px_rgba(11,14,46,0.35)]",
        mode === "embedded" && "h-full min-h-[360px] w-full rounded-[6px]",
        mode === "widget" &&
          !expanded &&
          "h-[min(560px,calc(100dvh-6.5rem))] w-[min(380px,calc(100vw-1.5rem))] rounded-[6px]",
        mode === "widget" &&
          expanded &&
          "h-[min(720px,calc(100dvh-5rem))] w-[min(520px,calc(100vw-1.5rem))] rounded-[6px] sm:w-[min(560px,calc(100vw-2rem))]",
        // Mobile: nearly full screen when open as widget
        mode === "widget" &&
          "max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:top-auto max-sm:h-[min(92dvh,720px)] max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:rounded-t-[10px]",
        className
      )}
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-white/10 bg-navy px-3.5 py-3 text-white">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-[6px] bg-white/10">
            <MessageCircle className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold tracking-tight">
              Clinic Assistant
            </p>
            <p className="truncate text-[11px] text-white/55">
              {name}
              <span className="mx-1.5 text-white/25">·</span>
              <span className="text-emerald-300/90">Online</span>
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            aria-label="Quick options"
            title="Quick options"
            onClick={() => setMenuOpen((v) => !v)}
            className={cn(
              "rounded-[6px] p-1.5 transition-colors hover:bg-white/10",
              menuOpen && "bg-white/15"
            )}
          >
            <Menu className="size-4" />
          </button>
          {mode === "widget" ? (
            <>
              <button
                type="button"
                aria-label={expanded ? "Compact chat" : "Expand chat"}
                title={expanded ? "Compact" : "Expand"}
                onClick={() => setExpanded((v) => !v)}
                className="hidden rounded-[6px] p-1.5 transition-colors hover:bg-white/10 sm:inline-flex"
              >
                {expanded ? (
                  <Minimize2 className="size-4" />
                ) : (
                  <Maximize2 className="size-4" />
                )}
              </button>
              <button
                type="button"
                aria-label="Close chat"
                title="Close"
                onClick={() => {
                  setOpen(false);
                  setExpanded(false);
                  setMenuOpen(false);
                }}
                className="rounded-[6px] p-1.5 transition-colors hover:bg-white/10"
              >
                <X className="size-4" />
              </button>
            </>
          ) : null}
        </div>
      </div>

      {/* Quick options drawer */}
      <AnimatePresence initial={false}>
        {menuOpen ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="shrink-0 overflow-hidden border-b border-border bg-[#f7f7fb]"
          >
            <div className="grid grid-cols-2 gap-1 p-2">
              {MAIN_MENU_ITEMS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => handleAction("menu", item)}
                  className="rounded-[6px] border border-transparent bg-white px-2.5 py-2 text-left text-[11px] font-medium text-navy shadow-sm transition-colors hover:border-primary/20 hover:bg-accent/40"
                >
                  {item.label}
                </button>
              ))}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* Messages — native scroll for reliable history browsing */}
      <div className="relative min-h-0 flex-1 bg-[#fbfbfe]">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="h-full overflow-y-auto overscroll-contain px-3 py-3"
        >
          <div className="mx-auto flex max-w-lg flex-col gap-3">
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
            <div ref={bottomRef} className="h-px shrink-0" />
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
              className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-white px-3 py-1.5 text-[11px] font-medium text-navy shadow-md"
              aria-label="Jump to latest message"
            >
              <ArrowDown className="size-3" />
              Latest
            </motion.button>
          ) : null}
        </AnimatePresence>
      </div>

      {/* Composer */}
      <form
        className="flex shrink-0 items-center gap-2 border-t border-border bg-white p-2.5 sm:p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void sendText(input);
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message…"
          className="h-9 rounded-[6px] border-border bg-white"
          disabled={typing}
          autoComplete="off"
        />
        <Button
          type="submit"
          size="icon"
          className="size-9 shrink-0 rounded-[6px]"
          disabled={typing || !input.trim()}
          aria-label="Send message"
        >
          <Send className="size-4" />
        </Button>
      </form>
    </div>
  );

  if (mode === "embedded") {
    return panel;
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-end p-3 sm:inset-x-auto sm:right-5 sm:bottom-5 sm:p-0">
      <AnimatePresence>
        {open ? (
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.98 }}
            transition={{ duration: 0.18 }}
            className="pointer-events-auto mb-3 w-full sm:mb-3 sm:w-auto"
          >
            {panel}
          </motion.div>
        ) : null}
      </AnimatePresence>

      <button
        type="button"
        onClick={() => {
          if (open) {
            setOpen(false);
            setExpanded(false);
            setMenuOpen(false);
          } else {
            setOpen(true);
          }
        }}
        className={cn(
          "pointer-events-auto flex size-12 items-center justify-center rounded-[6px] bg-navy text-white shadow-lg transition hover:bg-navy/90",
          "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        )}
        aria-label={open ? "Close chat" : "Open chat"}
      >
        {open ? (
          <X className="size-5" />
        ) : (
          <MessageCircle className="size-5" />
        )}
      </button>
    </div>
  );
}
