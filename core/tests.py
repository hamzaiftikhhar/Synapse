from django.core.cache import cache
from django.test import SimpleTestCase
from ninja.errors import HttpError

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
