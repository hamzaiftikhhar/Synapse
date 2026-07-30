"""Marketing site assistant — sales only, zero clinic tenant data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketingResult:
    response: str
    route: str = "direct_response"
    intent: str = "marketing"
    confidence: float = 0.99
    needs_sql: bool = False
    needs_vector: bool = False
    needs_llm: bool = False
    safety_message: str | None = None
    sql_results: list = field(default_factory=list)
    vector_results: list = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


_GREETING = (
    "Hello! I'm the Synapse assistant. I can help with product features, "
    "pricing, security, integrations, and booking a demo. "
    "What would you like to know?"
)

_FAQ = {
    "pricing": (
        "Synapse offers flexible plans for clinics of all sizes. "
        "Visit our Pricing page or book a demo for a tailored quote."
    ),
    "security": (
        "Synapse is built for healthcare: tenant isolation, encrypted data, "
        "audit logs, and HIPAA-ready architecture. Each clinic's data is fully isolated."
    ),
    "features": (
        "Synapse includes AI chatbot, appointment booking, doctor search, "
        "insurance verification, knowledge-base RAG, and a full admin portal."
    ),
    "demo": (
        "I'd love to connect you with our team! "
        "Use the Contact page to book a demo, or say 'contact sales'."
    ),
    "integration": (
        "Synapse embeds on any clinic website via a lightweight widget. "
        "Staff manage everything from the admin portal. API docs are at /developers."
    ),
}

_OFF_TOPIC = (
    "I'm the Synapse product assistant — I can only help with Synapse features, "
    "pricing, security, and demos. I can't answer clinic-specific questions here."
)


class MarketingEngine:
    """Rule-based marketing assistant — no clinic DB access."""

    def process(self, *, message: str) -> MarketingResult:
        text = message.lower().strip()
        meta: dict[str, Any] = {
            "actions": [
                {
                    "id": "features",
                    "label": "Features",
                    "icon": "Search",
                    "behavior": "message",
                    "message": "What features does Synapse offer?",
                },
                {
                    "id": "pricing",
                    "label": "Pricing",
                    "icon": "Calendar",
                    "behavior": "message",
                    "message": "Tell me about pricing",
                },
                {
                    "id": "demo",
                    "label": "Book Demo",
                    "icon": "Phone",
                    "behavior": "open_url",
                    "url": "/contact",
                },
            ],
        }

        if any(w in text for w in ("hi", "hello", "hey", "good morning", "how are")):
            return MarketingResult(response=_GREETING, meta=meta)

        if any(w in text for w in ("price", "pricing", "cost", "plan", "subscription")):
            return MarketingResult(
                response=_FAQ["pricing"],
                intent="pricing",
                meta={**meta, "buttons": [{"id": "pricing", "label": "View Pricing", "behavior": "open_url", "url": "/pricing"}]},
            )

        if any(w in text for w in ("security", "hipaa", "compliance", "encrypt", "privacy")):
            return MarketingResult(response=_FAQ["security"], intent="security", meta=meta)

        if any(w in text for w in ("feature", "what do you do", "capabilities", "offer")):
            return MarketingResult(response=_FAQ["features"], intent="features", meta=meta)

        if any(w in text for w in ("demo", "contact", "sales", "talk to", "book a")):
            return MarketingResult(
                response=_FAQ["demo"],
                intent="demo",
                meta={**meta, "buttons": [{"id": "contact", "label": "Contact Sales", "behavior": "open_url", "url": "/contact"}]},
            )

        if any(w in text for w in ("integrat", "embed", "widget", "api", "website")):
            return MarketingResult(response=_FAQ["integration"], intent="integration", meta=meta)

        # Block clinic-specific queries
        if any(
            w in text
            for w in (
                "doctor", "appointment", "insurance", "clinic hours",
                "medicaid", "patient", "cardiology", "dr ", "book with",
            )
        ):
            return MarketingResult(response=_OFF_TOPIC, intent="off_topic", meta=meta)

        return MarketingResult(
            response=(
                "I can help with Synapse product questions — features, pricing, "
                "security, integrations, or booking a demo. What interests you?"
            ),
            intent="unknown",
            meta=meta,
        )
