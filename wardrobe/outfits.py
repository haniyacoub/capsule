"""Outfit combinations from the pieces currently selected.

An outfit is: optional outerwear, optional mid layer, a top, trousers and
(if the wardrobe has any) shoes. Every combination is checked against a few
plain rules — formality has to overlap, colours shouldn't fight — and scored.
The page then shows a varied handful rather than the top few lookalikes.

The rule numbers are constants below; change them to taste.
"""
from __future__ import annotations

import hashlib
import itertools
import random
from collections import Counter
from dataclasses import dataclass

from . import colours, style
from .garments import LAYER_OVER
from .selection import SlotView, Wardrobe

OCCASIONS = {"all": "All", "everyday": "Everyday", "office": "Office"}
SEP = "~"                 # joins the slot ids of an outfit into its address (slot ids never contain it)

MIN_SCORE = 60            # combinations scoring below this are not shown
CLOSE = 20                # lightness difference under which two colours read as "the same"

PENALTY_TWO_ACCENTS = 40          # more than one non-neutral colour family
PENALTY_TOP_MATCHES_BOTTOM = 35   # e.g. grey jumper with grey trousers
PENALTY_LOW_CONTRAST = 10         # different colours but equally dark/light top and bottom
PENALTY_MID_MATCHES_TOP = 20      # e.g. navy blazer over a navy tee
PENALTY_MID_MATCHES_BOTTOM = 30   # e.g. navy blazer with navy trousers: a broken suit
PENALTY_OUTER_MATCHES_INNER = 10
PENALTY_OUTER_MATCHES_BOTTOM = 5
PENALTY_BROWN_SHOES_BLACK_TROUSERS = 30
PENALTY_BLACK_SHOES_LIGHT_TROUSERS = 10
BONUS_LIGHT_UNDER_DARK = 5        # a light top under a dark layer
BONUS_REUSE = 10                  # per piece the customer already has in his wardrobe (generate)


@dataclass
class Piece:
    view: SlotView
    colour: colours.Colour
    hex: str

    @property
    def key(self) -> str:
        chosen = self.view.chosen
        return f"{self.view.slot['id']}:{chosen.id if chosen else 'owned'}"

    @property
    def category(self) -> str:
        return self.view.garment.key

    @property
    def layer(self) -> str:
        return self.view.garment.layer

    @property
    def owned(self) -> bool:
        return self.view.state == "owned"

    @property
    def price(self) -> float:
        return 0.0 if self.owned or not self.view.chosen else self.view.chosen.price

    @property
    def lightness(self) -> float:
        return colours.lightness(self.hex)


@dataclass
class Outfit:
    pieces: list[Piece]      # top to bottom: outerwear, mid layer, top, trousers, shoes
    score: float
    level: float             # 1 very casual … 5 formal

    @property
    def key(self) -> str:
        return hashlib.sha1("|".join(p.key for p in self.pieces).encode(), usedforsecurity=False).hexdigest()[:12]

    @property
    def slots(self) -> tuple[str, ...]:
        return tuple(p.view.slot["id"] for p in self.pieces)

    @property
    def sig(self) -> str:
        """Which slots are combined, top to bottom. Unlike `key` it stays the same when a
        slot's product is swapped, so it is how the pages point at "this outfit"."""
        return SEP.join(self.slots)

    @property
    def cost(self) -> float:
        return round(sum(p.price for p in self.pieces), 2)

    @property
    def label(self) -> str:
        return "Everyday" if self.level < 3 else "Office" if self.level > 3 else "Smart casual"

    def suits(self, occasion: str) -> bool:
        if occasion == "everyday":
            return self.level <= 3
        if occasion == "office":
            return self.level >= 3
        return True


def roles(layers: list[str]) -> list[str]:
    """What each piece is in an outfit, from its layers top to bottom: outer, mid, top, bottom or shoes.

    A jumper worn over a shirt is a "top" garment twice over; the first of the two is then the mid layer.
    """
    uppers = [i for i, layer in enumerate(layers) if layer in ("mid", "top")]
    last = uppers[-1] if uppers else -1
    return ["top" if i == last else "mid" if layer in ("mid", "top") else layer for i, layer in enumerate(layers)]


