"""The body on Profile reaches the AI pictures: height and weight as a build in words, chest against waist as a
comparison, never as numbers. A new body means new pictures; a customer who changed nothing keeps the ones he has.
What is sent is said on Profile and on the privacy page, and the drawn figure takes the same build."""
import hashlib
import io
import re

from wardrobe import colours, figure, looks, person
from wardrobe import profile as profile_mod

from .test_app import AppCase
from .test_production import ProductionCase
from .test_looks import PHOTO, WithPictures, look_key, some_outfits

# The words the standard front picture is asked for, as a fingerprint of the whole description of looks.SAMPLE.
# It must not change for a customer who changed nothing: a different description is a different picture, drawn and
# paid for again. (It changed once on purpose, in round 6: the front picture moved from a light-grey studio to a
# white one, in new words, and every picture is drawn anew. Before that it was a9222a284fca1c05.)
UNTOUCHED = "89098e042ecf3449"


def body(height=180, weight=78, chest=None, waist=None) -> dict:
    return {**profile_mod.EXAMPLE, "height_cm": height, "weight_kg": weight, "chest_cm": chest, "waist_cm": waist}


def sample_prompt() -> str:
    return looks.prompt([dict(piece) for piece in looks.SAMPLE], looks.load_rules(), person.current())


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class Saving(AppCase):
    def form(self, **changes) -> dict:
        """The Profile form as the page sends it: today's answers and today's model (Any as ""), with these changes."""
        p = profile_mod.load()
        model = person.load()
        names = {k: v.label.lower() for k, v in colours.COLOURS.items()}
        data = {"top_size": p["top_size"], "waist": p["waist"], "length": p["length"], "shoe": p["shoe"],
                "height_cm": p["height_cm"], "weight_kg": p["weight_kg"], "chest_cm": p["chest_cm"] or "",
                "waist_cm": p["waist_cm"] or "", "budget": p["budget"],
                "liked": ", ".join(names[k] for k in p["liked"]), "refused": ", ".join(names[k] for k in p["refused"]),
                "use": p["use"], "owned": p["owned"], "shoes": "on" if p["shoes"] else None,
                "outerwear": "on" if p["outerwear"] else None, "tab": "",
                **{group: model.get(group, "") for group in person.GROUPS}}
        data.update(changes)
        return {k: v for k, v in data.items() if v is not None}


class TheBodyInWords(AppCase):
    def test_height_and_weight_become_a_height_and_a_build_in_words(self):
        said = {(h, w): person.body_words(body(h, w))[:2] for h, w in
                ((160, 60), (170, 55), (172, 65), (180, 70), (181, 78), (180, 90), (172, 95), (190, 85), (198, 140))}
        self.assertEqual(said[(160, 60)], ("clearly shorter than average", "average build"))
        self.assertEqual(said[(170, 55)], ("a little shorter than average", "slim, narrow build"))
        self.assertEqual(said[(172, 65)], ("a little shorter than average", "lean build"))
        self.assertEqual(said[(180, 70)], ("of average height", "lean build"))
        self.assertEqual(said[(181, 78)], ("of average height", "average build"))
        self.assertEqual(said[(180, 90)], ("of average height", "solid, stocky build, a little soft round the middle"))
        self.assertEqual(said[(172, 95)], ("a little shorter than average", "heavy build with a full stomach"))
        self.assertEqual(said[(190, 85)], ("tall", "average build"))
        self.assertEqual(said[(198, 140)], ("very tall, with long legs", "very heavy build with a large, round stomach"))

    def test_chest_and_waist_are_a_comparison(self):
        shape = lambda chest, waist: person.body_words(body(chest=chest, waist=waist))[2]   # noqa: E731
        self.assertEqual(shape(108, 84), "broad chest and shoulders, narrow waist")
        self.assertEqual(shape(100, 86), "")                       # an ordinary difference: nothing to say
        self.assertEqual(shape(100, 97), "waist about as wide as the chest")
        self.assertEqual(shape(100, 110), "waist wider than the chest")
        self.assertEqual(shape(100, None), "")                     # one alone compares with nothing
        self.assertEqual(shape(None, 90), "")

    def test_no_number_ever_reaches_the_words(self):
        # A picture model given "172 cm, 95 kg" may print it on the picture. Every body the form takes, in words only.
        for height in range(140, 221, 4):
            for weight in range(40, 201, 8):
                for chest, waist in ((None, None), (98, 84), (120, 121), (110, 70)):
                    words, just_body = person.describe({}, body(height, weight, chest, waist))
                    self.assertFalse(re.search(r"\d", words + just_body), f"{height} cm, {weight} kg: {words!r}")
                    self.assertNotIn(" cm", words)
                    self.assertNotIn(" kg", words)

    def test_the_menu_wins_where_something_is_chosen_and_the_body_fills_in_any(self):
        heavy = body(172, 95)
        self.assertEqual(person.describe({}, heavy),
                         ("an adult man (a little shorter than average, heavy build with a full stomach)",
                          "a little shorter than average, heavy build with a full stomach"))
        self.assertEqual(person.describe({"build": "athletic", "age": "30s"}, heavy)[0],
                         "an adult man in his thirties (a little shorter than average, athletic build)")
        self.assertEqual(person.describe({"height": "tall", "hair": "brown", "cut": "short"}, heavy)[0],
                         "an adult man (tall, heavy build with a full stomach; short brown hair)")

    def test_the_examples_body_says_nothing(self):
        # 180 cm and 78 kg with no chest and waist are the example's, not yet the customer's own: nothing is worked
        # out from them, so the model is described exactly as before.
        self.assertFalse(person.own_body(profile_mod.EXAMPLE))
        self.assertFalse(person.own_body({**profile_mod.EXAMPLE, "example": False, "top_size": "L", "budget": 900}))
        self.assertEqual(person.body_words(profile_mod.EXAMPLE), ("", "", ""))
        self.assertEqual(person.describe({}, profile_mod.EXAMPLE), ("", ""))
        self.assertEqual(person.describe({}), ("", ""))
        for choices in ({"hair": "brown", "cut": "short"}, {"build": "slim", "height": "tall", "age": "40s"}):
            self.assertEqual(person.describe(choices, profile_mod.EXAMPLE), person.describe(choices))
        for own in (body(181), body(weight=79), body(chest=100), body(waist=84)):
            self.assertTrue(person.own_body(own))
            self.assertNotEqual(person.describe({}, own), ("", ""))


