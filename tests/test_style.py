"""Styles, the style brief and the style chat (wardrobe/style.py, stylechat.py, mockchat.py).

No test talks to Google: the text model is a stand-in (mockchat.answer, or a canned answer), and the
one thing that could open a connection (imagegen's opener) is replaced by one that fails the test
if it is used, except where a test hands it a canned answer of its own.
"""
import html
import io
import json
import re
import unittest
from contextlib import redirect_stdout
from unittest import mock

from wardrobe import config, db, imagegen, mockchat, outfits, programmes, selection, settings, style, stylechat
from wardrobe.__main__ import main
from wardrobe.imagegen import DrawError

from .test_app import HX, AppCase
from .test_production import ProductionCase, words

STREET = {**style.EMPTY, "styles": ["street"], "formality": "casual", "colours_like": ["black", "charcoal"],
          "fits": ["relaxed"]}
OFFICE = {**style.EMPTY, "styles": ["tailored"], "formality": "smart", "colours_like": ["navy"],
          "not_wanted": ["logos"]}


def picks(w) -> dict:
    return {view.slot["id"]: view.chosen.id if view.chosen else None for view in w.slots}


def offered(w) -> list[str]:
    return [o.key for o in outfits.generate(w)[0]]


class NoNetwork:
    """The chat switched on (a key is set), with no way out to the network."""

    def chat_on(self, answer=mockchat.answer):
        self.asked = []         # everything the "text model" was sent

        def stand_in(model, key, turns, brief):
            self.asked.append({"model": model, "key": key, "turns": [dict(turn) for turn in turns], "brief": brief})
            return answer(model, key, turns, brief) if callable(answer) else answer

        self.opener = mock.Mock()
        self.opener.open.side_effect = AssertionError("a network connection was opened")
        for patch in (mock.patch.object(settings, "GEMINI_API_KEY", "test-gemini-key"),
                      mock.patch.object(stylechat, "ask", stand_in),
                      mock.patch.object(imagegen, "_opener", self.opener)):
            patch.start()
            self.addCleanup(patch.stop)

    def with_chat_rules(self, **changes):
        rules = style.load_rules()
        changed = {**rules, "chat": {**rules["chat"], **changes}}
        patch = mock.patch.object(style, "load_rules", lambda: changed)
        patch.start()
        self.addCleanup(patch.stop)


# ── the brief itself ──────────────────────────────────────────────────────────

