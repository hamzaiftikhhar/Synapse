import type { ChatMessageResponse } from "@/types/api";
import type { ChatMessage } from "@/types/chat";
import type { BackendAction } from "./types";

export const CONNECTION_ERROR =
  "Unable to connect to the clinic assistant. Please try again.";

export function uid(prefix = "m") {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

export type ParsedChatResponse = {
  messages: ChatMessage[];
  /** Contextual chips for the latest assistant turn (Homey-style, under the reply). */
  contextualActions: BackendAction[];
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
) {
  if (Array.isArray(meta.cards) && meta.cards.length) {
    messages.push({
      id: uid("cards"),
      role,
      type: "cards",
      createdAt: now,
      payload: { cards: meta.cards },
    });
  }

  // Homey-style: embed wizard when backend sets booking.launch
  if (meta.booking && typeof meta.booking === "object") {
    const booking = meta.booking as Record<string, unknown>;
    if (booking.launch) {
      messages.push({
        id: uid("booking_wizard"),
        role,
        type: "booking_wizard",
        createdAt: now,
        payload: booking,
      });
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

  if (Array.isArray(meta.doctors) && meta.doctors.length) {
    messages.push({
      id: uid("docs"),
      role,
      type: "doctor_cards",
      createdAt: now,
      payload: { doctors: meta.doctors },
    });
  }

  if (Array.isArray(meta.services) && meta.services.length) {
    messages.push({
      id: uid("svc"),
      role,
      type: "service_cards",
      createdAt: now,
      payload: { services: meta.services },
    });
  }

  if (Array.isArray(meta.insurance) && meta.insurance.length) {
    messages.push({
      id: uid("ins"),
      role,
      type: "insurance_cards",
      createdAt: now,
      payload: { plans: meta.insurance },
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

  if (Array.isArray(meta.specialties) && meta.specialties.length) {
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

  if (Array.isArray(meta.time_slots) && meta.time_slots.length) {
    messages.push({
      id: uid("slots"),
      role,
      type: "time_slots",
      createdAt: now,
      payload: { slots: meta.time_slots },
    });
  }

  if (meta.location && typeof meta.location === "object") {
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

  if (res.response) {
    messages.push({
      id: uid("text"),
      role,
      type: "text",
      content: res.response,
      createdAt: now,
    });
  }

  appendMetaComponents(messages, meta, role, now);
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
