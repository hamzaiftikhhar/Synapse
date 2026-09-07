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

# Live-confirmed P0 bug (pre-production safety review): the plain word
# "suicide" -- arguably the single most common way someone discloses
# suicidal intent -- matched NEITHER this file's old EMERGENCY_RE (which
# only had the adjective "suicidal" and "kill myself") NOR its SYMPTOM_CUE_RE/
# SYMPTOM_NARRATIVE_RE's bare "suicid" stem, which turns out to have never
# matched anything at all: `\bsuicid\b` requires a word boundary immediately
# after "suicid", but "suicide" and "suicidal" both continue with another
# letter right there (d->e, d->a) -- there IS no boundary there, confirmed
# empirically, not assumed. This file's own fail-closed philosophy ("a
# missed genuine self-harm... disclosure is far worse than one unnecessary
# 911 nudge") was being violated by its own regex bug: a real disclosure
# using the plain word "suicide" depended entirely on a live LLM call
# correctly classifying it -- exactly what this file's docstring says the
# deterministic layer should never have to rely on. Live-reproduced: with
# the real chatbot, an actual OpenAI API hiccup on one turn caused a
# suicide disclosure to fall through to a generic rules-fallback
# clarification instead of the emergency response, precisely because nothing
# deterministic caught it first.
#
# _SELF_HARM_FRAGMENT is now the single canonical self-harm/suicide pattern
# fragment, interpolated into EMERGENCY_RE/EMERGENCY_NARRATIVE_RE (the hard
# trigger) and SYMPTOM_CUE_RE/SYMPTOM_NARRATIVE_RE (the softer gate) below,
# and exported as SELF_HARM_RE for response_templates.py/engine.py to pick
# the mental-health-specific safety message (988 Suicide & Crisis Lifeline)
# instead of the generic physical-emergency one (911) -- one definition,
# not four independently-drifting copies (this file already had two;
# response_templates.py had a third, broader one maintained separately with
# no word-boundary anchoring at all, i.e. plain substring containment,
# never actually wired into the live response path at all — see
# engine.py's safety_message fix in the same change).
#
# Includes a handful of common misspellings ("sucide", "suicde", "suiside",
# "suicidle") found via live testing — none of these contain "suicid" as a
# substring (letters transposed or dropped), so `suicid\w*` alone does not
# catch them; a real user typed "i want to do sucide" during this review.
# Not a general fuzzy-typo engine (that would be over-engineering for one
# word) — a short, explicit list of the misspellings actually observed or
# obviously plausible, same scope as this session's other typo-tolerance
# fixes (e.g. common dental-term typos in booking/discovery.py).
#
# Deliberately excludes two words from the older, superseded
# response_templates.py list that are dangerous false-positive traps in a
# clinical/administrative context: "jump" (jump rope, jump the queue,
# jump-start) and "slit" ("slit lamp" is a real, common ophthalmology exam
# device/procedure -- a patient asking about one would otherwise get a
# suicide-crisis response). "overdose" is kept: an overdose is time-critical
# regardless of intent, so it stays fail-closed like every other term here.
_SELF_HARM_FRAGMENT = (
    r"suicid\w*|sucide|suicde|suiside|suicidle|kill{SP}myself|"
    r"end{SP}(?:my|his|her|their|this){SP}life|"
    r"harm{SP}myself|self[\s-]harm|"
    r"don'?t{SP}want{SP}to{SP}live|want{SP}to{SP}die|"
    r"wish{SP}i{SP}(?:was|were){SP}dead|"
    r"take{SP}my{SP}(?:own{SP})?life|hurt{SP}myself|"
    r"can'?t{SP}go{SP}on|better{SP}off{SP}dead|no{SP}reason{SP}to{SP}live|"
    r"cut{SP}myself|shoot{SP}myself|overdose"
)
# Two renderings of the fragment: `\s+` for the \s+-spaced regexes below,
# plain " " for the single-space-spaced ones -- same word list either way.
SELF_HARM_RE = re.compile(
    r"\b(" + _SELF_HARM_FRAGMENT.format(SP=r"\s+") + r")\b", re.IGNORECASE
)
_SELF_HARM_SINGLE_SPACE = _SELF_HARM_FRAGMENT.format(SP=" ")
_SELF_HARM_MULTI_SPACE = _SELF_HARM_FRAGMENT.format(SP=r"\s+")


def is_self_harm_mention(text: str) -> bool:
    """True when `text` names suicide/self-harm specifically (not just any
    emergency) -- used to choose the 988-crisis-line safety message over
    the generic 911-physical-emergency one. Never used to decide *whether*
    something is an emergency (that stays EMERGENCY_RE's job) -- only which
    of the two safety messages to show once it already is one.
    """
    return bool(SELF_HARM_RE.search(text or ""))


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
    + _SELF_HARM_MULTI_SPACE
    + r"|"
    r"severe\s+bleeding|unconscious|"
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
# phrase (chest pain, arm numbness, choking, self-harm terms, severe
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
    + _SELF_HARM_MULTI_SPACE
    + r"|severe\s+bleeding|unconscious|"
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
# same relationship as EMERGENCY_NARRATIVE_RE above.
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
    + _SELF_HARM_SINGLE_SPACE
    + r"|"
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
    r"heart attack|stroke|"
    + _SELF_HARM_SINGLE_SPACE
    + r"|"
    r"severe bleeding|unconscious|choking|"
    r"numb(?:ness)? (?:in )?(?:my |left )?arm|"
    r"left arm numb"
    r")\b",
    re.I,
)
