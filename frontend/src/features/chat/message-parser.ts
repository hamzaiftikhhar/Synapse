import type { ChatMessageHistoryOut, ChatMessageResponse } from "@/types/api";
import type { ChatMessage } from "@/types/chat";
import type { BackendAction } from "./types";

export const CONNECTION_ERROR =
  "Unable to connect to the clinic assistant. Please try again.";

export const CLINIC_CONTEXT_ERROR =
  "No clinic selected. Enter a clinic from Platform → Clinics, then try again.";

export const CHAT_TIMEOUT_ERROR =
  "That took too long. Please try again — shorter questions usually respond faster.";

export function uid(prefix = "m") {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

export type BookingUpdate = {
  bookingId: string;
  patch: Record<string, unknown>;
};

export type ParsedChatResponse = {
  messages: ChatMessage[];
  /** Contextual chips for the latest assistant turn (Homey-style, under the reply). */
  contextualActions: BackendAction[];
  /**
   * Present when a booking is already in progress (backend set
   * `booking.launch=false` + a `booking_id`) — merge into the existing
   * booking_wizard message instead of minting a new one.
   */
  bookingUpdate?: BookingUpdate | null;
};

function mapMetaMessage(
  m: Record<string, unknown>,
  index: number,
  role: ChatMessage["role"]
): ChatMessage {
  return {
    id: typeof m.id === "string" ? m.id : uid(`meta_${index}`),
    role: (m.role as ChatMessage["role"]) || role,
    type: (m.type as ChatMessage["type"]) || "text",
    content: typeof m.content === "string" ? m.content : undefined,
    createdAt:
      typeof m.createdAt === "string"
        ? m.createdAt
        : new Date().toISOString(),
    payload: (m.payload as Record<string, unknown>) || undefined,
  };
}

function parseActions(value: unknown): BackendAction[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (a): a is BackendAction =>
      Boolean(a) &&
      typeof a === "object" &&
      typeof (a as BackendAction).id === "string" &&
      typeof (a as BackendAction).label === "string"
  );
}

