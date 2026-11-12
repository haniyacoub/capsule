"""Which candidate fills each slot, and what it all costs.

Rules, in order:
  1. A slot marked "already own" costs nothing and needs no candidate.
  2. A locked slot keeps its candidate, whatever the price level says.
  3. Otherwise two controls decide, among candidates in stock in your size:
       minimum quality   only candidates scoring at least this are considered
                         (if none does: the best-scoring one, with a warning)
       price level       which of those to take, by where its price sits among
                         them: the cheapest, a cheap one, the middle one, an
                         expensive one, or the most expensive
     or, instead of a price level:
       best for budget   the wardrobe as a whole: every slot starts on its
                         cheapest option and the rest of the budget goes to
                         upgrades, best value first (see fit_budget below)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from functools import cached_property

from . import capsule
from . import catalog as catalog_mod
from . import colours, db, scoring, shared, sizecheck, sizes
from . import profile as profile_mod
from .garments import GARMENTS, SECTIONS, Garment

# The price levels, cheapest first. To rename one, change its label here.
# "Top" is the dearest option these stores sell for a slot; none of the three is a luxury brand.
MODES = {"cheapest": "Cheapest", "cheap": "Cheap", "medium": "Medium", "expensive": "Expensive", "top": "Top",
         "budget": "Best for budget"}
# Where each level sits between the cheapest (0) and the most expensive (1) candidate of a slot.
# ("budget" is not a place on that line: it looks at the whole wardrobe.)
POSITION = {"cheapest": 0.0, "cheap": 0.25, "medium": 0.5, "expensive": 0.75, "top": 1.0}
HINTS = {
    "budget": "The most quality your budget buys: every slot starts on its cheapest option, and what is left "
              "pays for upgrades, first where a euro improves most the pieces you would wear most",
    "cheapest": "The lowest-priced option for each slot",
    "cheap": "A low-priced option: about a quarter of the way up each slot's price range",
    "medium": "The middle-priced option for each slot",
    "expensive": "A high-priced option: about three quarters of the way up each slot's price range",
    "top": "The most expensive option these stores sell for each slot",
}
DEFAULT_MODE = "cheapest"
DEFAULT_THRESHOLD = 70


def usable_price(value: object) -> float:
    """A price in euros and whole cents, or 0 when there is none: nothing stored, or something
    stored that is not a price (text, a negative or absurd number) in a file or a feed."""
    try:
        price = float(value or 0)       # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return round(price, 2) if math.isfinite(price) and 0 < price < 1_000_000 else 0.0


@dataclass
class Cand:
    """One candidate, with everything the pages need worked out."""
    data: dict
    score: scoring.Score
    size: sizes.SizeStatus
    fabric: str
    colour_hex: str
    check: sizecheck.Check = field(default_factory=lambda: sizecheck.Check(usual=""))

    @property
    def size_to_order(self) -> str:
        """The store's label for your size, or your usual size with a question mark."""
        if self.size.label:
            return str(self.size.label)
        return f"{self.check.usual} (check)" if self.check.usual else "check"

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def price(self) -> float:
        return usable_price(self.data.get("price"))

    @property
    def available(self) -> bool:
        return self.size.available

    @property
    def manual(self) -> bool:
        """Added by hand (a pasted link) rather than collected."""
        return self.data.get("source") == "manual"

    @property
    def gaps(self) -> list[str]:
        """What is still unknown about this item, in plain words."""
        out = []
        if self.price <= 0:
            out.append("price")
        if self.score.fabric_source != "listed":
            out.append("fabric")
        if not self.size.known:
            out.append("sizes")
        return out


@dataclass
class SlotView:
    slot: dict
    garment: Garment
    colour: colours.Colour
    cands: list[Cand] = field(default_factory=list)
    chosen: Cand | None = None
    state: str = "auto"          # auto | locked | owned
    note: str | None = None
    warn: bool = False
    # A piece Capsule's product list has nothing for: colours it has the garment in, to switch to in one
    # tap (see _offer), or, when there are none, why the piece stays out of the outfits and the total.
    offers: list[colours.Colour] = field(default_factory=list)
    left_out: str | None = None

    @property
    def qty(self) -> int:
        return int(self.slot.get("qty") or 1)

    @property
    def cost(self) -> float:
        if self.state == "owned" or self.chosen is None:
            return 0.0
        return self.chosen.price * self.qty

    @property
    def n_available(self) -> int:
        return sum(1 for c in self.cands if c.available)


