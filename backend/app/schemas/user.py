from pydantic import BaseModel, EmailStr, Field, field_validator
from uuid import UUID
from typing import Optional
from datetime import date, datetime


class BillingAddress(BaseModel):
    line1: str
    line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class SavedPaymentMethod(BaseModel):
    payment_method_id: Optional[str] = None
    brand: Optional[str] = None
    last4: Optional[str] = Field(default=None, min_length=4, max_length=4)
    exp_month: Optional[int] = Field(default=None, ge=1, le=12)
    exp_year: Optional[int] = Field(default=None, ge=2024, le=2100)

    @field_validator("last4", mode="before")
    @classmethod
    def normalize_last4(cls, value):
        if value in (None, ""):
            return None
        digits = "".join(character for character in str(value) if character.isdigit())
        if not digits:
            return None
        return digits[-4:]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str
    phone: Optional[str] = None

class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str]
    phone: Optional[str]
    birthday: Optional[date] = None
    billing_address: Optional[BillingAddress] = None
    saved_payment_method: Optional[SavedPaymentMethod] = None
    opt_in_email: bool
    opt_in_sms: bool
    two_factor_enabled: bool = False
    two_factor_method: Optional[str] = None
    is_admin: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AdminUserAccountOut(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str]
    phone: Optional[str]
    birthday: Optional[date] = None
    billing_address: Optional[BillingAddress] = None
    saved_payment_method: Optional[SavedPaymentMethod] = None
    stripe_customer_id: Optional[str] = None
    opt_in_email: bool
    opt_in_sms: bool
    two_factor_enabled: bool = False
    two_factor_method: Optional[str] = None
    is_admin: bool
    booking_count: int = 0
    last_booking_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    birthday: Optional[date] = None
    opt_in_email: Optional[bool] = None
    opt_in_sms: Optional[bool] = None
    billing_address: Optional[BillingAddress] = None
    saved_payment_method: Optional[SavedPaymentMethod] = None
    two_factor_enabled: Optional[bool] = None
    two_factor_method: Optional[str] = None


class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

class Token(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    two_factor_required: bool = False
    two_factor_token: Optional[str] = None
    two_factor_method: Optional[str] = None


class TwoFactorVerifyIn(BaseModel):
    two_factor_token: str
    code: str = Field(min_length=6, max_length=6)


class TwoFactorResendIn(BaseModel):
    two_factor_token: str


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    reset_token: str
    new_password: str = Field(min_length=8, max_length=128)