def snapshot(outfit: Outfit) -> list[dict]:
    """An outfit's pieces as plain data, top to bottom: what the page shows, what a favourite
    keeps, and what an AI picture is described from."""
    out = []
    parts = roles([p.layer for p in outfit.pieces])
    for p, role in zip(outfit.pieces, parts):
        chosen = None if p.owned else p.view.chosen
        data = chosen.data if chosen else {}
        out.append({
            "slot_id": p.view.slot["id"], "slot_name": p.view.slot["name"],
            "layer": p.layer, "role": role, "category": p.category, "owned": p.owned, "hex": p.hex,
            "cand_id": chosen.id if chosen else None,
            "name": data.get("name") or p.view.slot["name"],      # what the page shows
            "store_name": data.get("name") or "",                  # the store's own words, or nothing
            "store": data.get("store", ""), "price": p.price,
            "url": data.get("url", ""), "image_url": data.get("image_url", ""),
            # what the piece is like, for describing it: the store's own words
            "colour": data.get("colour") or "", "composition": data.get("composition_text") or "",
            "fit": data.get("fit") or "", "slug": data.get("slug") or "",
            "description": data.get("description") or "", "source": data.get("source") or "",
        })
    return out


def no_longer_offered(piece: dict) -> dict:
    """A saved outfit's piece from a store customers are no longer offered (programmes.py), as the Saved page shows
    it: the piece it filled, in its colour and at what it cost, without the store, its product, photo or link."""
    piece.update(gone=True, name=piece.get("slot_name") or "", store_name="", store="", image_url="", url="")
    return piece


def with_roles(pieces: list[dict]) -> list[dict]:
    """Fill in "role" on pieces saved before it existed."""
    for piece, role in zip(pieces, roles([p.get("layer", "") for p in pieces])):
        piece.setdefault("role", role)
    return pieces


def find(w: Wardrobe, key: str) -> Outfit | None:
    """The outfit with this fingerprint among today's valid combinations."""
    return next((o for o in all_outfits(w) if o.key == key), None)


def find_by_sig(w: Wardrobe, sig: str) -> Outfit | None:
    """The valid outfit that combines exactly these slots."""
    wanted = tuple(sig.split(SEP)) if sig else ()
    return next((o for o in all_outfits(w) if o.slots == wanted), None)


def alternatives(w: Wardrobe, outfit: Outfit, slot_id: str) -> tuple[list[tuple[Piece, str]], str | None]:
    """Changing one piece of an outfit: the other pieces of the wardrobe that can take its
    place (each with the address of the resulting outfit), and the address of the outfit
    without it, if it can be left off. Only combinations that pass the outfit rules count."""
    here = outfit.slots
    if slot_id not in here:
        return [], None
    i = here.index(slot_id)
    swaps: list[tuple[Piece, str]] = []
    without = None
    for other in all_outfits(w):
        there = other.slots
        if there == here[:i] + here[i + 1:]:
            without = other.sig
        elif len(there) == len(here) and there[i] != slot_id and there[:i] == here[:i] and there[i + 1:] == here[i + 1:]:
            swaps.append((other.pieces[i], other.sig))
    return swaps, without


def pieces_of(w: Wardrobe) -> list[Piece]:
    """One piece per filled slot: the chosen candidate, or the thing you own."""
    out = []
    for view in w.slots:
        if view.state == "owned":
            out.append(Piece(view, view.colour, view.colour.hex))
        elif view.chosen:
            key = colours.find(view.chosen.data.get("colour")) or view.slot["colour"]
            out.append(Piece(view, colours.get(key), view.chosen.colour_hex))
    return out


def _same(a: Piece, b: Piece) -> bool:
    """Same colour family and about equally light: reads as one colour."""
    return a.colour.family == b.colour.family and abs(a.lightness - b.lightness) < CLOSE


def evaluate(outer: Piece | None, mid: Piece | None, top: Piece, bottom: Piece,
             shoe: Piece | None) -> Outfit | None:
    worn = [p for p in (outer, mid, top, bottom, shoe) if p is not None]

    # Formality: every piece has a range it works in; the ranges must overlap.
    low = max(p.view.garment.formality[0] for p in worn)
    high = min(p.view.garment.formality[1] for p in worn)
    if low > high:
        return None

    score = 100.0
    if len({p.colour.family for p in worn if not p.colour.neutral}) > 1:
        score -= PENALTY_TWO_ACCENTS

    if _same(top, bottom):
        score -= PENALTY_TOP_MATCHES_BOTTOM
    elif top.colour.family != bottom.colour.family and abs(top.lightness - bottom.lightness) < 10:
        score -= PENALTY_LOW_CONTRAST

    if mid:
        if _same(mid, top):
            score -= PENALTY_MID_MATCHES_TOP
        elif top.lightness > 75 and mid.lightness < 40:
            score += BONUS_LIGHT_UNDER_DARK
        if _same(mid, bottom):
            score -= PENALTY_MID_MATCHES_BOTTOM
    if outer:
        if _same(outer, mid or top):
            score -= PENALTY_OUTER_MATCHES_INNER
        if _same(outer, bottom):
            score -= PENALTY_OUTER_MATCHES_BOTTOM
    if shoe:
        if shoe.colour.family == "brown" and bottom.colour.family == "black":
            score -= PENALTY_BROWN_SHOES_BLACK_TROUSERS
        if shoe.colour.family == "black" and bottom.colour.family == "beige":
            score -= PENALTY_BLACK_SHOES_LIGHT_TROUSERS

    if score < MIN_SCORE:
        return None
    return Outfit(pieces=worn, score=score, level=(low + high) / 2)


