"""Aggregate apps/chatbot/booking/capability_shadow.py's log into the
Clinic Capability Resolver shadow-mode report: total calls, provider
failures, old/new agreement, new-only/old-only resolutions, and a
classification of disagreements (better / equivalent / potentially
incorrect / needs review) — never treating the old system as ground
truth, since several of its behaviors are already-proven failures.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

_LOG_PATH = Path("logs") / "capability_shadow" / "shadow.jsonl"


def _classify(record: dict) -> tuple[str, str]:
    """(bucket, note) -- one of: agree, new_only, old_only,
    potentially_dangerous, needs_review. Never asserts the old system was
    right merely because it found something the new one didn't."""
    resolver = record["resolver"]
    decision = record["routing_decision"]
    old = record["old_pipeline"]

    if resolver["outcome"] == "provider_error":
        return "provider_error", "resolver call failed -- not a semantic signal"

    old_had_service = bool(old.get("resolved_service_ids"))
    old_sql_found = bool(old.get("sql_found"))
    new_has_specialty = bool(decision["specialty_ids"])
    new_has_service = bool(decision["service_ids"])
    new_informational = bool(decision["informational_service_candidates"])

    if decision["action"] == "decline" and not old_sql_found:
        return "agree", "both decline"
    if decision["action"] == "unavailable":
        return "provider_error", "policy marked unavailable"

    if new_has_service and old_had_service:
        overlap = set(decision["service_ids"]) & set(old["resolved_service_ids"])
        if overlap:
            return "agree", "same service id"
        return "needs_review", "both resolved a service, but different ids"

    if new_has_service and not old_had_service:
        # New found a specific service the old deterministic matcher missed
        # entirely -- exactly the proven lexical-matcher gap this whole
        # effort exists to close. Not automatically "better" without
        # checking the id is plausible, but never assumed wrong either.
        return "new_only", "new resolved a service id the old pipeline never had"

    if not new_has_service and old_had_service:
        return "old_only", "old pipeline had a resolved_service_id the new resolver's top pick didn't produce"

    if (new_has_specialty or new_informational) and not old_sql_found:
        return "new_only", "new surfaced relevant capabilities where the old pipeline found nothing"

    if old_sql_found and not (new_has_specialty or new_has_service):
        return "old_only", "old pipeline found SQL rows, new resolver surfaced nothing"

    return "needs_review", "no clean rule matched -- inspect manually"


class Command(BaseCommand):
    help = "Aggregate the Clinic Capability Resolver shadow log into a comparison report"

    def add_arguments(self, parser):
        parser.add_argument("--log-path", type=str, default=str(_LOG_PATH))
        parser.add_argument("--show-examples", type=int, default=5)

    def handle(self, *args, **options):
        path = Path(options["log_path"])
        if not path.exists():
            self.stdout.write(self.style.WARNING(f"No shadow log at {path}"))
            return

        records = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        total = len(records)
        buckets: dict[str, list[dict]] = {}
        for r in records:
            bucket, note = _classify(r)
            r["_bucket"] = bucket
            r["_note"] = note
            buckets.setdefault(bucket, []).append(r)

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Capability Resolver Shadow Report ==="))
        self.stdout.write(f"1. Total shadow calls: {total}")
        self.stdout.write(f"2. Provider failures: {len(buckets.get('provider_error', []))}")
        self.stdout.write(f"3. Agreement (agree): {len(buckets.get('agree', []))}")
        self.stdout.write(f"4. New-only resolutions: {len(buckets.get('new_only', []))}")
        self.stdout.write(f"5. Old-only resolutions: {len(buckets.get('old_only', []))}")
        self.stdout.write(f"6. Needs review (ambiguous/dangerous candidates): {len(buckets.get('needs_review', []))}")

        n = options["show_examples"]
        for bucket in ("new_only", "old_only", "needs_review", "provider_error"):
            rows = buckets.get(bucket, [])
            if not rows:
                continue
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n--- {bucket} (showing up to {n} of {len(rows)}) ---"))
            for r in rows[:n]:
                top = r["resolver"]["candidates"][0] if r["resolver"]["candidates"] else None
                top_desc = f"{top['name']} ({top['type']}, conf={top['confidence']})" if top else "(none)"
                self.stdout.write(
                    f"  [{r['clinic_id'][:8]}] {r['message']!r} [{r['context']}]\n"
                    f"      note: {r['_note']}\n"
                    f"      new top candidate: {top_desc} -> action={r['routing_decision']['action']}\n"
                    f"      old: intent={r['old_pipeline']['intent']} sql_found={r['old_pipeline']['sql_found']} "
                    f"resolved_service_ids={r['old_pipeline']['resolved_service_ids']} n_rows={r['old_pipeline']['n_rows']}"
                )