class TheBrief(AppCase):
    def test_only_what_exists_here_is_kept_of_a_brief_from_anywhere(self):
        raw = {"styles": ["Street", "punk", 7, "minimal", "street"], "formality": "black tie",
               "colours_like": ["navy", "Schwarz", "sparkle", {"x": 1}], "colours_avoid": ["navy", "x" * 500],
               "fits": ["RELAXED", "skin-tight"], "price": ["low"], "stores": ["zara"], "products": ["cos-123"],
               "not_wanted": ["<script>alert(1)</script>", "Logo!!", "a", "x" * 200, "logo"] + [f"w{i}x" for i in range(30)]}
        brief = style.clean(raw)
        self.assertEqual(sorted(brief), sorted(style.EMPTY), "no part is added: nothing names a store or a product")
        self.assertEqual(brief["styles"], ["street", "minimal"])
        self.assertEqual((brief["formality"], brief["price"]), ("", ""))
        self.assertEqual((brief["colours_like"], brief["colours_avoid"]), (["black"], ["navy"]),
                         "a colour named in both is avoided")
        self.assertEqual(brief["fits"], ["relaxed"])
        self.assertEqual(len(brief["not_wanted"]), style.MAX_NOT_WANTED)
        self.assertEqual(brief["not_wanted"][:2], ["script alert 1 script", "logo"])
        self.assertTrue(all(len(word) <= style.MAX_WORD and re.fullmatch(r"[a-z0-9äöüß -]+", word)
                            for word in brief["not_wanted"]))
        for junk in (None, "street", 3, [], ["street"], {"styles": "street"}, {"styles": {"a": 1}}):
            self.assertEqual(sorted(style.clean(junk)), sorted(style.EMPTY), repr(junk))
        self.assertEqual(style.clean({"styles": "street"})["styles"], ["street"], "one word is a list of one")
        self.assertFalse(style.active(style.clean({})))
        self.assertTrue(style.active(style.clean({"price": "low"})))

    def test_a_product_earns_and_loses_points_from_its_words_fit_colour_and_store(self):
        jeans = {"name": "Relaxed Jeans aus Denim", "fit": "relaxed", "colour": "Schwarz", "store": "weekday",
                 "composition_text": "100 % Baumwolle"}
        points = style.load_rules()["points"]
        total, fits_style, fit = style.judge(jeans, "jeans", STREET)
        self.assertEqual((fits_style, fit), ("street", "relaxed"))
        self.assertEqual(total, points["style_word"] + points["style_garment"] + points["fit"] + points["colour"]
                         + points["store_style"], "a street word, a street garment, his fit, his colour, a street store")
        slim = {**jeans, "name": "Slim Jeans", "fit": "slim", "colour": "Beige", "store": "cos"}
        self.assertEqual(style.product_points(slim, "jeans", STREET), points["style_garment"] + points["other_fit"])
        # Things he does not want, as the stores write them (German too), and colours he avoids (olive is a green).
        tee = {"name": "T-Shirt mit Logo-Print", "colour": "Navy", "store": "cos"}
        self.assertLess(style.product_points(tee, "tee", {**style.EMPTY, "not_wanted": ["logos"]}), 0)
        self.assertLess(style.product_points({"name": "Pullover", "colour": "Olive"}, "knit",
                                             {**style.EMPTY, "colours_avoid": ["green"]}), 0)
        self.assertEqual(style.product_points({"name": "Katalog Hemd"}, "shirt", {**style.EMPTY, "not_wanted": ["logo"]}),
                         0, "a word is looked for at the start of a word: 'katalog' is not a logo")
        self.assertEqual(style.product_points({}, "tee", style.clean({})), 0, "an empty brief gives nothing")
        # Something he owns has no store, name or fit: only its garment type counts.
        self.assertEqual(style.judge({"owned": True}, "jeans", STREET), (points["style_garment"], "street", ""))

    def test_the_products_that_fit_come_first_and_one_against_the_brief_only_when_nothing_else(self):
        class Cand:
            def __init__(self, **data):
                self.data = data

        fits = Cand(name="Relaxed Jeans", fit="relaxed", colour="Schwarz")
        silent = Cand(name="Hose", colour="Beige")
        against = Cand(name="Jeans mit Logo", fit="slim", colour="Beige")
        brief = {**style.EMPTY, "fits": ["relaxed"], "not_wanted": ["logo"]}
        self.assertEqual(style.narrow([against, silent, fits], "trousers", brief), [fits])
        self.assertEqual(style.narrow([against, silent], "trousers", brief), [silent])
        self.assertEqual(style.narrow([against], "trousers", brief), [against], "a piece is never left empty")
        pool = [against, silent, fits]
        self.assertIs(style.narrow(pool, "trousers", None), pool, "without a brief: the same products, untouched")
        self.assertEqual(style.narrow([], "trousers", brief), [])

    def test_the_stores_are_ranked_by_the_style_table_in_stores_toml(self):
        stores = config.load("stores.toml")
        known = set(style.styles())
        for key in programmes.offered():
            self.assertIsInstance(stores[key].get("styles"), list, f"{key} has a styles line")
            self.assertLessEqual(set(stores[key]["styles"]), known, f"{key}: a style config/style.toml does not have")
            self.assertRegex(stores[key].get("price", ""), r"^(budget|mid|premium)(-(mid|premium))?$", key)
        self.assertEqual(style.stores_that_suit(STREET), ["weekday", "blue-tomato"])
        self.assertEqual(style.stores_that_suit({**style.EMPTY, "styles": ["outdoor"]}), ["blue-tomato", "bergfreunde"])
        tailored_high = {**style.EMPTY, "styles": ["tailored", "smart-casual"], "price": "high"}
        self.assertEqual(style.stores_that_suit(tailored_high)[:3], ["cos", "hirmer", "breuninger"],
                         "two shared styles and the price level: the most points, then the file's order")
        self.assertNotIn("otto", style.stores_that_suit(STREET), "a store with no style of its own earns nothing")
        self.assertEqual(style.stores_that_suit(STREET, among=["cos", "weekday"]), ["weekday"],
                         "only among the stores he ticked")
        self.assertEqual(style.stores_that_suit(style.clean({})), [])
        self.assertNotIn("zara", style.stores_that_suit({**style.EMPTY, "styles": list(known), "price": "mid"}),
                         "a store without a partner programme is never named")

    def test_an_outfit_says_in_one_line_why_it_fits(self):
        pieces = [{"category": "jeans", "name": "Relaxed Jeans", "fit": "relaxed", "colour": "Blau", "store": "weekday"},
                  {"category": "overshirt", "name": "Overshirt aus Twill", "fit": "regular", "colour": "Schwarz",
                   "store": "weekday"},
                  {"category": "shoes", "name": "Derby", "colour": "Braun", "store": "cos"}]
        brief = {**style.EMPTY, "styles": ["street"], "fits": ["relaxed"]}
        self.assertEqual(style.why(pieces, brief), "Street: relaxed jeans, overshirt")
        self.assertEqual(style.why(pieces[2:], brief), "", "nothing in it fits: nothing is said")
        self.assertEqual(style.why(pieces, None), "")
        self.assertEqual(style.why([{"category": "knit", "name": "Pullover", "colour": "Navy", "store": "otto"}],
                                   {**style.EMPTY, "colours_like": ["navy"]}), "Your brief: navy jumper")

    def test_a_mistake_in_style_toml_is_said_in_words(self):
        rules = config.load("style.toml")
        for change, said in ((lambda r: r["styles"].update(grunge={"label": "Grunge", "words": [], "garments": ["kilt"]}),
                              "not a garment type"),
                             (lambda r: r["chat"].update(model=""), "chat.model"),
                             (lambda r: r["chat"].update(per_day=-1), "cannot be negative"),
                             (lambda r: r.update(styles={}), "at least one style"),
                             (lambda r: r["formality"].update(casual={"label": "Casual", "levels": [1]}), "two numbers")):
            broken = json.loads(json.dumps(rules))
            change(broken)
            with self.assertRaises(config.ConfigError) as caught:
                style._check(broken)
            self.assertIn(said, str(caught.exception))


# ── what a brief changes, and that nothing changes without one ────────────────

