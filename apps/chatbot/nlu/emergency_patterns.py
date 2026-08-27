"""Canonical safety regex — single source of truth for emergency/symptom detection.

Previously duplicated (and drifting) across nlu/rules.py, nlu/entity_extract.py,
and routing/signals.py. Fail-closed: when in doubt, these patterns should match,
not miss. Two separate constants because they serve different purposes:

- EMERGENCY_RE: hard trigger for Intent.EMERGENCY (narrative cardiac + classic
  red flags, plus explicit self-harm/choking/unconscious).
- SYMPTOM_CUE_RE: softer signal used to gate non-emergency paths (e.g. "don't
  answer a business-hours question if the message also contains symptom
  language"), and as a pre/post-LLM symptom-cue check in the classifier.
"""

from __future__ import annotations

import re

EMERGENCY_RE = re.compile(
    r"\b("
    r"chest\s+pain|chest\s+(?:pressure|tightness|tight)|"
    r"pain\s+in\s+(?:my\s+)?chest|chest\s+hurts?|"
    r"(?:tight|crushing)\s+(?:pressure|pain)\s+in\s+(?:my\s+|his\s+|her\s+)?chest|"
    r"pressure\s+(?:in|into|to)\s+(?:my\s+|his\s+|her\s+)?(?:chest|arm)|"
    r"radiat(?:e|ing|es)?\s+(?:to\s+|down\s+)?(?:my\s+|his\s+|her\s+)?(?:left\s+)?arm|"
    r"(?:left\s+)?arm\s+(?:numb(?:ness)?|tingling|pain).{0,40}chest|"
    r"chest.{0,40}(?:left\s+)?arm\s+(?:numb|pain|tingl)|"
    r"can't\s+breathe|cannot\s+breathe|difficulty\s+breathing|"
    r"shortness\s+of\s+breath|heavy\s+pressure\s+on\s+(?:my\s+|his\s+|her\s+)?chest|"
    r"hard\s+to\s+swallow|trouble\s+swallowing|"
    r"tongue\s+(?:feels\s+huge|swelling|swollen)|"
    r"lips?\s+(?:are\s+)?tingling|"
    r"dizzy\s+and\s+faint|faint\s+and\s+dizzy|"
    r"heart\s+attack|stroke|"
    r"suicidal|kill\s+myself|severe\s+bleeding|unconscious|"
    r"choking|left\s+arm\s+numbness"
    r")\b",
    re.IGNORECASE,
)

