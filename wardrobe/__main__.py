"""Command line:

    python -m wardrobe                        start the app on this computer only
    python -m wardrobe serve --lan            also reachable from your phone on the home network
    python -m wardrobe refresh                collect store data by hand, for this computer only (see collect/)
    python -m wardrobe refresh --store cos --slot white-tee      only part of it
    python -m wardrobe mock                   go back to the invented demo catalogue
    python -m wardrobe publish ./data-production   give your own or an invite-only service the collected products
    python -m wardrobe looks                  are the AI pictures of outfits switched on?
    python -m wardrobe looks --test           draw one sample picture, to check the key (costs one picture)
    python -m wardrobe looks --test-set       draw a sample outfit's whole set: the front picture and the five made from it
    python -m wardrobe looks --test-video     make one "See it move" video from that set (--video-model NAME tries another model)
    python -m wardrobe example-pictures       what drawing the example wardrobe's pictures (what visitors see) would cost
    python -m wardrobe example-pictures --yes ... and draw them (billed; --sample 3: only three; --max-cost 1.00)
    python -m wardrobe chat                   is the style chat switched on?
    python -m wardrobe chat --test "WORDS"    send one message to Google's text model (costs about a tenth of a cent)
    python -m wardrobe stores [sync | end KEY]    the stores whose feeds Stilsmith may use (config/feeds.toml)
    python -m wardrobe feeds [--store KEY] [--from FILE]   import the approved stores' product feeds (feeds/)
    python -m wardrobe owner [add EMAIL | remove EMAIL]    who sees the owner's pages, such as /stores (owner.py)
    python -m wardrobe pro [add EMAIL | remove EMAIL]      Pro accounts: more AI videos a day (videos.py)
"""
from __future__ import annotations

import argparse
import logging
import socket
import socketserver
import sys
import time
from decimal import ROUND_UP, Decimal, InvalidOperation


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
    print(f"\n  {settings.SITE_NAME} is running:  http://127.0.0.1:{port}")
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
    "Reads COS and Weekday category pages in a visible Chrome window (never their product pages) and keeps "
    "what it finds on this computer. For your own machine and for testing only: run "
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
          "A Chrome window opens and reads the stores' category pages one at a time,\n"
          "with a few seconds between pages, so this is slow on purpose — a full\n"
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


