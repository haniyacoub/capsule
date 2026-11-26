"""The owner's test of reference photographs: python -m wardrobe looks --test-photos FOLDER (phototest.py).

One outfit of his own garments, a photograph of each, drawn from the words alone and with the photographs sent
along. The image service is a stand-in here, as everywhere in the tests: nothing is sent and nothing is billed.
The photographs are files built to look like a phone's (test_looks.photo_jpeg) and no real garment's.
"""
import contextlib
import io
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from unittest import mock

from wardrobe import imagegen, looks, paths, person, phototest, settings
from wardrobe.__main__ import main
from wardrobe.garments import GARMENTS

from .test_app import AppCase
from .test_looks import PICTURE, WithPictures, photo_jpeg, photo_png

HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x07" * 600    # what an iPhone's photo starts like

# One outfit, named as the command asks: the kind first, then colour and fabric. Each file is a different picture
# (another width), so that what was sent can be told apart.
OUTFIT = {"trousers grey flannel.jpg": photo_jpeg(300, 400),
          "Jumper navy merino.JPG": photo_jpeg(310, 400),
          "coat charcoal wool.png": photo_png(320, 400),
          "2 sneakers_white-leather.jpeg": photo_jpeg(330, 400),
          "shirt white cotton.jpg": photo_jpeg(340, 400)}
IN_ORDER = ["coat charcoal wool.png", "Jumper navy merino.JPG", "shirt white cotton.jpg", "trousers grey flannel.jpg",
            "2 sneakers_white-leather.jpeg"]


class WithAFolder:
    def a_folder(self, files: dict[str, bytes] | None = None) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="capsule-photos-")) / "my outfit"
        folder.mkdir()
        self.addCleanup(shutil.rmtree, folder.parent, ignore_errors=True)
        for name, data in (OUTFIT if files is None else files).items():
            (folder / name).write_bytes(data)
        return folder


class WhatAFileIsNamedFor(unittest.TestCase):
    def test_the_kind_comes_first_and_the_rest_are_his_words(self):
        for stem, read in (("jumper navy merino", ("knit", "navy merino jumper")),
                           ("Jumper_Navy-Merino", ("knit", "navy merino jumper")),
                           ("2 sneakers_white-leather", ("sneakers", "white leather sneakers")),
                           ("03 coat charcoal wool", ("coat", "charcoal wool coat")),
                           ("T-Shirt white", ("tee", "white t shirt")),
                           ("long-sleeve tee white", ("longsleeve", "white long sleeve tee")),
                           ("polo shirt navy", ("polo", "navy polo shirt")),       # the longer name first
                           ("cargo trousers olive", ("cargo", "olive cargo trousers")),
                           ("leather shoes brown", ("shoes", "brown leather shoes")),
                           ("overshirt olive", ("overshirt", "olive overshirt")),  # never "shirt"
                           ("shirt", ("shirt", "shirt"))):
            with self.subTest(stem=stem):
                self.assertEqual(phototest.named(stem), read)

    def test_a_name_that_does_not_start_with_a_kind_says_nothing(self):
        # Only the start is read: a kind further on is no kind ("navy jumper"), nor is a word that only holds one.
        for stem in ("IMG_1234", "navy jumper", "shirts white", "my coat", "", "42"):
            with self.subTest(stem=stem):
                self.assertIsNone(phototest.named(stem))

    def test_every_garment_of_the_app_has_its_own_name_here_and_no_name_twice(self):
        names = [phototest._plain(name) for names in phototest._NAMES.values() for name in names]
        self.assertEqual(len(names), len(set(names)), "a name stands for two garments")
        self.assertEqual(set(phototest._NAMES), set(GARMENTS))
        for key, garment in GARMENTS.items():
            with self.subTest(garment=key):
                self.assertEqual(phototest.KINDS.get(phototest._plain(garment.label)), key, "as the app calls it")
        for first in phototest.kinds_said().split(", "):
            self.assertIsNotNone(phototest.named(first), "a kind the help names is not read")


