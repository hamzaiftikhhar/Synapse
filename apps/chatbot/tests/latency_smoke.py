#!/usr/bin/env python
"""Optional latency smoke — SQL/direct lanes should stay under 3s without network LLM.

Usage (with Django settings + demo clinic):
  .venv/bin/python manage.py shell < apps/chatbot/tests/latency_smoke.py

Or run as a module after DJANGO_SETTINGS_MODULE is set.
This script is manual/CI-optional and skips if the demo clinic is missing.
"""

from __future__ import annotations

import time


def run() -> int:
    import django

    django.setup()
    from apps.clinics.models import Clinic
    from apps.chatbot.engine import ChatEngine

    clinic = Clinic.objects.filter(slug="acme-cardiology").first()
    if clinic is None:
        print("SKIP: demo clinic acme-cardiology not found")
        return 0

    engine = ChatEngine()
    cases = [
        ("direct", "Hi"),
        ("sql_fast", "Help me find a doctor"),
        ("sql_fast", "What are your hours?"),
        ("sql_fast", "Do you accept Aetna?"),
        ("booking", "I would like to book an appointment"),
    ]
    failures = 0
    for expected_lane, message in cases:
        t0 = time.perf_counter()
        result = engine.process(clinic=clinic, message=message, session=None)
        ms = (time.perf_counter() - t0) * 1000
        ok = result.lane == expected_lane or (
            expected_lane == "sql_fast" and result.lane == "sql_fast"
        )
        # Budget: SQL/direct without Large LLM should be under 3s locally
        budget_ok = ms < 3000 or result.lane == "vector_rag"
        status = "OK" if ok and budget_ok else "FAIL"
        if status == "FAIL":
            failures += 1
        print(
            f"{status} lane={result.lane} expected={expected_lane} "
            f"ms={ms:.0f} msg={message!r}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
