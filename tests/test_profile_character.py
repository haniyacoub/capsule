"""Profile as a character screen: the drawn figure in the middle, the tabs around it, one form and one Save.

The figure (figure.py) is checked by its outlines: every build, height, skin, haircut and beard draws differently, and
every build's outlines can be blended into another's. The page is checked as it is sent: one form holding every field
(the model's choices too), the tabs (shown by app.js) and the figure in words. Saving is checked as it was before,
with the model's choices now in the same form. "Your model" (the AI picture of the saved model) is drawn by a stand-in.
"""
import html
import json
import re
from pathlib import Path
from unittest import mock

from wardrobe import colours, figure, looks, outfits, person, selection, settings
from wardrobe import profile as profile_mod

from .test_app import HX, AppCase
from .test_looks import WithPictures

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def numbers(path: str) -> list[float]:
    return [float(n) for n in NUMBER.findall(path)]


def widest(path: str, low: float, high: float) -> float:
    """The largest x of an outline's points between two heights (each point is an "x y" pair)."""
    values = numbers(path)
    return max(x for x, y in zip(values[::2], values[1::2]) if low <= y <= high)


class TheFigure(AppCase):
    def test_every_build_draws_its_own_body_and_each_blends_into_the_others(self):
        bodies = {build: figure.body(build) for build in figure.BUILDS}
        for part in ("skin", "tee", "briefs", "lines", "creases"):
            outlines = {build: body[part] for build, body in bodies.items()}
            self.assertEqual(len(set(outlines.values())), 5, f"two builds draw the same {part}")
            # Blending (app.js 13b) moves each number of one outline towards the same number of the other: the
            # outlines have the same commands and the same count of numbers.
            shapes = {NUMBER.sub("#", outline) for outline in outlines.values()}
            self.assertEqual(len(shapes), 1, f"the builds' {part} outlines cannot be blended into each other")
        shoulders = {build: widest(body["tee"], 60, 100) for build, body in bodies.items()}
        self.assertLess(shoulders["slim"], shoulders["average"])
        self.assertLess(shoulders["average"], shoulders["athletic"])
        self.assertLess(shoulders["athletic"], shoulders["broad"])
        waists = {build: widest(body["tee"], 140, 160) for build, body in bodies.items()}
        self.assertEqual(max(waists, key=lambda build: waists[build]), "heavy", f"the heavy build's waist: {waists}")
        self.assertLess(waists["athletic"] - shoulders["athletic"], waists["average"] - shoulders["average"],
                        "the athletic build does not narrow more from shoulders to waist")
        self.assertEqual(figure.drawing({}, 180)["body"], bodies["average"], "'Any' does not draw the average build")

    def test_the_figure_grows_from_the_floor_with_the_height(self):
        menu = [figure.scale({"height": key}, 180) for key in ("short", "medium", "tall")]
        self.assertEqual(menu, sorted(menu))
        self.assertEqual(len(set(menu)), 3)
        self.assertEqual(figure.scale({}, 180), 1.0)                       # "Any": the customer's own height
        self.assertEqual(figure.scale({}, 198), 1.1)
        self.assertEqual(figure.scale({}, 120), 140 / 180, "under the form's lowest height")
        self.assertEqual(figure.scale({}, 260), 220 / 180, "over the form's highest height")
        self.assertEqual(figure.scale({"height": "tall"}, 150), figure.HEIGHTS_CM["tall"] / 180, "the model's height wins")
        for s in (140 / 180, 1.0, 220 / 180):
            a, b, c, d, e, f = (float(n) for n in NUMBER.findall(figure.transform(s)))
            self.assertAlmostEqual(d * 400 + f, 400, places=1, msg="the soles leave the floor")
            self.assertEqual((a, b, c, e), (round(s, 4), 0, 0, 0))

    def test_the_figure_stays_inside_its_frame_at_every_height_and_build(self):
        # The frame (_figure.html's viewBox): x from -130 to 130, y from -100 to 410. Measured on the points that
        # shape the curves, which hold the curves inside them.
        frame = re.search(r'viewBox="([-\d. ]+)"', (Path(__file__).parent.parent / "wardrobe/templates/_figure.html")
                          .read_text()).group(1).split()
        left, top, width, height = (float(n) for n in frame)
        for cm in range(figure.LOWEST_CM, figure.HIGHEST_CM + 1, 5):
            for build in figure.BUILDS:
                for cut in ("long", "curly", "medium"):
                    drawn = figure.drawing({"build": build, "cut": cut, "beard": "full"}, cm)
                    s = drawn["scale"]
                    outlines = [drawn["body"][part] for part in ("skin", "tee", "briefs")] + [drawn["hair"], drawn["hair_back"],
                                                                                                drawn["beard"], drawn["ears"]]
                    values = [n for outline in outlines for n in numbers(outline)]
                    xs = [x * s for x in values[::2]]
                    ys = [400 - (400 - y) * s for y in values[1::2]]
                    self.assertGreaterEqual(min(xs), left + 2, (cm, build, cut))
                    self.assertLessEqual(max(xs), left + width - 2, (cm, build, cut))
                    self.assertGreaterEqual(min(ys), top + 2, (cm, build, cut, min(ys)))
                    self.assertLessEqual(max(ys), top + height, (cm, build, cut))

    def test_skin_hair_and_beard_draw_what_was_chosen(self):
        skins = {o.key: figure.drawing({"skin": o.key}, 180)["skin"] for o in person.GROUPS["skin"][1]}
        self.assertEqual(skins, {o.key: o.swatch for o in person.GROUPS["skin"][1]})
        self.assertEqual(figure.drawing({}, 180)["skin"], figure.PAPER, "'Any' skin is not left unpainted")
        hair = {o.key: figure.drawing({"hair": o.key}, 180)["hair_colour"] for o in person.GROUPS["hair"][1]}
        self.assertEqual(hair, {o.key: o.swatch for o in person.GROUPS["hair"][1]})
        cuts = {o.key: figure.drawing({"cut": o.key}, 180) for o in person.GROUPS["cut"][1]}
        self.assertEqual(len({drawn["hair"] for drawn in cuts.values()}), len(cuts), "two haircuts look the same")
        self.assertTrue(cuts["long"]["hair_back"] and not cuts["short"]["hair_back"], "long hair falls behind the neck")
        self.assertTrue(cuts["shaved"]["shaved"])
        self.assertEqual(figure.drawing({}, 180)["hair"], cuts["short"]["hair"], "'Any' does not draw the short cut")
        beards = {o.key: figure.drawing({"beard": o.key}, 180)["beard"] for o in person.GROUPS["beard"][1]}
        self.assertEqual(beards["none"], "")
        self.assertEqual(len({beards[key] for key in ("stubble", "full")}), 2)
        self.assertEqual(figure.drawing({}, 180)["beard"], "")

    def test_the_fine_lines_on_the_skin_read_on_every_skin_tone(self):
        # The brows, nose and mouth, the knees and the thumbs: in ink they vanished on brown and dark skin (1.7:1 and
        # 1.2:1). Each skin tone has its own colour for them, at least 3:1 against it, as "Any" (the paper) has.
        def luminance(colour: str) -> float:
            channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        def contrast(a: str, b: str) -> float:
            light, dark = sorted((luminance(a), luminance(b)), reverse=True)
            return (light + 0.05) / (dark + 0.05)

        tones = [(o.key, o.swatch) for o in person.GROUPS["skin"][1]] + [("", figure.PAPER)]
        for key, skin in tones:
            drawn = figure.drawing({"skin": key} if key else {}, 180)
            self.assertEqual(drawn["skin"], skin)
            self.assertGreaterEqual(contrast(drawn["detail"], skin), 3.0, f"the lines on {key or 'any'} skin")
        self.assertEqual({key: entry["detail"] for key, entry in figure.data()["skin"].items()}, figure.DETAIL)
        self.assertEqual(figure.data()["paperDetail"], figure.drawing({}, 180)["detail"])

    def test_every_choice_on_the_menu_can_be_drawn(self):
        for group, (_, options) in person.GROUPS.items():
            for option in options:
                drawn = figure.drawing({group: option.key}, 180)
                self.assertTrue(drawn["body"]["skin"] and drawn["face"] and drawn["words"], (group, option.key))

    def test_the_figure_in_words(self):
        self.assertEqual(figure.words({}, 180), "180 cm, any build, any skin tone, any hair")
        self.assertEqual(figure.words({"height": "tall", "build": "athletic", "skin": "medium", "hair": "dark-brown",
                                       "cut": "short", "beard": "stubble"}, 172),
                         "Tall, athletic build, medium skin, short dark-brown hair, stubble")
        self.assertEqual(figure.words({"cut": "shaved", "hair": "red", "beard": "none"}, 191),
                         "191 cm, any build, any skin tone, shaved head, clean-shaven")
        self.assertEqual(figure.words({"hair": "blond"}, 300), "220 cm, any build, any skin tone, blond hair")
        self.assertEqual(figure.words({"cut": "curly", "beard": "full", "height": "medium"}, 180),
                         "Average height, any build, any skin tone, curly hair, full beard")

    def test_what_the_page_needs_to_redraw_it(self):
        data = figure.data()
        self.assertEqual(set(data["builds"]), set(figure.BUILDS))
        self.assertEqual(set(data["hair"]), {o.key for o in person.GROUPS["cut"][1]})
        self.assertEqual(set(data["beards"]), {"none"} | {o.key for o in person.GROUPS["beard"][1]})
        self.assertEqual(data["heights"], figure.HEIGHTS_CM)
        self.assertEqual(set(data["heights"]), {o.key for o in person.GROUPS["height"][1]})
        self.assertEqual(data["skin"]["dark"], {"colour": "#4a2f22", "detail": figure.DETAIL["dark"], "label": "dark"})
        self.assertEqual(data["hairColour"]["dark-brown"]["label"], "dark-brown")


