"""The garment types the app knows about. To add a type, add a row here and
give it price/brand/fabric entries in config/scoring.toml."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Garment:
    key: str
    label: str                   # shown in the UI
    plural: str                  # used in score explanations ("for coats")
    section: str                 # heading on the wardrobe page
    layer: str                   # outfit-board row: outer | mid | top | bottom | shoes
    size_group: str              # which of your sizes applies: tops | bottoms | shoes
    formality: tuple[int, int]   # 1 very casual … 5 formal: the range it works in


_ALL = [
    Garment("coat", "Coat", "coats", "Outerwear", "outer", "tops", (2, 5)),
    Garment("jacket", "Jacket", "jackets", "Outerwear", "outer", "tops", (1, 3)),
    Garment("blazer", "Blazer", "blazers", "Layers", "mid", "tops", (3, 5)),
    Garment("overshirt", "Overshirt", "overshirts", "Layers", "mid", "tops", (1, 3)),
    Garment("cardigan", "Cardigan", "cardigans", "Layers", "mid", "tops", (2, 4)),
    Garment("knit", "Jumper", "knitwear", "Knitwear", "top", "tops", (2, 5)),
    Garment("shirt", "Shirt", "shirts", "Shirts", "top", "tops", (2, 5)),
    Garment("polo", "Polo", "polos", "Shirts", "top", "tops", (2, 4)),
    Garment("tee", "T-shirt", "T-shirts", "T-shirts", "top", "tops", (1, 3)),
    Garment("longsleeve", "Long-sleeve tee", "long-sleeve tees", "T-shirts", "top", "tops", (1, 3)),
    Garment("trousers", "Trousers", "trousers", "Trousers", "bottom", "bottoms", (3, 5)),
    Garment("chinos", "Chinos", "chinos", "Trousers", "bottom", "bottoms", (2, 4)),
    Garment("jeans", "Jeans", "jeans", "Trousers", "bottom", "bottoms", (1, 3)),
    Garment("sneakers", "Sneakers", "sneakers", "Shoes", "shoes", "shoes", (1, 3)),
    Garment("shoes", "Leather shoes", "leather shoes", "Shoes", "shoes", "shoes", (3, 5)),
    Garment("boots", "Boots", "boots", "Shoes", "shoes", "shoes", (2, 4)),
]

GARMENTS: dict[str, Garment] = {g.key: g for g in _ALL}
SECTIONS: list[str] = list(dict.fromkeys(g.section for g in _ALL))

# Which mid layer can be worn over which top. A jumper counts as a mid layer
# only over a shirt (the collar shows); over a tee it is simply the top.
LAYER_OVER: dict[str, set[str]] = {
    "blazer": {"tee", "longsleeve", "shirt", "polo", "knit"},
    "overshirt": {"tee", "longsleeve", "polo"},
    "cardigan": {"tee", "longsleeve", "shirt", "polo"},
    "knit": {"shirt"},
}
