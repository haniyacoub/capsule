"""What every feed importer shares: reading the files, prices, times, stock and sizes, and building
one row of the `products` table.

Each importer (google.py, awin_csv.py, tradedoubler.py) only says which of its feed's fields means
what. The rules for turning those values into a row are here, once:

    a product needs an id, a name, a price above zero and a buy link, or it is skipped and counted
    prices:  "39,95 EUR", "39.95 EUR", "EUR 39.95", "€39,95", 39.95 or {"value": "39.95", "currency": "EUR"}
    sizes:   only what the feed says. A size the feed does not name stays unknown (an empty list),
             and a size counts as in stock only when the feed says so for that size
"""
from __future__ import annotations

import csv
import gzip
import io
import itertools
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import IO, Any

from .. import colours, composition

DEFAULT_CURRENCY = "EUR"        # the stores sell in Germany first; a price without a currency is taken as euros
csv.field_size_limit(16 * 1024 * 1024)     # long product descriptions must not stop a whole feed


class Skip(Exception):
    """This record cannot become a product. The message is the reason, counted in the import's summary."""


@dataclass
class Result:
    """What an importer read from one file: the products, and how many records it skipped, by reason."""
    rows: list[dict] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)

    def summary(self) -> str:
        """'2 skipped: 1 without a price, 1 without a link', or '' when none were."""
        if not self.skipped:
            return ""
        reasons = ", ".join(f"{n} {why}" for why, n in sorted(self.skipped.items(), key=lambda kv: (-kv[1], kv[0])))
        return f"{sum(self.skipped.values())} skipped: {reasons}"


def collect(records: Iterable[dict | None], make: Callable[[dict], dict]) -> Result:
    """Run an importer's mapping over every record. None stands for a record that could not be read."""
    result = Result()
    seen: set[str] = set()
    for record in records:
        try:
            if record is None:
                raise Skip("unreadable")
            row = make(record)
            if row["product_id"] in seen:
                raise Skip("with an id seen before in the file")
        except Skip as why:
            result.skipped[str(why)] += 1
            continue
        seen.add(row["product_id"])
        result.rows.append(row)
    return result


# ── reading the files ─────────────────────────────────────────────────────────

def open_text(path: Path) -> IO[str]:
    """A feed file as text, unpacked on the way if it is gzipped (Awin and Rakuten offer .gz files)."""
    with path.open("rb") as f:
        packed = f.read(2) == b"\x1f\x8b"
    if packed:
        return io.TextIOWrapper(gzip.open(path), encoding="utf-8-sig", newline="")
    return path.open(encoding="utf-8-sig", newline="")


def starts_with_brace(path: Path) -> bool:
    """True for a JSON file or JSON Lines: its first character that is not a space is '{'."""
    with open_text(path) as f:
        return f.read(4096).lstrip().startswith("{")


def json_lines(path: Path) -> Iterator[dict | None]:
    """One record per line. A line that is not a JSON object comes out as None (counted, not fatal)."""
    with open_text(path) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                yield None
                continue
            yield record if isinstance(record, dict) else None


def delimited(path: Path) -> Iterator[dict]:
    """The rows of a CSV or TSV file under its header line, as {column: value}.
    Whether a tab or a comma separates the columns is read off the header."""
    with open_text(path) as f:
        header = f.readline()
        delimiter = "\t" if header.count("\t") > header.count(",") else ","
        for record in csv.DictReader(itertools.chain([header], f), delimiter=delimiter):
            yield {(name or "").strip(): value.strip() if isinstance(value, str) else value
                   for name, value in record.items()}


# ── reading the values ────────────────────────────────────────────────────────

def text(value: Any) -> str | None:
    """The value as trimmed text, None when it is empty."""
    if value is None or isinstance(value, (dict, list)):
        return None
    out = str(value).strip()
    return out or None


def parse_price(value: Any, currency: str | None = None) -> tuple[float | None, str | None]:
    """(39.95, 'EUR') from '39,95 EUR', '39.95 EUR', 'EUR 39.95', '€39,95', 39.95 or
    {'value': '39.95', 'currency': 'EUR'}. (None, None) when there is no price in it.
    `currency` is used when the value does not name one."""
    if isinstance(value, dict):
        return parse_price(value.get("value", value.get("amount")), text(value.get("currency")) or currency)
    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        return (float(value), currency) if math.isfinite(value) else (None, None)
    words = str(value).strip()
    number = re.search(r"\d[\d.,]*", words)
    if not number:
        return None, None
    code = re.search(rf"(?<![A-Z])({'|'.join(_CURRENCIES)})(?![A-Z])", words.upper())
    sign = next((c for s, c in (("€", "EUR"), ("£", "GBP"), ("$", "USD")) if s in words), None)
    return _number(number.group()), (code.group(1) if code else sign) or currency


_CURRENCIES = ("EUR", "GBP", "USD", "CHF", "SEK", "DKK", "NOK", "PLN", "CZK")


def _number(digits: str) -> float:
    """'1.299,95' and '1,299.95' -> 1299.95, '39,95' -> 39.95. With one kind of separator, three
    digits after it make it a thousands separator ('1.299' -> 1299), anything else a decimal one."""
    digits = digits.rstrip(".,")
    if "," in digits and "." in digits:
        decimal = "," if digits.rfind(",") > digits.rfind(".") else "."
        digits = digits.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in digits or "." in digits:
        separator = "," if "," in digits else "."
        whole, _, tail = digits.rpartition(separator)
        if len(tail) == 3 or digits.count(separator) > 1:
            digits = digits.replace(separator, "")
        else:
            digits = whole.replace(separator, "") + "." + tail
    return float(digits)