# A handful of EMERGENCY_RE/SYMPTOM_CUE_RE terms are not anchored to a
# narrative symptom phrase the way "chest pain"/"can't breathe" are — real
# patient-question data (Phase 40) proved two of them, independently, fire a
# hard emergency override on purely informational questions: "What are the
# 4 causes of a stroke?" and, in a larger follow-up sample, "What is
# shortness of breath symptom of?". EXCEPTION_TERMS_RE below is exactly
# those proven terms — deliberately NOT generalized to every narrative
# phrase (chest pain, arm numbness, choking, suicidal/kill myself, severe
# bleeding, unconscious all stay unconditionally fail-closed; the cost of a
# missed genuine self-harm or cardiac-arrest disclosure is far worse than
# one unnecessary "call 911" nudge, and none of these has been proven prone
# to informational-question phrasing the way the two terms below are).
# EMERGENCY_RE and SYMPTOM_CUE_RE themselves are left untouched (each keeps
# its existing consumers and behavior); the pieces below are additive and
# used only by is_informational_emergency_mention(), which each hard-
# emergency-override call site (rules.py's _match_safety, entity_extract.
# py's has_symptom_cues/extract_emergency_symptoms) checks to carve out
# those two narrow, proven false-positives without weakening any other
# consumer of these two regexes (e.g. routing/signals.py's own, separate
# has_symptom_cues, which gates something lower-stakes and is untouched).
EMERGENCY_NARRATIVE_RE = re.compile(
    r"\b("
    r"chest\s+pain|chest\s+(?:pressure|tightness|tight)|"
    r"pain\s+in\s+(?:my\s+)?chest|chest\s+hurts?|"
    r"(?:tight|crushing)\s+(?:pressure|pain)\s+in\s+(?:my\s+|his\s+|her\s+)?chest|"
    r"pressure\s+(?:in|into|to)\s+(?:my\s+|his\s+|her\s+)?(?:chest|arm)|"
    r"radiat(?:e|ing|es)?\s+(?:to\s+|down\s+)?(?:my\s+|his\s+|her\s+)?(?:left\s+)?arm|"
    r"(?:left\s+)?arm\s+(?:numb(?:ness)?|tingling|pain).{0,40}chest|"
    r"chest.{0,40}(?:left\s+)?arm\s+(?:numb|pain|tingl)|"
    r"can't\s+breathe|cannot\s+breathe|"
    r"heavy\s+pressure\s+on\s+(?:my\s+|his\s+|her\s+)?chest|"
    r"hard\s+to\s+swallow|trouble\s+swallowing|"
    r"tongue\s+(?:feels\s+huge|swelling|swollen)|"
    r"lips?\s+(?:are\s+)?tingling|"
    r"dizzy\s+and\s+faint|faint\s+and\s+dizzy|"
    r"suicidal|kill\s+myself|severe\s+bleeding|unconscious|"
    r"choking|left\s+arm\s+numbness"
    r")\b",
    re.IGNORECASE,
)
EXCEPTION_TERMS_RE = re.compile(
    r"\b(?:heart\s+attack|stroke|shortness\s+of\s+breath|difficulty\s+breathing)\b",
    re.IGNORECASE,
)
INFORMATIONAL_EMERGENCY_QUESTION_RE = re.compile(
    r"^\s*(?:what|how|why|when|who|which|define|list)\b.{0,80}\b"
    r"(?:causes?|symptoms?|signs?|treat\w*|risk\s+factors?|definition|prevent\w*|diagnos\w*)\b",
    re.IGNORECASE,
)
EMERGENCY_EXPERIENTIAL_OVERRIDE_RE = re.compile(
    r"\b(?:i'?m|i\s+am|he'?s|she'?s|they'?re|my\s+\w+(?:\s+\w+)?\s+is)\s+having\b|"
    r"\bhaving\s+an?\s+(?:stroke|heart\s+attack)\b|"
    r"\bright\s+now\b|\bcurrently\b",
    re.IGNORECASE,
)
# SYMPTOM_CUE_RE's narrative-phrase list, minus EXCEPTION_TERMS_RE's terms —
# same relationship as EMERGENCY_NARRATIVE_RE above, for the "suicid" stem
# and "numbness in arm" variants SYMPTOM_CUE_RE adds.
SYMPTOM_NARRATIVE_RE = re.compile(
    r"\b("
    r"chest (?:pain|hurt|hurts|pressure|tight(?:ness)?)|"
    r"(?:tight|crushing) (?:pressure|pain) in (?:my |his |her )?chest|"
    r"pressure in (?:my |his |her )?chest|"
    r"pain (?:in|radiat\w*).{0,40}\barm|"
    r"radiat\w*.{0,30}\b(?:left )?arm|"
    r"can'?t breathe|cannot breathe|"
    r"heavy pressure on (?:my |his |her )?chest|"
    r"hard to swallow|trouble swallowing|"
    r"tongue (?:feels huge|swelling|swollen)|"
    r"lips? (?:are )?tingling|"
    r"dizzy and faint|faint and dizzy|"
    r"suicid|"
    r"severe bleeding|unconscious|choking|"
    r"numb(?:ness)? (?:in )?(?:my |left )?arm|"
    r"left arm numb"
    r")\b",
    re.I,
)


def is_informational_emergency_mention(text: str, narrative_re: re.Pattern[str]) -> bool:
    """True when the only emergency signal in `text` is a bare WH question
    about one of EXCEPTION_TERMS_RE's terms in general, not a live symptom
    report.

    `narrative_re` is whichever narrative-phrase set the caller's own hard
    trigger otherwise relies on (EMERGENCY_NARRATIVE_RE or
    SYMPTOM_NARRATIVE_RE) — if that also matches, or the message reads as
    someone currently experiencing it, this returns False and the caller's
    existing fail-closed behavior is unchanged.
    """
    text = text or ""
    return (
        not narrative_re.search(text)
        and EXCEPTION_TERMS_RE.search(text) is not None
        and INFORMATIONAL_EMERGENCY_QUESTION_RE.match(text) is not None
        and not EMERGENCY_EXPERIENTIAL_OVERRIDE_RE.search(text)
    )


SYMPTOM_CUE_RE = re.compile(
    r"\b("
    r"chest (?:pain|hurt|hurts|pressure|tight(?:ness)?)|"
    r"(?:tight|crushing) (?:pressure|pain) in (?:my |his |her )?chest|"
    r"pressure in (?:my |his |her )?chest|"
    r"pain (?:in|radiat\w*).{0,40}\barm|"
    r"radiat\w*.{0,30}\b(?:left )?arm|"
    r"can'?t breathe|cannot breathe|shortness of breath|"
    r"heavy pressure on (?:my |his |her )?chest|"
    r"hard to swallow|trouble swallowing|"
    r"tongue (?:feels huge|swelling|swollen)|"
    r"lips? (?:are )?tingling|"
    r"dizzy and faint|faint and dizzy|"
    r"heart attack|stroke|suicid|"
    r"severe bleeding|unconscious|choking|"
    r"numb(?:ness)? (?:in )?(?:my |left )?arm|"
    r"left arm numb"
    r")\b",
    re.I,
)
