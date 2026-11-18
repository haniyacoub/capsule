"""The wardrobe is the outfits the customer said yes to.

Outfits offers one outfit at a time. "Add to my wardrobe" is a yes: the outfit is stored (db.save_outfit, the table
that held the saved outfits) with which pieces of the plan it combines. "Not for me" is a no: that combination is
not offered again (db.decline_outfit). A piece is in his wardrobe when an outfit he said yes to wears it, when he
owns it, or when he kept it (selection.SlotView.mine); the Wardrobe page, the shopping list and the budget bar
count only those (selection.Wardrobe.mine).

A yes adds exactly what the outfit shows: one of each piece it wears, with the product and at the price shown. So
the outfit's own price, what the button says it adds, what the bar gains and "Buy this outfit" agree, at every
price level (selection.build picks a piece's product without looking at what he has said yes to). Where the plan
has a piece twice (two white tees), the second is a spare he may add himself on the piece's card (spare, below).

This module works out what follows from a yes before and after it is given:

    adds(w, outfit)       what the outfit would add: which pieces are new, what they cost, how many he has
                          already, and by how much it would take him over his budget
    leaving(w, sig)       taking an outfit out again: the pieces no other yes-outfit wears, which go with it
    offer(...)            the outfits to offer: none he answered, and those that reuse his pieces first
    name(pieces)          how a message names one outfit: by its two main pieces, never by its occasion alone
    title(label, occ)     the outfit's title as the page shows it over the outfit: "Office, smart casual"
    answered(...)         what the message after a yes or a no names the outfit by: its number in the row and its
                          title ("outfit 2 (Office, smart casual)") and its pieces, shown as small photos
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
        """Pieces to add: one of each new piece the outfit wears, as the bar will count them."""
        return len(self.new)

    @property
    def n_have(self) -> int:
        return len(self.have)

    @property
    def words(self) -> str:
        """'2 new pieces 208.99 €, 3 already in your wardrobe', the line under an outfit's price."""
        if self.in_wardrobe:
            return "In your wardrobe"
        n = len(self.new) + len(self.have)
        if not self.new:
            # The capsule's promise come true, said as such (review N6). (Short enough for one line of a phone's bar
            # over the tabs, app.css .dock.)
            return f"You can already wear this: {'its piece is' if n == 1 else f'all {n} pieces are'} yours"
        said = f"{self.n_new} new {pieces_word(self.n_new)} {eur(self.cost)}"
        if self.have:
            said += f", {self.n_have} already in your wardrobe"
        return said

    @property
    def all_yours(self) -> bool:
        """Every piece of it is in his wardrobe already, and he has not said yes to it: the yes saves it to My
        outfits ("Save to My outfits"), and there is no "Not for me" to say."""
        return not self.in_wardrobe and not self.new and bool(self.have)

    @property
    def over_short(self) -> str:
        """The same, in short, for the bar with the answers on a phone: '74.95 € over your budget'."""
        return f"{eur(self.over_by)} over your budget" if self.over_words else ""

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
    """'Charcoal wool coat', 'Charcoal wool coat and White tee', 'Charcoal wool coat, White tee and Indigo jeans'.
    A piece whose spare is in his wardrobe too says so: 'White tee with its spare'."""
    return names_of([view.slot["name"] + (f" with its {'spare' if view.n_spare == 1 else 'spares'}" if view.qty > 1 else "")
                     for view in views])


def names_of(words: list[str]) -> str:
    return ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else "".join(words)


def offer(w: Wardrobe, occasion: str, limit: int, seed: int,
          front: tuple[str, ...] | list[str] = ()) -> tuple[list[outfits.Outfit], int, int]:
    """The outfits to offer now: (a varied handful, how many there are to offer in all, how many he said no to).
    None he answered already, with a yes or a no. Those that wear pieces he already has come first, most first.
    A no leaves the others in their places (outfits.generate, `passed`). A yes changes what he has, and so the
    order: of the outfits behind the one he answered. Those that stood in front of it (`front`, their keys) stay
    where they were, so he goes on from where he was."""
    yes, no = set(db.yes_sigs()), db.declined_sigs()
    have = {view.slot["id"] for view in w.slots if view.mine}
    chosen, total = outfits.generate(w, occasion=occasion, limit=limit, seed=seed, skip=yes, have=have, passed=no,
                                     front=front)
    return chosen, total, len(no)


def name(pieces: list[dict] | None) -> str:
    """How a message names one outfit: by its two main pieces, 'outfit with the charcoal wool coat and indigo
    jeans' (the page puts "the" or "that" before it). The outermost thing worn on top and the trousers: what is
    seen of it first. Never its occasion alone: "Everyday" is also a filter's name, and that of dozens of outfits.
    `pieces`: the outfit's pieces as plain data, top to bottom (outfits.snapshot, or as a yes stored them)."""
    if not pieces:
        return "outfit"
    main = [pieces[0]] + [piece for piece in pieces[1:] if piece.get("layer") == "bottom"][:1]
    return "outfit with the " + " and ".join(str(piece.get("slot_name") or "").lower() for piece in main)


def spare(slot_id: str, added: bool) -> None:
    """Put the spare of a piece into the wardrobe, or take it out again (the setting "spares"): the further ones of
    a piece the plan has more than one of. An outfit wears one, and a yes adds that one (selection.SlotView.qty)."""
    now = [key for key in (db.get_setting("spares") or []) if key != slot_id]
    db.set_setting("spares", now + [slot_id] if added else now)


def keep(slot_id: str, kept: bool) -> None:
    """Put a piece into the wardrobe on its own account, or take it out of that again (the setting "kept_pieces")."""
    now = [key for key in (db.get_setting("kept_pieces") or []) if key != slot_id]
    db.set_setting("kept_pieces", now + [slot_id] if kept else now)


def owned_from_outside(slot_id: str) -> bool:
    """Whether he said he owns this piece while it was not in his wardrobe (the setting "owned_from_outside"): taking
    "Owned" back then returns it to where it was, outside his wardrobe (app.py, slot_own)."""
    return slot_id in (db.get_setting("owned_from_outside") or [])


def remember_outside(slot_id: str, outside: bool) -> None:
    now = [key for key in (db.get_setting("owned_from_outside") or []) if key != slot_id]
    db.set_setting("owned_from_outside", now + [slot_id] if outside else now)


def title(label: str, occasion: str) -> str:
    """An outfit's title as the page shows it over the outfit (outfits.html): its kind ("Smart casual"), and under
    the Everyday and Office filters the filter's name before it, "Office, smart casual"."""
    if label == "Smart casual" and occasion in ("everyday", "office"):
        return f"{outfits.OCCASIONS[occasion]}, smart casual"
    return label


def answered(label: str, occasion: str, pieces: list[dict], row: list[str], key: str) -> dict:
    """What the message after a yes or a no names the one outfit answered by, so that two outfits never read the
    same (review N2): its number in the row as he saw it and its title, "outfit 2 (Office, smart casual)" ("this
    outfit (Smart casual)" where it stood in no row: shown on its own after a swap), and every piece of it, as a row
    of small photos and, for a screen reader, by name. `row`: the keys of the outfits of the row before the answer,
    in order."""
    number = row.index(key) + 1 if key in row else 0
    return {"title": f"{f'outfit {number}' if number else 'this outfit'} ({title(label, occasion)})",
            "thumbs": [{"name": str(piece.get("shown_name") or piece.get("slot_name") or ""), "image_url": piece.get("image_url") or "",
                        "hex": piece.get("hex") or "#cccccc"} for piece in pieces]}
