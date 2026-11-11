"""The shopping list: what is selected right now, grouped by store.

`build()` turns the wardrobe into plain rows; the page, the Markdown file and
the CSV file are three ways of printing the same rows.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date

from .scoring import STORE_LABELS
from .selection import Wardrobe

STORE_ORDER = ["cos", "weekday", "zara"]


@dataclass
class Line:
    slot: str
    product: str
    colour: str
    size: str
    qty: int
    unit_price: float
    url: str
    notes: list[str] = field(default_factory=list)

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

    @property
    def remaining(self) -> float:
        return round(self.budget - self.total, 2)

    @property
    def pieces(self) -> int:
        return sum(g.pieces for g in self.groups)


def build(w: Wardrobe, only: tuple[str, ...] | None = None) -> ShoppingList:
    """The list for the whole wardrobe, or with `only` for the slots of one outfit (one of each)."""
    groups: dict[str, StoreGroup] = {}
    owned: list[str] = []
    missing: list[tuple[str, str]] = []
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
        notes = list(c.check.notes)
        if c.score.fabric_source in ("name", "assumed"):
            notes.append("Fabric is an estimate — check the label on the product page.")
        elif c.score.fabric_source == "none":
            notes.append("Fabric unknown — check the product page.")
        if s.note:
            notes.append(s.note + ".")
        store = c.data.get("store", "")
        group = groups.setdefault(store, StoreGroup(store, STORE_LABELS.get(store, store or "Other")))
        group.lines.append(Line(
            slot=s.slot["name"], product=c.data.get("name", ""), colour=c.data.get("colour", ""),
            size=c.size_to_order, qty=s.qty if only is None else 1, unit_price=c.price,
            url=c.data.get("url", ""), notes=notes))
    ordered = sorted(groups.values(), key=lambda g: STORE_ORDER.index(g.key) if g.key in STORE_ORDER else 99)
    total = w.total if only is None else round(sum(g.subtotal for g in ordered), 2)
    return ShoppingList(groups=ordered, owned=owned, missing=missing, total=total, budget=w.budget,
                        collected=w.collected, demo=w.source == "mock")


def _eur(value: float) -> str:
    return f"{value:,.0f} €" if abs(value - round(value)) < 0.005 else f"{value:,.2f} €"


def to_markdown(sl: ShoppingList) -> str:
    out = [f"# Shopping list — {date.today().strftime('%-d %B %Y')}", ""]
    if sl.demo:
        out += ["> DEMO DATA: these items are invented. Run `python -m wardrobe refresh` for real ones.", ""]
    left = f"{_eur(sl.remaining)} left" if sl.remaining >= 0 else f"{_eur(-sl.remaining)} over budget"
    out += [f"**{_eur(sl.total)}** for {sl.pieces} pieces · budget {_eur(sl.budget)} · {left}",
            f"Prices and stock as of {sl.collected}.", ""]
    for g in sl.groups:
        out += [f"## {g.label} — {g.pieces} pieces, {_eur(g.subtotal)}", ""]
        for line in g.lines:
            qty = f"{line.qty} × " if line.qty > 1 else ""
            colour = f", {line.colour}" if line.colour else ""
            out.append(f"- [ ] **{line.slot}** — {qty}{line.product}{colour} — size {line.size} — {_eur(line.total)}")
            out.append(f"  <{line.url}>")
            out += [f"  - {note}" for note in line.notes]
        out.append("")
    if sl.missing:
        out += ["## Still missing", ""] + [f"- {slot} — {why}" for slot, why in sl.missing] + [""]
    if sl.owned:
        out += ["## Already own", ""] + [f"- {name}" for name in sl.owned] + [""]
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
