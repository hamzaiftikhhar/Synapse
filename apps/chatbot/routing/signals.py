"""Clinic-agnostic speech-act signals for routing (no tenant-specific keywords)."""

from __future__ import annotations

import re
from typing import Any

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
    r"(?:book|schedule|make|set up|reserve)\b|"
    r"\b(?:book|schedule)\s+(?:something|an? appointment|a visit)\b|"
    r"\bstart booking\b|"
    r"\bbook (?:an? )?appointment\b|"
    r"\bschedule (?:an? )?appointment\b|"
    r"\bbook .{0,40}\bwith\b"
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

_STOPWORDS = frozenset(
    {
        "about", "after", "again", "also", "been", "before", "being", "between",
        "clinic", "could", "does", "doing", "from", "have", "here", "into",
        "just", "like", "more", "most", "much", "only", "other", "please",
        "should", "some", "such", "than", "that", "their", "them", "then",
        "there", "these", "they", "this", "those", "through", "under", "very",
        "want", "what", "when", "where", "which", "while", "with", "would",
        "your", "yours", "tell", "give", "make", "help", "need", "know",
        "hours", "hour", "time", "take", "takes", "full", "body",
    }
)


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


def is_business_hours_query(message: str) -> bool:
    text = (message or "").strip()
    if not text:
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
    if is_procedure_duration_query(text):
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
    return {t for t in tokens if t not in _STOPWORDS}


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
    """Match this clinic's service names in free text (tenant-dynamic)."""
    text = (message or "").lower()
    if not text or not services:
        return []
    hits: list[dict[str, Any]] = []
    for svc in services:
        name = str(svc.get("name") or "").strip().lower()
        if len(name) < 4:
            continue
        if name in text:
            hits.append(svc)
            continue
        # Phrase windows (e.g. "cancer screening", "botox")
        words = [w for w in re.findall(r"[a-z0-9]+", name) if w not in {"and", "the", "for", "with"}]
        matched = False
        for n in (3, 2):
            if matched:
                break
            for i in range(0, max(0, len(words) - n + 1)):
                phrase = " ".join(words[i : i + n])
                if len(phrase) >= 6 and phrase in text:
                    matched = True
                    break
        if not matched:
            # Strong single token (botox, invisalign, extraction…)
            for w in words:
                if len(w) >= 5 and w in text:
                    matched = True
                    break
        if not matched and len(words) >= 2:
            overlap = sum(1 for t in words if t in text)
            if overlap >= 2 and overlap / len(words) >= 0.4:
                matched = True
        if matched:
            hits.append(svc)
    return hits
