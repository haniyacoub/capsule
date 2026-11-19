"""What a test's customer already has, said in one line at the top of the test.

The wardrobe is the outfits a customer said yes to (wardrobe/yes.py): someone new has an empty one, and the
Wardrobe page, the shopping list and the budget bar have nothing to show. A test about those pages, with pieces on
them, starts from a customer who has pieces.
"""
from wardrobe import capsule, catalog, db, mock, settings, shared
from wardrobe import profile as profile_mod


def the_whole_plan(budget: bool = True) -> None:
    """The customer whose turn it is has every piece of his plan in his wardrobe (each on its own account, as the
    pieces someone chose by hand before version 9 are: the setting "kept_pieces"), with the spare of each piece the
    plan has twice (the setting "spares"), and has given his budget, so the bar counts against it. With budget=False
    the budget stays one he never gave."""
    db.set_setting("kept_pieces", [slot["id"] for slot in db.list_slots()])
    db.set_setting("spares", [slot["id"] for slot in db.list_slots() if slot["qty"] > 1])
    if budget:
        profile_mod.answer("budget")


def the_old_start() -> None:
    """The customer whose turn it is starts as every account did until 19 Nov 2026: the example's answers with a
    budget of 1,500 € (24 pieces for everyday and the office, config/budget.toml: a coat, a blazer, boots and the
    rest), on the price level Cheapest, with the products of that plan (the published list's on the public site where
    there is one, else the demo's). For a test about something else that needs that big wardrobe; a new account now
    starts at 300 € (9 pieces) on "Best for budget" (test_budget.py)."""
    profile = {**profile_mod.EXAMPLE, "budget": 1500}
    profile_mod.save(profile)
    db.set_setting("mode", "cheapest")
    db.set_setting("levels", True)
    db.replace_slots(capsule.propose(profile)[0])
    real = shared.build_catalog(db.list_slots(), None) if settings.PRODUCTION and shared.published() else None
    catalog.save(real or mock.build(db.list_slots()))
    if real:
        db.set_setting("pool", real["pool"])
