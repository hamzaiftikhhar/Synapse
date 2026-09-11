"""End-to-end adversarial corpus for the Clinic Capability Resolver live
vertical slice -- unlike run_capability_resolver_eval (which calls
resolve_capability in isolation), this runs full ChatEngine.process()
calls, once with the live resolver OFF (today's baseline) and once ON,
for the same message -- the actual measurement that matters: "did the
whole chatbot produce the right behavior," not just "did the resolver
pick the right candidate."

Live LLM calls, real cost, several minutes. Run deliberately, not in CI.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.test import override_settings

# (clinic_slug, message, category) -- categories match the requested
# adversarial corpus shape: explicit / care_navigation / ambiguous /
# unsupported / medical_info / transactional / multi_intent / emergency.
_CORPUS = [
    # -- Explicit service --
    ("apex-dental", "I need teeth whitening", "explicit"),
    ("apex-dental", "Can you whiten my teeth?", "explicit"),
    ("apex-dental", "I want my teeth cleaned", "explicit"),
    ("apex-dental", "I need a filling", "explicit"),
    ("horizon-family-care", "I need stitches", "explicit"),
    ("horizon-family-care", "Can you do stitches?", "explicit"),
    ("horizon-family-care", "I need a blood draw", "explicit"),
    # -- Wound/laceration capability regression (real production trace:
    # "is there any doctor available Monday afternoon that can treat the
    # stitches?" returned the generic soft_medical decline despite Horizon
    # listing "Simple Wound Laceration Repair (Sutures)"; a second,
    # separate live trace of the exact same query showed the degraded
    # rules_fallback path misreading a typo of "available" as a doctor
    # name) --
    ("horizon-family-care", "Can you stitch a cut?", "explicit"),
    ("horizon-family-care", "I cut my hand and need stitches", "explicit"),
    ("horizon-family-care", "I cut my hand which has caused a wound and need stitches", "explicit"),
    ("horizon-family-care", "Can anyone repair a laceration today?", "explicit"),
    ("horizon-family-care", "Is there any doctor available Monday afternoon that can treat the stitches?", "transactional"),
    ("horizon-family-care", "Who can see me Monday afternoon for stitches?", "transactional"),
    ("horizon-family-care", "is there any doctor availabel on monday afternoon taht can treat the stitches", "transactional"),
    ("horizon-family-care", "Do you have a plastic surgeon for a deep laceration?", "unsupported"),
    # -- Care navigation --
    ("apex-dental", "My gums are bleeding, who should I see?", "care_navigation"),
    ("apex-dental", "My tooth hurts, who should I see?", "care_navigation"),
    ("apex-dental", "My teeth are yellow", "care_navigation"),
    ("apex-dental", "I have a weird black spot on my tooth", "care_navigation"),
    ("horizon-family-care", "My child has a fever", "care_navigation"),
    ("horizon-family-care", "My throat hurts", "care_navigation"),
    ("horizon-family-care", "I cut my finger", "care_navigation"),
    # -- Ambiguous --
    ("apex-dental", "My tooth is bad", "ambiguous"),
    ("horizon-family-care", "I have a cut", "ambiguous"),
    ("apex-dental", "My teeth look strange", "ambiguous"),
    ("apex-dental", "Something is wrong with my gums", "ambiguous"),
    ("apex-dental", "I think I need treatment", "ambiguous"),
    # -- Unsupported capability --
    ("apex-dental", "Do you have a cardiologist?", "unsupported"),
    ("horizon-family-care", "Do you have a dermatologist?", "unsupported"),
    ("horizon-family-care", "Can I get an MRI?", "unsupported"),
    ("apex-dental", "Do you have a neurologist?", "unsupported"),
    ("horizon-family-care", "Can you treat Crohn's disease?", "unsupported"),
    # -- Medical information (must stay unaffected) --
    ("apex-dental", "What causes bleeding gums?", "medical_info"),
    ("apex-dental", "Why do teeth turn yellow?", "medical_info"),
    ("apex-dental", "What causes black spots on teeth?", "medical_info"),
    # -- Transactional (must stay unaffected) --
    ("apex-dental", "Is anyone available Monday evening?", "transactional"),
    ("apex-dental", "I want to cancel my appointment", "transactional"),
    ("apex-dental", "What insurance do you accept?", "transactional"),
    ("apex-dental", "How much is whitening?", "transactional"),
    # -- Multi-intent --
    ("apex-dental", "I need whitening and want to book Friday", "multi_intent"),
    ("apex-dental", "Do you have a dentist and is anyone available tomorrow?", "multi_intent"),
    # -- Emergency (must stay untouched) --
    ("apex-dental", "I have crushing chest pain and can't breathe", "emergency"),
]


class Command(BaseCommand):
    help = "End-to-end old-vs-new adversarial corpus for the Capability Resolver live slice"

    def add_arguments(self, parser):
        parser.add_argument("--json-out", type=str, default="")

    def handle(self, *args, **options):
        from apps.chatbot.engine import ChatEngine
        from apps.clinics.models import Clinic

        engine = ChatEngine()
        clinics = {slug: Clinic.objects.get(slug=slug) for slug in {c[0] for c in _CORPUS}}
        results = []

        for slug, message, category in _CORPUS:
            clinic = clinics[slug]

            with override_settings(CAPABILITY_RESOLVER_LIVE_ENABLED=False):
                old = engine.process(clinic=clinic, message=message, session=None)
            with override_settings(CAPABILITY_RESOLVER_LIVE_ENABLED=True):
                new = engine.process(clinic=clinic, message=message, session=None)

            def _summarize(res):
                n_doctors = 0
                if res.meta:
                    n_doctors = len(res.meta.get("doctors") or [])
                return {
                    "intent": res.intent,
                    "route": res.route,
                    "n_doctors": n_doctors,
                    "response": res.response[:160],
                }

            old_s = _summarize(old)
            new_s = _summarize(new)
            same = old_s["response"] == new_s["response"]

            row = {
                "clinic": slug,
                "category": category,
                "message": message,
                "old": old_s,
                "new": new_s,
                "changed": not same,
            }
            results.append(row)

            marker = "SAME" if same else "CHANGED"
            self.stdout.write(f"[{category}] {slug}: {message!r} -> {marker}")
            if not same:
                self.stdout.write(f"    old: {old_s['intent']}/{old_s['route']} n_doctors={old_s['n_doctors']} {old_s['response']!r}")
                self.stdout.write(f"    new: {new_s['intent']}/{new_s['route']} n_doctors={new_s['n_doctors']} {new_s['response']!r}")

        n_changed = sum(1 for r in results if r["changed"])
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {n_changed}/{len(results)} messages changed behavior ==="))
        by_cat = {}
        for r in results:
            by_cat.setdefault(r["category"], {"total": 0, "changed": 0})
            by_cat[r["category"]]["total"] += 1
            if r["changed"]:
                by_cat[r["category"]]["changed"] += 1
        for cat, counts in by_cat.items():
            self.stdout.write(f"  {cat}: {counts['changed']}/{counts['total']} changed")

        if options.get("json_out"):
            with open(options["json_out"], "w") as f:
                json.dump(results, f, indent=2)
            self.stdout.write(self.style.SUCCESS(f"\nWrote {options['json_out']}"))
