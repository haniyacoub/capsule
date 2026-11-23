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
       best for budget   the plan as a whole (every piece outfits are made from,
                         not only the ones in his wardrobe so far): every slot
                         starts on its cheapest option and the rest of the budget
                         goes to upgrades, best value first (see fit_budget below).
                         A piece's product therefore does not depend on which
                         outfits he said yes to: a yes adds exactly the products
                         the outfit showed, at the prices it showed. A piece with
                         nothing that reaches the minimum quality takes its
                         cheapest option in your size, with a warning (_fit)
     "In stock in your size" first: a candidate whose store gave no sizes (COS)
     is considered only when none known to be in your size reaches the minimum
     quality. One known to be sold out in your size, or not made in it, is never
     picked automatically; it stays on the piece's page, marked, to choose by hand.
  4. A product chosen by hand (rule 2) can sell out in your size afterwards, or be chosen
     although it is. It stays the piece's product, so the outfits stay as they are, but it
     is said to be sold out, it counts nothing in the total (it cannot be bought), and the
     next best product that is in stock in your size is offered in its place (next_best).
     "Nothing else is in stock in your size" is said only when that is known: other products
     whose sizes were never checked (COS) are counted and pointed to instead (SlotView.no_swap).

The pieces are the plan: what outfits are made from. The customer's wardrobe is the part of it he said yes to
(SlotView.mine, Wardrobe.mine): the pieces of the outfits he added, what he owns, and what he had chosen by hand
before the wardrobe worked this way. Only that part is counted in a total.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import cached_property

from . import capsule
from . import catalog as catalog_mod
from . import colours, db, english, programmes, scoring, shared, sizecheck, sizes, style
from . import profile as profile_mod
from .garments import GARMENTS, SECTIONS, Garment
from . import settings

# The price levels, cheapest first. To rename one, change its label here.
# "Top" is the dearest option these stores sell for a slot; none of them is a luxury brand.
MODES = {"cheapest": "Cheapest", "cheap": "Cheap", "medium": "Medium", "expensive": "Expensive", "top": "Top",
         "budget": "Best for budget"}
