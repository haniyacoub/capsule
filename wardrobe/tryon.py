"""Extension point for a future virtual try-on. Deliberately not built.

Not to be confused with the AI pictures of outfits, which are built (looks.py):
those are drawn from descriptions of the pieces, so the clothes in them are
close to the products, not the products themselves. A true try-on would put
the actual garments, from their product photos, on you. This is the hook for it.

How it would plug in:

  1. Write a class with the members of `TryOnProvider` below — for example one
     that runs an image model on this machine (the app's rule: nothing leaves
     your computer, no paid APIs).
  2. Assign an instance to `PROVIDER` at the bottom of this file.

That is all. A "Try on" button then appears on every outfit board, and the
`/outfits/tryon` route in app.py calls `render()` with the outfit's pieces and
shows the image it returns. Until then the button is hidden and the route
answers "not available".
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .paths import DATA_DIR

# Where a provider should expect the photo of you, and may write its results.
PERSON_PHOTO = DATA_DIR / "tryon" / "me.jpg"
OUTPUT_DIR = DATA_DIR / "tryon" / "renders"


class TryOnProvider(Protocol):
    name: str

    def render(self, person_photo: Path, garments: list[dict]) -> Path:
        """Return the path of an image of the person wearing the garments.

        `garments` has one dict per piece, top to bottom (outerwear, mid layer,
        top, trousers, shoes), each with: layer, category, name, colour_hex,
        image_url, url.
        """
        ...


PROVIDER: TryOnProvider | None = None


def available() -> bool:
    return PROVIDER is not None
