"""Quality score, 0-100, with the working shown.

All numbers come from config/scoring.toml. This file only does the arithmetic
and writes down, line by line, how each number came about. Those lines are what
a customer reads under "How it's rated" on a piece's page, so they are in his
words: a price is "in the usual range", and the brand part says plainly that the
rating is Stilsmith's own.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import composition, config
from .garments import GARMENTS
from . import settings

STORE_LABELS = {"cos": "COS", "weekday": "Weekday", "zara": "Zara"}


@dataclass
class Part:
    key: str
    label: str
    score: float           # 0-100
    weight: float          # 0-1, after rescaling
    lines: list[str] = field(default_factory=list)

    @property
    def points(self) -> float:
        return self.score * self.weight


@dataclass
class Score:
    total: int
    parts: list[Part]
    comp: list[tuple[str, float]] = field(default_factory=list)   # the fibres the score used
    fabric_source: str = "listed"   # listed | name (estimated) | assumed | none

    @property
    def band(self) -> str:
        return "good" if self.total >= 75 else "ok" if self.total >= 55 else "poor"

    @property
    def note(self) -> str:
        """The line under every breakdown: which part counts most (from the weights, so it stays true when they
        change), and that the brand part is Stilsmith's own judgement, not a fact from the store."""
        weights = sorted((p.weight for p in self.parts), reverse=True)
        most = next(p for p in self.parts if p.weight == weights[0])
        first = f"{most.label} counts most. " if len(weights) < 2 or weights[0] > weights[1] else ""
        return first + (f"The brand part is {settings.SITE_NAME}'s own judgement of how well each store makes this "
                        "kind of garment.")

    @property
    def fabric_text(self) -> str:
        """'80% wool · 20% polyamide', marked with ≈ when it is not the store's own figure."""
        if not self.comp:
            return "fabric not listed"
        text = composition.describe(self.comp)
        return text if self.fabric_source == "listed" else "≈ " + text


def _check(rules: dict) -> None:
    """Catch values that are valid TOML but would give nonsense scores."""
    number, table = config.number, config.table

    weights = table(rules.get("weights", {}), "weights")
    if sum(max(0.0, number(v, f"weights.{k}")) for k, v in weights.items()) <= 0:
        raise config.ConfigError("[weights] needs at least one weight above zero")

    fabric = table(rules.get("fabric", {}), "fabric")
    for fibre, value in table(fabric.get("fibres", {}), "fabric.fibres").items():
        number(value, f"fabric.fibres.{fibre}")
    for category, fibres in table(fabric.get("by_category", {}), "fabric.by_category").items():
        for fibre, value in table(fibres, f"fabric.by_category.{category}").items():
            number(value, f"fabric.by_category.{category}.{fibre}")
    adjustments = table(fabric.get("adjustments", {}), "fabric.adjustments")
    for key in ("mostly_synthetic_above", "mostly_synthetic_penalty", "wool_rich_from",
                "wool_rich_bonus", "unknown_composition"):
        if key in adjustments:
            number(adjustments[key], f"fabric.adjustments.{key}")
    guess = table(fabric.get("name_guess", {}), "fabric.name_guess")
    for key in ("pure_share", "plain_share", "blend_share", "trace_share", "penalty"):
        if key in guess:
            number(guess[key], f"fabric.name_guess.{key}")
    for category, text in table(fabric.get("assume_when_unknown", {}), "fabric.assume_when_unknown").items():
        if not composition.parse(text if isinstance(text, str) else ""):
            raise config.ConfigError(
                f'fabric.assume_when_unknown.{category} must be a composition like "98 % Baumwolle, 2 % Elasthan"')

    for store, tiers in table(rules.get("brand", {}), "brand").items():
        for category, value in table(tiers, f"brand.{store}").items():
            number(value, f"brand.{store}.{category}")

    price = table(rules.get("price", {}), "price")
    for key in ("score_when_suspicious", "score_when_steep"):
        if key in price:
            number(price[key], f"price.{key}")
    for category, band in table(price.get("bands", {}), "price.bands").items():
        where = f"price.bands.{category}"
        band = table(band, where)
        fair = band.get("fair")
        if not isinstance(fair, list) or len(fair) != 2:
            raise config.ConfigError(f"{where}.fair must be two numbers, like [12, 40]")
        points = [number(band.get("suspicious_below"), f"{where}.suspicious_below"),
                  number(fair[0], f"{where}.fair"), number(fair[1], f"{where}.fair"),
                  number(band.get("steep_above"), f"{where}.steep_above")]
        if points != sorted(points):
            raise config.ConfigError(
                f"[{where}] must rise in order: suspicious_below ≤ fair low ≤ fair high ≤ steep_above")