class Steering(AppCase):
    def test_without_a_brief_every_pick_and_every_outfit_is_as_before(self):
        # "As before" is proved two ways: the style arithmetic is never asked (it would fail the test), and the
        # picks and the outfits' order are the ones the code gives with the style module's two entry points
        # taken out altogether.
        for mode in ("cheapest", "balanced", "best", "budget"):
            self.set_mode(mode)
            with mock.patch.object(style, "judge", side_effect=AssertionError("the brief's arithmetic ran")):
                w = selection.build()
                self.assertIsNone(w.brief)
                now = picks(w), offered(w), w.levels
            with mock.patch.object(style, "narrow", lambda pool, category, brief: pool), \
                    mock.patch.object(style, "outfit_bonus", lambda pieces, level, brief: 0.0):
                w = selection.build()
                self.assertEqual((picks(w), offered(w), w.levels), now, mode)
        page = self.client.get("/outfits").get_data(as_text=True)
        self.assertNotIn("data-why", page)

    def test_a_brief_that_was_removed_or_says_nothing_leaves_everything_as_before(self):
        before = picks(selection.build()), offered(selection.build())
        style.save(STREET)
        self.assertNotEqual((picks(selection.build()), offered(selection.build())), before)
        style.save(style.clean({}))
        self.assertIsNone(style.current(), "a brief that says nothing is no brief")
        self.assertEqual((picks(selection.build()), offered(selection.build())), before)
        style.save(STREET)
        style.remove()
        self.assertEqual((picks(selection.build()), offered(selection.build())), before)

    def test_with_a_brief_each_piece_takes_a_product_that_fits_it_where_there_is_one(self):
        self.set_mode("cheapest")
        plain = selection.build()
        style.save(STREET)
        w = selection.build()
        self.assertEqual(w.brief, STREET)
        changed = 0
        for view, was in zip(w.slots, plain.slots):
            if view.state != "auto" or not view.chosen:
                continue
            category = view.slot["category"]
            pool = selection.in_your_size_first([c for c in view.cands if c.available and c.score.total >= w.threshold])
            scores = [style.product_points(c.data, category, STREET) for c in pool]
            mine = style.product_points(view.chosen.data, category, STREET)
            if any(score > 0 for score in scores):
                self.assertGreater(mine, 0, view.slot["name"])
                # … and among those that fit, the price level still chooses: here, the cheapest of them.
                self.assertEqual(view.chosen.price, min(c.price for c, s in zip(pool, scores) if s > 0))
            elif any(score == 0 for score in scores):
                self.assertEqual(mine, 0, view.slot["name"])
            self.assertIn(view.chosen.id, [c.id for c in view.cands], "always a product of the catalogue")
            changed += view.chosen.id != was.chosen.id
        self.assertGreater(changed, 0, "the demo catalogue has pieces whose cheapest product is not the street one")
        self.assertEqual([c.score.total for v in w.slots for c in v.cands],
                         [c.score.total for v in plain.slots for c in v.cands], "the quality score is not touched")

    def test_the_budget_level_fits_the_budget_among_the_products_that_fit_the_brief(self):
        self.set_mode("budget")
        style.save(OFFICE)
        w = selection.build()
        for view in w.slots:
            if view.state == "auto" and view.chosen:
                pool = selection.in_your_size_first([c for c in view.cands if c.available and c.price > 0
                                                     and c.score.total >= w.threshold])
                if any(style.product_points(c.data, view.slot["category"], OFFICE) > 0 for c in pool):
                    self.assertGreater(style.product_points(view.chosen.data, view.slot["category"], OFFICE), 0,
                                       view.slot["name"])

    def test_the_outfits_that_fit_the_brief_are_offered_first_and_say_why(self):
        style.save(STREET)
        w = selection.build()
        shown, _ = outfits.generate(w)
        bonus = {o.key: style.outfit_bonus(outfits.snapshot(o), o.level, STREET) for o in outfits.all_outfits(w)}
        ranked = sorted(bonus.values())
        self.assertGreater(bonus[shown[0].key], ranked[len(ranked) // 2], "the first outfit fits better than most")
        self.assertGreater(sum(bonus[o.key] for o in shown[:4]) / 4, sum(ranked) / len(ranked))
        points = style.load_rules()["points"]
        self.assertTrue(all(points["outfit_least"] - points["formality"] <= value
                            <= points["outfit_most"] + points["formality"] for value in ranked), "within its bounds")
        self.assertEqual(style.outfit_bonus(outfits.snapshot(shown[0]), shown[0].level, None), 0.0)
        page = self.client.get("/outfits").get_data(as_text=True)
        lines = re.findall(r'<p class="about-why" data-why>([^<]+)</p>', page)
        self.assertTrue(lines, "each outfit that fits says why")
        first = style.why(outfits.snapshot(shown[0]), STREET)
        self.assertRegex(first, r"^Street: [a-z -]+(, [a-z -]+){0,2}$")
        # The line is true of the outfit: every thing it names is one of its pieces' garments.
        for outfit in shown:
            line = style.why(outfits.snapshot(outfit), STREET)
            if line:
                from wardrobe.garments import GARMENTS
                garments = {GARMENTS[p.category].label.lower() for p in outfit.pieces}
                for named in line.split(": ", 1)[1].split(", "):
                    self.assertTrue(any(named.endswith(garment) for garment in garments), (line, garments))

    def test_formality_moves_the_outfits_at_that_level_up(self):
        casual = {**style.EMPTY, "formality": "casual"}
        formal = {**style.EMPTY, "formality": "formal"}
        w = selection.build()
        levels = {o.key: o.level for o in outfits.all_outfits(w)}
        style.save(casual)
        first_casual = [levels[key] for key in offered(selection.build())[:4]]
        style.save(formal)
        first_formal = [levels[key] for key in offered(selection.build())[:4]]
        self.assertLess(sum(first_casual), sum(first_formal))


# ── Profile: the styles to tick ───────────────────────────────────────────────

class Ticking(AppCase):
    def form(self, **more):
        """Profile's own form as the page sends it, with these changes."""
        page = self.client.get("/profile").get_data(as_text=True)
        form = page.split('id="about-you"', 1)[1].split("</form>", 1)[0]
        data = {}
        for name, value in re.findall(r'<input type="(?:text|number|hidden)"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form):
            data[name] = value
        for name, value in re.findall(r'<input type="radio" name="([^"]+)" value="([^"]*)" checked', form):
            data[name] = value
        return {**data, **more}

    def test_the_styles_are_tappable_choices_beside_everyday_office_both(self):
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertNotIn("Describe your style", page, "no key: no chat")
        for value in ("everyday", "office", "both"):
            self.assertRegex(page, rf'<input type="radio" name="use" value="{value}"')
        for key, label in style.styles().items():
            self.assertRegex(page, rf'<input type="checkbox" name="styles" value="{key}"><span>{label}</span>')
        self.assertEqual(list(style.styles().values()),
                         ["Smart casual", "Street", "Minimal", "Tailored", "Workwear", "Outdoor"])

    def test_ticked_styles_are_the_brief_and_steer_the_picks_without_any_chat(self):
        self.client.post("/profile", data=self.form())       # the profile is his own now; no style ticked
        before = picks(selection.build()), offered(selection.build())
        plan = [(s.slot["category"], s.slot["name"]) for s in selection.build().slots]
        response = self.client.post("/profile", data={**self.form(), "styles": ["street", "workwear", "punk"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(style.current(), {**style.EMPTY, "styles": ["street", "workwear"]})
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertRegex(page, r'name="styles" value="street" checked')
        self.assertRegex(page, r'name="styles" value="workwear" checked')
        self.assertNotRegex(page, r'name="styles" value="minimal" checked')
        w = selection.build()
        self.assertNotEqual((picks(w), offered(w)), before)
        self.assertTrue(style.why(outfits.snapshot(outfits.generate(w)[0][0]), w.brief).startswith(("Street: ", "Workwear: ")))
        # Unticking them all: no brief again, every pick as before.
        self.client.post("/profile", data=self.form())
        self.assertIsNone(style.current())
        self.assertEqual((picks(selection.build()), offered(selection.build())), before)
        self.assertEqual([(s.slot["category"], s.slot["name"]) for s in selection.build().slots], plan,
                         "a style never changes the plan")

    def test_everyday_office_both_work_as_they_did(self):
        for use in ("office", "everyday", "both"):
            self.client.post("/profile", data={**self.form(use=use), "styles": ["minimal"]})
            from wardrobe import profile as profile_mod
            self.assertEqual(profile_mod.load()["use"], use)
        self.assertEqual(style.current()["styles"], ["minimal"])

    def test_a_form_without_the_styles_leaves_the_brief_alone(self):
        style.save(STREET)
        data = self.form()
        data.pop("styles_shown")
        self.client.post("/profile", data=data)
        self.assertEqual(style.current(), STREET)

    def test_without_a_key_a_brief_in_use_can_still_be_changed_by_hand_or_removed(self):
        style.save(STREET)
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertNotIn("Describe your style", page)
        self.assertIn('data-brief="in-use"', page)
        self.assertIn("Your style brief", page)
        self.client.post("/profile/style/brief", data={"do": "use", "styles": ["minimal"], "formality": "smart",
                                                       "colours_like": "navy, grey; ecru", "colours_avoid": "pink",
                                                       "fits": ["regular"], "price": "mid",
                                                       "not_wanted": "Logo, leather"})
        self.assertEqual(style.current(), {"styles": ["minimal"], "formality": "smart",
                                           "colours_like": ["navy", "grey", "ecru"], "colours_avoid": ["pink"],
                                           "fits": ["regular"], "price": "mid", "not_wanted": ["logo", "leather"]})
        self.client.post("/profile/style/brief", data={"do": "remove"})
        self.assertIsNone(style.current())
        self.assertNotIn("data-brief", self.client.get("/profile").get_data(as_text=True))


# ── the chat ──────────────────────────────────────────────────────────────────

class Chat(NoNetwork, AppCase):
    def setUp(self):
        super().setUp()
        self.chat_on()

    def say(self, message, **headers):
        return self.client.post("/profile/style/say", data={"message": message}, headers=headers)

    def test_without_a_key_the_chat_is_not_offered_and_takes_no_message(self):
        with mock.patch.object(settings, "GEMINI_API_KEY", ""):
            self.assertFalse(stylechat.available())
            page = self.client.get("/profile").get_data(as_text=True)
            self.assertNotIn("Describe your style", page)
            self.assertNotIn("/profile/style/say", page)
            self.assertIn("And in which style?", page, "the tappable choices are still there")
            answer = self.say("street style, Berlin vibe", **HX).get_data(as_text=True)
            self.assertIn(stylechat.SAY["closed"], answer)
        self.assertEqual((self.asked, stylechat.state()["turns"], db.chat_requests(0)), ([], [], 0))

    def test_his_words_become_a_suggested_brief_and_only_confirming_it_changes_anything(self):
        before = picks(selection.build()), offered(selection.build())
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertIn("Describe your style", page)
        self.assertNotIn("data-brief", page, "no brief yet: none shown")
        fragment = self.say("street style, Berlin vibe", **HX).get_data(as_text=True)
        self.assertNotIn("<html", fragment, "HTMX gets the chat alone")
        said = words(fragment)
        self.assertIn("street style, Berlin vibe", said)
        self.assertIn("I understood street", said)
        self.assertIn("Should it stay all dark, or may one colour come in?", said, "one question back")
        self.assertIn('data-brief="suggested"', fragment)
        self.assertIn("Not in use yet.", said)
        self.assertRegex(fragment, r'name="styles" value="street" checked')
        self.assertRegex(fragment, r'name="fits" value="relaxed" checked')
        self.assertRegex(fragment, r'name="formality" value="casual" checked')
        self.assertRegex(fragment, r'name="colours_like" value="black, charcoal"')
        self.assertIn("Stores that suit this brief, best first: Weekday", said)
        # Nothing is in use yet.
        self.assertIsNone(style.current())
        self.assertEqual((picks(selection.build()), offered(selection.build())), before)
        self.assertNotIn("data-why", self.client.get("/outfits").get_data(as_text=True))
        # He corrects it (adds a colour to avoid) and confirms.
        response = self.client.post("/profile/style/brief", data={
            "do": "use", "styles": ["street"], "formality": "casual", "colours_like": "black, charcoal",
            "colours_avoid": "mustard", "fits": ["relaxed"], "price": "", "not_wanted": ""}, follow_redirects=True)
        self.assertIn("Style brief saved.", words(response.get_data(as_text=True)))
        self.assertEqual(style.current(), {**STREET, "colours_avoid": ["mustard"]})
        self.assertIsNone(stylechat.state()["draft"], "it is the brief now, no longer a suggestion")
        self.assertNotEqual((picks(selection.build()), offered(selection.build())), before)
        self.assertIn("data-why", self.client.get("/outfits").get_data(as_text=True))
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertIn('data-brief="in-use"', page)
        self.assertRegex(page, r'name="styles" value="street" checked', "the styles ticked above show the brief's")

    def test_the_chat_can_be_asked_again_and_builds_on_the_brief(self):
        self.say("street style, Berlin vibe")
        self.client.post("/profile/style/brief", data={"do": "use", "styles": ["street"], "fits": ["relaxed"]})
        self.say("no leather, and cheap please")
        self.assertEqual(self.asked[-1]["brief"]["styles"], ["street"], "the brief in use goes along")
        draft = stylechat.state()["draft"]
        self.assertEqual((draft["styles"], draft["fits"], draft["price"], draft["not_wanted"]),
                         (["street"], ["relaxed"], "low", ["leather"]))
        page = words(self.client.get("/profile").get_data(as_text=True))
        self.assertIn("Not in use yet.", page)
        self.assertIn("In use now: styles Street; fits relaxed.", page)
        self.assertEqual(style.current()["price"], "", "still the confirmed brief")
        # A message it finds no style in leaves the suggestion standing; nothing is lost.
        self.say("what is the weather")
        self.assertEqual(stylechat.state()["draft"], draft)

    def test_the_second_stand_in_phrase(self):
        self.say("office, navy, no logos")
        self.assertEqual(stylechat.state()["draft"], OFFICE)

    def test_start_again_deletes_the_conversation_and_keeps_the_brief_in_use(self):
        style.save(STREET)
        self.say("office, navy, no logos")
        response = self.client.post("/profile/style/brief", data={"do": "forget"}, follow_redirects=True)
        self.assertIn("The conversation is deleted. Your style brief stays in use.", words(response.get_data(as_text=True)))
        self.assertEqual(stylechat.state(), {"turns": [], "draft": None, "question": ""})
        self.assertEqual(style.current(), STREET)
        self.say("office, navy, no logos")
        self.client.post("/profile/style/brief", data={"do": "remove"})
        self.assertEqual((style.current(), stylechat.state()["turns"]), (None, []))

    def test_confirming_an_emptied_brief_puts_none_in_use(self):
        self.say("street style, Berlin vibe")
        response = self.client.post("/profile/style/brief", data={"do": "use"}, follow_redirects=True)
        self.assertIn("The brief was empty, so none is in use.", words(response.get_data(as_text=True)))
        self.assertIsNone(style.current())

    def test_only_the_last_lines_are_kept_and_a_long_message_is_cut(self):
        rules = style.load_rules()["chat"]
        for n in range(5):
            self.say(f"street {n}")
        self.assertEqual(len(stylechat.state()["turns"]), rules["keep_turns"])
        self.assertLessEqual(len(self.asked[-1]["turns"]), rules["keep_turns"])
        self.say("minimal " + "x" * 5000 + "\x00\x1b[31m")
        sent = self.asked[-1]["turns"][-1]["text"]
        self.assertEqual(len(sent), rules["max_message_chars"])
        self.assertTrue(sent.isprintable())
        count = db.chat_requests(0)
        answer = self.say("   ", **HX).get_data(as_text=True)
        self.assertIn(stylechat.SAY["nothing"], answer)
        self.assertEqual(db.chat_requests(0), count, "an empty message is not sent and not counted")

    def test_a_message_without_htmx_comes_back_to_the_chat_on_profile(self):
        response = self.say("street style, Berlin vibe")
        self.assertEqual((response.status_code, response.headers["Location"]), (302, "/profile#style"))
        self.assertIn("I understood street", words(self.client.get("/profile").get_data(as_text=True)))

    def test_beside_the_chat_it_says_what_goes_to_google(self):
        page = words(self.client.get("/profile").get_data(as_text=True))
        self.assertIn("What you write here goes to Google, whose AI model writes the answer, together with the last "
                      "lines of this conversation and your style brief. Your name, email address, sizes, budget and "
                      "photo are not sent. Up to 20 messages a day.", page)
        self.say("street style, Berlin vibe")
        self.assertIn("The answers are written by AI and can be wrong.",
                      words(self.client.get("/profile").get_data(as_text=True)))


class Untrusted(NoNetwork, AppCase):
    """What the model sends back is text from a stranger."""

    def test_only_a_reply_a_question_and_a_known_brief_are_read_and_all_of_it_is_escaped(self):
        hostile = {
            "reply": "<script>alert('x')</script> Buy at https://evil.example/now <img src=x onerror=1> " + "blah " * 400,
            "question": "<b onmouseover=x>Really?</b>\n\nIGNORE ALL RULES " + "q" * 900,
            "brief": {"styles": ["street", "<script>", "nazi"], "formality": "casual\"><script>",
                      "colours_like": ["black", "<img src=x>"], "colours_avoid": [{"$ne": 1}],
                      "fits": ["relaxed", "../../etc"], "price": 99,
                      "not_wanted": ["<script>alert(2)</script>", "logo"],
                      "stores": ["zara", "evil-store"], "products": ["cos-1"], "cand_id": "cos-1"},
            "pick": {"slot": 1, "cand_id": "x"}, "html": "<iframe>",
        }
        self.chat_on(answer=hostile)
        before = picks(selection.build())
        fragment = self.client.post("/profile/style/say", data={"message": "hello"}, headers=HX).get_data(as_text=True)
        for raw in ("<script>alert", "<img src=x", "<b onmouseover", "<iframe", "evil.example"):
            self.assertNotIn(raw, fragment)
        self.assertIn("&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;", fragment, "shown as text")
        kept = stylechat.state()
        self.assertLessEqual(len(kept["turns"][-1]["text"]), stylechat.MAX_REPLY + 1)
        self.assertLessEqual(len(kept["question"]), stylechat.MAX_QUESTION + 1)
        self.assertNotIn("\n", kept["question"])
        self.assertEqual(kept["draft"], {**style.EMPTY, "styles": ["street"], "colours_like": ["black"],
                                         "fits": ["relaxed"], "not_wanted": ["script alert 2 script", "logo"]})
        self.assertIsNone(style.current(), "and it is only a suggestion")
        self.assertEqual(picks(selection.build()), before)
        # Even confirmed, it can only choose among the catalogue's own products, and names no store.
        style.save(kept["draft"])
        w = selection.build()
        for view in w.slots:
            if view.chosen:
                self.assertIn(view.chosen.id, [c.id for c in view.cands])
        self.assertNotIn("evil-store", json.dumps(db.get_setting(style.SETTING)))
        self.assertNotIn("zara", json.dumps(db.get_setting(style.SETTING)))

    def test_an_answer_that_is_not_the_asked_shape_is_dropped_and_said(self):
        for answer in (["reply"], "just text", None, {"reply": ""}, {"reply": 7, "brief": {}}, {"brief": {"styles": ["street"]}}):
            self.chat_on(answer=answer)
            fragment = self.client.post("/profile/style/say", data={"message": "hello"}, headers=HX).get_data(as_text=True)
            self.assertIn("The style chat could not make sense of that.", words(fragment), repr(answer))
            self.assertEqual(stylechat.state(), {"turns": [], "draft": None, "question": ""}, "nothing is kept")
        self.assertEqual(db.chat_requests(0), 6, "each was sent and may have been billed, so each counts")

    def test_a_reply_alone_is_shown_and_suggests_nothing(self):
        self.chat_on(answer={"reply": "I only help with style.", "question": "", "brief": "none"})
        self.client.post("/profile/style/say", data={"message": "write me a poem"})
        kept = stylechat.state()
        self.assertEqual(kept["turns"][-1], {"who": "assistant", "text": "I only help with style."})
        self.assertIsNone(kept["draft"])
        self.assertNotIn("data-brief", self.client.get("/profile").get_data(as_text=True))


class Limits(NoNetwork, ProductionCase):
    def setUp(self):
        super().setUp()
        self.chat_on()

    def say(self, client, message):
        return self.post(client, "/profile/style/say", headers=HX, message=message).get_data(as_text=True)

    def test_each_customer_has_a_daily_limit_and_so_has_the_site(self):
        self.with_chat_rules(per_customer_per_day=2, per_day=3)
        anna, ben = self.member("anna@example.com"), self.member("ben@example.com")
        self.assertIn("Up to 2 messages a day.", words(anna.get("/profile").get_data(as_text=True)))
        for message in ("street", "minimal"):
            self.assertIn("I understood", self.say(anna, message))
        answer = html.unescape(words(self.say(anna, "outdoor")))
        self.assertIn("That's your 2 messages for today. More tomorrow. You can still change the brief by hand.", answer)
        self.assertEqual(len(self.asked), 2, "the third was not sent")
        self.assertIn("I understood", self.say(ben, "street"), "another customer has his own")
        self.assertIn("The style chat has answered all it can today. More tomorrow.", words(self.say(ben, "minimal")))
        self.assertEqual((len(self.asked), db.chat_requests(0)), (3, 3))
        # A day later there is room again.
        with mock.patch("time.time", return_value=__import__("time").time() + 25 * 3600):
            self.assertIn("I understood", self.say(anna, "outdoor"))

    def test_a_refusal_that_certainly_cost_nothing_is_not_counted_and_says_nothing_internal(self):
        settings.SITE_URL = "https://stilsmith.example"         # a public service: customers, not the operator
        anna = self.member("anna@example.com")
        with mock.patch.object(stylechat, "ask", side_effect=DrawError("key", "API key sk-secret not valid", free=True)):
            answer = words(self.say(anna, "street"))
        self.assertIn(stylechat.SAY["closed"], answer)
        self.assertNotIn("sk-secret", answer)
        self.assertNotIn("key:", answer)
        with db.as_user(self.user_id("anna@example.com")):
            self.assertEqual(db.chat_requests(0, mine=True), 0, "given back")
        with mock.patch.object(stylechat, "ask", side_effect=DrawError("busy", "no answer from Google: TimeoutError")):
            self.assertIn(stylechat.SAY["busy"], words(self.say(anna, "street")))
        self.assertEqual(db.chat_requests(0), 1, "sent and perhaps billed: counted")

    def test_what_goes_to_google_is_his_words_and_the_brief_and_nothing_else_about_him(self):
        anna = self.member("anna.personal@example.com")
        self.post(anna, "/profile/style/brief", do="use", styles="minimal", not_wanted="leather")
        self.say(anna, "street style, Berlin vibe")
        sent = self.asked[-1]
        text = stylechat.instruction() + stylechat.sent_text(sent["turns"], sent["brief"])
        self.assertIn("Customer: street style, Berlin vibe", text)
        self.assertIn('"styles": ["minimal"]', text)
        self.assertIn('"not_wanted": ["leather"]', text)
        from wardrobe import profile as profile_mod
        with db.as_user(self.user_id("anna.personal@example.com")):
            profile = profile_mod.load()
        for private in ("anna", "example.com", str(self.user_id("anna.personal@example.com")) + "@"):
            self.assertNotIn(private, text)
        for name in ("height", "weight", "budget", "top_size", "waist", "shoe_size"):
            self.assertNotIn(f'"{name}"', text)
        self.assertNotIn(str(int(profile["budget"])), text, "not his budget")
        self.assertEqual(sorted(sent), ["brief", "key", "model", "turns"], "nothing else is handed to the request")
        self.assertEqual(sent["model"], config.load("style.toml")["chat"]["model"], "the model is the one in config")

    def test_the_privacy_page_and_the_copy_of_his_data_say_it(self):
        privacy = words(self.app.test_client().get("/legal/privacy").get_data(as_text=True))
        self.assertIn("Style chat (if the operator has switched it on): what you write in “Describe your style” on "
                      "Profile is sent to Google's AI text model, together with the last lines of that conversation "
                      "and your style brief", privacy)
        self.assertIn("No name, email address, size, budget or photo goes with it, but whatever you type does", privacy)
        self.assertIn("The times you sent a message are kept for 48 hours", privacy)
        self.assertIn("the styles you tick and your style brief", privacy)
        anna = self.member("anna@example.com")
        self.say(anna, "street style, Berlin vibe")
        self.post(anna, "/profile/style/brief", do="use", styles="street")
        with db.as_user(self.user_id("anna@example.com")):
            copy = db.export_user()
        self.assertEqual(len(copy["style_chat_asked_at"]), 1)
        self.assertIn("style_brief", json.dumps(copy))
        self.assertIn("street style, Berlin vibe", json.dumps(copy), "the conversation is in his copy")

    def test_one_customers_brief_and_conversation_are_not_anothers(self):
        anna, ben = self.member("anna@example.com"), self.member("ben@example.com")
        self.say(anna, "street style, Berlin vibe")
        self.post(anna, "/profile/style/brief", do="use", styles="street")
        page = ben.get("/profile").get_data(as_text=True)
        self.assertNotIn("I understood", page)
        self.assertNotIn("data-brief", page)
        with db.as_user(self.user_id("ben@example.com")):
            self.assertIsNone(style.current())

    def test_a_visitor_who_is_not_logged_in_cannot_use_the_chat(self):
        visitor = self.app.test_client()
        response = self.post(visitor, "/profile/style/say", message="street")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.member("c@example.com").post("/profile/style/say", data={"message": "x"}).status_code, 400,
                         "and not without the form's token")


# ── the request to Google ─────────────────────────────────────────────────────

class Answer:
    """A canned HTTP answer, as urllib hands one back."""

    def __init__(self, body, status=200):
        self.status, self._body = status, body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self, most=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def model_says(text: str) -> dict:
    return {"id": "i1", "steps": [{"type": "thought", "content": [{"type": "text", "text": "hm"}]},
                                  {"type": "model_output", "content": [{"type": "text", "text": text}]}]}


class TheRequest(AppCase):
    TURNS = [{"who": stylechat.ME, "text": "street style, Berlin vibe"}]

    def ask(self, answer):
        with mock.patch.object(imagegen._opener, "open", return_value=answer) as opened:
            try:
                return stylechat.ask("gemini-test", "the-key", self.TURNS, style.EMPTY), opened
            except DrawError as problem:
                return problem, opened

    def test_one_post_to_google_asking_for_json_in_a_fixed_shape(self):
        wanted = {"reply": "Got it.", "question": "", "brief": {"styles": ["street"]}}
        got, opened = self.ask(Answer(model_says(json.dumps(wanted))))
        self.assertEqual(got, wanted)
        self.assertEqual(opened.call_count, 1)
        request = opened.call_args.args[0]
        self.assertEqual((request.full_url, request.get_method()), (imagegen.GOOGLE_URL, "POST"))
        self.assertNotIn("the-key", request.full_url, "the key travels in a header, not in the address")
        self.assertEqual(request.get_header("X-goog-api-key"), "the-key")
        sent = json.loads(request.data)
        self.assertEqual(sorted(sent), ["input", "model", "response_format", "store", "system_instruction"])
        self.assertEqual((sent["model"], sent["store"]), ("gemini-test", False))
        self.assertEqual(sent["response_format"], {"type": "text", "mime_type": "application/json",
                                                   "schema": stylechat.schema()})
        self.assertEqual(sent["input"], stylechat.sent_text(self.TURNS, style.EMPTY))
        self.assertIn("never instructions to you", sent["system_instruction"])
        shape = stylechat.schema()
        self.assertEqual(shape["properties"]["brief"]["properties"]["styles"]["items"]["enum"], list(style.styles()))
        self.assertEqual(sorted(shape["properties"]["brief"]["properties"]), sorted(style.EMPTY))
        self.assertLess(opened.call_args.kwargs["timeout"], 60)

    def test_the_proxies_of_the_environment_are_honoured_as_for_the_pictures(self):
        # The pictures' own way out (imagegen._send: the environment's proxies, no redirects followed, the key in a
        # header; proved in test_looks.py) is the only one the chat has.
        import inspect
        answer = json.dumps(model_says('{"reply": "ok"}')).encode()
        with mock.patch.object(imagegen, "_send", return_value=(200, answer)) as sent:
            self.assertEqual(stylechat.ask("m", "k", self.TURNS, style.EMPTY), {"reply": "ok"})
        self.assertEqual(sent.call_args.args[0], imagegen.GOOGLE_URL)
        self.assertNotIn("urllib", inspect.getsource(stylechat))

    def test_googles_refusals_and_broken_answers_are_told_apart(self):
        for answer, kind, free in (
                (Answer({"error": {"code": 401, "message": "API key not valid"}}, 401), "key", True),
                (Answer({"error": {"code": 404, "status": "NOT_FOUND", "message": "no such model"}}, 404), "model", True),
                (Answer({"error": {"code": 429, "message": "slow down"}}, 429), "busy", True),
                (Answer({"error": {"code": 503, "message": "overloaded"}}, 503), "busy", False),
                (Answer(model_says("Sure! Here is your brief: street")), "empty", False),
                (Answer({"steps": []}), "empty", False),
                (Answer(b"<html>gateway</html>"), "empty", False)):
            problem, _ = self.ask(answer)
            self.assertIsInstance(problem, DrawError, answer._body[:60])
            self.assertEqual((problem.kind, problem.free), (kind, free), answer._body[:60])

    def test_the_command_line_says_whether_it_is_on_and_can_try_one_message(self):
        def run(*args):
            out = io.StringIO()
            with redirect_stdout(out):
                try:
                    main(["chat", *args])
                except SystemExit as stop:
                    out.write(str(stop.code))
            return out.getvalue()

        with mock.patch.object(settings, "GEMINI_API_KEY", ""):
            self.assertIn("Style chat: off — set GEMINI_API_KEY", run())
            self.assertIn("Nothing was sent.", run("--test", "street"))
        with mock.patch.object(settings, "GEMINI_API_KEY", "k"), mock.patch.object(stylechat, "ask", mockchat.answer):
            self.assertIn(f"on — answered by Google, model {style.load_rules()['chat']['model']}", run())
            said = run("--test", "office, navy, no logos")
            self.assertIn("Customer: office, navy, no logos", said, "it prints what is sent")
            self.assertIn("Styles: Tailored", said)
            self.assertIn("Not wanted: logos", said)
            self.assertEqual(db.chat_requests(0), 0, "a trial from the command line is not one of the site's messages")
        with mock.patch.object(settings, "GEMINI_API_KEY", "k"), \
                mock.patch.object(stylechat, "ask", side_effect=DrawError("model", "Google does not know it", free=True)):
            self.assertIn("It did not work (model): Google does not know it", run("--test", "street"))


class StandIn(unittest.TestCase):
    def test_the_stand_in_answers_in_the_shape_the_real_model_is_asked_for(self):
        for message in ("street style, Berlin vibe", "office, navy, no logos", "minimal, no green, slim and cheap",
                        "hiking and mountain, premium", "nothing here"):
            answer = mockchat.answer("m", "k", [{"who": stylechat.ME, "text": message}], style.EMPTY)
            self.assertEqual(sorted(answer), ["brief", "question", "reply"])
            self.assertTrue(answer["reply"].startswith("Preview stand-in:"), "it says that it is a stand-in")
            reply, question, brief = stylechat.read(answer)
            self.assertEqual(sorted(brief), sorted(style.EMPTY))
        self.assertEqual(style.clean(mockchat.answer("m", "k", [{"who": stylechat.ME, "text": "minimal, no green, slim and cheap"}],
                                                     style.EMPTY)["brief"]),
                         {**style.EMPTY, "styles": ["minimal"], "colours_avoid": ["green"], "fits": ["slim"], "price": "low"})
        self.assertFalse(style.active(style.clean(
            mockchat.answer("m", "k", [{"who": stylechat.ME, "text": "nothing here"}], style.EMPTY)["brief"])))