@dataclass
class Wardrobe:
    slots: list[SlotView]
    mode: str
    threshold: int
    budget: float
    source: str                  # mock | collected | empty
    collected: str
    stores: dict = field(default_factory=dict)   # per store: how the last refresh went
    note: str = ""               # something to say about the whole wardrobe (the budget cannot be met)

    @cached_property
    def levels(self) -> dict[str, float]:
        """What the whole wardrobe would cost at each price level, and fitted to the budget.
        Only the Wardrobe page shows this, so it is worked out when first asked for."""
        ladder = {}
        for level in POSITION:
            cost = 0.0
            for view in self.slots:
                if view.state == "auto":
                    pick = choose(view.cands, level, self.threshold)[0]
                    cost += pick.price * view.qty if pick else 0.0
                else:
                    cost += view.cost
            ladder[level] = round(cost, 2)
        ladder["budget"] = self.total if self.mode == "budget" else _fit(self)[2]
        return ladder

    @property
    def total(self) -> float:
        return round(sum(s.cost for s in self.slots), 2)

    @property
    def remaining(self) -> float:
        return round(self.budget - self.total, 2)

    @property
    def spent_pct(self) -> float:
        if self.budget <= 0:
            return 100.0 if self.total > 0 else 0.0
        return max(0.0, min(100.0, self.total / self.budget * 100))

    @property
    def n_buy(self) -> int:
        return sum(s.qty for s in self.slots if s.state != "owned" and s.chosen)

    @property
    def n_owned(self) -> int:
        return sum(s.qty for s in self.slots if s.state == "owned")

    @property
    def n_unfilled(self) -> int:
        return sum(1 for s in self.slots if s.state != "owned" and s.chosen is None)

    @property
    def n_missing(self) -> int:
        """Pieces Capsule's product list has nothing for yet. Counted like n_buy: a white tee ×2 is two."""
        return sum(s.qty for s in self.slots if s.state != "owned" and not s.cands)

    @property
    def n_no_size(self) -> int:
        """Pieces with options, none of them in stock in your size, so nothing is picked."""
        return sum(s.qty for s in self.slots if s.state != "owned" and s.cands and s.chosen is None and not s.n_available)

    @property
    def n_nothing_to_buy(self) -> int:
        """Every piece nothing is picked for, whatever the reason: all a phone's budget bar has room to say when
        there is more than one reason."""
        return self.n_missing + self.n_no_size + self.n_no_price

    @property
    def n_no_price(self) -> int:
        """Pieces whose options in your size all lack a price, so nothing is picked: a product added by its
        link has none until you type it in."""
        return sum(s.qty for s in self.slots if s.state != "owned" and s.chosen is None and s.n_available)

    @property
    def unfilled_words(self) -> list[str]:
        """The budget bar's count of pieces nothing is picked for, by why: '6 pieces not in the product list
        yet', '1 piece not in stock in your size', '1 piece with no price yet'. Each count is true on its own."""
        out = []
        for n, why in ((self.n_missing, "not in the product list yet"), (self.n_no_size, "not in stock in your size"),
                       (self.n_no_price, "with no price yet")):
            if n:
                out.append(f"{n} {'piece' if n == 1 else 'pieces'} {why}")
        return out

    @property
    def sections(self) -> list[tuple[str, list[SlotView]]]:
        out = []
        for section in SECTIONS:
            items = [s for s in self.slots if s.garment.section == section]
            if items:
                out.append((section, items))
        return out

    def get(self, slot_id: str) -> SlotView | None:
        return next((s for s in self.slots if s.slot["id"] == slot_id), None)


def _cand(raw: dict, slot: dict, profile: dict, rules: dict, charts: dict) -> Cand:
    data = {**raw, **(raw.get("manual") or {})}     # details you typed in win over collected ones
    data["price"] = usable_price(data.get("price"))
    category = slot["category"]
    raw_hex = data.get("colour_hex")
    if colours.is_hex(raw_hex):
        hex_ = "#" + str(raw_hex).lstrip("#")
    else:  # no usable swatch from the store: fall back to the colour name, then the slot's colour
        hex_ = colours.get(colours.find(data.get("colour")) or slot["colour"]).hex
    score = scoring.score(data, category, rules)
    size = sizes.my_size(data, profile, category, charts)
    return Cand(
        data=data,
        score=score,
        size=size,
        fabric=score.fabric_text,
        colour_hex=hex_,
        check=sizecheck.check(data, size, profile, category, charts),
    )


