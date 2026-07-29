import type { ChatMessageResponse } from "@/types/api";
import type { ChatMessage, MainMenuItem } from "@/types/chat";

export function uid(prefix = "m") {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

export const MAIN_MENU_ITEMS: MainMenuItem[] = [
  {
    id: "book",
    label: "Book Appointment",
    description: "Pick a doctor, date & time",
    prompt: "I want to book an appointment",
    icon: "Calendar",
  },
  {
    id: "doctor",
    label: "Find a Doctor",
    description: "Browse providers & specialties",
    prompt: "Help me find a doctor",
    icon: "Stethoscope",
  },
  {
    id: "services",
    label: "Services",
    description: "What we offer & visit types",
    prompt: "What services do you offer?",
    icon: "BriefcaseMedical",
  },
  {
    id: "insurance",
    label: "Insurance",
    description: "Accepted plans & coverage",
    prompt: "What insurance do you accept?",
    icon: "Shield",
  },
  {
    id: "hours",
    label: "Clinic Hours",
    description: "Open days and times",
    prompt: "What are your clinic hours?",
    icon: "Clock",
  },
  {
    id: "location",
    label: "Location",
    description: "Address & directions",
    prompt: "Where is the clinic located?",
    icon: "MapPin",
  },
  {
    id: "contact",
    label: "Contact",
    description: "Phone, email & front desk",
    prompt: "How can I contact the clinic?",
    icon: "Phone",
  },
  {
    id: "faq",
    label: "FAQ",
    description: "Common patient questions",
    prompt: "What are frequently asked questions?",
    icon: "CircleHelp",
  },
];

export function createWelcomeMessages(clinicName = "our clinic"): ChatMessage[] {
  const now = new Date().toISOString();
  return [
    {
      id: uid("welcome"),
      role: "assistant",
      type: "text",
      content: `Hi — welcome to ${clinicName}. How can I help you today?`,
      createdAt: now,
    },
    {
      id: uid("menu"),
      role: "assistant",
      type: "main_menu",
      createdAt: now,
      payload: { items: MAIN_MENU_ITEMS },
    },
  ];
}

export function parseChatResponse(
  res: ChatMessageResponse,
  role: "assistant" = "assistant"
): ChatMessage[] {
  const now = new Date().toISOString();
  const meta = res.meta ?? {};

  if (Array.isArray(meta.messages)) {
    return (meta.messages as Record<string, unknown>[]).map((m, i) => ({
      id: uid(`meta_${i}`),
      role: (m.role as ChatMessage["role"]) || role,
      type: (m.type as ChatMessage["type"]) || "text",
      content: typeof m.content === "string" ? m.content : undefined,
      createdAt: now,
      payload: (m.payload as Record<string, unknown>) || undefined,
    }));
  }

  const messages: ChatMessage[] = [
    {
      id: uid("text"),
      role,
      type: "text",
      content: res.response,
      createdAt: now,
      payload: {
        intent: res.intent,
        route: res.route,
        confidence: res.confidence,
      },
    },
  ];

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
  if (Array.isArray(meta.quick_replies) && meta.quick_replies.length) {
    messages.push({
      id: uid("qr"),
      role,
      type: "quick_replies",
      createdAt: now,
      payload: { replies: meta.quick_replies },
    });
  }

  if (res.safety_message) {
    messages.push({
      id: uid("safe"),
      role: "system",
      type: "system",
      content: res.safety_message,
      createdAt: now,
    });
  }

  return messages;
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