def check_chat(args: argparse.Namespace) -> None:
    """Say whether the style chat is on and, with --test, send one message and print what came back."""
    from . import imagegen, settings, style, stylechat

    print(f"Style chat: {stylechat.status()}")
    if args.test is None:
        return
    if not stylechat.available():
        sys.exit("\nNothing was sent.")
    model = style.load_rules()["chat"]["model"]
    turns = [{"who": stylechat.ME, "text": args.test}]
    print(f"Sending to Google ({model}):\n{stylechat.sent_text(turns, style.EMPTY)}\n")
    try:
        reply, question, brief = stylechat.read(stylechat.ask(model, settings.GEMINI_API_KEY, turns, style.EMPTY))
    except imagegen.DrawError as problem:
        sys.exit(f"It did not work ({problem.kind}): {problem.detail}")
    print(f"Reply:    {reply}\nQuestion: {question or '(none)'}\nBrief, after checking:")
    for what, value in style.in_words(brief):
        print(f"  {what}: {value}")


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
    if args.test_video is not None:
        # One clip of "See it move", from a sample picture: to look at with your own eyes, and to try another
        # name for the video model (--video-model) without touching config/looks.toml.
        from . import videos
        try:
            clip = videos.clip_of(args.test_video)
            name = args.video_model or (videos.rules() or {}).get("model", "")
            print(f"Making a {clip.seconds}-second video from the sample outfit's {clip.label} picture with {name}.\n"
                  "This takes up to two minutes and is billed to your key…", flush=True)
            path, seconds, clip = videos.sample(args.test_video, args.video_model)
        except imagegen.DrawError as problem:
            if problem.kind == "picture":
                sys.exit(f"\nNothing was sent: {problem.detail}.\nDraw the sample pictures first (six pictures billed):\n"
                         "  python -m wardrobe looks --test-set")
            sys.exit(f"\nIt did not work: {videos.SAY.get(problem.kind, videos.SAY['unknown'])}\n  {problem.detail}")
        print(f"It works: {path} ({seconds:.0f} seconds). Open that file to look at it.")
        return
    if args.test_set:
        # The whole set of one made-up outfit, to judge with your own eyes: is it the same man in the same clothes
        # in every picture, and do the street, the café and the library look photographed?
        print(f"Drawing a sample outfit's {len(looks.shots())} pictures: the front picture, then the others made from it.\n"
              "This takes a few minutes and each picture is billed to your key…", flush=True)
        try:
            looks.sample_set(lambda line: print("  " + line, flush=True))
        except imagegen.DrawError as problem:
            sys.exit(f"\nIt did not work: {looks.SAY.get(problem.kind, looks.SAY['unknown'])}\n  {problem.detail}")
        print("Done. Open the files side by side to compare them.")
        return
    if not args.test:
        print("To check the key by drawing one sample picture (the service bills it, a few cents):\n"
              "  python -m wardrobe looks --test\n"
              "To see a whole set (the front picture and the five made from it, six pictures billed):\n"
              "  python -m wardrobe looks --test-set\n"
              "To see one \"See it move\" video made from a picture of that set (one video billed, far more than a picture):\n"
              "  python -m wardrobe looks --test-video            the front picture's turn\n"
              "  python -m wardrobe looks --test-video cafe       another picture's: walking, turned, street, cafe, library\n"
              "  python -m wardrobe looks --test-video --video-model NAME      with another name for the video model")
        return
    print("Drawing a sample outfit. This takes up to a minute and is billed to your key…", flush=True)
    try:
        path, seconds = looks.sample()
    except imagegen.DrawError as problem:
        sys.exit(f"\nIt did not work: {looks.SAY.get(problem.kind, looks.SAY['unknown'])}\n  {problem.detail}")
    print(f"It works: {path} ({seconds:.0f} seconds). Open that file to look at it.")


# What `python -m wardrobe example-pictures --help` says above its options.
EXAMPLE_PICTURES = (
    "Draws the AI pictures of the example wardrobe that visitors without an account look through: the front picture "
    "of each of its first outfits, in the order a visitor sees them, of Stilsmith's house model (never anyone's "
    "photo). First it says how many are there already, how many it would draw, and what that would cost by "
    "price_each_usd in config/looks.toml (an estimate); without --yes it stops there. Each picture is billed to the "
    "image service's key. It is the owner's, run by hand where the site runs (deploy/README.md): it is not counted "
    "in the day's picture limits, it never runs by itself, and a visitor never causes a drawing. Running it again "
    "draws only what is still missing."
)


def _whole(low: int, high: int):
    """For the options: a whole number from `low` to `high`, else a plain line saying so."""
    def read(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            value = low - 1
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"a whole number from {low} to {high}")
        return value
    return read


def _dollars(text: str) -> Decimal:
    """For --max-cost: an amount in US dollars, like 1.00 (exact, so that 12 pictures at 0.05 are 0.60, not more)."""
    try:
        value = Decimal(text.strip().lstrip("$"))
    except InvalidOperation:
        value = Decimal(-1)
    if not value.is_finite() or value < 0:
        raise argparse.ArgumentTypeError("an amount in US dollars, like 1.00")
    return value


def _usd(amount: Decimal) -> str:
    """$0.35: to the cent, rounded up (it is an estimate: better a little high)."""
    return f"${amount.quantize(Decimal('0.01'), rounding=ROUND_UP)}"


