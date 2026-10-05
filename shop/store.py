from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from .cart import (
    build_lines,
    get_cart,
    parse_quantity,
    save_cart,
    total_cents,
    with_added,
    with_quantity,
)
from .extensions import db
from .models import Product

bp = Blueprint("store", __name__)


def _active_product_or_404(product_id: int) -> Product:
    product = db.session.get(Product, product_id)
    if product is None or not product.is_active:
        abort(404)
    return product


@bp.route("/")
def index():
    products = db.session.scalars(
        select(Product).where(Product.is_active.is_(True)).order_by(Product.id)
    ).all()
    return render_template("shop/index.html", products=products)


@bp.route("/product/<slug>")
def product(slug: str):
    item = db.session.scalar(select(Product).filter_by(slug=slug, is_active=True))
    if item is None:
        abort(404)
    return render_template("shop/product.html", product=item)


@bp.route("/cart")
def cart():
    lines = build_lines(get_cart())
    return render_template("shop/cart.html", lines=lines, total=total_cents(lines))


@bp.route("/cart/add/<int:product_id>", methods=["POST"])
def add_to_cart(product_id: int):
    product = _active_product_or_404(product_id)
    qty = parse_quantity(request.form.get("quantity"))
    if not qty:
        flash("Please choose a valid quantity.", "warning")
        return redirect(url_for("store.product", slug=product.slug))

    save_cart(with_added(get_cart(), product.id, qty))
    flash(f"Added {product.name} to your cart.", "success")
    if request.form.get("return_to") == "shop":
        return redirect(url_for("store.index"))
    return redirect(url_for("store.cart"))


@bp.route("/cart/update/<int:product_id>", methods=["POST"])
def update_cart(product_id: int):
    qty = parse_quantity(request.form.get("quantity"))
    if qty is None:
        flash("Please choose a valid quantity.", "warning")
    else:
        save_cart(with_quantity(get_cart(), product_id, qty))
    return redirect(url_for("store.cart"))


@bp.route("/cart/remove/<int:product_id>", methods=["POST"])
def remove_from_cart(product_id: int):
    save_cart(with_quantity(get_cart(), product_id, 0))
    flash("Item removed from your cart.", "info")
    return redirect(url_for("store.cart"))
