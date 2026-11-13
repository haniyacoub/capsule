"""The owner's pages: what only the people who run Capsule see.

    /stores      every listed store and its current catalogue, from the stores' own feeds (feeds/)

Who is an owner. On your own machine (CAPSULE_ENV=local) you are: one person, no login. In
production, an account marked in the database, with no setting to change and no restart:

    python -m wardrobe owner add EMAIL       the account must exist: sign up on the site first
    python -m wardrobe owner remove EMAIL
    python -m wardrobe owner list

Anyone else who asks for an owner's page, signed in or not, gets exactly what an address that does
not exist gets: Capsule's "We can't find that page". Nothing says the page is there, and only an
owner's Account page links to it.

The catalogue shows only rows of the `products` table: products from the feeds the stores'
affiliate programmes license, never the collector's snapshot. It is for running Capsule, so there is
no export and no download (Awin, for one, limits the data to the purpose of its agreement).
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from datetime import datetime

from flask import Blueprint, abort, current_app, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from . import auth, colours, db, settings
from .feeds import registry
from .sizes import ALPHA

bp = Blueprint("owner", __name__)

PER_PAGE = 100
FILTERS = ("store", "category", "colour", "size", "q")      # what the page's address may carry, besides the page
NETWORKS = {"awin": "Awin", "tradedoubler": "Tradedoubler", "rakuten": "Rakuten", "webgains": "Webgains",
            "impact": "impact.com"}


@bp.before_request
def owners_only() -> None:
    """Also checked before the login is (app.py, accounts_and_csrf): here it holds on your own machine too."""
    if not auth.is_owner():
        abort(404)


def hidden_here() -> bool:
    """For an error page: whether the address asked for is an owner's page and the person asking is not an
    owner. Asked with a method the page does not take (a form sent to it), the address is refused before any
    check runs, and "not allowed" would say that the page exists: such a person gets "not found" instead."""
    try:
        endpoint, _ = current_app.url_map.bind_to_environ(request.environ).match(method="GET")
    except HTTPException:
        return False
    return str(endpoint).startswith(bp.name + ".") and not auth.is_owner()


# ── /stores ───────────────────────────────────────────────────────────────────

@bp.get("/stores")
def stores():
    asked = {name: " ".join(request.args.get(name, "").split())[:100] for name in FILTERS}
    try:
        page = min(max(1, int(request.args.get("page", "1"))), 1_000_000)
    except ValueError:
        page = 1
    search = {"store": asked["store"] or None, "category": asked["category"] or None,
              "colour": asked["colour"] or None, "size": asked["size"] or None, "words": asked["q"] or None}
    total, products = db.find_products(**search, limit=PER_PAGE, offset=(page - 1) * PER_PAGE)
    pages = max(1, math.ceil(total / PER_PAGE))
    if page > pages:                        # an old link past the last page: the last page
        page = pages
        total, products = db.find_products(**search, limit=PER_PAGE, offset=(page - 1) * PER_PAGE)

    listed = db.list_stores()
    kept = {name: value for name, value in asked.items() if value}

    def link(**change) -> str:
        """This page's address with the same filters, and `change` on top (page=None drops the page)."""
        values = {**kept, **change}
        return url_for("owner.stores", **{k: v for k, v in values.items() if v not in (None, "", 1)})

    return render_template(
        "stores.html", tab="account", stores=[{**s, "notes": notes(s)} for s in listed],
        products=products, total=total, every=sum(s["products"] for s in listed), page=page, pages=pages,
        first=(page - 1) * PER_PAGE + 1, asked=asked, filtered=bool(kept), choices=choices(listed, asked), link=link,
        networks=NETWORKS, when=when, money=money, swatch=swatch)


def notes(store: dict) -> list[tuple[str, str]]:
    """What the owner should know about a store's feed, as (kind, words): kind is good, warn or bad."""
    said = []
    if store["last_error"]:
        said.append(("bad", f"The last refresh failed: {store['last_error']}"))
    if registry.stale(store):
        said.append(("warn", "Stale: no feed imported yet" if not (store["last_feed_update"] or store["last_import_at"])
                     else "Stale: the feed is older than its refresh hours plus a day"))
    if store["products"] and store["status"] == "ended":
        said.append(("bad", f"Ended, yet its products are still here. Delete them: python -m wardrobe stores end {store['key']}"))
    elif store["products"] and store["status"] != "approved" and not store["rules"].get("sample"):
        said.append(("bad", "No longer approved, yet its products are still here. "
                            f"Delete them: python -m wardrobe stores end {store['key']}"))
    if not said and store["status"] == "approved":
        said.append(("good", "Up to date"))
    return said


