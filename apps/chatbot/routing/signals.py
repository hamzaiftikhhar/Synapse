"""Clinic-agnostic speech-act signals for routing (no tenant-specific keywords)."""

from __future__ import annotations

import re
from typing import Any

from apps.chatbot.nlu.emergency_patterns import SYMPTOM_CUE_RE as _SYMPTOM_CUE_RE

# Question / info-seeking frames (any clinic)
_INFORMATIONAL_RE = re.compile(
    r"\b("
    r"what|what'?s|whats|which|when|where|why|how|how'?s|"
    r"tell me|can you (?:tell|explain)|explain|describe|"
    r"do you (?:have|offer|provide|accept|take|cover)|"
    r"is there|are there|should i|do i (?:need|have to)|"
    r"how (?:much|long|early|many|far)|"
    r"cost|price|pricing|fee|fees|deposit|duration"
    r")\b",
    re.I,
)

# Explicit desire to create/change a booking
_TRANSACTIONAL_BOOK_RE = re.compile(
    r"\b("
    r"(?:i )?(?:want to |wanna |would like to |need to |can i |please )?"
    r"(?:book|schedule|make|set up|reserve|reschedule)\b|"
    r"\b(?:book|schedule|reschedule)\s+(?:something|an? appointment|a visit|my appointment)\b|"
    r"\bstart booking\b|"
    r"\bbook (?:an? )?appointment\b|"
    r"\bschedule (?:an? )?appointment\b|"
    r"\breschedule (?:my |an? )?appointment\b|"
    r"\bbook .{0,40}\bwith\b|"
    r"\bschedule a spot\b|"
    r"\bcheck (?:my )?appointment\b"
    r")",
    re.I,
)

# Duration / procedure-time frames (must beat bare "hours")
_DURATION_HOURS_RE = re.compile(
    r"("
    r"\bhow\s+much\s+hours?\b|"
    r"\bhow\s+many\s+hours?\b|"
    r"\bhow\s+much\s+time\b|"
    r"\bhow\s+long\b|"
    r"\bhours?\s+does\s+it\s+take\b|"
    r"\bhours?\s+(?:to\s+)?(?:do|for|take|takes|taking)\b|"
    r"\btake[s]?\s+(?:to\s+)?(?:do|for|complete)\b|"
    r"\btakes?\b.*\bhours?\b|"
    r"\bhours?\b.*\btake[s]?\b|"
    r"\bfor\s+how\s+many\s+hours\b|"
    r"\bhours?\s+(?:after|before|per\s+day|a\s+day|straight)\b|"
    r"\bduration\b"
    r")",
    re.I,
)

# True clinic open/close — short or explicit business frames
_BUSINESS_HOURS_RE = re.compile(
    r"\b("
    r"(?:clinic|office|your|business)\s+hours\b|"
    r"what\s+(?:are\s+)?(?:your\s+)?(?:clinic\s+|office\s+)?hours\b|"
    r"tell\s+(?:me\s+)?(?:about\s+)?(?:your\s+|the\s+|clinic\s+)?hours\b|"
    r"when\s+(?:are\s+you|do\s+you)\s+open|"
    r"what\s+time\s+(?:do\s+you|are\s+you)\s+(?:open|close)|"
    r"(?:are\s+you|you)\s+(?:open|closed)|"
    r"closing\s+time|opening\s+(?:hours|time)|"
    r"hours\s+of\s+operation"
    r")\b",
    re.I,
)
_BARE_HOURS_RE = re.compile(r"^(?:hours|hours\?|clinic hours|your hours)\s*$", re.I)

# Structured catalog facts patients ask SQL for
_PRICE_DURATION_RE = re.compile(
    r"\b(cost|price|pricing|fee|fees|charge|charges|how long|duration|"
    r"how much time|how much hours?|how many hours?)\b|"
    r"\bhow much(?: does| is| for| to)\b|"
    r"\bhours?\s+does\s+it\s+take\b|"
    r"\btake[s]?\s+(?:to\s+)?(?:do|for)\b",
    re.I,
)