function appendMetaComponents(
  messages: ChatMessage[],
  meta: Record<string, unknown>,
  role: ChatMessage["role"],
  now: string
): BookingUpdate | null {
  let bookingUpdate: BookingUpdate | null = null;
  const primary = typeof meta.primary_component === "string" ? meta.primary_component : null;

  const allow = (component: string) => !primary || primary === component;

  if (Array.isArray(meta.cards) && meta.cards.length) {
    messages.push({
      id: uid("cards"),
      role,
      type: "cards",
      createdAt: now,
      payload: { cards: meta.cards },
    });
  }

  // Persisted by BookingService.confirm() (apps/chatbot/services/
  // message_history.py::persist_confirmation_message) as its own
  // ChatMessage — the one durable trace of a completed booking, since
  // confirm() is a separate API call from the normal chat pipeline and
  // nothing else would ever save this. Renders via the existing (until
  // now unused) ConfirmationCard.
  if (meta.confirmation && typeof meta.confirmation === "object") {
    const confirmation = meta.confirmation as Record<string, unknown>;
    messages.push({
      id: uid("confirmation"),
      role,
      type: "confirmation",
      content: typeof confirmation.content === "string" ? confirmation.content : undefined,
      createdAt: now,
      payload: confirmation,
    });
  }

  // Homey-style: embed wizard when backend sets booking.launch. When a
  // booking is already in progress (launch:false + booking_id), don't mint a
  // second wizard card — merge into the existing one instead (fixes the
  // restart-on-every-turn bug).
  if (meta.booking && typeof meta.booking === "object" && allow("booking")) {
    const booking = meta.booking as Record<string, unknown>;
    if (booking.launch) {
      messages.push({
        id: uid("booking_wizard"),
        role,
        type: "booking_wizard",
        createdAt: now,
        payload: booking,
      });
    } else if (typeof booking.booking_id === "string" && booking.booking_id) {
      bookingUpdate = { bookingId: booking.booking_id, patch: booking };
    } else {
      messages.push({
        id: uid("booking"),
        role,
        type: "appointment_form",
        createdAt: now,
        payload: booking,
      });
    }
  }

  if (Array.isArray(meta.doctors) && meta.doctors.length && allow("doctors")) {
    messages.push({
      id: uid("docs"),
      role,
      type: "doctor_cards",
      createdAt: now,
      payload: { doctors: meta.doctors },
    });
  }

  if (Array.isArray(meta.services) && meta.services.length && allow("services")) {
    messages.push({
      id: uid("svc"),
      role,
      type: "service_cards",
      createdAt: now,
      payload: { services: meta.services },
    });
  }

  if (Array.isArray(meta.insurance) && meta.insurance.length && allow("insurance")) {
    messages.push({
      id: uid("ins"),
      role,
      type: "insurance_cards",
      createdAt: now,
      payload: { plans: meta.insurance },
    });
  }

  if (Array.isArray(meta.appointments) && allow("appointments")) {
    messages.push({
      id: uid("appt"),
      role,
      type: "appointments",
      createdAt: now,
      payload: { appointments: meta.appointments },
    });
  }

  if (meta.verify_identity && allow("verify_identity")) {
    messages.push({
      id: uid("verify"),
      role,
      type: "verify_identity",
      createdAt: now,
    });
  }

  if (Array.isArray(meta.hours) && meta.hours.length) {
    messages.push({
      id: uid("hours"),
      role,
      type: "cards",
      createdAt: now,
      payload: {
        cards: (meta.hours as Record<string, unknown>[]).map((h) => ({
          title: h.day,
          description: h.is_closed
            ? "Closed"
            : `${h.open_time ?? ""} – ${h.close_time ?? ""}`,
        })),
      },
    });
  }

  const priority = String(meta.ui_priority || "").toUpperCase();
  const suppressExtra =
    priority === "NONE" || priority === "BOOKING" || priority === "EMERGENCY";

  if (Array.isArray(meta.specialties) && meta.specialties.length && !suppressExtra) {
    // Prefer inline wizard over duplicating specialty cards when embedding
    const booking = meta.booking as Record<string, unknown> | undefined;
    if (!(booking && booking.launch)) {
      messages.push({
        id: uid("spec"),
        role,
        type: "cards",
        createdAt: now,
        payload: {
          cards: (meta.specialties as Record<string, unknown>[]).map((s) => ({
            title: s.name,
            description: s.description || `${s.doctor_count ?? 0} doctors`,
            action: s.select_message,
            id: s.id,
          })),
        },
      });
    }
  }

  if (Array.isArray(meta.time_slots) && meta.time_slots.length && allow("time_slots")) {
    messages.push({
      id: uid("slots"),
      role,
      type: "time_slots",
      createdAt: now,
      payload: { slots: meta.time_slots },
    });
  }

  if (meta.location && typeof meta.location === "object" && allow("location")) {
    messages.push({
      id: uid("loc"),
      role,
      type: "clinic_location",
      createdAt: now,
      payload: meta.location as Record<string, unknown>,
    });
  }

  if (Array.isArray(meta.buttons) && meta.buttons.length) {
    const booking = meta.booking as Record<string, unknown> | undefined;
    // Wizard already embeds — skip redundant Start Booking buttons
    if (!(booking && booking.launch)) {
      messages.push({
        id: uid("btn"),
        role,
        type: "buttons",
        createdAt: now,
        payload: { buttons: meta.buttons },
      });
    }
  }

  if (Array.isArray(meta.quick_replies) && meta.quick_replies.length) {
    messages.push({
      id: uid("qr"),
      role,
      type: "quick_replies",
      createdAt: now,
      payload: { replies: meta.quick_replies },
    });
  }

  return bookingUpdate;
}

function attachActionsToLastAssistantMessage(
  messages: ChatMessage[],
  actions: BackendAction[]
) {
  if (!actions.length) return;
  // Put chips after tool UIs (booking wizard, cards, etc.), not between text and tools
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === "assistant" && m.type !== "system" && m.type !== "typing") {
      m.payload = { ...(m.payload ?? {}), actions };
      return;
    }
  }
}

export function parseChatResponse(
  res: ChatMessageResponse,
  role: "assistant" = "assistant"
): ParsedChatResponse {
  const now = new Date().toISOString();
  const meta = res.meta ?? {};
  // Prefer turn-specific `actions`; fall back to `persistent_actions` from backend.
  const contextualActions = parseActions(
    meta.actions ?? meta.persistent_actions
  );

  if (Array.isArray(meta.messages)) {
    const messages = (meta.messages as Record<string, unknown>[]).map((m, i) =>
      mapMetaMessage(m, i, role)
    );
    attachActionsToLastAssistantMessage(messages, contextualActions);
    if (res.safety_message) {
      messages.push({
        id: uid("safe"),
        role: "system",
        type: "system",
        content: res.safety_message,
        createdAt: now,
      });
    }
    return { messages, contextualActions };
  }

  const messages: ChatMessage[] = [];

  // Skip the plain-text bubble when a confirmation card is also about to
  // render (below) — it says the same thing in a clearer format; res.response
  // still stays meaningful on the raw ChatMessage.content field itself
  // (e.g. for the staff conversations list preview), just not duplicated
  // as a second bubble here.
  if (res.response && !meta.confirmation) {
    messages.push({
      id: uid("text"),
      role,
      type: "text",
      content: res.response,
      createdAt: now,
    });
  }

  const bookingUpdate = appendMetaComponents(messages, meta, role, now);
  attachActionsToLastAssistantMessage(messages, contextualActions);

  if (res.safety_message) {
    messages.push({
      id: uid("safe"),
      role: "system",
      type: "system",
      content: res.safety_message,
      createdAt: now,
    });
  }

  return { messages, contextualActions, bookingUpdate };
}

