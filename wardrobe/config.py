"""Loads the editable TOML files in config/.

Files are re-read whenever they change on disk, so editing a rule and
reloading the page is enough — no restart.
"""
from __future__ import annotations

import tomllib

from .paths import CONFIG_DIR


class ConfigError(Exception):
    """A config file is missing or has a syntax error. Shown as a friendly page."""


_cache: dict[str, tuple[int, dict]] = {}


def load(name: str, check=None) -> dict:
    """Read config/<name>. `check(data)` may raise ConfigError for values that
    parse but make no sense; it runs once per change of the file."""
    path = CONFIG_DIR / name
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        raise ConfigError(f"config/{name} is missing.") from None
    hit = _cache.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config/{name} has a syntax error: {e}") from None
    if check:
        try:
            check(data)
        except ConfigError as e:
            raise ConfigError(f"config/{name}: {e}") from None
    _cache[name] = (mtime, data)
    return data


def number(value, where: str) -> float:
    """`value` as a float, or a ConfigError naming the setting."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be a number, not {value!r}")
    return float(value)


def table(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"[{where}] must be a table of settings, not {value!r}")
    return value
