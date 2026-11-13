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

        def stand_in(service, picture, prompt):
            self.made.append({"service": service, "picture": picture, "prompt": prompt})
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
        self.assertIn("An 8-second AI video: the model turns round once, then poses.", said(offer))
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
        self.assertEqual(sent["prompt"], looks.load_rules()["videos"]["text"])
        self.assertEqual(sent["service"].model, "gemini-omni-flash-preview")
        self.assertIn("turns slowly on the spot through one full circle", sent["prompt"])
        self.assertIn("data-play", shown, "it plays once it is there")
        self.assertIn('<span class="ai-chip">AI video</span>', shown)

        street = self.post("/outfits/look", key=outfit.key, scene="street").data.decode()   # another scene
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
            self.post("/outfits/look", key=outfit.key, again="1")
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
        self.assertEqual(json.loads(ada.get("/account/export").data)["settings"]["photo_consent"], videos.CONSENT)
        bob = self.member("bob@example.com")
        with mock.patch.object(videos, "service", lambda: None):        # videos off: the words say nothing of them
            self.assertNotIn("videos", said(bob.get("/profile").data.decode()))
            self.upload(bob)
        self.assertEqual(json.loads(bob.get("/account/export").data)["settings"]["photo_consent"], "2026-11-12")
        self.assertEqual(videos.CONSENT, "2026-11-13")

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
        self.assertEqual((kept["photo_consent"], kept["video_consent"]["words"]), ("2026-11-12", videos.CONSENT),
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
                           (dict(pro_per_customer_per_day=2.5), "videos.pro_per_customer_per_day")):
            data = {"videos": {**looks.load_rules()["videos"], **bad}}
            with self.assertRaises(config.ConfigError, msg=named) as caught:
                looks._check_videos(data["videos"])
            self.assertIn(named, str(caught.exception))

    def test_a_different_model_or_words_is_a_different_video(self):
        outfit = some_outfits(1)[0]
        self.post("/outfits/look", key=outfit.key)
        look = looks.get(look_key(outfit))
        self.post("/outfits/video", look=look.key, outfit=outfit.key)
        self.with_video_rules(text="Walk towards the camera.")
        self.post("/outfits/video", look=look.key, outfit=outfit.key)
        self.assertEqual([sent["prompt"] for sent in self.made][1], "Walk towards the camera.")
        self.assertEqual(len(self.made), 2)


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
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM pro").fetchone()[0], 0, "nobody is Pro by itself")
        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master")), after)
        paths.DB_PATH.unlink(missing_ok=True)