def load_rules() -> dict:
    return config.load("scoring.toml", _check)


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def _num(x: float) -> str:
    return f"{x:.0f}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"


def _eur(x: float) -> str:
    """'89.95 €', with a space that never breaks: on a phone '130' and '€' stay on one line."""
    return f"{x:,.0f}\u00a0€" if float(x).is_integer() else f"{x:,.2f}\u00a0€"


def fabric_part(comp: list[tuple[str, float]], category: str, rules: dict) -> tuple[float, list[str]]:
    fab = rules.get("fabric", {})
    adj = fab.get("adjustments", {})
    plural = GARMENTS[category].plural if category in GARMENTS else category

    if not comp:
        score = float(adj.get("unknown_composition", 45))
        return score, [f"No composition listed by the store → neutral {_num(score)}"]

    base = fab.get("fibres", {})
    by_cat = fab.get("by_category", {}).get(category, {})
    total_pct = sum(pct for _, pct in comp) or 1.0
    lines: list[str] = []
    avg = 0.0
    for fibre, pct in comp:
        if fibre in by_cat:
            value, source = float(by_cat[fibre]), f" (rule for {plural})"
        else:
            value, source = float(base.get(fibre, base.get("other", 45))), ""
        avg += value * pct / total_pct
        lines.append(f"{pct:g}% {composition.label(fibre)} → {_num(value)}{source}")
    if len(comp) > 1:
        lines.append(f"Blend average: {_num(avg)}")
    score = avg

    synthetic = sum(pct for f, pct in comp if f in adj.get("synthetic_fibres", [])) / total_pct * 100
    limit = adj.get("mostly_synthetic_above", 50)
    penalty = adj.get("mostly_synthetic_penalty", 0)
    if penalty and synthetic > limit and category not in adj.get("mostly_synthetic_exempt", []):
        score -= penalty
        lines.append(f"−{_num(penalty)} mostly synthetic ({_num(synthetic)}% is over {_num(limit)}%)")

    wool = sum(pct for f, pct in comp if f in adj.get("wool_fibres", [])) / total_pct * 100
    wool_from = adj.get("wool_rich_from", 50)
    bonus = adj.get("wool_rich_bonus", 0)
    if bonus and wool >= wool_from and category in adj.get("wool_rich_categories", []):
        score += bonus
        lines.append(f"+{_num(bonus)} wool-rich ({_num(wool)}% wool-type fibres)")

    return _clamp(score), lines