def at_level(pool: list[Cand], mode: str) -> Cand:
    """The candidate whose price sits at this level among `pool`; at equal prices, the better one."""
    ranked = sorted(pool, key=lambda c: (c.price, -c.score.total))
    spot = math.ceil(POSITION.get(mode, 0.0) * (len(ranked) - 1) - 0.5)   # nearest; halfway goes to the cheaper
    price = ranked[max(0, spot)].price
    return max((c for c in ranked if c.price == price), key=lambda c: c.score.total)


def choose(cands: list[Cand], mode: str, threshold: int, colour: str = "") -> tuple[Cand | None, str | None, bool]:
    """The automatic pick for a slot: (candidate, note, is_warning). `colour` is the piece's colour, in
    words ('black'), for the note on a piece the product list has nothing for."""
    if not cands:
        return None, f"Not in Capsule's product list in {colour} yet" if colour else "Not in Capsule's product list yet", True
    # An item without a price has no place on the price ladder: it is never picked automatically.
    available = [c for c in cands if c.available and c.price > 0]
    if not available:
        if any(c.available for c in cands):     # in your size, but no price: one added by its link has none yet
            return None, "No price yet: add it under “Add details”", True
        return None, "Nothing in stock in your size", True
    good = [c for c in available if c.score.total >= threshold]
    if not good:
        best = max(available, key=lambda c: (c.score.total, -c.price))
        return best, f"Nothing reaches {threshold} — this is the best available", True
    return at_level(good, mode), None, False


# ── best for budget: the wardrobe as a whole ──────────────────────────────────

def _worth_paying_for(pool: list[Cand]) -> list[Cand]:
    """A slot's candidates as a ladder, cheapest first: each rung costs more and scores higher than the last."""
    ladder: list[Cand] = []
    for cand in sorted(pool, key=lambda c: (c.price, -c.score.total)):
        if not ladder or cand.score.total > ladder[-1].score.total:
            ladder.append(cand)
    return ladder


def _big_steps(ladder: list[Cand]) -> list[Cand]:
    """The ladder without rungs that buy little for their price when the next rung buys a lot."""
    kept: list[Cand] = []
    for cand in ladder:
        while len(kept) >= 2:
            a, b = kept[-2], kept[-1]
            if (b.score.total - a.score.total) * (cand.price - b.price) <= (cand.score.total - b.score.total) * (b.price - a.price):
                kept.pop()      # going straight from a to cand is the better deal
            else:
                break
        kept.append(cand)
    return kept


def fit_budget(free: list[tuple[str, int, list[Cand]]], budget: float,
               weight: dict[str, float]) -> tuple[dict[str, Cand], bool]:
    """One candidate for each free slot, for the most quality that `budget` pays for.

    `free` lists the slots to decide as (slot id, quantity, candidates that may be picked);
    `weight` says how much each slot's quality counts (how often it would be worn).
    Returns the picks and whether they fit the budget. They always fit unless even the
    cheapest candidates together cost more, in which case those are returned.

    How: every slot starts on its cheapest candidate. Each possible upgrade has a price
    and a gain (score points, times the slot's weight). Upgrades are taken in order of
    gain per euro, skipping any the remaining money does not cover; whatever is left at
    the end goes to the largest single improvement it still pays for. Simple, repeatable,
    and never over budget; it is not guaranteed to find the single best combination.
    """
    cents = {sid: {c.id: round(c.price * 100) * qty for c in pool} for sid, qty, pool in free}
    ladders = {sid: _worth_paying_for(pool) for sid, qty, pool in free}
    picks = {sid: ladder[0] for sid, ladder in ladders.items()}
    left = round(budget * 100) - sum(cents[sid][cand.id] for sid, cand in picks.items())
    if left < 0:
        return picks, False

    upgrades = []
    for sid, ladder in ladders.items():
        steps = _big_steps(ladder)
        for a, b in zip(steps, steps[1:]):
            price = cents[sid][b.id] - cents[sid][a.id]
            gain = (b.score.total - a.score.total) * weight.get(sid, 1.0)
            if price > 0:                                   # (always, since each rung costs more than the last)
                upgrades.append((-gain / price, price, sid, a.id, b))
    upgrades.sort(key=lambda u: u[:4])                      # most gain per euro first; ties: cheaper, then by name
    for _, price, sid, from_id, to in upgrades:
        if picks[sid].id == from_id and price <= left:      # only from where the slot stands now
            picks[sid], left = to, left - price

    while True:                                             # use up what is left
        best = None
        for sid, ladder in ladders.items():
            for cand in ladder:
                price = cents[sid][cand.id] - cents[sid][picks[sid].id]
                gain = (cand.score.total - picks[sid].score.total) * weight.get(sid, 1.0)
                if gain > 0 and price <= left and (best is None or (gain, -price, sid) > best[:3]):
                    best = (gain, -price, sid, cand)
        if best is None:
            return picks, True
        picks[best[2]], left = best[3], left + best[1]