def parse_time(value: Any) -> str | None:
    """A feed's time as ISO text with a time zone, from ISO text ('2026-11-12T06:00:00Z',
    '2026-11-12 06:00:00'), an HTTP date (Last-Modified), or seconds or milliseconds since 1970.
    A time without a zone is taken as this computer's. None when it is not a time."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    when: datetime | None = None
    if isinstance(value, (int, float)) or re.fullmatch(r"\s*\d{9,13}(\.\d+)?\s*", str(value)):
        seconds = float(value)
        if seconds > 1e11:                      # milliseconds, as Tradedoubler gives them
            seconds /= 1000
        when = datetime.fromtimestamp(seconds, timezone.utc)
    else:
        words = str(value).strip()
        try:
            when = datetime.fromisoformat(words.replace("Z", "+00:00"))
        except ValueError:
            try:
                when = parsedate_to_datetime(words)
            except (TypeError, ValueError, IndexError):
                return None
    return when.astimezone().isoformat(timespec="seconds")


# Words for "can be bought now" and "cannot". Google's own are in_stock, out_of_stock, preorder and
# backorder; a pre-order or back-order cannot be bought now, so it counts as not available.
_NOT_NOW = ("out of stock", "outofstock", "sold out", "soldout", "unavailable", "not available", "preorder",
            "pre order", "backorder", "back order", "discontinued", "ausverkauft", "nicht ")
_NOW = ("in stock", "instock", "available", "lieferbar", "auf lager", "vorrätig", "verfügbar")
_YES_NO = {"yes": True, "true": True, "y": True, "ja": True, "no": False, "false": False, "n": False, "nein": False}


def in_stock(*values: Any) -> bool | None:
    """Can it be bought now? The first value that says so either way: words such as 'in_stock' or
    'out of stock', yes or no, 1 or 0, or a stock count. None when none of them says."""
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        words = str(value).strip().lower().replace("_", " ").replace("-", " ")
        if re.fullmatch(r"\d+", words):
            return int(words) > 0
        if words in _YES_NO:
            return _YES_NO[words]
        if words.startswith(_NOT_NOW):
            return False
        if words.startswith(_NOW):
            return True
    return None


def split_sizes(value: Any) -> list[str]:
    """['S', 'M', 'L'] from 'S, M, L', 'S|M|L' or a list. A slash stays: '32/34' is one size."""
    parts = value if isinstance(value, list) else re.split(r"[,|;]", text(value) or "")
    out: list[str] = []
    for part in parts:
        label = text(part)
        if label and label not in out:
            out.append(label)
    return out


def size_stock(value: Any) -> dict[str, bool]:
    """{'S': True, 'M': False} from 'S:available|M:out of stock'. Sizes it says nothing clear about are left out."""
    out: dict[str, bool] = {}
    for part in re.split(r"[|,]", text(value) or ""):
        label, _, status = part.partition(":")
        says = in_stock(status)
        if text(label) and says is not None:
            out[label.strip()] = says
    return out


def _link(value: Any) -> str | None:
    """An address as given, if it is a web address at all (never a 'javascript:' or a file)."""
    address = text(value)
    return address if address and re.match(r"https?://", address, re.IGNORECASE) else None


# ── the row ───────────────────────────────────────────────────────────────────

def product(*, product_id: Any, name: Any, price: Any, buy_link: Any, sale_price: Any = None,
            currency: Any = None, group_id: Any = None, brand: Any = None, category: Any = None,
            gender: Any = None, colour: Any = None, material: Any = None, sizes: Any = None,
            size_stock: dict[str, bool] | None = None, available: bool | None = None,
            image_url: Any = None, feed_updated_at: Any = None) -> dict:
    """One row of the `products` table from a feed's values, or Skip with the reason.
    The store and the import time are added when the file is imported (refresh.py)."""
    pid, title = text(product_id), text(name)
    if not pid:
        raise Skip("without an id")
    if not title:
        raise Skip("without a name")
    amount, money = parse_price(price, text(currency))
    if amount is None or amount <= 0:
        raise Skip("without a price")
    link = _link(buy_link)
    if not link:
        raise Skip("without a link")
    reduced, reduced_money = parse_price(sale_price, money)
    labels = split_sizes(sizes)
    if size_stock:                                  # the feed says it per size
        labels = labels or list(size_stock)
        stocked = [label for label in labels if size_stock.get(label)]
    else:                                           # one size and the product is in stock: that size is
        stocked = labels if len(labels) == 1 and available else []
    colour_words, material_words = text(colour), text(material)
    return {
        "product_id": pid,
        "group_id": text(group_id),
        "name": title,
        "brand": text(brand),
        "category": text(category),
        "gender": text(gender),
        "colour": colour_words,
        "colour_key": colours.find(colour_words),
        "material": material_words,
        "composition": [[fibre, share] for fibre, share in composition.parse(material_words)],
        "price": amount,
        "sale_price": reduced if reduced and reduced > 0 else None,
        "currency": money or reduced_money or DEFAULT_CURRENCY,
        "sizes": labels,
        "sizes_in_stock": stocked,
        "available": available,
        "image_url": _link(image_url),
        "buy_link": link,
        "feed_updated_at": parse_time(feed_updated_at),
    }
