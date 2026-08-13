"""Idempotent catalog sync for Paddle sandbox plans.

Usage:
    python manage.py sync_billing_plans
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.billing.models import BillingInterval, Plan

# Paddle sandbox Product → Price (Monthly). Display cents must match Paddle
# unit_price so the dashboard cards and the overlay never disagree.
PLANS = (
    {
        "slug": "starter",
        "name": "Starter",
        "paddle_price_id_sandbox": "pri_01kznr8ptq2dxm9eaa2w6ghndg",
        "display_price_cents": 2900,
        "display_order": 1,
    },
    {
        "slug": "growth",
        "name": "Professional",
        "paddle_price_id_sandbox": "pri_01kznrbqxgkahdxmvdpvafbwhj",
        "display_price_cents": 4900,
        "display_order": 2,
    },
    {
        "slug": "enterprise",
        "name": "Enterprise",
        "paddle_price_id_sandbox": "pri_01kznra1m5spzvp50h1sk7j34f",
        "display_price_cents": 9900,
        "display_order": 3,
    },
)


class Command(BaseCommand):
    help = "Create/update Starter / Professional / Enterprise billing plans."

    def handle(self, *args, **options):
        for spec in PLANS:
            plan, created = Plan.objects.update_or_create(
                slug=spec["slug"],
                defaults={
                    "name": spec["name"],
                    "paddle_price_id_sandbox": spec["paddle_price_id_sandbox"],
                    "billing_interval": BillingInterval.MONTH,
                    "display_price_cents": spec["display_price_cents"],
                    "display_currency": "USD",
                    "is_active": True,
                    "display_order": spec["display_order"],
                },
            )
            verb = "Created" if created else "Updated"
            self.stdout.write(f"  {verb} {plan.slug} ({plan.name}) ${plan.display_price_cents / 100:.0f}")
        self.stdout.write(self.style.SUCCESS("Billing plans synced."))
