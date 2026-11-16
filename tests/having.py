"""What a test's customer already has, said in one line at the top of the test.

The wardrobe is the outfits a customer said yes to (wardrobe/yes.py): someone new has an empty one, and the
Wardrobe page, the shopping list and the budget bar have nothing to show. A test about those pages, with pieces on
them, starts from a customer who has pieces.
"""
from wardrobe import db
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
