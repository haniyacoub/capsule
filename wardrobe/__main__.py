"""Command line:

    python -m wardrobe                        start the app on this computer only
    python -m wardrobe serve --lan            also reachable from your phone on the home network
    python -m wardrobe refresh                collect store data by hand, for this computer only (see collect/)
    python -m wardrobe refresh --store zara --slot white-tee     only part of it
    python -m wardrobe mock                   go back to the invented demo catalogue
    python -m wardrobe publish ./data-production   give your own or an invite-only service the collected products
    python -m wardrobe looks                  are the AI pictures of outfits switched on?
    python -m wardrobe looks --test           draw one sample picture, to check the key (costs one picture)
    python -m wardrobe stores [sync | end KEY]    the stores whose feeds Capsule may use (config/feeds.toml)
    python -m wardrobe feeds [--store KEY] [--from FILE]   import the approved stores' product feeds (feeds/)
    python -m wardrobe owner [add EMAIL | remove EMAIL]    who sees the owner's pages, such as /stores (owner.py)
"""
from __future__ import annotations

import argparse
import logging
import socket
import socketserver
import sys


def _free_port(host: str, wanted: int) -> int:
    """`wanted` if it is free, otherwise the next free port after it."""
    for port in range(wanted, wanted + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    sys.exit(f"No free port between {wanted} and {wanted + 19} — pass another with --port.")


def _lan_address() -> str | None:
    """This computer's address on the local network (no data is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def _make_server(host: str, port: int, app):
    """Flask's built-in web server — plenty for one person on one machine."""
    from werkzeug.serving import ThreadedWSGIServer

    class Server(ThreadedWSGIServer):
        def server_bind(self) -> None:
            # The stock version also looks up this computer's network name here,
            # which can stall for half a minute on a Mac. Nothing needs the name.
            socketserver.TCPServer.server_bind(self)
            name, number = self.server_address[:2]
            self.server_name, self.server_port = str(name), int(number)

    return Server(host, port, app)


def serve(args: argparse.Namespace) -> None:
    from . import settings
    from .app import create_app

    if settings.PRODUCTION:
        sys.exit("In production, run the app with a real web server:\n"
                 "  gunicorn --workers 2 --threads 4 --bind 0.0.0.0:8000 wardrobe.wsgi:app")

    # Every network interface only with --lan, which says what that means; otherwise this computer alone.
    host = "0.0.0.0" if args.lan else "127.0.0.1"   # nosec
    app = create_app()
    port = _free_port(host, args.port)
    server = _make_server(host, port, app)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)   # no line per request, only errors

    if port != args.port:
        print(f"\n  Port {args.port} is busy, using {port} instead.")
    print(f"\n  Capsule is running:  http://127.0.0.1:{port}")
    try:
        from . import looks
        print(f"  AI pictures:         {looks.status()[1]}")
    except Exception:       # a typo in config/looks.toml: the page will say so
        pass
    if args.lan:
        address = _lan_address()
        if address:
            print(f"  On your phone:       http://{address}:{port}   (same Wi-Fi)")
        print("  Anyone on this network can open it while it runs — there is no login.")
    print("  Stop with Ctrl+C.\n", flush=True)

    try:
        server.serve_forever()   # returns when you press Ctrl+C
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("\n  Stopped.")


# What `python -m wardrobe refresh --help` says above its options.
COLLECTOR_IS_PRIVATE = (
    "Reads COS, Weekday and Zara category pages (and Zara's product pages for fabric and sizes) in a visible "
    "Chrome window and keeps what it finds on this computer. For your own machine and for testing only: run "
    "it by hand, never on a schedule (no cron job, timer or start-up call), and never use what it collects as "
    "the source for the public site. The public site is to use the stores' licensed product feeds "
    "(PRODUCTION.md, \"Before customers\"). It refuses to run in production mode."
)


def _local_only(what: str) -> None:
    from . import settings
    if settings.PRODUCTION:
        sys.exit(f"{what} is for your own machine only and is switched off in production mode.")


def refresh(args: argparse.Namespace) -> None:
    _local_only("The collector")
    from . import db
    from .app import bootstrap
    from .collect import STORE_ORDER, load_settings
    from .collect import refresh as collect

    bootstrap()   # in case the app has never been started: profile, slots
    slots = {s["id"]: s for s in db.list_slots()}
    unknown = [s for s in args.slot if s not in slots]
    if unknown:
        sys.exit(f"No slot called {', '.join(unknown)}. Slot ids: {', '.join(slots)}")
    settings = load_settings()
    names = [settings[k].get("label", k) for k in STORE_ORDER if not args.store or k in args.store]
    wanted = len(args.slot) or sum(1 for s in slots.values() if not s["owned"])
    print(f"Collecting {wanted} slot{'s' if wanted != 1 else ''} from {', '.join(names)}.\n"
          "A Chrome window opens and reads the stores' category pages (and Zara's product pages)\n"
          "one at a time, with a few seconds between pages, so this is slow on purpose — a full\n"
          "run takes 20 to 30 minutes.\n"
          "Leave that window alone; you can keep using the computer. Ctrl+C stops and keeps\n"
          "what has been collected so far.")
    try:
        results = collect(store_keys=args.store or None, slot_ids=args.slot or None, max_candidates=args.max)
    except KeyboardInterrupt:
        sys.exit("\nStopped. What was collected up to here has been saved.")
    except RuntimeError as problem:
        sys.exit(f"\n{problem}")

    print("\nDone.")
    for key, status in results.items():
        label = settings[key].get("label", key)
        line = f"  {label:<8} {status['candidates']} candidates for {status['slots_filled']} slots ({status['pages']} pages read)"
        print(line + (f"\n           {status['message']}" if status["message"] else ""))
    print("Reload the app to see them.")