def _controls() -> tuple[str, int]:
    """The price level and minimum quality in force.

    Before there were price levels the choice was "cheapest" or "cheapest good";
    whoever set one of those is carried over once to the same picks as before.
    """
    mode = db.get_setting("mode")
    threshold = db.get_setting("threshold")
    if mode == "good":                                  # = the cheapest, with a minimum quality
        mode = "cheapest"
        db.set_setting("mode", mode)
        db.set_setting("levels", True)
    elif mode == "cheapest" and not db.get_setting("levels"):   # the old plain "cheapest" had no minimum
        threshold = 0
        db.set_setting("threshold", 0)
        db.set_setting("levels", True)
    if mode not in MODES:
        mode = DEFAULT_MODE
    return mode, int(DEFAULT_THRESHOLD if threshold is None else threshold)


def build(profile: dict | None = None) -> Wardrobe:
    """Everything the pages show, computed fresh from the files on disk."""
    profile = profile or profile_mod.load()
    cat = catalog_mod.load()
    mode, threshold = _controls()
    rules = scoring.load_rules()
    charts = sizes.load_charts()
    grouped = catalog_mod.by_slot(cat)

    views: list[SlotView] = []
    for slot in db.list_slots():
        if slot["category"] not in GARMENTS:
            continue  # a garment type that no longer exists
        cands = [_cand(c, slot, profile, rules, charts) for c in grouped.get(slot["id"], [])]
        cands.sort(key=lambda c: (not c.available, c.price, -c.score.total))
        view = SlotView(slot=slot, garment=GARMENTS[slot["category"]],
                        colour=colours.get(slot["colour"]), cands=cands)

        if slot["owned"]:
            view.state = "owned"
        else:
            picked = None
            if slot["locked"] and slot["pick"]:
                picked = next((c for c in cands if c.id == slot["pick"]), None)
            if picked:
                view.state, view.chosen = "locked", picked
                if not picked.available:
                    view.note, view.warn = "Your locked choice is not in stock in your size", True
            else:
                view.chosen, view.note, view.warn = choose(cands, mode, threshold, view.colour.label.lower())
                if slot["locked"] and slot["pick"] and cands:     # (with nothing on offer, choose said so)
                    view.note = "Your locked choice is no longer in the catalogue — showing the automatic pick"
                    view.warn = True
        views.append(view)
    for view in views:
        if view.state != "owned" and not view.cands:
            _offer(view, views, profile, charts)

    wardrobe = Wardrobe(
        slots=views, mode=mode, threshold=threshold, budget=float(profile.get("budget") or 0),
        source=cat.get("source", "empty"),
        collected=catalog_mod.collected_label(cat),
        stores=cat.get("stores", {}),
    )
    if mode == "budget":
        picks, fits, _ = _fit(wardrobe)
        for view in views:
            if view.slot["id"] in picks:
                view.chosen = picks[view.slot["id"]]
        if not fits:
            wardrobe.note = ("Even the cheapest options that reach your minimum quality come to more than your "
                             "budget, so these are the cheapest. Lower the minimum quality, mark what you own, "
                             "or raise the budget on the Profile page.")
    return wardrobe


