"""Your details: sizes, budget, colours, what the wardrobe is for."""
from __future__ import annotations

from . import colours, db, programmes
from .sizes import ALPHA

USES = {"everyday": "Everyday", "office": "Office", "both": "Both"}

# The Profile page's tabs, in order: their names in the address (/profile#colours) and on screen. "body" is the
# model's menu, shown where AI pictures are on (and on your own machine).
TABS = {"you": "You", "body": "Body", "sizes": "Sizes", "colours": "Colours", "budget": "Budget", "stores": "Stores"}

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
    "stores_off": [],      # the stores he unticked on the Stores tab; none = every store offered (see stores)
}


# The four sizes a customer orders in. Until he says they are his, they may still be the example's.
SIZES = ("top_size", "waist", "length", "shoe")


def load() -> dict:
    stored = db.get_setting("profile") or {}
    return {**EXAMPLE, **stored}


def save(profile: dict) -> None:
    """Store the profile. Sizes changed on the Profile page were typed in by the customer, so they are
    his own: the warning about the example sizes stays away, even if he later types in the example's."""
    if not same_sizes(load(), profile):
        confirm_sizes()
    db.set_setting("profile", profile)


def stores(profile: dict | None = None) -> list[str]:
    """The stores a customer's pieces are picked from: every store customers are offered (programmes.offered), in
    config/stores.toml's order, but for those he unticked on Profile's Stores tab. What is saved is what he left out,
    so a store that is offered later (its programme approved) is among his stores until he unticks it. Never none:
    should every store he kept stop being offered, he gets all those that are."""
    off = (load() if profile is None else profile).get("stores_off") or []
    offered = list(programmes.offered())
    return [key for key in offered if key not in off] or offered


def _stores_from(form, current: dict) -> tuple[list[str], str | None]:
    """The stores he left out, from the Stores tab's ticks, and a note when he unticked them all. A form without the
    Stores tab (`stores_shown`) leaves them as they were. A store that is not offered just now stays left out, should
    it be offered again."""
    kept = list(current.get("stores_off") or [])
    if "stores_shown" not in form:
        return kept, None
    offered = list(programmes.offered())
    ticked = [key for key in form.getlist("stores") if key in offered]
    if not ticked:
        return kept, "At least one store must stay ticked, so your stores stay as they were."
    return [key for key in offered if key not in ticked] + [key for key in kept if key not in offered], None


def same_answers(a: dict, b: dict) -> bool:
    """Whether two profiles hold the same answers (whether they are still the example's aside)."""
    return {k: v for k, v in a.items() if k != "example"} == {k: v for k, v in b.items() if k != "example"}


def same_sizes(a: dict, b: dict) -> bool:
    """Whether two profiles order in the same sizes. 'm' and 'M', 32 and '32', '43' and '43.0' are the same."""
    def size(value) -> str:
        text = str(value).strip().replace(",", ".").upper()
        try:
            return f"{float(text):g}"
        except ValueError:
            return text
    return all(size(a.get(key)) == size(b.get(key)) for key in SIZES)


def confirm_sizes() -> None:
    """'These are my sizes': the customer says his sizes are his own, also where they are the example's."""
    db.set_setting("sizes_confirmed", True)


def sizes_unconfirmed(profile: dict) -> bool:
    """Whether the sizes are still the example's (Tops M, Trousers W32 L32, Shoes 43) and the customer
    hasn't said they are his. Then a page that says which size to order says that first: Buy this outfit,
    the shopping list, the piece pop-up.

    Not profile["example"]: any Profile save clears that, also one that changed only the colours and left
    the example's sizes as they were."""
    return same_sizes(profile, EXAMPLE) and not db.get_setting("sizes_confirmed")


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

    stores_off, stores_note = _stores_from(form, current)
    if stores_note:
        notes.append(stores_note)

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
        "stores_off": stores_off,
    }
    return profile, notes
