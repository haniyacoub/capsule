"""'Is this in stock in my size?' — translating each store's size labels.

Stores label the same body differently: a W32 waist is "32/32" on Weekday
jeans, "48" on COS trousers and "42" at Zara. config/size_charts.toml holds
the translation tables; this file applies them.

Phase 3 builds the size check (between sizes, oversized/slim cuts) on top.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .garments import GARMENTS

ALPHA = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]


def load_charts() -> dict:
    return config.load("size_charts.toml")


def norm(label: str) -> str:
    """'EU 42 (US 32)' -> '42',  'w32 l34' -> '32/34',  ' m ' -> 'M'."""
    s = re.sub(r"\(.*?\)", "", str(label)).upper()
    s = re.sub(r"\b(EU|EUR|DE)\b", "", s).strip()
    m = re.fullmatch(r"W?\s*(\d{2})\s*(?:[/X×]|\s)\s*L?\s*(\d{2})", s)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(r"W\s*(\d{2})", s)
    if m:
        return m.group(1)
    return re.sub(r"\s+", " ", s)


def _to_float(value) -> float | None:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def label_fits(label: str, profile: dict, store: str, category: str, charts: dict) -> bool:
    """Does this store label correspond to the size in the profile?"""
    group = GARMENTS[category].size_group
    lab = norm(label)
    chart = charts.get(store, {}).get(group, {})

    if group == "tops":
        want = str(profile.get("top_size") or "").upper()
        if not want:
            return False
        return lab == want or want in [str(x).upper() for x in chart.get(lab, [])]

    if group == "bottoms":
        waist, length = _to_int(profile.get("waist")), _to_int(profile.get("length"))
        if waist is None:
            return False
        m = re.fullmatch(r"(\d{2})/(\d{2})", lab)
        if m:  # waist/length label: waist exact; length within an inch (L33 fits 32 or 34)
            return int(m.group(1)) == waist and (length is None or abs(int(m.group(2)) - length) <= 1)
        if lab in chart:
            return waist in chart[lab]
        if lab.isdigit() and 26 <= int(lab) <= 42:  # a bare waist in inches
            return int(lab) == waist
        return False

    # shoes: exact, or for a half size (42.5) the whole size either side
    want_f, have_f = _to_float(profile.get("shoe")), _to_float(lab)
    if want_f is None or have_f is None:
        return False
    return abs(want_f - have_f) < 0.01 or (want_f % 1 != 0 and abs(want_f - have_f) <= 0.5)


def expected_labels(profile: dict, store: str, category: str, charts: dict) -> list[str]:
    """The label(s) this store most likely prints for your size — used when a
    store page gave no size list, so the shopping list can still say what to look for."""
    group = GARMENTS[category].size_group
    if group == "shoes":
        return [str(profile.get("shoe") or "")]
    chart = charts.get(store, {}).get(group, {})
    if group == "tops":
        mine = str(profile.get("top_size") or "").upper()
        numbered = [label for label, fits in chart.items() if label.isdigit() and mine in [str(x).upper() for x in fits]]
        return [mine] + (numbered[:1] if category in ("coat", "blazer") else [])
    waist, length = _to_int(profile.get("waist")), _to_int(profile.get("length"))
    if category == "jeans":
        return [f"{waist}/{length}"]
    numbered = [label for label, fits in chart.items() if label.isdigit() and waist in fits]
    return numbered[:1] or [f"{waist}/{length}"]


@dataclass
class SizeStatus:
    available: bool        # can be bought in your size right now
    label: str | None      # the store's label for your size, if it makes one
    text: str              # one-line explanation for the UI
    known: bool = True     # False when the store gave no size information


def my_size(candidate: dict, profile: dict, category: str, charts: dict | None = None) -> SizeStatus:
    charts = charts if charts is not None else load_charts()
    store = candidate.get("store", "")
    in_stock = candidate.get("sizes_in_stock") or []
    all_sizes = candidate.get("sizes_all") or in_stock

    if not all_sizes:
        return SizeStatus(True, None, "Size availability unknown — check the product page", known=False)

    for label in in_stock:
        if label_fits(label, profile, store, category, charts):
            return SizeStatus(True, label, f"{label} in stock")
    for label in all_sizes:
        if label_fits(label, profile, store, category, charts):
            return SizeStatus(False, label, f"{label} sold out")
    return SizeStatus(False, None, "Not made in your size")