def publish(args: argparse.Namespace) -> None:
    _local_only("Publishing")
    from pathlib import Path

    from . import catalog, db, shared

    db.init()
    if catalog.load().get("source") != "collected":
        sys.exit("There is no collected store data to publish yet. Run:  python -m wardrobe refresh")
    count = shared.publish(Path(args.folder))
    print(f"Published {count} products to {Path(args.folder) / shared.POOL_NAME}.\n"
          "A service running on that folder shows them to its customers from their next page load.\n"
          "Showing them to the public needs the stores' permission; on your own machine it is yours to try.")


def check_looks(args: argparse.Namespace) -> None:
    """Say whether the AI pictures are on and, with --test, prove it by drawing one."""
    from . import imagegen, looks

    on, line = looks.status()
    print(f"AI pictures of outfits: {line}")
    if not on:
        sys.exit('\nGet a key from platform.openai.com or aistudio.google.com, then in this terminal:\n'
                 '  export OPENAI_API_KEY="sk-…"      (or GEMINI_API_KEY="…")\n'
                 "and start the app from the same terminal. To keep the key for every new terminal,\n"
                 "add that line to the file ~/.zshrc.")
    if not args.test:
        print("To check the key by drawing one sample picture (the service bills it, a few cents):\n"
              "  python -m wardrobe looks --test")
        return
    print("Drawing a sample outfit. This takes up to a minute and is billed to your key…", flush=True)
    try:
        path, seconds = looks.sample()
    except imagegen.DrawError as problem:
        sys.exit(f"\nIt did not work: {looks.SAY.get(problem.kind, looks.SAY['unknown'])}\n  {problem.detail}")
    print(f"It works: {path} ({seconds:.0f} seconds). Open that file to look at it.")


def rebuild_mock(args: argparse.Namespace) -> None:
    _local_only("Rebuilding the demo catalogue")
    from . import catalog, db, mock

    db.init()
    current = catalog.load()
    if current.get("source") == "collected" and not args.yes:
        sys.exit("The catalogue holds real store data. To throw it away and go back to the\n"
                 "invented demo data, run:  python -m wardrobe mock --yes")
    data = mock.build(db.list_slots())
    data["candidates"] += [c for c in current.get("candidates", []) if c.get("source") == "manual"]
    catalog.save(data)
    print(f"Demo catalogue rebuilt: {len(data['candidates'])} invented candidates "
          f"for {len(db.list_slots())} slots.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m wardrobe", description="Capsule wardrobe builder")
    parser.set_defaults(func=serve, lan=False, port=8000)
    sub = parser.add_subparsers(title="commands")

    p_serve = sub.add_parser("serve", help="start the app (the default)")
    p_serve.add_argument("--lan", action="store_true", help="reachable from other devices on your network")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=serve)

    p_refresh = sub.add_parser("refresh", help="collect store data by hand, for this computer only (never scheduled)",
                               description=COLLECTOR_IS_PRIVATE)
    p_refresh.add_argument("--store", action="append", default=[], choices=["cos", "weekday", "zara"],
                           help="only this store (repeatable)")
    p_refresh.add_argument("--slot", action="append", default=[], metavar="SLOT_ID",
                           help="only this slot, e.g. white-tee (repeatable)")
    p_refresh.add_argument("--max", type=int, default=None, metavar="N",
                           help="candidates per slot per store (default: config/stores.toml)")
    p_refresh.set_defaults(func=refresh)

    p_publish = sub.add_parser("publish", help="copy the collected products into your own or an invite-only "
                                               "service's data folder (never a public site's)")
    p_publish.add_argument("folder", help="that service's WARDROBE_DATA_DIR, e.g. ./data-production")
    p_publish.set_defaults(func=publish)

    p_looks = sub.add_parser("looks", help="check the AI pictures of outfits and the key they need")
    p_looks.add_argument("--test", action="store_true", help="draw one sample picture (billed by the service)")
    p_looks.set_defaults(func=check_looks)

    p_mock = sub.add_parser("mock", help="go back to the invented demo catalogue")
    p_mock.add_argument("--yes", action="store_true", help="discard collected store data without asking")
    p_mock.set_defaults(func=rebuild_mock)

    from .feeds import commands as feed_commands      # stores, feeds: the licensed store feeds
    feed_commands.add(sub)
    from .owner import add_commands as owner_commands  # owner: the accounts that see the owner's pages
    owner_commands(sub)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