# Where each level sits between the cheapest (0) and the most expensive (1) candidate of a slot.
# ("budget" is not a place on that line: it looks at the whole wardrobe.)
POSITION = {"cheapest": 0.0, "cheap": 0.25, "medium": 0.5, "expensive": 0.75, "top": 1.0}
HINTS = {
    "budget": "The most quality your budget buys for all the pieces your outfits are made from, taken together: "
              "every piece starts on its cheapest option, and what is left pays for upgrades, first where a euro "
              "improves most the pieces you would wear most",
    "cheapest": "The lowest-priced option for each piece",
    "cheap": "A low-priced option: about a quarter of the way up each piece's price range",
    "medium": "The middle-priced option for each piece",
    "expensive": "A high-priced option: about three quarters of the way up each piece's price range",
    "top": "The most expensive option these stores sell for each piece",
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


def gone_words(n_sold_out: int, n_not_made: int, example: bool = False) -> str:
    """What is said of pieces whose chosen product cannot be bought in his size, counted together: 'sold out in
    your size', 'not made in your size', or, with some of each, 'sold out or not made in your size'. While the
    sizes are still the example's it is 'the example size', as everywhere."""
    size = "the example size" if example else "your size"
    if not n_not_made:
        return f"sold out in {size}"
    return f"not made in {size}" if not n_sold_out else f"sold out or not made in {size}"


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
    def size_cautions(self) -> list[str]:
        """What there is to act on about this very product's size before buying, for its row in a list: a cut that
        runs large or sits close ("Fit: oversized, runs large. Size down for a regular fit."), then what the store's
        chart and the label say against his measurements (sizecheck.check). Not "Sizes not checked at COS": that is
        true of the whole store, the last of the notes where it applies, and said once for it (said_once)."""
        store_wide = sizes.not_checked(self.data.get("store", "")) + "."
        notes = [note for note in self.check.notes if note != store_wide]
        return ([f"Fit: {self.check.fit}"] if self.check.fit and self.check.fit_flag else []) + list(notes)

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def collected(self) -> str:
        """The day this product's price and stock were collected ("11 Nov 2026, 17:00"), or "" when it does not say."""
        return catalog_mod.oldest_label([self.data], "")

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
    # A piece Stilsmith's product list has nothing for: colours it has the garment in, to switch to in one
    # tap (see _offer), or, when there are none, why the piece stays out of the outfits and the total.
    offers: list[colours.Colour] = field(default_factory=list)
    left_out: str | None = None
    # For a chosen product that is sold out in his size: the next best one that is in stock in it (next_best),
    # offered in one tap wherever the piece shows (_sold_out.html). None when no other is in stock in his size.
    swap: Cand | None = None
    example_size: bool = False      # the sizes are still the example's (profile.sizes_unconfirmed): said with the size
    outfits_in: int = 0             # how many of the outfits he said yes to wear this piece ("In 4 of your outfits")
    kept: bool = False              # in his wardrobe on its own account: chosen by hand before version 9 (db.py)
    spare: bool = False             # he added the plan's further ones of this piece to his wardrobe ("Add a spare")
    # How his style (the styles he ticked, his style brief) narrowed what the price level chose among for this
    # piece (style.narrowed): "" not at all, "fits" to the products that fit it, "best" to those that suit it best
    # where none fits. The piece's page says it: with a cheaper option in its list that the style passed over,
    # "the cheapest option rated 70 or more" alone would not be true.
    styled: str = ""
    # "Best for budget" with nothing for this piece that reaches the minimum quality: it takes its cheapest option in
    # his size (_fit), not the best-rated one a price level takes (choose). The piece's page says which.
    cheapest_instead: bool = False

    @property
    def mine(self) -> bool:
        """Whether the piece is in his wardrobe: an outfit he said yes to wears it, he owns it, or he kept it."""
        return self.outfits_in > 0 or self.state == "owned" or self.kept

    @property
    def shown_name(self) -> str:
        """The piece's name as shown with its product: its own, or the product's kind where that plainly differs
        from it ("Dark brown loafers" for "Dark brown derby shoes" filled by a loafer: english.as_picked). A piece he
        owns, or with nothing picked, keeps its own name."""
        if self.chosen is None or self.state == "owned":
            return self.slot["name"]
        return english.as_picked(self.slot["name"], self.slot.get("keywords", ""), self.chosen.data.get("name", ""))

    @property
    def in_outfits_words(self) -> str:
        """'In 4 of your outfits', 'In 1 of your outfits', or 'In none of your outfits yet'."""
        return f"In {self.outfits_in} of your outfits" if self.outfits_in else "In none of your outfits yet"

    @property
    def your_size(self) -> str:
        return "the example size" if self.example_size else "your size"

    @property
    def planned(self) -> int:
        """How many of this piece the plan has: two white tees. What the plan page counts."""
        return int(self.slot.get("qty") or 1)

    @property
    def qty(self) -> int:
        """How many of this piece count in his wardrobe, his total and his shopping list. One: an outfit wears one,
        and a yes adds exactly what the outfit shows. All the plan has once he added the spare to a piece of his
        wardrobe ("Add a spare" on its card), and for a piece he owns (he said how many he has)."""
        return self.planned if self.state == "owned" or (self.spare and self.mine) else 1

    @property
    def n_spare(self) -> int:
        """How many more of this piece the plan has than an outfit wears: what "Add a spare" adds. None for a piece
        he owns."""
        return 0 if self.state == "owned" else self.planned - 1

    @property
    def spare_words(self) -> tuple[str, str, str]:
        """What the piece's card says of its spare, and the two buttons: ('One of the 2 is a spare', 'Add a spare',
        'Take the spare out'); with three in the plan ('2 of the 3 are spares', 'Add 2 spares', 'Take the spares
        out')."""
        n = self.n_spare
        if n == 1:
            return f"One of the {self.planned} is a spare", "Add a spare", "Take the spare out"
        return f"{n} of the {self.planned} are spares", f"Add {n} spares", "Take the spares out"

    @property
    def sold_out(self) -> bool:
        """The chosen product cannot be bought in his size: sold out in it since he chose it, or not made in it.
        Only a product chosen by hand can be: the automatic pick never takes one (choose)."""
        return self.state != "owned" and self.chosen is not None and not self.chosen.available

    @property
    def not_made(self) -> bool:
        """The chosen product is not made in his size at all (rather than sold out in it)."""
        return self.sold_out and self.chosen is not None and not self.chosen.size.label

    @property
    def sold_words(self) -> str:
        """'Sold out in M', with the store's own label for his size, or 'Not made in your size'. While the sizes
        are still the example's: 'Sold out in M (example size)', 'Not made in the example size'."""
        label = self.chosen.size.label if self.chosen else None
        if not label:
            return f"Not made in {self.your_size}"
        return f"Sold out in {label}" + (" (example size)" if self.example_size else "")

    @property
    def no_swap(self) -> tuple[str, str, bool]:
        """With no product to offer in place of a sold-out one (swap is None), what is true of the piece's other
        products: (the sentence, what else there is, whether there is anything else to look at).
        "Nothing else for this piece is in stock in your size" only when that is known. Products whose store gave
        no sizes (COS) may well be in stock: they are counted, by store, and the page points to all the options
        instead of to pasting a link. So is one in his size that has no price yet (a pasted link)."""
        others = [c for c in self.cands if self.chosen is None or c.id != self.chosen.id]
        unchecked = [c for c in others if c.size.rank == sizes.NOT_CHECKED]
        no_price = [c for c in others if c.size.rank == sizes.IN_YOUR_SIZE and c.price <= 0]
        more = []
        if unchecked:
            names = sorted({programmes.label(c.data.get("store", "")) for c in unchecked if c.data.get("store")})
            at = f" at {' and '.join(names)}" if names else ""
            more.append(f"{len(unchecked)} more{at}: sizes not checked")
        if no_price:
            more.append(f"{len(no_price)} more in stock in {self.your_size}: no price yet")
        if no_price:
            lead = f"Nothing else in stock in {self.your_size} has a price yet"
        elif unchecked:
            lead = f"Nothing else is known to be in stock in {self.your_size}"
        else:
            lead = f"Nothing else for this piece is in stock in {self.your_size}"
        return lead, ", ".join(more), bool(more)

    @property
    def swap_cents(self) -> int:
        """What the product offered in place of a sold-out one costs more (or, below zero, less), in cents, for
        one of them."""
        if self.swap is None or self.chosen is None:
            return 0
        return round(self.swap.price * 100) - round(self.chosen.price * 100)

    @property
    def price(self) -> float:
        """What the chosen product costs for this piece, in stock or not."""
        return 0.0 if self.state == "owned" or self.chosen is None else self.chosen.price * self.qty

    @property
    def cost(self) -> float:
        """What this piece adds to the total: nothing while its product is sold out in his size, as it cannot be
        bought. Every page that shows the piece says so."""
        return 0.0 if self.sold_out else self.price

    @property
    def n_available(self) -> int:
        """Options that may be picked: in stock in your size, or with sizes not checked."""
        return sum(1 for c in self.cands if c.available)

    @property
    def n_in_your_size(self) -> int:
        """Options known to be in stock in your size."""
        return sum(1 for c in self.cands if c.size.rank == sizes.IN_YOUR_SIZE)

    @property
    def n_not_checked(self) -> int:
        """Options whose store gave no sizes, so nobody knows whether yours is in stock."""
        return sum(1 for c in self.cands if c.size.rank == sizes.NOT_CHECKED)


@dataclass
class StoreSaid:
    """What is true of a whole store's products on a page, said once instead of on every row (said_once)."""
    store: str          # the store's key
    label: str          # its name, as people read it
    sizes: str = ""     # "Sizes not checked at COS: look on its page before you buy." A size to check: amber
    fabric: str = ""    # "Fabric is estimated for 3 of the 5 products here …": plain words


def said_once(cands: list[Cand]) -> list[StoreSaid]:
    """The cautions that used to stand on every row of a list, said once per store: that a store's sizes were not
    checked, and for how many of its products here the fabric is an estimate or not stated at all. `cands` are the
    products the page lists (the chosen product of each piece). Stores are in the order config/stores.toml lists
    them; a store with nothing to say is left out. Nothing here is new: each product's own card (the pop-up, the
    piece's page) still says its fabric, "estimated" where it is, and "Sizes not checked at …" in full.

    Sizes: where none of a store's products here had its sizes checked (COS), the sentence every row used to carry
    (sizes.not_checked); where only some did not, how many, and that those are the ones marked "check".
    Fabric: "estimated" is a fabric read off the product's name or assumed from the kind of garment
    (scoring.Score.fabric_source "name" or "assumed"); "not stated" is one with nothing to go by ("none")."""
    by_store: dict[str, list[Cand]] = {}
    for c in cands:
        by_store.setdefault(c.data.get("store", ""), []).append(c)
    order = list(programmes.offered())
    out: list[StoreSaid] = []
    for store in sorted(by_store, key=lambda key: order.index(key) if key in order else len(order)):
        products = by_store[store]
        m, name = len(products), programmes.label(store) if store else ""
        said = StoreSaid(store=store, label=name or "Other")

        def of_them(n: int) -> str:
            if n == m:
                return "this product" if m == 1 else "both products here" if m == 2 else f"all {m} products here"
            return f"{n} of the {m} products here"

        unchecked = sum(1 for c in products if not c.size.known)
        if unchecked == m:
            said.sizes = sizes.not_checked(store) + "."
        elif unchecked:
            at, where = (f" at {name}", "its page") if name else ("", "the store's page")
            said.sizes = (f"Sizes not checked for {unchecked} of the {m} products here{at}, marked “check”: "
                          f"look on {where} before you buy.")
        estimated = sum(1 for c in products if c.score.fabric_source in ("name", "assumed"))
        unstated = sum(1 for c in products if c.score.fabric_source == "none")
        if estimated and unstated:
            what = f"Fabric is estimated for {estimated} of the {m} products here and not stated for {unstated}"
        elif estimated:
            what = f"Fabric is estimated for {of_them(estimated)}"
        elif unstated:
            what = f"Fabric is not stated for {of_them(unstated)}"
        else:
            what = ""
        if what:
            said.fabric = what + ": check the label on the product page. Each piece's own page says what is known."
        if said.sizes or said.fabric:
            out.append(said)
    return out


@dataclass
class Wardrobe:
    slots: list[SlotView]
    mode: str
    threshold: int
    budget: float
    source: str                  # mock | collected | empty
    collected: str               # when the list was collected: its newest store's day (as_of says it for the pieces)
    stores: dict = field(default_factory=dict)   # per store: how the last refresh went
    note: str = ""               # something to say about the whole wardrobe (the budget cannot be met)
    example_sizes: bool = False  # the sizes are still the example's: "in the example size", not "in your size"
    n_outfits: int = 0           # how many outfits he said yes to
    budget_known: bool = True    # False until he gave a budget (profile.budget_known): then nothing is "left" or "over"
    # Whether "Best for budget" has a budget to fit to: one he gave, or, for someone who was on that level before the
    # wardrobe became the outfits he said yes to, the budget his account started with, as it was fitted then (build).
    budget_to_fit: bool = True
    only_mine: bool = False      # this is `mine` already: the pieces of his wardrobe and nothing else
    plan: "Wardrobe | None" = None      # for `mine`: the whole plan it is the part of (what "Best for budget" fits)
    brief: dict | None = None    # the style brief he confirmed (style.py), or None: then every pick is as before

    @cached_property
    def mine(self) -> "Wardrobe":
        """His wardrobe: the same thing with only the pieces that are in it (SlotView.mine). Every total, count and
        list of things to buy is asked of this; the outfits are made from all the pieces."""
        if self.only_mine:
            return self
        return replace(self, slots=[view for view in self.slots if view.mine], only_mine=True, plan=self)

    @cached_property
    def levels(self) -> dict[str, float]:
        """What the whole wardrobe would cost at each price level, and fitted to the budget.
        Only the Wardrobe page shows this, so it is worked out when first asked for."""
        ladder = {}
        for level in POSITION:
            cost = 0.0
            for view in self.slots:
                if view.state == "auto":
                    pick = choose(view.cands, level, self.threshold, brief=self.brief,
                                  category=view.slot["category"])[0]
                    cost += pick.price * view.qty if pick else 0.0
                else:
                    cost += view.cost
            ladder[level] = round(cost, 2)
        if not self.budget_to_fit:      # no budget to fit to yet: that level picks the cheapest options meanwhile
            ladder["budget"] = ladder["cheapest"]
        elif self.mode == "budget":
            ladder["budget"] = self.total
        else:
            # "Best for budget" is fitted for the whole plan (build, below); these pieces at the products it gives them.
            picks = _fit(self.plan or self)[0]
            ladder["budget"] = round(sum(picks[view.slot["id"]].price * view.qty if view.slot["id"] in picks
                                         else view.cost for view in self.slots), 2)
        return ladder

    @property
    def said_once(self) -> list[StoreSaid]:
        """What is true of each store's products among these pieces, said once over the rows (said_once): of the
        products to buy, so not of a piece he owns."""
        return said_once([view.chosen for view in self.slots if view.chosen is not None and view.state != "owned"])

    @property
    def styled(self) -> bool:
        """Whether his style passed over a product for any piece outfits are made from (SlotView.styled): then "the
        lowest-priced option for each piece" is true only among the products his style left."""
        return any(view.styled for view in (self.plan or self).slots)

    @property
    def total(self) -> float:
        return round(sum(s.cost for s in self.slots), 2)

    @property
    def as_of(self) -> str:
        """"Prices and stock as of …" for these pieces: the day the oldest of their products was collected (a product
        collected on 11 Nov holds as of 11 Nov, though the list also has stores collected later), or the list's."""
        return catalog_mod.oldest_label([view.chosen.data for view in self.slots
                                         if view.chosen is not None and view.state != "owned"], self.collected)

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
        return sum(s.qty for s in self.slots if s.state != "owned" and s.chosen and not s.sold_out)

    @property
    def n_sold_out(self) -> int:
        """Pieces whose chosen product is sold out in his size (or not made in it): not to buy, not in the total."""
        return sum(s.qty for s in self.slots if s.sold_out)

    @property
    def gone_words(self) -> str:
        """'sold out in your size', 'not made in your size' or 'sold out or not made in your size': what is true
        of the pieces n_sold_out counts."""
        not_made = sum(s.qty for s in self.slots if s.not_made)
        return gone_words(self.n_sold_out - not_made, not_made, self.example_sizes)

    @property
    def n_owned(self) -> int:
        return sum(s.qty for s in self.slots if s.state == "owned")

    @property
    def n_unfilled(self) -> int:
        return sum(1 for s in self.slots if s.state != "owned" and s.chosen is None)

    @property
    def n_missing(self) -> int:
        """Pieces Stilsmith's product list has nothing for yet. Counted like n_buy: a white tee ×2 is two."""
        return sum(s.qty for s in self.slots if s.state != "owned" and not s.cands)

    @property
    def n_no_size(self) -> int:
        """Pieces with options, none of them in stock in your size, so nothing is picked."""
        return sum(s.qty for s in self.slots if s.state != "owned" and s.cands and s.chosen is None and not s.n_available)

    @property
    def n_nothing_to_buy(self) -> int:
        """Every piece nothing is picked for, whatever the reason: all a phone's budget bar has room to say when
        there is more than one reason."""
        return self.n_missing + self.n_no_size + self.n_no_price + self.n_sold_out

    @property
    def n_no_price(self) -> int:
        """Pieces whose options in your size all lack a price, so nothing is picked: a product added by its
        link has none until you type it in."""
        return sum(s.qty for s in self.slots if s.state != "owned" and s.chosen is None and s.n_available)

    @property
    def unfilled_words(self) -> list[str]:
        """The budget bar's count of pieces nothing is picked for, by why: '6 pieces not in the product list
        yet', '1 piece not in stock in your size', '1 piece with no price yet', '1 piece sold out in your size' (its
        chosen product is, and others may not be; 'not made in your size' where that is the reason, see
        gone_words). Each count is true on its own."""
        out = []
        for n, why in ((self.n_missing, "not in the product list yet"), (self.n_no_size, "not in stock in your size"),
                       (self.n_no_price, "with no price yet"), (self.n_sold_out, self.gone_words)):
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


def in_your_size_first(pool: list[Cand]) -> list[Cand]:
    """The candidates of `pool` known to be in stock in your size, or, when there are none, all of `pool` (those
    whose sizes were not checked). `pool` never holds one known to be sold out in your size or not made in it."""
    return [c for c in pool if c.size.rank == sizes.IN_YOUR_SIZE] or pool


def choose(cands: list[Cand], mode: str, threshold: int, colour: str = "", brief: dict | None = None,
           category: str = "") -> tuple[Cand | None, str | None, bool]:
    """The automatic pick for a slot: (candidate, note, is_warning). `colour` is the piece's colour, in
    words ('black'), for the note on a piece the product list has nothing for. `brief`: his style brief, if he
    confirmed one, for a piece of garment type `category`: the price level then chooses among the products that
    fit it (style.narrow). Without one, among all of them, as before."""
    if not cands:
        return None, (f"Not in {settings.SITE_NAME}'s product list in {colour} yet" if colour
                      else f"Not in {settings.SITE_NAME}'s product list yet"), True
    # An item without a price has no place on the price ladder: it is never picked automatically. Nor is one known
    # to be sold out in your size or not made in it (c.available is False); one whose sizes were not checked may be.
    available = [c for c in cands if c.available and c.price > 0]
    if not available:
        if any(c.available for c in cands):     # in your size, but no price: one added by its link has none yet
            return None, "No price yet: add it under “Add details”", True
        return None, "Nothing in stock in your size", True
    good = [c for c in available if c.score.total >= threshold]
    if not good:
        pool = in_your_size_first(available)
        best = max(pool, key=lambda c: (c.score.total, -c.price))
        if len(pool) < len(available):      # options whose sizes were not checked were passed over
            return best, f"Nothing reaches {threshold} — this is the best in your size", True
        return best, f"Nothing reaches {threshold} — this is the best available", True
    return at_level(style.narrow(in_your_size_first(good), category, brief), mode), None, False


def next_best(cands: list[Cand], sold_out: Cand, threshold: int) -> Cand | None:
    """What to offer in place of a chosen product that is sold out in his size: among the piece's other products
    known to be in stock in his size, with a price, the one nearest in price to the one he chose (at equal
    distance the better one, then the cheaper). Those that are good enough first; if none is, any. Good enough:
    reaching the minimum quality, or rated at least as well as the one he chose (he took a 67 under a minimum of
    70: another 67 at the same price is a truer replacement than an 80 for 5 € more).
    Never one whose sizes were not checked: the offer says "in stock in your size", and that must be known.
    None when nothing else is in stock in his size."""
    pool = [c for c in cands if c.id != sold_out.id and c.size.rank == sizes.IN_YOUR_SIZE and c.price > 0]
    enough = min(threshold, sold_out.score.total)
    pool = [c for c in pool if c.score.total >= enough] or pool
    if not pool:
        return None
    return min(pool, key=lambda c: (abs(round(c.price * 100) - round(sold_out.price * 100)), -c.score.total, c.price))


# ── best for budget: the wardrobe as a whole ──────────────────────────────────

def cheapest_instead(cands: list[Cand]) -> Cand | None:
    """"Best for budget" for a piece with nothing that reaches the minimum quality: its cheapest option in your
    size (one whose sizes were not checked only where none is known to be in your size), never one sold out in your
    size, not made in it, or without a price. At equal prices the better one. None when there is nothing to buy."""
    available = [c for c in cands if c.available and c.price > 0]
    if not available:
        return None
    return min(in_your_size_first(available), key=lambda c: (c.price, -c.score.total))


def cheapest_words(cands: list[Cand], threshold: int) -> str:
    """The warning on a piece that takes its cheapest option because nothing reaches the minimum quality
    (cheapest_instead): 'Nothing reaches 70 — this is the cheapest in your size' where options whose sizes were not
    checked were passed over (one of them might cost less), else '… — this is the cheapest available'."""
    available = [c for c in cands if c.available and c.price > 0]
    if len(in_your_size_first(available)) < len(available):
        return f"Nothing reaches {threshold} — this is the cheapest in your size"
    return f"Nothing reaches {threshold} — this is the cheapest available"


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


def build(profile: dict | None = None, catalogue: dict | None = None) -> Wardrobe:
    """Everything the pages show, computed fresh from the files on disk (or from `catalogue`, a catalogue as it was
    stored: what a customer saw before a store stopped being offered, see shared.refresh_customer)."""
    profile = profile or profile_mod.load()
    cat = catalog_mod.load() if catalogue is None else catalogue
    mode, threshold = _controls()
    rules = scoring.load_rules()
    charts = sizes.load_charts()
    grouped = catalog_mod.by_slot(cat)
    example = profile_mod.sizes_unconfirmed(profile)     # said with every size until he says the sizes are his
    yes = db.yes_sigs()                                   # the outfits he said yes to, as the pieces each combines
    worn = Counter(slot_id for sig in yes for slot_id in set(sig.split("~")))
    kept = set(db.get_setting("kept_pieces") or [])
    spares = set(db.get_setting("spares") or [])       # pieces whose spare he added to his wardrobe (yes.spare)
    brief = style.current()                               # None unless he confirmed a style brief

    views: list[SlotView] = []
    for slot in db.list_slots():
        if slot["category"] not in GARMENTS:
            continue  # a garment type that no longer exists
        cands = [_cand(c, slot, profile, rules, charts) for c in grouped.get(slot["id"], [])]
        # In your size first, then sizes not checked, then sold out or not made in your size; each by price.
        cands.sort(key=lambda c: (c.size.rank, c.price, -c.score.total))
        view = SlotView(slot=slot, garment=GARMENTS[slot["category"]],
                        colour=colours.get(slot["colour"]), cands=cands, example_size=example,
                        outfits_in=worn.get(slot["id"], 0), kept=slot["id"] in kept, spare=slot["id"] in spares)

        if slot["owned"]:
            view.state = "owned"
        else:
            picked = None
            if slot["locked"] and slot["pick"]:
                picked = next((c for c in cands if c.id == slot["pick"]), None)
            if picked:
                view.state, view.chosen = "locked", picked
                if not picked.available:      # said wherever the piece shows, with the next best in his size
                    view.note, view.warn = view.sold_words, True
                    view.swap = next_best(cands, picked, threshold)
            else:
                view.chosen, view.note, view.warn = choose(cands, mode, threshold, view.colour.label.lower(),
                                                           brief, slot["category"])
                if slot["locked"] and slot["pick"] and cands:     # (with nothing on offer, choose said so)
                    view.note = "Your locked choice is no longer in the catalogue — showing the automatic pick"
                    view.warn = True
        views.append(view)
    for view in views:
        if view.state != "owned" and not view.cands:
            _offer(view, views, profile, charts)
    for view in views:
        view.styled = _styled(view, threshold, brief)

    wardrobe = Wardrobe(
        slots=views, mode=mode, threshold=threshold, budget=float(profile.get("budget") or 0),
        source=cat.get("source", "empty"),
        collected=catalog_mod.collected_label(cat),
        stores=cat.get("stores", {}), example_sizes=example, brief=brief,
        n_outfits=db.count_saved(), budget_known=profile_mod.budget_known(profile),
    )
    # Someone who was on "Best for budget" before the wardrobe became the outfits he said yes to, with the budget his
    # account started with (he never gave one): the level goes on fitting to that budget, so that none of his
    # products changes with the upgrade (db.py notes it, "budget_as_before"), and the page says which budget it is.
    wardrobe.budget_to_fit = wardrobe.budget_known or bool(db.get_setting("budget_as_before"))
    # Where his style passed products over, "cheapest" is the cheapest of what it left, and the notes say so.
    of_style = " and suit your style best" if wardrobe.styled else ""
    if mode == "budget" and not wardrobe.budget_to_fit:
        # No budget to fit anything to yet: every piece shows its cheapest option that reaches the minimum quality.
        wardrobe.note = ("“Best for budget” needs your budget: set one on the Profile page. Until then these are "
                         f"the cheapest options that reach your minimum quality{of_style}.")
    elif mode == "budget":
        # Fitted for the whole plan together, the pieces that are not in his wardrobe yet included, each as often as
        # the plan has it (_fit). So a piece's product does not depend on which outfits he said yes to, or on a
        # spare: a yes adds the products the outfit showed, at the prices it showed, and nothing he already has
        # changes under him. His wardrobe is a part of the plan, so whatever he adds stays within his budget
        # whenever the plan as a whole does. (It is also what this level did before the wardrobe was the outfits he
        # said yes to: nobody's products change with that upgrade.)
        picks, fits, _ = _fit(wardrobe)
        for view in views:
            if view.slot["id"] in picks:
                view.chosen = picks[view.slot["id"]]
                if view.chosen.score.total < threshold:     # nothing reaches it: the cheapest instead (_fit)
                    view.cheapest_instead, view.warn = True, True
                    view.note = cheapest_words(view.cands, threshold)
        if not fits:
            # A piece with nothing that reaches the minimum quality is on its cheapest option all the same.
            where = " where one does" if any(view.cheapest_instead for view in views) else ""
            on = "the cheapest of those" if of_style else "its cheapest option"
            if of_style and where:
                on += " (its cheapest option where none does)"
            wardrobe.note = (
                f"Even on their cheapest options that reach your minimum quality{of_style}{where}, the pieces your "
                f"outfits are made from come to more than your budget together, so every piece is on {on}. Lower the "
                "minimum quality, mark what you own, or raise the budget on the Profile page.")
        if not wardrobe.budget_known:
            wardrobe.note = (f"“Best for budget” is still fitted to {wardrobe.budget:,.0f} €, the budget your account "
                             "started with, as before. Set your own budget on the Profile page. " + wardrobe.note).strip()
    return wardrobe


def _styled(view: SlotView, threshold: int, brief: dict | None) -> str:
    """How his style narrowed what this piece's automatic pick was chosen among (SlotView.styled). The products are
    the ones a price level (choose) and "Best for budget" (_fit) choose among: those he can buy that reach the
    minimum quality, in his size first. Where none reaches it the pick is the best-rated one and his style has no
    say, and a piece he owns or locked is not picked for him at all."""
    if not brief or view.state != "auto" or view.chosen is None:
        return ""
    good = [c for c in view.cands if c.available and c.price > 0 and c.score.total >= threshold]
    return style.narrowed(in_your_size_first(good), view.slot["category"], brief)[1] if good else ""


def _offer(view: SlotView, views: list[SlotView], profile: dict, charts: dict) -> None:
    """For a piece the product list has nothing for: up to three colours Stilsmith has its garment in, each
    of which fills it in one tap (app.slot_colour). Liked colours come first and refused ones never. A
    colour whose products another piece of that garment already has is skipped, and so is one that
    reaches the same products as a colour already offered: the piece must not become a copy of another.
    So is a colour with nothing in your size at a price: the tap would leave the piece as empty as before.
    With nothing left to offer, `left_out` says why the piece stays empty, true to why each colour he
    wears was passed over: its products are already another piece's, or not in his size.
    """
    category = view.slot["category"]
    refused = frozenset(capsule.banned(profile.get("refused", [])))      # refusing "green" refuses olive too
    mine = frozenset(profile_mod.stores(profile))                          # the stores he ticked on Profile
    on_offer = shared.colours_on_offer(category, refused, mine)      # never a product in a refused colour, either
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
        if not shared.colours_on_offer(category, stores=mine):  # none in any colour (on_offer leaves out the refused)
            # Say whether the stores he unticked on Profile have some: ticking one again fills the piece.
            why = (f"{settings.SITE_NAME} has {kind} only from stores you unticked" if shared.colours_on_offer(category)
                   else f"{settings.SITE_NAME} has no {kind} yet")
        elif in_your_plan:      # say so: "Stilsmith has none" would be untrue beside the grey jumper that has them
            why = f"{settings.SITE_NAME}'s {kind} in other colours you wear {verb} already in your plan"
            if not_in_your_size:
                why += " or not in your size"
        elif not_in_your_size:
            why = f"{settings.SITE_NAME} has no {kind} in your size in other colours you wear yet"
        else:                   # it has this garment only in colours he refused
            why = f"{settings.SITE_NAME} has no {kind} in other colours you wear yet"
        view.left_out = f"{why}, so this piece is left out of your outfits and your total."


def _fit(wardrobe: Wardrobe) -> tuple[dict[str, Cand], bool, float]:
    """Best for budget, for this wardrobe: (the pick per automatic slot, whether it fits, what it all costs).

    The slots it may move are the automatic ones that have candidates reaching the minimum quality, and each
    moves among those in your size first, as a price level does (choose). An automatic slot with none that does
    takes its cheapest option in your size (cheapest_instead), and is in the picks too. Everything else (owned,
    locked, those cheapest options) is money already spent. A locked product that is sold out in his size counts
    nothing in the total, but its price is kept aside here: the swap offered for it costs about as much, and the
    money must not be spent on upgrades that the swap would then take back.

    Every piece counts as often as the plan has it (two white tees), whether or not his wardrobe holds the spare:
    what is picked must not depend on what he has said yes to so far (build).
    """
    def planned(view: SlotView) -> float:       # the piece's product, as often as the plan has the piece
        return 0.0 if view.state == "owned" or view.chosen is None else view.chosen.price * view.planned

    free = [(view, [c for c in view.cands if c.available and c.price > 0 and c.score.total >= wardrobe.threshold])
            for view in wardrobe.slots if view.state == "auto"]
    # A piece with nothing that reaches the minimum quality takes its cheapest option in his size (cheapest_instead),
    # not the best-rated one a price level takes: the best-rated one, counted as money already spent, could break
    # the budget by itself. It is money already spent all the same: there is nothing better for it to move to.
    instead = {view.slot["id"]: cheapest for view, pool in free if not pool
               and (cheapest := cheapest_instead(view.cands)) is not None}
    free = [(view, style.narrow(in_your_size_first(pool), view.slot["category"], wardrobe.brief))
            for view, pool in free if pool]
    moving = {view.slot["id"]: min(pool, key=lambda c: (c.price, -c.score.total)) for view, pool in free}
    fixed = [replace(view, chosen=instead[view.slot["id"]]) if view.slot["id"] in instead else view
             for view in wardrobe.slots if view.slot["id"] not in moving]
    spent = sum(planned(view) for view in fixed if not view.sold_out)
    aside = sum(planned(view) for view in fixed if view.sold_out)
    # How much each slot is worn is judged with every free slot on its cheapest candidate, whatever
    # is selected right now: the answer must not depend on the level the page happens to be on.
    start = {**instead, **moving}
    basis = replace(wardrobe, slots=[replace(view, chosen=start[view.slot["id"]]) if view.slot["id"] in start
                                     else view for view in wardrobe.slots])
    slots, wear = [(view.slot["id"], view.planned, pool) for view, pool in free], _wear(basis)
    picks, fits = fit_budget(slots, wardrobe.budget - spent - aside, wear)
    if not fits and aside:      # only the money kept aside is in the way: what can be bought does fit
        picks, fits = fit_budget(slots, wardrobe.budget - spent, wear)
    total = spent + sum(picks[view.slot["id"]].price * view.planned for view, _ in free)
    return {**instead, **picks}, fits, round(total, 2)


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