def price_part(price: float, category: str, rules: dict) -> tuple[float, list[str]]:
    cfg = rules.get("price", {})
    band = cfg.get("bands", {}).get(category)
    plural = GARMENTS[category].plural if category in GARMENTS else category
    if not band:
        return 70.0, [f"{settings.SITE_NAME} has no usual price range for {plural} yet → neutral 70"]

    low_score = float(cfg.get("score_when_suspicious", 40))
    high_score = float(cfg.get("score_when_steep", 55))
    cheap = float(band["suspicious_below"])
    fair_lo, fair_hi = (float(x) for x in band["fair"])
    steep = float(band["steep_above"])
    fair = f"{_eur(fair_lo)}–{_eur(fair_hi)}"

    # A low price counts against an option because it often means lower quality: said so, not hinted at.
    if fair_lo <= price <= fair_hi:
        return 100.0, [f"{_eur(price)} is in the usual range for {plural} ({fair})"]
    if price < fair_lo:
        if price <= cheap:
            return low_score, [f"{_eur(price)} is far below the usual {fair} for {plural}. Prices this low often "
                               f"mean lower quality, so this counts against it."]
        score = low_score + (price - cheap) / (fair_lo - cheap) * (100 - low_score)
        return score, [f"{_eur(price)} is below the usual {fair} for {plural}. Prices this low often mean lower "
                       f"quality, so this counts a little against it."]
    if price >= steep:
        return high_score, [f"{_eur(price)} is far above the usual {fair} for {plural}, so this counts against it."]
    score = 100 - (price - fair_hi) / (steep - fair_hi) * (100 - high_score)
    return score, [f"{_eur(price)} is above the usual {fair} for {plural}, so this counts a little against it."]


def brand_part(store: str, category: str, rules: dict) -> tuple[float, list[str]]:
    tiers = rules.get("brand", {}).get(store, {})
    plural = GARMENTS[category].plural if category in GARMENTS else category
    name = STORE_LABELS.get(store, store)
    # Stilsmith's own judgement of the store, and said to be: "Zara is rated 52" hid who rates it.
    if category in tiers:
        value = float(tiers[category])
        return value, [f"{settings.SITE_NAME} rates {name} {_num(value)}/100 for {plural}"]
    value = float(tiers.get("default", 50))
    return value, [f"{settings.SITE_NAME} rates {name} {_num(value)}/100 for {plural} "
                   f"(its rating for {name} in general)"]


def score(candidate: dict, category: str, rules: dict | None = None) -> Score:
    rules = rules or load_rules()
    weights = rules.get("weights", {})
    w = {k: max(0.0, float(weights.get(k, 0))) for k in ("fabric", "brand", "price")}
    w_total = sum(w.values()) or 1.0

    # Fabric: the store's own composition if we have it; otherwise a labelled guess.
    fab = rules.get("fabric", {})
    comp = composition.parse(candidate.get("composition_text"))
    source, preface = "listed", ""
    if not comp:
        guess_rules = fab.get("name_guess", {})
        if guess_rules.get("enabled", True):
            words = f"{candidate.get('name', '')} {candidate.get('slug', '')}"
            comp, how = composition.guess(words, guess_rules)
            if comp:
                source = "name"
                preface = f"The store page gave no composition — estimated from the name ({how})"
        if not comp:
            typical = fab.get("assume_when_unknown", {}).get(category)
            comp = composition.parse(typical) if typical else []
            if comp:
                source = "assumed"
                plural = GARMENTS[category].plural if category in GARMENTS else category
                preface = f"The store page gave no composition — assumed what is typical for {plural}"
        if not comp:
            source = "none"
    f_score, f_lines = fabric_part(comp, category, rules)
    if preface:
        penalty = float(fab.get("name_guess", {}).get("penalty", 0))
        f_lines.insert(0, preface)
        if penalty:
            f_score = _clamp(f_score - penalty)
            f_lines.append(f"−{_num(penalty)} because this is an estimate, not the label")
    b_score, b_lines = brand_part(candidate.get("store", ""), category, rules)
    p_score, p_lines = price_part(float(candidate.get("price") or 0), category, rules)

    parts = [
        Part("fabric", "Fabric", f_score, w["fabric"] / w_total, f_lines),
        Part("brand", "Brand", b_score, w["brand"] / w_total, b_lines),
        Part("price", "Price", p_score, w["price"] / w_total, p_lines),
    ]
    total = sum(p.points for p in parts)
    return Score(total=int(_clamp(total) + 0.5), parts=parts, comp=comp, fabric_source=source)
