"""The shopping list: what is selected right now, grouped by store.

`build()` turns the wardrobe into plain rows; the page, the Markdown file and
the CSV file are three ways of printing the same rows. (The CSV columns never
change: people keep spreadsheets built on them.)

A piece whose chosen product is sold out in your size is not a row to buy: it is
listed apart (`sold_out`), counts nothing in any total, and the page and the
Markdown file say so, with the next best product in your size. The CSV file,
which is rows to buy and nothing else, leaves it out.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date

from . import programmes
from .selection import Cand, SlotView, StoreSaid, Wardrobe, gone_words, said_once


@dataclass
class Line:
    slot: str
    product: str
    colour: str
    size: str
    qty: int
    unit_price: float
    url: str
    notes: list[str] = field(default_factory=list)     # what to check before ordering: the fit, sizes, the fabric
    image_url: str = ""         # the store's photo of the product: on the pages, not in the files
    hex: str = ""               # its colour, shown where there is no photo
    # On the pages a row is short (_buy_groups.html): the piece and its price, the store's product by name, the colour
    # and the size. Under it only what there is to act on about this very product's size (`cautions`,
    # selection.Cand.size_cautions) and what was said of how it was picked (`said`). What is true of the whole store
    # (sizes not checked, fabric estimated) is said once under the store's name (StoreGroup.said).
    cand: Cand | None = None
    cautions: list[str] = field(default_factory=list)
    said: str = ""
    view: SlotView | None = None    # the piece itself: for a sold-out line, what is offered in its place
    slot_id: str = ""           # the piece's own page: where its fabric, fit and quality are said in full
    spares: int = 0             # how many of `qty` are spares he added on the piece's card: said beside the count

    @property
    def spare_words(self) -> str:
        """'one is a spare' or '2 are spares', or nothing."""
        return "" if not self.spares else "one is a spare" if self.spares == 1 else f"{self.spares} are spares"

    @property
    def total(self) -> float:
        return round(self.unit_price * self.qty, 2)


@dataclass
class StoreGroup:
    key: str
    label: str
    lines: list[Line] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return round(sum(line.total for line in self.lines), 2)

    @property
    def said(self) -> StoreSaid | None:
        """What is true of this store's products on the list, said once under its name instead of on every row
        (selection.said_once): sizes not checked, fabric estimated or not stated. None with nothing to say."""
        once = said_once([line.cand for line in self.lines if line.cand is not None])
        return once[0] if once else None

    @property
    def pieces(self) -> int:
        return sum(line.qty for line in self.lines)


@dataclass
class ShoppingList:
    groups: list[StoreGroup]
    owned: list[str]
    missing: list[tuple[str, str]]      # (slot, why nothing is selected)
    total: float
    budget: float
    collected: str
    demo: bool
    sold_out: list[Line] = field(default_factory=list)     # chosen, but sold out in your size: not to buy, not counted
    example_sizes: bool = False     # the sizes are still the example's: "in the example size"

    @property
    def remaining(self) -> float:
        return round(self.budget - self.total, 2)

    @property
    def pieces(self) -> int:
        return sum(g.pieces for g in self.groups)

    @property
    def pieces_sold_out(self) -> int:
        return sum(line.qty for line in self.sold_out)

    @property
    def gone_words(self) -> str:
        """What is true of the pieces listed apart: 'sold out in your size', 'not made in your size', or 'sold out
        or not made in your size' (selection.gone_words)."""
        not_made = sum(line.qty for line in self.sold_out if line.view and line.view.not_made)
        return gone_words(self.pieces_sold_out - not_made, not_made, self.example_sizes)