_INSURANCE_FRAME_RE = re.compile(
    r"\b(insurance|coverage|copay|deductible|in[- ]network|"
    r"accept(?:ed|s)?|covered|cover(?:age)?)\b",
    re.I,
)

# Soft knowledge / policy frames — healthcare-general, not clinic-branded
_KNOWLEDGE_FRAME_RE = re.compile(
    r"\b("
    r"policy|policies|protocol|protocols|sop|"
    r"arrive|arrival|early|check[- ]?in|"
    r"deposit|down payment|refund|cancellation|"
    r"post[- ]?op|postoperative|after (?:surgery|procedure|extraction|visit)|"
    r"instructions?|guidelines?|restrictions?|"
    r"gauze|bleeding|fever|swelling|"
    r"straw|straws|smoking|spitting|rinse|"
    r"replacement|lost|damaged|"
    r"emergency (?:number|line|contact|phone)|"
    r"what (?:does|do) .+ include|"
    r"membership|package|"
    r"sun exposure|retinoid|pre[- ]?care|aftercare"
    r")\b",
    re.I,
)

_ABOUT_SERVICE_RE = re.compile(
    r"\b(tell me (?:about|something about)|what (?:is|about)|about (?:the|your))\b",
    re.I,
)

# Single source of truth for "generic English word, never a name/SKU fragment"
# — reused by nlu/resolvers.py's doctor fuzzy-matcher as well as the
# service-matching functions below. Don't fork a second list.
STOPWORDS = frozenset(
    {
        "about", "after", "again", "also", "been", "before", "being", "between",
        "clinic", "could", "does", "doing", "from", "have", "here", "into",
        "just", "like", "more", "most", "much", "only", "other", "please",
        "should", "some", "such", "than", "that", "their", "them", "then",
        "there", "these", "they", "this", "those", "through", "under", "very",
        "want", "what", "when", "where", "which", "while", "with", "would",
        "your", "yours", "tell", "give", "make", "help", "need", "know",
        "hours", "hour", "time", "take", "takes", "full", "body",
        # Generic care/visit tokens — never treat as a named service SKU
        "visit", "visits", "care", "basic", "level", "routine", "simple",
        "urgent", "patient", "adult", "exam", "combo", "swab", "rapid",
        "treatment", "treatments", "service", "services", "procedure",
        "wrinkle", "tooth", "child", "well",
    }
)

# List / browse frames — must NOT collapse to a single matched service SKU
_SERVICE_LIST_RE = re.compile(
    r"\b("
    r"what (?:services|special(?:t(?:y|ies)|ities)|things)\b|"
    r"which (?:services|special(?:t(?:y|ies)|ities))\b|"
    r"services? (?:do you )?(?:offer|provide|have)\b|"
    r"special(?:t(?:y|ies)|ities) (?:do you )?(?:offer|provide|have)\b|"
    r"list (?:of )?(?:services|special(?:t(?:y|ies)|ities))\b|"
    r"what (?:do you|things do you) (?:offer|provide)\b|"
    r"what (?:are )?(?:the )?(?:urgent care|primary care).{0,40}provid|"
    r"what (?:urgent care|primary care).{0,40}(?:provid|offer)|"
    r"(?:urgent care|primary care) (?:services?\b|do you provid)|"
    r"(?:urgent care|primary care).{0,30}(?:clinic )?(?:provid|offer)"
    r")",
    re.I,
)

_SPECIALTY_LIST_RE = re.compile(
    r"\b("
    r"what special(?:t(?:y|ies)|ities)|which special(?:t(?:y|ies)|ities)|"
    r"special(?:t(?:y|ies)|ities) (?:do you )?(?:offer|provide|have)|"
    r"list (?:of )?special(?:t(?:y|ies)|ities)"
    r")\b",
    re.I,
)

# Doctor browse/list — must not inherit catalog specialty/service filters
_DOCTOR_BROWSE_RE = re.compile(
    r"\b("
    r"which doctors?|what doctors?|how many doctors?|"
    r"who (?:are|is) (?:your|the|ur) doctors?|"
    r"list (?:of )?doctors?|"
    r"(?:doctors?|dentists?) (?:do you )?(?:have|got)|"
    r"do you have any doctors?"
    r")\b",
    re.I,
)

