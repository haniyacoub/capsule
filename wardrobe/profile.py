"""Your details: sizes, budget, colours, what the wardrobe is for."""
from __future__ import annotations

from . import colours, db
from .sizes import ALPHA

USES = {"everyday": "Everyday", "office": "Office", "both": "Both"}

# Shown until you save your own details on the Profile page.
EXAMPLE = {
    "example": True,
    "top_size": "M",
    "waist": 32,           # trousers, inches
    "length": 32,          # trousers, inches
    "shoe": "43",          # EU
    "height_cm": 180,
    "weight_kg": 78,
    "chest_cm": None,      # optional: lets the size check use each store's chart
    "waist_cm": None,      # optional: your body waist, not your jeans size
    "budget": 1500,        # EUR, for the whole wardrobe
    "liked": ["navy", "grey", "white", "olive"],
    "refused": [],
    "use": "both",         # everyday | office | both
    "shoes": True,
    "outerwear": True,
    "owned": "",           # things you already own, one per line
}


def load() -> dict:
    stored = db.get_setting("profile") or {}
    return {**EXAMPLE, **stored}


def save(profile: dict) -> None:
    db.set_setting("profile", profile)


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(str(value).replace(",", ".")))))
    except (TypeError, ValueError):
        return default


def _optional_cm(value, lo: int, hi: int) -> float | None:
    """A measurement in cm, or None when the field was left empty or makes no sense."""
    try:
        number = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    return round(number, 1) if lo <= number <= hi else None


def from_form(form, current: dict) -> tuple[dict, list[str]]:
    """Read the Profile form. Returns the new profile and any notes for the user."""
    notes: list[str] = []
    liked, unknown_liked = colours.parse_list(form.get("liked", ""))
    refused, unknown_refused = colours.parse_list(form.get("refused", ""))
    for word in unknown_liked + unknown_refused:
        notes.append(f"Didn't recognise the colour “{word}” — it was left out.")
    clash = [k for k in liked if k in refused]
    if clash:
        names = ", ".join(colours.get(k).label.lower() for k in clash)
        notes.append(f"You both like and refuse {names} — treated as refused.")
        liked = [k for k in liked if k not in refused]

    top = str(form.get("top_size", "")).upper()
    shoe = str(form.get("shoe", "")).replace(",", ".").strip()
    try:
        shoe_ok = 35 <= float(shoe) <= 50
    except ValueError:
        shoe_ok = False

    profile = {
        "example": False,
        "top_size": top if top in ALPHA else current["top_size"],
        "waist": _int(form.get("waist"), current["waist"], 26, 46),
        "length": _int(form.get("length"), current["length"], 28, 38),
        "shoe": shoe if shoe_ok else current["shoe"],
        "height_cm": _int(form.get("height_cm"), current["height_cm"], 140, 220),
        "weight_kg": _int(form.get("weight_kg"), current["weight_kg"], 40, 200),
        "chest_cm": _optional_cm(form.get("chest_cm"), 70, 150),
        "waist_cm": _optional_cm(form.get("waist_cm"), 55, 150),
        "budget": _int(form.get("budget"), current["budget"], 0, 100000),
        "liked": liked,
        "refused": refused,
        "use": form.get("use") if form.get("use") in USES else current["use"],
        "shoes": form.get("shoes") == "on",
        "outerwear": form.get("outerwear") == "on",
        "owned": (form.get("owned") or "").strip(),
    }
    return profile, notes
