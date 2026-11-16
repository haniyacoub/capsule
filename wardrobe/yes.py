"""The wardrobe is the outfits the customer said yes to.

Outfits offers one outfit at a time. "Add to my wardrobe" is a yes: the outfit is stored (db.save_outfit, the table
that held the saved outfits) with which pieces of the plan it combines. "Not for me" is a no: that combination is
not offered again (db.decline_outfit). A piece is in his wardrobe when an outfit he said yes to wears it, when he
owns it, or when he kept it (selection.SlotView.mine); the Wardrobe page, the shopping list and the budget bar
count only those (selection.Wardrobe.mine).

This module works out what follows from a yes before and after it is given:

    adds(w, outfit)       what the outfit would add: which pieces are new, what they cost, how many he has
                          already, and by how much it would take him over his budget
    leaving(w, sig)       taking an outfit out again: the pieces no other yes-outfit wears, which go with it
    offer(...)            the outfits to offer: none he answered, and those that reuse his pieces first
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import db, outfits
from .selection import SlotView, Wardrobe


def eur(value: float) -> str:
    value = float(value or 0)
    text = f"{value:,.0f}" if abs(value - round(value)) < 0.005 else f"{value:,.2f}"
    return f"{text}\u00a0€"       # (a no-break space, as on every page: the sign never starts a line)


def pieces_word(n: int) -> str:
    return "piece" if n == 1 else "pieces"


@dataclass
class Adds:
    """What saying yes to one outfit would do to the wardrobe."""
    new: list[SlotView] = field(default_factory=list)       # pieces that are not in his wardrobe yet
    have: list[SlotView] = field(default_factory=list)      # pieces that are: in another outfit of his, owned, kept
    cost: float = 0.0            # what the new pieces add to the wardrobe's total
    total_after: float = 0.0     # the wardrobe's total with them
    over_by: float = 0.0         # how far that is over his budget, or 0 (also while he has given no budget)
    in_wardrobe: bool = False    # he already said yes to this outfit

    @property
    def n_new(self) -> int:
        """Pieces to add, counted as the bar counts them: a white tee the plan wants twice is two."""
        return sum(view.qty for view in self.new)

    @property
    def n_have(self) -> int:
        return len(self.have)

    @property
    def twice(self) -> str:
        """'2 × White tee' for new pieces the plan wants more than one of, so the count and the sum can be checked
        against the outfit's own price, which is for one of each."""
        return ", ".join(f"{view.qty} × {view.slot['name']}" for view in self.new if view.qty > 1)

    @property
    def words(self) -> str:
        """'2 new pieces 208.99 €, 3 already in your wardrobe', the line under an outfit's price."""
        if self.in_wardrobe:
            return "In your wardrobe"
        n = len(self.new) + len(self.have)
        if not self.new:
            return (f"Nothing new to buy: {'the piece is' if n == 1 else f'all {n} pieces are'} "
                    "already in your wardrobe")
        said = f"{self.n_new} new {pieces_word(self.n_new)} {eur(self.cost)}"
        if self.twice:
            said += f" ({self.twice})"
        if self.have:
            said += f", {self.n_have} already in your wardrobe"
        return said

    @property
    def over_words(self) -> str:
        """Said before he says yes, when the outfit would take the wardrobe over his budget."""
        if self.in_wardrobe or self.over_by <= 0 or self.cost <= 0:
            return ""
        return f"With it your wardrobe comes to {eur(self.total_after)}: {eur(self.over_by)} over your budget."


def adds(w: Wardrobe, outfit: outfits.Outfit, yes: set[str] | None = None) -> Adds:
    """What this outfit would add to the wardrobe `w` was built for. `yes`: the outfits he said yes to (their
    sigs), when the caller has them already."""
    yes = set(db.yes_sigs()) if yes is None else yes
    out = Adds(in_wardrobe=outfit.sig in yes)
    for piece in outfit.pieces:
        (out.have if piece.view.mine else out.new).append(piece.view)
    out.cost = round(sum(view.cost for view in out.new), 2)
    out.total_after = round(w.mine.total + out.cost, 2)
    if w.budget_known and out.total_after > w.budget:
        out.over_by = round(out.total_after - w.budget, 2)
    return out


def leaving(w: Wardrobe, sig: str) -> list[SlotView]:
    """The pieces that leave the wardrobe when the outfit that combines `sig` is taken out: those no other outfit
    of his wears. A piece he owns or kept stays in any case. (Before the outfit is taken out.)"""
    out = []
    for slot_id in dict.fromkeys(sig.split(outfits.SEP)):
        view = w.get(slot_id)
        if view is not None and view.outfits_in == 1 and view.state != "owned" and not view.kept:
            out.append(view)
    return out


def names(views: list[SlotView]) -> str:
    """'Charcoal wool coat', 'Charcoal wool coat and White tee', 'Charcoal wool coat, White tee and Indigo jeans'."""
    words = [view.slot["name"] for view in views]
    return ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else "".join(words)


def offer(w: Wardrobe, occasion: str, limit: int, seed: int) -> tuple[list[outfits.Outfit], int, int]:
    """The outfits to offer now: (a varied handful, how many there are to offer in all, how many he said no to).
    None he answered already, with a yes or a no. Those that wear pieces he already has come first, most first."""
    yes, no = set(db.yes_sigs()), db.declined_sigs()
    have = {view.slot["id"] for view in w.slots if view.mine}
    chosen, total = outfits.generate(w, occasion=occasion, limit=limit, seed=seed, skip=yes | no, have=have)
    return chosen, total, len(no)


def keep(slot_id: str, kept: bool) -> None:
    """Put a piece into the wardrobe on its own account, or take it out of that again (the setting "kept_pieces")."""
    now = [key for key in (db.get_setting("kept_pieces") or []) if key != slot_id]
    db.set_setting("kept_pieces", now + [slot_id] if kept else now)
