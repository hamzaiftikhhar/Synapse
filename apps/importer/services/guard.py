"""Refuse to import files that look like patient/clinical records instead
of clinic configuration data (providers/services/specialties).

Runs on column headers only, before any sample rows are captured or the
LLM is ever called — patient data must not reach the mapper, let alone the
LLM API.
"""

import re

# Deliberately compound/specific terms so legitimate provider/service
# columns ("Name", "Insurance", "Rate") never false-positive.
_PATIENT_DATA_MARKERS = {
    "date of birth",
    "dob",
    "birth date",
    "birthdate",
    "ssn",
    "social security",
    "mrn",
    "medical record number",
    "patient name",
    "patient id",
    "diagnosis",
    "icd-10",
    "icd10",
    "icd 10",
    "cpt code",
    "allergy",
    "allergies",
    "medication",
    "medications",
    "prescription",
    "insurance id",
    "insurance number",
    "member id",
    "policy number",
    "emergency contact",
    "guardian",
    "next of kin",
    "blood type",
    "chief complaint",
    "treatment notes",
    "procedure code",
    "visit date",
    "admission date",
    "discharge date",
}


def _normalize(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower())


# Payer-list spreadsheets often include an "Insurance ID" / NAIC column.
# Those headers are PHI on a *patient* file, but they are setup metadata
# when the owner is importing accepted plans — skip them only then.
_INSURANCE_SETUP_HEADERS = {"insurance id", "insurance number"}


def looks_like_patient_data(
    headers: list[str], record_type: str | None = None
) -> list[str]:
    """Returns the subset of headers that matched a patient-data marker
    (empty list = safe to proceed)."""
    skipped = _INSURANCE_SETUP_HEADERS if record_type == "insurance" else set()
    matches = []
    for header in headers:
        normalized = _normalize(header)
        if any(
            marker in normalized
            for marker in _PATIENT_DATA_MARKERS
            if marker not in skipped
        ):
            matches.append(header)
    return matches
