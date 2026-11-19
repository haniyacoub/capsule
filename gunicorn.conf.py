"""Settings gunicorn reads by itself when it is started from this folder.

How many workers and where to listen is said on the command line (PRODUCTION.md, the
Dockerfile). This file says what a line of the access log holds (3., below), and adds two
protections, both learned on 2026-11-11, when a reload left the service starting and
losing 3,485 workers in five minutes.

1. No control socket. gunicorn can listen on a socket for its `gunicornc` tool, which
   this service does not use. Listening takes a second thread in the main process, and
   on macOS a process that has ever had a second thread may not start workers that then
   call into the system's own frameworks: such a worker is killed on the spot. Without
   the socket the main process stays single-threaded, and it leaves no socket file in
   the home folder for another gunicorn to trip over.

2. Stop instead of trying for ever. gunicorn starts a new worker for each one that
   dies. When workers die as soon as they start, that is a loop of several a second
   with no end. Here the service stops after a handful and says why.

3. The access log (written where the Dockerfile asks for it, --access-logfile -) holds no
   visitor's address and no name. gunicorn's own line starts with the address the request
   came from, which behind the Cloudflare tunnel is the visitor's real one (the app's
   ProxyFix puts it there, app.py, TRUSTED_PROXY_HOPS), and has the user name typed into
   the browser's password box (SITE_PASSWORD) in it. This line has neither, and leaves out
   the address's ?… part and the page the visitor came from (both can carry an invitation
   code). What is left is enough to see what was asked and how it went:

       [19/Nov/2026:10:15:02 +0000] "GET /outfits" 200 48213 87ms "Mozilla/5.0 (iPhone; …)"

   the time, the request (method and path), the answer's status and size in bytes, how
   long it took, and the browser's own name for itself (user agent). PRODUCTION.md, "Logs",
   says what else is logged and how long it is kept.
"""
import time

control_socket_disable = True

# Time, "method path" (without ?…), status, bytes, milliseconds, "user agent": no %(h)s (the address), no %(u)s (the
# name from the password box), no %(r)s or %(q)s (the address with its ?…), no %(f)s (the page before). See 3. above.
access_log_format = '%(t)s "%(m)s %(U)s" %(s)s %(b)s %(M)sms "%(a)s"'

YOUNG = 10      # seconds. A worker that dies sooner than this never got going.
WITHIN = 30     # seconds. Young deaths are counted over this stretch of time.

_young_deaths: list[float] = []
_state = {"reloaded_at": 0.0, "stopped": False}


def too_many(workers: int) -> int:
    """This many young deaths within WITHIN seconds stop the service: more than two rounds of workers."""
    return 2 * max(1, workers) + 1


def when_ready(server):
    server.log.info("Guard on: the service stops if %s workers die within seconds of starting.",
                    too_many(server.num_workers))


def pre_fork(server, worker):
    """In the main process, just before a worker is started: note when."""
    worker.capsule_born = time.monotonic()


def on_reload(server):
    """A reload (kill -HUP) retires every worker, however young. Those are not counted."""
    _state["reloaded_at"] = time.monotonic()
    server.log.info("Reloading. Guard on: the service stops if %s workers die within seconds of starting.",
                    too_many(server.num_workers))


def child_exit(server, worker):
    """In the main process, after a worker has gone: stop the service if they keep dying young."""
    reason = reason_to_stop(server, worker)
    if reason:
        from gunicorn.errors import HaltServer
        raise HaltServer(reason, getattr(server, "WORKER_BOOT_ERROR", 3))


def reason_to_stop(server, worker) -> str | None:
    """Why the service should stop now, or None. Counts this worker's death if it died young."""
    try:
        now = time.monotonic()
        born = getattr(worker, "capsule_born", None)
        if (_state["stopped"] or born is None or born < _state["reloaded_at"]
                or not getattr(server, "LISTENERS", True)       # the service is shutting down
                or now - born >= YOUNG):
            return None
        _young_deaths[:] = [at for at in _young_deaths if now - at < WITHIN] + [now]
        if len(_young_deaths) < too_many(getattr(server, "num_workers", 1)):
            return None
        _state["stopped"] = True
        return (f"{len(_young_deaths)} workers died within seconds of starting, so the service stopped "
                "instead of starting more. The lines above say how each one ended. Find what makes a "
                "worker die as it starts, then start the service again.")
    except Exception:  # noqa: BLE001 - the guard must never be what brings the service down
        server.log.exception("The guard against dying workers failed itself. Carrying on without it.")
        return None
