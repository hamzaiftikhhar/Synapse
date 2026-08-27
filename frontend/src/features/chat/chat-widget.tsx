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
  DateSeparator,
  clinicDayLabel,
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
  hydrateHistoryMessages,
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
import { chatService, widgetAppointmentsService, widgetService } from "@/services";
import { useAuth } from "@/providers/auth-provider";
import { useWidget, type AssistantMode } from "@/providers/widget-provider";
import type { AppointmentCardData, ChatMessage, TimeSlotData } from "@/types/chat";
import { waitForNaturalReplyPace } from "@/features/chat/natural-pace";
import {
  WidgetThemeProvider,
  appearanceFromConfig,
  widgetThemeStyle,
} from "@/features/chat/widget-theme";

const HISTORY_PAGE_SIZE = 50;

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

/**
 * Collapse-on-supersede (ROADMAP.md "Chat card collapse-on-supersede",
 * Phase 22) extended past booking_wizard: whenever a card's own action
 * has been used and a newer UI takes its place, the old card should stop
 * being a live, re-clickable prompt — same `payload.completed` convention
 * `sendText`'s own launchedWizard logic and handleBookingConfirmed
 * already use for booking_wizard messages.
 */
function markMessageCompleted(
  messages: ChatMessage[],
  messageId: string | undefined
): ChatMessage[] {
  if (!messageId) return messages;
  return messages.map((m) =>
    m.id === messageId
      ? { ...m, payload: { ...(m.payload ?? {}), completed: true } }
      : m
  );
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
  const staffMode =
    resolvedMode === "staff" || (useStaffApi && isAuthenticated);
  // Own copy of the patient chat session token. GlobalChatWidget used to sit
  // outside WidgetProvider, so setSessionToken was a no-op and cancel/reschedule
  // posted session_token:"" even after a successful verify+list. Keep a local
  // ref so appointment CRUD never depends solely on context wiring.
  const sessionTokenRef = useRef<string | null>(widgetCtx.sessionToken);
  useEffect(() => {
    if (widgetCtx.sessionToken) sessionTokenRef.current = widgetCtx.sessionToken;
  }, [widgetCtx.sessionToken]);
  // Staff/QA chat (dashboard's own "test the bot" widget) gets its own
  // session token, held only in memory — never routed through
  // widgetCtx.setSessionToken, which persists to sessionStorage under the
  // same clinic-scoped key the real patient-facing embed widget uses.
  // Without this separation, opening the dashboard's QA widget on a fresh
  // page load silently reused whatever session token a *previous* QA
  // sitting (hours or days earlier, in the same browser tab) had left in
  // sessionStorage — every new test message kept appending onto that old,
  // ever-growing ChatSession (visible in the staff Conversations tab),
  // while the widget's own message list, being fresh React state, always
  // rendered empty. A fresh page load now always starts a genuinely fresh
  // QA session, matching what the UI already showed; multi-turn continuity
  // (verify identity -> book) within one open widget/page sitting is
  // unaffected since this ref persists for the component's lifetime.
  const staffSessionTokenRef = useRef<string | null>(null);

  const rememberSessionToken = useCallback(
    (token: string | null | undefined) => {
      if (!token) return;
      if (staffMode) {
        staffSessionTokenRef.current = token;
        return;
      }
      sessionTokenRef.current = token;
      widgetCtx.setSessionToken(token);
    },
    [staffMode, widgetCtx.setSessionToken]
  );

  const patientSessionToken = useCallback((): string => {
    if (staffMode) return staffSessionTokenRef.current || "";
    return sessionTokenRef.current || widgetCtx.sessionToken || "";
  }, [staffMode, widgetCtx.sessionToken]);

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
  const applyClinicTheme = resolvedMode !== "marketing";
  const clinicAppearance = applyClinicTheme
    ? appearanceFromConfig(widgetConfig?.configuration?.widget)
    : null;
  const themeStyle = clinicAppearance ? widgetThemeStyle(clinicAppearance) : undefined;

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
  const [unreadCount, setUnreadCount] = useState(0);
  const [resuming, setResuming] = useState(false);
  const [hasMoreOlder, setHasMoreOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [dismissedWizards, setDismissedWizards] = useState<Set<string>>(
    () => new Set()
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const lastUserMessageRef = useRef("");
  const lastBookingMetaRef = useRef<Record<string, unknown> | null>(null);
  const requestIdRef = useRef(0);
  // Oldest sequence_number loaded so far — the cursor for the next older
  // page. Not component state: it never needs to trigger a render on its
  // own, only to be read at fetch time.
  const oldestCursorRef = useRef<number | null>(null);
  const resumeAttemptedRef = useRef(false);
  const prependAdjustRef = useRef<{ scrollHeight: number; scrollTop: number } | null>(
    null
  );
  const staffChat = useStaffChat();
  const patientChat = usePatientChat();
  const guestChat = useGuestChat();
  const marketingChat = useMarketingChat();
  const clinicTimezone = widgetConfig?.timezone || "UTC";
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
    setUnreadCount(0);
    setHasMoreOlder(false);
    oldestCursorRef.current = null;
    prevMessageCountRef.current = 0;
    stickToBottom.current = true;
    // Abandon the in-memory staff/QA session too — without this, "Restart"
    // only looked fresh (cleared messages client-side) while still posting
    // the old session_token, silently continuing the same server-side
    // ChatSession. See staffSessionTokenRef above.
    staffSessionTokenRef.current = null;
  }, []);

  // A super admin can enter a *different* clinic at any point without a full
  // page reload (same tab, no remount) — the effective tenant flips under
  // this same component instance. Without an explicit reset here, the
  // in-memory staff session token (and whatever messages are on screen)
  // would keep belonging to the clinic that was active when they were set,
  // even though every new message now targets a different clinic's tenant.
  // The backend's own `ChatSession.objects.get(clinic=clinic,
  // session_token=...)` lookup is already clinic-scoped so a stale token can
  // never leak another clinic's session, but leaving it unreset would still
  // mean a wasted lookup and a UI showing one clinic's transcript while
  // about to post into a different clinic's — reset proactively instead of
  // relying solely on that backend-side guard.
  const activeStaffTenant = staffMode
    ? getActiveTenant() || clinic?.slug || clinicSlug || null
    : null;
  const staffTenantRef = useRef(activeStaffTenant);
  useEffect(() => {
    if (!staffMode) return;
    if (staffTenantRef.current === activeStaffTenant) return;
    staffTenantRef.current = activeStaffTenant;
    resetChat();
  }, [staffMode, activeStaffTenant, resetChat]);

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
      setUnreadCount(0);
    },
    [expanded]
  );

  // Staff/QA resume — the equivalent of the anonymous-visitor resume
  // effect below, but keyed by the staff JWT's own identity (this user +
  // this clinic) instead of a browser-stored visitor id, since staff
  // sessions were never wired into that mechanism at all: opening the
  // dashboard's chat widget used to always start blank, even though the
  // conversation was sitting right there in the Conversations tab. Runs
  // once per distinct tenant this component instance sees, not once ever
  // — a super admin entering a different clinic mid-session must get that
  // clinic's own resume attempt, not silently skip it because *some*
  // clinic was already resumed earlier in this tab.
  const staffResumedTenantRef = useRef<string | null>(null);
  useEffect(() => {
    if (!open || !staffMode || !activeStaffTenant) return;
    if (staffResumedTenantRef.current === activeStaffTenant) return;
    staffResumedTenantRef.current = activeStaffTenant;

    setResuming(true);
    void (async () => {
      try {
        const res = await chatService.resumeStaffChat();
        if (res.session_token) rememberSessionToken(res.session_token);
        if (res.messages.length) {
          oldestCursorRef.current = res.messages[0].sequence_number;
          setHasMoreOlder(res.has_more);
          stickToBottom.current = true;
          setMessages(hydrateHistoryMessages(res.messages));
          requestAnimationFrame(() => scrollToBottom(false));
        }
      } catch {
        // A failed resume must never block the widget.
      } finally {
        setResuming(false);
      }
    })();
  }, [open, staffMode, activeStaffTenant, rememberSessionToken, scrollToBottom]);

  // Set right before a prepend's setMessages call so the effects below
  // skip both auto-scroll-to-bottom and the unread counter for it — an
  // older page loading in is never "new", and its scroll handling is a
  // position *restore*, not a jump.
  const isPrependingRef = useRef(false);
  const prevMessageCountRef = useRef(0);

  useEffect(() => {
    const grew = messages.length > prevMessageCountRef.current;
    prevMessageCountRef.current = messages.length;
    if (isPrependingRef.current) {
      isPrependingRef.current = false;
      return;
    }
    if (stickToBottom.current) {
      scrollToBottom(messages.length > 0);
    } else if (grew) {
      // No live push channel exists in this app today (request/response
      // only), so in practice this only ever fires for the rare case of
      // the user scrolling away mid-flight — kept correct regardless.
      setUnreadCount((n) => n + 1);
    }
  }, [messages, typing, scrollToBottom]);

  // Restores the reader's exact visual position after an older page is
  // prepended — prepending pushes everything down by the new content's
  // height, so without this the browser's constant scrollTop produces a
  // visible jump.
  useEffect(() => {
    const pending = prependAdjustRef.current;
    if (!pending) return;
    prependAdjustRef.current = null;
    const el = scrollRef.current;
    if (!el) return;
    const delta = el.scrollHeight - pending.scrollHeight;
    el.scrollTop = pending.scrollTop + delta;
  }, [messages]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const wasStuck = stickToBottom.current;
    stickToBottom.current = distance < 64;
    if (stickToBottom.current && !wasStuck) setUnreadCount(0);
    setShowJumpDown(
      !stickToBottom.current && el.scrollHeight > el.clientHeight + 80
    );
  }

  const loadOlderMessages = useCallback(async () => {
    const sessionToken = patientSessionToken();
    const cursor = oldestCursorRef.current;
    if (!sessionToken || !clinicSlug || cursor == null) return;
    if (loadingOlder || !hasMoreOlder) return;
    setLoadingOlder(true);
    const el = scrollRef.current;
    if (el) {
      prependAdjustRef.current = { scrollHeight: el.scrollHeight, scrollTop: el.scrollTop };
    }
    try {
      const page = await widgetService.getMessages(
        sessionToken,
        clinicSlug,
        { before: cursor, limit: HISTORY_PAGE_SIZE },
        widgetCtx.visitorId
      );
      if (page.messages.length) {
        oldestCursorRef.current = page.messages[0].sequence_number;
        const older = hydrateHistoryMessages(page.messages);
        isPrependingRef.current = true;
        setMessages((prev) => [...older, ...prev]);
      } else {
        prependAdjustRef.current = null;
      }
      setHasMoreOlder(page.has_more);
    } catch {
      prependAdjustRef.current = null;
      // Leave hasMoreOlder as-is — scrolling up again retries naturally.
    } finally {
      setLoadingOlder(false);
    }
  }, [clinicSlug, hasMoreOlder, loadingOlder, patientSessionToken, widgetCtx.visitorId]);

  useEffect(() => {
    if (!open || !hasMoreOlder) return;
    const sentinel = topSentinelRef.current;
    const root = scrollRef.current;
    if (!sentinel || !root) return;

    // Resume's initial jump-to-bottom (`el.scrollTo({behavior:"auto"})`)
    // does not update scrollTop synchronously — the browser can defer the
    // actual scroll commit by an unpredictable number of frames (worse
    // under load), and during that unsettled window either a raw
    // scrollTop snapshot or a same-tick 'scroll' event can transiently
    // read as "not at the bottom". Either one alone can wrongly treat the
    // sentinel as "the user scrolled up" and fire an unwanted extra
    // older-page fetch on every resume with more than one page of
    // history, even though nothing was scrolled. Two independent guards:
    // a fixed delay before the observer is even attached (gives scroll
    // commit + any transient scroll events time to fully settle first),
    // plus stickToBottom.current (only ever flips to false from *this*
    // container's own onScroll handler once things have settled, so it
    // reflects the real, current state rather than a stale snapshot).
    let observer: IntersectionObserver | null = null;
    const timeoutId = setTimeout(() => {
      observer = new IntersectionObserver(
        (entries) => {
          if (entries[0]?.isIntersecting && !stickToBottom.current) {
            void loadOlderMessages();
          }
        },
        { root, rootMargin: "200px 0px 0px 0px" }
      );
      observer.observe(sentinel);
    }, 500);
    return () => {
      clearTimeout(timeoutId);
      observer?.disconnect();
    };
  }, [open, hasMoreOlder, loadOlderMessages]);

  // Case A/B from the approved plan: opening the widget resumes a known
  // visitor's most recent conversation; a first-time browser (no stored
  // visitor id) never calls the backend at all — resume is a pure read
  // whose only reason to exist is finding *something already there*.
  useEffect(() => {
    if (!open) return;
    if (resolvedMode !== "clinic" || !clinicSlug) return;
    if (resumeAttemptedRef.current) return;
    if (!widgetCtx.visitorId) return;
    // Deliberately no per-invocation `cancelled` cleanup flag here (unlike
    // most data-fetching effects) — resumeAttemptedRef above already
    // guarantees this async work starts at most once for the widget's
    // whole lifetime, which is exactly what broke when this used to also
    // track `cancelled`: React's dev-mode Strict Mode double-invoke
    // (mount -> cleanup -> remount) set `cancelled = true` from the first
    // invocation's cleanup *before* its own `await` resolved, while the
    // ref had already blocked the second invocation from retrying — the
    // one fetch that actually completed then discarded its own result and
    // never cleared `resuming`, leaving the loading skeleton stuck
    // forever. Caught only by real browser testing in dev mode; tsc/build
    // never exercise this lifecycle at all.
    resumeAttemptedRef.current = true;

    setResuming(true);
    void (async () => {
      try {
        const res = await widgetService.resume(clinicSlug, widgetCtx.visitorId);
        if (res.visitor_id) widgetCtx.setVisitorId(res.visitor_id);
        if (res.session_token) rememberSessionToken(res.session_token);
        if (res.messages.length) {
          oldestCursorRef.current = res.messages[0].sequence_number;
          setHasMoreOlder(res.has_more);
          stickToBottom.current = true;
          setMessages(hydrateHistoryMessages(res.messages));
          requestAnimationFrame(() => scrollToBottom(false));
        }
      } catch {
        // A failed resume must never block the widget — it just falls
        // back to the same empty/greeting state a first-time visitor sees.
      } finally {
        setResuming(false);
      }
    })();
  }, [
    open,
    resolvedMode,
    clinicSlug,
    widgetCtx.visitorId,
    widgetCtx,
    rememberSessionToken,
    scrollToBottom,
  ]);

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
            visitor_id: widgetCtx.visitorId,
          });
          const token = res.meta?.session_token;
          if (typeof token === "string") rememberSessionToken(token);
          // First real message is what creates the ChatVisitor server-side
          // (opening the widget never does) — this is where the frontend
          // first learns its own id and persists it going forward.
          const visitorId = res.meta?.visitor_id;
          if (typeof visitorId === "string" && visitorId !== widgetCtx.visitorId) {
            widgetCtx.setVisitorId(visitorId);
          }
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
        const launchedWizard = parsed.messages.some((m) => m.type === "booking_wizard");
        setMessages((prev) => {
          // A launching wizard supersedes not just an older wizard, but
          // any other still-open "what do you want to do" card too — a
          // reply can bundle an empty appointments/verify_identity card
          // *with* a wizard launch in the very same turn (e.g. "no
          // appointments — want to book one?"), which used to leave the
          // older/bundled card fully interactive underneath the wizard.
          const base = launchedWizard
            ? prev.map((m) =>
                (m.type === "booking_wizard" ||
                  m.type === "appointments" ||
                  m.type === "verify_identity") &&
                !m.payload?.completed
                  ? { ...m, payload: { ...(m.payload ?? {}), completed: true } }
                  : m
              )
            : prev;
          // Same-turn bundling: an appointments/verify_identity card that
          // arrives *alongside* the wizard in this exact reply must start
          // out already collapsed, never render live even for a frame.
          const incoming = launchedWizard
            ? parsed.messages.map((m) =>
                m.type === "appointments" || m.type === "verify_identity"
                  ? { ...m, payload: { ...(m.payload ?? {}), completed: true } }
                  : m
              )
            : parsed.messages;
          const next = [...base, ...incoming];
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
      dismissedWizards,
      patientSessionToken,
      rememberSessionToken,
      widgetCtx,
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

  function handleIdentityVerified(messageId: string, sessionToken: string) {
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
          ...markMessageCompleted(prev, messageId),
          {
            id: uid("appt"),
            role: "assistant",
            type: "appointments",
            createdAt: new Date().toISOString(),
            payload: { appointments: result.appointments },
          },
        ]);
      } catch (err) {
        // Verification itself still succeeded even though this fetch
        // failed — the verify card must still collapse either way.
        setMessages((prev) => [
          ...markMessageCompleted(prev, messageId),
          systemErrorMessage(
            getApiErrorMessage(err, "Couldn't load your appointments — please try again.")
          ),
        ]);
      }
    })();
  }

  function handleBookingConfirmed() {
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
    // The wizard mounts with an empty "Preparing your booking…" placeholder,
    // then grows once start() resolves — the auto-scroll that fired when the
    // (still-empty) card was first added already settled on the shorter
    // height, so the sudden growth leaves the view stuck mid-card. Re-settle
    // once the browser has painted the now-loaded content, and only if the
    // patient hasn't deliberately scrolled away to re-read something.
    if (stickToBottom.current) {
      requestAnimationFrame(() => scrollToBottom(true));
    }
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
        messageId?: string;
      };
      setMessages((prev) => [
        ...markMessageCompleted(prev, doctor.messageId),
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
      const slot = data as TimeSlotData & { messageId?: string };
      if (!slot.start || !slot.doctor_id) {
        setMessages((prev) => [
          ...markMessageCompleted(prev, slot.messageId),
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
        ...markMessageCompleted(prev, slot.messageId),
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
        messageId?: string;
      };
      // The empty-appointments-card "Book a New Appointment" button (the
      // only caller that ever sets messageId) carries no doctor/slot/
      // service pick of its own — nothing precise to lose by routing it
      // through a real message, matching every other bare "Book
      // Appointment" entry point in this app (runBackendAction's
      // launch_booking, below). Also collapses the card that triggered
      // it. Other callers (e.g. insurance-card.tsx, after picking a
      // plan) still carry structured data worth keeping local — untouched.
      if (payload?.messageId) {
        setMessages((prev) => markMessageCompleted(prev, payload.messageId));
        void sendText("I would like to book an appointment");
        return;
      }
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
        messageId?: string;
      };
      setMessages((prev) => [
        ...markMessageCompleted(prev, service.messageId),
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

  const renderItems = useMemo(() => {
    const items: (
      | { kind: "separator"; key: string; label: string }
      | { kind: "message"; message: ChatMessage }
    )[] = [];
    let lastDay: string | null = null;
    for (const m of messages) {
      const day = clinicDayLabel(m.createdAt, clinicTimezone);
      if (day !== lastDay) {
        items.push({ kind: "separator", key: `sep_${m.id}`, label: day });
        lastDay = day;
      }
      items.push({ kind: "message", message: m });
    }
    return items;
  }, [messages, clinicTimezone]);

  const resumingSkeleton = (
    <div className="synapse-chat-msg flex gap-2.5" aria-hidden>
      <RobotAvatar size="sm" className="mt-5 shrink-0 rounded-full bg-primary" />
      <div className="min-w-0 max-w-[85%] flex-1">
        <BotMetaRow name={`${displayName} Assistant`} />
        <div className="synapse-chat-bubble synapse-chat-bubble--bot space-y-2 border border-border/80 bg-card px-3.5 py-3 shadow-sm">
          <div className="synapse-chat-skeleton h-2.5 w-[88%] rounded-full" />
          <div className="synapse-chat-skeleton h-2.5 w-[64%] rounded-full" />
          <div className="synapse-chat-skeleton h-2.5 w-[76%] rounded-full" />
        </div>
      </div>
    </div>
  );

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
          <div className="synapse-chat-bubble synapse-chat-bubble--bot border border-border/80 bg-card px-3.5 py-2.5 text-sm leading-relaxed text-foreground shadow-sm">
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
            {messages.length === 0 && resuming ? resumingSkeleton : null}
            {messages.length === 0 && !typing && !resuming ? emptyState : null}
            {hasMoreOlder ? (
              <div ref={topSentinelRef} className="flex justify-center py-1" aria-hidden>
                {loadingOlder ? (
                  <div className="synapse-chat-skeleton h-2 w-24 rounded-full" />
                ) : null}
              </div>
            ) : null}
            {renderItems.map((item) =>
              item.kind === "separator" ? (
                <DateSeparator key={item.key} label={item.label} />
              ) : (
                <MessageRenderer
                  key={item.message.id}
                  message={item.message}
                  onAction={handleAction}
                  onBackendAction={handleBackendAction}
                  showContextActions={item.message.id === lastActionMessageId && !typing}
                  assistantName={`${displayName} Assistant`}
                  clinicSlug={canBook ? bookingClinicSlug : undefined}
                  // patientSessionToken() already falls back to
                  // widgetCtx.sessionToken internally for non-staff modes —
                  // an extra `|| widgetCtx.sessionToken` here would leak the
                  // real patient-facing token into staff mode's identity
                  // cards whenever staffSessionTokenRef was still empty.
                  sessionToken={patientSessionToken()}
                  bookingWizardActive={
                    item.message.type === "booking_wizard" &&
                    item.message.id === activeWizardId &&
                    !dismissedWizards.has(item.message.id) &&
                    !item.message.payload?.completed
                  }
                  onBookingConfirmed={handleBookingConfirmed}
                  onBookingDismiss={handleBookingDismiss}
                  onBookingStarted={handleBookingStarted}
                  onIdentityVerified={handleIdentityVerified}
                  onSessionToken={rememberSessionToken}
                />
              )
            )}
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
            aria-label={
              unreadCount > 0 ? `${unreadCount} new message${unreadCount === 1 ? "" : "s"} — jump to latest` : "Jump to latest"
            }
            className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-border/80 bg-card py-1.5 pl-3 pr-3 text-[11px] font-medium text-foreground shadow-md transition-shadow hover:shadow-lg hover:bg-accent"
          >
            <ArrowDown className="size-3" />
            Latest
            {unreadCount > 0 ? (
              <span className="ml-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-none text-primary-foreground">
                {unreadCount > 9 ? "9+" : unreadCount}
              </span>
            ) : null}
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
        mode === "embedded" && "h-full min-h-[420px] w-full",
        mode === "widget" &&
          !expanded &&
          "h-[min(740px,calc(100dvh-5.5rem))] w-[min(560px,calc(100vw-1.25rem))]",
        mode === "widget" &&
          expanded &&
          "h-[min(80dvh,900px)] w-[min(78vw,1080px)]",
        mode === "widget" &&
          "max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:top-auto max-sm:h-[min(92dvh,820px)] max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none",
        expanded &&
          mode === "widget" &&
          "max-sm:inset-0 max-sm:h-[100dvh] max-sm:rounded-none",
        className
      )}
      style={themeStyle}
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
      <WidgetThemeProvider appearance={clinicAppearance}>{panel}</WidgetThemeProvider>
    );
  }

  return (
    <WidgetThemeProvider appearance={clinicAppearance}>
      {open && expanded ? (
        <div
          className="pointer-events-auto fixed inset-0 z-[55] bg-black/20"
          onClick={() => setExpanded(false)}
          aria-hidden
        />
      ) : null}

      <div
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-end p-3 sm:inset-x-auto sm:right-5 sm:bottom-5 sm:p-0"
        style={themeStyle}
      >
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
          className="pointer-events-auto flex size-14 items-center justify-center overflow-hidden rounded-full shadow-lg ring-2 ring-black/10"
          aria-label={open ? "Close chat" : "Open Synapse Assistant"}
        >
          {open ? (
            <span className="flex size-full items-center justify-center rounded-full bg-primary text-primary-foreground">
              <X className="size-5" />
            </span>
          ) : (
            <RobotLauncherIcon className="rounded-full" />
          )}
        </button>
      </div>
    </WidgetThemeProvider>
  );
}
