import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import payment_service


class PaymentServiceTest(unittest.TestCase):
    def test_stripe_checkout_requires_real_publishable_and_secret_keys(self) -> None:
        fake_settings = SimpleNamespace(
            PAYMENT_BACKEND="stripe",
            STRIPE_PUBLISHABLE_KEY="pk_test_change_me",
            STRIPE_SECRET_KEY="sk_test_change_me",
            STRIPE_WEBHOOK_SECRET="whsec_change_me",
            STRIPE_API_VERSION="2026-02-25.clover",
        )

        with patch.object(payment_service, "settings", fake_settings):
            with self.assertRaises(payment_service.PaymentConfigurationError):
                payment_service.get_payment_intent_session(
                    payment_intent_id=None,
                    amount_cents=5000,
                    currency="CAD",
                    booking_id="booking_123",
                    user_email="user@example.com",
                )

    def test_stripe_payment_intent_sets_configured_api_version(self) -> None:
        fake_settings = SimpleNamespace(
            PAYMENT_BACKEND="stripe",
            STRIPE_PUBLISHABLE_KEY="pk_test_realistic_value",
            STRIPE_SECRET_KEY="sk_test_realistic_value",
            STRIPE_WEBHOOK_SECRET="whsec_test_realistic_value",
            STRIPE_API_VERSION="2026-02-25.clover",
        )
        fake_intent = {"id": "pi_123", "client_secret": "pi_client_secret_123"}

        with patch.object(payment_service, "settings", fake_settings):
            with patch.object(payment_service.stripe.PaymentIntent, "create", return_value=fake_intent):
                result = payment_service.create_payment_intent(
                    amount_cents=8500,
                    currency="CAD",
                    booking_id="booking_123",
                    user_email="user@example.com",
                )

        self.assertEqual(result.intent_id, "pi_123")
        self.assertEqual(result.client_secret, "pi_client_secret_123")
        self.assertEqual(payment_service.stripe.api_key, "sk_test_realistic_value")
        self.assertEqual(payment_service.stripe.api_version, "2026-02-25.clover")

    def test_stripe_payment_session_recreates_stub_intents(self) -> None:
        fake_settings = SimpleNamespace(
            PAYMENT_BACKEND="stripe",
            STRIPE_PUBLISHABLE_KEY="pk_test_realistic_value",
            STRIPE_SECRET_KEY="sk_test_realistic_value",
            STRIPE_WEBHOOK_SECRET="whsec_test_realistic_value",
            STRIPE_API_VERSION="2026-02-25.clover",
        )
        fake_intent = {"id": "pi_live_123", "client_secret": "pi_client_secret_live_123"}

        with patch.object(payment_service, "settings", fake_settings):
            with patch.object(payment_service.stripe.PaymentIntent, "retrieve") as retrieve_mock:
                with patch.object(
                    payment_service.stripe.PaymentIntent,
                    "create",
                    return_value=fake_intent,
                ) as create_mock:
                    result = payment_service.get_payment_intent_session(
                        payment_intent_id="pi_stub_existing",
                        amount_cents=8500,
                        currency="CAD",
                        booking_id="booking_123",
                        user_email="user@example.com",
                    )

        retrieve_mock.assert_not_called()
        create_mock.assert_called_once()
        self.assertEqual(result.intent_id, "pi_live_123")
        self.assertEqual(result.client_secret, "pi_client_secret_live_123")

    def test_provider_error_redacts_secret_like_tokens(self) -> None:
        fake_settings = SimpleNamespace(
            PAYMENT_BACKEND="stripe",
            STRIPE_PUBLISHABLE_KEY="pk_test_realistic_value",
            STRIPE_SECRET_KEY="sk_test_realistic_value",
            STRIPE_WEBHOOK_SECRET="whsec_test_realistic_value",
            STRIPE_API_VERSION="2026-02-25.clover",
            SECRET_KEY="app-secret",
            SENDGRID_API_KEY="SG.hidden-value",
            SMTP_PASSWORD="",
            TWILIO_AUTH_TOKEN="",
            SUITEDASH_SECRET_KEY="",
        )

        with patch.object(payment_service, "settings", fake_settings):
            with self.assertRaises(payment_service.PaymentProviderError) as context:
                payment_service._run_stripe_request(
                    lambda: (_ for _ in ()).throw(payment_service.StripeError("bad key sk_test_abc123")),
                    purpose="payment setup",
                )

        self.assertNotIn("sk_test_abc123", str(context.exception))
        self.assertIn("[REDACTED]", str(context.exception))


if __name__ == "__main__":
    unittest.main()