def example_pictures(args: argparse.Namespace) -> None:
    """The owner's command (EXAMPLE_PICTURES): what drawing the example wardrobe's pictures would cost and, with
    --yes, drawing them one at a time, each waited for. guests.py has the example wardrobe and the visitor's order,
    looks.draw_front_now the drawing."""
    from . import db, guests, looks, selection, settings, yes
    from .config import ConfigError

    if not settings.PRODUCTION:
        sys.exit("There is no example wardrobe on your own machine: it is for the visitors of the public site. "
                 "Run this where the site runs (deploy/README.md).")
    try:
        on, line = looks.status()
        price = looks.price_each()
    except ConfigError as mistake:
        sys.exit(f"Nothing was drawn: {mistake}")
    if not on:
        sys.exit(f"Nothing was drawn: AI pictures are {line}.")
    if price is None:
        sys.exit("Nothing was drawn: the estimate needs price_each_usd under [pictures] in config/looks.toml.")
    db.init()
    example = db.internal_account(guests.EXAMPLE_EMAIL)     # (not guests.example_id: that is the site's process)
    if example is None:
        sys.exit("There is no example wardrobe here yet: the site makes it when it starts, and its start-up lines "
                 "say if it could not. Nothing was drawn.")

    with db.as_user(example):
        reading = db.set_read_only(True)     # read as a visitor's page reads the example: nothing can be written
        try:
            first = guests.first_outfits(selection.build(), args.outfits)
        finally:
            db.reset_read_only(reading)
        states = []                          # for each: there | working (being drawn already) | missing
        for _, board in first:
            front = board["photos"][0].look if board.get("photos") else None
            states.append("there" if guests.outfit_picture(board) else
                          "working" if front is not None and front.status == "working" else "missing")
        missing = [(number, board) for number, ((_, board), state) in enumerate(zip(first, states), 1)
                   if state == "missing"]
        wanted = missing[:args.sample] if args.sample else missing
        cost = price * len(wanted)

        print(f"AI pictures: {line}", flush=True)
        if len(first) < args.outfits:
            print(f"The example wardrobe: all its {len(first)} outfits, as a visitor sees them (it has no more).")
        else:
            print(f"The example wardrobe: its first {len(first)} outfits, as a visitor sees them.")
        print(f"{states.count('there')} of {len(first)} already there.")
        if "working" in states:
            busy = states.count("working")
            print(f"{busy} {'is' if busy == 1 else 'are'} being drawn already: left alone.")
        if not wanted:
            print("Nothing to draw.")
            return
        each = f"{len(wanted)} {'picture' if len(wanted) == 1 else 'pictures'} at ${price}, price_each_usd in config/looks.toml"
        if len(wanted) < len(missing):
            print(f"{len(missing)} missing; --sample {args.sample} draws the first {len(wanted)} of them: "
                  f"about {_usd(cost)} ({each}).")
        else:
            print(f"{len(wanted)} to draw: about {_usd(cost)} ({each}).")
        if cost > args.max_cost:
            sys.exit(f"That is more than --max-cost ({_usd(args.max_cost)}), so nothing was drawn. "
                     "Draw fewer with --sample, or allow more with --max-cost.")
        if not args.yes:
            print("Nothing was drawn. To draw them, run this again with --yes.")
            return
        if not guests.door_open():
            print("Note: visitors cannot look around at the moment (guests = false in config/site.toml).")

        print(f"Drawing {len(wanted)}, one at a time (each takes up to a minute):", flush=True)
        drawn = failed = billed = 0
        for done, (number, board) in enumerate(wanted, 1):
            if looks.held_off():         # the image service's last answer would only come again for the next ones
                print(f"Stopped: the other {len(wanted) - done + 1} were not sent. Run this again once that is put "
                      "right: it draws only what is missing.")
                break
            started = time.time()
            try:
                result, problem = looks.draw_front_now(board["pieces"])
            except ValueError as refusal:
                sys.exit(str(refusal))
            said = f"  {done}/{len(wanted)}  #{number}, the {yes.name(board['pieces'])}:"
            if result == "ready":
                drawn += 1
                billed += 1
                print(f"{said} ready ({time.time() - started:.0f} seconds)", flush=True)
            elif result != "failed":
                print(f"{said} {'there already' if result == 'there' else 'being drawn already'}, nothing sent",
                      flush=True)
            else:
                failed += 1
                billed += 0 if problem is None or problem.free else 1
                why = (looks.SAY.get(problem.kind, looks.SAY["unknown"]) + (f" {problem.detail}" if problem.detail
                                                                             else "")) if problem else "not sent"
                print(f"{said} failed. {why}", flush=True)

    print(f"Done: {drawn} drawn" + (f", {failed} failed" if failed else "") + ".")
    print(f"Spent, by this command's estimate: about {_usd(price * billed)} ({billed} "
          f"{'picture' if billed == 1 else 'pictures'} at ${price}"
          + (", counting those that failed after reaching the image service: it may bill them" if billed > drawn
             else "") + ").")
    if drawn and guests.door_open():
        print("Visitors see the new pictures from their next page load.")