def build(w: Wardrobe, only: tuple[str, ...] | None = None) -> ShoppingList:
    """The list for the whole wardrobe, or with `only` for the slots of one outfit (one of each)."""
    groups: dict[str, StoreGroup] = {}
    owned: list[str] = []
    missing: list[tuple[str, str]] = []
    sold_out: list[Line] = []
    for s in w.slots:
        if only is not None and s.slot["id"] not in only:
            continue
        if s.state == "owned":
            owned.append(s.slot["name"])
            continue
        c = s.chosen
        if c is None:
            missing.append((s.slot["name"], s.note or "nothing selected"))
            continue
        if s.sold_out:      # not a line of a store's basket: said apart, with what is in stock in his size
            sold_out.append(Line(
                slot=s.shown_name, product=c.data.get("name", ""), colour=c.data.get("colour", ""),
                size=c.size_to_order, qty=s.qty if only is None else 1, unit_price=c.price,
                url=c.data.get("url", ""), image_url=c.data.get("image_url") or "", hex=c.colour_hex, cand=c, view=s,
                slot_id=s.slot["id"]))
            continue
        cautions = c.size_cautions
        notes = ([f"Fit: {c.check.fit}"] if c.check.fit else []) + list(c.check.notes)
        if c.score.fabric_source in ("name", "assumed"):
            notes.append("Fabric is an estimate — check the label on the product page.")
        elif c.score.fabric_source == "none":
            notes.append("Fabric not stated: check the product page.")
        if s.note:
            notes.append(s.note + ".")
        store = c.data.get("store", "")
        group = groups.setdefault(store, StoreGroup(store, programmes.label(store) if store else "Other"))
        group.lines.append(Line(
            slot=s.shown_name, product=c.data.get("name", ""), colour=c.data.get("colour", ""),
            size=c.size_to_order, qty=s.qty if only is None else 1, unit_price=c.price,
            url=c.data.get("url", ""), notes=notes,
            image_url=c.data.get("image_url") or "", hex=c.colour_hex, cand=c, cautions=cautions,
            spares=s.qty - 1 if only is None else 0, slot_id=s.slot["id"], said=s.note + "." if s.note else ""))
    order = list(programmes.offered())       # the stores in the order config/stores.toml lists them
    ordered = sorted(groups.values(), key=lambda g: order.index(g.key) if g.key in order else 99)
    total = w.total if only is None else round(sum(g.subtotal for g in ordered), 2)
    return ShoppingList(groups=ordered, owned=owned, missing=missing, total=total, budget=w.budget,
                        collected=w.collected, demo=w.source == "mock", sold_out=sold_out,
                        example_sizes=w.example_sizes)


def _eur(value: float) -> str:
    return f"{value:,.0f} €" if abs(value - round(value)) < 0.005 else f"{value:,.2f} €"


def to_markdown(sl: ShoppingList) -> str:
    out = [f"# Shopping list — {date.today().strftime('%-d %B %Y')}", ""]
    if sl.demo:
        out += ["> DEMO DATA: these items are invented. Run `python -m wardrobe refresh` for real ones.", ""]
    left = f"{_eur(sl.remaining)} left" if sl.remaining >= 0 else f"{_eur(-sl.remaining)} over budget"
    gone = sl.pieces_sold_out
    sold = f" ({gone} more {'is' if gone == 1 else 'are'} {sl.gone_words} and not counted)" if gone else ""
    out += [f"**{_eur(sl.total)}** for {sl.pieces} pieces{sold} · budget {_eur(sl.budget)} · {left}",
            f"Prices and stock as of {sl.collected}.",
            "Prices include VAT. Each store adds its own delivery costs at checkout.", ""]
    for g in sl.groups:
        out += [f"## {g.label} — {g.pieces} pieces, {_eur(g.subtotal)}", ""]
        for line in g.lines:
            qty = f"{line.qty} × " if line.qty > 1 else ""
            colour = f", {line.colour}" if line.colour else ""
            spare = f" ({line.spare_words})" if line.spares else ""
            out.append(f"- [ ] **{line.slot}** — {qty}{line.product}{colour}{spare} — size {line.size} — {_eur(line.total)}")
            out.append(f"  <{line.url}>")
            out += [f"  - {note}" for note in line.notes]
        out.append("")
    if sl.sold_out:
        out += [f"## {sl.gone_words[0].upper()}{sl.gone_words[1:]} (not counted above)", ""]
        for line in sl.sold_out:
            view = line.view
            store = programmes.label(line.cand.data.get("store", "")) if line.cand else ""
            said = f"- **{line.slot}** — {line.product} — {view.sold_words if view else 'Sold out'}"
            out.append(said + (f" at {store}" if store else ""))
            if view and view.swap:
                cents = view.swap_cents * line.qty      # for as many as the list buys, as its total would change
                diff = "same price" if cents == 0 else f"{_eur(abs(cents) / 100)} {'more' if cents > 0 else 'less'}"
                each, for_all = (" each", f" for {line.qty}") if line.qty > 1 and cents else ("", "")
                out.append(f"  - In stock in {view.your_size}: {view.swap.data.get('name', '')}, {_eur(view.swap.price)}{each} "
                           f"({diff}{for_all})")
                out.append(f"    <{view.swap.data.get('url', '')}>")
            elif view:      # only "nothing else" where that is known: sizes that were not checked are said
                lead, more, _ = view.no_swap
                out.append(f"  - {lead}." + (f" {more}. See them on the piece's page." if more else ""))
        out.append("")
    if sl.missing:
        out += ["## Still missing", ""] + [f"- {slot} — {why}" for slot, why in sl.missing] + [""]
    if sl.owned:
        out += ["## You already own", ""] + [f"- {name}" for name in sl.owned] + [""]
    return "\n".join(out)


def to_csv(sl: ShoppingList) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["store", "slot", "product", "colour", "size", "quantity", "unit_price_eur",
                     "total_eur", "link", "notes"])
    for g in sl.groups:
        for line in g.lines:
            writer.writerow([g.label, line.slot, line.product, line.colour, line.size, line.qty,
                             f"{line.unit_price:.2f}", f"{line.total:.2f}", line.url, " | ".join(line.notes)])
    return buffer.getvalue()
