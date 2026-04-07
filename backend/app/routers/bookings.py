from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.rate_limit import rate_limit_dependency
from app.database import get_db
from app.models.user import User
from app.schemas.booking import (
    BookingAvailabilityOut,
    BookingCancel,
    BookingCreate,
    BookingOut,
    PaymentSessionOut,
    ReservationCreate,
    ReservationOut,
)
from app.services.booking_service import (
    BookingConflictError,
    DailyBookingLimitError,
    cancel_booking,
    create_booking,
    create_reservation_hold,
    get_booking_payment_session,
    get_booking_for_user,
    get_room_availability,
    list_bookings_for_user,
    PaymentSessionError,
    StaffAvailabilityError,
    StaffSelectionError,
)
from app.config import settings
from app.services.payment_service import PaymentBackendError


router = APIRouter(prefix="/api", tags=["Bookings"])
booking_rate_limit = rate_limit_dependency("booking", settings.BOOKING_RATE_LIMIT_MAX_REQUESTS)


@router.get("/rooms/{room_id}/availability", response_model=BookingAvailabilityOut)
def room_availability(
    room_id: str,
    date_value: date = Query(alias="date"),
    db: Session = Depends(get_db),
):
    try:
        return get_room_availability(db, room_id, date_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bookings/reservations", response_model=ReservationOut, status_code=201)
def create_reservation(
    payload: ReservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    try:
        return create_reservation_hold(
            db,
            payload.room_id,
            payload.start_time,
            payload.duration_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking_endpoint(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    try:
        return create_booking(db, current_user, payload)
    except DailyBookingLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffAvailabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/bookings", response_model=List[BookingOut])
def list_my_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_bookings_for_user(db, current_user)


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def get_my_booking(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.post("/bookings/{booking_id}/payment-session", response_model=PaymentSessionOut)
def get_my_booking_payment_session(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        return get_booking_payment_session(db, booking, current_user)
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PaymentSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_my_booking(
    booking_id: str,
    payload: BookingCancel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        return cancel_booking(db, booking, current_user, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