def rebuild_mock(args: argparse.Namespace) -> None:
    _local_only("Rebuilding the demo catalogue")
    from . import catalog, db, mock

    db.init()
    current = catalog.stored()      # what you added from a store that is no longer offered is kept too
    if current.get("source") == "collected" and not args.yes:
        sys.exit("The catalogue holds real store data. To throw it away and go back to the\n"
                 "invented demo data, run:  python -m wardrobe mock --yes")
    data = mock.build(db.list_slots())
    data["candidates"] += [c for c in current.get("candidates", []) if c.get("source") == "manual"]
    catalog.save(data)
    print(f"Demo catalogue rebuilt: {len(data['candidates'])} invented candidates "
          f"for {len(db.list_slots())} slots.")


def main(argv: list[str] | None = None) -> None:
    from . import settings

    parser = argparse.ArgumentParser(prog="python -m wardrobe",
                                     description=f"{settings.SITE_NAME}, a capsule wardrobe builder")
    parser.set_defaults(func=serve, lan=False, port=8000)
    sub = parser.add_subparsers(title="commands")

    p_serve = sub.add_parser("serve", help="start the app (the default)")
    p_serve.add_argument("--lan", action="store_true", help="reachable from other devices on your network")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=serve)

    p_refresh = sub.add_parser("refresh", help="collect store data by hand, for this computer only (never scheduled)",
                               description=COLLECTOR_IS_PRIVATE)
    from .collect import STORE_ORDER
    p_refresh.add_argument("--store", action="append", default=[], choices=STORE_ORDER,
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
    p_looks.add_argument("--test-set", action="store_true",
                         help="draw a sample outfit's whole set: the front picture and the pictures made from it (each billed)")
    p_looks.add_argument("--test-video", nargs="?", const="front", default=None, metavar="PICTURE",
                         help="make one \"See it move\" video from a picture of that sample set: front (the turn) "
                              "unless another is named, e.g. cafe (billed, far more than a picture)")
    p_looks.add_argument("--video-model", metavar="NAME",
                         help="with --test-video: try this name for the video model instead of [videos] model")
    p_looks.set_defaults(func=check_looks)

    from .guests import MOST, PAGE
    p_example = sub.add_parser("example-pictures", help="draw the AI pictures of the example wardrobe that visitors "
                                                        "see (the owner's, by hand; billed, and only with --yes)",
                               description=EXAMPLE_PICTURES)
    p_example.add_argument("--outfits", type=_whole(1, MOST), default=PAGE, metavar="N",
                           help=f"its first N outfits, as a visitor sees them ({PAGE}, the default: his first page; "
                                f"{2 * PAGE}: also those after one \"Show more outfits\"; at most {MOST})")
    p_example.add_argument("--sample", type=_whole(1, MOST), metavar="K",
                           help="draw only the first K of those still missing, to look at them first")
    p_example.add_argument("--max-cost", type=_dollars, default=Decimal("1.00"), metavar="USD",
                           help="draw nothing if the estimate is above this, in US dollars (default 1.00)")
    p_example.add_argument("--yes", action="store_true",
                           help="draw them; without it, it only says what it would draw and what that would cost")
    p_example.set_defaults(func=example_pictures)

    p_chat = sub.add_parser("chat", help="is the style chat switched on? (--test sends one message)")
    p_chat.add_argument("--test", metavar="WORDS", help="send these words to Google's text model and print its answer")
    p_chat.set_defaults(func=check_chat)

    p_mock = sub.add_parser("mock", help="go back to the invented demo catalogue")
    p_mock.add_argument("--yes", action="store_true", help="discard collected store data without asking")
    p_mock.set_defaults(func=rebuild_mock)

    from .feeds import commands as feed_commands      # stores, feeds: the licensed store feeds
    feed_commands.add(sub)
    from .owner import add_commands as owner_commands  # owner: the accounts that see the owner's pages
    owner_commands(sub)
    from .videos import add_commands as pro_commands   # pro: the accounts that may ask for more videos a day
    pro_commands(sub)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
