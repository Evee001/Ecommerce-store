"""Session-backed shopping cart.

The cart is stored in the signed session cookie as {product_id: quantity}.
Only ids and quantities live client-side; prices are always read from the
database so a tampered cookie can never change what a customer pays.
"""

from dataclasses import dataclass

from flask import session
from sqlalchemy import select

from .extensions import db
from .models import Product

CART_KEY = "cart"
MAX_QTY_PER_ITEM = 10
MAX_DISTINCT_ITEMS = 50


@dataclass(frozen=True)
class CartLine:
    product: Product
    quantity: int

    @property
    def subtotal_cents(self) -> int:
        return self.product.price_cents * self.quantity


def _clamp(quantity: int) -> int:
    return max(0, min(int(quantity), MAX_QTY_PER_ITEM))


def get_cart() -> dict[str, int]:
    raw = session.get(CART_KEY)
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): _clamp(qty)
        for key, qty in raw.items()
        if str(key).isdigit() and isinstance(qty, int) and qty > 0
    }


def save_cart(cart: dict[str, int]) -> None:
    session[CART_KEY] = dict(cart)


def clear_cart() -> None:
    session.pop(CART_KEY, None)


def with_quantity(cart: dict[str, int], product_id: int, quantity: int) -> dict[str, int]:
    """Return a new cart with product_id set to quantity (0 removes it)."""
    key = str(product_id)
    qty = _clamp(quantity)
    rest = {k: v for k, v in cart.items() if k != key}
    if qty == 0:
        return rest
    if key not in cart and len(rest) >= MAX_DISTINCT_ITEMS:
        return dict(cart)
    return {**rest, key: qty}


def with_added(cart: dict[str, int], product_id: int, quantity: int) -> dict[str, int]:
    return with_quantity(cart, product_id, cart.get(str(product_id), 0) + quantity)


def item_count(cart: dict[str, int]) -> int:
    return sum(cart.values())


def build_lines(cart: dict[str, int]) -> list[CartLine]:
    """Resolve cart ids to active products, dropping any that no longer exist."""
    if not cart:
        return []
    ids = [int(k) for k in cart]
    products = db.session.scalars(
        select(Product).where(Product.id.in_(ids), Product.is_active.is_(True))
    ).all()
    by_id = {p.id: p for p in products}
    return [CartLine(by_id[i], cart[str(i)]) for i in ids if i in by_id]


def total_cents(lines: list[CartLine]) -> int:
    return sum(line.subtotal_cents for line in lines)


def parse_quantity(value: str | None, default: int = 1) -> int | None:
    """Parse a form quantity; returns None when it is not a valid integer in range."""
    if value is None or value == "":
        return default
    try:
        qty = int(value)
    except (TypeError, ValueError):
        return None
    return qty if 0 <= qty <= MAX_QTY_PER_ITEM else None
