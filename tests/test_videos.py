"""'See it move': the AI video of an outfit, its limits, Pro accounts and drag to turn.

No test talks to Google: the video is "made" by a stand-in, Google's answers are canned, and the
one thing that could open a connection (imagegen's opener) is replaced by one that fails the test if
it is used. tests/fixtures/test-pattern.mp4 is a made-up clip (ffmpeg's test pattern, no person in it).
"""
import base64
import io
import json
import re
import shutil
import sqlite3
import subprocess
import unittest
import urllib.error
from contextlib import closing, redirect_stdout
from email.message import Message
from pathlib import Path
from unittest import mock

from wardrobe import config, db, imagegen, looks, paths, person, settings, videogen, videos
from wardrobe.__main__ import main
from wardrobe.app import PHOTO_CONSENT

from .test_app import HX, AppCase
from .test_looks import PHOTO, PICTURE, WithPictures, look_key, some_outfits
from .test_production import PASSWORD, ProductionCase, words

CLIP = (Path(__file__).parent / "fixtures" / "test-pattern.mp4").read_bytes()
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class WithVideos(WithPictures):
    """AI pictures and videos switched on, with stand-ins for both services and no way out to the network."""

    def switch_on(self):
        super().switch_on()
        self.made = []          # every video the "video model" was asked for
        self.refuse_video = None

        def stand_in(service, picture, prompt, seconds=8):
            self.made.append({"service": service, "picture": picture, "prompt": prompt, "seconds": seconds})
            if self.refuse_video:
                raise self.refuse_video
            return CLIP

        self.opener = mock.Mock()
        self.opener.open.side_effect = AssertionError("a network connection was opened")
        for patch in (mock.patch.object(settings, "GEMINI_API_KEY", "test-gemini-key"),
                      mock.patch.object(videogen, "make", stand_in),
                      mock.patch.object(videos, "STARTED", 0.0),
                      mock.patch.object(videos, "_spawn", lambda job: job()),      # made at once, not in the background
                      mock.patch.object(videos, "_ffmpeg", lambda: None),       # no ffmpeg, unless a test says so
                      mock.patch.object(imagegen, "_opener", self.opener)):
            patch.start()
            self.addCleanup(patch.stop)
        shutil.rmtree(videos.folder(), ignore_errors=True)
        self.addCleanup(lambda: self.assertFalse(self.opener.open.called, "a test opened a network connection"))

    def videos_on_disk(self):
        return sorted(p.name for p in videos.folder().glob("*.mp4")) if videos.folder().exists() else []

    def with_video_rules(self, **changes):
        rules = looks.load_rules()
        changed = {**rules, "videos": {**rules["videos"], **changes}}
        patch = mock.patch.object(looks, "load_rules", lambda: changed)
        patch.start()
        self.addCleanup(patch.stop)


def fetched(client, address, **options) -> int:
    """The status of a video's address, the file closed again."""
    response = client.get(address, **options)
    response.close()
    return response.status_code


