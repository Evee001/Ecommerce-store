from shop.cart import (
    MAX_QTY_PER_ITEM,
    parse_quantity,
    with_added,
    with_quantity,
)
from shop.extensions import db
from shop.models import Product


def _mug():
    return db.session.query(Product).filter_by(slug="deep-thinker-mug").one()


def test_with_added_returns_new_dict_and_sums_quantities():
    cart = {"1": 2}
    result = with_added(cart, 1, 3)
    assert result == {"1": 5}
    assert cart == {"1": 2}


def test_with_quantity_zero_removes_item():
    assert with_quantity({"1": 2, "2": 1}, 1, 0) == {"2": 1}


def test_quantity_is_clamped_to_max():
    assert with_added({}, 7, 99) == {"7": MAX_QTY_PER_ITEM}


def test_parse_quantity_rejects_garbage_and_out_of_range():
    assert parse_quantity("3") == 3
    assert parse_quantity("") == 1
    assert parse_quantity("abc") is None
    assert parse_quantity("-1") is None
    assert parse_quantity(str(MAX_QTY_PER_ITEM + 1)) is None


def test_shop_lists_products(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Deep Thinker Mug" in response.data
    assert b"$18.00" in response.data


def test_product_page_and_404(client):
    assert client.get("/product/deep-thinker-mug").status_code == 200
    assert client.get("/product/does-not-exist").status_code == 404


def test_add_update_remove_flow(client):
    mug = _mug()

    client.post(f"/cart/add/{mug.id}", data={"quantity": "2"})
    page = client.get("/cart")
    assert b"Deep Thinker Mug" in page.data
    assert b"$36.00" in page.data

    client.post(f"/cart/update/{mug.id}", data={"quantity": "3"})
    assert b"$54.00" in client.get("/cart").data

    client.post(f"/cart/remove/{mug.id}")
    assert b"Your cart is empty" in client.get("/cart").data


def test_add_unknown_product_404(client):
    assert client.post("/cart/add/9999", data={"quantity": "1"}).status_code == 404


def test_add_invalid_quantity_is_rejected(client):
    client.post(f"/cart/add/{_mug().id}", data={"quantity": "500"})
    assert b"Your cart is empty" in client.get("/cart").data


def test_tampered_cart_cookie_is_sanitised(client):
    mug = _mug()
    with client.session_transaction() as sess:
        sess["cart"] = {str(mug.id): 2, "abc": 5, "9999": 1, "1'; DROP": 3}
    page = client.get("/cart")
    assert page.status_code == 200
    assert b"$36.00" in page.data


def test_inactive_product_is_hidden(client):
    mug = _mug()
    mug.is_active = False
    db.session.commit()
    assert b"Deep Thinker Mug" not in client.get("/").data
    assert client.post(f"/cart/add/{mug.id}").status_code == 404
