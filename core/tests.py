from django.test import SimpleTestCase


class CoreSmokeTest(SimpleTestCase):
    def test_uuid_model_is_abstract(self):
        from core.models import UUIDModel

        self.assertTrue(UUIDModel._meta.abstract)
