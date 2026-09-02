"""Scoped CORS handling for the public widget/patient-chat endpoints.

django-cors-headers has no native per-clinic, DB-backed origin support — it
only knows a single static CORS_ALLOWED_ORIGINS list, applied uniformly to
whatever URLs CORS_URLS_REGEX matches. The public widget needs a dynamic,
per-clinic origin allowlist (Clinic.allowed_origins), which is fundamentally
a different shape of policy than "one static list for the whole API."

The split: CORS_URLS_REGEX (config/settings/base.py) excludes /api/v1/widget/*
and exactly /api/v1/chat/message from corsheaders entirely, and this
middleware handles CORS for exactly those paths instead — everything else in
the project keeps today's static CORS_ALLOWED_ORIGINS behavior, untouched.

This middleware deliberately does NOT decide whether a request is allowed —
it just lets the browser read whatever response the view produces (echoing
back the Origin, since the real per-clinic allowlist can't be known without
the clinic_slug the view itself resolves). The actual 403 decision is
apps.api.auth.deps.origin_allowed_for_clinic, called from inside the view.
Without this middleware, a browser would see an opaque CORS failure instead
of that 403 body — and a *registered* origin's real, successful responses
would never be readable by the browser at all.
"""

from __future__ import annotations

from django.http import HttpResponse

_WIDGET_PREFIX = "/api/v1/widget/"
_PATIENT_CHAT_PATH = "/api/v1/chat/message"


def _is_scoped_path(path: str) -> bool:
    return path.startswith(_WIDGET_PREFIX) or path.rstrip("/") == _PATIENT_CHAT_PATH


class WidgetCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _is_scoped_path(request.path):
            return self.get_response(request)

        origin = request.headers.get("Origin")

        if request.method == "OPTIONS":
            response = HttpResponse(status=200)
        else:
            response = self.get_response(request)

        if origin:
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
            if request.method == "OPTIONS":
                response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                response["Access-Control-Allow-Headers"] = (
                    "content-type, authorization, x-synapse-visitor-id"
                )

        return response
