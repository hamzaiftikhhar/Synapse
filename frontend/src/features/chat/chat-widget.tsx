"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { format } from "date-fns";
import { ArrowDown, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  SamplePromptChips,
  StarterChips,
} from "@/features/chat/components/action-buttons";
import { ChatComposer } from "@/features/chat/components/chat-composer";
import {
  BotMetaRow,
  ChatHeader,
} from "@/features/chat/components/chat-chrome";
import {
  RobotAvatar,
  RobotLauncherIcon,
} from "@/features/chat/components/robot-avatar";
import { MessageRenderer } from "@/features/chat/messages";
import {
  CHAT_TIMEOUT_ERROR,
  CLINIC_CONTEXT_ERROR,
  CONNECTION_ERROR,
  bookingWizardMessage,
  insuranceSelectedMessage,
  parseChatResponse,
  systemErrorMessage,
  systemNoticeMessage,
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
import { readSelectedInsurance } from "@/hooks/use-selected-insurance";
import { getActiveTenant, getApiErrorMessage } from "@/lib/api/client";
import { widgetAppointmentsService } from "@/services";
import { useAuth } from "@/providers/auth-provider";
import { useWidget, type AssistantMode } from "@/providers/widget-provider";
import type { BookingStepPayload } from "@/types/api";
import type { AppointmentCardData, ChatMessage, TimeSlotData } from "@/types/chat";
import { waitForNaturalReplyPace } from "@/features/chat/natural-pace";

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
  sendText: (text: string) => void
) {
  const behavior = action.behavior ?? "message";

  // Never open wizard client-side — always go through chat
  if (behavior === "launch_booking") {
    const msg =
      action.message?.trim() ||
      (action.doctor_name
        ? `I would like to book an appointment with ${action.doctor_name}`
        : "I would like to book an appointment");
    sendText(msg);
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
  // Own copy of the patient chat session token. GlobalChatWidget used to sit
  // outside WidgetProvider, so setSessionToken was a no-op and cancel/reschedule
  // posted session_token:"" even after a successful verify+list. Keep a local
  // ref so appointment CRUD never depends solely on context wiring.
  const sessionTokenRef = useRef<string | null>(widgetCtx.sessionToken);
  useEffect(() => {
    if (widgetCtx.sessionToken) sessionTokenRef.current = widgetCtx.sessionToken;
  }, [widgetCtx.sessionToken]);

  function rememberSessionToken(token: string | null | undefined) {
    if (!token) return;
    sessionTokenRef.current = token;
    widgetCtx.setSessionToken(token);
  }

  function patientSessionToken(): string {
    return sessionTokenRef.current || widgetCtx.sessionToken || "";
  }

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
  const [dismissedWizards, setDismissedWizards] = useState<Set<string>>(
    () => new Set()
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const lastUserMessageRef = useRef("");
  const lastBookingMetaRef = useRef<Record<string, unknown> | null>(null);
  const requestIdRef = useRef(0);
  const staffChat = useStaffChat();
  const patientChat = usePatientChat();
  const guestChat = useGuestChat();
  const marketingChat = useMarketingChat();
  const staffMode =
    resolvedMode === "staff" || (useStaffApi && isAuthenticated);
  const canBook =
    resolvedMode !== "marketing" && Boolean(clinicSlug || clinic?.slug);
  const bookingClinicSlug = clinicSlug || clinic?.slug || "";

  const activeWizardId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (
        m?.type === "booking_wizard" &&
        !dismissedWizards.has(m.id) &&
        !m.payload?.completed
      ) {
        return m.id;
      }
    }
    return null;
  }, [messages, dismissedWizards]);

  const lastActionMessageId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (
        m?.role === "assistant" &&
        Array.isArray(m.payload?.actions) &&
        (m.payload.actions as unknown[]).length > 0
      ) {
        return m.id;
      }
    }
    return null;
  }, [messages]);

  const resetChat = useCallback(() => {
    requestIdRef.current += 1;
    setTyping(false);
    setMessages([]);
    setDismissedWizards(new Set());
    stickToBottom.current = true;
  }, []);

  const scrollToBottom = useCallback(
    (smooth = true) => {
      const el = scrollRef.current;
      if (!el) return;
      el.scrollTo({
        top: el.scrollHeight,
        behavior: smooth && !expanded ? "smooth" : "auto",
      });
      stickToBottom.current = true;
      setShowJumpDown(false);
    },
    [expanded]
  );

  useEffect(() => {
    if (stickToBottom.current) scrollToBottom(messages.length > 0);
  }, [messages, typing, scrollToBottom]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = distance < 64;
    setShowJumpDown(
      !stickToBottom.current && el.scrollHeight > el.clientHeight + 80
    );
  }

  const stopGenerating = useCallback(() => {
    requestIdRef.current += 1;
    setTyping(false);
  }, []);

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || typing) return;
      setInput("");
      stickToBottom.current = true;
      lastUserMessageRef.current = trimmed;
      setMessages((prev) => [...prev, userTextMessage(trimmed)]);
      setTyping(true);
      const reqId = ++requestIdRef.current;
      const startedAt = performance.now();

      try {
        let res;
        if (staffMode) {
          const activeTenant =
            getActiveTenant() || clinic?.slug || clinicSlug || null;
          if (!activeTenant) {
            setMessages((prev) => [
              ...prev,
              systemErrorMessage(CLINIC_CONTEXT_ERROR),
            ]);
            return;
          }
          res = await staffChat.mutateAsync({
            message: trimmed,
            session_token: patientSessionToken() || null,
          });
          const staffToken = res.meta?.session_token;
          if (typeof staffToken === "string") rememberSessionToken(staffToken);
        } else if (resolvedMode === "marketing") {
          res = await marketingChat.mutateAsync({ message: trimmed });
        } else if (resolvedMode === "clinic" && clinicSlug) {
          res = await guestChat.mutateAsync({
            clinic_slug: clinicSlug,
            message: trimmed,
            session_token: patientSessionToken() || null,
          });
          const token = res.meta?.session_token;
          if (typeof token === "string") rememberSessionToken(token);
        } else {
          res = await patientChat.mutateAsync({
            message: trimmed,
            session_token: patientSessionToken() || null,
          });
        }

        if (reqId !== requestIdRef.current) return;

        // Pad only ultra-fast rule replies so they feel intentional, not robotic.
        // Slow NLU/SQL/RAG paths get zero extra wait.
        await waitForNaturalReplyPace(startedAt);
        if (reqId !== requestIdRef.current) return;

        const parsed = parseChatResponse(res);
        const bookingMeta = res.meta?.booking;
        if (bookingMeta && typeof bookingMeta === "object") {
          lastBookingMetaRef.current = bookingMeta as Record<string, unknown>;
        }
        const bookingUpdate = parsed.bookingUpdate;
        setMessages((prev) => {
          const next = [...prev, ...parsed.messages];
          if (!bookingUpdate) return next;
          const visible = next.find(
            (m) =>
              m.type === "booking_wizard" &&
              (m.payload as Record<string, unknown> | undefined)?.booking_id ===
                bookingUpdate.bookingId &&
              !dismissedWizards.has(m.id) &&
              !m.payload?.completed
          );
          if (visible) {
            return next.map((m) =>
              m.id === visible.id
                ? { ...m, payload: { ...(m.payload ?? {}), ...bookingUpdate.patch } }
                : m
            );
          }
          // Draft exists on the session but the card isn't on screen
          // (dismissed, reload, or staff view) — mint it so the reply
          // isn't a dangling "choose below" with no UI.
          return [
            ...next,
            bookingWizardMessage({
              ...bookingUpdate.patch,
              booking_id: bookingUpdate.bookingId,
              launch: true,
            }),
          ];
        });
      } catch (err) {
        // Log timeout vs network for ops; user-facing copy stays friendly.
        const ax = err as {
          code?: string;
          message?: string;
          response?: { status?: number; data?: { detail?: string } };
        };
        console.warn("chat_request_failed", {
          code: ax?.code,
          status: ax?.response?.status,
          message: ax?.message,
          detail: ax?.response?.data?.detail,
        });
        if (reqId !== requestIdRef.current) return;
        await waitForNaturalReplyPace(startedAt);
        if (reqId !== requestIdRef.current) return;
        const detail = String(ax?.response?.data?.detail || "").toLowerCase();
        const isTimeout =
          ax?.code === "ECONNABORTED" ||
          /timeout/i.test(ax?.message || "") ||
          ax?.response?.status === 504;
        const needsClinic =
          ax?.response?.status === 400 &&
          (detail.includes("clinic context") || detail.includes("clinic"));
        const friendly = needsClinic
          ? CLINIC_CONTEXT_ERROR
          : isTimeout
            ? CHAT_TIMEOUT_ERROR
            : CONNECTION_ERROR;
        setMessages((prev) => [...prev, systemErrorMessage(friendly)]);
      } finally {
        if (reqId === requestIdRef.current) setTyping(false);
      }
    },
    [
      typing,
      staffMode,
      resolvedMode,
      clinicSlug,
      clinic,
      staffChat,
      patientChat,
      guestChat,
      marketingChat,
      widgetCtx,
      dismissedWizards,
    ]
  );

  function handleBackendAction(action: BackendAction) {
    // "Check Insurance" already has an answer once the patient picked a
    // plan this session — don't re-ask the backend a question we already
    // know. Surface the existing selection as widget state instead of a
    // fresh chat round-trip; skip if it's already the most recent message
    // so repeat clicks don't stack up duplicate cards.
    if (action.id === "insurance" && canBook) {
      const existing = readSelectedInsurance(bookingClinicSlug);
      if (existing && existing.is_accepted !== false) {
        const last = messages[messages.length - 1];
        if (last?.type !== "insurance_cards") {
          setMessages((prev) => [...prev, insuranceSelectedMessage()]);
        }
        return;
      }
    }
    runBackendAction(action, (msg) => void sendText(msg));
  }

  function handleIdentityVerified(sessionToken: string) {
    // OTP verification is a state transition, not a new chat turn — fetch
    // the now-authenticated patient's appointments directly instead of
    // re-sending the triggering message (which would duplicate the user's
    // message and re-run intent classification for no reason).
    // Prefer the token just returned by verify — React state may not have
    // flushed widgetCtx.sessionToken yet.
    const token = sessionToken || patientSessionToken();
    if (token) rememberSessionToken(token);
    void (async () => {
      try {
        const result = await widgetAppointmentsService.list({
          clinic_slug: bookingClinicSlug,
          session_token: token,
        });
        setMessages((prev) => [
          ...prev,
          {
            id: uid("appt"),
            role: "assistant",
            type: "appointments",
            createdAt: new Date().toISOString(),
            payload: { appointments: result.appointments },
          },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          systemErrorMessage(
            getApiErrorMessage(err, "Couldn't load your appointments — please try again.")
          ),
        ]);
      }
    })();
  }

  function handleBookingConfirmed(_payload: BookingStepPayload) {
    // Confirmation stays inside the wizard card only — no duplicate chat message
    setMessages((prev) =>
      prev.map((m) =>
        m.type === "booking_wizard" && m.id === activeWizardId
          ? {
              ...m,
              payload: { ...(m.payload ?? {}), completed: true },
            }
          : m
      )
    );
  }

  function handleBookingDismiss(messageId: string) {
    setDismissedWizards((prev) => new Set(prev).add(messageId));
  }

  function handleBookingStarted(messageId: string, bookingId: string) {
    // Stamp the wizard card's own payload with its booking_id so a later
    // turn's bookingUpdate (matched by booking_id) can find this message.
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId && m.payload?.booking_id !== bookingId
          ? { ...m, payload: { ...(m.payload ?? {}), booking_id: bookingId } }
          : m
      )
    );
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
      const doctor = data as {
        id?: string;
        name?: string;
        select_message?: string;
        message?: string;
      };
      setMessages((prev) => [
        ...prev,
        bookingWizardMessage({
          reason: doctor.name
            ? `I would like to book an appointment with ${doctor.name}`
            : "I would like to book an appointment",
          doctor_id: doctor.id || undefined,
          doctor_name: doctor.name || undefined,
        }),
      ]);
      return;
    }

    if (action === "select_slot") {
      const slot = data as TimeSlotData;
      if (!slot.start || !slot.doctor_id) {
        setMessages((prev) => [
          ...prev,
          bookingWizardMessage({
            reason: slot.doctor
              ? `I would like to book an appointment with ${slot.doctor}`
              : "I would like to book an appointment",
            doctor_id: slot.doctor_id || undefined,
            doctor_name: slot.doctor || undefined,
          }),
        ]);
        return;
      }
      // Prefer a matching end; if missing, assume 30-minute slot
      let end = slot.end || "";
      if (!end && slot.start) {
        const startMs = Date.parse(slot.start);
        if (!Number.isNaN(startMs)) {
          end = new Date(startMs + 30 * 60 * 1000).toISOString();
        }
      }
      setMessages((prev) => [
        ...prev,
        bookingWizardMessage({
          reason: `Book ${slot.label || slot.time || "this time"}`,
          doctor_id: slot.doctor_id,
          doctor_name: slot.doctor,
          slot_start: slot.start,
          slot_end: end,
        }),
      ]);
      return;
    }

    if (action === "book_appointment") {
      const payload = data as {
        service?: string;
        service_id?: string;
        insurance?: string;
      };
      const stored = readSelectedInsurance(bookingClinicSlug);
      const usableStored = stored && stored.is_accepted !== false ? stored : null;
      const insurance =
        payload?.insurance || usableStored?.name || undefined;
      setMessages((prev) => [
        ...prev,
        bookingWizardMessage({
          reason: payload?.service
            ? `I would like to book ${payload.service}`
            : "I would like to book an appointment",
          service_name: payload?.service,
          service_id: payload?.service_id,
          insurance_name: insurance,
        }),
      ]);
      return;
    }

    if (action === "select_service") {
      const service = data as {
        id?: string;
        name?: string;
        select_message?: string;
      };
      setMessages((prev) => [
        ...prev,
        bookingWizardMessage({
          reason: service.name
            ? `I would like to book ${service.name}`
            : "I would like to book an appointment",
          service_id: service.id,
          service_name: service.name,
        }),
      ]);
      return;
    }

    if (action === "confirm_cancel_appointment") {
      const appt = data as { id?: string; doctor?: string };
      if (!appt.id) return;
      const appointmentId = appt.id;
      void (async () => {
        try {
          await widgetAppointmentsService.cancel({
            clinic_slug: bookingClinicSlug,
            session_token: patientSessionToken(),
            appointment_id: appointmentId,
          });
          // Drop it from any appointments card already on screen — otherwise
          // the just-cancelled appointment keeps showing Reschedule/Cancel
          // buttons as if it were still active.
          setMessages((prev) =>
            prev.map((m) => {
              if (m.type !== "appointments") return m;
              const list = (m.payload?.appointments as AppointmentCardData[]) ?? [];
              return {
                ...m,
                payload: {
                  ...m.payload,
                  appointments: list.filter((a) => a.id !== appointmentId),
                },
              };
            })
          );
          setMessages((prev) => [
            ...prev,
            systemNoticeMessage(
              appt.doctor
                ? `Appointment cancelled. Your appointment with ${appt.doctor} has been cancelled.`
                : "Appointment cancelled."
            ),
          ]);
        } catch (err) {
          setMessages((prev) => [
            ...prev,
            systemErrorMessage(getApiErrorMessage(err, "Couldn't cancel that appointment — please try again.")),
          ]);
        }
      })();
      return;
    }

    if (action === "start_reschedule") {
      const appt = data as {
        id?: string;
        doctor?: string;
        service?: string;
        changeDoctor?: boolean;
      };
      if (!appt.id) return;
      const appointmentId = appt.id;
      const keepDoctor = !appt.changeDoctor;
      void (async () => {
        try {
          const result = await widgetAppointmentsService.reschedule({
            clinic_slug: bookingClinicSlug,
            session_token: patientSessionToken(),
            appointment_id: appointmentId,
          });
          const start = new Date(result.start_time);
          const currentWhen =
            result.when ||
            (Number.isNaN(start.getTime())
              ? result.start_time
              : format(start, "EEE d MMM, h:mm a"));
          setMessages((prev) => [
            ...prev,
            systemNoticeMessage(
              `Current appointment: ${result.doctor_name} · ${currentWhen}. Choose a new time below — your current appointment stays booked until you confirm.`
            ),
            bookingWizardMessage({
              reason: keepDoctor
                ? `Reschedule with ${result.doctor_name}`
                : "I would like to reschedule with a different doctor",
              doctor_id: keepDoctor ? result.doctor_id : undefined,
              doctor_name: keepDoctor ? result.doctor_name : undefined,
              service_id: result.service_id || undefined,
              service_name: result.service_name || undefined,
              replaces_appointment_id: appointmentId,
            }),
          ]);
        } catch (err) {
          setMessages((prev) => [
            ...prev,
            systemErrorMessage(getApiErrorMessage(err, "Couldn't start rescheduling — please try again.")),
          ]);
        }
      })();
      return;
    }
  }

  function closeAll() {
    setOpen(false);
    setExpanded(false);
  }

  function handleStarter(msg: string) {
    void sendText(msg);
  }

  const emptyState = (
    <div className="flex flex-col gap-1">
      <SamplePromptChips
        items={samples}
        onSelect={(msg) => void sendText(msg)}
      />
      <div className="synapse-chat-msg flex gap-2.5">
        <RobotAvatar
          size="sm"
          className="mt-5 shrink-0 rounded-full bg-primary"
        />
        <div className="min-w-0 max-w-[85%]">
          <BotMetaRow name={`${displayName} Assistant`} time="Just now" />
          <div className="rounded-[18px] rounded-bl-md border border-border/80 bg-card px-3.5 py-2.5 text-sm leading-relaxed text-foreground shadow-sm">
            {greeting}
          </div>
        </div>
      </div>
      <StarterChips
        items={starters}
        onSelect={(msg) => handleStarter(msg)}
      />
    </div>
  );

  const chatBody = (
    <div className="relative flex min-h-0 flex-1 flex-col bg-background">
      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="h-full overflow-y-auto overscroll-contain scroll-smooth px-3 py-4 sm:px-4"
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
                assistantName={`${displayName} Assistant`}
                clinicSlug={canBook ? bookingClinicSlug : undefined}
                sessionToken={patientSessionToken() || widgetCtx.sessionToken}
                bookingWizardActive={
                  m.type === "booking_wizard" &&
                  m.id === activeWizardId &&
                  !dismissedWizards.has(m.id) &&
                  !m.payload?.completed
                }
                onBookingConfirmed={handleBookingConfirmed}
                onBookingDismiss={handleBookingDismiss}
                onBookingStarted={handleBookingStarted}
                onIdentityVerified={handleIdentityVerified}
                onSessionToken={rememberSessionToken}
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
                assistantName={`${displayName} Assistant`}
                typingHint={lastUserMessageRef.current}
              />
            ) : null}
          </div>
        </div>

        {showJumpDown ? (
          <button
            type="button"
            onClick={() => scrollToBottom(true)}
            className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-card px-3 py-1.5 text-[11px] font-medium text-foreground shadow-sm hover:bg-accent"
          >
            <ArrowDown className="size-3" />
            Latest
          </button>
        ) : null}
      </div>

      <ChatComposer
        value={input}
        onChange={setInput}
        onSubmit={() => void sendText(input)}
        onStop={stopGenerating}
        generating={typing}
        placeholder="Write a message"
      />
    </div>
  );

  const panel = (
    <div
      className={cn(
        "synapse-chat-panel relative flex flex-col overflow-hidden border border-border/70 bg-card shadow-[0_18px_50px_-18px_rgba(11,14,46,0.28)]",
        mode === "embedded" && "h-full min-h-[420px] w-full rounded-[18px]",
        mode === "widget" &&
          !expanded &&
          "h-[min(740px,calc(100dvh-5.5rem))] w-[min(560px,calc(100vw-1.25rem))] rounded-[18px]",
        mode === "widget" &&
          expanded &&
          "h-[min(80dvh,900px)] w-[min(78vw,1080px)] rounded-[18px]",
        mode === "widget" &&
          "max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:top-auto max-sm:h-[min(92dvh,820px)] max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:rounded-t-[18px]",
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
    return panel;
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
          className="pointer-events-auto flex size-14 items-center justify-center rounded-full shadow-lg ring-2 ring-background"
          aria-label={open ? "Close chat" : "Open Synapse Assistant"}
        >
          {open ? (
            <span className="flex size-full items-center justify-center rounded-full bg-primary text-primary-foreground">
              <X className="size-5" />
            </span>
          ) : (
            <RobotLauncherIcon className="rounded-full bg-primary" />
          )}
        </button>
      </div>
    </>
  );
}
