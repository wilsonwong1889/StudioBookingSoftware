import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import suitedash_service


class SuiteDashServiceTest(unittest.TestCase):
    def test_status_reports_disabled_when_not_enabled(self) -> None:
        with patch.object(suitedash_service.settings, "SUITEDASH_ENABLED", False), patch.object(
            suitedash_service.settings, "SUITEDASH_PUBLIC_ID", ""
        ), patch.object(suitedash_service.settings, "SUITEDASH_SECRET_KEY", ""):
            status = suitedash_service.get_suitedash_status()

        self.assertFalse(status["enabled"])
        self.assertFalse(status["configured"])

    def test_status_reports_configured_when_credentials_present(self) -> None:
        with patch.object(suitedash_service.settings, "SUITEDASH_ENABLED", True), patch.object(
            suitedash_service.settings, "SUITEDASH_PUBLIC_ID", "public-id"
        ), patch.object(suitedash_service.settings, "SUITEDASH_SECRET_KEY", "secret-key"):
            status = suitedash_service.get_suitedash_status()

        self.assertTrue(status["enabled"])
        self.assertTrue(status["configured"])

    def test_build_contact_sync_payload_splits_name_and_defaults_signup_role(self) -> None:
        user = SimpleNamespace(
            email="creator@example.com",
            full_name="Studio Booker",
            phone="5551112222",
        )

        with patch.object(suitedash_service.settings, "SUITEDASH_ROLE_ON_SIGNUP", "Lead"):
            payload = suitedash_service.build_contact_sync_payload(user, source="signup")

        self.assertEqual(payload["email"], "creator@example.com")
        self.assertEqual(payload["first_name"], "Studio")
        self.assertEqual(payload["last_name"], "Booker")
        self.assertEqual(payload["phone"], "5551112222")
        self.assertEqual(payload["role"], "Lead")

    def test_suitedash_request_uses_auth_headers_and_parses_json(self) -> None:
        response = MagicMock()
        response.read.return_value = b'{"ok": true}'

        with patch.object(suitedash_service.settings, "SUITEDASH_ENABLED", True), patch.object(
            suitedash_service.settings, "SUITEDASH_PUBLIC_ID", "public-id"
        ), patch.object(
            suitedash_service.settings, "SUITEDASH_SECRET_KEY", "secret-key"
        ), patch.object(
            suitedash_service.settings, "SUITEDASH_BASE_URL", "https://example.suitedash.test"
        ), patch.object(
            suitedash_service, "urlopen"
        ) as urlopen_mock:
            urlopen_mock.return_value.__enter__.return_value = response
            result = suitedash_service.suitedash_request("GET", "/contact/meta")

        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.suitedash.test/contact/meta")
        self.assertEqual(request.headers["X-public-id"], "public-id")
        self.assertEqual(request.headers["X-secret-key"], "secret-key")
        self.assertEqual(result, {"ok": True})

    def test_fetch_contact_meta_uses_configured_meta_path(self) -> None:
        response = MagicMock()
        response.read.return_value = b'{"fields": []}'

        with patch.object(suitedash_service.settings, "SUITEDASH_ENABLED", True), patch.object(
            suitedash_service.settings, "SUITEDASH_PUBLIC_ID", "public-id"
        ), patch.object(
            suitedash_service.settings, "SUITEDASH_SECRET_KEY", "secret-key"
        ), patch.object(
            suitedash_service.settings, "SUITEDASH_BASE_URL", "https://example.suitedash.test"
        ), patch.object(
            suitedash_service.settings, "SUITEDASH_CONTACT_META_PATH", "/contact/meta"
        ), patch.object(
            suitedash_service, "urlopen"
        ) as urlopen_mock:
            urlopen_mock.return_value.__enter__.return_value = response
            result = suitedash_service.fetch_suitedash_contact_meta()

        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.suitedash.test/contact/meta")
        self.assertEqual(result, {"fields": []})


if __name__ == "__main__":
    unittest.main()
