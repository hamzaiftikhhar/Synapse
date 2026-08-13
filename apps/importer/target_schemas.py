"""Canonical target fields per import record type.

This is the fixed catalog the LLM/heuristic column mapper is allowed to map
onto — it can never invent a target field outside this list (see
apps/importer/services/mapper.py), and it drives the deterministic type
coercion in apps/importer/services/extractor.py.
"""

from apps.importer.models import ImportRecordType

FieldSpec = dict[str, bool | str | int]

# type: "string" | "string_list" | "integer" | "money_cents"
PROVIDER_FIELDS: dict[str, FieldSpec] = {
    "full_name": {"required": True, "type": "string"},
    "title": {"required": False, "type": "string"},
    "bio": {"required": False, "type": "string"},
    "languages": {"required": False, "type": "string_list"},
}

SERVICE_FIELDS: dict[str, FieldSpec] = {
    "name": {"required": True, "type": "string"},
    "description": {"required": False, "type": "string"},
    "category": {"required": False, "type": "string"},
    "duration_min": {"required": False, "type": "integer", "default": 30},
    "price_cents": {"required": False, "type": "money_cents"},
}

SPECIALTY_FIELDS: dict[str, FieldSpec] = {
    "name": {"required": True, "type": "string"},
    "description": {"required": False, "type": "string"},
}

INSURANCE_FIELDS: dict[str, FieldSpec] = {
    "provider_name": {"required": True, "type": "string"},
    "plan_name": {"required": False, "type": "string"},
    "plan_type": {"required": False, "type": "string"},
}

TARGET_FIELDS: dict[str, dict[str, FieldSpec]] = {
    ImportRecordType.PROVIDERS: PROVIDER_FIELDS,
    ImportRecordType.SERVICES: SERVICE_FIELDS,
    ImportRecordType.SPECIALTIES: SPECIALTY_FIELDS,
    ImportRecordType.INSURANCE: INSURANCE_FIELDS,
}


def target_fields_for(record_type: str) -> dict[str, FieldSpec]:
    return TARGET_FIELDS.get(record_type, {})


def required_fields_for(record_type: str) -> set[str]:
    return {
        field
        for field, spec in target_fields_for(record_type).items()
        if spec.get("required")
    }