class ThePicturesFollowTheBody(WithPictures, Saving):
    def setUp(self):
        super().setUp()
        self.switch_on()

    def test_a_customer_who_changed_nothing_is_asked_for_in_the_same_words_as_before(self):
        self.assertEqual(digest(sample_prompt()), UNTOUCHED, "the untouched example profile draws a different picture")
        self.assertEqual(person.current(), person.Who())
        outfit = some_outfits(1)[0]
        before = look_key(outfit)
        # Saving Profile with the body as it was (new colours, a new budget) keeps every picture too.
        self.client.post("/profile", data=self.form(budget="900", top_size="L"))
        self.assertFalse(profile_mod.load()["example"])
        self.assertEqual(digest(sample_prompt()), UNTOUCHED)
        self.assertEqual(look_key(outfit), before)

    def test_a_new_body_is_a_new_picture_asked_for_in_its_words(self):
        outfit = some_outfits(1)[0]
        before = look_key(outfit)
        self.post("/outfits/look", key=outfit.key)
        self.assertIn("an adult male fashion model with an average build", self.drawn[0]["prompt"])
        old_page = self.client.get("/outfits").data.decode()
        self.assertIn(f"/looks/{before}", old_page)

        saved = self.client.post("/profile", data=self.form(height_cm="172", weight_kg="95", chest_cm="104",
                                                             waist_cm="102"), follow_redirects=True).data.decode()
        self.assertIn("Your model now follows your new measurements. Pictures drawn from now on show it.", saved)
        after = look_key(outfit)
        self.assertNotEqual(after, before, "the new body shows the old body's picture")
        self.assertNotIn(f"/looks/{before}", self.client.get("/outfits").data.decode())
        self.post("/outfits/look", key=outfit.key)
        asked = self.drawn[1]["prompt"].split("\n")[0]
        self.assertIn("an adult man (a little shorter than average, heavy build with a full stomach, "
                      "waist about as wide as the chest)", asked)
        self.assertNotIn("fashion model", asked)
        self.assertFalse(re.search(r"172|95|104|102", asked), "a measurement went along as a number")

        # Back to the body he had: the picture he had, without drawing again.
        self.client.post("/profile", data=self.form(height_cm="180", weight_kg="78", chest_cm="", waist_cm=""))
        self.assertEqual(look_key(outfit), before)
        self.assertIn(f"/looks/{before}", self.client.get("/outfits").data.decode())
        self.assertEqual(len(self.drawn), 2)

    def test_measurements_that_say_the_same_words_keep_the_pictures_and_say_nothing(self):
        self.client.post("/profile", data=self.form(height_cm="176", weight_kg="70"), follow_redirects=True)
        outfit = some_outfits(1)[0]
        before = look_key(outfit)
        saved = self.client.post("/profile", data=self.form(height_cm="177", weight_kg="71"),
                                 follow_redirects=True).data.decode()
        self.assertNotIn("follows your new measurements", saved)
        self.assertEqual(look_key(outfit), before)

    def test_with_his_own_photo_the_body_goes_along_in_words(self):
        self.client.post("/profile/photo", data={"photo": (io.BytesIO(PHOTO), "me.jpg"), "agree": "on"},
                         content_type="multipart/form-data")
        self.assertIsNotNone(person.photo())
        outfit = some_outfits(1)[0]
        before = look_key(outfit)
        self.post("/outfits/look", key=outfit.key)
        self.assertNotIn("Their build", self.drawn[0]["prompt"])       # the example's body: as before
        self.client.post("/profile", data=self.form(height_cm="192", weight_kg="80"))
        self.assertNotEqual(look_key(outfit), before)
        self.post("/outfits/look", key=outfit.key)
        self.assertIn("Their build: tall, lean build. ", self.drawn[1]["prompt"])
        self.assertIsNotNone(self.drawn[1]["photo"])