def said(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class SeeItMove(WithVideos, AppCase):
    """On your own machine: one person, no login."""

    def setUp(self):
        super().setUp()
        self.switch_on()

    def picture(self, outfit=None):
        """An outfit with its picture drawn. Returns (the outfit, its picture)."""
        outfit = outfit or some_outfits(1)[0]
        self.post("/outfits/look", key=outfit.key)
        return outfit, looks.get(look_key(outfit))

    def part(self, outfit, look, **more):
        return self.client.get("/outfits/video", query_string={"look": look.key, "outfit": outfit.key, **more}).data.decode()

    def make(self, outfit, look):
        return self.post("/outfits/video", look=look.key, outfit=outfit.key).data.decode()

    def test_a_finished_picture_offers_see_it_move_and_nothing_is_made_by_itself(self):
        outfit, look = self.picture()
        box = self.post("/outfits/look", key=outfit.key).data.decode()
        self.assertIn('class="look-vid"', box)
        self.assertIn("See it move", box)
        page = self.client.get("/outfits").data.decode()
        self.assertEqual(page.count('class="look-vid"'), 1, "only under the finished picture")
        self.assertEqual(self.made, [], "a video is made only when asked for")

    def test_see_it_move_says_what_it_is_and_how_many_are_left_before_anything_is_spent(self):
        outfit, look = self.picture()
        offer = self.part(outfit, look, ask="1")
        form = re.search(r'<form class="([^"]+)"', offer).group(1)
        self.assertEqual(form, "vid-bar ask", "the offer is under the picture (app.css), not a band across it")
        self.assertIn("AI video of the Front picture, 8 seconds: he turns round once.", said(offer))
        self.assertIn("10 videos left today.", said(offer))        # on your own machine: the site's ten
        self.assertIn("Make the video", offer)
        self.assertIn("Not now", offer)
        self.assertEqual(self.made, [])
        self.assertNotIn("Make the video", self.part(outfit, look), "Not now: back to the button")

    def test_the_video_starts_from_the_picture_on_screen_with_the_words_in_the_settings(self):
        outfit, look = self.picture()
        shown = self.make(outfit, look)
        self.assertEqual(len(self.made), 1)
        sent = self.made[0]
        self.assertEqual(sent["picture"], (looks.folder() / look.file).read_bytes())
        rules = looks.load_rules()["videos"]
        self.assertEqual(sent["prompt"], f"{rules['start']} {rules['motion']['front']} {rules['keep']}")
        self.assertEqual(sent["service"].model, "gemini-omni-flash-preview")
        self.assertEqual(sent["service"].task, "image_to_video", "Google is told the picture is the first frame")
        self.assertEqual(sent["seconds"], 8, "the turn is 8 seconds")
        self.assertIn("turns slowly on the spot through one full circle", sent["prompt"])
        self.assertIn("No dialogue, no music", sent["prompt"])
        self.assertIn("data-play", shown, "it plays once it is there")
        self.assertIn('<span class="ai-chip">AI video</span>', shown)

        self.post("/outfits/look", key=outfit.key, more="1")                                # "More photos"
        street = self.post("/outfits/look", key=outfit.key, shot="street").data.decode()    # another of its pictures
        self.assertIn('class="look-vid"', street)
        other = looks.get(re.search(r'data-look="([0-9a-f]{24})"', street).group(1))
        self.assertNotEqual(other.key, look.key)
        self.assertIn("See it move", street)
        self.make(outfit, other)
        self.assertEqual(len(self.made), 2, "the street picture has a video of its own")
        self.assertEqual(self.made[1]["picture"], (looks.folder() / other.file).read_bytes(),
                         "the street video starts from the street picture")

    def test_each_state_is_said_on_the_picture_box(self):
        outfit, look = self.picture()
        held = []
        with mock.patch.object(videos, "_spawn", held.append):
            making = self.make(outfit, look)
        band = re.search(r'<p class="vid-bar band wait"[^>]*>', making).group(0)
        self.assertIn("Making the video · about a minute", said(making))
        self.assertIn("hx-get", band)                               # it asks again by itself …
        self.assertIn("wait=1", band)
        self.assertNotIn("role=", band)                             # … without being read out each time
        self.assertIn("Making the video", self.part(outfit, look, wait="1"))
        held.pop()()                                                # made
        ready = self.part(outfit, look, wait="1")
        self.assertIn("data-play", ready)
        slider = re.search(r'<div class="vid-turn"[^>]*>', ready).group(0)
        for wanted in ('role="slider"', 'tabindex="0"', 'aria-valuemin="0"', 'aria-valuemax="360"', 'aria-valuenow="0"',
                       'aria-valuetext="0 degrees"', 'aria-label="Drag to turn the model"'):
            self.assertIn(wanted, slider)
        for wanted in ("Drag to turn", "Play again", "Show picture"):
            self.assertIn(wanted, said(ready))
        # The picture's caption stays while the video shows (its line is hidden then): first, then the controls.
        lines = said(ready[ready.index('<div class="vid-line">'):])
        self.assertRegex(lines, r"^Look and fit will differ on the real pieces\. ?Look and fit will differ\. "
                                r"Drag to turn Play again Show picture")
        clip = re.search(r'<video class="vid-clip"[^>]*>', ready).group(0)
        for wanted in ("muted", "playsinline", 'preload="none"', f'poster="/looks/{look.file}"'):
            self.assertIn(wanted, clip)
        self.assertNotIn("autoplay", clip, "app.js plays it, and not where the device asks for less motion")
        page = self.client.get("/outfits").data.decode()            # reloaded: the picture, and the video to play
        self.assertIn("data-vid-open", page)
        self.assertNotIn("data-play", page)
        self.assertEqual(len(self.made), 1)

    def test_the_bands_words_are_heard_on_each_of_its_buttons_close_too(self):
        # Whichever of the band's buttons has keyboard focus, a screen reader hears the band's words with it: also
        # "No videos left today: more tomorrow" with Close, the only button left then.
        outfit, look = self.picture()
        described = f'aria-describedby="vid-said-{outfit.key}"'
        offer = self.part(outfit, look, ask="1")
        buttons = re.findall(r"<button[^>]*>.*?</button>", offer, re.S)
        self.assertEqual([said(button) for button in buttons], ["Make the video", "Not now"])
        for button in buttons:
            self.assertIn(described, button)
        self.with_video_rules(per_day=0)
        used = self.part(outfit, look, ask="1")
        buttons = re.findall(r"<button[^>]*>.*?</button>", used, re.S)
        self.assertEqual([said(button) for button in buttons], ["Close"])
        self.assertIn(described, buttons[0])
        words = used[used.index(f'<span id="vid-said-{outfit.key}">'):used.index("<button")]
        self.assertIn("No videos left today: more tomorrow.", said(words))

    def test_a_video_that_cannot_start_is_neither_left_being_made_nor_counted(self):
        # The row was claimed and the day's video taken, then the making could not start (no thread to run it).
        # Nothing went to Google: the video is not "being made" for minutes, and the day's video is given back.
        outfit, look = self.picture()
        with mock.patch.object(videos, "_spawn", side_effect=RuntimeError("can't start new thread")):
            shown = self.make(outfit, look)
        self.assertEqual(db.video_requests(0), 0, "the day's video was spent on nothing")
        self.assertNotIn("Making the video", shown)
        self.assertIn("Something went wrong while making the video. Try again.", said(shown))
        self.assertIn("Try again", shown)
        self.assertEqual(videos.of(look).status, "failed")
        self.assertEqual(self.made, [])
        self.assertIn("data-play", self.make(outfit, look), "Try again makes it")
        self.assertEqual((len(self.made), db.video_requests(0)), (1, 1))

    def test_a_video_another_request_has_just_claimed_is_counted_once(self):
        # Two asks at once: between this one taking the day's video and claiming the making, the other claimed it.
        # This one gives its video back and shows the one being made.
        outfit, look = self.picture()
        taken = db.take_video_ticket

        def and_the_other_claims_it(*args, **kwargs):
            ticket = taken(*args, **kwargs)
            key = videos.fingerprint(videos.service(), videos.clip_of("front").text, look.file)
            self.assertTrue(db.start_video(key, look.file, videos.service().tag, None, 0.0))   # the other request
            return ticket
        with mock.patch.object(db, "take_video_ticket", and_the_other_claims_it):
            shown = self.make(outfit, look)
        self.assertEqual(db.video_requests(0), 0, "counted for a video another request is making")
        self.assertIn("Making the video", shown)
        self.assertEqual(self.made, [], "made twice")

    def test_a_video_whose_file_has_gone_is_made_again(self):
        outfit, look = self.picture()
        self.make(outfit, look)
        for clip in videos.folder().glob("*.mp4"):                  # its folder emptied, say
            clip.unlink()
        self.assertIn("Make the video", self.part(outfit, look, ask="1"))
        shown = self.make(outfit, look)
        self.assertEqual(len(self.made), 2, "made again, not 'being made' for ever")
        self.assertIn("data-play", shown)
        self.assertEqual(fetched(self.client, re.search(r'src="(/videos/[^"]+)"', shown).group(1)), 200)
        self.make(outfit, look)
        self.assertEqual(len(self.made), 2, "and then kept, as before")

    def test_asking_again_costs_nothing_and_the_file_is_served_in_parts(self):
        outfit, look = self.picture()
        shown = self.make(outfit, look)
        self.make(outfit, look)
        self.assertEqual(len(self.made), 1, "never paid for twice")
        self.assertIn("data-play", self.part(outfit, look, ask="1"), "already there: it plays, no offer")
        address = re.search(r'src="(/videos/[^"]+)"', shown).group(1)
        whole = self.client.get(address)
        self.assertEqual((whole.status_code, whole.mimetype, whole.data), (200, "video/mp4", CLIP))
        self.assertIn("immutable", whole.headers["Cache-Control"])
        whole.close()
        part = self.client.get(address, headers={"Range": "bytes=0-99"})
        self.assertEqual((part.status_code, len(part.data)), (206, 100), "phones play a video asked for in parts")
        part.close()
        self.assertEqual(self.client.get("/videos/../wardrobe.db").status_code, 404)
        self.assertEqual(self.client.get("/videos/" + "0" * 24 + "-1.mp4").status_code, 404)

    def test_a_refusal_and_a_failure_are_said_and_can_be_tried_again(self):
        outfit, look = self.picture()
        self.refuse_video = imagegen.DrawError("refused", "Google answered 400 safety: blocked")
        refused = self.make(outfit, look)
        self.assertIn("The AI would not make a video of this picture.", said(refused))
        self.assertIn("Try again", refused)
        self.assertIn("would not make a video", self.part(outfit, look, ask="1"), "said again when it is opened")
        self.assertNotIn("would not make", self.client.get("/outfits").data.decode(), "not over the picture on every page")
        self.refuse_video = None
        self.assertIn("data-play", self.make(outfit, look))
        self.assertEqual(len(self.made), 2)

    def test_a_failure_that_cost_nothing_does_not_count(self):
        outfit, look = self.picture()
        self.refuse_video = imagegen.DrawError("busy", "Google could not be reached", free=True)
        self.make(outfit, look)
        self.assertEqual(db.video_requests(0), 0)
        self.refuse_video = imagegen.DrawError("busy", "no answer in time")      # sent: it may have been billed
        self.make(outfit, look)
        self.assertEqual(db.video_requests(0), 1)

    def test_on_your_own_machine_only_the_sites_limit_applies(self):
        self.with_video_rules(per_day=2, per_customer_per_day=1)
        first, second, third = some_outfits(3)
        for outfit in (first, second):
            _, look = self.picture(outfit)
            self.assertIn("data-play", self.make(outfit, look))
        _, look = self.picture(third)
        refused = self.make(third, look)
        self.assertIn("No videos left today: more tomorrow.", said(refused))
        self.assertIn("per_day under [videos] in config/looks.toml", refused, "the limit is named here")
        self.assertNotIn("Make the video", refused)
        self.assertEqual(len(self.made), 2)

    def test_videos_never_use_up_pictures_nor_pictures_videos(self):
        self.with_video_rules(per_day=1)
        self.with_rules(per_day=2)
        first, second = some_outfits(2)
        _, look = self.picture(first)
        self.make(first, look)
        self.assertEqual((db.look_requests(0), db.video_requests(0)), (1, 1))
        self.picture(second)                                         # the second picture is still drawn
        self.assertEqual(len(self.drawn), 2)

    def test_drawing_a_picture_again_deletes_the_video_of_the_old_one(self):
        outfit, look = self.picture()
        self.make(outfit, look)
        self.assertEqual(len(self.videos_on_disk()), 1)
        later = looks.time.time() + 30                              # a new version comes later, with a new name
        with mock.patch.object(looks.time, "time", lambda: later):
            # A video costs more than a picture: "Draw again" asks first, as for the photos made from it. (It
            # removed the video without a word.)
            asked = said(self.post("/outfits/look", key=outfit.key, again="1").data.decode())
            self.assertIn("Draw the front picture again? Its video will be removed. “See it move” makes a new one, "
                          "as one of your videos for the day.", asked)
            self.assertEqual(len(self.videos_on_disk()), 1, "nothing is removed before he answers")
            self.post("/outfits/look", key=outfit.key, again="1", sure="1")
        self.assertEqual(self.videos_on_disk(), [])
        again = looks.get(look.key)
        self.assertNotEqual(again.file, look.file)
        self.assertNotIn("data-play", self.part(outfit, again, ask="1"), "the new picture has no video yet")

    def test_without_a_gemini_key_or_with_videos_off_there_is_no_trace(self):
        outfit, look = self.picture()
        with mock.patch.object(settings, "GEMINI_API_KEY", ""):
            self.assertNotIn("look-vid", self.client.get("/outfits").data.decode())
            self.assertEqual(self.client.get("/outfits/video", query_string={"look": look.key}).status_code, 404)
            self.assertEqual(self.post("/outfits/video", look=look.key).status_code, 404)
            self.assertNotIn("videos", said(self.client.get("/profile").data.decode()))
        self.with_video_rules(on=False)
        self.assertNotIn("look-vid", self.client.get("/outfits").data.decode())
        self.assertEqual(self.made, [])

    def test_only_a_finished_picture_can_be_made_into_a_video(self):
        self.assertEqual(self.client.get("/outfits/video", query_string={"look": "0" * 24}).status_code, 404)
        self.assertEqual(self.post("/outfits/video", look="not a key").status_code, 404)


class FromThePictureShowing(WithVideos, AppCase):
    """'See it move' starts from whichever of the outfit's pictures is showing, with a movement that fits it."""

    def setUp(self):
        super().setUp()
        self.switch_on()
        self.outfit = some_outfits(1)[0]
        self.post("/outfits/look", key=self.outfit.key)
        self.front = looks.get(look_key(self.outfit))
        self.post("/outfits/look", key=self.outfit.key, more="1")              # "More photos"

    def show(self, shot):
        """Tap a small picture. Returns (its box on the page, the picture)."""
        box = self.post("/outfits/look", key=self.outfit.key, shot=shot).data.decode()
        return box, looks.get(re.search(r'data-look="([0-9a-f]{24})"', box).group(1))

    def offer(self, look, **more):
        return said(self.client.get("/outfits/video", query_string={"look": look.key, "outfit": self.outfit.key,
                                                                    "ask": "1", **more}).data.decode())

    def make(self, look, **more):
        return self.post("/outfits/video", look=look.key, outfit=self.outfit.key, **more).data.decode()

    def test_the_offer_names_the_picture_it_will_animate_and_what_is_left_today(self):
        _, cafe = self.show("cafe")
        offer = self.offer(cafe)
        self.assertIn("AI video of the Café picture, 5 seconds: he moves naturally. 10 videos left today.", offer)
        self.assertIn("AI video of the Front picture, 8 seconds: he turns round once. 10 videos left today.",
                      self.offer(self.front))
        self.assertEqual(self.made, [], "nothing is made by opening the offer")

    def test_each_picture_gets_its_own_movement_from_exactly_that_stored_picture(self):
        rules = looks.load_rules()["videos"]
        for shot in ("walking", "turned", "street", "cafe", "library"):
            _, look = self.show(shot)
            self.make(look)
            sent = self.made[-1]
            self.assertEqual(sent["picture"], (looks.folder() / look.file).read_bytes(), f"{shot}: not that picture")
            self.assertEqual(sent["prompt"], f"{rules['start']} {rules['motion'][shot]} {rules['keep']}", shot)
            self.assertEqual(sent["seconds"], 5, f"{shot}: a few seconds, not the 8-second turn")
            self.assertNotIn("full circle", sent["prompt"], f"{shot}: only the front picture turns")
        self.assertEqual(len(self.made), 5)
        self.make(self.front)
        self.assertEqual((self.made[-1]["seconds"], rules["motion"]["front"] in self.made[-1]["prompt"]), (8, True))

    def test_which_picture_it_is_is_never_taken_from_the_page(self):
        # A request that names the café picture but claims it is the front one still gets the café's movement.
        _, cafe = self.show("cafe")
        self.make(cafe, shot="front")
        self.assertIn("lifts the cup", self.made[0]["prompt"])
        self.assertEqual(self.made[0]["seconds"], 5)
        # Without its outfit, a picture made from another cannot be told apart: nothing is made of it.
        response = self.post("/outfits/video", look=cafe.key)
        self.assertEqual(response.status_code, 404)
        missing = self.client.get("/outfits/video", query_string={"look": cafe.key, "outfit": "0" * 12})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(len(self.made), 1)
        self.assertEqual(videos.shot_of(self.front, None), "front", "a picture not made from another is a front picture")

    def test_one_clip_is_kept_for_each_picture_and_shown_again_without_a_new_charge(self):
        _, cafe = self.show("cafe")
        self.make(cafe)
        self.make(self.front)
        self.assertEqual((len(self.made), db.video_requests(0), len(self.videos_on_disk())), (2, 2, 2))
        # Asked again, from the offer or by "Make the video": the kept clip, and nothing is counted.
        self.assertIn("data-play", self.make(cafe))
        self.assertIn("data-play", self.client.get("/outfits/video", query_string={
            "look": cafe.key, "outfit": self.outfit.key, "ask": "1"}).data.decode())
        # Each picture's clip comes back with its picture: tap Front, then Café again.
        front_box, _ = self.show("front")
        cafe_box, _ = self.show("cafe")
        clips = [re.search(r'<video class="vid-clip" src="(/videos/[^"]+)"', box).group(1) for box in (front_box, cafe_box)]
        self.assertEqual(len(set(clips)), 2, "the two pictures show the same clip")
        self.assertIn('poster="/looks/' + cafe.file, cafe_box, "the café's clip lies over the café picture")
        street_box, _ = self.show("street")
        self.assertNotIn("vid-clip", street_box, "the street has no clip yet")
        self.assertIn("See it move", street_box)
        self.assertEqual((len(self.made), db.video_requests(0), len(self.videos_on_disk())), (2, 2, 2))
        page = self.client.get("/outfits").data.decode()         # the page shows the front picture, with its own clip
        self.assertIn(clips[0], page)
        self.assertNotIn(clips[1], page)

    def test_only_the_front_pictures_video_is_dragged_round_and_every_clip_is_muted(self):
        runs = []

        def ffmpeg(command, **options):
            runs.append(command)
            Path(command[-1]).write_bytes(CLIP[:5000])
            return subprocess.CompletedProcess(command, 0)

        _, cafe = self.show("cafe")
        with mock.patch.object(videos, "_ffmpeg", lambda: "/usr/bin/ffmpeg"), \
                mock.patch.object(videos.subprocess, "run", ffmpeg):
            moving = self.make(cafe)
            self.assertEqual(runs, [], "a clip that only plays needs no turn file")
            turning = self.make(self.front)
            self.assertEqual(len(runs), 1)
        self.assertIn("data-turns", turning)
        self.assertIn('role="slider"', turning)
        self.assertIn("Drag to turn", turning)
        self.assertNotIn("data-turns", moving)
        self.assertNotIn('role="slider"', moving)
        self.assertNotIn("Drag to turn", said(moving))
        self.assertIn("Café, moving", said(moving))
        self.assertIn('aria-label="AI video of this outfit, made from the Café picture, 5 seconds, without sound"', moving)
        self.assertIn("Play again", moving)
        for shown in (moving, turning):
            players = re.findall(r"<video [^>]*>", shown)
            self.assertTrue(players and all(" muted " in player for player in players), "a clip is not muted")

    def test_a_pose_without_a_movement_of_its_own_moves_naturally_and_the_length_is_a_setting(self):
        rules = looks.load_rules()["videos"]
        self.with_video_rules(seconds=4, motion={name: words for name, words in rules["motion"].items() if name != "library"})
        _, library = self.show("library")
        self.assertIn("AI video of the Library picture, 4 seconds: he moves naturally.", self.offer(library))
        self.make(library)
        self.assertIn(rules["motion"]["other"], self.made[0]["prompt"])
        self.assertEqual(self.made[0]["seconds"], 4)

    def test_drawing_the_front_picture_again_takes_every_pictures_clip_with_it(self):
        _, cafe = self.show("cafe")
        self.make(cafe)
        self.make(self.front)
        self.assertEqual(len(self.videos_on_disk()), 2)
        later = looks.time.time() + 30                              # a new version comes later, with a new name
        with mock.patch.object(looks.time, "time", lambda: later):
            asked = said(self.post("/outfits/look", key=self.outfit.key, again="1").data.decode())
            self.assertIn("Draw the front picture again? The other 5 photos of this outfit are made from it, so they "
                          "will be removed, and with them the 2 videos made from these pictures. “More photos” draws "
                          "them again. “See it move” makes a new video, as one of your videos for the day.", asked)
            self.post("/outfits/look", key=self.outfit.key, again="1", sure="1")    # asked first, and answered yes
        self.assertEqual(self.videos_on_disk(), [], "clips of pictures that are gone")


class TryingTheVideoModel(WithVideos, AppCase):
    """python -m wardrobe looks --test-video: one clip from a sample picture, also with another model name."""

    def setUp(self):
        super().setUp()
        self.switch_on()

    def run_looks(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            main(["looks", *args])
        return out.getvalue()

    def test_it_makes_the_sample_front_pictures_turn_and_can_try_another_model_name(self):
        with self.assertRaises(SystemExit) as stopped:
            self.run_looks("--test-video")
        self.assertIn("Nothing was sent", str(stopped.exception))
        self.assertIn("looks --test-set", str(stopped.exception))
        self.assertEqual(self.made, [])
        self.run_looks("--test-set")
        told = self.run_looks("--test-video")
        self.assertIn("Making a 8-second video from the sample outfit's Front picture with gemini-omni-flash-preview", told)
        self.assertIn("It works:", told)
        self.assertEqual((videos.folder() / "sample.mp4").read_bytes(), CLIP)
        self.assertEqual((self.made[0]["service"].model, self.made[0]["seconds"]), ("gemini-omni-flash-preview", 8))
        self.assertEqual(self.made[0]["picture"], (looks.folder() / "sample.jpg").read_bytes())

        told = self.run_looks("--test-video", "cafe", "--video-model", "gemini-omni-1.2-flash")
        self.assertIn("5-second video from the sample outfit's Café picture with gemini-omni-1.2-flash", told)
        sent = self.made[1]
        self.assertEqual((sent["service"].model, sent["service"].task, sent["seconds"]),
                         ("gemini-omni-1.2-flash", "image_to_video", 5))
        self.assertEqual(sent["picture"], (looks.folder() / "sample-cafe.jpg").read_bytes())
        self.assertIn("lifts the cup", sent["prompt"])
        self.assertTrue((videos.folder() / "sample-cafe.mp4").is_file())
        self.assertEqual(looks.load_rules()["videos"]["model"], "gemini-omni-flash-preview", "the setting is untouched")
        self.assertEqual(db.video_requests(0), 0, "a trial from the command line is not one of the site's videos")

    def test_googles_answer_to_a_name_it_does_not_know_is_said(self):
        self.run_looks("--test-set")
        self.refuse_video = imagegen.DrawError("model", "models/gemini-omni-1.2-flash is not found")
        with self.assertRaises(SystemExit) as stopped:
            self.run_looks("--test-video", "--video-model", "gemini-omni-1.2-flash")
        self.assertIn("It did not work: Google does not know the video model", str(stopped.exception))
        self.assertIn("gemini-omni-1.2-flash is not found", str(stopped.exception))
        self.assertIn("--test-video", self.run_looks())       # the plain command says how to try a video


class TurnFile(WithVideos, AppCase):
    """Drag to turn: the turn kept with every frame a keyframe, where ffmpeg is installed."""

    def setUp(self):
        super().setUp()
        self.switch_on()

    def made_video(self):
        outfit = some_outfits(1)[0]
        self.post("/outfits/look", key=outfit.key)
        look = looks.get(look_key(outfit))
        return self.post("/outfits/video", look=look.key, outfit=outfit.key).data.decode()

    def test_with_ffmpeg_the_turn_is_made_and_dragged(self):
        runs = []

        def ffmpeg(command, **options):
            runs.append(command)
            Path(command[-1]).write_bytes(CLIP[:5000])
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(videos, "_ffmpeg", lambda: "/usr/bin/ffmpeg"), \
                mock.patch.object(videos.subprocess, "run", ffmpeg):
            shown = self.made_video()
        self.assertEqual(len(runs), 1)
        command = runs[0]
        self.assertEqual(command[0], "/usr/bin/ffmpeg")
        for wanted in (["-t", "6.2"], ["-g", "1"], ["-an"], ["-vf", "scale=540:-2"]):
            self.assertIn(" ".join(wanted), " ".join(command))
        drag = re.search(r'<video class="vid-drag"[^>]*>', shown).group(0)
        self.assertRegex(drag, r'src="/videos/[0-9a-f]{24}-\d+-turn\.mp4"')
        self.assertEqual(len(self.videos_on_disk()), 2)
        address = re.search(r'src="(/videos/[^"]+-turn\.mp4)"', drag).group(1)
        self.assertEqual(fetched(self.client, address), 200)

    def test_a_lost_clip_is_made_again_and_its_old_turn_goes(self):
        def ffmpeg(command, **options):
            Path(command[-1]).write_bytes(CLIP[:5000])
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(videos, "_ffmpeg", lambda: "/usr/bin/ffmpeg"), \
                mock.patch.object(videos.subprocess, "run", ffmpeg):
            self.made_video()
            old_turn = next(name for name in self.videos_on_disk() if name.endswith("-turn.mp4"))
            (videos.folder() / old_turn.replace("-turn", "")).unlink()       # the clip has gone, its turn not
            later = videos.time.time() + 30                                 # made again later, under new names
            with mock.patch.object(videos.time, "time", lambda: later):
                shown = self.made_video()
        self.assertEqual(len(self.made), 2)
        self.assertIn("vid-drag", shown)
        self.assertNotIn(old_turn, self.videos_on_disk(), "the old turn is not left behind")
        self.assertEqual(len(self.videos_on_disk()), 2)

    def test_without_ffmpeg_the_clip_itself_is_dragged(self):
        shown = self.made_video()
        self.assertNotIn("vid-drag", shown)
        self.assertIn('data-turn-seconds="6.2"', shown, "how much of the clip a drag across it goes through")
        self.assertEqual(len(self.videos_on_disk()), 1)

    def test_when_ffmpeg_fails_the_video_is_still_there(self):
        def broken(command, **options):
            raise subprocess.CalledProcessError(1, command)

        with mock.patch.object(videos, "_ffmpeg", lambda: "/usr/bin/ffmpeg"), \
                mock.patch.object(videos.subprocess, "run", broken):
            shown = self.made_video()
        self.assertIn("data-play", shown)
        self.assertNotIn("vid-drag", shown)
        self.assertEqual(len(self.videos_on_disk()), 1, "no half-made turn left behind")

    @unittest.skipUnless(FFMPEG, "ffmpeg is not installed here")
    def test_the_real_ffmpeg_makes_every_frame_a_keyframe(self):
        folder = videos.folder()
        folder.mkdir(parents=True, exist_ok=True)
        clip = folder / "clip.mp4"
        clip.write_bytes(CLIP)
        with mock.patch.object(videos, "_ffmpeg", lambda: shutil.which("ffmpeg")):
            turn = videos.turn_file(clip, folder / "clip-turn.mp4")
        self.assertIsNotNone(turn)
        probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-select_streams", "v", "-show_entries",
                                "frame=key_frame:format=duration", "-of", "json", str(turn)],
                               capture_output=True, check=True, text=True)
        found = json.loads(probe.stdout)
        frames = [frame["key_frame"] for frame in found["frames"]]
        self.assertGreater(len(frames), 100)
        self.assertEqual(set(frames), {1}, "every frame a keyframe")
        self.assertAlmostEqual(float(found["format"]["duration"]), 6.2, delta=0.1)