class ThePage(AppCase):
    def page(self) -> str:
        return self.client.get("/profile").data.decode()

    def test_one_form_with_every_field_and_one_save(self):
        page = self.page()
        about = page[page.index('<form class="form" id="about-you"'):]
        about = about[:about.index("</form>")]
        for group in person.GROUPS:          # the model's choices are in the same form now
            self.assertIn(f'name="{group}"', about, group)
        for name in ("use", "shoes", "outerwear", "owned", "top_size", "shoe", "waist", "length", "height_cm",
                     "weight_kg", "chest_cm", "waist_cm", "liked", "refused", "budget"):
            self.assertIn(f'name="{name}"', about, name)
        self.assertEqual(re.findall(r"<button[^>]*>(Save[^<]*)</button>", page), ["Save profile"], "one Save button")
        self.assertIn('<button class="btn" form="about-you">Save profile</button>', page, "Save sends the form")
        self.assertNotIn("/profile/model", page, "the model's own form is gone")
        self.assertIn('name="tab" value=""', about, "the form cannot say which tab it was sent from")

    def test_tabs_and_their_panels(self):
        page = self.page()
        tablist = re.search(r'<div class="cc-tabs" role="tablist" aria-label="Your profile" data-cc-tabs hidden>(.*?)</div>',
                            page, re.S)
        self.assertIsNotNone(tablist, "no tablist, or shown before the script makes it work")
        tabs = re.findall(r'<button type="button" role="tab" id="tab-(\w+)" aria-controls="([\w -]+)" '
                          r'aria-selected="false" tabindex="-1">(\w+)</button>', tablist.group(1))
        self.assertEqual([(key, label) for key, _, label in tabs],
                         [("you", "You"), ("body", "Body"), ("sizes", "Sizes"), ("colours", "Colours"), ("budget", "Budget"),
                          ("stores", "Stores")])
        for key, controls, _ in tabs:
            for panel in controls.split():
                self.assertRegex(page, rf'<section class="cc-panel[^"]*" id="{panel}" data-tab="{key}" aria-labelledby="tab-{key}">')
        # Where the old anchors lead: each inside its tab's panel.
        for anchor, tab in (("sizes", "sizes"), ("budget", "budget"), ("model", "body"), ("colours-label", "colours"),
                            ("stores", "stores")):
            panel = page.rindex('class="cc-panel', 0, page.index(f'id="{anchor}"'))
            self.assertIn(f'data-tab="{tab}"', page[panel:panel + 120], anchor)
        self.assertEqual(set(profile_mod.TABS), {key for key, _, _ in tabs})

    def test_the_figure_is_decoration_said_in_words(self):
        person.save({"build": "athletic", "skin": "tan", "hair": "black", "cut": "curly", "height": "tall"})
        page = self.page()
        svg = re.search(r"<svg class=\"fig\"[^>]*>", page).group(0)
        self.assertIn('aria-hidden="true"', svg)
        self.assertIn(f"--skin: #b07d55; --detail: {figure.DETAIL['tan']}; --hair: #1c1a19", svg)
        self.assertIn('class="fig-creases" data-part="creases"', page, "the lines on the skin are not drawn")
        self.assertIn(f'<p class="cc-words" data-figure-words>{figure.words(person.load(), 180)}</p>', page)
        self.assertIn("Tall, athletic build, tan skin, curly black hair", page)
        self.assertIn(f'transform="{figure.transform(figure.HEIGHTS_CM["tall"] / 180)}"', page)
        self.assertIn(figure.body("athletic")["skin"], html.unescape(page))
        data = json.loads(html.unescape(re.search(r'<script type="application/json" id="figure-data">(.*?)</script>',
                                                  page, re.S).group(1)))
        self.assertEqual(data["builds"]["heavy"], figure.body("heavy"))

    def test_the_figure_follows_the_saved_height_on_any(self):
        profile_mod.save({**profile_mod.load(), "height_cm": 198})
        self.assertIn(f'transform="{figure.transform(1.1)}"', self.page())
        # … and, his body now being his own, the build his height and weight give (78 kg at 198 cm is slim): the one
        # the AI pictures are asked for (tests/test_body.py).
        self.assertIn("198 cm, slim build, any skin tone", self.page())


