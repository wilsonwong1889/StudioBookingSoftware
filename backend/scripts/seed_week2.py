import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.database import SessionLocal
from app.services.seed_service import ensure_admin_user, ensure_rooms, ensure_staff_profiles


def main() -> None:
    db = SessionLocal()
    try:
        admin = ensure_admin_user(
            db,
            email=os.environ.get("SEED_ADMIN_EMAIL", "admin@example.com"),
            password=os.environ.get("SEED_ADMIN_PASSWORD", "change-me-admin-password"),
            full_name=os.environ.get("SEED_ADMIN_FULL_NAME", "Studio Admin"),
        )
        staff_profiles = ensure_staff_profiles(db)
        rooms = ensure_rooms(db)
        admin_email = admin.email
        staff_profile_count = len(staff_profiles)
        room_count = len(rooms)
    finally:
        db.close()

    print(f"Admin ready: {admin_email}")
    print(f"Staff profiles created this run: {staff_profile_count}")
    print(f"Rooms created this run: {room_count}")


if __name__ == "__main__":
    main()