class VideosForCustomers(WithVideos, ProductionCase):
    def setUp(self):
        super().setUp()
        self.switch_on()

    def picture_of(self, client, which=0):
        """An outfit of a customer's page (the first, or another), drawn. Returns (its key, its picture)."""
        key = re.findall(r'id="outfit-(\w+)"', client.get("/outfits").data.decode())[which]
        box = self.post(client, "/outfits/look", headers=HX, key=key).data.decode()
        return key, re.search(r'data-look="([0-9a-f]{24})"', box).group(1)

    def offer(self, client, key, look):
        return said(client.get(f"/outfits/video?look={look}&outfit={key}&ask=1").data.decode())

    def make(self, client, key, look):
        return self.post(client, "/outfits/video", headers=HX, look=look, outfit=key).data.decode()

    def test_every_customer_has_one_video_a_day_and_is_told_so(self):
        ada = self.member("ada@example.com")
        key, look = self.picture_of(ada)
        self.assertIn("1 video left today.", self.offer(ada, key, look))
        self.assertIn("data-play", self.make(ada, key, look))
        bob = self.member("bob@example.com")
        bob_key, bob_look = self.picture_of(bob, 1)
        self.assertIn("1 video left today.", self.offer(bob, bob_key, bob_look), "his own allowance")
        other, second = self.picture_of(ada, 1)
        offer = self.offer(ada, other, second)
        self.assertIn("No videos left today: more tomorrow.", offer)
        self.assertNotIn("Make the video", offer)
        refused = self.make(ada, other, second)
        self.assertIn("No videos left today: more tomorrow.", said(refused))
        self.assertNotIn("config/looks.toml", refused, "customers are not sent to the settings")
        self.assertEqual(len(self.made), 1)
        self.assertEqual(len(self.drawn), 2, "pictures go on: a video is not a picture")

    def test_pro_accounts_and_owners_have_five(self):
        ada = self.member("ada@example.com")
        key, look = self.picture_of(ada)
        with redirect_stdout(io.StringIO()) as printed:
            main(["pro", "add", "ada@example.com"])
        self.assertIn("ada@example.com is now Pro: 5 videos a day instead of 1", printed.getvalue())
        self.assertIn("5 videos left today.", self.offer(ada, key, look))
        self.make(ada, key, look)
        other, second = self.picture_of(ada, 1)
        self.assertIn("4 videos left today.", self.offer(ada, other, second))
        with redirect_stdout(io.StringIO()) as printed:
            main(["pro", "list"])
        self.assertIn("ada@example.com", printed.getvalue())
        with redirect_stdout(io.StringIO()):
            main(["pro", "remove", "ada@example.com"])
        self.assertFalse(db.is_pro(self.user_id("ada@example.com")))
        bob = self.member("bob@example.com")
        db.add_owner("bob@example.com")
        bob_key, bob_look = self.picture_of(bob, 2)
        self.assertIn("5 videos left today.", self.offer(bob, bob_key, bob_look), "an owner counts as Pro")
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                main(["pro", "add", "nobody@example.com"])

    def test_the_whole_site_has_ten_a_day(self):
        self.with_video_rules(per_day=1)
        ada, bob = self.member("ada@example.com"), self.member("bob@example.com")
        key, look = self.picture_of(ada)
        self.make(ada, key, look)
        other, second = self.picture_of(bob, 1)
        self.assertIn("No videos left today: more tomorrow.", self.offer(bob, other, second))
        self.assertIn("No videos left today", said(self.make(bob, other, second)))
        self.assertIn("data-play", bob.get(f"/outfits/video?look={look}&outfit={key}&ask=1").data.decode(),
                      "the video Ada asked for is there for him too")
        self.assertEqual(len(self.made), 1)
        self.assertEqual(looks.load_rules()["videos"]["per_day"], 1)

    def test_the_real_limits_are_one_five_and_ten(self):
        self.assertEqual({name: looks.load_rules()["videos"][name]
                          for name in ("per_customer_per_day", "pro_per_customer_per_day", "per_day")},
                         {"per_customer_per_day": 1, "pro_per_customer_per_day": 5, "per_day": 10})

    def test_customers_share_the_video_of_the_same_picture(self):
        ada, bob = self.member("ada@example.com"), self.member("bob@example.com")
        key, look = self.picture_of(ada)
        shown = self.make(ada, key, look)
        address = re.search(r'src="(/videos/[^"]+)"', shown).group(1)
        self.assertIn(address, bob.get("/outfits").data.decode(), "already there for the next customer")
        self.assertEqual(fetched(bob, address), 200)
        self.make(bob, key, look)
        self.assertEqual(len(self.made), 1, "and not paid for twice")
        self.assertEqual(db.video_requests(0), 1, "nor counted for him")
        self.assertEqual(self.app.test_client().get(address).status_code, 302, "not for anybody logged out")

    def test_a_video_of_someone_is_theirs_alone_and_goes_with_their_photo_and_account(self):
        ada, bob = self.member("ada@example.com"), self.member("bob@example.com")
        uid = self.user_id("ada@example.com")
        key, shared_look = self.picture_of(ada)
        self.make(ada, key, shared_look)                            # a video with no real person in it: stays
        ada.post("/profile/photo", content_type="multipart/form-data", data={
            "photo": (io.BytesIO(PHOTO), "me.jpg"), "agree": "on", "csrf_token": self.token(ada)})
        with mock.patch.object(videos, "allowance", lambda: 5):
            key, look = self.picture_of(ada)
            shown = self.make(ada, key, look)
        address = re.search(r'src="(/videos/[^"]+)"', shown).group(1)
        self.assertEqual(fetched(ada, address), 200)
        self.assertEqual(bob.get(address).status_code, 404)
        self.assertNotIn(address, bob.get("/outfits").data.decode())
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM videos WHERE user_id = ?", (uid,)).fetchone()[0], 1)
        self.assertEqual(len(self.videos_on_disk()), 2)

        self.post(ada, "/profile/photo", remove="1")               # the photo goes: its pictures and their videos
        self.assertEqual(len(self.videos_on_disk()), 1)
        self.assertEqual(ada.get(address).status_code, 404)

        ada.post("/profile/photo", content_type="multipart/form-data", data={
            "photo": (io.BytesIO(PHOTO), "me.jpg"), "agree": "on", "csrf_token": self.token(ada)})
        with mock.patch.object(videos, "allowance", lambda: 5):
            key, look = self.picture_of(ada)
            self.make(ada, key, look)
        self.assertEqual(len(self.videos_on_disk()), 2)
        copy_of_data = json.loads(ada.get("/account/export").data)
        self.assertEqual(len(copy_of_data["ai_videos_asked_for_at"]), 3)
        self.post(ada, "/account/delete", current=PASSWORD)       # the account goes: so does the video of her
        self.assertIsNone(person.photo_of(uid))
        self.assertEqual(len(self.videos_on_disk()), 1)
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM videos WHERE user_id = ?", (uid,)).fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM video_requests WHERE user_id = ?", (uid,)).fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM video_requests").fetchone()[0], 3,
                             "deleting an account does not hand back the day's total")

    def upload(self, client):
        client.post("/profile/photo", content_type="multipart/form-data", data={
            "photo": (io.BytesIO(PHOTO), "me.jpg"), "agree": "on", "csrf_token": self.token(client)})

    def test_the_date_kept_with_a_photo_is_that_of_the_words_shown(self):
        ada = self.member("ada@example.com")
        self.assertIn("to make videos of them when I ask", said(ada.get("/profile").data.decode()))
        self.upload(ada)
        # Two dates, one for each part of the box's words: the photo's (app.PHOTO_CONSENT) and the videos'.
        kept = json.loads(ada.get("/account/export").data)["settings"]
        self.assertEqual((kept["photo_consent"], kept["video_consent"]["words"]), (PHOTO_CONSENT, videos.CONSENT))
        self.assertEqual(kept["video_consent"]["photo_added"], kept["photo_added"], "for this photo")
        bob = self.member("bob@example.com")
        with mock.patch.object(videos, "service", lambda: None):        # videos off: the words say nothing of them
            self.assertNotIn("videos", said(bob.get("/profile").data.decode()))
            self.upload(bob)
        kept = json.loads(bob.get("/account/export").data)["settings"]
        self.assertEqual(kept["photo_consent"], PHOTO_CONSENT)
        self.assertNotIn("video_consent", kept, "he agreed to nothing about videos")
        self.assertEqual((PHOTO_CONSENT, videos.CONSENT), ("2026-11-15", "2026-11-13"))

    def test_the_photos_newer_date_is_never_taken_for_agreeing_to_videos(self):
        # The photo's words are dated later (15 Nov) than the videos' (13 Nov). A photo added while videos were off
        # carries the later date and still needs the tick before a picture of him goes to Google for a video.
        ada = self.member("ada@example.com")
        with mock.patch.object(videos, "service", lambda: None):
            self.upload(ada)
        key, look = self.picture_of(ada)
        self.assertGreater(PHOTO_CONSENT, videos.CONSENT)
        self.assertIn("I agree to Stilsmith sending this picture of me", self.offer(ada, key, look))
        self.assertIn("tick the box to agree to it going to Google first", said(self.make(ada, key, look)))
        self.assertEqual(self.made, [], "nothing was sent")

    def test_a_photo_added_with_the_videos_words_before_the_dates_were_split_still_counts(self):
        # Until 15 Nov one setting held both: "2026-11-13" meant the box he ticked had the videos' words in it.
        ada = self.member("ada@example.com")
        self.upload(ada)
        with db.as_user(self.user_id("ada@example.com")):
            db.set_setting("photo_consent", "2026-11-13")
            db.set_setting("video_consent", None)
            self.assertTrue(videos.consented())
            db.set_setting("photo_consent", "2026-11-12")               # added before the videos' words
            self.assertFalse(videos.consented())

    def test_a_photo_added_before_the_words_about_videos_needs_a_tick_first(self):
        ada = self.member("ada@example.com")
        with mock.patch.object(videos, "service", lambda: None):        # videos were off when she added it
            self.upload(ada)
        key, look = self.picture_of(ada)                                # drawn from her photo
        offer = ada.get(f"/outfits/video?look={look}&outfit={key}&ask=1").data.decode()
        box = re.search(r'<label class="check">(.*?)</label>', offer, re.S).group(1)
        self.assertIn("I agree to Stilsmith sending this picture of me to Google to make the video.", said(box))
        for wanted in ('name="agree"', "required", f'aria-describedby="vid-said-{key}"'):
            self.assertIn(wanted, box)
        self.assertLess(offer.index('name="agree"'), offer.index("Make the video"), "the box comes first")
        not_ticked = said(self.make(ada, key, look))                   # sent without it (no browser stops that)
        self.assertIn("tick the box to agree to it going to Google first", not_ticked)
        self.assertEqual((self.made, db.video_requests(0)), ([], 0), "nothing sent, nothing counted")
        ticked = self.post(ada, "/outfits/video", headers=HX, look=look, outfit=key, agree="on").data.decode()
        self.assertIn("data-play", ticked)
        self.assertEqual(len(self.made), 1)
        kept = json.loads(ada.get("/account/export").data)["settings"]
        self.assertEqual((kept["photo_consent"], kept["video_consent"]["words"]), (PHOTO_CONSENT, videos.CONSENT),
                         "what she agreed to, and when, in her copy of her data")
        with mock.patch.object(videos, "allowance", lambda: 5):
            other, second = self.picture_of(ada, 1)
            self.assertNotIn("I agree", self.offer(ada, other, second), "asked once for this photo")
            bob = self.member("bob@example.com")                        # no photo: nothing to agree to
            bob_key, bob_look = self.picture_of(bob, 2)
            self.assertNotIn("I agree", self.offer(bob, bob_key, bob_look))
            # A new photo added while videos are off again: her tick was for the photo before it.
            with mock.patch.object(videos, "service", lambda: None), \
                    mock.patch.object(db, "now_iso", lambda: "2099-01-01T00:00:00+01:00"):
                self.upload(ada)
            key, look = self.picture_of(ada, 3)
            self.assertIn("I agree to Stilsmith sending this picture of me", self.offer(ada, key, look))
            self.upload(ada)                                            # added with the words about videos: no box
            key, look = self.picture_of(ada, 4)
            self.assertNotIn("I agree", self.offer(ada, key, look))

    def test_a_refused_video_of_someones_photo_says_why_plainly(self):
        ada = self.member("ada@example.com")
        ada.post("/profile/photo", content_type="multipart/form-data", data={
            "photo": (io.BytesIO(PHOTO), "me.jpg"), "agree": "on", "csrf_token": self.token(ada)})
        key, look = self.picture_of(ada)
        self.refuse_video = imagegen.DrawError("refused", "Google answered 400 safety: real person")
        with mock.patch.object(settings, "on_this_machine", lambda: False):    # customers, on a public address
            refused = said(self.make(ada, key, look))
        self.assertIn("It turns down some pictures of real, recognisable people, and this one is drawn from your photo.",
                      refused)
        self.assertNotIn("Google", refused, "customers are told about the AI, not the inside")

    def test_a_failure_that_used_the_last_video_does_not_say_try_again(self):
        # Google worked on it and failed: it counts, and that was his one video today. The offer then says what went
        # wrong and that none are left, with only Close: never "Try again" beside "No videos left today".
        ada = self.member("ada@example.com")
        key, look = self.picture_of(ada)
        self.refuse_video = imagegen.DrawError("busy", "no answer in time")          # sent: it may have been billed
        with mock.patch.object(settings, "on_this_machine", lambda: False):
            shown = said(self.make(ada, key, look))
            again = self.offer(ada, key, look)                                          # opened again later
        for offer in (shown, again):
            self.assertIn("The AI is busy or did not answer in time. No videos left today: more tomorrow.", offer)
            self.assertNotIn("Try again", offer)
            self.assertNotIn("Make the video", offer)
            self.assertIn("Close", offer)
        self.assertEqual(db.video_requests(0), 1)
        # With a video left, the same failure still says to try again, with the button that does.
        self.with_video_rules(per_customer_per_day=2)
        with mock.patch.object(settings, "on_this_machine", lambda: False):
            offer = self.offer(ada, key, look)
        self.assertIn("The AI is busy or did not answer in time. Try again in a minute. 1 video left today.", offer)

    def test_a_problem_only_the_operator_can_fix_is_not_shown_to_customers(self):
        ada = self.member("ada@example.com")
        key, look = self.picture_of(ada)
        self.refuse_video = imagegen.DrawError("model", "Google answered 404 not_found: no such model", free=True)
        with mock.patch.object(settings, "on_this_machine", lambda: False):
            shown = said(self.make(ada, key, look))
        self.assertIn("Videos are not available at the moment.", shown)
        self.assertNotIn("404", shown)
        self.assertEqual(db.video_requests(0), 0, "it cost nothing")

    def test_the_photo_consent_and_the_privacy_outline_say_what_happens(self):
        ada = self.member("ada@example.com")
        profile = words(ada.get("/profile").get_data(as_text=True))
        self.assertIn("When you ask for a video of a picture of you (“See it move”), that picture goes to Google, "
                      "which makes the video from it.", profile)
        self.assertIn("and the pictures made from it go with it, with their videos.", profile)
        self.assertIn("and those pictures to Google to make videos of them when I ask.", profile)
        privacy = words(self.app.test_client().get("/legal/privacy").get_data(as_text=True))
        self.assertIn("AI videos of outfits", privacy)
        self.assertIn("the outfit's AI picture is sent to Google's video model", privacy)
        self.assertIn("deleted with it: when you delete the photo or your account", privacy)
        self.assertIn("A picture drawn from your photo goes to Google only once you have agreed to it", privacy)

    def test_the_videos_need_a_login_and_the_pages_token(self):
        ada = self.member("ada@example.com")
        key, look = self.picture_of(ada)
        visitor = self.app.test_client()
        self.assertEqual(self.post(visitor, "/outfits/video", headers=HX, look=look).status_code, 401)
        self.assertEqual(visitor.get(f"/outfits/video?look={look}").status_code, 302)
        no_token = ada.post("/outfits/video", data={"look": look, "outfit": key}, headers=HX)
        self.assertEqual(no_token.status_code, 400, "no token")
        self.assertEqual(self.made, [])
        offer = ada.get(f"/outfits/video?look={look}&outfit={key}&ask=1").data.decode()
        self.assertEqual(offer.count('name="csrf_token"'), offer.count("<form"))


