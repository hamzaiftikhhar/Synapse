from django.apps import AppConfig


class VerificationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.verification"
    label = "verification"
    verbose_name = "Verification"

    def ready(self) -> None:
        from apps.verification import checks  # noqa: F401 — registers the system check