class Saving(AppCase):
    """The model's choices come with the one form; everything else saves exactly as before (test_app.py)."""

    def form(self, **changes) -> dict:
        """The form as the page sends it: today's answers and today's model (Any as ""), with these changes."""
        p = profile_mod.load()
        model = person.load()
        names = {k: v.label.lower() for k, v in colours.COLOURS.items()}
        data = {"top_size": p["top_size"], "waist": p["waist"], "length": p["length"], "shoe": p["shoe"],
                "height_cm": p["height_cm"], "weight_kg": p["weight_kg"], "budget": p["budget"],
                "liked": ", ".join(names[k] for k in p["liked"]), "refused": ", ".join(names[k] for k in p["refused"]),
                "use": p["use"], "owned": p["owned"], "shoes": "on" if p["shoes"] else None,
                "outerwear": "on" if p["outerwear"] else None, "tab": "",
                **{group: model.get(group, "") for group in person.GROUPS}}
        data.update(changes)
        return {k: v for k, v in data.items() if v is not None}

    def model_part(self) -> str:
        page = self.client.get("/profile").data.decode()
        return page[page.index('id="model"'):page.index('id="panel-sizes"')]

    def test_a_new_model_alone_is_saved_as_the_models_own_button_did(self):
        before = profile_mod.load()
        self.assertTrue(before["example"])
        saved = self.client.post("/profile", data=self.form(build="athletic", age="30s", cut="short", hair="brown"))
        self.assertTrue(saved.headers["Location"].endswith("/profile#model"), saved.headers["Location"])
        self.assertEqual(person.load(), {"build": "athletic", "age": "30s", "cut": "short", "hair": "brown"})
        self.assertEqual(profile_mod.load(), before, "the profile was saved too: it is no longer the example's")
        model = self.model_part()
        self.assertIn("Model saved. Pictures drawn from now on show it.", model)
        self.assertIn("an adult man in his thirties (athletic build; short brown hair)", model)

    def test_a_new_model_with_new_answers_saves_both(self):
        self.client.post("/profile", data=self.form())                   # his own answers, saved once
        self.client.get("/outfits")                                      # where that save's message was read
        # (A size, which leaves the plan as it is: a budget sizes the plan since 19 Nov 2026, and its save shows the
        # outfits of the plan made for it.)
        saved = self.client.post("/profile", data=self.form(build="slim", waist="33", tab="sizes"))
        self.assertTrue(saved.headers["Location"].endswith("/profile#sizes"), saved.headers["Location"])
        self.assertEqual(person.load(), {"build": "slim"})
        self.assertEqual(profile_mod.load()["waist"], 33)
        page = self.client.get("/profile").data.decode()
        said = re.findall(r'<p class="flash" role="status">(.*?)</p>', page, re.S)
        self.assertEqual(said[:2], ["Model saved. Pictures drawn from now on show it.",
                                    'Profile saved. <a href="/outfits">See your outfits</a>'])

    def test_new_answers_alone_leave_the_model_as_it_is(self):
        person.save({"build": "broad", "skin": "dark"})
        self.client.post("/profile", data=self.form(budget="1800"))
        self.assertEqual(person.load(), {"build": "broad", "skin": "dark"})
        self.assertEqual(profile_mod.load()["budget"], 1800)
        self.assertNotIn("Model saved", self.client.get("/profile").data.decode())

    def test_back_to_any_clears_the_model(self):
        person.save({"build": "broad", "beard": "full"})
        self.client.post("/profile", data=self.form(build="", beard=""))
        self.assertEqual(person.load(), {})

    def test_a_form_without_the_models_choices_leaves_the_model_alone(self):
        # A page from before (or a service without AI pictures, which shows no model menu).
        person.save({"build": "broad"})
        form = {k: v for k, v in self.form(budget="1700").items() if k not in person.GROUPS}
        self.client.post("/profile", data=form)
        self.assertEqual(person.load(), {"build": "broad"})

    def test_back_to_the_tab_it_was_sent_from(self):
        self.client.post("/profile", data=self.form())
        for tab, where in (("budget", "/profile#budget"), ("colours", "/profile#colours"), ("nowhere", "/profile"),
                           ("", "/profile")):
            saved = self.client.post("/profile", data=self.form(shoe=str(40 + len(tab)), tab=tab))   # (a size)
            self.assertTrue(saved.headers["Location"].endswith(where), (tab, saved.headers["Location"]))

    def test_the_model_saved_from_the_one_form_is_the_one_described(self):
        self.client.post("/profile", data=self.form(skin="purple", beard="<script>", height="tall"))
        self.assertEqual(person.load(), {"height": "tall"}, "only choices from the menu are kept")


