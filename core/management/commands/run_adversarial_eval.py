"""Run the Phase 51 adversarial evaluation corpus against a real clinic.

Unlike `run_chat_eval` (offline, no live LLM calls), this makes real
ChatEngine calls with real API costs and takes several minutes. Intended
to be run deliberately before a release, not on every CI run.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run the Phase 51 external adversarial evaluation corpus (live LLM calls)"

    def add_arguments(self, parser):
        parser.add_argument("--clinic-slug", type=str, default="horizon-family-care")
        parser.add_argument(
            "--category", type=str, default="",
            help="Comma-separated category filter (e.g. hallucination,safety)",
        )
        parser.add_argument("--json-out", type=str, default="")

    def handle(self, *args, **options):
        from apps.chatbot.eval.adversarial.runner import dump_json, print_compact, run_all
        from apps.clinics.models import Clinic

        try:
            clinic = Clinic.objects.get(slug=options["clinic_slug"])
        except Clinic.DoesNotExist as exc:
            raise CommandError(f"Clinic {options['clinic_slug']!r} not found") from exc

        categories = [c.strip() for c in options["category"].split(",") if c.strip()] or None
        results = run_all(clinic, categories=categories)
        print_compact(results)

        if options.get("json_out"):
            dump_json(results, options["json_out"])
            self.stdout.write(f"\nWrote {options['json_out']}")

        self.stdout.write(
            self.style.WARNING(
                f"\n{len(results)} cases run. This command does not auto-score — "
                "review the captured responses against TAXONOMY.md severity "
                "definitions (see docstring in runner.py for why)."
            )
        )
