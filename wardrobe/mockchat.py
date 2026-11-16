"""A stand-in for Google's text model, for the tests, the walk-through and the night preview.

    stylechat.ask = mockchat.answer

It is not a language model: it spots a few words in the customer's last message ("street",
"Berlin", "office", "navy", "no logos", "relaxed", "cheap" …) and answers in the shape the real
model is asked for (stylechat.schema). Nothing is sent anywhere and nothing is billed. The real
service never runs through this file: stylechat.ask is only replaced where a test or the
preview says so.

Phrases it is known to understand:  "street style, Berlin vibe"  and  "office, navy, no logos".
"""
from __future__ import annotations

import re

from . import colours, style
from .stylechat import ME

# Words in a message, and the style they stand for.
STYLE_WORDS = {
    "street": "street", "streetwear": "street", "skate": "street", "berlin": "street",
    "minimal": "minimal", "minimalist": "minimal", "clean": "minimal", "simple": "minimal",
    "smart casual": "smart-casual", "smart": "smart-casual",
    "office": "tailored", "tailored": "tailored", "suit": "tailored", "business": "tailored", "formal": "tailored",
    "workwear": "workwear", "rugged": "workwear",
    "outdoor": "outdoor", "hiking": "outdoor", "mountain": "outdoor",
}
FORMALITY_WORDS = {"street": "casual", "casual": "casual", "relaxed": "casual", "weekend": "casual",
                   "smart": "smart", "office": "smart", "formal": "formal", "business": "formal", "suit": "formal"}
FIT_WORDS = {"relaxed": "relaxed", "loose": "relaxed", "baggy": "oversized", "oversized": "oversized",
             "slim": "slim", "fitted": "slim", "regular": "regular", "street": "relaxed"}
PRICE_WORDS = {"cheap": "low", "affordable": "low", "budget": "low", "premium": "high", "quality": "high",
               "expensive": "high", "mid": "mid"}
NO = re.compile(r"\b(?:no|not|without|never|avoid)\s+([a-zäöüß]+(?:\s+[a-zäöüß]+)?)")


def answer(model: str, key: str, turns: list[dict], brief: dict) -> dict:
    """What the real model would send back, as parsed JSON: {"reply", "question", "brief"}."""
    said = next((turn["text"] for turn in reversed(turns) if turn["who"] == ME), "").lower()
    new = {name: (list(value) if isinstance(value, list) else value) for name, value in style.clean(brief).items()}
    understood: list[str] = []

    refused = [found.strip() for found in NO.findall(said)]
    rest = NO.sub(" ", said)                       # what he does want: the "no …" parts are read apart
    for words in refused:
        colour = colours.find(words)
        if colour:
            new["colours_avoid"].append(colour)
            understood.append(f"no {colours.get(colour).label.lower()}")
        else:
            word = words.split()[0]
            new["not_wanted"].append(word)
            understood.append(f"no {word}")
    for word, key_ in STYLE_WORDS.items():
        if re.search(rf"\b{word}\b", rest) and key_ not in new["styles"]:
            new["styles"].append(key_)
            understood.append(style.styles()[key_].lower())
    for word, level in FORMALITY_WORDS.items():
        if re.search(rf"\b{word}\b", rest):
            new["formality"] = level
            break
    for word, fit in FIT_WORDS.items():
        if re.search(rf"\b{word}\b", rest) and fit not in new["fits"]:
            new["fits"].append(fit)
            understood.append(f"{fit} fits")
    for word, level in PRICE_WORDS.items():
        if re.search(rf"\b{word}\b", rest):
            new["price"] = level
    if "berlin" in rest or "dark" in rest:         # "Berlin vibe": dark colours
        new["colours_like"] += ["black", "charcoal"]
        understood.append("dark colours")
    for part in re.split(r"[,.;]|\band\b", rest):
        colour = colours.find(part)
        if colour and colour not in new["colours_like"]:
            new["colours_like"].append(colour)
            understood.append(colours.get(colour).label.lower())

    if not understood:
        return {"reply": "Preview stand-in: I did not find a style in that. Tell me a style, a colour or a fit, "
                         "such as “street style, Berlin vibe”.",
                "question": "", "brief": brief}
    question = ("Should it stay all dark, or may one colour come in?" if "dark colours" in understood
                else "Do you prefer a slim or a relaxed fit?" if not new["fits"] else "")
    return {"reply": f"Preview stand-in: I understood {', '.join(dict.fromkeys(understood))}. "
                     "The brief below has it. Change what is wrong, then use it.",
            "question": question, "brief": new}