export function userTextMessage(content: string): ChatMessage {
  return {
    id: uid("user"),
    role: "user",
    type: "text",
    content,
    createdAt: new Date().toISOString(),
  };
}

export function systemErrorMessage(content: string): ChatMessage {
  return {
    id: uid("err"),
    role: "system",
    type: "system",
    content,
    createdAt: new Date().toISOString(),
  };
}

/** Local success/status notice — e.g. after cancelling an appointment. */
export function systemNoticeMessage(content: string): ChatMessage {
  return {
    id: uid("notice"),
    role: "system",
    type: "system",
    content,
    createdAt: new Date().toISOString(),
  };
}

/**
 * Locally-synthesized card for "Check Insurance" when a plan is already
 * selected — no backend round-trip, no re-asking a question we already
 * answered. payload.plans is empty on purpose: InsuranceCards' selected
 * branch never reads it, it renders straight from useSelectedInsurance.
 */
export function insuranceSelectedMessage(): ChatMessage {
  return {
    id: uid("ins"),
    role: "assistant",
    type: "insurance_cards",
    createdAt: new Date().toISOString(),
    payload: { plans: [] },
  };
}

/** Launch the booking wizard in-chat without a new NLU round-trip. */
export function bookingWizardMessage(
  payload: Record<string, unknown> = {}
): ChatMessage {
  return {
    id: uid("booking_wizard"),
    role: "assistant",
    type: "booking_wizard",
    createdAt: new Date().toISOString(),
    payload: {
      launch: true,
      reason: "I would like to book an appointment",
      ...payload,
    },
  };
}

const EMPTY_TIMINGS = {
  nlu_ms: 0,
  decision_ms: 0,
  sql_ms: 0,
  vector_ms: 0,
  llm_ms: 0,
  fast_path_ms: 0,
  total_ms: 0,
};

/**
 * Reconstructs one persisted row from /chat/resume or the pagination
 * endpoint into the same ChatMessage shape a live turn produces —
 * deliberately reuses parseChatResponse rather than a second parallel
 * mapper, so a historical doctor-cards/booking-wizard/time-slots turn
 * renders through the exact same MessageRenderer path as a live one.
 * Assistant rows carry the same `meta` dict the live response sent as
 * `res.meta` (persisted by the backend for exactly this purpose); user
 * rows are always plain text (the only thing a user ever sends).
 */
function hydrateHistoryRow(row: ChatMessageHistoryOut): ChatMessage[] {
  if (row.role === "user") {
    return [{ ...userTextMessage(row.content), createdAt: row.created_at }];
  }

  if (row.role === "assistant") {
    const fakeResponse: ChatMessageResponse = {
      response: row.content,
      route: "",
      intent: "",
      confidence: 0,
      needs_sql: false,
      needs_vector: false,
      needs_llm: false,
      safety_message: null,
      timings: EMPTY_TIMINGS,
      meta: row.metadata || {},
    };
    const { messages } = parseChatResponse(fakeResponse);
    return messages.map((m) => {
      const base = { ...m, createdAt: row.created_at };
      // A historical booking_wizard must never mount live and interactive
      // — BookingWizard.start() would fire again on a stale, possibly
      // long-expired hold/booking draft the moment it's scrolled into
      // view, with no click needed at all. Its own confirmation (if the
      // booking was actually completed) shows separately as its own
      // persisted `confirmation` message instead — see
      // persist_confirmation_message on the backend.
      if (base.type === "booking_wizard") {
        return { ...base, payload: { ...(base.payload ?? {}), completed: true } };
      }
      // Same reasoning for a past appointments list: Cancel/Reschedule
      // acting on a real appointment must be a deliberate action taken
      // from the *current* state of that appointment, never a stray
      // click replaying an old turn's snapshot of it.
      if (base.type === "appointments") {
        return { ...base, payload: { ...(base.payload ?? {}), readOnly: true } };
      }
      return base;
    });
  }

  // system/tool rows — no live path ever produces these today, but handle
  // them as a plain system note rather than silently dropping the turn.
  return [
    {
      id: uid("hist_sys"),
      role: "system",
      type: "system",
      content: row.content,
      createdAt: row.created_at,
    },
  ];
}

/** Oldest-first page of persisted rows -> the same ChatMessage[] shape the
 * live chat state already uses. Caller is responsible for prepending vs.
 * replacing `messages` state — this is a pure mapper, no side effects. */
export function hydrateHistoryMessages(rows: ChatMessageHistoryOut[]): ChatMessage[] {
  return rows.flatMap(hydrateHistoryRow);
}
