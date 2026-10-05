from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .cart import clear_cart
from .extensions import db, limiter
from .forms import LoginForm, RegisterForm
from .models import User

bp = Blueprint("auth", __name__)

AUTH_RATE_LIMIT = "10 per minute"


def _safe_next(target: str | None) -> str:
    """Only allow same-site relative redirects to prevent open redirects."""
    if target:
        parsed = urlparse(target)
        is_relative = not parsed.scheme and not parsed.netloc
        if is_relative and target.startswith("/") and not target.startswith("//") \
                and "\\" not in target:
            return target
    return url_for("store.index")


def _normalise_email(value: str) -> str:
    return value.strip().lower()


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit(AUTH_RATE_LIMIT, methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("store.index"))

    form = RegisterForm()
    if form.validate_on_submit():
        email = _normalise_email(form.email.data)
        if db.session.scalar(select(User).filter_by(email=email)):
            flash("An account with that email already exists. Please log in.", "warning")
            return redirect(url_for("auth.login"))

        user = User(
            email=email,
            name=form.name.data.strip(),
            password_hash=generate_password_hash(form.password.data),
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            # Another request registered the same email between check and insert.
            db.session.rollback()
            flash("An account with that email already exists. Please log in.", "warning")
            return redirect(url_for("auth.login"))
        login_user(user)
        flash(f"Welcome, {user.name}! Your account is ready.", "success")
        return redirect(_safe_next(request.args.get("next")))

    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(AUTH_RATE_LIMIT, methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("store.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(select(User).filter_by(email=_normalise_email(form.email.data)))
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember.data)
            flash(f"Welcome back, {user.name}.", "success")
            return redirect(_safe_next(request.args.get("next")))
        flash("Incorrect email or password.", "danger")

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    clear_cart()
    flash("You have been logged out.", "info")
    return redirect(url_for("store.index"))
