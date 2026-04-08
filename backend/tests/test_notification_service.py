import unittest
from unittest.mock import patch

from app.services import notification_service


class NotificationServiceTest(unittest.TestCase):
    def test_send_email_console_backend_returns_console_payload(self) -> None:
        with patch.object(notification_service.settings, "EMAIL_BACKEND", "console"):
            delivery = notification_service.send_email(
                to_email="user@example.com",
                subject="Hello",
                plain_text_content="Console body",
            )

        self.assertEqual(delivery["backend"], "console")
        self.assertEqual(delivery["status_code"], 202)
        self.assertIn("user@example.com", delivery["message"])

    def test_send_email_smtp_backend_uses_configured_server(self) -> None:
        with patch.object(notification_service.settings, "EMAIL_BACKEND", "smtp"), patch.object(
            notification_service.settings, "EMAIL_FROM", "bookings@example.com"
        ), patch.object(
            notification_service.settings, "EMAIL_REPLY_TO", "support@example.com"
        ), patch.object(
            notification_service.settings, "SMTP_HOST", "smtp.gmail.com"
        ), patch.object(
            notification_service.settings, "SMTP_PORT", 587
        ), patch.object(
            notification_service.settings, "SMTP_USERNAME", "bookings@example.com"
        ), patch.object(
            notification_service.settings, "SMTP_PASSWORD", "app-password"
        ), patch.object(
            notification_service.settings, "SMTP_USE_TLS", True
        ), patch.object(
            notification_service.settings, "SMTP_TIMEOUT_SECONDS", 20
        ), patch(
            "app.services.notification_service.smtplib.SMTP"
        ) as smtp_mock:
            delivery = notification_service.send_email(
                to_email="user@example.com",
                subject="SMTP Hello",
                plain_text_content="SMTP body",
                html_content="<p>SMTP body</p>",
            )

        smtp_mock.assert_called_once_with("smtp.gmail.com", 587, timeout=20)
        client = smtp_mock.return_value.__enter__.return_value
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("bookings@example.com", "app-password")
        client.send_message.assert_called_once()
        self.assertEqual(delivery["backend"], "smtp")
        self.assertEqual(delivery["status_code"], 250)

    def test_send_email_smtp_backend_requires_credentials(self) -> None:
        with patch.object(notification_service.settings, "EMAIL_BACKEND", "smtp"), patch.object(
            notification_service.settings, "SMTP_HOST", "smtp.gmail.com"
        ), patch.object(
            notification_service.settings, "SMTP_PORT", 587
        ), patch.object(
            notification_service.settings, "SMTP_USERNAME", "bookings@example.com"
        ), patch.object(
            notification_service.settings, "SMTP_PASSWORD", ""
        ):
            with self.assertRaises(ValueError):
                notification_service.send_email(
                    to_email="user@example.com",
                    subject="SMTP Hello",
                    plain_text_content="SMTP body",
                )

    def test_password_reset_email_includes_reset_link(self) -> None:
        with patch.object(notification_service.settings, "EMAIL_BACKEND", "console"), patch.object(
            notification_service.settings, "PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", 30
        ):
            delivery = notification_service.password_reset_email(
                to_email="user@example.com",
                full_name="Reset User",
                reset_url="http://127.0.0.1:8000/account?mode=reset&reset_token=test-token",
            )

        self.assertEqual(delivery["backend"], "console")
        self.assertIn("reset_token=test-token", delivery["message"])
        self.assertIn("30 minutes", delivery["message"])


if __name__ == "__main__":
    unittest.main()
