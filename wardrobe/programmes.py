"""Which stores Capsule offers its customers: only stores with a partner (affiliate) programme.

A store's products are shown to customers only if the store runs a partner programme that Capsule can join:
that is the legal way to use its catalogue (product feeds, links that earn a commission). config/stores.toml
says it for each store, in one line:

    [cos]
    programme = "rakuten"      # the network that runs the store's partner programme
    [zara]
    programme = "none"         # no programme: never offered

This is the one place that decides. Everything a customer sees reads the catalogue through it (catalog.load
for each customer's products, shared.load for the list every customer's products come from), so the planner,
the piece pages, the pop-up, "Buy this outfit" and the shopping list never meet a store without a programme.
The list on disk is never edited for it: such a store's products stay in the file and are skipped as it is
read. A customer's own products are read the same way, and are saved back without them.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping

from . import config

NONE = "none"
# The networks that run partner programmes for the stores Capsule may use (PRODUCTION.md, "Before customers").
NETWORKS = ("awin", "rakuten", "tradedoubler", "partnerize", "daisycon", "webgains", "impact")
SETTINGS = "collector"      # the one table in config/stores.toml that is not a store


def check(data: dict) -> None:
    """Refuse a store without a `programme` line, or with one that names no known network."""
    for key, store in data.items():
        if key == SETTINGS or not isinstance(store, dict):
            continue
        value = store.get("programme")
        if value is None:
            raise config.ConfigError(f'[{key}] needs a programme line: the network that runs its partner programme '
                                     f'({", ".join(NETWORKS)}), or "none"')
        if value != NONE and value not in NETWORKS:
            raise config.ConfigError(f'{key}.programme is {value!r}; it can be "none" or one of: {", ".join(NETWORKS)}')


def _stores() -> dict[str, dict]:
    """Every store in config/stores.toml, in the file's order."""
    data = config.load("stores.toml")
    try:
        check(data)
    except config.ConfigError as e:
        raise config.ConfigError(f"config/stores.toml: {e}") from None
    return {key: store for key, store in data.items() if key != SETTINGS and isinstance(store, dict)}


def offered() -> dict[str, str]:
    """The stores customers are offered, {key: name}, in the file's order: those with a programme."""
    return {key: store.get("label", key) for key, store in _stores().items() if store["programme"] != NONE}


class _Offered(Mapping):
    """offered() as a dict that is read each time it is used, so a change to config/stores.toml shows at the next
    page: the pages' STORES (app.py), {key: name}."""

    def __getitem__(self, key: str) -> str:
        return offered()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(offered())

    def __len__(self) -> int:
        return len(offered())


OFFERED: Mapping[str, str] = _Offered()


def is_offered(store: object) -> bool:
    return store in offered()


def label(store: str) -> str:
    """A store's name as people read it ('COS'), also for one that is not offered; its key if it is not listed."""
    return _stores().get(store, {}).get("label", store)


def names(keys, last: str = "and") -> str:
    """'Zara', 'COS and Weekday', 'COS, Weekday and Arket' (or 'COS or Weekday'): the stores' names in a sentence."""
    words = [label(key) for key in keys]
    return ", ".join(words[:-1]) + f" {last} " + words[-1] if len(words) > 1 else "".join(words)


def only_offered(catalogue: dict) -> dict:
    """A catalogue (a customer's, or the list every customer's products come from) without the products of
    stores that are not offered, and without their lines in its "stores" notes. A new dict: the one given,
    and the file it came from, are left as they are."""
    keep = offered()
    out = dict(catalogue)
    for name in ("candidates", "products"):
        if name in catalogue:
            out[name] = [item for item in catalogue[name] if item.get("store") in keep]
    if isinstance(catalogue.get("stores"), dict):
        out["stores"] = {key: notes for key, notes in catalogue["stores"].items() if key in keep}
    return out
