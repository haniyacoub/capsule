"""Stand-in product pictures for the demo data: a flat garment silhouette in
the item's colour, drawn as SVG. Only used while the catalogue is mock data —
real collected items carry the store's own image URL."""
from __future__ import annotations

from .colours import is_hex, lightness, shade

_BACKDROP = "#e7e5df"
_SOLE_LIGHT = "#f3f1eb"
_SOLE_DARK = "#2b2725"

# Garment outlines on a 300 × 400 canvas.
_TEE = ("M128 70 L88 86 L42 148 L70 172 L98 142 L98 335 L202 335 L202 142 "
        "L230 172 L258 148 L212 86 L172 70 Q150 96 128 70 Z")
_LONG = ("M128 70 L88 86 L50 318 L80 324 L100 150 L100 338 L200 338 L200 150 "
         "L220 324 L250 318 L212 86 L172 70 Q150 92 128 70 Z")
_SHIRT = ("M128 66 L88 84 L50 318 L80 324 L100 150 L100 332 Q150 350 200 332 L200 150 "
          "L220 324 L250 318 L212 84 L172 66 L150 90 Z")
_OVERSHIRT = ("M128 66 L86 84 L48 318 L80 324 L98 150 L98 338 L202 338 L202 150 "
              "L220 324 L252 318 L214 84 L172 66 L150 90 Z")
_CARDIGAN = ("M128 68 L88 86 L50 318 L80 324 L100 150 L100 338 L200 338 L200 150 "
             "L220 324 L250 318 L212 86 L172 68 L150 178 Z")
_BLAZER = ("M126 62 L86 80 L52 310 L82 316 L100 150 L98 345 L202 345 L200 150 "
           "L218 316 L248 310 L214 80 L174 62 L150 172 Z")
_COAT = ("M126 46 L84 64 L50 286 L80 292 L98 136 L92 388 L208 388 L202 136 "
         "L220 292 L250 286 L216 64 L174 46 L150 160 Z")
_JACKET = ("M128 64 L88 82 L50 300 L82 308 L100 148 L100 320 L200 320 L200 148 "
           "L218 308 L250 300 L212 82 L172 64 Q150 80 128 64 Z")
_LEGS = "M104 30 L196 30 L212 388 L162 388 L150 140 L138 388 L88 388 Z"
_SNEAKER = ("M40 250 L40 226 Q42 202 72 197 L112 189 Q142 162 185 140 Q200 168 228 166 "
            "Q244 164 255 150 Q266 200 264 250 Z")
_DERBY = ("M40 250 L40 234 Q44 214 80 208 L132 198 Q160 180 190 170 Q204 192 230 188 "
          "Q246 184 254 172 Q266 212 264 250 Z")
_BOOT = ("M40 250 L40 228 Q42 206 72 200 L122 190 Q152 180 168 150 L172 92 L246 92 "
         "L254 180 Q266 215 264 250 Z")


def _collar(y: int) -> str:
    """Two shirt-collar leaves meeting at the placket."""
    return (f'<path d="M128 {y} L150 {y + 24} L130 {y + 44} L116 {y + 12} Z"/>'
            f'<path d="M172 {y} L150 {y + 24} L170 {y + 44} L184 {y + 12} Z"/>')


def _buttons(x: int, ys: list[int], ink: str, r: float = 2.4) -> str:
    return "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{ink}" stroke="none"/>' for y in ys)


