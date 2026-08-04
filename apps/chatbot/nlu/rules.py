"""Deterministic NLU gates — safety + phatic before LLM; tiny fallback after.

Strong semantic regex remains available for legacy/tests via tier=strong but is
NOT used before the Small LLM when NLU_RULES_BEFORE_LLM=False (default).
"""

from __future__ import annotations

import re
from typing import Any

from apps.chatbot.nlu.entity_extract import (
    extract_emergency_symptoms,
    extract_entities,
    has_negation_near,
    looks_like_compound,
    merge_entities,
)
from apps.chatbot.nlu.schemas import Intent

_GREETING_EXACT = frozenset(
    {
        "hi", "hello", "hey", "hiya", "howdy", "greetings",
        "hi there", "hello there", "hey there", "hi all", "hello all",
        "good morning", "good afternoon", "good evening", "good day",
        "how are you", "how are you doing", "how are you today",
        "how r you", "how r u", "how are u", "how are ya",
        "how you doing", "how you doin", "how you been",
        "how have you been", "how's it going", "how is it going",
        "how are things", "how's your day", "how do you do",
        "hi how are you", "hi how are you doing",
        "hello how are you", "hey how are you",
        "yo", "sup", "whats up", "what's up", "wassup", "wazzup",
        "waddup", "whassup", "heya", "hey hey", "yoo", "ayy",
        "hola", "bonjour", "namaste", "salam", "salut",
    }
)

_GREETING_RE = re.compile(
    r"^("
    r"hi+|hey+|hello+|hiya|howdy|greetings|yo+|"
    r"good\s+(?:morning|afternoon|evening|day)"
    r")"
    r"(?:\s*[,!]?\s*(?:there|folks|everyone|all|doc|friend))?"
    r"(?:\s*[,!?.]?\s*how\s+(?:are|r|is)\s+(?:you|u|ya)(?:\s+doing|\s+today)?)?"
    r"[!.?]*$",
    re.IGNORECASE,
)

_HOW_ARE_YOU_RE = re.compile(
    r"^how\s+(?:are|r)\s+(?:you|u|ya)(?:\s+doing|\s+today|\s+been)?\?*$",
    re.IGNORECASE,
)

_FAREWELL_EXACT = frozenset(
    {
        "bye", "bye bye", "byee", "byeee",
        "goodbye", "good bye",
        "see you", "see ya", "see u", "cya", "cu",
        "take care", "later", "later!", "laters",
        "ttyl", "ttyl!", "talk later",
        "have a good day", "have a great day",
        "good night", "goodnight",
        "i'm leaving", "im leaving", "gotta go", "gotta go!",
        "got to go", "i have to go",
    }
)

_THANKS_EXACT = frozenset(
    {
        "thanks", "thank you", "thank u", "thankyou", "thank you!",
        "thanks!", "thx", "ty", "tysm", "tyvm", "thnx", "thanx",
        "cheers", "appreciated", "appreciate it", "much appreciated",
        "thanks a lot", "thanks a bunch", "thanks so much",
        "many thanks", "gracias", "danke",
    }
)

_OFF_TOPIC_EXACT = frozenset(
    {
        "lol", "lmao", "lmfao", "haha", "hahaha", "😂", "xd",
        "ok", "okay", "k", "kk", "cool", "nice", "ok cool",
        "interesting", "wow", "omg", "oh my god", "oh wow",
        "no worries", "no problem", "np", "nvm", "nevermind",
    }
)

# Fail-closed emergency — narrative cardiac + classic red flags
_EMERGENCY_RE = re.compile(
    r"\b("
    r"chest\s+pain|chest\s+(?:pressure|tightness|tight)|"
    r"pain\s+in\s+(?:my\s+)?chest|chest\s+hurts?|"
    r"(?:tight|crushing)\s+(?:pressure|pain)\s+in\s+(?:my\s+|his\s+|her\s+)?chest|"
    r"pressure\s+(?:in|into|to)\s+(?:my\s+|his\s+|her\s+)?(?:chest|arm)|"
    r"radiat(?:e|ing|es)?\s+(?:to\s+|down\s+)?(?:my\s+|his\s+|her\s+)?(?:left\s+)?arm|"
    r"(?:left\s+)?arm\s+(?:numb(?:ness)?|tingling|pain).{0,40}chest|"
    r"chest.{0,40}(?:left\s+)?arm\s+(?:numb|pain|tingl)|"
    r"can't\s+breathe|cannot\s+breathe|difficulty\s+breathing|"
    r"shortness\s+of\s+breath|heart\s+attack|stroke|"
    r"suicidal|kill\s+myself|severe\s+bleeding|unconscious|"
    r"choking|left\s+arm\s+numbness"
    r")\b",
    re.IGNORECASE,
)

