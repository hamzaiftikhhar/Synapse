"""
URL configuration for Synapse.

Phase 2: admin only. Django Ninja API routes arrive in later phases.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path


def healthcheck(_request):
    """Lightweight liveness probe — no DB dependency."""
    return JsonResponse({"status": "ok", "service": "synapse"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="healthcheck"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
