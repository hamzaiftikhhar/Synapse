"""
Fast-path response templates for direct responses.

The NLU classifier may return a `clarification_question` string it generated —
we use that for CLARIFY intents. For all other direct intents we own the wording
here so every clinic gets consistent, on-brand copy that is easy to tune, A/B
test, or localise without touching prompts.

Template IDs are stable string constants. The backend looks them up via
`get_response(template_id, **vars)`.  Variables are optional — any {var} in the
template string is filled from `vars`; unknown keys are silently ignored so
callers don't need to pass every variable.
"""

from __future__ import annotations

import re
from typing import Any


# ── Template registry ────────────────────────────────────────────────────────

_TEMPLATES: dict[str, str] = {
    # Greetings / small talk
    "GREETING": (
        "Hi! How can I help you today? I can help with appointments, "
        "doctors, clinic hours, and insurance."
    ),
    "GREETING_RETURNING": (
        "Welcome back! How can I help you today?"
    ),
    "HOW_ARE_YOU": (
        "I'm here and ready to help! What can I do for you today?"
    ),
    # Farewells
    "FAREWELL": (
        "Thank you for reaching out. Have a great day and stay healthy!"
    ),
    "FAREWELL_AFTER_BOOKING": (
        "You're all set! Have a great day and we'll see you soon."
    ),
    # Thanks
    "THANKS": (
        "Happy to help! Is there anything else I can assist you with?"
    ),
    # Off-topic — gentle redirect
    "OFF_TOPIC": (
        "I'm here to assist with clinic-related questions — things like "
        "appointments, doctors, services, or insurance. "
        "Is there something along those lines I can help you with?"
    ),
    "OFF_TOPIC_PHONE": (
        "Sounds like that's a phone issue — I'm only able to help with "
        "clinic matters. Would you like help booking an appointment or "
        "finding a doctor?"
    ),
    "OFF_TOPIC_SPORTS": (
        "That's a fun topic, but I'm only able to help with clinic-related "
        "questions. Is there anything I can help you with regarding your "
        "health or an appointment?"
    ),
    "OFF_TOPIC_FOOD": (
        "Ha — I'm not a food expert! I can, however, help you find a "
        "doctor or book an appointment. Would you like help with that?"
    ),
    "OFF_TOPIC_TRAVEL": (
        "Sounds like a great trip idea! I'm only able to help with "
        "clinic-related things, though — like appointments, doctors, or "
        "insurance. Need anything along those lines?"
    ),
    "OFF_TOPIC_ENTERTAINMENT": (
        "Nice taste! Unfortunately I can only help with clinic-related "
        "questions. Would you like to book an appointment or look up "
        "a doctor?"
    ),
    # Abusive / aggressive language
    "ABUSIVE_LANGUAGE": (
        "I understand you may be frustrated. I'm here to help with clinic "
        "questions as best I can. Please let me know how I can assist."
    ),
    "ABUSIVE_LANGUAGE_REPEAT": (
        "I want to help, but I'm not able to continue if the conversation "
        "includes offensive language. Please let me know your clinic-related "
        "question and I'll do my best to assist."
    ),
    # Emergencies
    "EMERGENCY": (
        "⚠️ If this is a medical emergency, please call 911 (or your local "
        "emergency number) immediately, or go to the nearest emergency room.\n\n"
        "This chatbot cannot provide emergency medical care."
    ),
    "EMERGENCY_MENTAL_HEALTH": (
        "⚠️ If you or someone you know is in crisis, please call or text "
        "988 (Suicide & Crisis Lifeline) or call 911 immediately.\n\n"
        "I'm not able to provide emergency mental-health support — please "
        "reach out to a professional right away."
    ),
    # Clarify — uses LLM-generated question as fallback
    "CLARIFY_GENERIC": (
        "I want to make sure I help you correctly — could you tell me a bit "
        "more about what you're looking for?"
    ),
    # Booking — acknowledge intent; the wizard is the next step (never claim
    # times/slots are "below" unless availability SQL actually returned them).
    "BOOKING_START": "Sure — let's get you booked.",
    "BOOKING_START_SERVICE": "Let's get {service} booked.",
    # Human handoff
    "HANDOFF_HUMAN": (
        "Of course — let me connect you with a team member. "
        "Please hold on while I transfer you, or call us directly at "
        "{clinic_phone}."
    ),
    # Can't help
    "CANNOT_HELP": (
        "I'm sorry, I'm not able to help with that right now. "
        "Please call the clinic directly if you need immediate assistance."
    ),
    # Native / colloquial tone — these fire when rules detect informal phrasing
    "GREETING_INFORMAL": (
        "Hey! What's up? I can help with appointments, doctors, or "
        "insurance — what do you need?"
    ),
    "THANKS_INFORMAL": (
        "No problem at all! Anything else I can do for you?"
    ),
}


# ── Public API ───────────────────────────────────────────────────────────────

def get_response(template_id: str, **variables: Any) -> str:
    """Return a filled template string, or a safe fallback."""
    template = _TEMPLATES.get(template_id, _TEMPLATES["CANNOT_HELP"])
    if not variables:
        return template
    # Fill only the vars that exist in the template — ignore unknown keys.
    placeholders = {m.group(1) for m in re.finditer(r"\{(\w+)\}", template)}
    safe_vars = {k: v for k, v in variables.items() if k in placeholders}
    return template.format_map(safe_vars)


