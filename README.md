# Tiny Thoughts Co. — a Flask eCommerce store

A small but complete online shop built with Flask:

- **Catalogue** – product grid and product detail pages.
- **Cart** – add, change quantity, remove; stored in the signed session cookie
  (only ids + quantities; prices always come from the database).
- **Accounts** – registration, login ("keep me signed in"), logout, order history.
  Passwords are hashed with Werkzeug (scrypt).
- **Checkout** – [Stripe Checkout](https://stripe.com/docs/payments/checkout):
  a pending order is created, the customer pays on Stripe's hosted page, and the
  order is marked paid by the success page *and* a signed webhook (idempotent).
- **Security** – CSRF on every form, rate-limited auth/checkout, open-redirect
  guard, Stripe signature verification, secrets from environment only.

## Project layout

```
config.py            settings (reads .env)
run.py               entry point: flask --app run run
shop/
  __init__.py        app factory, error pages, `flask seed` command
  models.py          User, Product, Order, OrderItem
  cart.py            pure cart helpers (session-backed)
  store.py           shop, product and cart routes
  auth.py            register / login / logout
  checkout.py        Stripe Checkout session, success/cancel, orders, /webhook
  seed.py            demo products
  templates/  static/
tests/               pytest suite (Stripe is mocked, no network)
```

## Run it locally

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Edit `.env`:

| Variable | Where to get it |
|---|---|
| `SECRET_KEY` | any long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `STRIPE_SECRET_KEY` | Stripe Dashboard → Developers → API keys (`sk_test_…`) |
| `STRIPE_WEBHOOK_SECRET` | printed by `stripe listen` (below), or the Dashboard webhook endpoint |

Start the server (tables and demo products are created automatically):

```bash
flask --app run run
```

Open http://localhost:5000, add items, sign up, and check out with Stripe's
test card **4242 4242 4242 4242**, any future expiry, any CVC.

### Webhooks in development

Install the [Stripe CLI](https://stripe.com/docs/stripe-cli) and run:

```bash
stripe listen --forward-to localhost:5000/webhook
```

Copy the `whsec_…` it prints into `STRIPE_WEBHOOK_SECRET` and restart Flask.
The success page also confirms payment directly with Stripe, so orders still
complete locally without the CLI; the webhook covers customers who close the
tab before being redirected back, plus expired sessions.

## Taking real payments

1. Activate your Stripe account (business details + bank account).
2. Deploy behind HTTPS and set `SESSION_COOKIE_SECURE=1`.
3. Swap in your live `sk_live_…` key.
4. In Dashboard → Developers → Webhooks, add `https://your-domain/webhook` with
   events `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, `checkout.session.expired`, and use
   its signing secret as `STRIPE_WEBHOOK_SECRET`.
5. Use a real database (`DATABASE_URL=postgresql://…`) and a production server
   such as `gunicorn "run:app"`. For multiple workers, point Flask-Limiter at
   Redis instead of in-memory storage.

## Tests

```bash
pytest -q
```

## Adding products

Edit `shop/seed.py` and run `flask --app run seed` (it only inserts new slugs),
or insert rows into the `product` table. Prices are stored in cents.