_DOCTOR_BROWSE_FILTER_CUE_RE = re.compile(
    r"\b("
    r"cardiolog\w*|dermatolog\w*|pediatric\w*|surgeon\w*|specialist\w*|"
    r"offer(?:s|ing)?|specializ\w*|who does|heart surgery|"
    r"dr\.?\s+\w|doctor\s+\w"
    r")\b",
    re.I,
)

_PHATIC_GREETING_RE = re.compile(
    r"^\s*(?:(?:hey|hi|hello|yo|hiya|howdy)\s+)*"
    r"(?:hi|hello|hey|hiya|howdy|yo|good\s+(?:morning|afternoon|evening))"
    r"(?:\s+(?:there|all|folks))?"
    r"(?:\s+how\s+are\s+(?:you|u|ya))?"
    r"(?:\s+please)?"
    r"[\s?!.]*$",
    re.I,
)
_DAY_TOKEN_RE = re.compile(
    r"\b("
    r"today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mon|tue|wed|thu|fri|sat|sun|next\s+week|this\s+week|next\s+monday|"
    r"next\s+tuesday|next\s+wednesday|next\s+thursday|next\s+friday|"
    r"next\s+saturday|next\s+sunday|morning|afternoon|evening|after\s+work"
    r")\b",
    re.I,
)

_DOCTOR_CUE_RE = re.compile(r"\b(?:dr\.?|doctor|doc)\b", re.I)

_DOCTOR_AVAILABILITY_RE = re.compile(
    r"\b("
    r"(?:dr\.?|doctor|doc)\s+[a-z][\w'-]{0,30}.{0,40}\b(?:free|available|availability|open|slot|slots)\b|"
    r"\b(?:free|available|availability|open\s+slots?)\b.{0,40}\b(?:dr\.?|doctor|doc)\b|"
    r"\b(?:is|are)\s+(?:dr\.?|doctor|doc)\b.{0,40}\b(?:free|available|open)\b|"
    r"\b(?:dr\.?|doctor|doc)\b.{0,40}\b(?:free|available|open)\b.{0,20}"
    r"(?:on|this|next)?\b"
    r")\b",
    re.I,
)

_URGENT_AVAILABILITY_RE = re.compile(
    r"\b("
    r"squeeze\s+me\s+in|asap|as\s+soon\s+as\s+possible|urgent|"
    r"next\s+available|earliest\s+(?:opening|slot|appointment)|"
    r"urgent\s+appointment|emergency\s+appointment|"
    r"need\s+(?:to\s+)?(?:be\s+)?seen\s+(?:today|asap|soon)"
    r")\b",
    re.I,
)

# Canonical "the patient has committed enough detail to skip discovery and go
# straight into doctor/slot resolution" phrase set — the single source of
# truth shared by nlu/rules.py's post-LLM fallback tier and engine.py's
# booking-commit check. Distinct from is_transactional_booking() above: that
# answers "is this about booking at all"; this answers the narrower "is it
# specific enough to skip straight past discovery UI."
BOOKING_COMMIT_EXACT = frozenset(
    {
        "start booking",
        "book appointment",
        "book an appointment",
        "i would like to book an appointment",
        "schedule an appointment",
        "i wanna book something",
    }
)

_BOOKING_COMMIT_WITH_RE = re.compile(r"(book|schedule).{0,40}(with\s+dr\.?|with\s+[a-z])", re.I)
_GENERIC_DOCTOR_RE = re.compile(
    r"\b(good|best|a|the|some)\s+doctor\b", re.I
)


def is_booking_commit(message: str, *, doctor_name: Any = None) -> bool:
    """True when the patient has given enough specificity (exact commit
    phrase, or a named doctor + booking verb) to skip discovery and go
    straight to doctor/slot resolution."""
    text = (message or "").lower().strip()
    if not text:
        return False
    if text in BOOKING_COMMIT_EXACT or "start booking" in text:
        return True

    if doctor_name and any(k in text for k in ("book", "schedule", "appointment")):
        return True

    if _GENERIC_DOCTOR_RE.search(text):
        return False

    return bool(_BOOKING_COMMIT_WITH_RE.search(text))