class WhatAFolderHolds(WithAFolder, unittest.TestCase):
    def test_one_outfit_from_the_outermost_layer_down_to_the_shoes(self):
        folder = self.a_folder()
        (folder / "notes.txt").write_text("the jumper is the old one")
        (folder / ".DS_Store").write_bytes(b"\x00")
        (folder / "pictures-20261126-101500").mkdir()         # an earlier run's pictures: not photographs of his
        (folder / "pictures-20261126-101500" / "coat again.jpg").write_bytes(photo_jpeg())
        photos, skipped = phototest.read(folder)
        self.assertEqual([photo.file.name for photo in photos], IN_ORDER)
        self.assertEqual([photo.kind for photo in photos], ["coat", "knit", "shirt", "trousers", "sneakers"])
        self.assertEqual(photos[1].words, "navy merino jumper")
        self.assertEqual(skipped, ["notes.txt"])

    def test_what_is_not_one_outfit_is_refused_with_what_to_do(self):
        some = photo_jpeg()
        for files, said in (
                ({}, "There are no photographs in"),
                ({"notes.txt": b"words"}, "There are no photographs in"),
                ({"IMG_1234.jpg": some, "trousers grey.jpg": some}, "“IMG_1234.jpg” does not say what the garment is"),
                ({"navy jumper.jpg": some}, "Start its name with one of these"),
                ({f"{kind} one.jpg": some for kind in ("coat", "blazer", "cardigan", "jumper", "shirt", "jeans",
                                                         "boots")}, "There are 7 photographs"),
                ({"jeans blue.jpg": some, "chinos beige.jpg": some, "shirt white.jpg": some},
                 "There are 2 pairs of trousers"),
                ({"shirt white.jpg": some, "shirt blue.jpg": some, "jeans blue.jpg": some},
                 "are “shirt”: one outfit has one of a kind"),
                ({"jumper navy.jpg": some, "sweater grey.jpg": some, "jeans blue.jpg": some},
                 "2 photographs in"),
                ({"coat grey.jpg": some, "jacket black.jpg": some, "shirt white.jpg": some, "jeans blue.jpg": some},
                 "There are 2 coats or jackets"),
                ({"sneakers white.jpg": some, "boots brown.jpg": some, "tee white.jpg": some, "jeans blue.jpg": some},
                 "There are 2 pairs of shoes"),
                ({"blazer navy.jpg": some, "cardigan grey.jpg": some, "jumper navy.jpg": some, "shirt white.jpg": some,
                  "jeans blue.jpg": some}, "There are 4 tops and layers"),
                ({"coat grey.jpg": some, "jeans blue.jpg": some},
                 "has no top (a shirt, a T-shirt, a jumper …): the model would be drawn in one the service makes up"),
                ({"shirt white.jpg": some, "sneakers white.jpg": some},
                 "has no trousers: the model would be drawn in some the service makes up")):
            with self.subTest(files=sorted(files)):
                with self.assertRaises(phototest.Unusable) as refused:
                    phototest.read(self.a_folder(files))
                self.assertIn(said, str(refused.exception))
        with self.assertRaises(phototest.Unusable) as refused:
            phototest.read(Path(tempfile.gettempdir()) / "capsule-no-such-folder")
        self.assertIn("is not a folder", str(refused.exception))
        self.assertIn("jumper", phototest.kinds_said())

    def test_the_words_are_the_apps_own_with_what_the_photographs_are_after_them(self):
        photos, _ = phototest.read(self.a_folder())
        rules = looks.load_rules()
        words, with_photos = phototest.prompts(photos, rules)
        self.assertEqual(words, looks.prompt(phototest.pieces(photos), rules, person.Who()), "as for any outfit")
        self.assertIn(rules["text"]["model"], words, "Stilsmith's house model")
        lines = [line for line in words.splitlines() if line[:2] in ("1.", "2.", "3.", "4.", "5.")]
        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[0].startswith("1. Coat, worn open as the outer layer"), lines[0])
        self.assertIn("charcoal", lines[0])
        self.assertTrue(lines[1].startswith("2. Jumper, worn over the shirt, with the collar of the shirt showing"))
        self.assertIn("navy", lines[1])
        # Piece k is photograph k: his words for it stand in its line, in the order the photographs are sent in.
        for line, photo in zip(lines, photos):
            self.assertIn(f"Sold as: {photo.words}.", line)
        self.assertEqual(phototest.listed(photos), lines, "what is shown before anything is drawn")
        self.assertTrue(with_photos.startswith(words + "\n\n"))
        said = with_photos[len(words):]
        self.assertIn("The 5 pictures sent along are photographs of these exact pieces", said)
        self.assertIn("picture 1 shows piece 1, picture 2 shows piece 2", said)
        self.assertIn("any logo or print that is on the garment itself", said, "the usual words forbid logos")
        self.assertNotIn("{n}", said)

    def test_a_name_with_no_colour_or_fabric_still_makes_a_piece(self):
        photos, _ = phototest.read(self.a_folder({"jumper.jpg": photo_jpeg(), "jeans.jpg": photo_jpeg()}))
        pieces = phototest.pieces(photos)
        self.assertEqual([(piece["category"], piece["role"], piece["colour"], piece["hex"]) for piece in pieces],
                         [("knit", "top", "", None), ("jeans", "bottom", "", None)])
        words, _ = phototest.prompts(photos, looks.load_rules())
        self.assertIn("1. Jumper. Sold as: jumper.", words)
        self.assertIn("Shoes are not part of this outfit", words)


