"""Phase A diagnostic harness for the Clinic Capability Resolver.

Runs the approved Phase A test battery (see the "Clinic Capability
Resolver — Phase A" plan) directly against `resolve_capability` and real
seeded clinic data — live LLM calls, no threshold/pass-fail logic, since
no threshold exists yet. Prints the raw ranked candidates, confidence, and
reasoning for every case, repeated for a consistency check. The point is
human inspection of real numbers, not an assertion the numbers are right.
"""

from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError

# (message, context, note) — matches the approved Phase A plan's battery.
_HORIZON_CASES = [
    ("I need stitches", "explicit", "explicit — expect Sutures"),
    ("I need wound repair", "explicit", "paraphrase — expect Sutures"),
    ("can I get a strep test?", "explicit", "expect the Swab service"),
    ("I need an MRI", "explicit", "negative — Horizon has no MRI"),
    (
        "My throat hurts and I think I need antibiotics.",
        "concern",
        "distractor — must not invent an antibiotics capability",
    ),
    (
        "I cut my finger and it needs stitches.",
        "explicit",
        "distractor narrative — expect Sutures despite noise",
    ),
    (
        "I have a cut but I'm not sure if I need stitches.",
        "concern",
        "distractor concern — Sutures may surface, not as a decision",
    ),
    (
        "I need blood taken for some lab work.",
        "explicit",
        "description-semantics probe — expect Routine Blood Draw",
    ),
]

_APEX_CASES = [
    ("I have a problem with my teeth", "concern", "ambiguous concern"),
    ("my teeth are a bit yellow", "concern", "centerpiece case, no fixed expectation"),
    (
        "my teeth look yellow, who should I see?",
        "concern",
        "centerpiece case, no fixed expectation",
    ),
    (
        "which doctor can do teeth whitening?",
        "explicit",
        "expect Whitening service ranked top",
    ),
    ("Do you have a cardiologist?", "explicit", "negative — Apex has no cardiology"),
    (
        "My teeth hurt.",
        "concern",
        "distractor — must not auto-collapse to Composite Filling",
    ),
    (
        "I need my tooth pulled.",
        "explicit",
        "distractor — expect Surgical Tooth Extraction",
    ),
]


class Command(BaseCommand):
    help = "Phase A diagnostic run of the Clinic Capability Resolver against real clinic data"

    def add_arguments(self, parser):
        parser.add_argument("--repeats", type=int, default=5)
        parser.add_argument("--json-out", type=str, default="")
        parser.add_argument(
            "--horizon-slug", type=str, default="horizon-family-care"
        )
        parser.add_argument("--apex-slug", type=str, default="apex-dental")

    def handle(self, *args, **options):
        from apps.chatbot.booking.capability_resolver import resolve_capability
        from apps.clinics.models import Clinic

        repeats = options["repeats"]
        results: list[dict] = []

        for slug, cases in (
            (options["horizon_slug"], _HORIZON_CASES),
            (options["apex_slug"], _APEX_CASES),
        ):
            try:
                clinic = Clinic.objects.get(slug=slug)
            except Clinic.DoesNotExist as exc:
                raise CommandError(f"Clinic {slug!r} not found") from exc

            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {slug} ==="))
            for message, context, note in cases:
                self.stdout.write(f"\n--- {message!r} [{context}] — {note}")
                runs = []
                for i in range(repeats):
                    t0 = time.perf_counter()
                    resolution = resolve_capability(clinic, message, context=context)
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    candidates = [
                        {
                            "type": c.target_type,
                            "id": c.id,
                            "name": c.name,
                            "confidence": round(c.confidence, 3),
                            "reasoning": c.reasoning,
                        }
                        for c in resolution.candidates
                    ]
                    runs.append(
                        {
                            "elapsed_ms": round(elapsed_ms, 1),
                            "outcome": resolution.outcome,
                            "candidates": candidates,
                        }
                    )
                    top = candidates[0] if candidates else None
                    if resolution.outcome == "provider_error":
                        top_desc = "(PROVIDER ERROR)"
                    elif top:
                        top_desc = f"{top['name']} ({top['type']}, conf={top['confidence']})"
                    else:
                        top_desc = "(no candidates -- genuine)"
                    self.stdout.write(f"    run {i + 1}: {top_desc}  [{elapsed_ms:.0f}ms]")
                    if len(candidates) > 1:
                        for c in candidates[1:]:
                            self.stdout.write(
                                f"             + {c['name']} ({c['type']}, conf={c['confidence']})"
                            )

                results.append(
                    {
                        "clinic": slug,
                        "message": message,
                        "context": context,
                        "note": note,
                        "runs": runs,
                    }
                )

        if options.get("json_out"):
            with open(options["json_out"], "w") as f:
                json.dump(results, f, indent=2)
            self.stdout.write(self.style.SUCCESS(f"\nWrote {options['json_out']}"))
