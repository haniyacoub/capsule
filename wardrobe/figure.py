"""The drawn figure on the Profile page: a man in plain underclothes, sketched in fine lines, who takes the height,
build, skin and hair chosen for the model the moment they are chosen.

It is drawn here, in Python, as the outlines (SVG paths) of a picture, so the page shows it without any script.
app.js (13b) redraws it while the choices change, from the outlines of every build and haircut that the page carries
along (see `data`). It is a drawing, not the AI picture: nothing is sent anywhere and nothing is billed.

How it is drawn: the figure stands 400 units tall at 180 cm, on the floor at y = 400, facing out, its middle at
x = 0 (y counts downwards, as in every SVG). Only its right half is written down (x ≥ 0): the left half is its mirror
image. Each outline is a few points joined by smooth curves; a build changes the widths (shoulders, chest, waist, hips,
arms and legs), never the number of points, so one build can be turned into another little by little.
"""
from __future__ import annotations

import re

from . import person

Point = tuple[float, float]

REFERENCE_CM = 180                     # the height at which the figure is 400 units tall
LOWEST_CM, HIGHEST_CM = 140, 220       # the heights the Profile form takes (profile.from_form)

# Every build as widths from the middle of the body, in units (a head is about 33 wide): the neck, the shoulders at
# their widest, the chest under the arms, the waist, the hips; `arm` and `leg` widen the limbs, `belly` rounds the
# middle. "Any" draws the average build.
BUILDS: dict[str, dict[str, float]] = {
    "slim":     {"neck": 6.8, "shoulder": 44.0, "chest": 30.5, "waist": 25.0, "hip": 28.5, "arm": 0.84, "leg": 0.86, "belly": 0},
    "athletic": {"neck": 8.0, "shoulder": 54.0, "chest": 37.5, "waist": 27.0, "hip": 31.0, "arm": 1.08, "leg": 1.03, "belly": 0},
    "average":  {"neck": 7.4, "shoulder": 48.5, "chest": 35.0, "waist": 30.0, "hip": 32.5, "arm": 1.00, "leg": 1.00, "belly": 0},
    "broad":    {"neck": 8.8, "shoulder": 56.0, "chest": 41.0, "waist": 35.0, "hip": 36.5, "arm": 1.18, "leg": 1.12, "belly": 0},
    "heavy":    {"neck": 9.2, "shoulder": 53.5, "chest": 43.0, "waist": 47.0, "hip": 42.0, "arm": 1.22, "leg": 1.22, "belly": 1},
}

# The heights in the model's menu (person.GROUPS "height"), drawn at these. "Any" draws the customer's own height.
HEIGHTS_CM = {"short": 168, "medium": 178, "tall": 190}

# Colours where nothing is chosen ("Any"): the paper of the drawing, so the figure is line only.
PAPER = "#f3f0eb"
CLOTH = "#dcd8d0"      # the underclothes: a light heather grey, the same for everyone