def _details(kind: str, ink: str) -> tuple[str, str]:
    """(garment outline, detail lines) for a garment kind."""
    if kind == "tee":
        return _TEE, '<path d="M123 73 Q150 106 177 73"/>'
    if kind == "longsleeve":
        return _LONG, ('<path d="M123 73 Q150 102 177 73"/>'
                       '<path d="M53 302 L83 307 M217 307 L247 302"/>')
    if kind == "knit":
        return _LONG, ('<path d="M122 73 Q150 104 178 73" stroke-width="5"/>'
                       '<path d="M100 320 H200 M53 300 L84 305 M216 305 L247 300"/>'
                       '<path d="M112 322 V337 M124 322 V337 M136 322 V337 M150 322 V337 '
                       'M164 322 V337 M176 322 V337 M188 322 V337" stroke-width="1.2"/>')
    if kind == "shirt":
        return _SHIRT, (_collar(66) + '<path d="M150 90 V341 M54 300 L84 305 M216 305 L246 300"/>'
                        + _buttons(150, [120, 160, 200, 240, 280, 318], ink))
    if kind == "polo":
        return _TEE.replace("L172 70 Q150 96 128 70 Z", "L172 70 L150 92 L128 70 Z"), (
            _collar(70).replace("L130", "L132").replace("L170", "L168")
            + '<path d="M150 94 V150"/>' + _buttons(150, [112, 134], ink))
    if kind == "overshirt":
        return _OVERSHIRT, (
            _collar(66) + '<path d="M150 90 V338 M52 300 L84 305 M216 305 L248 300"/>'
            '<path d="M110 150 H140 V186 H110 Z M160 150 H190 V186 H160 Z M110 160 H140 M160 160 H190"/>'
            + _buttons(150, [124, 172, 220, 268, 316], ink, 3))
    if kind == "cardigan":
        return _CARDIGAN, ('<path d="M150 178 V338 M100 320 H200 M53 300 L84 305 M216 305 L247 300"/>'
                           '<path d="M122 71 L146 180 M178 71 L154 180" stroke-width="1.4"/>'
                           + _buttons(150, [202, 236, 270, 304], ink, 3))
    if kind == "blazer":
        return _BLAZER, (
            '<path d="M126 62 L110 102 L124 114 L150 172 Z M174 62 L190 102 L176 114 L150 172 Z"/>'
            '<path d="M150 172 V345 M106 262 H136 M164 262 H194 M166 148 H188"/>'
            + _buttons(146, [208, 246], ink, 3.2))
    if kind == "coat":
        return _COAT, (
            '<path d="M126 46 L108 90 L123 102 L150 160 Z M174 46 L192 90 L177 102 L150 160 Z"/>'
            '<path d="M150 160 V388 M104 262 L132 254 M168 254 L196 262"/>'
            + _buttons(144, [196, 244, 292], ink, 3.4))
    if kind == "jacket":
        return _JACKET, ('<path d="M123 66 Q150 90 177 66" stroke-width="5"/>'
                         '<path d="M150 80 V320 M100 302 H200 M53 286 L84 292 M216 292 L247 286"/>'
                         '<path d="M112 304 V319 M126 304 V319 M138 304 V319 M162 304 V319 '
                         'M174 304 V319 M188 304 V319" stroke-width="1.2"/>'
                         '<path d="M112 210 L128 240 M188 210 L172 240"/>')
    if kind == "trousers":
        return _LEGS, ('<path d="M103 46 H197 M150 46 V104 M118 46 L107 96 M182 46 L193 96"/>'
                       '<path d="M127 60 L113 388 M173 60 L187 388" stroke-width="1.1"/>')
    if kind == "chinos":
        return _LEGS, '<path d="M103 46 H197 M150 46 V104 M118 46 L107 96 M182 46 L193 96 M89 376 H138 M162 376 H211"/>'
    if kind == "jeans":
        return _LEGS, ('<path d="M103 46 H197 M150 46 V98 Q150 110 139 110"/>'
                       '<path d="M112 46 Q116 80 104 86 M188 46 Q184 80 196 86 M89 378 H138 M162 378 H211"/>'
                       '<path d="M114 34 V44 M186 34 V44 M150 34 V44" stroke-width="3"/>')
    raise KeyError(kind)


def _shoe(kind: str, fill: str, ink: str) -> str:
    light = lightness(fill) > 60
    if kind == "sneakers":
        upper, sole = _SNEAKER, "M34 250 H270 V264 Q270 276 258 276 H46 Q34 276 34 264 Z"
        sole_fill = _SOLE_LIGHT
        extra = ('<path d="M72 197 Q86 222 80 250 M122 183 L135 196 M138 172 L151 185 '
                 'M154 161 L167 174 M169 150 L182 163 M236 166 Q242 210 238 250"/>')
        shift = 0
    elif kind == "boots":
        upper, sole = _BOOT, "M34 250 H270 V272 H212 V262 H46 Q34 262 34 256 Z"
        sole_fill = _SOLE_DARK
        gusset = shade(fill, 0.22 if not light else -0.22)
        extra = (f'<path d="M196 100 L228 100 L220 176 L206 176 Z" fill="{gusset}"/>'
                 '<path d="M72 200 Q84 224 80 250 M172 92 H246"/>')
        shift = 22
    else:  # leather shoes
        upper, sole = _DERBY, "M34 250 H270 V268 H214 V260 H46 Q34 260 34 256 Z"
        sole_fill = _SOLE_DARK
        extra = ('<path d="M80 208 Q96 228 90 250 M140 192 L151 204 M156 184 L167 196 '
                 'M172 177 L183 189"/>')
        shift = -8
    return (f'<g transform="translate(0 {shift})">'
            f'<path d="{sole}" fill="{sole_fill}" stroke="{ink}"/>'
            f'<path d="{upper}" fill="{fill}" stroke="{ink}"/>'
            f'<g fill="none" stroke="{ink}">{extra}</g></g>')


def svg(kind: str, hex_: str | None) -> str:
    """SVG text for a garment kind in a colour. Raises KeyError for unknown kinds."""
    fill = "#" + hex_.lstrip("#") if hex_ and is_hex(hex_) else "#9a9893"
    ink = "rgba(0,0,0,.34)" if lightness(fill) > 42 else "rgba(255,255,255,.34)"
    if kind in ("sneakers", "shoes", "boots"):
        body = _shoe(kind, fill, ink)
    else:
        outline, details = _details(kind, ink)
        body = (f'<path d="{outline}" fill="{fill}" stroke="{ink}"/>'
                f'<g fill="{fill}" stroke="{ink}">{details}</g>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 400" width="300" height="400" '
            'stroke-width="2" stroke-linejoin="round" stroke-linecap="round">'
            f'<rect width="300" height="400" fill="{_BACKDROP}"/>{body}</svg>')
