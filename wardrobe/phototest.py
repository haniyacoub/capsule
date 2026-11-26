"""The owner's test: does the model wear the real garments when their photographs go along?

    python -m wardrobe looks --test-photos FOLDER          (__main__.test_photos)

An outfit's picture is drawn from words alone (looks.prompt), so the model wears look-alikes of the products. This
draws ONE outfit both ways, to compare with your own eyes: once from the words, as the app draws today, and a few
times with a photograph of each garment sent along as a reference picture.

The photographs are of garments you own, taken by you. A store's product photos must not be sent this way without
the store's written permission: they are the store's, and the image service's terms ask whoever sends a picture
to hold the rights to it.

FOLDER is one outfit: one photograph per garment, each file named for what it is. The kind comes first, then its
colour and fabric, because the picture from words has nothing else to go on:

    coat charcoal wool.jpg       jumper navy merino.jpg       shirt white cotton.jpg
    trousers grey flannel.jpg    sneakers white leather.jpg

The kinds are the app's own (garments.py) under their everyday names (KINDS). A number in front ("2 jumper …") is
ignored: the pieces are put in order from the outermost layer down to the shoes, as in every outfit, and the
photographs are sent in that same order, so that "picture 2" is piece 2.

What is sent: each photograph made upright and resized, with nothing else of its file, so not where and when it
was taken (prepare). What is not used: any person's photo or build. The model is Stilsmith's house model, always.
Nothing is written to the database and nothing counts in the day's limits: the command is run by hand, asks before
it draws, and draws at most MOST_WITH_PHOTOS + 1 pictures a run. Each run's pictures, the photographs exactly as
they were sent, the words sent with them and a page to compare them on go into a new folder inside FOLDER.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess  # nosec B404  (runs macOS's sips only, with a fixed list of arguments: _sips)
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from . import colours, imagegen, looks, outfits, person
from .garments import GARMENTS

PHOTOS = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp")   # what a folder's photographs may be (see prepare)
LONGEST = 1536                  # pixels: the longer side of a photograph as it is sent
MAX_SENT = 2 * 1024 * 1024      # bytes: one photograph as it is sent, at most
MOST_PIECES = 6                 # garments in one outfit: a coat, three tops and layers, trousers and shoes (read)
MOST_WITH_PHOTOS = 9            # pictures drawn with the photographs in one run (plus the one from words)
WITH_PHOTOS = 3                 # … and how many as the command comes
SIPS_SECONDS = 60
# What each photograph sent along adds to a picture's price, in US dollars: Google counts 1,120 tokens for a
# picture that is sent, at $1.50 a million (its Cloud price list, read on 23 Nov 2026), so $0.0017. Rounded up.
PHOTO_IN_USD = Decimal("0.002")

# What the image service is told after the usual words (looks.prompt), when the photographs go along. {n}: how
# many. The usual words forbid logos anywhere in the picture: one on a garment's own photograph stays.
SAID_WITH_PHOTOS = (
    "The {n} pictures sent along are photographs of these exact pieces, one each, in the order of the list above: "
    "picture 1 shows piece 1, picture 2 shows piece 2, and so on. Dress the model in these very garments. "
    "Reproduce each one as its photograph shows it: its true colour, pattern, fabric texture, cut, collar or "
    "neckline, buttons, zips, pockets, seams and length, and any logo or print that is on the garment itself (the "
    "rule above against logos is for everything else in the picture). Take only the garment from each photograph: "
    "not its background, its shadows or its light, and no hanger, hand or person that may be in it. The garments "
    "are worn, not laid flat: they hang and fold naturally on his body.")

# The kind a file's name starts with -> the app's garment (garments.py). Longer names are tried first, so "polo
# shirt" is a polo and "long sleeve tee" a long-sleeve tee. Only the START of a name is read: "overshirt" holds
# "shirt", and a word further on ("shirt collar") says nothing about what the garment is.
_NAMES: dict[str, tuple[str, ...]] = {
    "coat": ("coat", "overcoat", "trench coat", "parka"),
    "jacket": ("jacket", "bomber jacket", "bomber"),
    "blazer": ("blazer", "sakko"),
    "overshirt": ("overshirt", "shacket"),
    "cardigan": ("cardigan",),
    "knit": ("jumper", "sweater", "pullover"),
    "hoodie": ("hoodie",),
    "shirt": ("shirt",),
    "polo": ("polo shirt", "polo"),
    "tee": ("t-shirt", "tshirt", "tee"),
    "longsleeve": ("long-sleeve tee", "long-sleeve", "longsleeve"),
    "trousers": ("trousers", "pants"),
    "chinos": ("chinos",),
    "jeans": ("jeans",),
    "cargo": ("cargo trousers", "cargo pants", "cargos"),
    "sneakers": ("sneakers", "trainers"),
    "shoes": ("leather shoes", "shoes", "loafers", "derby shoes", "derbies", "oxfords"),
    "boots": ("boots", "chelsea boots"),
}


def _plain(text: str) -> str:
    """A file's name as plain words: 'Long-Sleeve_Tee  white' -> 'long sleeve tee white'."""
    return " ".join(re.sub(r"[^a-z0-9äöüß]+", " ", text.lower()).split())


