from sqlalchemy import select

from shop.auth import _safe_next
from shop.extensions import db
from shop.models import User

from .conftest import PASSWORD, register


def test_register_creates_user_with_hashed_password(client):
    response = register(client, email="  Ada@Example.com ")
    assert response.status_code == 302

    user = db.session.scalar(select(User))
    assert user.email == "ada@example.com"
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith(("scrypt:", "pbkdf2:"))


def test_register_rejects_duplicate_email(client):
    register(client)
    client.post("/logout")
    response = register(client)
    assert response.headers["Location"].endswith("/login")
    assert db.session.query(User).count() == 1


def test_register_validates_password_length_and_match(client):
    response = client.post(
        "/register",
        data={"name": "A", "email": "a@example.com", "password": "short", "confirm": "nope"},
    )
    assert response.status_code == 200
    assert b"Passwords must match" in response.data
    assert db.session.query(User).count() == 0


def test_login_success_and_failure(client):
    register(client)
    client.post("/logout")

    bad = client.post("/login", data={"email": "ada@example.com", "password": "wrong-password"})
    assert b"Incorrect email or password" in bad.data

    good = client.post("/login", data={"email": "ADA@example.com", "password": PASSWORD})
    assert good.status_code == 302
    assert b"Log out" in client.get("/").data


def test_logout_requires_post_and_clears_cart(client):
    register(client)
    client.post("/cart/add/1", data={"quantity": "1"})
    assert client.get("/logout").status_code == 405

    client.post("/logout")
    assert b"Your cart is empty" in client.get("/cart").data
    assert b"Log in" in client.get("/").data


def test_login_redirects_to_safe_next_only(client):
    register(client)
    client.post("/logout")
    response = client.post(
        "/login?next=https://evil.example/phish",
        data={"email": "ada@example.com", "password": PASSWORD},
    )
    assert response.headers["Location"] == "/"


def test_safe_next(app):
    with app.test_request_context():
        assert _safe_next("/cart") == "/cart"
        assert _safe_next("//evil.example") == "/"
        assert _safe_next("https://evil.example") == "/"
        assert _safe_next("/\\evil.example") == "/"
        assert _safe_next(None) == "/"


def test_orders_page_requires_login(client):
    response = client.get("/orders")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
