import pytest

from shop.models import Product


def test_security_headers_present(client):
    response = client.get("/")
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self' https://checkout.stripe.com" in csp
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize("bad", ["red", "#fff", "#12345g", "#123456;x", ""])
def test_product_color_must_be_hex(app, bad):
    with pytest.raises(ValueError):
        Product(slug="x", name="X", price_cents=100, color=bad)


@pytest.mark.parametrize("bad", [0, -5, 1.5])
def test_product_price_must_be_positive_int(app, bad):
    with pytest.raises(ValueError):
        Product(slug="x", name="X", price_cents=bad, color="#aabbcc")


def test_money_filter_uses_currency(app):
    from shop import format_money

    with app.test_request_context():
        assert format_money(123456) == "$1,234.56"
        assert format_money(500, "gbp") == "\u00a35.00"
        assert format_money(500, "sek") == "SEK 5.00"


def test_unsupported_currency_fails_fast():
    from config import TestConfig
    from shop import create_app

    class Yen(TestConfig):
        CURRENCY = "jpy"

    with pytest.raises(RuntimeError, match="Unsupported CURRENCY"):
        create_app(Yen)


def test_register_race_on_unique_email_is_handled(client, monkeypatch):
    """Simulate the pre-check missing a concurrent insert of the same email."""
    from shop.extensions import db
    from shop.models import User

    from .conftest import register

    register(client, email="race@example.com")
    client.post("/logout")

    real_scalar = db.session.scalar
    monkeypatch.setattr(
        db.session, "scalar",
        lambda stmt, *a, **k: None if "user" in str(stmt).lower() else real_scalar(stmt, *a, **k),
    )
    response = register(client, email="race@example.com")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    monkeypatch.undo()
    assert db.session.query(User).count() == 1
