"""What a brand-new user starts with: an example profile, a proposed capsule
and the demo catalogue. Runs once per user (at sign-up; on your own machine,
at first start)."""
from __future__ import annotations

from . import capsule, catalog, db, mock, settings, shared
from . import profile as profile_mod


def ensure_setup() -> None:
    if db.get_setting("profile") is None:
        profile_mod.save(dict(profile_mod.EXAMPLE))
    if not db.get_setting("slots_initialised"):
        slots, _ = capsule.propose(profile_mod.load())
        db.replace_slots(slots)
        db.set_setting("slots_initialised", True)
    if catalog.load().get("source") == "empty":
        # A public service with a published store catalogue starts customers on real products.
        real = shared.build_catalog(db.list_slots(), None) if settings.PRODUCTION else None
        catalog.save(real or mock.build(db.list_slots()))
        if real:
            db.set_setting("pool", real["pool"])