def all_outfits(w: Wardrobe) -> list[Outfit]:
    pieces = pieces_of(w)
    tops = [p for p in pieces if p.layer == "top"]
    bottoms = [p for p in pieces if p.layer == "bottom"]
    shoes: list[Piece | None] = [p for p in pieces if p.layer == "shoes"] or [None]
    outers: list[Piece | None] = [None] + [p for p in pieces if p.layer == "outer"]
    layers = [p for p in pieces if p.category in LAYER_OVER]

    found = []
    for top in tops:
        mids: list[Piece | None] = [None] + [
            m for m in layers if m is not top and top.category in LAYER_OVER[m.category]]
        for mid, bottom, shoe, outer in itertools.product(mids, bottoms, shoes, outers):
            outfit = evaluate(outer, mid, top, bottom, shoe)
            if outfit:
                found.append(outfit)
    return found


def generate(w: Wardrobe, occasion: str = "all", limit: int = 12, seed: int = 0,
             skip: frozenset[str] | set[str] = frozenset(),
             have: frozenset[str] | set[str] = frozenset(),
             passed: frozenset[str] | set[str] = frozenset(),
             front: tuple[str, ...] | list[str] = ()) -> tuple[list[Outfit], int]:
    """A varied selection of outfits, and how many valid combinations exist in total.

    `skip`: combinations (sigs) that are not offered: the ones he said yes to (yes.py); they are not counted.
    `have`: the pieces (slot ids) already in his wardrobe. An outfit that wears some of them is likelier to be
    among the selection, and the selection is put in order of how many it wears, most first: the outfits that cost
    him least come first.
    `passed`: combinations he said no to. They are not offered and not counted either, but each still takes its
    turn while the selection is made. So a no takes that one outfit out of the row and leaves every other where it
    was, in the same order (one more joins at the end): he goes on from where he was.
    `front`: the outfits (keys) that stood in front of the one he said yes to. They keep their places at the head
    of the row, and the rest of the selection follows in its order, most of his pieces first. So after a yes he
    goes on from where he was too, and the next outfit in line is the one that reuses most of what he now has.

    With a style brief (w.brief, style.py) the outfits that fit it are likelier to be among the selection and move up
    its order, those that are one of his styles as a whole furthest; without one the order is as it always was.
    Once he has pieces (`have`), the outfits that reuse most of them still come first, and the brief orders the
    outfits that reuse equally many."""
    pool = [o for o in all_outfits(w) if o.suits(occasion) and o.sig not in skip]
    total = sum(1 for o in pool if o.sig not in passed)
    rng = random.Random(seed)
    nudge = {o.key: rng.uniform(0, 8) for o in pool}   # "Shuffle" changes which near-ties win
    brief = getattr(w, "brief", None)
    fits = {o.key: style.outfit_bonus(snapshot(o), o.level, brief) for o in pool} if brief else {}

    used: Counter[str] = Counter()
    pairs: set[tuple[str, str]] = set()
    chosen: list[Outfit] = []

    def core(o: Outfit) -> tuple[str, str]:
        top = next(p for p in o.pieces if p.layer == "top")
        bottom = next(p for p in o.pieces if p.layer == "bottom")
        return top.key, bottom.key

    def appeal(o: Outfit) -> float:
        value = o.score + nudge[o.key] + fits.get(o.key, 0.0)
        value -= 7 * sum(used[p.key] for p in o.pieces)            # don't repeat the same pieces
        value += 6 * sum(1 for p in o.pieces if not used[p.key])   # give every piece an outing
        if core(o) in pairs:
            value -= 25                                            # same top + trousers again
        return value + BONUS_REUSE * reused(o)

    def reused(o: Outfit) -> int:
        return sum(1 for slot_id in o.slots if slot_id in have)

    def take(best: Outfit) -> None:
        pool.remove(best)
        if best.sig not in passed:
            chosen.append(best)
        pairs.add(core(best))
        for p in best.pieces:
            used[p.key] += 1

    by_key = {o.key: o for o in pool}
    for key in dict.fromkeys(front):            # those of them that are still outfits he could be offered
        if key in by_key and len(chosen) < limit:
            take(by_key[key])
    held = len(chosen)
    while pool and len(chosen) < limit:
        take(max(pool, key=appeal))
    if have:
        chosen[held:] = sorted(chosen[held:], key=lambda o: -reused(o))    # (a stable sort: equals keep the varied order)
    return chosen, total
