import logging

import click
import stripe
from flask import Flask, Response, current_app, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

from .cart import MAX_QTY_PER_ITEM, get_cart, item_count
from .extensions import csrf, db, limiter, login_manager
from .models import User

log = logging.getLogger(__name__)


def _check_required_settings(app: Flask) -> None:
    missing = [name for name in app.config["REQUIRED_SETTINGS"] if not app.config.get(name)]
    if missing:
        raise RuntimeError(
            "Missing required settings: " + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in."
        )
    if app.config["CURRENCY"] not in CURRENCY_SYMBOLS:
        raise RuntimeError(
            f"Unsupported CURRENCY {app.config['CURRENCY']!r}; choose one of "
            + ", ".join(sorted(CURRENCY_SYMBOLS))
        )
    if not app.config.get("STRIPE_WEBHOOK_SECRET"):
        log.warning("STRIPE_WEBHOOK_SECRET is not set; /webhook will reject all events.")


# Two-decimal currencies only: prices are stored in the minor unit (cents),
# which is what Stripe's unit_amount expects for these currencies.
CURRENCY_SYMBOLS = {
    "usd": "$", "cad": "CA$", "aud": "A$", "nzd": "NZ$",
    "eur": "€", "gbp": "£", "ngn": "₦",
}


def format_money(cents: int, currency: str | None = None) -> str:
    code = (currency or current_app.config["CURRENCY"]).lower()
    return f"{CURRENCY_SYMBOLS.get(code, code.upper() + ' ')}{cents / 100:,.2f}"


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    _check_required_settings(app)

    stripe.api_key = app.config["STRIPE_SECRET_KEY"]

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "info"

    from .auth import bp as auth_bp
    from .checkout import bp as checkout_bp
    from .store import bp as store_bp

    app.register_blueprint(store_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(checkout_bp)

    app.add_template_filter(format_money, "money")

    @app.context_processor
    def inject_cart_count():
        return {"cart_count": item_count(get_cart()), "max_qty_per_item": MAX_QTY_PER_ITEM}

    if app.config["TRUSTED_PROXIES"]:
        hops = app.config["TRUSTED_PROXIES"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    app.after_request(_set_security_headers)
    _register_error_handlers(app)
    _register_cli(app)

    with app.app_context():
        db.create_all()
        if app.config["AUTO_SEED"]:
            from .seed import seed_products

            seed_products()

    return app


# Style attributes need 'unsafe-inline' (product tile colours); scripts are
# not used at all. form-action must allow Stripe because the checkout POST
# redirects there and browsers apply form-action to that redirect.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'none'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "form-action 'self' https://checkout.stripe.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "object-src 'none'",
])

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _set_security_headers(response: Response) -> Response:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if current_app.config["SESSION_COOKIE_SECURE"]:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id)) if user_id.isdigit() else None


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_err):
        return render_template("error.html", code=404, message="We couldn't find that page."), 404

    @app.errorhandler(429)
    def too_many(_err):
        message = "Too many requests. Please wait a moment and try again."
        return render_template("error.html", code=429, message=message), 429

    @app.errorhandler(500)
    def server_error(_err):
        db.session.rollback()
        message = "Something went wrong on our end."
        return render_template("error.html", code=500, message=message), 500


def _register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    def seed_command():
        """Add the demo products to the database."""
        from .seed import seed_products

        click.echo(f"Added {seed_products()} product(s).")