KINDS: dict[str, str] = {_plain(name): key for key, names in _NAMES.items() for name in names}
ORDER = list(GARMENTS)          # from the outermost layer down to the shoes, as garments.py lists them


class Unusable(Exception):
    """The folder, or a photograph in it, cannot be used. The words are for the person at the terminal."""


@dataclass(frozen=True)
class Photo:
    file: Path
    kind: str           # the garment: a key of GARMENTS
    words: str          # what it is, in his words: "navy merino jumper"


def kinds_said() -> str:
    """The kinds a file's name may start with, for the person at the terminal: one name each, as the app says it."""
    return ", ".join(names[0] for names in _NAMES.values())


def named(stem: str) -> tuple[str, str] | None:
    """What a file's name says the garment is: (the garment, his words for it), from the kind its name starts
    with. A number in front is passed over. None when it starts with no kind."""
    words = re.sub(r"^\d+ ", "", _plain(stem))
    for name in sorted(KINDS, key=len, reverse=True):
        if words == name or words.startswith(name + " "):
            rest = words[len(name):].strip()
            return KINDS[name], f"{rest} {name}".strip()
    return None


def read(folder: Path) -> tuple[list[Photo], list[str]]:
    """The outfit a folder holds: its photographs, from the outermost layer down to the shoes, and the names of
    the files in it that are no photographs (left alone, and said). Folders inside it and hidden files are passed
    over: the earlier runs' pictures are in folders of their own. Unusable when the folder is none, or what it
    holds is not one outfit."""
    if not folder.is_dir():
        raise Unusable(f"{folder} is not a folder.")
    files = sorted((f for f in folder.iterdir() if f.is_file() and not f.name.startswith(".")),
                   key=lambda f: f.name.lower())
    photos, skipped = [], []
    for file in files:
        if file.suffix.lower() not in PHOTOS:
            skipped.append(file.name)
            continue
        found = named(file.stem)
        if found is None:
            raise Unusable(f"“{file.name}” does not say what the garment is. Start its name with one of these, "
                           f"then its colour and fabric (like “jumper navy merino.jpg”): {kinds_said()}.")
        photos.append(Photo(file, *found))
    if not photos:
        raise Unusable(f"There are no photographs in {folder} (JPEG, PNG or an iPhone's HEIC).")
    if len(photos) > MOST_PIECES:
        raise Unusable(f"There are {len(photos)} photographs in {folder}: one outfit has {MOST_PIECES} pieces at "
                       "most. Put each outfit in a folder of its own.")
    photos.sort(key=lambda photo: (ORDER.index(photo.kind), photo.file.name.lower()))
    kinds = [photo.kind for photo in photos]
    twice = next((kind for kind in kinds if kinds.count(kind) > 1), None)
    if twice is not None:
        raise Unusable(f"{kinds.count(twice)} photographs in {folder} are “{GARMENTS[twice].label.lower()}”: one "
                       "outfit has one of a kind. Put each outfit in a folder of its own.")
    layers = [GARMENTS[photo.kind].layer for photo in photos]
    for layer, most, what in (("outer", 1, "coats or jackets"), ("bottom", 1, "pairs of trousers"),
                              ("shoes", 1, "pairs of shoes")):
        if layers.count(layer) > most:
            raise Unusable(f"There are {layers.count(layer)} {what} in {folder}: one outfit has one. Put each "
                           "outfit in a folder of its own.")
    uppers = layers.count("mid") + layers.count("top")
    if uppers > 3:
        raise Unusable(f"There are {uppers} tops and layers in {folder}: one outfit wears three at most.")
    if not uppers or "bottom" not in layers:
        missing, made_up = (("top (a shirt, a T-shirt, a jumper …)", "one") if not uppers else ("trousers", "some"))
        raise Unusable(f"The outfit in {folder} has no {missing}: the model would be drawn in {made_up} the service "
                       "makes up. Add a photograph.")
    return photos, skipped


