from sqlalchemy import select

from .extensions import db
from .models import Product

PRODUCTS = [
    {
        "slug": "deep-thinker-mug",
        "name": "Deep Thinker Mug",
        "tagline": "For coffee and overthinking in equal measure.",
        "description": "A 12oz stoneware mug that holds enough coffee to get you "
        "through one medium-sized existential question. Dishwasher safe; thoughts are not.",
        "price_cents": 1800,
        "glyph": "☕",
        "color": "#f4d35e",
    },
    {
        "slug": "future-self-notebook",
        "name": "Future Self Notebook",
        "tagline": "Write letters to the person who has to deal with it.",
        "description": "120 dotted pages, lay-flat binding and a ribbon marker. "
        "Your future self will thank you, probably.",
        "price_cents": 1400,
        "glyph": "\U0001F4D3",
        "color": "#9bc1bc",
    },
    {
        "slug": "long-view-poster",
        "name": "The Long View Poster",
        "tagline": "Your whole life, in weeks, on one wall.",
        "description": "An 18x24in print on heavy matte stock with one small box for "
        "every week of a 90-year life. Ships rolled in a tube.",
        "price_cents": 2500,
        "glyph": "\U0001F5D3",
        "color": "#ed6a5a",
    },
    {
        "slug": "cozy-cosmos-hoodie",
        "name": "Cozy Cosmos Hoodie",
        "tagline": "The universe is cold. You don't have to be.",
        "description": "Heavyweight brushed-fleece hoodie with a tiny embroidered galaxy "
        "on the chest. Unisex fit, sizes XS to 3XL.",
        "price_cents": 5200,
        "glyph": "\U0001F30C",
        "color": "#8e86a8",
    },
    {
        "slug": "no-small-talk-cards",
        "name": "No Small Talk Card Deck",
        "tagline": "60 questions that skip straight to the good part.",
        "description": "A deck of conversation starters for dinners, road trips and "
        "awkward first dates. Warning: may cause genuine connection.",
        "price_cents": 2000,
        "glyph": "\U0001F0CF",
        "color": "#e6ebe0",
    },
    {
        "slug": "just-five-minutes-timer",
        "name": "Just-Five-Minutes Timer",
        "tagline": "Start for five. Keep going if you feel like it.",
        "description": "A walnut-and-brass mechanical kitchen timer. Twist, set it down, "
        "and do the thing for five minutes. That's the whole trick.",
        "price_cents": 3400,
        "glyph": "⏳",
        "color": "#c9a66b",
    },
]


def seed_products() -> int:
    """Insert any missing demo products. Returns the number of rows added."""
    existing = set(db.session.scalars(select(Product.slug)).all())
    new = [Product(**p) for p in PRODUCTS if p["slug"] not in existing]
    db.session.add_all(new)
    db.session.commit()
    return len(new)
