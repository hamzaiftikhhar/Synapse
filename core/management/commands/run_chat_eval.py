"""Run chat routing eval battery (500+ cases) and print a scorecard."""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.chatbot.eval import build_eval_cases, evaluate_cases


class Command(BaseCommand):
    help = "Run the Synapse chat routing evaluation battery"

    def add_arguments(self, parser):
        parser.add_argument("--target", type=int, default=520)
        parser.add_argument(
            "--min-pass-rate",
            type=float,
            default=0.85,
            help="Exit non-zero if pass rate is below this threshold",
        )
        parser.add_argument(
            "--json-out",
            type=str,
            default="",
            help="Optional path to write full report JSON",
        )
        parser.add_argument("--show-failures", type=int, default=25)

    def handle(self, *args, **options):
        target = int(options["target"])
        cases = build_eval_cases(target=target)
        self.stdout.write(f"Evaluating {len(cases)} routing cases…")
        report = evaluate_cases(cases)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"PASS RATE: {report.pass_rate:.1%}  ({report.passed}/{report.total})"
            )
            if report.pass_rate >= float(options["min_pass_rate"])
            else self.style.ERROR(
                f"PASS RATE: {report.pass_rate:.1%}  ({report.passed}/{report.total})"
            )
        )
        self.stdout.write("By family:")
        for fam, stats in sorted(report.by_family.items()):
            total = stats["pass"] + stats["fail"]
            rate = stats["pass"] / total if total else 0
            self.stdout.write(f"  {fam:20s} {rate:6.1%}  {stats['pass']}/{total}")

        if report.by_lane_confusion:
            self.stdout.write("\nTop lane confusions:")
            for k, n in list(report.by_lane_confusion.items())[:10]:
                self.stdout.write(f"  {k}: {n}")

        show_n = int(options["show_failures"])
        if report.failures and show_n:
            self.stdout.write(f"\nFirst {show_n} failures:")
            for f in report.failures[:show_n]:
                self.stdout.write(
                    f"  [{f.expected_family}] want={f.expected_lane} got={f.predicted_lane} "
                    f"intent={f.predicted_intent} conf={f.confidence:.2f} band={f.confidence_band}"
                )
                self.stdout.write(f"    Q: {f.message[:120]}")

        out = options.get("json_out") or ""
        if out:
            path = Path(out)
            path.write_text(json.dumps(report.to_dict(), indent=2))
            self.stdout.write(f"\nWrote {path}")

        if report.pass_rate < float(options["min_pass_rate"]):
            raise SystemExit(1)