def colourless(photos: list[Photo]) -> list[str]:
    """The files whose names say no colour: the picture from words alone has only the name to go on, so it would
    come out worse than the app's own, which knows each product's colour and fabric. Said before anything is drawn."""
    return [photo.file.name for photo in photos if colours.find(photo.words) is None]


def pieces(photos: list[Photo]) -> list[dict]:
    """The outfit as the pieces an AI picture is described from (outfits.snapshot): each garment, how it is worn
    over the others, its colour where his words name one, and his words as the name it is "sold as"."""
    out = []
    layers = [GARMENTS[photo.kind].layer for photo in photos]
    for photo, layer, role in zip(photos, layers, outfits.roles(layers)):
        key = colours.find(photo.words)
        colour = colours.get(key) if key else None
        out.append({"role": role, "layer": layer, "category": photo.kind, "owned": False,
                    "hex": colour.hex if colour else None, "colour": colour.label if colour else "",
                    "composition": "", "fit": "", "name": photo.words, "store_name": photo.words, "slug": "",
                    "description": "", "source": "collected", "slot_name": ""})
    return out


def listed(photos: list[Photo]) -> list[str]:
    """The pieces as the image service is told them, line by line (looks.prompt's own list): shown before anything
    is drawn, so that a colour or fabric read wrongly out of a file's name is seen while it costs nothing."""
    return looks._listed(outfits.with_roles(pieces(photos)))


def prompts(photos: list[Photo], rules: dict) -> tuple[str, str]:
    """What the image service is told: (for the picture from words alone, for a picture with the photographs sent
    along). The first is what the app sends for any outfit, of Stilsmith's house model; the second is the same
    words and, after them, what the photographs are (SAID_WITH_PHOTOS)."""
    words = looks.prompt(pieces(photos), rules, person.Who())
    return words, words + "\n\n" + SAID_WITH_PHOTOS.replace("{n}", str(len(photos)))


# ── a photograph as it is sent ────────────────────────────────────────────────

Convert = Callable[[Path, Path], None]      # (a photograph's file, where its upright, resized JPEG copy goes)


def converter() -> Convert | None:
    """What makes a photograph upright, LONGEST pixels on its longer side and a JPEG on this computer: macOS's own
    `sips`. None where there is none (anything but a Mac): photographs are then sent as they are, less everything
    but the picture."""
    tool = shutil.which("sips")
    if tool is None:
        return None
    return lambda photo, copy: _sips(tool, photo, copy)