_BOOKING_COMMIT_EXACT = frozenset(
    {
        "start booking",
        "book appointment",
        "book an appointment",
        "i would like to book an appointment",
        "schedule an appointment",
        "i wanna book something",
    }
)

_OFF_TOPIC_ABUSE_RE = re.compile(
    r"\b(fuck|shit|damn|asshole|bitch)\b",
    re.IGNORECASE,
)


def _empty_entities() -> dict[str, Any]:
    return {
        "doctor_name": None,
        "specialty": None,
        "service": None,
        "insurance_provider": None,
        "date": None,
        "time": None,
        "patient_name": None,
        "location": None,
        "symptom": None,
    }


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent": Intent.UNKNOWN.value,
        "secondary_intents": [],
        "confidence": 0.85,
        "entities": _empty_entities(),
        "needs_sql": False,
        "needs_vector": False,
        "needs_llm": False,
        "can_respond_directly": False,
        "is_emergency": False,
        "is_off_topic": False,
        "clarification_needed": False,
        "clarification_question": None,
        "reasoning_short": "Rule-based classification",
        "service_filter_mode": "none",
        "sql_tool": None,
        "document_needed": False,
    }
    payload.update(overrides)
    return payload


def _normalize(text: str) -> str:
    text = text.strip().lower()
    if text.startswith("message:"):
        text = text[8:].strip()
    text = re.sub(r"[^\w\s'?-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    replacements = (
        (r"\bapointment\b", "appointment"),
        (r"\bappt\b", "appointment"),
        (r"\bdocotr\b", "doctor"),
        (r"\bhoures\b", "hours"),
        (r"\bhrs\b", "hours"),
        (r"\binsurence\b", "insurance"),
    )
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    return text


def _with_entities(message: str, payload: dict[str, Any]) -> dict[str, Any]:
    extracted = extract_entities(message)
    payload["entities"] = merge_entities(payload.get("entities"), extracted)
    return payload


def try_rule_classify(
    message: str,
    *,
    tier: str = "all",
) -> dict[str, Any] | None:
    """
    Deterministic classifier gates.

    tier: fast | safety | strong | fallback | all
      - fast/safety: always safe for pre-LLM
      - strong: legacy semantic regex (opt-in via NLU_RULES_BEFORE_LLM)
      - fallback: tiny post-LLM recovery only
    """
    text = _normalize(message)
    if not text:
        return None

    if tier in {"fast", "all"}:
        hit = _match_fast(text)
        if hit:
            return hit

    if tier in {"safety", "all", "strong", "fallback"}:
        hit = _match_safety(message, text)
        if hit:
            return hit

    if tier in {"strong", "all"}:
        if tier != "fallback" and looks_like_compound(message):
            return None
        hit = _match_strong_legacy(message, text, broad=False)
        if hit:
            return _with_entities(message, hit)

    if tier in {"fallback", "all"}:
        hit = _match_fallback_tiny(message, text)
        if hit:
            return _with_entities(message, hit)

    return None


def _match_fast(text: str) -> dict[str, Any] | None:
    if text in _GREETING_EXACT or _GREETING_RE.fullmatch(text) or _HOW_ARE_YOU_RE.fullmatch(text):
        return _base_payload(
            intent=Intent.GREETING.value,
            confidence=0.99,
            can_respond_directly=True,
            reasoning_short="Greeting (rule)",
            _classifier_source="rules_fast",
        )

    if text in _FAREWELL_EXACT or text.rstrip("!.?") in _FAREWELL_EXACT:
        return _base_payload(
            intent=Intent.FAREWELL.value,
            confidence=0.99,
            can_respond_directly=True,
            reasoning_short="Farewell (rule)",
            _classifier_source="rules_fast",
        )

    if text in _THANKS_EXACT or text.rstrip("!.?") in _THANKS_EXACT:
        return _base_payload(
            intent=Intent.FAREWELL.value,
            confidence=0.99,
            can_respond_directly=True,
            reasoning_short="Thanks (rule)",
            _classifier_source="rules_fast",
        )

    if text in _OFF_TOPIC_EXACT:
        return _base_payload(
            intent=Intent.OFF_TOPIC.value,
            confidence=0.95,
            is_off_topic=True,
            can_respond_directly=True,
            reasoning_short="Trivial off-topic (rule)",
            _classifier_source="rules_fast",
        )

    return None


