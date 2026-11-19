"""Your details: sizes, budget, colours, what the wardrobe is for."""
from __future__ import annotations

from . import capsule, colours, db, programmes
from .sizes import ALPHA

USES = {"everyday": "Everyday", "office": "Office", "both": "Both"}

# The Profile page's tabs, in order: their names in the address (/profile#colours) and on screen. "body" is the
# model's menu, shown where AI pictures are on (and on your own machine).
TABS = {"you": "You", "body": "Body", "sizes": "Sizes", "colours": "Colours", "budget": "Budget", "stores": "Stores"}

# What a new account starts with (onboarding.ensure_setup), shown until he saves his own details on the Profile page.
# Its budget plans his first wardrobe (config/budget.toml: 9 pieces for everyday and the office) until he gives his
# own: a budget he skips in the welcome stays this one, as the figure the plan is made for, and is not "his" budget
# (budget_known). The visitors' example wardrobe has its own budget (guests.example_budget).
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
    "budget": 300,         # EUR, for the whole wardrobe: "Basic" (config/budget.toml, [presets])
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
    mine = [key for key in offered if key not in off]
    # A store with no products yet (shared.stocked) cannot be his only store: his pieces would have nowhere to come
    # from. Should that be all he kept (the stores he ticked lost their products), he gets every store offered.
    return mine if _enough(mine) else offered


def _enough(keys: list[str]) -> bool:
    """Whether these stores can be all of a customer's stores: at least one, and one of them a store Stilsmith has
    products from (shared.stocked; read here, late: shared.py builds on this module). While no store has products
    at all, any store will do."""
    from . import shared
    stocked = shared.stocked()
    return bool(keys) and (not stocked or any(key in stocked for key in keys))


def _stores_from(form, current: dict) -> tuple[list[str], str | None]:
    """The stores he left out, from the Stores tab's ticks, and a note when he unticked them all. A form without the
    Stores tab (`stores_shown`) leaves them as they were. A store that is not offered just now stays left out, should
    it be offered again."""
    kept = list(current.get("stores_off") or [])
    if "stores_shown" not in form:
        return kept, None
    offered = list(programmes.offered())
    ticked = [key for key in form.getlist("stores") if key in offered]
    if not _enough(ticked):
        # None ticked, or only stores with no products yet (paste-a-link stores): his pieces need a store to come from.
        return kept, "At least one store with products must stay ticked, so your stores stay as they were."
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


# What a new customer is asked in the welcome besides his sizes (app.py, welcome). Until he answers one of them, or
# saves the Profile page, the pages do not treat the starting value as his: no budget is "his" budget, and Profile
# says which colours Stilsmith starts with.
QUESTIONS = ("colours", "budget", "use")


def answered(profile: dict | None = None) -> set[str]:
    """Which of QUESTIONS the customer has answered. An account from before the welcome answered them all by
    saving his Profile (then it no longer holds the example's values), or none."""
    said = db.get_setting("answered")
    if isinstance(said, list):
        return set(said) & set(QUESTIONS)
    profile = load() if profile is None else profile
    return set() if profile.get("example") else set(QUESTIONS)


def answer(*questions: str) -> None:
    """Note that he answered these questions."""
    db.set_setting("answered", sorted(answered() | (set(questions) & set(QUESTIONS))))


def unanswer(*questions: str) -> None:
    """Note that these questions are no longer answered (a budget cleared: its field emptied on Profile)."""
    db.set_setting("answered", sorted(answered() - set(questions)))
    if "budget" in questions:
        db.set_setting("budget_as_before", None)    # (nor fitted to the budget his account started with)


def budget_known(profile: dict | None = None) -> bool:
    """Whether the budget is one he gave. Until then the bar shows the total and nothing is "left" or "over"."""
    return "budget" in answered(profile)


NOT_A_BUDGET = "A budget has to be more than 0 €, so what you typed was not saved as your budget."


def budget_sent(form) -> str | None:
    """What a form says the budget is, as the text of an amount: the amount of the budget chosen among the presets
    (`budget_choice`, config/budget.toml), else what was typed in the field `budget`, with "Other amount" chosen or in
    a form without the choices (an older page, the welcome's answers read again, app.as_sent). An empty text: the
    field was emptied, so no budget. None: the form has no budget at all (no choice, no field)."""
    choice = str(form.get("budget_choice") or "")
    amounts = {str(amount) for amount in capsule.presets().values()}
    if choice in amounts:
        return choice       # a preset: whatever the field below it still holds is not what he chose
    typed = form.get("budget")
    return None if typed is None and not choice else str(typed or "")


def given_budget(value) -> int | None:
    """The budget typed into a field, in whole euros, or None when the field holds no budget: nothing, a word, or
    0. (A budget of 0 € cannot be meant: every outfit would be "over" it. An empty field means no budget.)"""
    try:
        budget = int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError, OverflowError):
        return None
    return min(budget, 100000) if budget > 0 else None


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
    budget = budget_sent(form) or ""        # a preset chosen, or the amount typed (with "Other amount" chosen)
    if budget.strip() and given_budget(budget) is None:
        notes.append(NOT_A_BUDGET)      # "0", or not a number: the budget he had stays (below)

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
        "budget": given_budget(budget) or current["budget"],
        "liked": liked,
        "refused": refused,
        "use": form.get("use") if form.get("use") in USES else current["use"],
        "shoes": form.get("shoes") == "on",
        "outerwear": form.get("outerwear") == "on",
        "owned": (form.get("owned") or "").strip(),
        "stores_off": stores_off,
    }
    return profile, notes
