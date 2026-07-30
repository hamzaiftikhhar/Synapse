"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, Send, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { BookingSheet } from "@/features/booking";
import {
  SamplePromptChips,
  StarterChips,
} from "@/features/chat/components/action-buttons";
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

const CLINIC_SAMPLES = [
  { id: "s1", label: "I have a headache", message: "I have a headache" },
  { id: "s2", label: "Do you accept Aetna?", message: "Do you accept Aetna insurance?" },
  {
    id: "s3",
    label: "Who are your cardiologists?",
    message: "Who are your cardiologists?",
  },
];

const CLINIC_STARTERS = [
  {
    id: "doctor",
    label: "Find a Doctor",
    message: "Help me find a doctor",
    icon: "Stethoscope",
  },
  {
    id: "book",
    label: "Book Appointment",
    message: "I would like to book an appointment",
    icon: "Calendar",
  },
  {
    id: "hours",
    label: "Clinic Hours",
    message: "What are your clinic hours?",
    icon: "Clock",
  },
];

const MARKETING_SAMPLES = [
  { id: "s1", label: "What is Synapse?", message: "What is Synapse?" },
  { id: "s2", label: "Pricing", message: "Tell me about pricing" },
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
  action: BackendAction & {
    doctor_id?: string;
    doctor_name?: string;
    specialty_id?: string;
    specialty_name?: string;
  },
  sendText: (text: string) => void,
  launchBooking?: (
    seed?: string,
    prefill?: {
      specialtyId?: string | null;
      specialtyName?: string | null;
      doctorId?: string | null;
      doctorName?: string | null;
    }
  ) => void
) {
  const behavior = action.behavior ?? "message";

  if (behavior === "launch_booking") {
    launchBooking?.(action.message || undefined, {
      doctorId: action.doctor_id,
      doctorName: action.doctor_name,
      specialtyId: action.specialty_id,
      specialtyName: action.specialty_name,
    });
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
      ? "Hi! How can Synapse help you today?"
      : `Hi! How can ${displayName} help you today?`);

  const starters =
    resolvedMode === "marketing" ? MARKETING_STARTERS : CLINIC_STARTERS;
  const samples =
    resolvedMode === "marketing" ? MARKETING_SAMPLES : CLINIC_SAMPLES;

  const [open, setOpen] = useState(mode === "embedded" || defaultOpen);
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [typing, setTyping] = useState(false);
  const [showJumpDown, setShowJumpDown] = useState(false);
  const [bookingOpen, setBookingOpen] = useState(false);
  const [bookingSeed, setBookingSeed] = useState("");
  const [bookingPrefill, setBookingPrefill] = useState<{
    specialtyId?: string | null;
    specialtyName?: string | null;
    doctorId?: string | null;
    doctorName?: string | null;
  }>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const lastUserMessageRef = useRef("");
  const lastBookingMetaRef = useRef<Record<string, unknown> | null>(null);
  const staffChat = useStaffChat();
  const patientChat = usePatientChat();
  const guestChat = useGuestChat();
  const marketingChat = useMarketingChat();
  const staffMode =
    resolvedMode === "staff" || (useStaffApi && isAuthenticated);
  const canBook =
    resolvedMode !== "marketing" && Boolean(clinicSlug || clinic?.slug);
  const bookingClinicSlug = clinicSlug || clinic?.slug || "";

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

  const openBooking = useCallback(
    (
      seed?: string,
      prefill?: {
        specialtyId?: string | null;
        specialtyName?: string | null;
        doctorId?: string | null;
        doctorName?: string | null;
      }
    ) => {
      if (!canBook) return;
      const meta = lastBookingMetaRef.current || {};
      setBookingSeed((seed || lastUserMessageRef.current || "").trim());
      setBookingPrefill({
        specialtyId:
          prefill?.specialtyId ??
          (meta.specialty_id as string | undefined) ??
          null,
        specialtyName:
          prefill?.specialtyName ??
          (meta.specialty_name as string | undefined) ??
          null,
        doctorId:
          prefill?.doctorId ?? (meta.doctor_id as string | undefined) ?? null,
        doctorName:
          prefill?.doctorName ??
          (meta.doctor_name as string | undefined) ??
          null,
      });
      setBookingOpen(true);
      if (!open) setOpen(true);
    },
    [canBook, open]
  );

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || typing) return;
      setInput("");
      stickToBottom.current = true;
      lastUserMessageRef.current = trimmed;
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
        const bookingMeta = res.meta?.booking;
        if (bookingMeta && typeof bookingMeta === "object") {
          lastBookingMetaRef.current = bookingMeta as Record<string, unknown>;
        }
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
    runBackendAction(action, (msg) => void sendText(msg), openBooking);
  }

  function handleBookingConfirmed(payload: BookingStepPayload) {
    const conf = payload.confirmation;
    setMessages((prev) => [
      ...prev,
      {
        id: uid("confirm"),
        role: "assistant",
        type: "confirmation",
        content: "Appointment confirmed",
        createdAt: new Date().toISOString(),
        payload: {
          confirmation_code: conf?.confirmation_code,
          appointment_id: conf?.appointment_id,
          slot_summary: conf?.slot_summary,
          doctor_name: conf?.doctor_name,
          date: conf?.date,
          start: conf?.start,
        },
      },
    ]);
    setBookingOpen(false);
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
      const btn = data as BackendAction & {
        label?: string;
        doctor_id?: string;
        doctor_name?: string;
        specialty_id?: string;
        specialty_name?: string;
      };
      runBackendAction(
        {
          id: btn.id,
          label: btn.label ?? "",
          behavior: btn.behavior,
          message: btn.message ?? btn.label,
          url: btn.url,
          href: btn.href,
          phone: btn.phone,
          filled: btn.filled,
          icon: btn.icon,
          doctor_id: btn.doctor_id,
          doctor_name: btn.doctor_name,
          specialty_id: btn.specialty_id,
          specialty_name: btn.specialty_name,
        },
        (msg) => void sendText(msg),
        openBooking
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
      const doctor = data as {
        id?: string;
        name?: string;
        select_message?: string;
        message?: string;
      };
      if (canBook && doctor.id) {
        openBooking(doctor.select_message || `Book with ${doctor.name}`, {
          doctorId: doctor.id,
          doctorName: doctor.name,
        });
        return;
      }
      if (text) void sendText(text);
      return;
    }
  }

  function closeAll() {
    setOpen(false);
    setExpanded(false);
  }

  function handleStarter(msg: string, id?: string) {
    // Book chip opens wizard (commit); samples/other chips start conversation.
    if (id === "book" && canBook) {
      openBooking(msg);
      return;
    }
    void sendText(msg);
  }

  const emptyState = (
    <div className="flex flex-col gap-1">
      <SamplePromptChips
        items={samples}
        onSelect={(msg) => void sendText(msg)}
      />
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
        onSelect={(msg, item) => handleStarter(msg, item?.id)}
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
          "h-[min(740px,calc(100dvh-5.5rem))] w-[min(560px,calc(100vw-1.25rem))] rounded-[8px]",
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

  if (mode === "embedded") {
    return (
      <>
        {panel}
        {canBook ? (
          <BookingSheet
            open={bookingOpen}
            onOpenChange={setBookingOpen}
            clinicSlug={bookingClinicSlug}
            initialMessage={bookingSeed}
            specialtyId={bookingPrefill.specialtyId}
            specialtyName={bookingPrefill.specialtyName}
            doctorId={bookingPrefill.doctorId}
            doctorName={bookingPrefill.doctorName}
            onConfirmed={handleBookingConfirmed}
          />
        ) : null}
      </>
    );
  }

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

      {canBook ? (
        <BookingSheet
          open={bookingOpen}
          onOpenChange={setBookingOpen}
          clinicSlug={bookingClinicSlug}
          initialMessage={bookingSeed}
          specialtyId={bookingPrefill.specialtyId}
          specialtyName={bookingPrefill.specialtyName}
          doctorId={bookingPrefill.doctorId}
          doctorName={bookingPrefill.doctorName}
          onConfirmed={handleBookingConfirmed}
        />
      ) : null}
    </>
  );
}