class GoogleVideoModel(unittest.TestCase):
    """The request behind client.interactions.create, answered from canned replies."""

    def setUp(self):
        self.sent = []
        self.answers = []
        self.service = videogen.Service(model="gemini-omni-flash-preview", key="AIza-test-key-123456")

        def fake_send(url, headers, body, timeout=imagegen.TIMEOUT):
            self.sent.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
            return self.answers.pop(0)

        opener = mock.Mock()
        opener.open.side_effect = AssertionError("a network connection was opened")
        for patch in (mock.patch.object(imagegen, "_send", fake_send), mock.patch.object(imagegen, "_opener", opener)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(lambda: self.assertFalse(opener.open.called))

    def answer(self, *content, status=200, state="completed"):
        return status, json.dumps({"status": state, "steps": [{"type": "model_output", "content": list(content)}]}).encode()

    def test_the_picture_and_the_words_go_to_the_interactions_address(self):
        self.answers.append(self.answer({"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(CLIP).decode()}))
        self.assertEqual(videogen.make(self.service, PICTURE, "Turn round once."), CLIP)
        sent = self.sent[0]
        self.assertEqual(sent["url"], "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(sent["headers"]["x-goog-api-key"], "AIza-test-key-123456")
        self.assertGreaterEqual(sent["timeout"], 240, "a clip takes up to two minutes")
        payload = json.loads(sent["body"])
        self.assertEqual(payload["model"], "gemini-omni-flash-preview")
        self.assertEqual(payload["input"], [{"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(PICTURE).decode()},
                                            {"type": "text", "text": "Turn round once."}])
        self.assertEqual(payload["response_format"], {"type": "video", "duration": "8s", "aspect_ratio": "9:16",
                                                      "resolution": "720p"})
        self.assertNotIn("generation_config", payload, "no task set: nothing about it is sent")

    def test_the_picture_is_named_as_the_first_frame_and_the_clip_has_the_length_asked_for(self):
        self.answers.append(self.answer({"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(CLIP).decode()}))
        service = videogen.Service(model="gemini-omni-flash-preview", key="AIza-test-key-123456", task="image_to_video")
        self.assertEqual(videogen.make(service, PICTURE, "Lift the cup.", seconds=5), CLIP)
        payload = json.loads(self.sent[0]["body"])
        self.assertEqual(payload["generation_config"], {"video_config": {"task": "image_to_video"}})
        self.assertEqual(payload["response_format"]["duration"], "5s")
        self.assertEqual(payload["input"][0]["data"], base64.b64encode(PICTURE).decode(), "the stored picture itself")
        self.assertNotEqual(service.tag, self.service.tag, "a clip made with the task is another clip")

    def test_a_video_kept_on_googles_server_is_fetched_with_the_key_only_from_there(self):
        uri = "https://generativelanguage.googleapis.com/v1beta/files/abc:download?alt=media"
        self.answers += [self.answer({"type": "video", "uri": uri}), (200, CLIP)]
        self.assertEqual(videogen.make(self.service, PICTURE, "Turn."), CLIP)
        self.assertEqual((self.sent[1]["url"], self.sent[1]["body"]), (uri, None))
        self.assertEqual(self.sent[1]["headers"]["x-goog-api-key"], "AIza-test-key-123456")
        self.answers.append(self.answer({"type": "video", "uri": "https://elsewhere.example/clip.mp4"}))
        with self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        self.assertEqual(len(self.sent), 3, "the key never goes to another server")
        self.assertIn("another server", caught.exception.detail)

    def test_a_video_handed_over_from_googles_storage_is_followed_once_without_the_key(self):
        uri = "https://generativelanguage.googleapis.com/v1beta/files/abc:download?alt=media"
        storage = "https://storage.googleapis.com/some-bucket/abc.mp4?signature=made-up"
        self.answers += [self.answer({"type": "video", "uri": uri}), (302, storage.encode()), (200, CLIP)]
        self.assertEqual(videogen.make(self.service, PICTURE, "Turn."), CLIP)
        self.assertEqual([sent["url"] for sent in self.sent[1:]], [uri, storage])
        self.assertEqual(self.sent[1]["headers"]["x-goog-api-key"], "AIza-test-key-123456")
        self.assertNotIn("x-goog-api-key", self.sent[2]["headers"], "the key goes only to Google's own address")
        self.assertIsNone(self.sent[2]["body"])
        self.answers += [self.answer({"type": "video", "uri": uri}), (307, b"/download/abc.mp4"), (200, CLIP)]
        self.assertEqual(videogen.make(self.service, PICTURE, "Turn."), CLIP)
        self.assertEqual(self.sent[5]["url"], "https://generativelanguage.googleapis.com/download/abc.mp4")
        for elsewhere in (b"https://elsewhere.example/abc.mp4", b"http://storage.googleapis.com/abc.mp4",
                          b"https://storage.googleapis.com.example/abc.mp4", b""):
            self.answers += [self.answer({"type": "video", "uri": uri}), (302, elsewhere)]
            asked = len(self.sent)
            with self.assertRaises(imagegen.DrawError, msg=elsewhere) as caught:
                videogen.make(self.service, PICTURE, "Turn.")
            self.assertEqual(len(self.sent), asked + 2, f"{elsewhere!r} was followed")
            self.assertEqual(caught.exception.kind, "busy")
            self.assertFalse(caught.exception.free, "Google made the video: it is not handed back as free")

    def test_refusals_and_problems_are_told_apart(self):
        cases = [
            ((400, json.dumps({"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "x"}}).encode()), "request"),
            ((404, json.dumps({"error": {"code": 404, "status": "NOT_FOUND", "message": "models/x is not found"}}).encode()), "model"),
            ((200, json.dumps({"status": "failed", "steps": [{"type": "model_output", "error":
                                                              {"code": "safety", "message": "a real person"}}]}).encode()), "refused"),
            ((200, json.dumps({"status": "completed", "steps": []}).encode()), "empty"),
            (self.answer({"type": "video", "data": base64.b64encode(b"not a video at all").decode()}), "empty"),
            ((429, json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "slow down"}}).encode()), "busy"),
        ]
        for answer, kind in cases:
            self.answers.append(answer)
            with self.assertRaises(imagegen.DrawError, msg=kind) as caught:
                videogen.make(self.service, PICTURE, "Turn.")
            self.assertEqual(caught.exception.kind, kind, answer)
            self.assertNotIn("AIza-test-key-123456", str(caught.exception))

    def video(self):
        return {"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(CLIP).decode()}

    def waits(self):
        waited = []
        patch = mock.patch.object(videogen, "_wait", waited.append)
        patch.start()
        self.addCleanup(patch.stop)
        return waited

    def test_an_answer_still_being_made_is_asked_again_by_its_id_until_it_is_done(self):
        waited = self.waits()
        self.answers += [(200, json.dumps({"id": "v1_abc", "status": "in_progress"}).encode()),
                         (200, json.dumps({"id": "v1_abc", "status": "queued"}).encode()),
                         (200, json.dumps({"id": "v1_abc", "status": "in_progress", "steps": []}).encode()),
                         (200, json.dumps({"id": "v1_abc", "status": "completed",
                                           "steps": [{"type": "model_output", "content": [self.video()]}]}).encode())]
        self.assertEqual(videogen.make(self.service, PICTURE, "Turn."), CLIP, "an unfinished answer is not 'no video'")
        asked = self.sent[1:]
        self.assertEqual([sent["url"] for sent in asked],
                         ["https://generativelanguage.googleapis.com/v1beta/interactions/v1_abc"] * 3)
        for sent in asked:
            self.assertIsNone(sent["body"], "asked again with GET, nothing sent again")
            self.assertEqual(sent["headers"]["x-goog-api-key"], "AIza-test-key-123456")
            self.assertLessEqual(sent["timeout"], videogen.TIMEOUT)
        self.assertEqual(waited, [videogen.ASK_AGAIN_SECONDS] * 3, "a few seconds between two questions")

    def test_an_answer_that_stopped_part_way_goes_on_with_its_token(self):
        self.answers += [(200, json.dumps({"id": "v1_one", "status": "requires_continuation", "continuation_token": "t1",
                                           "steps": [{"type": "model_output", "content": [{"type": "text", "text": "…"}]}]}).encode()),
                         (200, json.dumps({"id": "v1_two", "status": "requires_continuation", "continuation_token": "t2",
                                           "steps": []}).encode()),
                         self.answer(self.video())]
        self.assertEqual(videogen.make(self.service, PICTURE, "Turn."), CLIP)
        first, *going_on = [json.loads(sent["body"]) for sent in self.sent]
        self.assertIn("input", first)
        self.assertEqual([(body["continuation_token"], body["previous_interaction_id"]) for body in going_on],
                         [("t1", "v1_one"), ("t2", "v1_two")], "each part goes on from the one before it")
        for body in going_on:
            self.assertNotIn("input", body, "Google kept the picture: it is not sent again")
            self.assertEqual((body["model"], body["response_format"]), (first["model"], first["response_format"]))
        # A token handed back unchanged would go round for ever: it stops there, with no video.
        stuck = json.dumps({"id": "v1_x", "status": "requires_continuation", "continuation_token": "same"}).encode()
        self.answers += [(200, stuck), (200, stuck)]
        with self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        self.assertEqual(len(self.sent), 5, "asked to go on once, not again with the same token")
        self.assertEqual(caught.exception.kind, "empty")
        self.assertFalse(caught.exception.free, "Google worked on it: it counts")

    def test_one_video_goes_on_a_few_times_at_most(self):
        # Each time Google is asked to go on it reads everything so far again, and bills it: a new token every time
        # would otherwise be followed until the five minutes are up. It goes on GO_ON_AT_MOST times, then stops.
        self.assertEqual(videogen.GO_ON_AT_MOST, 3)
        self.answers += [(200, json.dumps({"id": f"v1_{n}", "status": "requires_continuation",
                                           "continuation_token": f"t{n}", "steps": []}).encode()) for n in range(10)]
        with self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        first, *going_on = [json.loads(sent["body"]) for sent in self.sent]
        self.assertIn("input", first)
        self.assertEqual([body["continuation_token"] for body in going_on], ["t0", "t1", "t2"],
                         "asked to go on three times after the first request, and no more")
        self.assertEqual(caught.exception.kind, "busy")
        self.assertFalse(caught.exception.free, "Google worked on it: it counts")
        self.assertIn("after going on 3 times", caught.exception.detail)
        # Three times is enough when the video comes then.
        self.sent.clear()
        self.answers[:] = [(200, json.dumps({"id": f"v1_{n}", "status": "requires_continuation",
                                             "continuation_token": f"t{n}", "steps": []}).encode()) for n in range(3)]
        self.answers.append(self.answer(self.video()))
        self.assertEqual(videogen.make(self.service, PICTURE, "Turn."), CLIP)
        self.assertEqual(len(self.sent), 4)

    def test_still_being_made_when_the_time_is_up_counts_and_says_so(self):
        self.waits()
        now = [1000.0]
        patch = mock.patch.object(videogen, "_clock", lambda: now[0])
        patch.start()
        self.addCleanup(patch.stop)
        still = (200, json.dumps({"id": "v1_slow", "status": "in_progress"}).encode())

        def a_minute_passes(url, headers, body, timeout=imagegen.TIMEOUT):
            self.sent.append({"url": url, "timeout": timeout})
            now[0] += 60
            return still
        with mock.patch.object(imagegen, "_send", a_minute_passes), self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        self.assertEqual(caught.exception.kind, "busy")
        self.assertFalse(caught.exception.free, "Google may still be making it, and bill it")
        self.assertIn(f"after {videogen.TIMEOUT} seconds", caught.exception.detail)
        self.assertEqual(len(self.sent), videogen.TIMEOUT // 60, "asked again until the time was up, not after")
        self.assertTrue(all(sent["timeout"] <= videogen.TIMEOUT for sent in self.sent))

    def test_a_problem_after_google_took_the_request_is_never_free(self):
        self.waits()
        taken = (200, json.dumps({"id": "v1_abc", "status": "in_progress"}).encode())
        cases = [((404, json.dumps({"error": {"code": 404, "status": "NOT_FOUND", "message": "no such"}}).encode()), "busy"),
                 ((429, json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "slow"}}).encode()), "busy"),
                 ((200, json.dumps({"id": "v1_abc", "status": "failed", "steps": [{"type": "model_output", "error":
                                    {"code": "safety", "message": "a real person"}}]}).encode()), "refused"),
                 ((200, json.dumps({"id": "v1_abc", "status": "failed", "steps": [{"type": "model_output", "error":
                                    {"code": "invalid_argument", "message": "x"}}]}).encode()), "request")]
        for later, kind in cases:
            self.answers += [taken, later]
            with self.assertRaises(imagegen.DrawError, msg=kind) as caught:
                videogen.make(self.service, PICTURE, "Turn.")
            self.assertEqual(caught.exception.kind, kind, later)
            self.assertFalse(caught.exception.free, f"{kind}: given back although Google worked on it")
        # Not reached on the second question: the same, never free (on the first, nothing was taken: free).
        unreachable = imagegen.DrawError("busy", "could not be reached", free=True)
        with mock.patch.object(imagegen, "_send", side_effect=[taken, unreachable]), \
                self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        self.assertFalse(caught.exception.free)

    def test_a_clip_google_made_but_that_could_not_be_fetched_is_never_free(self):
        # Google's first answer already has the clip, kept on its server: it was made, and billed. Fetching it then
        # fails, even for want of a connection: the day's video is not given back (else each try would be billed
        # again and given back again while Google's server stays out of reach).
        uri = "https://generativelanguage.googleapis.com/v1beta/files/abc:download?alt=media"
        unreachable = imagegen.DrawError("busy", "generativelanguage.googleapis.com could not be reached", free=True)
        with mock.patch.object(imagegen, "_send", side_effect=[self.answer({"type": "video", "uri": uri}), unreachable]), \
                self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        self.assertEqual(caught.exception.kind, "busy")
        self.assertFalse(caught.exception.free, "Google made the video: it is not handed back as free")
        # The same for a problem inside Google's first answer (its request was taken and worked on) …
        failed = (200, json.dumps({"status": "failed", "steps": [{"type": "model_output", "error":
                                                                  {"code": "invalid_argument", "message": "x"}}]}).encode())
        self.answers.append(failed)
        with self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        self.assertEqual(caught.exception.kind, "request")
        self.assertFalse(caught.exception.free, "Google worked on it: it counts")
        # … but not for a request Google turned away at the door, or one that never reached it: those are free.
        self.answers.append((400, json.dumps({"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "x"}}).encode()))
        with self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        self.assertTrue(caught.exception.free, "turned away at the door: nothing was made")
        with mock.patch.object(imagegen, "_send", side_effect=[unreachable]), self.assertRaises(imagegen.DrawError) as caught:
            videogen.make(self.service, PICTURE, "Turn.")
        self.assertTrue(caught.exception.free, "never reached Google: nothing was made")

    def test_it_goes_through_the_pictures_opener(self):
        # The pictures' opener: proxies from the environment only (asking a Mac for its system proxy crashes a
        # web-server worker), and a redirect is never followed with the key (imagegen.py, tested in test_looks.py).
        self.answers.append(self.answer({"type": "video", "data": base64.b64encode(CLIP).decode()}))
        videogen.make(self.service, PICTURE, "Turn.")
        self.assertEqual(len(self.sent), 1, "one request, through imagegen._send")


class Redirects(unittest.TestCase):
    def test_a_redirect_is_not_followed_and_its_address_is_handed_back(self):
        # urllib reports a redirect that the opener does not follow as an error with the new address in its headers.
        headers = Message()
        headers["Location"] = "https://storage.googleapis.com/some-bucket/abc.mp4"
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/files/abc", 302, "Found", headers, None)
        with mock.patch.object(imagegen, "_opener", opener):
            answer = imagegen._send("https://generativelanguage.googleapis.com/v1beta/files/abc",
                                    {"x-goog-api-key": "AIza-test-key-123456"}, None)
        self.assertEqual(answer, (302, b"https://storage.googleapis.com/some-bucket/abc.mp4"))
        self.assertEqual(opener.open.call_count, 1, "once: not followed")
        self.assertEqual(opener.open.call_args[0][0].get_method(), "GET")


class TheOffersWords(unittest.TestCase):
    def test_with_no_videos_left_it_never_asks_for_what_it_cannot_do(self):
        # With none left, the offer ends "No videos left today: more tomorrow" and has only Close: no "Try again" in
        # what went wrong, and no "tick the box" for a box it does not show. With some left, every word stays.
        for kind in ("busy", "empty", "stalled", "unknown"):
            message = videos.SAY[kind]
            self.assertIn("Try again", message, kind)
            self.assertNotIn("Try again", videos.told(message, 0), kind)
            self.assertTrue(videos.told(message, 0).endswith("."), kind)
            for left in (1, 5, None):
                self.assertEqual(videos.told(message, left), message, f"{kind}, {left} left")
        on_this_machine = f"{videos.SAY['busy']} Google had still not finished the video after going on 3 times."
        self.assertEqual(videos.told(on_this_machine, 0), "The AI is busy or did not answer in time. "
                                                          "Google had still not finished the video after going on 3 times.")
        self.assertEqual(videos.told(videos.TICK_FIRST, 0), "", "it says what a video is instead")
        self.assertEqual(videos.told(videos.TICK_FIRST, 1), videos.TICK_FIRST)
        self.assertEqual(videos.told(videos.SAY["person"], 0), videos.SAY["person"], "nothing to leave out")


class VideoSettings(WithVideos, AppCase):
    def setUp(self):
        super().setUp()
        self.switch_on()

    def test_the_real_file_names_the_model_and_the_limits(self):
        rules = looks.load_rules()["videos"]
        self.assertEqual(rules["model"], "gemini-omni-flash-preview")
        self.assertTrue(rules["on"])
        self.assertEqual(rules["turn_seconds"], 6.2)

    def test_a_mistake_in_the_videos_settings_is_named(self):
        for bad, named in ((dict(on="yes"), "videos.on"), (dict(model=""), "videos.model"),
                           (dict(per_day=-1), "videos.per_day"), (dict(turn_seconds=20), "videos.turn_seconds"),
                           (dict(pro_per_customer_per_day=2.5), "videos.pro_per_customer_per_day"),
                           (dict(seconds=2), "videos.seconds"), (dict(seconds=16), "videos.seconds"),
                           (dict(seconds=5.5), "videos.seconds"), (dict(task=1), "videos.task"),
                           (dict(start=""), "videos.start"), (dict(keep=None), "videos.keep"),
                           (dict(motion="turn"), "[videos.motion]"),
                           (dict(motion={"other": "Moves."}), "videos.motion.front"),
                           (dict(motion={"front": "Turns."}), "videos.motion.other"),
                           (dict(motion={"front": "Turns.", "other": "Moves.", "cafe": ""}), "videos.motion.cafe")):
            data = {"videos": {**looks.load_rules()["videos"], **bad}}
            with self.assertRaises(config.ConfigError, msg=named) as caught:
                looks._check_videos(data["videos"])
            self.assertIn(named, str(caught.exception))
        looks._check_videos({**looks.load_rules()["videos"], "task": ""})      # "": left out of the request, allowed

    def test_the_real_file_has_a_movement_for_every_picture_and_five_second_clips(self):
        rules = looks.load_rules()["videos"]
        self.assertEqual(rules["seconds"], 5)
        self.assertEqual(rules["task"], "image_to_video")
        for name, _ in looks.shots():
            self.assertIn(name, rules["motion"], f"the {name} picture has no movement of its own")
        self.assertIn("other", rules["motion"])
        self.assertEqual(len({rules["motion"][name] for name, _ in looks.shots()}), len(looks.shots()),
                         "two pictures share a movement")

    def test_a_different_model_or_words_is_a_different_video(self):
        outfit = some_outfits(1)[0]
        self.post("/outfits/look", key=outfit.key)
        look = looks.get(look_key(outfit))
        self.post("/outfits/video", look=look.key, outfit=outfit.key)
        motion = looks.load_rules()["videos"]["motion"]
        self.with_video_rules(motion={**motion, "front": "Walk towards the camera."})
        self.post("/outfits/video", look=look.key, outfit=outfit.key)
        self.assertEqual(len(self.made), 2)
        self.assertIn(" Walk towards the camera. ", self.made[1]["prompt"])
        self.assertNotIn("turns slowly", self.made[1]["prompt"])


class Schema(unittest.TestCase):
    def test_a_database_at_version_6_gains_the_video_tables_and_nothing_else_changes(self):
        for path in (paths.DB_PATH,):
            path.unlink(missing_ok=True)
        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            for table in ("videos", "video_requests", "pro"):
                con.execute(f"DROP TABLE {table}")
            for index in ("videos_picture", "video_requests_at"):
                con.execute(f"DROP INDEX IF EXISTS {index}")
            con.execute("INSERT INTO users (id, email, password_hash, created_at) VALUES (5, 'x@example.com', 'h', 'x')")
            con.execute("PRAGMA user_version = 6")
            con.commit()
            before = set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            after = set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
            self.assertEqual(before - after, set())
            self.assertEqual(sorted((kind, name) for kind, name, _, _ in after - before),
                             [("index", "sqlite_autoindex_videos_1"), ("index", "video_requests_at"),
                              ("index", "videos_picture"), ("table", "pro"), ("table", "video_requests"),
                              ("table", "videos")])
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM pro").fetchone()[0], 0, "nobody is Pro by itself")
        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master")), after)
        paths.DB_PATH.unlink(missing_ok=True)
