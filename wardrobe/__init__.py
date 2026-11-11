"""Capsule — a local wardrobe builder for COS, Weekday and Zara.

Module map (each file does one job):

    garments.py     the garment types the app knows about
    colours.py      colour names (English and the stores' German), swatches, families
    capsule.py      proposes the slot list from your profile
    profile.py      your sizes, budget, colours
    composition.py  parses "80 % Wolle, 20 % Polyamid" into fibres; estimates from a name
    scoring.py      quality score 0-100, driven by config/scoring.toml
    sizes.py        "is this in stock in my size?" per store
    sizecheck.py    notes on cut, between-sizes, length — driven by config/size_charts.toml
    selection.py    the five price levels, the minimum quality, locks, owned, totals
    outfits.py      outfit combinations from the selected pieces
    looks.py        AI pictures of an outfit being worn (config/looks.toml)
    person.py       who the model in those pictures is: a few choices, or your photo
    imagegen.py     talks to the image services (OpenAI, Google) that draw them
    export.py       the shopping list (page, Markdown, CSV), for the wardrobe or one outfit
    catalog.py      reads/writes data/catalog.json (what the stores sell)
    db.py           reads/writes data/wardrobe.db (what you decided)
    collect/        the collector behind `python -m wardrobe refresh`
        browser.py    one visible Chrome window, robots.txt, pauses, stop at a refusal
        cos.py, weekday.py, zara.py   reading each store's pages
        matching.py   which products on a category page fit a slot
        manual.py     importing a pasted product link
    mock.py         invented demo catalogue (before the first refresh)
    tryon.py        extension point for a true virtual try-on of the actual garments (not built)
    app.py          the web pages

Running for customers (see PRODUCTION.md):

    settings.py     local or production, read from environment variables
    auth.py         accounts, log-in, password reset, CSRF, your-data and delete
    onboarding.py   what a new user starts with
    shared.py       the store catalogue all customers share, and `publish`
    mail.py         outgoing email
    wsgi.py         entry point for gunicorn
"""

__version__ = "1.0.0"
