from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from ninja.errors import HttpError

from core.middleware import WidgetCorsMiddleware
from core.ratelimit import check_rate_limit


class CoreSmokeTest(SimpleTestCase):
    def test_uuid_model_is_abstract(self):
        from core.models import UUIDModel

        self.assertTrue(UUIDModel._meta.abstract)


class RateLimitTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_under_limit_never_raises(self):
        for _ in range(3):
            check_rate_limit("scope_a", "id_1", limit=3, window_seconds=60)

    def test_exceeding_limit_raises_429(self):
        for _ in range(5):
            check_rate_limit("scope_b", "id_1", limit=5, window_seconds=60)
        with self.assertRaises(HttpError) as ctx:
            check_rate_limit("scope_b", "id_1", limit=5, window_seconds=60)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_error_message_never_echoes_the_identifier(self):
        secret_identifier = "victim@example.com"
        check_rate_limit("scope_c", secret_identifier, limit=1, window_seconds=60)
        with self.assertRaises(HttpError) as ctx:
            check_rate_limit("scope_c", secret_identifier, limit=1, window_seconds=60)
        self.assertNotIn(secret_identifier, str(ctx.exception))

    def test_different_identifiers_are_independent(self):
        for _ in range(3):
            check_rate_limit("scope_d", "id_a", limit=3, window_seconds=60)
        # id_b has its own budget, unaffected by id_a's exhausted one.
        check_rate_limit("scope_d", "id_b", limit=3, window_seconds=60)

    def test_different_scopes_are_independent_for_the_same_identifier(self):
        for _ in range(3):
            check_rate_limit("scope_e1", "shared_id", limit=3, window_seconds=60)
        check_rate_limit("scope_e2", "shared_id", limit=3, window_seconds=60)

    def test_empty_identifier_is_never_rate_limited(self):
        for _ in range(10):
            check_rate_limit("scope_f", "", limit=1, window_seconds=60)


class WidgetCorsMiddlewareUnitTests(SimpleTestCase):
    """Scoped CORS for the public widget/patient-chat prefix — see
    core/middleware.py's module docstring for why this exists instead of a
    global django-cors-headers setting. The real access decision
    (Clinic.allowed_origins) lives in the view via resolve_public_clinic;
    this middleware only decides whether the browser is allowed to *read*
    whatever the view responds with."""

    def setUp(self):
        self.factory = RequestFactory()

    def _middleware(self, marker_body: bytes = b"view ran"):
        calls = []

        def get_response(request):
            calls.append(request)
            return HttpResponse(marker_body)

        return WidgetCorsMiddleware(get_response), calls

    def test_options_preflight_short_circuits_without_calling_the_view(self):
        middleware, calls = self._middleware()
        request = self.factory.options(
            "/api/v1/widget/config", HTTP_ORIGIN="https://example.com"
        )
        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [])  # the view (and any DB lookup) never ran
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://example.com")
        self.assertEqual(response["Vary"], "Origin")
        self.assertIn("POST", response["Access-Control-Allow-Methods"])

    def test_options_without_origin_gets_no_cors_headers(self):
        middleware, _ = self._middleware()
        request = self.factory.options("/api/v1/widget/config")
        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_actual_request_to_widget_path_echoes_origin(self):
        middleware, calls = self._middleware()
        request = self.factory.get(
            "/api/v1/widget/config", HTTP_ORIGIN="https://example.com"
        )
        response = middleware(request)

        self.assertEqual(len(calls), 1)  # the view DID run this time
        self.assertEqual(response.content, b"view ran")
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://example.com")

    def test_exact_chat_message_path_is_scoped(self):
        middleware, _ = self._middleware()
        response = middleware(
            self.factory.get("/api/v1/chat/message", HTTP_ORIGIN="https://example.com")
        )
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://example.com")

    def test_other_chat_paths_are_not_scoped(self):
        """/api/v1/chat/message/staff and /api/v1/chat/conversations keep
        today's static CORS_ALLOWED_ORIGINS policy — this middleware must
        leave them alone entirely (see CORS_URLS_REGEX in
        config/settings/base.py, which is the other half of this split)."""
        middleware, calls = self._middleware()
        for path in ["/api/v1/chat/message/staff", "/api/v1/chat/conversations"]:
            with self.subTest(path=path):
                response = middleware(
                    self.factory.get(path, HTTP_ORIGIN="https://example.com")
                )
                self.assertNotIn("Access-Control-Allow-Origin", response)
        self.assertEqual(len(calls), 2)  # both still reached the view normally

    def test_non_widget_path_passes_through_untouched(self):
        middleware, calls = self._middleware()
        response = middleware(
            self.factory.get("/api/v1/clinics/me", HTTP_ORIGIN="https://example.com")
        )
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Access-Control-Allow-Origin", response)


class WidgetCorsMiddlewareIntegrationTests(TestCase):
    """End-to-end through the real middleware stack + URL routing — confirms
    CORS_URLS_REGEX (config/settings/base.py) and WidgetCorsMiddleware's own
    path matching actually agree with each other in the running app, not
    just in isolation."""

    def test_options_preflight_to_widget_config_needs_no_clinic(self):
        resp = self.client.options(
            "/api/v1/widget/config", HTTP_ORIGIN="https://example.com"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Access-Control-Allow-Origin"], "https://example.com")

    def test_get_widget_config_for_unknown_clinic_still_carries_cors_header(self):
        """Even an error response (404 here) must be readable by the
        browser — otherwise the frontend sees an opaque CORS failure
        instead of the real error body."""
        resp = self.client.get(
            "/api/v1/widget/config",
            {"clinic_slug": "does-not-exist"},
            HTTP_ORIGIN="https://example.com",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp["Access-Control-Allow-Origin"], "https://example.com")
