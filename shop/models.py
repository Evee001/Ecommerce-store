import re
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy.orm import validates
from sqlalchemy.types import DateTime, TypeDecorator

from .extensions import db

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Store datetimes as UTC and always hand back timezone-aware values.

    SQLite has no timezone support and returns naive datetimes, which would
    break arithmetic against datetime.now(timezone.utc).
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(UTCDateTime(), default=_now, nullable=False)

    orders = db.relationship("Order", back_populates="user", order_by="Order.created_at.desc()")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    tagline = db.Column(db.String(200), nullable=False, default="")
    description = db.Column(db.Text, nullable=False, default="")
    price_cents = db.Column(db.Integer, nullable=False)
    glyph = db.Column(db.String(8), nullable=False, default="*")
    color = db.Column(db.String(7), nullable=False, default="#f4d35e")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    @validates("color")
    def _validate_color(self, _key: str, value: str) -> str:
        # Rendered inside a style attribute, so only allow a plain hex colour.
        if not HEX_COLOR.fullmatch(value or ""):
            raise ValueError(f"Invalid product colour {value!r}; expected #rrggbb")
        return value.lower()

    @validates("price_cents")
    def _validate_price(self, _key: str, value: int) -> int:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("price_cents must be a positive integer")
        return value


class Order(db.Model):
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    total_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    stripe_session_id = db.Column(db.String(255), unique=True, index=True)
    created_at = db.Column(UTCDateTime(), default=_now, nullable=False)
    paid_at = db.Column(UTCDateTime())

    user = db.relationship("User", back_populates="orders")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    # Name and price are copied so past orders survive later catalogue edits.
    name = db.Column(db.String(120), nullable=False)
    unit_price_cents = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    order = db.relationship("Order", back_populates="items")

    @property
    def subtotal_cents(self) -> int:
        return self.unit_price_cents * self.quantity
