from types import SimpleNamespace

import pytest
import stripe
from sqlalchemy import select

from shop.extensions import db
from shop.models import Order, Product

from .conftest import register


def _add(client, slug, qty):
    product = db.session.scalar(select(Product).filter_by(slug=slug))
    client.post(f"/cart/add/{product.id}", data={"quantity": str(qty)})
    return product


def test_checkout_requires_login(client, fake_stripe):
    response = client.post("/checkout")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert fake_stripe["create"] == []


def test_checkout_with_empty_cart_does_not_call_stripe(logged_in, fake_stripe):
    response = logged_in.post("/checkout")
    assert response.headers["Location"].endswith("/cart")
    assert fake_stripe["create"] == []


def test_checkout_creates_pending_order_and_redirects_to_stripe(logged_in, fake_stripe):
    _add(logged_in, "deep-thinker-mug", 2)
    _add(logged_in, "long-view-poster", 1)

    response = logged_in.post("/checkout")

    assert response.status_code == 303
    assert response.headers["Location"].startswith("https://checkout.stripe.com/")

    order = db.session.scalar(select(Order))
    assert order.status == Order.STATUS_PENDING
    assert order.total_cents == 2 * 1800 + 2500
    assert order.stripe_session_id == "cs_test_1"

    sent = fake_stripe["create"][0]
    assert sent["mode"] == "payment"
    assert sent["client_reference_id"] == str(order.id)
    assert sent["customer_email"] == "ada@example.com"
    assert "{CHECKOUT_SESSION_ID}" in sent["success_url"]
    amounts = sorted((li["price_data"]["unit_amount"], li["quantity"]) for li in sent["line_items"])
    assert amounts == [(1800, 2), (2500, 1)]


def test_success_marks_order_paid_and_clears_cart(logged_in, fake_stripe):
    _add(logged_in, "deep-thinker-mug", 1)
    logged_in.post("/checkout")

    page = logged_in.get("/checkout/success?session_id=cs_test_1")

    assert page.status_code == 200
    assert b"Thank you" in page.data
    assert db.session.scalar(select(Order)).status == Order.STATUS_PAID
    assert b"Your cart is empty" in logged_in.get("/cart").data
    assert b"paid" in logged_in.get("/orders").data


def test_success_does_not_fulfil_unpaid_session(logged_in, fake_stripe):
    fake_stripe["payment_status"] = "unpaid"
    _add(logged_in, "deep-thinker-mug", 1)
    logged_in.post("/checkout")

    page = logged_in.get("/checkout/success?session_id=cs_test_1")

    assert b"Almost there" in page.data
    assert db.session.scalar(select(Order)).status == Order.STATUS_PENDING
    assert b"Deep Thinker Mug" in logged_in.get("/cart").data


def test_success_rejects_other_users_session(client, fake_stripe):
    register(client, email="ada@example.com")
    _add(client, "deep-thinker-mug", 1)
    client.post("/checkout")
    client.post("/logout")

    register(client, email="eve@example.com", name="Eve")
    assert client.get("/checkout/success?session_id=cs_test_1").status_code == 404
    assert client.get("/checkout/success?session_id=nonsense").status_code == 404


def test_stripe_failure_rolls_back_order(logged_in, monkeypatch):
    def boom(**_kwargs):
        raise stripe.APIConnectionError("network down")

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(boom))
    _add(logged_in, "deep-thinker-mug", 1)

    response = logged_in.post("/checkout", follow_redirects=True)

    assert b"start checkout right now" in response.data
    assert db.session.query(Order).count() == 0


# --- Webhook -----------------------------------------------------------------

def _event(event_type, session_id, payment_status="paid"):
    session = SimpleNamespace(id=session_id, payment_status=payment_status)
    return SimpleNamespace(type=event_type, data=SimpleNamespace(object=session))


def _fake_event(monkeypatch, event):
    monkeypatch.setattr(stripe.Webhook, "construct_event", staticmethod(lambda *_a: event))


@pytest.fixture
def pending_order(logged_in, fake_stripe):
    _add(logged_in, "deep-thinker-mug", 1)
    logged_in.post("/checkout")
    return db.session.scalar(select(Order))


def _post_webhook(client):
    return client.post("/webhook", data=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})


def test_webhook_rejects_bad_signature(client):
    assert _post_webhook(client).status_code == 400


def test_webhook_completed_fulfils_order_idempotently(client, pending_order, monkeypatch):
    _fake_event(monkeypatch, _event("checkout.session.completed", "cs_test_1"))
    assert _post_webhook(client).status_code == 200
    first_paid_at = db.session.get(Order, pending_order.id).paid_at
    assert _post_webhook(client).status_code == 200

    order = db.session.get(Order, pending_order.id)
    assert order.status == Order.STATUS_PAID
    assert order.paid_at == first_paid_at


def test_webhook_completed_but_unpaid_does_not_fulfil(client, pending_order, monkeypatch):
    _fake_event(monkeypatch, _event("checkout.session.completed", "cs_test_1", "unpaid"))
    _post_webhook(client)
    assert db.session.get(Order, pending_order.id).status == Order.STATUS_PENDING


def test_webhook_expired_cancels_pending_order(client, pending_order, monkeypatch):
    _fake_event(monkeypatch, _event("checkout.session.expired", "cs_test_1", "unpaid"))
    _post_webhook(client)
    assert db.session.get(Order, pending_order.id).status == Order.STATUS_CANCELLED


def test_webhook_unknown_session_is_acknowledged(client, monkeypatch):
    _fake_event(monkeypatch, _event("checkout.session.completed", "cs_unknown"))
    assert _post_webhook(client).status_code == 200


def test_missing_secret_key_fails_fast():
    from config import TestConfig
    from shop import create_app

    class NoKey(TestConfig):
        STRIPE_SECRET_KEY = None

    with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
        create_app(NoKey)


# --- Real stripe-python objects (guards against dict-vs-attribute regressions) ---

def _real_session(session_id, payment_status="paid"):
    return stripe.checkout.Session.construct_from(
        {"id": session_id, "object": "checkout.session", "payment_status": payment_status},
        "sk_test_dummy",
    )


def test_success_with_real_stripe_session_object(logged_in, fake_stripe, monkeypatch):
    monkeypatch.setattr(
        stripe.checkout.Session, "retrieve", staticmethod(lambda sid: _real_session(sid))
    )
    _add(logged_in, "deep-thinker-mug", 1)
    logged_in.post("/checkout")

    assert b"Thank you" in logged_in.get("/checkout/success?session_id=cs_test_1").data
    assert db.session.scalar(select(Order)).status == Order.STATUS_PAID


def test_webhook_with_real_stripe_event_object(client, pending_order, monkeypatch):
    event = stripe.Event.construct_from(
        {
            "id": "evt_1",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_1", "object": "checkout.session",
                                "payment_status": "paid"}},
        },
        "sk_test_dummy",
    )
    _fake_event(monkeypatch, event)
    assert _post_webhook(client).status_code == 200
    assert db.session.get(Order, pending_order.id).status == Order.STATUS_PAID


def test_paid_at_is_timezone_aware_after_reload(client, pending_order, monkeypatch):
    from datetime import datetime, timezone

    _fake_event(monkeypatch, _event("checkout.session.completed", "cs_test_1"))
    _post_webhook(client)
    db.session.expire_all()

    order = db.session.get(Order, pending_order.id)
    assert order.paid_at.tzinfo is not None
    assert order.created_at.tzinfo is not None
    assert datetime.now(timezone.utc) - order.paid_at >= datetime.resolution * 0