class WhatIsSaid(WithPictures, Saving):
    def setUp(self):
        super().setUp()
        self.switch_on()

    def page(self) -> str:
        return self.client.get("/profile").data.decode()

    def test_the_figure_is_called_a_sketch_that_the_pictures_follow(self):
        page = self.page()
        note = re.search(r'<p class="cc-sketch" data-figure-note>(.*?)</p>', page, re.S).group(1)
        self.assertEqual(re.sub(r"<[^>]+>", "", note), "This is a sketch. The AI pictures on Outfits follow the same body.")
        self.assertIn('href="/outfits"', note)
        self.assertLess(page.index("data-figure-words"), page.index("data-figure-note"), "the note is not under the figure")

    def test_what_goes_to_the_image_service_is_said_beside_the_body(self):
        page = self.page()
        notes = [re.sub(r"<[^>]+>", "", note) for note in re.findall(r"<p[^>]*data-body-sent>(.*?)</p>", page, re.S)]
        self.assertEqual(len(notes), 2, "once on the Body tab, once under the measurements on Sizes")
        model, sizes = page.index('id="panel-body"'), page.index('id="panel-sizes"')
        first, second = (page.index("data-body-sent"), page.rindex("data-body-sent"))
        self.assertTrue(model < first < sizes < second)
        for note in notes:                          # the service that draws here (the tests' stand-in is OpenAI)
            self.assertIn("OpenAI with each picture", note)
            self.assertIn("never as numbers", note)
        self.assertIn("Until you enter those, and with everything on “Any”, it is our standard model", page)
        self.assertIn("Described to the AI as: “an adult male fashion model with an average build”", page)

        self.client.post("/profile", data=self.form(height_cm="172", weight_kg="95"))
        page = self.page()
        words = "an adult man (a little shorter than average, heavy build with a full stomach)"
        self.assertEqual(person.current().words, words)
        self.assertEqual(page.count(f"“{words}”"), 2, "the words that are sent are not shown as they are sent")
        self.assertNotIn("it is our standard model", page)

    def test_the_drawn_figure_takes_the_build_the_pictures_are_asked_for(self):
        self.assertIn("180 cm, any build, any skin tone, any hair", self.page())
        self.assertEqual(figure.drawing({}, 180, profile_mod.load())["body"], figure.body("average"))
        self.client.post("/profile", data=self.form(height_cm="172", weight_kg="95"))
        page = self.page()
        self.assertIn('<p class="cc-words" data-figure-words>172 cm, heavy build, any skin tone, any hair</p>', page)
        mine = profile_mod.load()
        self.assertEqual(figure.drawing({}, 172, mine)["body"], figure.body("heavy"))
        # A build chosen in the menu is the one drawn and said, as it is the one the pictures are asked for.
        self.assertEqual(figure.drawing({"build": "slim"}, 172, mine)["body"], figure.body("slim"))
        self.assertTrue(figure.words({"build": "slim"}, 172, mine).startswith("172 cm, slim build"))
        # Every build worked out from height and weight has a body to draw and a word, and the page's script gets them.
        for build in person.BUILDS:
            self.assertIn(build.figure, figure.BUILDS)
        data = figure.data()
        self.assertEqual(data["example"], {"height_cm": 180, "weight_kg": 78, "chest_cm": None, "waist_cm": None})
        self.assertEqual([row[1:] for row in data["ownBuilds"]], [[b.label, b.figure] for b in person.BUILDS])
        self.assertIsNone(data["ownBuilds"][-1][0])


class ThePrivacyPage(ProductionCase):
    def test_the_privacy_page_says_the_body_goes_along_in_words(self):
        page = self.app.test_client().get("/legal/privacy").data.decode()
        for words in ("once you have entered your own height, weight, chest or waist on Profile, by your body in a few "
                      "words worked out from them", "how your chest compares with your waist",
                      "The numbers themselves are not sent", "is sent with each picture to an AI image service, "
                      "OpenAI or Google", "No name, email address or clothing size goes with it",
                      "An outfit's further pictures (“More photos”: other poses and surroundings) are made from its "
                      "first picture: that AI picture is sent to the same service again",
                      "the further pictures of an outfit are made from that picture of you, which then goes to the "
                      "same service in place of the photo"):
            self.assertIn(words, page)
        self.assertNotIn("No name, email address or size goes with it. If you upload", page)