def _match_safety(original: str, text: str) -> dict[str, Any] | None:
    """Fail-closed emergency / self-harm — never wait for Small LLM."""
    if _EMERGENCY_RE.search(text):
        symptoms = extract_emergency_symptoms(original)
        if not symptoms:
            # Narrative forms may not be in the short symptom list
            symptoms = ["chest symptoms"] if re.search(r"\bchest\b", text) else ["emergency symptoms"]
        return _base_payload(
            intent=Intent.EMERGENCY.value,
            confidence=0.99,
            is_emergency=True,
            can_respond_directly=True,
            entities={
                **_empty_entities(),
                "symptom": symptoms or None,
            },
            reasoning_short="Emergency keywords (rule)",
            _classifier_source="rules_safety",
        )

    if _OFF_TOPIC_ABUSE_RE.search(text) and len(text.split()) <= 6:
        return _base_payload(
            intent=Intent.OFF_TOPIC.value,
            confidence=0.95,
            is_off_topic=True,
            can_respond_directly=True,
            reasoning_short="Abusive/off-topic (rule)",
            _classifier_source="rules_safety",
        )

    return None


def _match_fallback_tiny(original: str, text: str) -> dict[str, Any] | None:
    """Post-LLM tiny recovery — booking commit phrases only."""
    stripped = text.rstrip("!.?")
    if stripped in _BOOKING_COMMIT_EXACT or "start booking" in text:
        return _base_payload(
            intent=Intent.BOOK_APPOINTMENT.value,
            confidence=0.85,
            needs_sql=True,
            needs_llm=False,
            reasoning_short="Booking commit fallback (rule)",
            _classifier_source="rules_fallback",
        )
    return None


