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