_PHATIC_FAREWELL_RE = re.compile(
    r"^\s*(?:(?:hey|hi|hello|ok|okay|alright|well)\s+)*"
    r"(?:bye|goodbye|good\s*bye|see\s+y(?:a|ou)|take\s+care|thanks?\s+bye|"
    r"thank\s+you|thanks|thx|ttyl|later)"
    r"(?:\s+please)?"
    r"[\s?!.]*$",
    re.I,
)


def is_phatic_greeting(message: str) -> bool:
    text = (message or "").strip()
    if not text or len(text) > 48:
        return False
    # Strip common filler prefixes used in chat
    text = re.sub(
        r"^(?:umm+|uh+|so+|quick\s+q\s*[—\-:]?\s*|pls\s+|please\s+)+",
        "",
        text,
        flags=re.I,
    ).strip()
    return bool(_PHATIC_GREETING_RE.match(text))


def is_phatic_farewell(message: str) -> bool:
    text = (message or "").strip()
    if not text or len(text) > 48:
        return False
    text = re.sub(
        r"^(?:umm+|uh+|ok+|okay\s+|quick\s+q\s*[—\-:]?\s*|pls\s+|please\s+)+",
        "",
        text,
        flags=re.I,
    ).strip()
    return bool(_PHATIC_FAREWELL_RE.match(text))


