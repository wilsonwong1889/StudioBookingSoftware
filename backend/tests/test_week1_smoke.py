import os
import sys
import unittest
import hashlib
import hmac
import json
import re
import time
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text


class AppSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.admin_database_url = os.environ.get(
            "TEST_ADMIN_DATABASE_URL",
            "postgresql://postgres:password@localhost:5432/postgres",
        )
        cls.test_database_name = f"studio_week1_{uuid4().hex[:8]}"
        cls.test_database_url = os.environ.get(
            "TEST_DATABASE_URL",
            f"postgresql://postgres:password@localhost:5432/{cls.test_database_name}",
        )
        cls._create_database()

        os.environ["DATABASE_URL"] = cls.test_database_url
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "week1-test-secret")

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                sys.modules.pop(module_name)

        from app.database import Base, SessionLocal, engine
        from app.main import app
        from app.models.booking import AuditLog, Booking, BookingSlot, NotificationLog, Refund
        from app.models.room import Room
        from app.models.staff_profile import StaffProfile
        from app.models.user import User
        from app.services.seed_service import ensure_admin_user, ensure_rooms

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.AuditLog = AuditLog
        cls.Booking = Booking
        cls.BookingSlot = BookingSlot
        cls.NotificationLog = NotificationLog
        cls.Refund = Refund
        cls.Room = Room
        cls.StaffProfile = StaffProfile
        cls.User = User
        cls.ensure_admin_user = staticmethod(ensure_admin_user)
        cls.ensure_rooms = staticmethod(ensure_rooms)

        cls.Base.metadata.create_all(bind=cls.engine)

        from fastapi.testclient import TestClient

        cls.client = TestClient(app)

    def setUp(self) -> None:
        from app.core import rate_limit
        from app.services import reservation_service

        rate_limit._requests.clear()
        reservation_service._memory_holds.clear()

        with self.SessionLocal() as db:
            for model in (
                self.AuditLog,
                self.NotificationLog,
                self.Refund,
                self.BookingSlot,
                self.Booking,
                self.Room,
                self.StaffProfile,
                self.User,
            ):
                db.query(model).delete()
            db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        cls._drop_database()

    @classmethod
    def _create_database(cls) -> None:
        admin_engine = create_engine(cls.admin_database_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {cls.test_database_name}"))
            conn.execute(text(f"CREATE DATABASE {cls.test_database_name}"))
        admin_engine.dispose()

    @classmethod
    def _drop_database(cls) -> None:
        admin_engine = create_engine(cls.admin_database_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": cls.test_database_name},
            )
            conn.execute(text(f"DROP DATABASE IF EXISTS {cls.test_database_name}"))
        admin_engine.dispose()

    def test_00_seed_helpers(self) -> None:
        with self.SessionLocal() as db:
            admin = type(self).ensure_admin_user(
                db,
                email="seed-admin@example.com",
                password="SeedAdmin123!",
                full_name="Seed Admin",
            )
            rooms = type(self).ensure_rooms(
                db,
                rooms=[
                    {
                        "name": "Seed Room",
                        "description": "Seeded room",
                        "capacity": 2,
                        "photos": [],
                        "hourly_rate_cents": 5000,
                    }
                ],
            )
            admin_email = admin.email
            admin_is_admin = admin.is_admin
            room_name = rooms[0].name
            room_count = len(rooms)
            default_seeded_rooms = type(self).ensure_rooms(db)

        self.assertEqual(admin_email, "seed-admin@example.com")
        self.assertTrue(admin_is_admin)
        self.assertEqual(room_count, 1)
        self.assertEqual(room_name, "Seed Room")
        self.assertEqual(default_seeded_rooms, [])

    def test_10_week_two_smoke_flow(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ready")
        self.assertTrue(response.json()["checks"]["database"])

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("StudioBookingSoftware", response.text)
        self.assertIn("2525 36 St N, Lethbridge, AB T1H 5L1", response.text)
        self.assertIn("Plan your session before you book it.", response.text)
        self.assertIn("Explore the studio", response.text)
        self.assertNotIn('id="rooms-grid"', response.text)
        self.assertIn("20260401s", response.text)

        for path in ("/account", "/rooms", "/room", "/reserve", "/bookings", "/booking", "/payment-success", "/admin"):
            page_response = self.client.get(path)
            self.assertEqual(page_response.status_code, 200, page_response.text)

        account_page = self.client.get("/account")
        self.assertIn("Delete profile", account_page.text)
        self.assertIn("Require two-factor verification at login", account_page.text)
        self.assertIn("login-2fa-form", account_page.text)
        self.assertIn("forgot-password-form", account_page.text)
        self.assertIn("reset-password-form", account_page.text)
        self.assertIn("Forgot password?", account_page.text)
        self.assertIn("Confirm password", account_page.text)
        self.assertIn("signup-password-match-feedback", account_page.text)
        self.assertIn("reset-password-match-feedback", account_page.text)
        self.assertIn("profile-password-match-feedback", account_page.text)
        self.assertIn("account-danger-zone", account_page.text)
        self.assertIn("20260401ab", account_page.text)

        bookings_page = self.client.get("/bookings")
        self.assertIn("Check availability", bookings_page.text)
        self.assertIn("booking-staff-section", bookings_page.text)
        self.assertIn("Available staff for this room", bookings_page.text)
        self.assertIn("Choose a room to preview available staff for this session.", bookings_page.text)
        self.assertIn("Save 5-minute spot hold", bookings_page.text)
        self.assertIn("Complete your saved bookings", bookings_page.text)
        self.assertIn("recent-bookings-shell", bookings_page.text)
        self.assertIn("pending-bookings-list", bookings_page.text)
        self.assertIn("20260408g", bookings_page.text)

        admin_page = self.client.get("/admin")
        self.assertIn("Accounts", admin_page.text)
        self.assertIn("Backend test cases", admin_page.text)
        self.assertIn("admin-panel-accounts", admin_page.text)
        self.assertIn("admin-panel-qa", admin_page.text)
        self.assertIn("admin-accounts-list", admin_page.text)
        self.assertIn("admin-test-case-summary", admin_page.text)
        self.assertIn("admin-test-cases-list", admin_page.text)
        self.assertIn("20260408f", admin_page.text)
        self.assertLess(admin_page.text.index("Room management"), admin_page.text.index("Backend test cases"))

        response = self.client.get("/assets/styles/app.css")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("--bg:", response.text)

        response = self.client.get("/assets/media/recording-studio.svg")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("<svg", response.text)

        response = self.client.get("/assets/js/main.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("refreshSession", response.text)
        self.assertIn('./api.js?v=20260401r', response.text)
        self.assertIn('./state.js?v=20260401r', response.text)
        self.assertIn("views/admin.js?v=20260408f", response.text)
        self.assertIn("views/booking-detail.js?v=", response.text)
        self.assertIn("views/payment-success.js?v=", response.text)
        self.assertIn("views/bookings.js?v=20260408g", response.text)
        self.assertIn("views/room-booking.js?v=20260401u", response.text)
        self.assertIn("views/rooms.js?v=20260408e", response.text)
        self.assertIn("views/room-detail.js?v=20260401r", response.text)
        self.assertIn("views/auth.js?v=20260401ab", response.text)
        self.assertIn("views/profile.js?v=20260401ab", response.text)
        self.assertNotIn("views/admin.js?v=20260401x", response.text)

        response = self.client.get("/assets/js/views/bookings.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('../state.js?v=20260401r', response.text)
        self.assertIn('getSearchParam("room") || getSearchParam("id")', response.text)
        self.assertIn("const MAX_DURATION_MINUTES = 300;", response.text)
        self.assertIn("Completed / checked in", response.text)
        self.assertIn("Cancelled bookings stay at the bottom.", response.text)

        response = self.client.get("/assets/js/views/booking-detail.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("stripeElements.submit()", response.text)
        self.assertIn('new URL("/payment-success"', response.text)
        self.assertIn("Skip Stripe as admin", response.text)
        self.assertIn('api.adminWaiveBookingPayment(button.dataset.bookingId)', response.text)

        response = self.client.get("/assets/js/views/payment-success.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Payment successful", response.text)
        self.assertIn("Refresh status", response.text)

        response = self.client.get("/assets/js/views/rooms.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('href="/bookings?room=${room.id}"', response.text)

        signup_payload = {
            "email": "user@example.com",
            "password": "Password123!",
            "full_name": "Week One User",
            "phone": "1234567890",
        }
        response = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(response.status_code, 201, response.text)
        user_id = response.json()["id"]

        response = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        access_token = response.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {access_token}"}

        response = self.client.get("/api/auth/me", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["email"], "user@example.com")

        response = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "full_name": "Updated User",
                "birthday": "1995-07-14",
                "billing_address": {
                    "line1": "123 Booking St",
                    "line2": "Unit 4",
                    "city": "Edmonton",
                    "state": "AB",
                    "postal_code": "T5J0N3",
                    "country": "Canada",
                },
                "opt_in_sms": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["full_name"], "Updated User")
        self.assertEqual(response.json()["birthday"], "1995-07-14")
        self.assertEqual(response.json()["billing_address"]["city"], "Edmonton")
        self.assertNotIn("saved_payment_method", response.json())
        self.assertTrue(response.json()["opt_in_sms"])

        response = self.client.put(
            "/api/users/me/password",
            headers=user_headers,
            json={
                "current_password": "Password123!",
                "new_password": "NewPassword456!",
            },
        )
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 401, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "NewPassword456!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.get("/api/rooms")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsInstance(response.json(), list)

        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.id == user_id).first()
            user.is_admin = True
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "NewPassword456!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.get("/api/rooms?include_inactive=true")
        self.assertEqual(response.status_code, 403, response.text)

        response = self.client.post(
            "/api/admin/rooms/photo",
            headers=admin_headers,
            files={"photo": ("room.jpg", b"\xff\xd8\xffroom-photo\xff\xd9", "image/jpeg")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        room_photo_url = response.json()["photo_url"]
        self.assertTrue(room_photo_url.startswith("/assets/media/rooms/"))

        response = self.client.post(
            "/api/rooms",
            headers=admin_headers,
            json={
                "name": "Studio A",
                "description": "Main room",
                "capacity": 4,
                "photos": [room_photo_url],
                "hourly_rate_cents": 5000,
                "max_booking_duration_minutes": 180,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        room_id = response.json()["id"]
        self.assertEqual(response.json()["max_booking_duration_minutes"], 180)

        response = self.client.get(f"/api/rooms/{room_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Studio A")
        self.assertEqual(response.json()["max_booking_duration_minutes"], 180)

        response = self.client.put(
            f"/api/admin/rooms/{room_id}",
            headers=admin_headers,
            json={
                "name": "Studio A Edited",
                "description": "Updated main room",
                "capacity": 6,
                "hourly_rate_cents": 6500,
                "max_booking_duration_minutes": 240,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Studio A Edited")
        self.assertEqual(response.json()["capacity"], 6)
        self.assertEqual(response.json()["hourly_rate_cents"], 6500)
        self.assertEqual(response.json()["max_booking_duration_minutes"], 240)

        response = self.client.get("/api/rooms?include_inactive=true", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)

        response = self.client.delete(f"/api/rooms/{room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.get(f"/api/rooms/{room_id}")
        self.assertEqual(response.status_code, 404, response.text)

        response = self.client.get(f"/api/rooms/{room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["active"])

        response = self.client.get("/api/rooms?include_inactive=true", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        archived_room = next(room for room in response.json() if room["id"] == room_id)
        self.assertFalse(archived_room["active"])

        response = self.client.post(f"/api/rooms/{room_id}/restore", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["active"])

        response = self.client.get("/api/rooms")
        self.assertEqual(response.status_code, 200, response.text)
        room_names = [room["name"] for room in response.json()]
        self.assertIn("Studio A Edited", room_names)

        response = self.client.delete(f"/api/rooms/{room_id}/permanent", headers=admin_headers)
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.get(f"/api/rooms/{room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 404, response.text)

    def test_11_all_frontend_pages_include_shared_footer_acknowledgement(self) -> None:
        frontend_dir = Path(__file__).resolve().parents[1] / "app" / "frontend"
        html_files = sorted(frontend_dir.glob("*.html"))
        self.assertTrue(html_files)

        required_strings = (
            "site-acknowledgement",
            "BIPOC Foundation is situated on the unceded, traditional and ancestral Siksikaitsitapii",
            "Copyright &copy; 2026 - media arts collective. All Rights Reserved.",
            "Powered by BIPOC Foundation.",
        )

        for html_file in html_files:
            content = html_file.read_text(encoding="utf-8")
            for required in required_strings:
                self.assertIn(required, content, f"{html_file.name} is missing footer text: {required}")

    def test_15_two_factor_login_flow(self) -> None:
        signup_payload = {
            "email": "twofactor@example.com",
            "password": "Password123!",
            "full_name": "Two Factor User",
            "phone": "5552223333",
        }
        response = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "two_factor_enabled": True,
                "two_factor_method": "email",
                "opt_in_email": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["two_factor_enabled"])
        self.assertEqual(response.json()["two_factor_method"], "email")

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        login_payload = response.json()
        self.assertTrue(login_payload["two_factor_required"])
        self.assertEqual(login_payload["two_factor_method"], "email")
        self.assertIsNotNone(login_payload["two_factor_token"])
        self.assertIsNone(login_payload["access_token"])

        with self.SessionLocal() as db:
            notification = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.type == "login_verification_email_worker")
                .order_by(self.NotificationLog.created_at.desc())
                .first()
            )

        self.assertIsNotNone(notification)
        delivery_message = json.loads(notification.details["delivery"]["message"])
        code_search = re.search(r"\b(\d{6})\b", delivery_message["body"])
        code_match = code_search.group(1) if code_search else None
        self.assertIsNotNone(code_match)

        response = self.client.post(
            "/api/auth/verify-2fa",
            json={
                "two_factor_token": login_payload["two_factor_token"],
                "code": "000000",
            },
        )
        self.assertEqual(response.status_code, 401, response.text)

        response = self.client.post(
            "/api/auth/verify-2fa",
            json={
                "two_factor_token": login_payload["two_factor_token"],
                "code": code_match,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["access_token"])

    def test_16_login_feedback_and_password_reset_flow(self) -> None:
        signup_payload = {
            "email": "reset-user@example.com",
            "password": "Password123!",
            "full_name": "Reset User",
            "phone": "5554443333",
        }
        response = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "not-an-email", "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "Enter a valid email address.")

        response = self.client.post(
            "/api/auth/login",
            data={"username": "missing@example.com", "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "We couldn't find an account with that email.")

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": "WrongPassword123!"},
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["detail"], "Wrong password. Try again or reset it.")

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": signup_payload["email"]},
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            response.json()["message"],
            "If we found an account with that email, we sent a password reset link.",
        )

        with self.SessionLocal() as db:
            notification = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.type == "password_reset_email_worker")
                .order_by(self.NotificationLog.created_at.desc())
                .first()
            )

        self.assertIsNotNone(notification)
        delivery_message = json.loads(notification.details["delivery"]["message"])
        token_search = re.search(r"reset_token=([A-Za-z0-9._-]+)", delivery_message["body"])
        token = token_search.group(1) if token_search else None
        self.assertIsNotNone(token)

        response = self.client.post(
            "/api/auth/reset-password",
            json={"reset_token": token, "new_password": "NewPassword123!"},
        )
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["detail"], "Wrong password. Try again or reset it.")

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": "NewPassword123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["access_token"])

    def test_20_week_three_booking_flow(self) -> None:
        from app.config import settings
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Booking Room",
                description="Room used for booking smoke tests",
                capacity=3,
                photos=[],
                hourly_rate_cents=5000,
                max_booking_duration_minutes=120,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        signup_payload = {
            "email": "booker@example.com",
            "password": "Password123!",
            "full_name": "Booking User",
            "phone": "5551112222",
        }
        response = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "booker@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        booking_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        business_timezone = ZoneInfo("America/Edmonton")
        start_time = datetime(2026, 4, 2, 10, 0, tzinfo=business_timezone)
        target_date = date(2026, 4, 2)

        response = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        availability = response.json()
        self.assertEqual(availability["timezone"], "America/Edmonton")
        self.assertIn(start_time.isoformat(), availability["available_start_times"])
        self.assertEqual(availability["max_duration_minutes_by_start"][start_time.isoformat()], 120)
        self.assertNotIn(
            datetime(2026, 4, 2, 9, 0, tzinfo=business_timezone).isoformat(),
            availability["available_start_times"],
        )
        self.assertNotIn(
            datetime(2026, 4, 2, 18, 0, tzinfo=business_timezone).isoformat(),
            availability["available_start_times"],
        )
        response = self.client.post(
            "/api/bookings/reservations",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        reservation = response.json()
        self.assertTrue(reservation["token"].startswith("hold_"))
        self.assertEqual(len(reservation["slot_keys"]), 2)

        response = self.client.post(
            "/api/bookings",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
                "reservation_token": reservation["token"],
                "note": "Podcast intro and guest setup",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertEqual(booking["price_cents"], 5000)
        self.assertTrue(booking["payment_intent_id"].startswith("pi_"))
        self.assertTrue(booking["payment_client_secret"])
        if settings.PAYMENT_BACKEND == "stub":
            self.assertTrue(booking["payment_client_secret"].startswith("pi_client_secret_stub_"))
        else:
            self.assertIn("_secret_", booking["payment_client_secret"])
        self.assertTrue(booking["booking_code"])
        self.assertEqual(booking["note"], "Podcast intro and guest setup")
        self.assertIsNotNone(booking["payment_expires_at"])
        self.assertGreater(booking["payment_seconds_remaining"], 0)
        self.assertLessEqual(booking["payment_seconds_remaining"], 300)

        response = self.client.get("/api/bookings", headers=booking_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)

        response = self.client.get(f"/api/bookings/{booking['id']}", headers=booking_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], booking["id"])

        response = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        updated_availability = response.json()
        self.assertNotIn(start_time.isoformat(), updated_availability["available_start_times"])

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "conflict@example.com",
                "password": "Password123!",
                "full_name": "Conflict User",
                "phone": "5550001111",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "conflict@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        conflict_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 409, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": datetime(2026, 4, 2, 13, 0, tzinfo=business_timezone).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            response.json()["detail"],
            "Only one booking per day is allowed for each account",
        )

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": datetime(2026, 4, 2, 10, 30, tzinfo=business_timezone).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": datetime(2026, 4, 2, 11, 0, tzinfo=business_timezone).isoformat(),
                "duration_minutes": 120,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["duration_minutes"], 120)
        self.assertEqual(response.json()["price_cents"], 10000)

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": datetime(2026, 4, 3, 11, 0, tzinfo=business_timezone).isoformat(),
                "duration_minutes": 360,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": datetime(2026, 4, 3, 9, 0, tzinfo=business_timezone).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(
            response.json()["detail"],
            "Bookings are only available between 10:00 and 18:00",
        )

    def test_25_pending_payment_window_expires_and_reopens_slot(self) -> None:
        from app.models.booking import Booking
        from app.models.room import Room

        business_timezone = ZoneInfo("America/Edmonton")
        target_date = date(2026, 4, 4)
        start_time = datetime(2026, 4, 4, 10, 0, tzinfo=business_timezone)

        with self.SessionLocal() as db:
            room = Room(
                name="Expiry Room",
                description="Room used for pending payment expiry coverage",
                capacity=4,
                photos=[],
                hourly_rate_cents=5000,
                max_booking_duration_minutes=180,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "expiry@example.com",
                "password": "Password123!",
                "full_name": "Expiry User",
                "phone": "5551112222",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "expiry@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertIsNotNone(booking["payment_expires_at"])

        with self.SessionLocal() as db:
            db_booking = db.query(Booking).filter(Booking.id == UUID(booking["id"])).first()
            db_booking.created_at = datetime.now(timezone.utc) - timedelta(minutes=6)
            db.commit()

        response = self.client.get(f"/api/bookings/{booking['id']}", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Cancelled")
        self.assertEqual(
            response.json()["cancellation_reason"],
            "Payment window expired after 5 minutes",
        )

        response = self.client.post(
            f"/api/bookings/{booking['id']}/payment-session",
            headers=user_headers,
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            response.json()["detail"],
            "Payment is only available for pending bookings",
        )

        response = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(start_time.isoformat(), response.json()["available_start_times"])

    def test_32_admin_backend_test_case_catalog(self) -> None:
        with self.SessionLocal() as db:
            type(self).ensure_admin_user(
                db,
                email="catalog-admin@example.com",
                password="Password123!",
                full_name="Catalog Admin",
            )

        response = self.client.post(
            "/api/auth/login",
            data={"username": "catalog-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.get("/api/admin/test-cases", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()

        self.assertGreaterEqual(len(payload), 12)
        self.assertTrue(all("health" in item for item in payload))
        self.assertTrue(all(item["health"] in {"working", "needs_fix", "not_working"} for item in payload))
        self.assertTrue(any(item["health"] == "working" for item in payload))
        self.assertTrue(any(item["health"] == "needs_fix" for item in payload))
        self.assertTrue(any(item["health"] == "not_working" for item in payload))
        self.assertTrue(any(item["title"] == "Payment confirmation end-to-end" for item in payload))
        self.assertTrue(any(item["title"] == "Runtime config rejects placeholder production secrets" for item in payload))

        response = self.client.get("/api/admin/integrations/suitedash/status", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["enabled"])
        self.assertFalse(response.json()["configured"])
        self.assertEqual(response.json()["contact_meta_path"], "/contact/meta")

        response = self.client.get("/api/admin/integrations/suitedash/contact-meta", headers=admin_headers)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("SuiteDash integration is disabled", response.text)

    def test_33_admin_can_skip_stripe_and_mark_booking_free(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Admin Free Room",
                description="Room used for admin free payment tests",
                capacity=4,
                photos=[],
                hourly_rate_cents=5050,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "free-admin@example.com",
                "password": "Password123!",
                "full_name": "Free Admin",
                "phone": "5551231111",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        admin_id = response.json()["id"]

        with self.SessionLocal() as db:
            admin = db.query(self.User).filter(self.User.id == admin_id).first()
            admin.is_admin = True
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            data={"username": "free-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "free-guest@example.com",
                "password": "Password123!",
                "full_name": "Free Guest",
                "phone": "5551232222",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "free-guest@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        guest_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        business_timezone = ZoneInfo("America/Edmonton")
        free_booking_date = datetime.now(business_timezone).date() + timedelta(days=4)
        start_time = datetime(
            free_booking_date.year,
            free_booking_date.month,
            free_booking_date.day,
            16,
            0,
            tzinfo=business_timezone,
        )
        response = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertEqual(booking["price_cents"], 5050)

        response = self.client.post(
            f"/api/admin/bookings/{booking['id']}/waive-payment",
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        waived_booking = response.json()
        self.assertEqual(waived_booking["status"], "Paid")
        self.assertEqual(waived_booking["price_cents"], 0)
        self.assertTrue(waived_booking["payment_intent_id"].startswith("admin_waived_"))

        response = self.client.get(f"/api/bookings/{booking['id']}", headers=guest_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Paid")
        self.assertEqual(response.json()["price_cents"], 0)

        response = self.client.get("/api/admin/bookings?status=Paid", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        paid_booking = next(item for item in response.json() if item["id"] == booking["id"])
        self.assertEqual(paid_booking["price_cents"], 0)

        response = self.client.get("/api/admin/activity?limit=10", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        activity_actions = [item["action"] for item in response.json()]
        self.assertIn("payment_waived_by_admin", activity_actions)

    def test_30_week_five_six_flow(self) -> None:
        from app.config import settings
        from app.models.booking import Booking
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Webhook Room",
                description="Room used for webhook and admin tests",
                capacity=5,
                photos=[],
                hourly_rate_cents=5000,
            )
            admin_room = Room(
                name="Admin Unlimited Room",
                description="Room used to verify admins can self-book multiple times in one day",
                capacity=2,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.add(admin_room)
            db.commit()
            db.refresh(room)
            db.refresh(admin_room)
            room_id = str(room.id)
            admin_room_id = str(admin_room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "ops-user@example.com",
                "password": "Password123!",
                "full_name": "Ops User",
                "phone": "5551230000",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        user_id = response.json()["id"]

        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.id == user_id).first()
            user.is_admin = True
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            data={"username": "ops-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        business_timezone = ZoneInfo("America/Edmonton")
        pending_booking_date = datetime.now(business_timezone).date() + timedelta(days=3)
        manual_booking_date = pending_booking_date + timedelta(days=1)
        admin_self_booking_date = manual_booking_date + timedelta(days=1)
        response = self.client.post(
            "/api/bookings",
            headers=admin_headers,
            json={
                "room_id": admin_room_id,
                "start_time": datetime(
                    admin_self_booking_date.year,
                    admin_self_booking_date.month,
                    admin_self_booking_date.day,
                    10,
                    0,
                    tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=admin_headers,
            json={
                "room_id": admin_room_id,
                "start_time": datetime(
                    admin_self_booking_date.year,
                    admin_self_booking_date.month,
                    admin_self_booking_date.day,
                    11,
                    0,
                    tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "paying-user@example.com",
                "password": "Password123!",
                "full_name": "Paying User",
                "phone": "5551239999",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "paying-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "phone": "5551239999",
                "opt_in_sms": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["opt_in_sms"])

        start_time = datetime(
            pending_booking_date.year,
            pending_booking_date.month,
            pending_booking_date.day,
            12,
            0,
            tzinfo=business_timezone,
        )
        target_date = pending_booking_date

        response = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        pending_booking = response.json()
        self.assertEqual(pending_booking["status"], "PendingPayment")
        self.assertTrue(pending_booking["payment_intent_id"].startswith("pi_"))

        event = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": pending_booking["payment_intent_id"],
                    "metadata": {"booking_id": pending_booking["id"]},
                }
            },
        }
        payload = json.dumps(event)
        timestamp = str(int(time.time()))
        signature = hmac.new(
            settings.STRIPE_WEBHOOK_SECRET.encode("utf-8"),
            f"{timestamp}.{payload}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        response = self.client.post(
            "/api/webhooks/stripe",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": f"t={timestamp},v1={signature}",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Paid")

        response = self.client.get(f"/api/bookings/{pending_booking['id']}", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Paid")
        self.assertIsNotNone(response.json()["confirmed_at"])

        response = self.client.get("/api/admin/bookings?email=paying-user@example.com", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["status"], "Paid")

        response = self.client.post(
            f"/api/bookings/{pending_booking['id']}/cancel",
            headers=user_headers,
            json={"reason": "Plans changed"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Cancelled")
        self.assertEqual(response.json()["cancellation_reason"], "Plans changed")

        response = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        availability = response.json()
        self.assertIn(start_time.isoformat(), availability["available_start_times"])

        refund_context = (
            patch("app.services.booking_service.create_refund", return_value="re_smoke_stripe")
            if settings.PAYMENT_BACKEND == "stripe"
            else nullcontext()
        )

        with refund_context:
            response = self.client.post(
                f"/api/admin/bookings/{pending_booking['id']}/refund",
                headers=admin_headers,
                json={"amount_cents": 5000, "reason": "Admin approved refund"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        refund = response.json()
        self.assertEqual(refund["status"], "Processed")
        self.assertEqual(refund["amount_cents"], 5000)

        response = self.client.get("/api/bookings", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["status"], "Refunded")

        manual_start_time = datetime(
            manual_booking_date.year,
            manual_booking_date.month,
            manual_booking_date.day,
            14,
            0,
            tzinfo=business_timezone,
        )
        response = self.client.post(
            "/api/admin/bookings/manual",
            headers=admin_headers,
            json={
                "user_email": "walkin@example.com",
                "full_name": "Walk In",
                "room_id": room_id,
                "start_time": manual_start_time.isoformat(),
                "duration_minutes": 60,
                "note": "Front desk override",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "Paid")
        self.assertEqual(response.json()["user_email"], "walkin@example.com")
        self.assertEqual(response.json()["note"], "Front desk override")

        response = self.client.post(
            "/api/admin/bookings/manual",
            headers=admin_headers,
            json={
                "user_email": "walkin@example.com",
                "full_name": "Walk In",
                "room_id": room_id,
                "start_time": datetime(
                    manual_booking_date.year,
                    manual_booking_date.month,
                    manual_booking_date.day,
                    15,
                    0,
                    tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
                "note": "Same day admin override",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "Paid")
        self.assertEqual(response.json()["user_email"], "walkin@example.com")

        response = self.client.get("/api/admin/bookings?status=Paid", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        paid_bookings = response.json()
        self.assertGreaterEqual(
            sum(1 for booking in paid_bookings if booking["user_email"] == "walkin@example.com"),
            2,
        )
        walk_in_booking_id = next(
            booking["id"] for booking in paid_bookings if booking["user_email"] == "walkin@example.com"
        )

        response = self.client.post(
            f"/api/admin/bookings/{walk_in_booking_id}/check-in",
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Completed")
        self.assertIsNotNone(response.json()["checked_in_at"])

        response = self.client.get("/api/admin/bookings?status=Completed", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any(booking["user_email"] == "walkin@example.com" for booking in response.json()))

        response = self.client.get("/api/admin/analytics/summary", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        analytics = response.json()
        self.assertEqual(analytics["currency"], "CAD")
        self.assertGreaterEqual(analytics["total_bookings"], 2)
        self.assertGreaterEqual(analytics["paid_bookings"], 1)
        self.assertGreaterEqual(analytics["refunded_bookings"], 1)
        self.assertGreaterEqual(analytics["gross_revenue_cents"], 10000)
        self.assertGreaterEqual(analytics["refunded_revenue_cents"], 5000)
        self.assertGreaterEqual(analytics["net_revenue_cents"], 5000)
        room_summary = next(
            summary for summary in analytics["room_summaries"] if summary["room_id"] == room_id
        )
        self.assertEqual(room_summary["total_bookings"], 3)
        self.assertGreaterEqual(room_summary["paid_bookings"], 2)
        self.assertEqual(room_summary["revenue_cents"], 15000)

        response = self.client.get("/api/admin/activity?limit=10", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        activity = response.json()
        activity_actions = [item["action"] for item in activity]
        self.assertIn("manual_booking_created", activity_actions)
        self.assertIn("refund_processed", activity_actions)
        self.assertIn("booking_checked_in", activity_actions)

        response = self.client.get("/api/admin/test-cases", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        test_cases = response.json()
        self.assertTrue(any(item["id"] == "booking-service-regression-matrix" for item in test_cases))
        self.assertTrue(any("/bookings" in item["covered_paths"] for item in test_cases))

        response = self.client.post(
            "/api/admin/bookings/clear-day",
            headers=admin_headers,
            json={"date": manual_booking_date.isoformat()},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"], "day")
        self.assertEqual(response.json()["target_date"], manual_booking_date.isoformat())
        self.assertGreaterEqual(response.json()["deleted_count"], 1)

        response = self.client.get("/api/admin/bookings?email=walkin@example.com", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(any(booking["user_email"] == "walkin@example.com" for booking in response.json()))

        with self.SessionLocal() as db:
            from app.models.booking import Booking

            past_booking = Booking(
                user_id=None,
                room_id=UUID(room_id),
                start_time=datetime.now(timezone.utc) - timedelta(days=2),
                end_time=datetime.now(timezone.utc) - timedelta(days=2) + timedelta(hours=1),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Completed",
                booking_code="PASTCLR1",
                user_email_snapshot="past@example.com",
                user_full_name_snapshot="Past Booking",
                user_phone_snapshot="5552224444",
            )
            db.add(past_booking)
            db.commit()

        response = self.client.post("/api/admin/bookings/clear-past", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"], "past")
        self.assertGreaterEqual(response.json()["deleted_count"], 1)

        response = self.client.get("/api/admin/bookings?booking_code=PASTCLR1", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

        with self.SessionLocal() as db:
            audit_count = db.query(self.AuditLog).count()
            notification_count = db.query(self.NotificationLog).count()
            refund_count = db.query(self.Refund).count()
            webhook_booking = db.query(Booking).filter(Booking.id == pending_booking["id"]).first()
            webhook_notification_types = {
                notification.type
                for notification in db.query(self.NotificationLog)
                .filter(self.NotificationLog.booking_id == pending_booking["id"])
                .all()
            }

        self.assertGreaterEqual(audit_count, 3)
        self.assertGreaterEqual(notification_count, 4)
        self.assertEqual(refund_count, 1)
        self.assertEqual(webhook_booking.status, "Refunded")
        self.assertIn("booking_confirmation_sms_worker", webhook_notification_types)
        self.assertIn("booking_cancellation_sms_worker", webhook_notification_types)
        self.assertIn("refund_processed_sms_worker", webhook_notification_types)

    def test_35_account_management_and_deleted_user_history(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Account Ops Room",
                description="Room for account management coverage",
                capacity=4,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "accounts-admin@example.com",
                "password": "Password123!",
                "full_name": "Accounts Admin",
                "phone": "5555551000",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        admin_id = response.json()["id"]

        with self.SessionLocal() as db:
            admin_user = db.query(self.User).filter(self.User.id == admin_id).first()
            admin_user.is_admin = True
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            data={"username": "accounts-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "history-user@example.com",
                "password": "Password123!",
                "full_name": "History User",
                "phone": "5555552000",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "history-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        history_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.put(
            "/api/users/me",
            headers=history_headers,
            json={
                "billing_address": {
                    "line1": "500 Studio Way",
                    "city": "Calgary",
                    "state": "AB",
                    "postal_code": "T2P1J9",
                    "country": "Canada",
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("saved_payment_method", response.json())

        response = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        history_account = next(
            account for account in response.json() if account["email"] == "history-user@example.com"
        )
        self.assertNotIn("saved_payment_method", history_account)
        self.assertEqual(history_account["billing_address"]["city"], "Calgary")

        business_timezone = ZoneInfo("America/Edmonton")
        start_time = datetime(2026, 4, 5, 11, 0, tzinfo=business_timezone)
        response = self.client.post(
            "/api/bookings",
            headers=history_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()

        response = self.client.delete("/api/users/me", headers=history_headers)
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.get("/api/auth/me", headers=history_headers)
        self.assertEqual(response.status_code, 401, response.text)

        response = self.client.get("/api/admin/bookings?email=history-user@example.com", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any(item["booking_code"] == booking["booking_code"] for item in response.json()))
        deleted_user_booking = next(
            item for item in response.json() if item["booking_code"] == booking["booking_code"]
        )
        self.assertEqual(deleted_user_booking["user_email"], "history-user@example.com")
        self.assertEqual(deleted_user_booking["user_full_name"], "History User")
        self.assertEqual(deleted_user_booking["user_phone"], "5555552000")

        response = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(any(account["email"] == "history-user@example.com" for account in response.json()))

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "delete-by-admin@example.com",
                "password": "Password123!",
                "full_name": "Delete By Admin",
                "phone": "5555553000",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        removable_user_id = response.json()["id"]

        response = self.client.delete(f"/api/admin/users/{removable_user_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(any(account["email"] == "delete-by-admin@example.com" for account in response.json()))

    def test_40_week_seven_eight_ops(self) -> None:
        from app.celery_app import celery_app
        from app.models.booking import Booking, BookingSlot, NotificationLog
        from app.models.room import Room
        from app.schemas.booking import BookingCreate
        from app.services.booking_service import BookingConflictError, create_booking
        from app.tasks import cleanup_expired_pending_bookings_task, dispatch_due_reminders_task

        beat_schedule = getattr(celery_app.conf, "beat_schedule", {})
        self.assertIn("dispatch-reminders-24h", beat_schedule)
        self.assertIn("dispatch-reminders-5h", beat_schedule)
        self.assertIn("dispatch-reminders-1h", beat_schedule)
        self.assertIn("cleanup-expired-pending-bookings", beat_schedule)

        with self.SessionLocal() as db:
            room = Room(
                name="Ops Room",
                description="Room used for Week 7 and 8 tests",
                capacity=6,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = room.id

        for email in ("ops-1@example.com", "ops-2@example.com", "ops-3@example.com"):
            response = self.client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": "Password123!",
                    "full_name": email.split("@")[0],
                    "phone": "5557778888",
                },
            )
            self.assertEqual(response.status_code, 201, response.text)

        with self.SessionLocal() as db:
            users = {
                user.email: user
                for user in db.query(self.User)
                .filter(self.User.email.in_(["ops-1@example.com", "ops-2@example.com", "ops-3@example.com"]))
                .all()
            }
            user_one_id = users["ops-1@example.com"].id
            user_two_id = users["ops-2@example.com"].id
            reminder_user = users["ops-3@example.com"]
            reminder_user.opt_in_sms = True

            reminder_booking = Booking(
                user_id=reminder_user.id,
                room_id=room_id,
                start_time=datetime.now(timezone.utc) + timedelta(hours=24),
                end_time=datetime.now(timezone.utc) + timedelta(hours=25),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Paid",
                booking_code="REMIND24",
                payment_intent_id="pi_stub_reminder",
                confirmed_at=datetime.now(timezone.utc),
            )
            db.add(reminder_booking)
            db.flush()
            db.add_all(
                [
                    BookingSlot(
                        booking_id=reminder_booking.id,
                        room_id=room_id,
                        slot_start=reminder_booking.start_time,
                    ),
                    BookingSlot(
                        booking_id=reminder_booking.id,
                        room_id=room_id,
                        slot_start=reminder_booking.start_time + timedelta(minutes=30),
                    ),
                ]
            )

            reminder_booking_5h = Booking(
                user_id=reminder_user.id,
                room_id=room_id,
                start_time=datetime.now(timezone.utc) + timedelta(hours=5),
                end_time=datetime.now(timezone.utc) + timedelta(hours=6),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Paid",
                booking_code="REMIND05",
                payment_intent_id="pi_stub_reminder_5h",
                confirmed_at=datetime.now(timezone.utc),
            )
            db.add(reminder_booking_5h)
            db.flush()
            db.add_all(
                [
                    BookingSlot(
                        booking_id=reminder_booking_5h.id,
                        room_id=room_id,
                        slot_start=reminder_booking_5h.start_time,
                    ),
                    BookingSlot(
                        booking_id=reminder_booking_5h.id,
                        room_id=room_id,
                        slot_start=reminder_booking_5h.start_time + timedelta(minutes=30),
                    ),
                ]
            )

            expired_booking = Booking(
                user_id=reminder_user.id,
                room_id=room_id,
                start_time=datetime.now(timezone.utc) + timedelta(days=2),
                end_time=datetime.now(timezone.utc) + timedelta(days=2, hours=1),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="PendingPayment",
                booking_code="EXPIRED24",
                payment_intent_id="pi_stub_expired",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            )
            db.add(expired_booking)
            db.flush()
            db.add_all(
                [
                    BookingSlot(
                        booking_id=expired_booking.id,
                        room_id=room_id,
                        slot_start=expired_booking.start_time,
                    ),
                    BookingSlot(
                        booking_id=expired_booking.id,
                        room_id=room_id,
                        slot_start=expired_booking.start_time + timedelta(minutes=30),
                    ),
                ]
            )
            expired_booking_id = expired_booking.id
            db.commit()

        reminder_result = dispatch_due_reminders_task(24)
        self.assertEqual(reminder_result["sent"], 2)
        reminder_result_5h = dispatch_due_reminders_task(5)
        self.assertEqual(reminder_result_5h["sent"], 2)

        cleanup_result = cleanup_expired_pending_bookings_task(5)
        self.assertEqual(cleanup_result["cleaned"], 1)

        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("studio_http_requests_total", response.text)
        self.assertIn("studio_http_request_duration_seconds_total", response.text)
        self.assertIn('studio_task_runs_total{task="dispatch_due_reminders"}', response.text)
        self.assertIn('studio_task_runs_total{task="cleanup_expired_pending_bookings"}', response.text)
        self.assertIn('studio_task_items_total{task="dispatch_due_reminders",result="sent"}', response.text)
        self.assertIn('studio_task_items_total{task="cleanup_expired_pending_bookings",result="cleaned"}', response.text)

        with self.SessionLocal() as db:
            reminder_notifications = (
                db.query(NotificationLog)
                .filter(
                    NotificationLog.type.in_(
                        (
                            "reminder_24h_email",
                            "reminder_24h_sms",
                            "reminder_5h_email",
                            "reminder_5h_sms",
                        )
                    )
                )
                .all()
            )
            expired_booking = db.query(Booking).filter(Booking.id == expired_booking_id).first()
            expired_slots_remaining = (
                db.query(BookingSlot)
                .filter(BookingSlot.booking_id == expired_booking_id)
                .count()
            )

        reminder_notification_types = {notification.type for notification in reminder_notifications}
        self.assertEqual(len(reminder_notifications), 4)
        self.assertIn("reminder_24h_email", reminder_notification_types)
        self.assertIn("reminder_24h_sms", reminder_notification_types)
        self.assertIn("reminder_5h_email", reminder_notification_types)
        self.assertIn("reminder_5h_sms", reminder_notification_types)
        self.assertEqual(expired_booking.status, "Cancelled")
        self.assertEqual(expired_booking.cancellation_reason, "Payment window expired after 5 minutes")
        self.assertEqual(expired_slots_remaining, 0)

        start_time = datetime(2026, 4, 5, 10, 0, tzinfo=ZoneInfo("America/Edmonton"))
        barrier = Barrier(3)

        def attempt_booking(user_id):
            barrier.wait()
            db = self.SessionLocal()
            try:
                user = db.query(self.User).filter(self.User.id == user_id).first()
                booking = create_booking(
                    db,
                    user,
                    BookingCreate(
                        room_id=room_id,
                        start_time=start_time,
                        duration_minutes=60,
                    ),
                )
                return ("success", str(booking.id))
            except BookingConflictError:
                return ("conflict", None)
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_one = executor.submit(attempt_booking, user_one_id)
            future_two = executor.submit(attempt_booking, user_two_id)
            barrier.wait()
            outcomes = [future_one.result(), future_two.result()]

        statuses = sorted(status for status, _ in outcomes)
        self.assertEqual(statuses, ["conflict", "success"])


if __name__ == "__main__":
    unittest.main()