class YourModel(WithPictures, AppCase):
    """'Your model': the AI picture of the saved model, in the first outfit Outfits shows."""

    def setUp(self):
        super().setUp()
        self.switch_on()

    def first_outfit(self):
        chosen, _ = outfits.generate(selection.build(), occasion="all", limit=12)
        return chosen[0]

    def test_draw_my_model_draws_the_first_outfit_once(self):
        page = self.client.get("/profile").data.decode()
        self.assertIn("Draw my model", page)
        self.assertIn('data-cc-switch hidden', page)
        self.assertIn('<button type="button" aria-pressed="false" data-show="picture">Your model</button>', page)
        drawn = self.client.post("/profile/picture", headers=HX).data.decode()
        self.assertEqual(len(self.drawn), 1)
        self.assertIn('class="cc-pic-img"', drawn)
        self.assertIn("AI picture", drawn)
        # The same picture as the first outfit's on Outfits: shown there, never drawn again.
        board = {"pieces": outfits.snapshot(self.first_outfit())}
        looks.attach([board])
        self.assertEqual(board["look"].status, "ready")
        self.assertIn(board["look"].file, self.client.get("/outfits").data.decode())
        self.assertIn(board["look"].file, self.client.get("/profile").data.decode())
        self.assertIn(board["look"].file, self.client.get("/profile/picture").data.decode())
        self.client.post("/profile/picture", headers=HX)
        self.assertEqual(len(self.drawn), 1, "asked twice, drawn twice")
        again = self.client.post("/profile/picture", data={"again": "1"}, headers=HX).data.decode()
        self.assertEqual(len(self.drawn), 2, "'Draw again' did not draw again")
        # "Draw again" draws the saved choices too: the line that says to save first (shown by app.js while the form
        # has changes) is under it, as it is beside "Draw my model".
        foot = again[again.index('<div class="cc-pic-again">'):]
        self.assertLess(foot.index("Draw again"), foot.index("data-unsaved-note"))
        self.assertIn("Save first: the picture shows the choices you saved.", foot[:foot.index("</div>")])

    def test_it_draws_the_saved_model(self):
        person.save({"build": "heavy", "beard": "full"})
        self.client.post("/profile/picture", headers=HX)
        self.assertIn("heavy build", self.drawn[0]["prompt"])
        self.assertIn("a full beard", self.drawn[0]["prompt"])
        person.save({"build": "slim"})          # a new model: a new picture to draw
        self.assertIn("Draw my model", self.client.get("/profile/picture").data.decode())

    def test_while_it_is_drawn_the_page_asks_again(self):
        waiting = []
        with mock.patch.object(looks, "_spawn", waiting.append):
            drawing = self.client.post("/profile/picture", headers=HX).data.decode()
        self.assertIn("Drawing your model", drawing)
        self.assertIn('hx-get="/profile/picture" hx-trigger="load delay:3s"', drawing)
        waiting.pop()()
        self.assertIn('class="cc-pic-img"', self.client.get("/profile/picture").data.decode())

    def test_the_days_limit_is_said(self):
        self.with_rules(per_day=0)
        said = html.unescape(self.client.post("/profile/picture", headers=HX).data.decode())
        self.assertEqual(self.drawn, [])
        self.assertIn("Today's pictures are used up.", said)
        self.assertIn("Draw my model", said)

    def test_the_days_limit_on_draw_again_is_said_under_it_and_the_picture_stays(self):
        self.client.post("/profile/picture", headers=HX)
        self.with_rules(per_day=1)
        said = html.unescape(self.client.post("/profile/picture", data={"again": "1"}, headers=HX).data.decode())
        self.assertEqual(len(self.drawn), 1, "drawn over the day's limit")
        self.assertIn('class="cc-pic-img"', said, "the picture there went")
        foot = said[said.index('<div class="cc-pic-again">'):]
        foot = foot[:foot.index("</div>")]
        self.assertIn("Draw again", foot)
        self.assertRegex(foot, r'<p class="cc-pic-note" role="status">[^<]*used up', "the limit is not said under Draw again")

    def test_without_javascript_back_to_the_page(self):
        sent = self.client.post("/profile/picture")
        self.assertTrue(sent.headers["Location"].endswith("/profile#figure"))
        self.assertEqual(len(self.drawn), 1)


class YourModelSwitchedOff(AppCase):
    def test_no_picture_and_no_switch_without_ai_pictures(self):
        with mock.patch.object(settings, "OPENAI_API_KEY", ""), mock.patch.object(settings, "GEMINI_API_KEY", ""):
            page = self.client.get("/profile").data.decode()
            self.assertNotIn("data-model-picture", page)
            self.assertNotIn("data-cc-switch", page)
            self.assertIn("data-figure", page, "the drawn figure needs no AI")
            self.assertEqual(self.client.get("/profile/picture").status_code, 404)
            self.assertEqual(self.client.post("/profile/picture").status_code, 404)
