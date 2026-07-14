from django.apps import AppConfig


class WidgetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.widget"
    label = "widget"
    verbose_name = "Widget"
