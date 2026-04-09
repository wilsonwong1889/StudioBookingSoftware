import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Date, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String)
    phone = Column(String)
    birthday = Column(Date)
    billing_address = Column(JSONB)
    stripe_customer_id = Column(String)
    opt_in_email = Column(Boolean, default=True)
    opt_in_sms = Column(Boolean, default=False)
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_method = Column(String, default="email")
    two_factor_code_hash = Column(String)
    two_factor_code_expires_at = Column(DateTime(timezone=True))
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
