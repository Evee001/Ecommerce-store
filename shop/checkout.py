"""Stripe Checkout integration.

Flow:
1. POST /checkout builds a pending Order from the cart (prices from the DB),
   creates a Stripe Checkout Session and redirects the customer to Stripe.
2. Stripe redirects back to /checkout/success; we re-fetch the session from
   Stripe (never trusting the query string) and mark the order paid.
3. The /webhook endpoint receives the same events server-to-server, so the
   order is fulfilled even if the customer closes the tab before redirecting.
"""

import logging
from datetime import datetime, timezone

import stripe
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select

from .cart import build_lines, clear_cart, get_cart, total_cents
from .extensions import csrf, db, limiter
from .models import Order, OrderItem

bp = Blueprint("checkout", __name__)
log = logging.getLogger(__name__)

FULFIL_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
CANCEL_EVENTS = {"checkout.session.expired", "checkout.session.async_payment_failed"}
SHIPPING_COUNTRIES = ["US", "CA", "GB", "AU", "NZ", "IE", "DE", "FR", "NL", "NG"]


def _order_from_lines(lines, currency: str) -> Order:
    return Order(
        user_id=current_user.id,
        currency=currency,
        total_cents=total_cents(lines),
        items=[
            OrderItem(
                product_id=line.product.id,
                name=line.product.name,
                unit_price_cents=line.product.price_cents,
                quantity=line.quantity,
            )
            for line in lines
        ],
    )


def _stripe_line_items(order: Order) -> list[dict]:
    return [
        {
            "price_data": {
                "currency": order.currency,
                "unit_amount": item.unit_price_cents,
                "product_data": {"name": item.name},
            },
            "quantity": item.quantity,
        }
        for item in order.items
    ]


def fulfil_order(order: Order) -> bool:
    """Mark an order paid. Idempotent: returns False if it was already paid."""
    if order.status == Order.STATUS_PAID:
        return False
    order.status = Order.STATUS_PAID
    order.paid_at = datetime.now(timezone.utc)
    db.session.commit()
    log.info("Order %s paid (session %s)", order.id, order.stripe_session_id)
    return True


def _cancel_order(order: Order) -> None:
    if order.status == Order.STATUS_PENDING:
        order.status = Order.STATUS_CANCELLED
        db.session.commit()


@bp.route("/checkout", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def create_checkout_session():
    lines = build_lines(get_cart())
    if not lines:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("store.cart"))

    order = _order_from_lines(lines, current_app.config["CURRENCY"])
    db.session.add(order)
    db.session.flush()  # assigns order.id for client_reference_id

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=_stripe_line_items(order),
            customer_email=current_user.email,
            client_reference_id=str(order.id),
            shipping_address_collection={"allowed_countries": SHIPPING_COUNTRIES},
            success_url=url_for("checkout.success", _external=True)
            + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("checkout.cancel", _external=True),
        )
    except stripe.StripeError:
        db.session.rollback()
        log.exception("Stripe Checkout Session creation failed for user %s", current_user.id)
        flash("We couldn't start checkout right now. Please try again in a moment.", "danger")
        return redirect(url_for("store.cart"))

    order.stripe_session_id = session.id
    db.session.commit()
    return redirect(session.url, code=303)


@bp.route("/checkout/success")
@login_required
def success():
    session_id = request.args.get("session_id", "")
    if not session_id.startswith("cs_"):
        abort(404)

    order = db.session.scalar(
        select(Order).filter_by(stripe_session_id=session_id, user_id=current_user.id)
    )
    if order is None:
        abort(404)

    if order.status != Order.STATUS_PAID:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError:
            log.exception("Could not retrieve Stripe session %s", session_id)
            session = None
        if session is not None and session.payment_status == "paid":
            fulfil_order(order)

    if order.status == Order.STATUS_PAID:
        clear_cart()
    return render_template("checkout/success.html", order=order)


@bp.route("/checkout/cancel")
@login_required
def cancel():
    flash("Checkout cancelled. Your cart is still here whenever you're ready.", "info")
    return redirect(url_for("store.cart"))


@bp.route("/orders")
@login_required
def orders():
    return render_template("checkout/orders.html", orders=current_user.orders)


@bp.route("/webhook", methods=["POST"])
@csrf.exempt
@limiter.exempt
def stripe_webhook():
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        log.error("Webhook received but STRIPE_WEBHOOK_SECRET is not configured")
        return jsonify(error="webhook not configured"), 400

    try:
        event = stripe.Webhook.construct_event(
            request.get_data(), request.headers.get("Stripe-Signature", ""), secret
        )
    except (ValueError, stripe.SignatureVerificationError):
        log.warning("Rejected webhook with invalid payload or signature")
        return jsonify(error="invalid signature"), 400

    if event.type in FULFIL_EVENTS | CANCEL_EVENTS:
        _handle_session_event(event.type, event.data.object)
    return jsonify(received=True), 200


def _handle_session_event(event_type: str, session) -> None:
    order = db.session.scalar(select(Order).filter_by(stripe_session_id=session.id))
    if order is None:
        log.warning("Webhook %s for unknown session %s", event_type, session.id)
        return
    if event_type in FULFIL_EVENTS and session.payment_status == "paid":
        fulfil_order(order)
    elif event_type in CANCEL_EVENTS:
        _cancel_order(order)
