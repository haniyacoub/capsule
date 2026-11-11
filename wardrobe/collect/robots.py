"""robots.txt, read the way search engines read it.

Each store publishes which addresses automated visitors should stay away
from. The collector asks `allowed(url)` before every page it opens.

Only the rules for "User-agent: *" are used. A rule may contain `*` (anything)
and end in `$` (end of address); when several rules match, the longest wins,
and "Allow" wins a tie.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit


def _to_regex(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(regex + ("$" if anchored else ""))


class Robots:
    def __init__(self, text: str):
        self.rules: list[tuple[int, bool, re.Pattern]] = []   # (length, is_allow, pattern)
        agents: list[str] = []
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, value = (part.strip() for part in line.split(":", 1))
            field = field.lower()
            if field == "user-agent":
                if in_rules:          # a new group starts after the previous group's rules
                    agents, in_rules = [], False
                agents.append(value.lower())
            elif field in ("allow", "disallow"):
                in_rules = True
                if "*" in agents and value:   # an empty "Disallow:" forbids nothing
                    self.rules.append((len(value), field == "allow", _to_regex(value)))

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best: tuple[int, bool] | None = None
        for length, is_allow, pattern in self.rules:
            if pattern.match(target) and (best is None or (length, is_allow) > best):
                best = (length, is_allow)
        return True if best is None else best[1]
