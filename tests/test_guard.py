"""gunicorn.conf.py: the service stops when its workers keep dying as they start, instead of
starting new ones for ever, and it runs without gunicorn's control socket.

The first half tests the counting with a made-up clock. The second half starts a real
gunicorn; workers that are meant to die are killed with SIGKILL, which no operating system
treats as a crash (on a Mac a real crash of Python puts a dialog on the screen each time).
"""
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from wardrobe import paths

SETTINGS = paths.ROOT / "gunicorn.conf.py"
HAS_GUNICORN = importlib.util.find_spec("gunicorn") is not None
needs_gunicorn = unittest.skipUnless(HAS_GUNICORN, "gunicorn is not installed (pip install -r requirements-dev.txt)")


def load():
    """The settings file as gunicorn would read it: afresh, with nothing counted yet."""
    spec = importlib.util.spec_from_file_location("capsule_gunicorn_settings", SETTINGS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Counting(unittest.TestCase):
    def setUp(self):
        self.guard = load()
        self.now = 1000.0
        self.guard.time = types.SimpleNamespace(monotonic=lambda: self.now)     # the guard's clock
        self.server = types.SimpleNamespace(num_workers=2, LISTENERS=[object()], WORKER_BOOT_ERROR=3, log=mock.Mock())

    def worker(self):
        """A worker started now."""
        worker = types.SimpleNamespace()
        self.guard.pre_fork(self.server, worker)
        return worker

    def dies(self, worker=None, after=0.1):
        """A worker dies `after` seconds after it was started. Returns the guard's verdict."""
        worker = worker or self.worker()
        self.now += after
        return self.guard.reason_to_stop(self.server, worker)

    def test_workers_that_die_as_they_start_stop_the_service(self):
        verdicts = [self.dies() for _ in range(5)]
        self.assertEqual(verdicts[:4], [None] * 4, "two rounds of two workers are given the benefit of the doubt")
        self.assertIn("5 workers died within seconds of starting", verdicts[4])

    def test_it_says_so_once(self):
        for _ in range(5):
            self.dies()
        self.assertIsNone(self.dies(), "the workers stopped while shutting down are not a second alarm")

    @needs_gunicorn
    def test_gunicorn_is_told_to_halt_as_it_does_for_a_worker_that_cannot_boot(self):
        from gunicorn.errors import HaltServer  # type: ignore[import-untyped]
        for _ in range(4):
            self.now += 0.1
            self.guard.child_exit(self.server, self.worker())
        self.now += 0.1
        with self.assertRaises(HaltServer) as halt:
            self.guard.child_exit(self.server, self.worker())
        self.assertEqual(halt.exception.exit_status, 3)
        self.assertIn("died within seconds of starting", halt.exception.reason)

    def test_a_worker_that_ran_for_a_while_is_not_counted(self):
        for _ in range(20):
            self.assertIsNone(self.dies(after=self.guard.YOUNG + 1))

    def test_deaths_far_apart_never_add_up(self):
        for _ in range(20):
            self.assertIsNone(self.dies())
            self.now += self.guard.WITHIN          # a worker that dies young now and then is not a loop

    def test_a_reload_retires_young_workers_without_alarm(self):
        for _ in range(6):                          # six reloads in a row, each seconds after the last
            retiring = [self.worker(), self.worker()]
            self.now += 1
            self.guard.on_reload(self.server)
            self.now += 0.1
            for worker in retiring:
                self.assertIsNone(self.dies(worker, after=0))

    def test_a_reload_does_not_excuse_the_workers_it_starts(self):
        self.guard.on_reload(self.server)
        self.now += 0.1
        verdicts = [self.dies() for _ in range(5)]
        self.assertIsNotNone(verdicts[4], "this is the case it exists for: a reload brings in code that kills its workers")

    def test_stopping_the_service_is_not_an_alarm(self):
        self.server.LISTENERS = []                  # gunicorn closes these first when it stops
        for _ in range(10):
            self.assertIsNone(self.dies())

    def test_workers_from_before_the_settings_file_was_read_are_left_alone(self):
        for _ in range(10):                         # started before a reload first loaded this file: no start time noted
            self.now += 0.1
            self.assertIsNone(self.guard.reason_to_stop(self.server, types.SimpleNamespace()))

    def test_more_workers_more_patience(self):
        self.assertEqual([self.guard.too_many(n) for n in (1, 2, 4)], [3, 5, 9])
        self.server.num_workers = 4
        verdicts = [self.dies() for _ in range(9)]
        self.assertEqual(verdicts[:8], [None] * 8)
        self.assertIsNotNone(verdicts[8])

    def test_the_guard_cannot_be_what_brings_the_service_down(self):
        broken = types.SimpleNamespace(capsule_born="yesterday")        # anything it does not expect
        self.assertIsNone(self.guard.reason_to_stop(self.server, broken))
        self.server.log.exception.assert_called_once()
        self.guard.child_exit(self.server, broken)                        # … and gunicorn's hook does not raise either

    def test_no_control_socket(self):
        # Serving it takes a thread in gunicorn's main process. On macOS, workers started by a process
        # that has ever had a second thread are killed when they call into the system's frameworks.
        self.assertIs(self.guard.control_socket_disable, True)


DYING = """
import os, signal
os.kill(os.getpid(), signal.SIGKILL)        # every worker, as it loads the app

def app(environ, start_response):
    start_response("200 OK", [])
    return [b""]
"""

HEALTHY = """
def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"ok"]
"""


@needs_gunicorn
class WithARealGunicorn(unittest.TestCase):
    def start(self, folder: Path, app: str, *more: str) -> subprocess.Popen:
        (folder / "theapp.py").write_text(app)
        return subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "--config", str(SETTINGS), "--workers", "2", "--bind", "127.0.0.1:0",
             "--error-logfile", str(folder / "log.txt"), *more, "theapp:app"],
            cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_for(self, folder: Path, text: str, times: int = 1, seconds: float = 20) -> str:
        deadline = time.monotonic() + seconds
        log = ""
        while time.monotonic() < deadline:
            log = (folder / "log.txt").read_text() if (folder / "log.txt").exists() else ""
            if log.count(text) >= times:
                return log
            time.sleep(0.05)
        self.fail(f"{text!r} did not appear {times} time(s) in gunicorn's log within {seconds} s:\n{log[-1500:]}")

    def test_workers_dying_as_they_start_stop_it_within_seconds(self):
        with tempfile.TemporaryDirectory() as where:
            server = self.start(Path(where), DYING)
            try:
                status = server.wait(timeout=30)        # without the guard this never returns
            finally:
                if server.poll() is None:
                    server.kill()
            log = (Path(where) / "log.txt").read_text()
        self.assertEqual(status, 3, log[-1500:])
        self.assertIn("5 workers died within seconds of starting", log)
        self.assertLessEqual(log.count("Booting worker"), 8, "it kept starting workers")

    def test_a_healthy_service_starts_reloads_and_stops_as_before(self):
        with tempfile.TemporaryDirectory() as where:
            folder = Path(where)
            server = self.start(folder, HEALTHY)
            try:
                self.wait_for(folder, "Guard on")
                self.wait_for(folder, "Booting worker", times=2)
                for reload in (1, 2, 3):                # three reloads on each other's heels
                    os.kill(server.pid, signal.SIGHUP)
                    self.wait_for(folder, "Reloading. Guard on", times=reload)
                    self.wait_for(folder, "Booting worker", times=2 + 2 * reload)
                self.assertIsNone(server.poll(), "it stopped during the reloads")
                server.send_signal(signal.SIGTERM)
                status = server.wait(timeout=30)
            finally:
                if server.poll() is None:
                    server.kill()
            log = (folder / "log.txt").read_text()
        self.assertEqual(status, 0, log[-1500:])
        self.assertNotIn("Reason:", log)
        for trace in ("Control socket listening", "Control server error"):
            self.assertNotIn(trace, log, "gunicorn's control socket was started")


if __name__ == "__main__":
    unittest.main()
