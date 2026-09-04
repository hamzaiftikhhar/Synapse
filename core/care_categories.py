"""Canonical, curated specialty categories shared across the platform.

These are standardized *internal* values, not a translation mechanism —
they normalize what a clinic's free-text `Specialty.name` conceptually is
("General Dentistry" -> category `DENTISTRY`), matching how real
production systems bind provider specialties to a controlled vocabulary
(FHIR's PractitionerRole.specialty is bound to the NUCC Health Provider
Taxonomy) rather than leaving every clinic's specialty an arbitrary,
independently-spelled string.

Deliberately a curated ~28-value list, not the full ~880-code NUCC set —
adopting the full taxonomy would be over-engineering for this product's
current stage (the same judgment already applied to FHIR PractitionerRole/
Location elsewhere in this codebase); the concept (a small controlled
vocabulary) is what's valuable, not exhaustive real-world coverage.

Translating a patient's own words ("heart doctor", "tooth pain") into one
of these values is explicitly NOT this module's job — that stays the
responsibility of the existing deterministic symptom map
(apps/chatbot/booking/discovery.py::_SYMPTOM_MAP) and, as a fallback, NLU
semantic understanding. This module only defines the controlled target
vocabulary those mechanisms resolve into, and the exact-match comparison
against it never uses fuzzy string logic.
"""

from __future__ import annotations

from django.db import models


class CareCategory(models.TextChoices):
    PRIMARY_CARE = "Primary Care", "Primary Care"
    CARDIOLOGY = "Cardiology", "Cardiology"
    DERMATOLOGY = "Dermatology", "Dermatology"
    GASTROENTEROLOGY = "Gastroenterology", "Gastroenterology"
    NEUROLOGY = "Neurology", "Neurology"
    PSYCHIATRY_MENTAL_HEALTH = "Psychiatry / Mental Health", "Psychiatry / Mental Health"
    OBGYN = "OB-GYN", "OB-GYN"
    ORTHOPEDICS = "Orthopedics", "Orthopedics"
    ENT = "ENT", "ENT"
    OPHTHALMOLOGY = "Ophthalmology", "Ophthalmology"
    DENTISTRY = "Dentistry", "Dentistry"
    PEDIATRICS = "Pediatrics", "Pediatrics"
    ENDOCRINOLOGY = "Endocrinology", "Endocrinology"
    PULMONOLOGY = "Pulmonology", "Pulmonology"
    UROLOGY = "Urology", "Urology"
    NEPHROLOGY = "Nephrology", "Nephrology"
    ONCOLOGY = "Oncology", "Oncology"
    SLEEP_MEDICINE = "Sleep Medicine", "Sleep Medicine"
    PAIN_MANAGEMENT = "Pain Management", "Pain Management"
    RHEUMATOLOGY = "Rheumatology", "Rheumatology"
    ALLERGY_IMMUNOLOGY = "Allergy & Immunology", "Allergy & Immunology"
    PODIATRY = "Podiatry", "Podiatry"
    SURGERY = "Surgery", "Surgery"
    AESTHETICS_COSMETIC = "Aesthetics / Cosmetic", "Aesthetics / Cosmetic"
    PHYSICAL_THERAPY = "Physical Therapy", "Physical Therapy"
    LABORATORY_DIAGNOSTICS = "Laboratory / Diagnostics", "Laboratory / Diagnostics"
    OTHER = "Other", "Other"


# The existing deterministic symptom->specialty-hint keyword table
# (_SYMPTOM_MAP) predates this controlled vocabulary and uses loose hint
# words ("cardiology", "general practice", "family") rather than the exact
# canonical strings above. This is the (also deterministic -- no fuzzy
# matching) translation from those existing hint words to the canonical
# category they conceptually mean, so a clinic's Specialty.category can be
# matched by plain equality, not string-similarity guessing.
HINT_TO_CATEGORY: dict[str, str] = {
    "neurology": CareCategory.NEUROLOGY,
    "neurologist": CareCategory.NEUROLOGY,
    "cardiology": CareCategory.CARDIOLOGY,
    "cardiologist": CareCategory.CARDIOLOGY,
    "gastroenterology": CareCategory.GASTROENTEROLOGY,
    "dermatology": CareCategory.DERMATOLOGY,
    "dermatologist": CareCategory.DERMATOLOGY,
    "psychiatry": CareCategory.PSYCHIATRY_MENTAL_HEALTH,
    "psychiatrist": CareCategory.PSYCHIATRY_MENTAL_HEALTH,
    "psychology": CareCategory.PSYCHIATRY_MENTAL_HEALTH,
    "ob-gyn": CareCategory.OBGYN,
    "obstetrics": CareCategory.OBGYN,
    "gynecology": CareCategory.OBGYN,
    "women": CareCategory.OBGYN,
    "orthopedic": CareCategory.ORTHOPEDICS,
    "orthopedics": CareCategory.ORTHOPEDICS,
    "sports medicine": CareCategory.ORTHOPEDICS,
    "ent": CareCategory.ENT,
    "otolaryngology": CareCategory.ENT,
    "ophthalmology": CareCategory.OPHTHALMOLOGY,
    "optometry": CareCategory.OPHTHALMOLOGY,
    "eye": CareCategory.OPHTHALMOLOGY,
    "dentistry": CareCategory.DENTISTRY,
    "dental": CareCategory.DENTISTRY,
    "general dentistry": CareCategory.DENTISTRY,
    "cosmetic dentistry": CareCategory.DENTISTRY,
    "restorative dentistry": CareCategory.DENTISTRY,
    "family dentistry": CareCategory.DENTISTRY,
    "primary care": CareCategory.PRIMARY_CARE,
    "general practice": CareCategory.PRIMARY_CARE,
    "internal medicine": CareCategory.PRIMARY_CARE,
    "family": CareCategory.PRIMARY_CARE,
}