def is_informational(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    if text.endswith("?"):
        return True
    return bool(_INFORMATIONAL_RE.search(text))


def is_transactional_booking(message: str) -> bool:
    """True only when the user is asking to create/change a booking."""
    text = message or ""
    if not _TRANSACTIONAL_BOOK_RE.search(text):
        return False
    # "when should I book" / "how do I book" stay informational if question-framed
    if is_informational(text) and re.search(
        r"\b(how (?:do|can|should)|when (?:should|can|do)|what (?:if|happens))\b",
        text,
        re.I,
    ):
        return False
    return True


def is_procedure_duration_query(message: str) -> bool:
    """True when 'hours/time' refers to how long a procedure takes."""
    return bool(_DURATION_HOURS_RE.search(message or ""))


def has_symptom_cues(message: str) -> bool:
    """True when message contains emergency/soft-symptom language (blocks hours steal)."""
    return bool(_SYMPTOM_CUE_RE.search(message or ""))


def is_service_list_query(message: str) -> bool:
    """Browse/list services — do not pin a single SKU from fuzzy name overlap."""
    return bool(_SERVICE_LIST_RE.search(message or ""))


def is_specialty_list_query(message: str) -> bool:
    return bool(_SPECIALTY_LIST_RE.search(message or ""))


def is_doctor_browse_query(message: str) -> bool:
    """Browse all doctors — no specialty/service filter unless named in message."""
    text = message or ""
    if not _DOCTOR_BROWSE_RE.search(text):
        return False
    if _DOCTOR_BROWSE_FILTER_CUE_RE.search(text):
        return False
    return True


def service_filter_mode(
    message: str, matched_services: list[dict[str, Any]] | None = None
) -> str:
    """
    none | named | category

    - none: list/browse all (or no filter)
    - named: user clearly named one service (full name / strong multi-token hit)
    - category: keyword category without a single SKU (e.g. "urgent care services")
    """
    if is_service_list_query(message) or is_specialty_list_query(message):
        return "none"
    hits = matched_services or []
    if len(hits) == 1:
        return "named"
    if len(hits) > 1:
        return "category"
    return "none"


def is_doctor_availability_query(message: str) -> bool:
    """Doctor + time window — not clinic open/close hours."""
    text = message or ""
    if not text:
        return False
    if _DOCTOR_AVAILABILITY_RE.search(text):
        return True
    if _DOCTOR_CUE_RE.search(text) and _DAY_TOKEN_RE.search(text):
        if re.search(r"\b(free|available|availability|open|slot|slots|see\s+me)\b", text, re.I):
            return True
    if re.search(r"\b(free|available)\b", text, re.I) and _DAY_TOKEN_RE.search(text):
        if _DOCTOR_CUE_RE.search(text):
            return True
    return False


def is_urgent_availability_request(message: str) -> bool:
    return bool(_URGENT_AVAILABILITY_RE.search(message or ""))


def mentions_doctor_with_temporal(message: str) -> bool:
    text = message or ""
    return bool(_DOCTOR_CUE_RE.search(text) and _DAY_TOKEN_RE.search(text))


def mentions_doctor(message: str) -> bool:
    """Cheap pre-check: does this message plausibly name/reference a doctor
    at all? Used to gate the fuzzy doctor-name resolver so it isn't run
    (DB query + fuzzy scoring) on every single message regardless of intent."""
    return bool(_DOCTOR_CUE_RE.search(message or ""))


def is_business_hours_query(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    # Doctor availability must never become clinic hours
    if is_doctor_availability_query(text):
        return False
    if mentions_doctor_with_temporal(text) and re.search(
        r"\b(free|available|availability|slot|slots)\b", text, re.I
    ):
        return False
    # Symptom / emergency narratives must never become open/close answers
    if has_symptom_cues(text):
        return False
    # Duration / procedure time always wins over open/close
    if is_procedure_duration_query(text) or is_price_or_duration_query(text):
        # Exception: explicit "clinic hours" / "what are your hours"
        if _BARE_HOURS_RE.match(text):
            return True
        if re.search(
            r"\b((?:clinic|office|business)\s+hours|hours of operation|"
            r"when (?:are you|do you) open)\b",
            text,
            re.I,
        ) and not re.search(r"\btake|takes|doing|procedure|treatment\b", text, re.I):
            return True
        return False
    if _BARE_HOURS_RE.match(text):
        return True
    if _BUSINESS_HOURS_RE.search(text):
        return True
    # Lone "hours" / "hours?" already handled; "can you tell about hours?"
    if re.search(r"\bhours\b", text, re.I) and not _KNOWLEDGE_FRAME_RE.search(text):
        # Only treat as business hours when the message is short / about the clinic clock
        tokens = re.findall(r"[a-z0-9']+", text.lower())
        if len(tokens) <= 8 and not re.search(
            r"\b(take|takes|treatment|procedure|screening|cleaning|filling|botox)\b",
            text,
            re.I,
        ):
            return True
    return False


def is_price_or_duration_query(message: str) -> bool:
    text = message or ""
    # Policy / membership fees are knowledge, not catalog pricing
    if re.search(
        r"\b(cancel(?:lation)?|refund|membership|policy|deposit|dues|prorat\w*)\b",
        text,
        re.I,
    ) and re.search(r"\b(fee|fees|charge|refund|policy)\b", text, re.I):
        return False
    if is_procedure_duration_query(text):
        # Bare "how much time" without a clinic service/procedure cue is not SQL pricing
        if re.search(r"\bhow\s+much\s+time\b", text, re.I) and not re.search(
            r"\b(service|procedure|treatment|appointment|cleaning|exam|"
            r"extraction|screening|botox|laser|visit|physical)\b",
            text,
            re.I,
        ):
            return False
        return True
    if not _PRICE_DURATION_RE.search(text):
        return False
    if _INSURANCE_FRAME_RE.search(text) and not re.search(
        r"\b(service|procedure|treatment|visit|extraction|filling|cleaning|"
        r"screening|botox|laser)\b",
        text,
        re.I,
    ):
        if re.search(r"\b(copay|deductible|premium)\b", text, re.I):
            return False
    if re.search(r"\b(early|arrive|arrival)\b", text, re.I):
        return False
    return True


def looks_like_about_service(message: str) -> bool:
    return bool(_ABOUT_SERVICE_RE.search(message or ""))


def looks_like_knowledge_question(message: str) -> bool:
    """Informational clinic-document question (policy / post-op / fees / arrival)."""
    text = message or ""
    if not text:
        return False
    if is_transactional_booking(text):
        return False
    # Cancellation/refund/membership fee frames beat service-pricing speech acts
    if re.search(
        r"\b(cancel(?:lation)?|refund|membership|reactivat\w*|terminat\w*)\b",
        text,
        re.I,
    ) and re.search(
        r"\b(fee|fees|policy|policies|charge|refund|dues|prorat\w*)\b",
        text,
        re.I,
    ):
        return True
    # Post-op / restriction frames beat bare duration/pricing speech acts
    if _KNOWLEDGE_FRAME_RE.search(text):
        return True
    if is_price_or_duration_query(text):
        return False
    # Informational + appointment without book/schedule → often policy (arrive early, etc.)
    if is_informational(text) and re.search(r"\bappointment\b", text, re.I):
        if not re.search(r"\b(book|schedule|reschedule|cancel)\b", text, re.I):
            return True
    return False


def significant_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]{4,}", (text or "").lower()))
    return {t for t in tokens if t not in STOPWORDS}


def catalog_overlap_score(
    message: str, catalog: list[dict[str, Any]] | None
) -> tuple[bool, list[str]]:
    """
    Dynamic overlap between the user message and each clinic's document catalog.
    Uses keywords + significant tokens from title/summary — no brand hardcoding.
    """
    text = (message or "").lower()
    if not text or not catalog:
        return False, []

    msg_tokens = significant_tokens(text)
    hits: list[str] = []

    for doc in catalog:
        matched = False
        for kw in doc.get("routing_keywords") or []:
            if isinstance(kw, str) and kw.strip() and kw.lower() in text:
                matched = True
                break
        if not matched:
            blob = " ".join(
                [
                    str(doc.get("title") or ""),
                    str(doc.get("routing_summary") or doc.get("summary") or ""),
                    " ".join(
                        str(k) for k in (doc.get("routing_keywords") or []) if k
                    ),
                ]
            )
            doc_tokens = significant_tokens(blob)
            # Require ≥2 overlapping content tokens, or 1 strong keyword-length token (≥6)
            overlap = msg_tokens & doc_tokens
            if len(overlap) >= 2 or any(len(t) >= 6 for t in overlap):
                matched = True
        if matched and doc.get("id"):
            hits.append(str(doc["id"]))

    return bool(hits), hits


def match_services_in_message(
    message: str, services: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """
    Strict tenant-dynamic service name match.

    Accepts: full name ⊆ text, multi-word phrase (≥2 tokens, len≥8),
    or ≥2 significant (len≥5, non-stopword) tokens from the name.
    Rejects: bare single tokens like "visit" / "care" / "routine".
    """
    text = (message or "").lower()
    if not text or not services:
        return []
    # List/browse questions never pin a SKU via fuzzy overlap
    if is_service_list_query(text):
        return []
    hits: list[dict[str, Any]] = []
    for svc in services:
        name = str(svc.get("name") or "").strip().lower()
        if len(name) < 4:
            continue
        if name in text:
            hits.append(svc)
            continue
        words = [
            w
            for w in re.findall(r"[a-z0-9]+", name)
            if w not in {"and", "the", "for", "with", "a", "an", "of", "or"}
            and w not in STOPWORDS
        ]
        matched = False
        # Multi-word phrase windows only (never single generic token)
        for n in (3, 2):
            if matched:
                break
            for i in range(0, max(0, len(words) - n + 1)):
                phrase = " ".join(words[i : i + n])
                if len(phrase) >= 8 and phrase in text:
                    matched = True
                    break
        # Distinctive single brand/procedure tokens only (len≥7, not stopword)
        if not matched:
            for w in words:
                if len(w) >= 7 and w in text and w not in STOPWORDS:
                    matched = True
                    break
        # ≥2 significant tokens present (each len≥5)
        if not matched and len(words) >= 2:
            strong = [t for t in words if len(t) >= 5]
            if len(strong) >= 2 and all(t in text for t in strong[:2]):
                matched = True
        if matched:
            hits.append(svc)
    return hits