def _offer(view: SlotView, views: list[SlotView], profile: dict, charts: dict) -> None:
    """For a piece the product list has nothing for: up to three colours Capsule has its garment in, each
    of which fills it in one tap (app.slot_colour). Liked colours come first and refused ones never. A
    colour whose products another piece of that garment already has is skipped, and so is one that
    reaches the same products as a colour already offered: the piece must not become a copy of another.
    So is a colour with nothing in your size at a price: the tap would leave the piece as empty as before.
    With nothing left to offer, `left_out` says why the piece stays empty, true to why each colour he
    wears was passed over: its products are already another piece's, or not in his size.
    """
    category = view.slot["category"]
    on_offer = shared.colours_on_offer(category)
    refused = capsule.banned(profile.get("refused", []))      # refusing "green" refuses olive too
    taken = {c.id for other in views if other is not view and other.slot["category"] == category
             for c in other.cands}
    liked = [key for key in profile.get("liked", []) if key in on_offer]
    in_your_plan = not_in_your_size = False         # why a colour he wears was passed over
    for key in liked + [key for key in on_offer if key not in liked]:
        ids = {product["id"] for product in on_offer[key]}
        if key in refused or key == view.slot["colour"]:
            continue
        if ids & taken:
            in_your_plan = True
            continue
        if not any(usable_price(product.get("price")) and sizes.my_size(product, profile, category, charts).available
                   for product in on_offer[key]):
            not_in_your_size = True
            continue
        view.offers.append(colours.get(key))
        taken |= ids
        if len(view.offers) == 3:
            break
    if not view.offers:
        kind = view.garment.plural
        verb = "are" if kind.endswith("s") else "is"        # "T-shirts are", "knitwear is"
        if not on_offer:
            why = f"Capsule has no {kind} yet"
        elif in_your_plan:      # say so: "Capsule has none" would be untrue beside the grey jumper that has them
            why = f"Capsule's {kind} in other colours you wear {verb} already in your plan"
            if not_in_your_size:
                why += " or not in your size"
        elif not_in_your_size:
            why = f"Capsule has no {kind} in your size in other colours you wear yet"
        else:                   # it has this garment only in colours he refused
            why = f"Capsule has no {kind} in other colours you wear yet"
        view.left_out = f"{why}, so this piece is left out of your outfits and your total."


def _fit(wardrobe: Wardrobe) -> tuple[dict[str, Cand], bool, float]:
    """Best for budget, for this wardrobe: (the pick per free slot, whether it fits, what it all costs).

    The slots it may move are the automatic ones that have candidates reaching the minimum quality.
    Everything else (owned, locked, a best-available fallback) is money already spent.
    """
    free = [(view, [c for c in view.cands if c.available and c.price > 0 and c.score.total >= wardrobe.threshold])
            for view in wardrobe.slots if view.state == "auto"]
    free = [(view, pool) for view, pool in free if pool]
    moving = {view.slot["id"]: min(pool, key=lambda c: (c.price, -c.score.total)) for view, pool in free}
    spent = sum(view.cost for view in wardrobe.slots if view.slot["id"] not in moving)
    # How much each slot is worn is judged with every free slot on its cheapest candidate, whatever
    # is selected right now: the answer must not depend on the level the page happens to be on.
    basis = replace(wardrobe, slots=[replace(view, chosen=moving[view.slot["id"]]) if view.slot["id"] in moving
                                     else view for view in wardrobe.slots])
    picks, fits = fit_budget([(view.slot["id"], view.qty, pool) for view, pool in free], wardrobe.budget - spent,
                             _wear(basis))
    total = spent + sum(picks[view.slot["id"]].price * view.qty for view, _ in free)
    return picks, fits, round(total, 2)


def _wear(wardrobe: Wardrobe) -> dict[str, float]:
    """How much each slot's quality counts: the share of the outfits it appears in (plus a little, so
    that a piece in few outfits still counts). Trousers and shoes are in most outfits; one of eight
    tops is in few."""
    from . import outfits     # imported here: outfits.py itself builds on this module

    every = outfits.all_outfits(wardrobe)
    if not every:
        return {}
    seen: dict[str, int] = {}
    for outfit in every:
        for slot_id in outfit.slots:
            seen[slot_id] = seen.get(slot_id, 0) + 1
    return {view.slot["id"]: seen.get(view.slot["id"], 0) / len(every) + 0.05 for view in wardrobe.slots}