def _match_strong_legacy(
    original: str,
    text: str,
    *,
    broad: bool = False,
) -> dict[str, Any] | None:
    """
    Legacy semantic regex — kept for tests / NLU_RULES_BEFORE_LLM=True opt-in.
    Production Small-LLM-first path does not call this before the LLM.
    """
    # Off-topic keyword sets — only when no clinic hint
    _clinic_hint = re.compile(
        r"\b(doctor|dr\.?|physician|appointment|book|schedule|insurance|"
        r"clinic|hospital|specialist|symptom|pain|diagnosis|prescription|"
        r"medication|service|hours|location)\b",
        re.IGNORECASE,
    )
    _OFF_TOPIC_FOOD_RE = re.compile(
        r"\b(pizza|burger|biryani|sushi|pasta|recipe|cook|restaurant|meal|"
        r"dinner|lunch|breakfast|food|hungry|eat\b|cafe|menu)\b",
        re.IGNORECASE,
    )
    _OFF_TOPIC_SPORTS_RE = re.compile(
        r"\b(fifa|cricket|football|soccer|basketball|nba|nfl|ipl|world cup|"
        r"tennis|golf|rugby|match|player|messi|ronaldo|lebron)\b",
        re.IGNORECASE,
    )
    if not _clinic_hint.search(text):
        for pattern, label in (
            (_OFF_TOPIC_FOOD_RE, "food"),
            (_OFF_TOPIC_SPORTS_RE, "sports"),
        ):
            if pattern.search(text):
                return _base_payload(
                    intent=Intent.OFF_TOPIC.value,
                    confidence=0.95,
                    is_off_topic=True,
                    can_respond_directly=True,
                    reasoning_short=f"Off-topic ({label}) (rule)",
                    _classifier_source="rules_strong",
                )

    if has_negation_near(text, "reschedule") or has_negation_near(text, "cancel"):
        if not broad:
            return None

    if (
        re.search(r"\b(cancel|cancellation)\b", text)
        and re.search(r"\b(appointment|visit|meeting)\b", text)
        and not has_negation_near(text, "cancel")
        and not re.search(
            r"\b(policy|policies|fee|fees|how (?:far|much)|what (?:is|are) your|refund|deposit)\b",
            text,
        )
    ):
        return _base_payload(
            intent=Intent.CANCEL_APPOINTMENT.value,
            confidence=0.9,
            needs_sql=True,
            needs_llm=False,
            sql_tool="appointments",
            reasoning_short="Cancel appointment (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(reschedule|re-?schedule)\b", text) and not has_negation_near(
        text, "reschedule"
    ):
        return _base_payload(
            intent=Intent.RESCHEDULE_APPOINTMENT.value,
            confidence=0.9,
            needs_sql=True,
            needs_llm=False,
            reasoning_short="Reschedule (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(book|schedule|make|wanna book)\b", text) and re.search(
        r"\b(appointment|visit|something)\b", text
    ) or re.search(r"\bbook .{0,40}\bwith\b", text):
        return _base_payload(
            intent=Intent.BOOK_APPOINTMENT.value,
            confidence=0.92,
            needs_sql=True,
            needs_llm=False,
            reasoning_short="Book appointment (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(slot|slots|available|availability)\b", text) and re.search(
        r"\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|"
        r"saturday|sunday|morning|afternoon|evening|doctor|dr)\b",
        text,
    ):
        return _base_payload(
            intent=Intent.DOCTOR_AVAILABILITY.value,
            confidence=0.9,
            needs_sql=True,
            needs_vector=False,
            needs_llm=False,
            sql_tool="doctors",
            reasoning_short="Availability (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(
        r"\b(find (?:me )?(?:a |the )?(?:doctor|dentist|physician)|"
        r"help me find (?:a )?(?:doctor|dentist)|list (?:of )?(?:doctors|dentists|specialt(?:y|ies))|"
        r"show (me )?(the )?(?:doctors|dentists)|who (are|is) (your|the) (?:doctors?|dentists?)|"
        r"looking for a (?:doctor|dentist)|need a (?:doctor|dentist)|"
        r"(?:doctors?|dentists?) (do you )?have|"
        r"what special(?:t(?:y|ies)|ities)|special(?:t(?:y|ies)|ities) (?:do you )?(?:offer|provide|have))\b",
        text,
    ) and not re.search(r"\b(book|schedule|appointment)\b", text):
        specialty_list = bool(
            re.search(r"\bspecial(?:t(?:y|ies)|ities)\b", text)
        )
        return _base_payload(
            intent=Intent.DOCTOR_SEARCH.value,
            confidence=0.93,
            needs_sql=True,
            needs_vector=False,
            needs_llm=False,
            sql_tool="specialties" if specialty_list else "doctors",
            reasoning_short="Doctor/specialty search (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(
        r"\b(where (are you|is the clinic)|address|location|directions|parking)\b",
        text,
    ):
        return _base_payload(
            intent=Intent.CLINIC_LOCATION.value,
            confidence=0.9,
            needs_sql=True,
            needs_vector=False,
            needs_llm=False,
            sql_tool="location",
            reasoning_short="Clinic location (rule)",
            _classifier_source="rules_strong",
        )

    # Business hours BEFORE FAQ — "what are your hours" must not become FAQ
    if re.search(
        r"\b((?:clinic |office |your |business )?hours?|open|close|closing|"
        r"when (?:are you|do you) open|what time (?:do you|are you) (?:open|close)|"
        r"what (?:are|is) your (?:clinic |office |business )?hours)\b",
        text,
    ) and not broad and not re.search(
        r"\b(for how many hours|how many hours|how much hours|how long|"
        r"hours? (?:after|before|per day|does it take)|"
        r"take[s]? (?:to )?(?:do|for)|post[- ]?op|gauze|straw|smoking|spitting|"
        r"arrive|arrival|deposit|fee|treatment|procedure|screening|cleaning|"
        r"chest|hurt|pressure|arm|numb|breathe|symptom|sick)\b",
        text,
    ):
        return _base_payload(
            intent=Intent.CLINIC_HOURS.value,
            confidence=0.88,
            needs_sql=True,
            needs_vector=False,
            needs_llm=False,
            sql_tool="hours",
            reasoning_short="Clinic hours (rule)",
            _classifier_source="rules_strong",
        )

    # Knowledge / policy BEFORE fee/pricing (cancel fee must not become service list)
    if re.search(
        r"\b(referral|referrals|do i need|policy|protocols?|how does|"
        r"cancellation policy|cancel\w* (?:fee|policy)|"
        r"cancel\w*.{0,30}fee|fee.{0,30}cancel\w*|"
        r"charged a fee|get charged|"
        r"arrive|arrival|how (?:early|soon)|deposit|down payment|refund|"
        r"post[- ]?op|after (?:surgery|procedure|extraction)|"
        r"replacement (?:fee|tray|cost)|emergency (?:number|line|contact)|"
        r"membership|prorat\w*|reactivat\w*)\b",
        text,
    ) and (
        re.search(
            r"\b(specialists?|referral|referrals|insurance|visit|appointment|"
            r"cancel\w*|booking|policy|protocols?|early|arrive|"
            r"deposit|payment|fee|gauze|bleeding|instructions?|restrictions?|"
            r"refund|membership|charged|dues)\b",
            text,
        )
        or re.search(r"\b(how|what|when|should|tell)\b", text)
    ):
        return _base_payload(
            intent=Intent.FAQ.value,
            confidence=0.85,
            needs_vector=True,
            needs_llm=True,
            document_needed=True,
            reasoning_short="FAQ / policy (rule)",
            _classifier_source="rules_strong",
        )

    # Cost / duration — skip when knowledge frames already handled
    if (
        re.search(
            r"\b(cost|price|pricing|fee|fees|charge|charges|how long|duration|"
            r"how much time|how much hours?|how many hours?)\b",
            text,
        )
        or re.search(r"\bhow much(?: does| is| for| to)\b", text)
        or re.search(r"\bhours?\s+does\s+it\s+take\b|\btake[s]?\s+(?:to\s+)?(?:do|for)\b", text)
    ) and not re.search(
        r"\b(insurance|copay|deductible|coverage|early|arrive|"
        r"cancel\w*|refund|deposit|policy|acid|poison|dissolve|charged)\b",
        text,
    ):
        return _base_payload(
            intent=Intent.PRICING.value,
            confidence=0.86,
            needs_sql=True,
            needs_vector=False,
            needs_llm=False,
            sql_tool="pricing",
            service_filter_mode="named",
            reasoning_short="Service price/duration (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(
        r"\b(what services|which services|services do you|list (?:of )?services|"
        r"services (?:do you )?(?:offer|provide|have)|medical spa|"
        r"what (?:urgent care|specialt)\b)",
        text,
    ):
        return _base_payload(
            intent=Intent.SERVICES_OFFERED.value,
            confidence=0.9,
            needs_sql=True,
            needs_vector=False,
            needs_llm=False,
            sql_tool="services",
            service_filter_mode="none",
            reasoning_short="Services offered (rule)",
            _classifier_source="rules_strong",
        )

    has_insurance_word = bool(re.search(r"\binsurance\b", text))
    has_accept_frame = bool(
        re.search(r"\b(accept|take|cover|covered|coverage|insured)\b", text)
    )
    has_brand = bool(
        re.search(
            r"\b(blue\s*cross|aetna|cigna|humana|kaiser|medicare|medicaid|"
            r"medi[- ]?cal|denti[- ]?cal|united\s*health|anthem|oscar|molina|"
            r"delta\s*dental|metlife|guardian)\b",
            text,
        )
    )
    if (has_insurance_word and has_accept_frame) or (has_insurance_word and has_brand) or (
        has_accept_frame and has_brand
    ):
        if re.search(r"\b(years?\s+old|child|son|daughter|pediatric)\b", text) and not has_brand:
            return None
        intent = (
            Intent.INSURANCE_VERIFICATION.value
            if re.search(r"\b(id|number|member|policy|my plan)\b", text)
            else Intent.INSURANCE_ACCEPTED.value
        )
        return _base_payload(
            intent=intent,
            confidence=0.88 if not broad else 0.75,
            needs_sql=True,
            needs_vector=False,
            needs_llm=False,
            sql_tool="insurance",
            reasoning_short="Insurance query (rule)",
            _classifier_source="rules_strong" if not broad else "rules_fallback",
        )

    if broad:
        if re.search(r"\b(doctor|physician|dr\.?)\b", text):
            return _base_payload(
                intent=Intent.DOCTOR_SEARCH.value,
                confidence=0.75,
                needs_sql=True,
                needs_vector=False,
                needs_llm=False,
                sql_tool="doctors",
                reasoning_short="Doctor query fallback (rule)",
                _classifier_source="rules_fallback",
            )
        if re.search(r"\b(book|schedule|make)\b", text) and re.search(
            r"\b(appointment|visit|slot)\b", text
        ):
            return _base_payload(
                intent=Intent.BOOK_APPOINTMENT.value,
                confidence=0.7,
                needs_sql=True,
                needs_llm=False,
                clarification_needed=False,
                reasoning_short="Appointment book fallback (rule)",
                _classifier_source="rules_fallback",
            )

    return None
