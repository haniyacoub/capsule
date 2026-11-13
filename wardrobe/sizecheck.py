"""Size check: what to look at before ordering this item in your size.

It never blocks anything. It adds short notes to an item:

  * the cut is described as oversized or slim;
  * you are between two sizes — by the store's chart (if you entered your
    chest or waist on the Profile page), with a half shoe size, or with a
    trouser length the item doesn't come in;
  * the store's chart puts you in a different size from the one you entered;
  * the garment comes in one length and you are notably tall or short;
  * the store gave no size information at all.

The charts and thresholds are in config/size_charts.toml.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .garments import GARMENTS
from . import programmes, sizes
from .sizes import SizeStatus

ONE_LENGTH = {"coat", "blazer", "trousers", "chinos", "shirt", "overshirt"}   # no length to choose


@dataclass
class Check:
    usual: str                                   # your size in your own terms: "M", "32/32", "43"
    notes: list[str] = field(default_factory=list)


def _number(value) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def usual_size(profile: dict, category: str, store: str = "", charts: dict | None = None) -> str:
    """Your size as this store would most likely label it: "M", "48", "M / 48", "32/32", "43"."""
    return " / ".join(x for x in sizes.expected_labels(profile, store, category, charts or {}) if x)


def by_chart(table: dict, value: float, near: float) -> tuple[str | None, str | None]:
    """(the size whose range holds `value`, the neighbouring size if `value` is on the border)."""
    rows = sorted(((label, float(lo), float(hi)) for label, (lo, hi) in table.items()), key=lambda r: r[1])
    for i, (label, lo, hi) in enumerate(rows):
        last = i == len(rows) - 1
        if lo <= value < hi or (last and value == hi):
            if value - lo < near and i > 0:
                return label, rows[i - 1][0]
            if hi - value <= near and not last:
                return label, rows[i + 1][0]
            return label, None
    return None, None


def check(data: dict, size: SizeStatus, profile: dict, category: str, charts: dict) -> Check:
    group = GARMENTS[category].size_group
    store = data.get("store", "")
    name = programmes.label(store)
    limits = charts.get("check", {})
    body = charts.get(store, {}).get("body", {})
    near = float(limits.get("near_edge_cm", 1.5))
    result = Check(usual=usual_size(profile, category, store, charts))
    notes = result.notes

    # 1. The cut
    height, weight = _number(profile.get("height_cm")), _number(profile.get("weight_kg"))
    bmi = weight / (height / 100) ** 2 if height and weight else None
    fit = data.get("fit")
    if fit == "oversized":
        extra = " On a slim build it will look bigger still: consider one size down." \
            if bmi and bmi <= float(limits.get("slim_build_bmi", 21.5)) else " Size down if you want a regular fit."
        notes.append("Oversized cut — it runs large on purpose." + extra)
    elif fit == "slim":
        extra = " Consider one size up." if bmi and bmi >= float(limits.get("broad_build_bmi", 26)) else ""
        notes.append("Slim cut — it sits close to the body." + extra)

    # 2. The store's chart against your measurements
    if group == "tops" and (chest := _number(profile.get("chest_cm"))) and body.get("tops"):
        fitted, neighbour = by_chart(body["tops"], chest, near)
        mine = str(profile.get("top_size") or "").upper()
        if fitted and neighbour:
            notes.append(f"Between sizes at {name}: a {chest:g} cm chest is on the border of {fitted} and {neighbour}.")
        elif fitted and mine and fitted.upper() != mine:
            notes.append(f"{name}'s chart puts a {chest:g} cm chest in {fitted}; you entered {mine}.")
        elif fitted is None:
            notes.append(f"A {chest:g} cm chest is outside {name}'s size chart.")
    if group == "bottoms" and (waist := _number(profile.get("waist_cm"))) and body.get("bottoms"):
        fitted, neighbour = by_chart(body["bottoms"], waist, near)
        if fitted and neighbour:
            notes.append(f"Between sizes at {name}: an {waist:g} cm waist is on the border of {fitted} and {neighbour}.")
        elif fitted and size.label and re.fullmatch(r"\d{2}", str(size.label)) and str(size.label) != fitted \
                and str(size.label) in body["bottoms"]:
            notes.append(f"{name}'s chart puts an {waist:g} cm waist in {fitted}; "
                         f"your W{profile.get('waist')} maps to {size.label}.")

    # 3. In-between sizes the label itself shows
    if group == "shoes" and (shoe := _number(profile.get("shoe"))) and shoe % 1:
        notes.append(f"You take {shoe:g}; these come in whole sizes, so you are between "
                     f"{int(shoe)} and {int(shoe) + 1}.")
    waist_length = re.fullmatch(r"(\d{2})/(\d{2})", str(size.label or ""))
    length = _number(profile.get("length"))
    if group == "bottoms" and waist_length and length and int(waist_length.group(2)) != int(length):
        notes.append(f"You take length {length:g}; the nearest this comes in is {waist_length.group(2)}.")

    # 4. One length only, and you are tall or short
    if height and category in ONE_LENGTH and not waist_length:
        if height >= float(limits.get("tall_from_cm", 190)):
            notes.append(f"Comes in one length and you are {height:g} cm: check sleeve and leg length.")
        elif height <= float(limits.get("short_up_to_cm", 170)):
            notes.append(f"Comes in one length and you are {height:g} cm: it may run long.")

    # 5. No size information at all
    if not size.known:
        notes.append("The store page gave no sizes: check that yours is in stock.")
    return result