def _sips(tool: str, photo: Path, copy: Path) -> None:
    # In two steps. First to BMP, a kind of file that cannot carry the note "turn me" a phone writes into a
    # photograph taken upright: sips then turns the picture itself. Straight to JPEG it keeps the note instead, and
    # with the note taken out (person.tidy) the garment would lie on its side. Then to JPEG. Tried on a Mac on
    # 26 Nov 2026: a JPEG with the note each of the four ways, and a HEIC that sips itself made from two of them,
    # came out upright every time. A file straight from a phone was not among them.
    with tempfile.TemporaryDirectory(prefix="stilsmith-photo-") as scratch:
        upright = Path(scratch) / "upright.bmp"
        to_bmp = [tool, "-s", "format", "bmp", "-Z", str(LONGEST), str(photo.resolve()), "--out", str(upright)]
        to_jpeg = [tool, "-s", "format", "jpeg", "-s", "formatOptions", "85", str(upright),
                   "--out", str(copy.resolve())]
        for command in (to_bmp, to_jpeg):
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=SIPS_SECONDS)  # nosec B603
            except (OSError, subprocess.SubprocessError):
                raise Unusable(f"“{photo.name}” could not be opened as a photograph.") from None


def prepare(photo: Path, convert: Convert | None) -> bytes:
    """One photograph as it goes to the image service: the picture alone, without anything else its file carries
    (where and when it was taken, the camera: person.tidy), and, where this computer can (`convert`: a Mac),
    upright, LONGEST pixels on its longer side and a JPEG, whatever kind of file it was."""
    if convert is None:
        data = photo.read_bytes()
    else:
        with tempfile.TemporaryDirectory(prefix="stilsmith-photo-") as scratch:
            copy = Path(scratch) / "photo.jpg"
            convert(photo, copy)
            data = copy.read_bytes() if copy.is_file() else b""
    tidy = person.tidy(data)
    if tidy is None:
        raise Unusable(f"“{photo.name}” is not a photograph this can use"
                       + (". Without a Mac's own converter it has to be a JPEG or PNG: save it as one first."
                          if convert is None else f": it has to be at least {person.MIN_SIDE} pixels a side."))
    picture, _ = tidy
    if len(picture) > MAX_SENT:
        raise Unusable(f"“{photo.name}” is too large to send ({len(picture) // 1024} KB; at most "
                       f"{MAX_SENT // 1024} KB). Make it smaller first.")
    return picture


# ── the price, the drawing, and the page to compare on ────────────────────────

def estimate(photos: int, with_photos: int, price: Decimal | None) -> Decimal | None:
    """About what a run costs, in US dollars: one picture from words and `with_photos` with the photographs, each
    at `price` (looks.price_each), and each photograph sent along with each of those (PHOTO_IN_USD). None while no
    price is set."""
    if price is None:
        return None
    return price * (with_photos + 1) + PHOTO_IN_USD * photos * with_photos


@dataclass
class Run:
    """What one run left: its folder, the pictures drawn (file, what it is), and what stopped it, if anything."""
    folder: Path
    drawn: list[tuple[Path, str]] = field(default_factory=list)
    problem: imagegen.DrawError | None = None