def _n(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") if abs(value) >= 0.05 else "0"


def _pt(p: Point) -> str:
    return f"{_n(p[0])} {_n(p[1])}"


def _smooth(points: list[Point]) -> str:
    """A smooth line from the first point through the others (Catmull-Rom, written as cubic Bézier curves)."""
    ends = [points[0], *points, points[-1]]
    parts = []
    for i in range(1, len(ends) - 2):
        p0, p1, p2, p3 = ends[i - 1], ends[i], ends[i + 1], ends[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        parts.append(f"C{_pt(c1)} {_pt(c2)} {_pt(p2)}")
    return " ".join(parts)


def _mirror(runs: list[list[Point]]) -> list[list[Point]]:
    """The left half of an outline: the right half's runs mirrored, walked the other way."""
    return [[(-x, y) for x, y in reversed(run)] for run in reversed(runs)]


def _closed(runs: list[list[Point]]) -> str:
    """One closed outline from the right half's runs (top to bottom) and their mirror image. Each run is smooth;
    where one run meets the next there is a corner (an armpit, a fingertip, a hem)."""
    every = runs + _mirror(runs)
    path = f"M{_pt(every[0][0])}"
    for run in every:
        if (round(run[0][0], 1), round(run[0][1], 1)) != _last(path):
            path += f" L{_pt(run[0])}"
        path += " " + _smooth(run)
    return path + " Z"


def _pair(runs: list[list[Point]]) -> str:
    """Two closed outlines: the right half's runs closed on themselves, and their mirror image (a beard's halves)."""
    def one(half: list[list[Point]]) -> str:
        path = f"M{_pt(half[0][0])}"
        for run in half:
            if (round(run[0][0], 1), round(run[0][1], 1)) != _last(path):
                path += f" L{_pt(run[0])}"
            path += " " + _smooth(run)
        return path + " Z"
    return one(runs) + " " + one([[(-x, y) for x, y in run] for run in runs])


def _last(path: str) -> tuple[float, float]:
    numbers = path.replace("M", " ").replace("C", " ").replace("L", " ").split()
    return round(float(numbers[-2]), 1), round(float(numbers[-1]), 1)


def _open(run: list[Point], mirrored: bool = True) -> str:
    """A line (not closed), and its mirror image on the other side."""
    path = f"M{_pt(run[0])} {_smooth(run)}"
    if mirrored:
        back = [(-x, y) for x, y in run]
        path += f" M{_pt(back[0])} {_smooth(back)}"
    return path


_PAIR = re.compile(r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)")


def _moved(path: str, x: float = 1.0, y_from_floor: float = 1.0, head: float = 1.0) -> str:
    """The same outline with every point moved: `head` shrinks it towards the top of the head (0, 0), and
    `y_from_floor` stretches it up from the floor (x is multiplied by `x` and `head`)."""
    def one(match: re.Match) -> str:
        px, py = float(match.group(1)) * x * head, float(match.group(2)) * head
        if y_from_floor != 1.0:
            py = 400 - (400 - py) * y_from_floor
        return f"{_n(px)} {_n(py)}"
    return _PAIR.sub(one, path)


# The head is drawn at its own size and shrunk to this: the figure is nine heads tall, like a fashion sketch, and
# the body below the chin is stretched up to meet it.
HEAD = 0.87
_BODY_UP = (400 - 38.5) / (400 - 44)


def _between(y: float, stops: list[Point]) -> float:
    """x at height y on a line through the stops (each (x, y), from top to bottom)."""
    for (x0, y0), (x1, y1) in zip(stops, stops[1:]):
        if y <= y1:
            return x0 + (x1 - x0) * (y - y0) / (y1 - y0)
    return stops[-1][0]


# ── the body, for one build ───────────────────────────────────────────────────

def body(build: str) -> dict[str, str]:
    """The outlines of the figure's body in one build: skin (the whole body), tee, briefs and the fine lines
    (hems, seams, knees). Every build gives outlines of the same shape of numbers, so app.js can blend them."""
    b = BUILDS.get(build, BUILDS["average"])
    nk, sh, ch, wa, hp, a, lg = b["neck"], b["shoulder"], b["chest"], b["waist"], b["hip"], b["arm"], b["leg"]

    # The arm hangs from the shoulder, a little away from the body, more so for wide builds so that it clears the
    # chest. Its middle line runs shoulder joint → elbow → wrist; its widths are measured across that line.
    spread = max(2.0, (ch + 2.5 + 9.2 * a - sh + 9) / 0.515 - 10)
    arm_line = [(sh - 9, 84.0), (sh + 1 + spread, 150.0), (sh + 8 + 2 * spread, 200.0)]

    def arm(y: float) -> float:
        return _between(y, arm_line)

    widths = {92: 10.5, 118: 9.2, 150: 7.4, 168: 8.0, 200: 5.2}      # half the arm's width at these heights
    wrist = arm(200)
    hand_out = [(wrist + 4.9 * a, 212.0), (wrist + 4.4 * a, 225.0)]
    tip = (wrist + 1.0, 236.0)
    hand_in = [(wrist - 3.0 * a, 232.5), (wrist - 4.9 * a, 220.0), (wrist - 4.8 * a, 207.0)]

    # The legs: hip joint → knee → ankle, the feet a little apart.
    leg_line = [(hp * 0.52, 196.0), (14.5, 300.0), (17.0, 384.0)]

    def leg(y: float) -> float:
        return _between(y, leg_line)

    def inner(x: float) -> float:
        return max(1.2, x)            # heavy thighs meet, they do not cross

    ankle = leg(384)
    belly = b["belly"]

    neck_and_arm = [(nk, 44.0), (nk + 0.3, 56.5), (nk + 9.5, 64.8), (sh - 10, 70.0), (sh - 2, 75.0),
                    (arm(92) + widths[92] * a, 92.0), (arm(118) + widths[118] * a, 118.0),
                    (arm(150) + widths[150] * a, 150.0), (arm(168) + widths[168] * a, 168.0),
                    (wrist + widths[200] * a, 200.0), *hand_out, tip]
    inner_arm = [tip, *hand_in, (wrist - widths[200] * a, 200.0), (arm(168) - widths[168] * a, 168.0),
                 (arm(150) - widths[150] * a, 150.0), (arm(118) - widths[118] * a, 118.0), (ch + 0.5, 101.0)]
    side_and_leg = [(ch + 0.5, 101.0), (ch - 0.6 + belly * 0.8, 114.0), (ch - 2.2 + (wa - ch + 2.2) * 0.45 + belly * 1.6, 130.0),
                    (wa + belly * 1.2, 150.0), (wa + (hp - wa) * 0.62, 172.0), (hp, 190.0), (hp - 1.2, 212.0),
                    (leg(240) + 15.5 * lg, 240.0), (leg(270) + 12.8 * lg, 270.0), (leg(300) + 9.8 * lg, 300.0),
                    (leg(326) + 11.0 * lg, 326.0), (leg(352) + 8.6 * lg, 352.0), (ankle + 5.6, 381.0),
                    (ankle + 6.9, 391.0), (ankle + 6.2, 398.6)]
    foot_and_inner_leg = [(ankle + 6.2, 398.6), (ankle + 2.6, 401.0), (ankle - 3.6, 400.8), (ankle - 6.4, 398.2),
                          (ankle - 5.4, 389.0), (ankle - 5.2, 379.0), (inner(leg(352) - 7.6 * lg), 352.0),
                          (inner(leg(326) - 9.4 * lg), 326.0), (inner(leg(300) - 8.6 * lg), 300.0),
                          (inner(leg(270) - 11.4 * lg), 270.0), (inner(leg(240) - 13.6 * lg), 240.0),
                          (inner(2.0), 214.0), (0.0, 206.0)]
    skin = _closed([neck_and_arm, inner_arm, side_and_leg, foot_and_inner_leg])

    # The tee: fitted, crew neck, short sleeves to the middle of the upper arm, the hem over the waistband.
    sleeve_out = (arm(117) + widths[118] * a + 1.7, 117.0)
    sleeve_in = (arm(118) - widths[118] * a - 1.5, 118.6)
    hem_y = 193.0
    tee = _closed([
        [(0.0, 66.5), (nk * 0.65, 64.6), (nk + 2.2, 59.0)],
        [(nk + 2.2, 59.0), (nk + 10, 64.4), (sh - 10, 69.6), (sh - 1.6, 74.6),
         (arm(92) + widths[92] * a + 0.9, 92.0), sleeve_out],
        [sleeve_out, ((sleeve_out[0] + sleeve_in[0]) / 2, 118.2), sleeve_in],
        [sleeve_in, (ch + 1.3, 102.0)],
        [(ch + 1.3, 102.0), (ch + 0.2 + belly * 1.0, 114.0), (ch - 1.8 + (wa - ch + 2.2) * 0.45 + belly * 1.8, 130.0),
         (wa + 1.6 + belly * 1.4, 150.0), (wa + (hp - wa) * 0.62 + 1.4, 172.0), (hp + 1.4, hem_y)],
        [(hp + 1.4, hem_y), (hp * 0.5, hem_y + 1.4), (0.0, hem_y + 1.6)],
    ])

    # Boxer briefs, from under the tee's hem to a hand's width down the thigh.
    opening = 223.0
    out_at, in_at = leg(opening) + 15.9 * lg + 0.9, inner(leg(opening + 5) - 13.9 * lg) - 0.5
    briefs = _closed([
        [(0.0, 186.0), (hp + 1.0, 186.0)],
        [(hp + 1.0, 186.0), (hp + 0.9, 198.0), (out_at, opening)],
        [(out_at, opening), ((out_at + in_at) / 2, opening + 3.6), (in_at, opening + 5.6)],
        [(in_at, opening + 5.6), (0.0, 213.0)],
    ])

    # The fine lines: the neck's rib, the sleeves' and the hems' stitching, the briefs' seam, the knees, the thumbs.
    lines = " ".join([
        _open([(nk + 2.0, 61.6), (nk * 0.65, 67.0), (0.0, 69.0)]),
        _open([(sleeve_out[0] - 0.4, 114.6), (sleeve_in[0] + 0.3, 116.2)]),
        _open([(hp + 1.2, hem_y - 2.4), (hp * 0.5, hem_y - 1.0), (0.0, hem_y - 0.8)]),
        _open([(out_at - 0.2, opening - 2.6), ((out_at + in_at) / 2, opening + 1.0), (in_at + 0.3, opening + 3.0)]),
        _open([(0.0, 197.0), (0.5, 204.0), (0.0, 211.0)], mirrored=False),
        _open([(leg(300) - 4.0, 296.5), (leg(300) - 0.4, 300.4), (leg(300) + 3.6, 296.8)]),
        _open([(wrist - 3.0, 212.0), (wrist - 1.4, 220.0), (wrist - 2.6, 228.0)]),
    ])
    return {name: _moved(path, y_from_floor=_BODY_UP)
            for name, path in (("skin", skin), ("tee", tee), ("briefs", briefs), ("lines", lines))}


# ── the head, hair and beard (the same for every build) ──────────────────────

def _face() -> str:
    return _head(_closed([[(0.0, 3.0), (9.6, 4.6), (15.2, 13.0), (16.0, 23.0), (15.4, 31.0), (13.2, 39.5),
                     (8.6, 46.6), (3.6, 50.2), (0.0, 51.0)]]))


def _head(path: str) -> str:
    return _moved(path, head=HEAD)


def _ears() -> str:
    right = "M15.4 24.6 C17.4 22.6 19.8 25.6 19.1 29.4 C18.6 32.4 17.2 34.4 15.2 33.6"
    left = "M-15.4 24.6 C-17.4 22.6 -19.8 25.6 -19.1 29.4 C-18.6 32.4 -17.2 34.4 -15.2 33.6"
    return _head(f"{right} Z {left} Z")


def _features() -> str:
    """A hint of a face, as a fashion sketch draws it: the brows, the line of the nose, the mouth."""
    return _head(" ".join([
        _open([(4.2, 22.4), (7.8, 21.4), (11.2, 22.4)]),
        "M0.6 26.8 C1.8 31 2.9 33.4 1.1 35.2",
        "M-3.8 41.2 C-1.4 42 1.4 42 3.8 41.2",
    ]))


def _wavy(points: list[Point], bump: float) -> list[Point]:
    """Every other point pushed out from the head's middle (0, 22): the outline of curls."""
    out = []
    for i, (x, y) in enumerate(points):
        if i % 2:
            dx, dy = x, y - 22
            length = max(1.0, (dx * dx + dy * dy) ** 0.5)
            out.append((x + dx / length * bump, y + dy / length * bump))
        else:
            out.append((x, y))
    return out


# Each haircut: the hair over the head ("front") and, for long hair, the part that falls behind the neck ("back").
# "Any" draws the short cut.
def _hair() -> dict[str, dict[str, str]]:
    curls = _wavy([(0.0, -5.0), (4.5, -4.8), (9.0, -3.6), (13.0, -1.0), (16.2, 2.6), (18.6, 7.0), (19.6, 12.0),
                   (19.8, 17.0), (18.8, 22.0)], 2.4)
    cuts = {
        "shaved": {"front": _closed([[(0.0, 2.0), (9.8, 3.4), (15.6, 11.6), (16.3, 19.8)],
                                     [(16.3, 19.8), (14.6, 13.2), (9.0, 9.8), (0.0, 9.4)]]), "back": ""},
        "short": {"front": _closed([[(0.0, -2.4), (6.4, -1.8), (12.8, 2.6), (16.4, 10.2), (16.7, 17.0), (16.0, 22.6)],
                                    [(16.0, 22.6), (14.9, 15.4), (11.0, 11.4), (5.0, 10.6), (0.0, 11.4)]]), "back": ""},
        "medium": {"front": _closed([[(0.0, -6.2), (8.2, -5.6), (15.4, -0.6), (18.6, 8.4), (18.9, 17.8), (17.6, 25.4)],
                                     [(17.6, 25.4), (16.2, 16.8), (12.6, 10.2), (6.0, 8.4), (0.0, 9.6)]]), "back": ""},
        # Parted in the middle, over the ears, to the shoulders; the rest falls behind the neck.
        "long": {"front": _closed([[(0.0, -3.4), (6.0, -5.6), (13.0, -2.8), (17.8, 4.6), (19.4, 15.0), (19.2, 26.0),
                                    (20.4, 36.0)],
                                   [(20.4, 36.0), (17.0, 33.6), (16.0, 24.0), (15.2, 16.0), (12.0, 10.6), (5.5, 7.8),
                                    (0.0, 6.4)]]),
                 "back": _closed([[(0.0, 8.0), (18.0, 10.0), (20.6, 26.0), (21.6, 42.0), (24.6, 58.0), (22.6, 63.0)],
                                  [(22.6, 63.0), (13.0, 61.0), (0.0, 60.0)]])},
        "curly": {"front": _closed([curls, [curls[-1], (16.6, 16.2), (13.2, 10.4), (6.4, 8.2), (0.0, 9.0)]]), "back": ""},
    }
    return {cut: {part: _head(path) for part, path in parts.items()} for cut, parts in cuts.items()}


def _beards() -> dict[str, str]:
    jaw = [(15.5, 25.6), (15.3, 32.0), (13.2, 39.8), (8.6, 46.8), (3.6, 50.4), (0.0, 51.2)]
    full_jaw = [(15.9, 23.6), (16.2, 32.0), (14.9, 42.0), (10.6, 51.4), (4.6, 56.6), (0.0, 57.6)]
    under_mouth = [(0.0, 44.0), (3.8, 43.4), (8.4, 41.0), (11.8, 36.4), (13.6, 30.6), (14.6, 26.6)]
    moustache = "M0 38.4 C3 37.4 5.6 38.2 6.6 40.6 C4.2 39.8 2.2 39.8 0 40.2 C-2.2 39.8 -4.2 39.8 -6.6 40.6 C-5.6 38.2 -3 37.4 0 38.4 Z"
    beard = _pair([jaw, [jaw[-1], under_mouth[0]], under_mouth])
    full = _pair([full_jaw, [full_jaw[-1], under_mouth[0]], under_mouth])
    kinds = {"stubble": f"{beard} {moustache}", "short": f"{beard} {moustache}", "full": f"{full} {moustache}"}
    return {"none": "", **{kind: _head(path) for kind, path in kinds.items()}}


# ── what the page needs ───────────────────────────────────────────────────────

def _choice(group: str, key: str | None) -> person.Choice | None:
    return next((o for o in person.GROUPS[group][1] if o.key == key), None)


def scale(model: dict[str, str], height_cm: int) -> float:
    """How much larger or smaller than at 180 cm the figure is drawn: the model's height where one is chosen,
    else the customer's own."""
    cm = HEIGHTS_CM.get(model.get("height", ""), height_cm)
    return max(LOWEST_CM, min(HIGHEST_CM, cm)) / REFERENCE_CM


def words(model: dict[str, str], height_cm: int) -> str:
    """The figure in words, under it (it is hidden from screen readers): "180 cm, athletic build, medium skin, short
    brown hair". What is left on "Any" is said as "any"."""
    cm = max(LOWEST_CM, min(HIGHEST_CM, height_cm))
    height = {"short": "short", "medium": "average height", "tall": "tall"}.get(model.get("height", ""), f"{cm} cm")
    build = _choice("build", model.get("build"))
    skin = _choice("skin", model.get("skin"))
    colour = _choice("hair", model.get("hair"))
    cut = _choice("cut", model.get("cut"))
    if cut and cut.key == "shaved":
        hair = "shaved head"
    elif cut or colour:
        named = [cut.label.lower() if cut else "", colour.label.lower().replace(" ", "-") if colour else ""]
        hair = " ".join(part for part in named if part) + " hair"
    else:
        hair = "any hair"
    beard = {"none": "clean-shaven", "stubble": "stubble", "short": "short beard", "full": "full beard"}.get(
        model.get("beard", ""), "")
    parts = [height, f"{build.label.lower()} build" if build else "any build",
             f"{skin.label.lower()} skin" if skin else "any skin tone", hair] + ([beard] if beard else [])
    said = ", ".join(parts)
    return said[0].upper() + said[1:]


def drawing(model: dict[str, str], height_cm: int) -> dict:
    """Everything the page draws for these choices (_figure.html)."""
    hair = _hair()[model.get("cut", "short") if model.get("cut") in _hair() else "short"]
    skin = _choice("skin", model.get("skin"))
    colour = _choice("hair", model.get("hair"))
    s = scale(model, height_cm)
    return {
        "body": body(model.get("build", "average")),
        "face": _face(), "ears": _ears(), "features": _features(),
        "hair": hair["front"], "hair_back": hair["back"],
        "beard": _beards().get(model.get("beard", ""), ""), "beard_kind": model.get("beard", ""),
        "shaved": model.get("cut") == "shaved",
        "skin": skin.swatch if skin else PAPER, "hair_colour": colour.swatch if colour else PAPER,
        "scale": s, "transform": transform(s), "words": words(model, height_cm),
        "cloth": CLOTH, 
    }


def transform(s: float) -> str:
    """The figure grows and shrinks from the floor: x stays in the middle, the soles stay on y = 400."""
    return f"matrix({s:.4f} 0 0 {s:.4f} 0 {400 * (1 - s):.2f})"


def ruler() -> list[tuple[float, bool]]:
    """Marks every 10 cm from 140 to 220 cm beside the figure: (y, whether it is a long mark at 150 and 200)."""
    return [(round(400 - cm * 400 / REFERENCE_CM, 1), cm % 50 == 0) for cm in range(LOWEST_CM, HIGHEST_CM + 1, 10)]


def data() -> dict:
    """What app.js needs to redraw the figure for any choice: every build's outlines, every haircut and beard, the
    colours and the words of every option, and the heights of the menu."""
    return {
        "builds": {key: body(key) for key in BUILDS},
        "hair": _hair(), "beards": _beards(), "heights": HEIGHTS_CM, "reference": REFERENCE_CM,
        "lowest": LOWEST_CM, "highest": HIGHEST_CM, "paper": PAPER,
        "skin": {o.key: {"colour": o.swatch, "label": o.label.lower()} for o in person.GROUPS["skin"][1]},
        "hairColour": {o.key: {"colour": o.swatch, "label": o.label.lower().replace(" ", "-")}
                       for o in person.GROUPS["hair"][1]},
        "build": {o.key: o.label.lower() for o in person.GROUPS["build"][1]},
        "cut": {o.key: o.label.lower() for o in person.GROUPS["cut"][1]},
    }
