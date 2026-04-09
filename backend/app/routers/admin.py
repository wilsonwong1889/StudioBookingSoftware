from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_admin_user
from app.core.rate_limit import rate_limit_dependency
from app.database import get_db
from app.models.room import Room
from app.models.staff_profile import StaffProfile  # noqa: F401
from app.models.user import User
from app.schemas.room import RoomOut, RoomPhotoUploadOut, RoomUpdate
from app.schemas.booking import (
    AdminActivityItemOut,
    AdminAnalyticsSummaryOut,
    AdminBookingLookupOut,
    AdminBookingBulkClearResultOut,
    AdminBookingClearByDateIn,
    BookingOut,
    ManualBookingCreate,
    RefundCreate,
    RefundOut,
)
from app.schemas.admin import AdminTestCaseOut
from app.schemas.admin import AdminSuiteDashMetaOut, AdminSuiteDashStatusOut
from app.schemas.staff import StaffPhotoUploadOut, StaffProfileCreate, StaffProfileOut, StaffProfileUpdate
from app.schemas.user import AdminUserAccountOut
from app.schemas.user import AdminUserDeleteConfirm
from app.core.security import verify_password
from app.services.account_service import can_delete_admin_account, delete_user_account, list_accounts_for_admin
from app.services.booking_service import (
    check_in_booking,
    create_manual_booking,
    create_audit_log,
    DailyBookingLimitError,
    get_admin_analytics_summary,
    list_recent_admin_activity,
    lookup_bookings_for_admin,
    mark_booking_paid_manually,
    process_refund,
    StaffAvailabilityError,
    StaffSelectionError,
    waive_booking_payment,
    clear_bookings_for_admin_day,
    clear_past_bookings_for_admin,
)
from app.services.payment_service import PaymentBackendError
from app.services.staff_service import (
    create_staff_profile,
    delete_staff_profile,
    list_staff_profiles,
    update_staff_profile,
)
from app.services.test_case_service import list_admin_test_cases
from app.services.suitedash_service import (
    SuiteDashConfigurationError,
    SuiteDashRequestError,
    fetch_suitedash_contact_meta,
    get_suitedash_status,
)


router = APIRouter(prefix="/api/admin", tags=["Admin"])
admin_rate_limit = rate_limit_dependency("admin", settings.ADMIN_RATE_LIMIT_MAX_REQUESTS)
STAFF_MEDIA_DIR = Path(__file__).resolve().parents[1] / "frontend" / "media" / "staff"
ROOM_MEDIA_DIR = Path(__file__).resolve().parents[1] / "frontend" / "media" / "rooms"
MAX_STAFF_PHOTO_BYTES = 5 * 1024 * 1024


def _is_jpeg_bytes(file_bytes: bytes) -> bool:
    return len(file_bytes) >= 4 and file_bytes.startswith(b"\xff\xd8\xff") and file_bytes.endswith(b"\xff\xd9")