def folder_for(folder: Path, stamp: str | None = None) -> Path:
    """A new folder inside the outfit's for one run's files, named for when it started: a later run never writes
    over an earlier one's pictures."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    out, n = folder / f"pictures-{stamp}", 1
    while out.exists():
        n += 1
        out = folder / f"pictures-{stamp}-{n}"
    out.mkdir(parents=True)
    return out


def draw(photos: list[Photo], sent: list[bytes], with_photos: int, out: Path, service: imagegen.Service,
         rules: dict, report: Callable[[str], None] = lambda line: None) -> Run:
    """Draw the outfit into `out`: once from the words alone, then `with_photos` times with the photographs sent
    along (`sent`: each as prepare made it, in the order of `photos`). One picture is billed for each; none is
    tried twice, and the first that fails stops the run (Run.problem). Beside the pictures go the photographs
    exactly as they were sent, the words sent, and compare.html, whatever happened. `report` is told each picture
    as it is written."""
    words, with_them = prompts(photos, rules)
    sent_as = []
    for number, (photo, picture) in enumerate(zip(photos, sent), 1):
        name = f"sent-{number}-{photo.kind}.{imagegen.kind_of(picture) or 'jpg'}"
        (out / name).write_bytes(picture)
        sent_as.append(name)
    (out / "words-alone.txt").write_text(words + "\n", encoding="utf-8")
    (out / "words-with-photos.txt").write_text(with_them + "\n", encoding="utf-8")
    run = Run(out)
    wanted: list[tuple[str, str, str, list[bytes]]] = [
        ("from-words", "From the words alone, as the app draws today", words, [])]
    wanted += [(f"with-photos-{n}", f"With your photographs sent along ({n} of {with_photos})", with_them, sent)
               for n in range(1, with_photos + 1)]
    for name, what, prompt, references in wanted:
        started = time.time()
        try:
            data, ext = imagegen.draw(service, prompt, references=references)
        except imagegen.DrawError as problem:
            run.problem = problem
            break
        path = out / f"{name}.{ext}"
        path.write_bytes(data)
        run.drawn.append((path, what))
        report(f"{path}  ({time.time() - started:.0f} seconds)")
    (out / "compare.html").write_text(page(photos, sent_as, run), encoding="utf-8")
    return run


def page(photos: list[Photo], sent_as: list[str], run: Run) -> str:
    """compare.html: the photographs as they were sent, each with what it was read as, and under them the pictures
    side by side, the one from words first. A plain page, opened from the folder: no script, nothing from outside."""
    def figure(file: str, caption: str, cls: str = "") -> str:
        return (f'<figure{cls}><a href="{quote(file)}"><img src="{quote(file)}" alt="{html.escape(caption)}" '
                f'loading="lazy"></a><figcaption>{html.escape(caption)}</figcaption></figure>')

    sent = "".join(figure(file, f"{number}. {GARMENTS[photo.kind].label}: {photo.words}", ' class="small"')
                   for number, (photo, file) in enumerate(zip(photos, sent_as), 1))
    drawn = "".join(figure(path.name, what) for path, what in run.drawn) or "<p>No picture was drawn.</p>"
    stopped = ""
    if run.problem is not None:
        stopped = ("<p class=\"stopped\">The run stopped before all pictures were drawn: "
                   f"{html.escape(looks.SAY.get(run.problem.kind, looks.SAY['unknown']))}</p>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Photo test: {html.escape(run.folder.parent.name)}</title>
<style>
  body {{ font: 16px/1.5 -apple-system, "Segoe UI", sans-serif; margin: 0 auto; padding: 24px 16px 48px;
         max-width: 1400px; background: #f6f5f2; color: #1c1b19; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}  h2 {{ font-size: 17px; margin: 32px 0 12px; }}
  p {{ margin: 0 0 12px; max-width: 70ch; }}  .stopped {{ color: #a12a12; }}
  .row {{ display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }}
  figure {{ margin: 0; width: 300px; max-width: 100%; }}  figure.small {{ width: 170px; }}
  img {{ display: block; width: 100%; height: auto; border-radius: 4px; background: #fff; }}
  figcaption {{ font-size: 14px; margin-top: 6px; }}
  @media (prefers-color-scheme: dark) {{ body {{ background: #171614; color: #ecebe7; }} img {{ background: #222; }}
                                         .stopped {{ color: #ff9c8a; }} }}
</style></head><body>
<h1>Photo test: {html.escape(run.folder.parent.name)}</h1>
<p>One outfit on Stilsmith's house model, drawn by AI: first from the words alone, then with your photographs sent
along. Compare each garment's colour, pattern, collar, buttons, pockets and length with the real one. A picture
opens full size when you click it.</p>
<h2>Your photographs, as they were sent</h2>
<div class="row">{sent}</div>
<h2>The pictures</h2>
{stopped}<div class="row">{drawn}</div>
<p style="margin-top:32px">The words that were sent are beside this page: words-alone.txt and
words-with-photos.txt.</p>
</body></html>
"""