def choices(listed: list[dict], asked: dict[str, str]) -> dict[str, list[tuple[str, str, int]]]:
    """What each filter offers, as (value, words, how many products): the stores with products, the feeds' own
    categories, Capsule's colours (and 'not recognised') and the sizes the feeds say are in stock. A value asked
    for that no product has (any more) is offered too, with 0, so that the filter shows what the list is."""
    found = db.product_choices()
    named = {key: n for key, n in found["colours"]}
    colour_list = [(key, c.label, named[key]) for key, c in colours.COLOURS.items() if key in named]
    if None in named:
        colour_list.append(("unknown", "Not recognised", named[None]))
    offered = {
        "store": [(s["key"], s["label"], s["products"]) for s in listed if s["products"]],
        "category": [(str(name), str(name), n) for name, n in found["categories"]],
        "colour": colour_list,
        "size": [(str(size), str(size), n) for size, n in sorted(found["sizes"], key=lambda item: size_order(str(item[0])))],
    }
    for name, values in offered.items():
        if asked[name] and asked[name] not in {value for value, _, _ in values}:
            values.append((asked[name], asked[name], 0))
    return offered


def size_order(label: str) -> tuple:
    """XS, S, M, L, XL first, then numbers (44, 46, 32/32), then any other label."""
    if label.upper() in ALPHA:
        return (0, ALPHA.index(label.upper()), label)
    number = re.match(r"\d+(?:[.,]\d+)?", label)
    if number:
        return (1, float(number.group().replace(",", ".")), label)
    return (2, 0.0, label)


def when(stamp: str | None) -> str:
    """'12 Nov 2026, 06:30' in this computer's time, or 'never'."""
    if not stamp:
        return "never"
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%-d %b %Y, %H:%M")
    except ValueError:
        return stamp


def money(amount: float | None, currency: str | None) -> str:
    """'39.95 €', or '39.95 GBP' in another currency."""
    if amount is None:
        return ""
    text = f"{amount:,.2f}"
    return f"{text} €" if (currency or "EUR") == "EUR" else f"{text} {currency}"


def swatch(colour_key: str | None) -> str:
    """The colour shown where a product has no photo, or its photo does not load."""
    return colours.get(colour_key).hex


# ── the command line: python -m wardrobe owner ... (added in __main__.py) ────

def add_commands(sub) -> None:
    p_owner = sub.add_parser("owner", help="the accounts that run Capsule and see the owner's pages (/stores)")
    p_owner.set_defaults(func=list_owners)
    what = p_owner.add_subparsers(title="what to do (without one: list them)")
    p_add = what.add_parser("add", help="mark an account as an owner (sign up on the site first)")
    p_add.add_argument("email")
    p_add.set_defaults(func=add_owner)
    p_remove = what.add_parser("remove", help="the account is no longer an owner")
    p_remove.add_argument("email")
    p_remove.set_defaults(func=remove_owner)
    what.add_parser("list", help="the owners").set_defaults(func=list_owners)


LOCAL_NOTE = ("On your own machine (CAPSULE_ENV=local) you are the owner anyway, with no login. "
              "Marks made here count where this database runs in production.")


def add_owner(args: argparse.Namespace) -> None:
    db.init()
    email = args.email.strip().lower()
    result = db.add_owner(email)
    if result == "no account":
        sys.exit(f"There is no account with the address {email}. Sign up on the site with it first, then run this again.")
    print(f"{email} is an owner already." if result == "already" else
          f"{email} is now an owner: its Account page links to the store catalogues (/stores), from its next page.")
    if not settings.PRODUCTION:
        print(LOCAL_NOTE)


def remove_owner(args: argparse.Namespace) -> None:
    db.init()
    email = args.email.strip().lower()
    if not db.remove_owner(email):
        sys.exit(f"{email} is not an owner. The owners: python -m wardrobe owner list")
    print(f"{email} is no longer an owner, from its next page.")


def list_owners(args: argparse.Namespace) -> None:
    db.init()
    owners = db.list_owners()
    if not owners:
        print("No owners yet. Mark your own account (sign up on the site first): python -m wardrobe owner add EMAIL")
    for row in owners:
        print(f"{row['email']:<40} owner since {when(row['added_at'])}")
    if not settings.PRODUCTION:
        print(LOCAL_NOTE)
