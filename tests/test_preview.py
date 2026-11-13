"""deploy/preview.sh: the service on the internet through a temporary Cloudflare tunnel, by invitation.

A test must not open a real tunnel: that would put the machine it runs on onto the internet.
So a stand-in for `cloudflared` says what the real one says and then waits; the script, gunicorn
and the app are the real ones.
"""
import importlib.util
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from wardrobe import paths

SCRIPT = paths.ROOT / "deploy" / "preview.sh"
ADDRESS = "https://made-up-words-for-a-test.trycloudflare.com"
RUNNABLE = os.name == "posix" and importlib.util.find_spec("gunicorn") is not None

STAND_IN = f"""#!/bin/sh
echo "2026-11-11T22:00:00Z INF Requesting new quick Tunnel on trycloudflare.com..." >&2
echo "2026-11-11T22:00:01Z INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |" >&2
echo "2026-11-11T22:00:01Z INF |  {ADDRESS}                                       |" >&2
exec sleep 300
"""
GIVES_UP = """#!/bin/sh
echo "2026-11-11T22:00:00Z ERR failed to request quick Tunnel: no route to host (https://api.trycloudflare.com/tunnel)" >&2
exit 1
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@unittest.skipUnless(RUNNABLE, "needs a Unix shell and gunicorn (pip install -r requirements-dev.txt)")
class Preview(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.folder / "bin").mkdir()
        self.port = free_port()
        self.settings = {
            "PATH": os.pathsep.join([str(self.folder / "bin"), os.path.dirname(sys.executable), "/usr/bin", "/bin"]),
            "HOME": str(self.folder), "TMPDIR": str(self.folder), "PORT": str(self.port),
            "CAPSULE_ENV": "production", "SECRET_KEY": secrets.token_urlsafe(48),
            "WARDROBE_DATA_DIR": str(self.folder / "data"),
        }

    def cloudflared(self, script: str) -> None:
        stand_in = self.folder / "bin" / "cloudflared"
        stand_in.write_text(script)
        stand_in.chmod(0o755)

    def run_it(self, **changes) -> subprocess.CompletedProcess:
        """Run the script to its end (the cases in which it stops by itself)."""
        settings = {name: value for name, value in {**self.settings, **changes}.items() if value is not None}
        return subprocess.run(["sh", str(SCRIPT)], env=settings, capture_output=True, text=True, timeout=60)

    def get(self, path: str, **headers):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as answer:
            return answer.headers, answer.read().decode()

    def test_it_starts_the_service_for_the_address_by_invitation_and_stops_both(self):
        self.cloudflared(STAND_IN)
        said = self.folder / "said.txt"
        with said.open("w") as out:
            running = subprocess.Popen(["sh", str(SCRIPT)], env=self.settings, stdout=out, stderr=subprocess.STDOUT,
                                       start_new_session=True)       # its own group, as in a Terminal window
        try:
            deadline = time.monotonic() + 40
            while True:
                try:
                    self.get("/healthz")
                    break
                except OSError:
                    if running.poll() is not None or time.monotonic() > deadline:
                        self.fail("the service did not come up:\n" + said.read_text()[-2000:])
                    time.sleep(0.2)
            text = said.read_text()
            self.assertIn(ADDRESS, text)
            self.assertIn("Stilsmith is on the internet for as long as this window stays open", text)
            invitation = re.search(re.escape(ADDRESS) + r"/signup\?code=([\w-]{8,})", text)
            self.assertIsNotNone(invitation, text)
            code = invitation.group(1)

            headers, page = self.get(f"/signup?code={code}")
            self.assertIn(f'value="{code}"', page, "the service does not ask for the code the script printed")
            self.assertIn("by invitation", self.get("/")[1])
            self.assertIn("Secure", headers.get("Set-Cookie", ""), "the address is https: the login cookie must say so")
            through_the_tunnel, _ = self.get("/login", **{"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"})
            self.assertIn("max-age", through_the_tunnel.get("Strict-Transport-Security", ""),
                          "what the tunnel says about https is not believed")
        finally:
            if running.poll() is None:
                os.killpg(running.pid, signal.SIGINT)                 # Ctrl+C in that window
            try:
                running.wait(timeout=45)
            except subprocess.TimeoutExpired:
                os.killpg(running.pid, signal.SIGKILL)
                self.fail("Ctrl+C did not stop it")
        for _ in range(50):                                           # … and the tunnel went with it
            try:
                os.killpg(running.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.killpg(running.pid, signal.SIGKILL)
            self.fail("something it started is still running after Ctrl+C")
        self.assertEqual(list(self.folder.glob("capsule-tunnel.*")), [], "the tunnel's log was left behind")

    def test_without_cloudflared_it_says_how_to_get_it(self):
        ran = self.run_it(PATH="/usr/bin:/bin")
        self.assertEqual(ran.returncode, 1)
        self.assertIn("brew install cloudflared", ran.stderr)

    def test_without_the_services_settings_it_says_where_to_run_it(self):
        self.cloudflared(STAND_IN)
        for missing in ("CAPSULE_ENV", "SECRET_KEY", "WARDROBE_DATA_DIR"):
            ran = self.run_it(**{missing: None})
            self.assertEqual(ran.returncode, 1, missing)
            self.assertIn("the Terminal window the service was started in", ran.stderr)

    def test_it_will_not_start_beside_a_service_that_is_still_running(self):
        self.cloudflared(STAND_IN)
        with socket.socket() as taken:
            taken.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            taken.bind(("127.0.0.1", self.port))
            taken.listen()
            ran = self.run_it()
        self.assertEqual(ran.returncode, 1)
        self.assertIn(f"already answering on port {self.port}", ran.stderr)

    def test_when_cloudflare_gives_no_address_nothing_is_started(self):
        self.cloudflared(GIVES_UP)
        ran = self.run_it()
        self.assertEqual(ran.returncode, 1)
        self.assertIn("did not give an address", ran.stderr)
        self.assertIn("no route to host", ran.stderr, "cloudflared's own words are not passed on")
        self.assertNotIn("Booting worker", ran.stdout + ran.stderr)


if __name__ == "__main__":
    unittest.main()