class APhotographAsItIsSent(WithAFolder, unittest.TestCase):
    def test_only_the_picture_is_sent_never_where_and_when_it_was_taken(self):
        folder = self.a_folder({"shirt.jpg": photo_jpeg(), "jeans.png": photo_png()})
        for name, secret in (("shirt.jpg", b"52.5N 13.4E"), ("jeans.png", b"at home")):
            with self.subTest(file=name):
                self.assertIn(secret, (folder / name).read_bytes())
                sent = phototest.prepare(folder / name, None)
                self.assertNotIn(secret, sent)
                self.assertNotIn(b"Exif", sent)
                self.assertNotIn(b"SecretCam", sent)
                self.assertEqual(sent, person.tidy((folder / name).read_bytes())[0])

    def test_what_cannot_be_used_is_said_before_anything_is_drawn(self):
        folder = self.a_folder({"shirt.heic": HEIC, "jeans.jpg": photo_jpeg(64, 64), "coat.jpg": photo_jpeg()})
        with self.assertRaises(phototest.Unusable) as refused:      # no converter here: not a Mac
            phototest.prepare(folder / "shirt.heic", None)
        self.assertIn("“shirt.heic” is not a photograph this can use. Without a Mac's own converter it has to be a "
                      "JPEG or PNG", str(refused.exception))
        with self.assertRaises(phototest.Unusable) as refused:
            phototest.prepare(folder / "jeans.jpg", None)
        self.assertIn("“jeans.jpg” is not a photograph this can use", str(refused.exception))
        with mock.patch.object(phototest, "MAX_SENT", 100), self.assertRaises(phototest.Unusable) as refused:
            phototest.prepare(folder / "coat.jpg", None)
        self.assertIn("“coat.jpg” is too large to send", str(refused.exception))

    def test_on_a_mac_every_photograph_is_made_upright_resized_and_a_jpeg_first(self):
        folder = self.a_folder({"shirt.heic": HEIC})
        asked = []

        def convert(photo: Path, copy: Path) -> None:
            asked.append(photo)
            copy.write_bytes(photo_jpeg(1152, 1536))        # what sips makes of it

        sent = phototest.prepare(folder / "shirt.heic", convert)
        self.assertEqual(asked, [folder / "shirt.heic"])
        self.assertEqual(sent, person.tidy(photo_jpeg(1152, 1536))[0], "and still nothing but the picture")
        self.assertNotIn(b"52.5N", sent)
        with self.assertRaises(phototest.Unusable) as refused:      # the converter left nothing
            phototest.prepare(folder / "shirt.heic", lambda photo, copy: None)
        self.assertIn("at least 128 pixels a side", str(refused.exception))

    def test_the_macs_converter_goes_through_a_file_that_cannot_say_turn_me(self):
        folder = self.a_folder({"shirt.heic": HEIC})
        ran = []

        def run(command, **how):
            ran.append((command, how))
            Path(command[-1]).write_bytes(b"BM" if command[3] == "bmp" else photo_jpeg())
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(phototest.shutil, "which", lambda tool: None):
            self.assertIsNone(phototest.converter(), "no sips here: photographs go as they are")
        with mock.patch.object(phototest.shutil, "which", lambda tool: f"/usr/bin/{tool}"), \
                mock.patch.object(phototest.subprocess, "run", run):
            convert = phototest.converter()
            copy = folder.parent / "copy.jpg"
            convert(folder / "shirt.heic", copy)
        self.assertEqual(copy.read_bytes(), photo_jpeg())
        (first, how), (second, _) = ran
        self.assertEqual(first[:6], ["/usr/bin/sips", "-s", "format", "bmp", "-Z", str(phototest.LONGEST)])
        self.assertEqual(first[6], str((folder / "shirt.heic").resolve()), "by its whole address")
        self.assertEqual(second[:7], ["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "85"])
        self.assertEqual(second[7], first[-1], "the JPEG is made from the upright copy")
        self.assertEqual(second[-1], str(copy.resolve()))
        self.assertEqual((how["check"], how["capture_output"], how["timeout"]), (True, True, phototest.SIPS_SECONDS))
        self.assertFalse(Path(first[-1]).exists(), "the copy in between is not kept")

        def fails(command, **how):
            raise subprocess.CalledProcessError(1, command)

        with mock.patch.object(phototest.subprocess, "run", fails), self.assertRaises(phototest.Unusable) as refused:
            phototest._sips("/usr/bin/sips", folder / "shirt.heic", copy)
        self.assertIn("“shirt.heic” could not be opened as a photograph", str(refused.exception))

    def test_about_what_a_run_costs(self):
        # Four pictures at 5 cents, and each of the five photographs sent with each of the three: 0.2 cents apiece.
        self.assertEqual(phototest.estimate(5, 3, Decimal("0.05")), Decimal("0.230"))
        self.assertEqual(phototest.estimate(2, 1, Decimal("0.05")), Decimal("0.104"))
        self.assertIsNone(phototest.estimate(5, 3, None))


class TheCommand(WithAFolder, WithPictures, AppCase):
    def setUp(self):
        super().setUp()
        self.switch_on()
        self.folder = self.a_folder()
        self.no_converter = mock.patch.object(phototest, "converter", lambda: None)   # as on anything but a Mac
        self.no_converter.start()
        self.addCleanup(self.no_converter.stop)

    def run_it(self, *more: str, answer: str | None = None, terminal: bool = True) -> tuple[str, str]:
        """Run the command; returns (what it printed, what it stopped with)."""
        said, stopped = io.StringIO(), ""
        asked = mock.Mock(return_value=answer or "")
        with contextlib.redirect_stdout(said), mock.patch("builtins.input", asked), \
                mock.patch("sys.stdin.isatty", lambda: terminal):
            try:
                main(["looks", "--test-photos", str(self.folder), *more])
            except SystemExit as stop:
                stopped = str(stop)
        self.asked = asked.call_count
        return said.getvalue(), stopped

    def runs(self) -> list[Path]:
        return sorted(path for path in self.folder.iterdir() if path.is_dir())

    def nothing_was_kept_by_the_app(self):
        self.assertEqual(self.pictures_on_disk(), [], "no picture among the app's own")
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            for table in ("looks", "look_requests"):
                self.assertEqual(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0, table)

    def test_it_says_how_each_photograph_was_read_and_what_it_costs_and_asks(self):
        said, stopped = self.run_it(answer="n")
        self.assertIn(f"One outfit from 5 photographs in {self.folder}, read as:", said)
        for number, (label, words, file) in enumerate((("Coat:", "charcoal wool coat", "coat charcoal wool.png"),
                                                       ("Jumper:", "navy merino jumper", "Jumper navy merino.JPG"),
                                                       ("Shirt:", "white cotton shirt", "shirt white cotton.jpg"),
                                                       ("Trousers:", "grey flannel trousers", "trousers grey flannel.jpg"),
                                                       ("Sneakers:", "white leather sneakers",
                                                        "2 sneakers_white-leather.jpeg")), 1):
            self.assertRegex(said, rf"  {number}\. {label} +{words}   \({file}, \d+ KB as sent\)")
        self.assertIn("  1 picture from the words alone, as the app draws today\n"
                      "  3 pictures with your 5 photographs sent along\n"
                      "That is 4 pictures billed to your key: about $0.23.", said)
        self.assertIn("on Stilsmith's house model (no photo of a person is used)", said)
        self.assertIn("without where and when they were taken", said)
        self.assertIn("This computer has no `sips`", said)
        self.assertNotIn("No colour in the name", said, "every name here says its colour")
        # The pieces as the service is told them, so that a colour read wrongly is seen while it costs nothing.
        self.assertIn("The image service is told of them, in the picture from words and with the photographs alike:\n"
                      "  1. Coat, worn open as the outer layer, so that what is underneath stays visible: charcoal, "
                      "wool. Sold as: charcoal wool coat.\n  2. Jumper, worn over the shirt", said)
        self.assertIn("  5. Sneakers: white, leather. Sold as: white leather sneakers.\n", said)
        self.assertEqual((stopped, self.asked), ("Nothing was drawn.", 1))
        self.assertEqual((self.drawn, self.runs()), ([], []), "not a picture, not a folder")

    def test_a_name_without_a_colour_is_pointed_out_for_a_fair_comparison(self):
        (self.folder / "shirt white cotton.jpg").rename(self.folder / "shirt oxford.jpg")
        (self.folder / "trousers grey flannel.jpg").rename(self.folder / "trousers.jpg")
        said, _ = self.run_it(answer="n")
        self.assertIn("No colour in the name of: shirt oxford.jpg, trousers.jpg. The picture from words alone has "
                      "only the names to go on:\nadd each garment's colour and fabric", said)
        self.assertEqual(self.drawn, [])

    def test_nothing_is_drawn_without_a_yes(self):
        _, stopped = self.run_it(terminal=False)                # run by a script: nobody to answer
        self.assertEqual((stopped, self.asked), ("\nNothing was drawn: answer in a terminal, or add --yes.", 0))
        for answer in ("", "no", "maybe", "yes please"):
            with self.subTest(answer=answer):
                self.assertEqual(self.run_it(answer=answer)[1], "Nothing was drawn.")
        self.assertEqual((self.drawn, self.runs()), ([], []))

    def test_without_a_key_it_says_what_it_would_draw_and_how_to_set_one(self):
        with mock.patch.object(settings, "GEMINI_API_KEY", ""):
            said, stopped = self.run_it("--yes")
        self.assertIn("That is 4 pictures billed to your key", said)
        self.assertIn("Nothing was drawn: AI pictures are off — set GEMINI_API_KEY.\n", stopped)
        self.assertIn("and run this command again in the same terminal.", stopped)
        self.assertNotIn("start the app", stopped, "that is for the site, not for this command")
        self.assertEqual((self.drawn, self.runs()), ([], []))

    def test_a_folder_that_cannot_be_used_stops_it_before_anything_else(self):
        (self.folder / "IMG_0001.HEIC").write_bytes(HEIC)
        said, stopped = self.run_it("--yes")
        self.assertIn("Nothing was drawn: “IMG_0001.HEIC” does not say what the garment is.", stopped)
        (self.folder / "IMG_0001.HEIC").rename(self.folder / "boots brown.heic")
        self.assertIn("Nothing was drawn: There are 2 pairs of shoes", self.run_it("--yes")[1])
        (self.folder / "2 sneakers_white-leather.jpeg").unlink()
        self.assertIn("Nothing was drawn: “boots brown.heic” is not a photograph this can use", self.run_it("--yes")[1])
        self.assertEqual((self.drawn, self.runs(), said), ([], [], ""))

    def test_a_yes_draws_the_outfit_from_words_and_with_the_photographs(self):
        said, stopped = self.run_it(answer="y")
        self.assertEqual(stopped, "")
        sent = [phototest.prepare(self.folder / name, None) for name in IN_ORDER]
        self.assertEqual(len(set(sent)), 5)
        words, with_photos = phototest.prompts(phototest.read(self.folder)[0], looks.load_rules())
        self.assertEqual(len(self.drawn), 4)
        self.assertEqual([(drawn["prompt"], drawn["references"]) for drawn in self.drawn],
                         [(words, [])] + [(with_photos, sent)] * 3,
                         "the words alone first; then photograph k is the photograph of piece k")
        self.assertTrue(all(drawn["photo"] is None for drawn in self.drawn), "no photo of a person, ever")
        for picture in sent:
            self.assertNotIn(b"52.5N", picture)
            self.assertNotIn(b"Exif", picture)
        (out,) = self.runs()
        self.assertRegex(out.name, r"^pictures-\d{8}-\d{6}$")
        self.assertEqual(sorted(path.name for path in out.iterdir()),
                         ["compare.html", "from-words.jpg", "sent-1-coat.png", "sent-2-knit.jpg", "sent-3-shirt.jpg",
                          "sent-4-trousers.jpg", "sent-5-sneakers.jpg", "with-photos-1.jpg", "with-photos-2.jpg",
                          "with-photos-3.jpg", "words-alone.txt", "words-with-photos.txt"])
        self.assertEqual([(out / name).read_bytes() for name in ("sent-1-coat.png", "sent-2-knit.jpg", "sent-3-shirt.jpg",
                                                                 "sent-4-trousers.jpg", "sent-5-sneakers.jpg")], sent,
                         "kept exactly as they were sent")
        self.assertEqual((out / "from-words.jpg").read_bytes(), PICTURE)
        self.assertEqual((out / "words-alone.txt").read_text(encoding="utf-8"), words + "\n")
        self.assertEqual((out / "words-with-photos.txt").read_text(encoding="utf-8"), with_photos + "\n")
        self.assertIn(f"Drawing into {out}", said)
        self.assertIn(f"Done: 4 pictures. Open this page to compare them:\n  {out / 'compare.html'}", said)
        self.assertEqual(said.count(" seconds)"), 4)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir() if path.is_file()), sorted(OUTFIT),
                         "his own photographs are as they were")
        self.nothing_was_kept_by_the_app()
        # The page to compare on: the photographs as sent, each with what it was read as, then the pictures.
        page = (out / "compare.html").read_text(encoding="utf-8")
        self.assertIn("<title>Photo test: my outfit</title>", page)
        self.assertLess(page.index('src="sent-1-coat.png"'), page.index('src="from-words.jpg"'))
        self.assertLess(page.index('src="from-words.jpg"'), page.index('src="with-photos-1.jpg"'))
        self.assertIn("2. Jumper: navy merino jumper", page)
        self.assertIn("From the words alone, as the app draws today", page)
        self.assertIn("With your photographs sent along (3 of 3)", page)
        self.assertEqual(page.count("<img "), 9)
        self.assertNotIn("<script", page)
        self.assertNotIn("http", page.replace("http-equiv", ""), "nothing is fetched from anywhere")
        self.assertNotIn("The run stopped", page)

    def test_how_many_is_his_to_say_up_to_nine(self):
        said, stopped = self.run_it("--pictures", "1", "--yes")
        self.assertEqual((stopped, len(self.drawn), self.asked), ("", 2, 0))
        self.assertIn("  1 picture with your 5 photographs sent along\nThat is 2 pictures billed to your key: about "
                      "$0.11.", said)
        self.assertEqual((phototest.WITH_PHOTOS, phototest.MOST_WITH_PHOTOS), (3, 9), "as the options say")
        for wrong in ("0", "10", "many"):
            with self.subTest(pictures=wrong), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                main(["looks", "--test-photos", str(self.folder), "--pictures", wrong, "--yes"])
        self.assertEqual(len(self.drawn), 2)

    def test_a_run_never_writes_over_an_earlier_one(self):
        with mock.patch.object(phototest.time, "strftime", lambda fmt: "20261126-101500"):
            self.run_it("--pictures", "1", "--yes")
            first = (self.folder / "pictures-20261126-101500" / "compare.html").read_bytes()
            self.run_it("--pictures", "2", "--yes")
        self.assertEqual([path.name for path in self.runs()], ["pictures-20261126-101500", "pictures-20261126-101500-2"])
        self.assertEqual((self.folder / "pictures-20261126-101500" / "compare.html").read_bytes(), first)
        self.assertTrue((self.folder / "pictures-20261126-101500-2" / "with-photos-2.jpg").is_file())
        self.assertEqual(len(phototest.read(self.folder)[0]), 5, "the runs' folders are no photographs of his")

    def test_one_that_fails_stops_the_run_and_says_what_was_billed(self):
        for free, billed in ((False, "it may have been billed all the same"), (True, "it was not billed")):
            with self.subTest(free=free):
                self.drawn.clear()
                problem = imagegen.DrawError("busy", "Google answered 503: overloaded", free=free)
                real = imagegen.draw

                def third_fails(service, prompt, photo=None, references=()):
                    self.refuse = problem if len(self.drawn) == 2 else None
                    return real(service, prompt, photo, references)

                with mock.patch.object(imagegen, "draw", third_fails):
                    said, stopped = self.run_it("--yes")
                out = self.runs()[-1]
                self.assertEqual(len(self.drawn), 3, "not tried again, and the fourth is not started")
                self.assertIn("It stopped at picture 3 of 4: ", stopped)
                self.assertIn(looks.SAY["busy"], stopped)
                self.assertIn("Google answered 503: overloaded", stopped)
                self.assertIn(f"2 pictures were drawn and billed; the one that failed was not drawn, and {billed}.",
                              stopped)
                self.assertIn(f"What there is: {out / 'compare.html'}", stopped)
                self.assertNotIn("Done", said)
                self.assertEqual(sorted(path.name for path in out.glob("*.jpg") if not path.name.startswith("sent-")),
                                 ["from-words.jpg", "with-photos-1.jpg"])
                page = (out / "compare.html").read_text(encoding="utf-8")
                self.assertIn("The run stopped before all pictures were drawn", page)
                self.assertEqual(page.count("<img "), 7)
        self.refuse = imagegen.DrawError("key", "Google answered 400: API key not valid", free=True)
        said, stopped = self.run_it("--yes")
        self.assertIn("It stopped at picture 1 of 4: ", stopped)
        self.assertIn("0 pictures were drawn and billed", stopped)
        self.assertIn("No picture was drawn.", (self.runs()[-1] / "compare.html").read_text(encoding="utf-8"))

    def test_on_a_mac_what_is_sent_is_what_the_converter_made(self):
        self.no_converter.stop()
        made = {name: photo_jpeg(1000 + n, 1536) for n, name in enumerate(IN_ORDER)}
        (self.folder / "shirt white cotton.jpg").write_bytes(HEIC)      # an iPhone's file, whatever its name says

        def convert(photo: Path, copy: Path) -> None:
            copy.write_bytes(made[photo.name])

        with mock.patch.object(phototest, "converter", lambda: convert):
            said, stopped = self.run_it("--pictures", "1", "--yes")
        self.no_converter.start()
        self.assertEqual(stopped, "")
        self.assertNotIn("has no `sips`", said)
        self.assertEqual(self.drawn[1]["references"], [person.tidy(made[name])[0] for name in IN_ORDER])
        self.assertEqual([path.suffix for path in sorted(self.runs()[-1].glob("sent-*"))], [".jpg"] * 5)


if __name__ == "__main__":
    unittest.main()