@router.get("/analytics/summary", response_model=AdminAnalyticsSummaryOut)
def admin_analytics_summary(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return get_admin_analytics_summary(db)


@router.get("/users", response_model=List[AdminUserAccountOut])
def admin_list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_accounts_for_admin(db)


@router.get("/test-cases", response_model=List[AdminTestCaseOut])
def admin_list_test_cases(
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_admin_test_cases()


@router.get("/integrations/suitedash/status", response_model=AdminSuiteDashStatusOut)
def admin_suitedash_status(
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return get_suitedash_status()


@router.get("/integrations/suitedash/contact-meta", response_model=AdminSuiteDashMetaOut)
def admin_suitedash_contact_meta(
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return {"data": fetch_suitedash_contact_meta()}
    except SuiteDashConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SuiteDashRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/users/{user_id}", status_code=204)
def admin_delete_user(
    user_id: str,
    payload: AdminUserDeleteConfirm,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    if not verify_password(payload.admin_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="Admin password is incorrect")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Use the account page to delete your own profile")
    if user.is_admin and not can_delete_admin_account(db, user):
        raise HTTPException(status_code=400, detail="At least one admin account must remain")

    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="user_deleted_by_admin",
        details={"deleted_user_id": str(user.id), "deleted_user_email": user.email},
    )
    delete_user_account(db, user)
    db.commit()


@router.get("/activity", response_model=List[AdminActivityItemOut])
def admin_recent_activity(
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_recent_admin_activity(db, limit=limit)


@router.get("/staff", response_model=List[StaffProfileOut])
def admin_list_staff_profiles(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_staff_profiles(db)


@router.post("/staff", response_model=StaffProfileOut, status_code=201)
def admin_create_staff_profile(
    payload: StaffProfileCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        profile = create_staff_profile(db, payload)
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="staff_profile_created",
            details={"staff_profile_id": str(profile.id), "name": profile.name},
        )
        db.commit()
        return profile
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/staff/{staff_profile_id}", response_model=StaffProfileOut)
def admin_update_staff_profile(
    staff_profile_id: str,
    payload: StaffProfileUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        profile = update_staff_profile(db, staff_profile_id, payload)
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="staff_profile_updated",
            details={"staff_profile_id": str(profile.id), "updated_fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        )
        db.commit()
        return profile
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/staff/{staff_profile_id}", status_code=204)
def admin_delete_staff_profile(
    staff_profile_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        delete_staff_profile(db, staff_profile_id)
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="staff_profile_deleted",
            details={"staff_profile_id": staff_profile_id},
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/staff/photo", response_model=StaffPhotoUploadOut)
async def admin_upload_staff_photo(
    photo: UploadFile = File(...),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    filename = (photo.filename or "").lower()
    if not filename.endswith((".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Only JPG staff profile photos are supported")

    file_bytes = await photo.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded photo is empty")
    if len(file_bytes) > MAX_STAFF_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Staff profile photo must be 5 MB or smaller")
    if not _is_jpeg_bytes(file_bytes):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid JPG image")

    STAFF_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    saved_filename = f"{uuid4().hex}.jpg"
    saved_path = STAFF_MEDIA_DIR / saved_filename
    saved_path.write_bytes(file_bytes)
    return {"photo_url": f"/assets/media/staff/{saved_filename}"}


@router.post("/rooms/photo", response_model=RoomPhotoUploadOut)
async def admin_upload_room_photo(
    photo: UploadFile = File(...),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    filename = (photo.filename or "").lower()
    if not filename.endswith((".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Only JPG room photos are supported")

    file_bytes = await photo.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded photo is empty")
    if len(file_bytes) > MAX_STAFF_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Room photo must be 5 MB or smaller")
    if not _is_jpeg_bytes(file_bytes):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid JPG image")

    ROOM_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    saved_filename = f"{uuid4().hex}.jpg"
    saved_path = ROOM_MEDIA_DIR / saved_filename
    saved_path.write_bytes(file_bytes)
    return {"photo_url": f"/assets/media/rooms/{saved_filename}"}


@router.get("/bookings", response_model=List[AdminBookingLookupOut])
def admin_bookings(
    status: Optional[str] = Query(default=None),
    email: Optional[str] = Query(default=None),
    booking_code: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return lookup_bookings_for_admin(
        db,
        status=status,
        email=email,
        booking_code=booking_code,
    )


@router.post("/bookings/clear-day", response_model=AdminBookingBulkClearResultOut)
def admin_clear_bookings_for_day(
    payload: AdminBookingClearByDateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return clear_bookings_for_admin_day(db, admin, payload.date)


@router.post("/bookings/clear-past", response_model=AdminBookingBulkClearResultOut)
def admin_clear_past_bookings(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return clear_past_bookings_for_admin(db, admin)


@router.post("/bookings/manual", response_model=AdminBookingLookupOut, status_code=201)
def admin_manual_booking(
    payload: ManualBookingCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        booking = create_manual_booking(db, admin, payload)
    except DailyBookingLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffAvailabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return booking


@router.post("/bookings/{booking_id}/refund", response_model=RefundOut)
def admin_refund_booking(
    booking_id: str,
    payload: RefundCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return process_refund(db, booking_id, admin, payload)
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/check-in", response_model=BookingOut)
def admin_check_in_booking(
    booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return check_in_booking(db, booking_id, admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/waive-payment", response_model=BookingOut)
def admin_waive_booking_payment(
    booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return waive_booking_payment(db, booking_id, admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/mark-paid", response_model=BookingOut)
def admin_mark_booking_paid(
    booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return mark_booking_paid_manually(db, booking_id, admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/rooms", response_model=List[RoomOut])
def admin_list_rooms(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return db.query(Room).order_by(Room.created_at.desc()).all()


@router.get("/rooms/{room_id}", response_model=RoomOut)
def admin_get_room(
    room_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.put("/rooms/{room_id}", response_model=RoomOut)
def admin_update_room(
    room_id: str,
    payload: RoomUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="room_updated",
        details={"room_id": room_id, "updated_fields": sorted(update_data.keys())},
    )
    db.commit()
    db.refresh(room)
    return room
