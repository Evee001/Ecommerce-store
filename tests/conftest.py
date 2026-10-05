import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import TestConfig  # noqa: E402
from shop import create_app  # noqa: E402
from shop.extensions import db  # noqa: E402
from shop.seed import seed_products  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        seed_products()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, email="ada@example.com", name="Ada", password=PASSWORD, **params):
    return client.post(
        "/register",
        query_string=params,
        data={"name": name, "email": email, "password": password, "confirm": password},
    )


@pytest.fixture
def logged_in(client):
    register(client)
    return client


@pytest.fixture
def fake_stripe(monkeypatch):
    """Replace network calls to Stripe with in-memory fakes."""
    import stripe

    calls = {"create": [], "retrieve": [], "payment_status": "paid"}

    def create(**kwargs):
        calls["create"].append(kwargs)
        n = len(calls["create"])
        return SimpleNamespace(id=f"cs_test_{n}", url=f"https://checkout.stripe.com/c/pay/cs_test_{n}")

    def retrieve(session_id):
        calls["retrieve"].append(session_id)
        return SimpleNamespace(id=session_id, payment_status=calls["payment_status"])

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(create))
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", staticmethod(retrieve))
    return calls