_MENTAL_HEALTH_KEYWORDS = (
    "suicid", "suicidal", "kill myself", "end my life", "harm myself",
    "self harm", "self-harm", "don't want to live", "want to die",
    "wish i was dead", "take my life", "hurt myself", "can't go on",
    "better off dead", "no reason to live", "take my own life",
    "jump", "overdose", "slit", "cut myself", "shoot myself",
)

_GREETING_INFORMAL_KEYWORDS = (
    "sup", "yo ", " yo", "wassup", "wazzup", "waddup", "whassup",
    "what's up", "whats up", "howdy", "hiya", "heya", "hey there",
    "ayy", "ay ", "greetings",
)

_HOW_ARE_YOU_KEYWORDS = (
    "how are you", "how r you", "how are u", "how do you do",
    "how have you been", "how's it going", "how is it going",
    "how are things", "how's your day", "how are ya",
    "how you doing", "how you doin", "how you been",
    "how're you",
)

_THANKS_INFORMAL_KEYWORDS = (
    "thx", "ty ", " ty", "tysm", "thnx", "tyvm", "thanx", "cheers",
    "appreciate it", "gracias", "much obliged", "thanks a lot",
    "thanks a bunch", "danke", "thank u", "thankyou",
)

_OFFTOPIC_PHONE_KEYWORDS = (
    "phone", "mobile", "cell phone", "iphone", "android", "samsung",
    "pixel", "tablet", "ipad", "screen", "battery", "charger",
    "laptop", "computer", "macbook", "pc", "wifi", "bluetooth",
    "app ", "software", "hardware", "ios", "windows", "gadget", "device",
    "smartphone",
)

_OFFTOPIC_SPORTS_KEYWORDS = (
    "fifa", "football", "soccer", "basketball", "nba", "nfl",
    "cricket", "baseball", "mlb", "hockey", "nhl", "tennis", "golf",
    "rugby", "volleyball", "wwe", "ufc", "boxing", "olympics",
    "messi", "ronaldo", "lebron", "sports", "match", "tournament",
    "ipl", "world cup", "champions league", "player",
)

_OFFTOPIC_FOOD_KEYWORDS = (
    "recipe", "cook", "cooking", "food", "restaurant", "meal", " eat",
    "hungry", "pizza", "burger", "sushi", "dinner", "lunch", "breakfast",
    "snack", "drink", "coffee", "beer", "wine", "baking", "chef",
    "menu", "cafe", "diet", "vegan", "grocery", "yummy", "delicious",
    "biryani", "bbq", "dessert", "cuisine", "pasta",
)

_OFFTOPIC_TRAVEL_KEYWORDS = (
    "flight", "hotel", "vacation", "trip", "tour", "visa",
    "passport", "beach", "travel", "airbnb", "booking",
)

_OFFTOPIC_ENTERTAINMENT_KEYWORDS = (
    "movie", "film", "series", "netflix", "anime", "music", "song",
    "spotify", "game", "gaming", "playstation", "xbox", "youtube",
    "tiktok", "instagram",
)


def resolve_direct_template(intent_value: str, message: str) -> str:
    """
    Map an intent + raw message to the best template ID.

    Called only when route == DIRECT_RESPONSE or CLARIFY/EMERGENCY.
    """
    msg = message.lower().strip()

    if intent_value == "emergency":
        if any(p in msg for p in _MENTAL_HEALTH_KEYWORDS):
            return "EMERGENCY_MENTAL_HEALTH"
        return "EMERGENCY"

    if intent_value == "greeting":
        if any(p in msg for p in _HOW_ARE_YOU_KEYWORDS):
            return "HOW_ARE_YOU"
        if any(p in msg for p in _GREETING_INFORMAL_KEYWORDS):
            return "GREETING_INFORMAL"
        return "GREETING"

    if intent_value == "farewell":
        return "FAREWELL"

    if intent_value in ("thanks", "thank_you"):
        if any(p in msg for p in _THANKS_INFORMAL_KEYWORDS):
            return "THANKS_INFORMAL"
        return "THANKS"

    if intent_value == "off_topic":
        if any(p in msg for p in _OFFTOPIC_PHONE_KEYWORDS):
            return "OFF_TOPIC_PHONE"
        if any(p in msg for p in _OFFTOPIC_SPORTS_KEYWORDS):
            return "OFF_TOPIC_SPORTS"
        if any(p in msg for p in _OFFTOPIC_FOOD_KEYWORDS):
            return "OFF_TOPIC_FOOD"
        if any(p in msg for p in _OFFTOPIC_TRAVEL_KEYWORDS):
            return "OFF_TOPIC_TRAVEL"
        if any(p in msg for p in _OFFTOPIC_ENTERTAINMENT_KEYWORDS):
            return "OFF_TOPIC_ENTERTAINMENT"
        return "OFF_TOPIC"

    if intent_value == "handoff_human":
        return "HANDOFF_HUMAN"

    if intent_value == "abusive":
        return "ABUSIVE_LANGUAGE"

    return "CLARIFY_GENERIC"
