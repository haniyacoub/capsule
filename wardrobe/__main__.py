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
    python -m wardrobe looks --test-photos FOLDER    draw an outfit of your own garments from words, and with their photos sent along
    python -m wardrobe example-pictures       what drawing the example wardrobe's pictures (what visitors see) would cost
    python -m wardrobe example-pictures --yes ... and draw them (billed; --sample 3: only three; --max-cost 1.00)
    python -m wardrobe example-pictures --clips 3     ... and the clips of its first three outfits (--yes to make them)
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
    "Reads the stores' category pages in a visible Chrome window (product pages only with --pool --fabric, and only "
    "for each product's fabric; never COS's or Weekday's, which refuse them) and keeps "
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
    from .collect import STORE_ORDER, collected_stores, load_settings
    from .collect import refresh as collect

    if args.pool:
        return refresh_pool(args)
    bootstrap()   # in case the app has never been started: profile, slots
    slots = {s["id"]: s for s in db.list_slots()}
    unknown = [s for s in args.slot if s not in slots]
    if unknown:
        sys.exit(f"No slot called {', '.join(unknown)}. Slot ids: {', '.join(slots)}")
    settings = load_settings()
    others = [k for k in args.store if k not in STORE_ORDER and k in collected_stores(settings)]
    if others:
        sys.exit(f"{', '.join(settings[k].get('label', k) for k in others)}: collected for the shared list only. "
                 "Run:  python -m wardrobe refresh --pool --store " + " --store ".join(others))
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


def refresh_pool(args: argparse.Namespace) -> None:
    """`refresh --pool`: every plain product of the chosen stores' category pages, into data/pool.json (pool.py).
    With --fabric: the fabric pass instead, each collected product's own page read once for its fabric (fabric.py)."""
    from .collect import collected_stores, load_settings
    from .collect import pool

    if args.fabric:
        return refresh_fabric(args)
    if args.sort_again:
        return refresh_sort_again(args)
    settings = load_settings()
    keys = [k for k in collected_stores(settings) if not args.store or k in args.store]
    if not keys:
        sys.exit("No store to collect: none of these has category pages listed (config/stores.toml, "
                 "config/collect.local.toml).")
    names = ", ".join(settings[k].get("label", k) for k in keys)
    print(f"Collecting every plain product of {names} for the shared list.\n"
          "A Chrome window opens and reads each store's category pages one at a time, with a few\n"
          "seconds between two pages of a store, so this is slow on purpose: about 5 to 10 minutes\n"
          "a store. Leave that window alone; you can keep using the computer. Ctrl+C stops and keeps\n"
          "what has been collected so far.")
    try:
        results = pool.run(keys)
    except KeyboardInterrupt:
        sys.exit("\nStopped. What was collected up to here has been saved.")
    except RuntimeError as problem:
        sys.exit(f"\n{problem}")
    print("\nDone.\n")
    for read in results.values():
        print("\n".join(pool.report(read)))
    print(f"\nThe pool: {pool.pool_path()}\nThis report: {pool.report_path()}\n"
          "Copy the pool into a service's list with:  python -m wardrobe publish FOLDER")


def refresh_sort_again(args: argparse.Namespace) -> None:
    """`refresh --pool --sort-again`: the pool's products sorted again with the words as they are now, without
    opening any page (pool.sort_again)."""
    from .collect import load_settings, pool

    the_pool = pool.load()
    keys = [k for k in the_pool["stores"] if not args.store or k in args.store]
    if not keys:
        sys.exit("The pool has no products of these stores yet. Run:  python -m wardrobe refresh --pool")
    results = pool.sort_again(the_pool, load_settings(), keys)
    pool.save(the_pool)
    pool.write_report(the_pool)
    for read in results.values():
        left = sum(len(names) for names in read.left_out.values())
        print(f"{read.label}: {len(read.products)} products kept" + (f", {left} left out now" if left else ""))
    print(f"\nNo page was opened. The pool: {pool.pool_path()}\nThe report, every store: {pool.report_path()}")


def refresh_fabric(args: argparse.Namespace) -> None:
    """`refresh --pool --fabric`: each pooled product's own page, read once for its fabric (collect/fabric.py)."""
    from .collect import fabric, load_settings, pool

    settings = load_settings().get("collector", {})
    most = args.max_pages or int(settings.get("max_product_pages", 300))
    stores = [k for k in pool.load()["stores"] if not args.store or k in args.store]
    if not stores:
        sys.exit("The pool has no products of these stores yet. Run:  python -m wardrobe refresh --pool")
    print(f"Reading the product pages of {len(stores)} store{'s' if len(stores) != 1 else ''}, at most {most} a "
          f"store, only for each product's fabric.\n"
          f"A Chrome window opens; with the pause between two pages this takes about {most * fabric.SECONDS_A_PAGE // 60} "
          "minutes a store.\nLeave that window alone; Ctrl+C stops and keeps what has been read so far.")
    try:
        results = fabric.run(stores, most)
    except KeyboardInterrupt:
        sys.exit("\nStopped. What was read up to here has been saved.")
    except RuntimeError as problem:
        sys.exit(f"\n{problem}")
    print("\nDone.")
    for done in results.values():
        print("  " + fabric.report(done))


def publish(args: argparse.Namespace) -> None:
    _local_only("Publishing")
    from pathlib import Path

    from . import db, shared

    db.init()
    fresh, _, _ = shared.to_publish()
    if not fresh:
        sys.exit("There is no collected store data to publish yet. Run:  python -m wardrobe refresh  "
                 "(or  python -m wardrobe refresh --pool)")
    count, kept = shared.publish(Path(args.folder))
    print(f"Published {count} products of {len(fresh)} store{'s' if len(fresh) != 1 else ''} to "
          f"{Path(args.folder) / shared.POOL_NAME}" + (f"; the {kept} products of the other stores in it were kept as "
                                                       "they were." if kept else ".") + "\n"
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


def _key_help(then: str = "and start the app from the same terminal. To keep the key for every new terminal,\n"
                          "add that line to the file ~/.zshrc.") -> str:
    """How to set the key of the service config/looks.toml names under [service] (Google, as the file comes), and
    what to do `then`."""
    from . import looks

    where, export = {"openai": ("platform.openai.com", 'OPENAI_API_KEY="sk-…"'),
                     "google": ("aistudio.google.com", 'GEMINI_API_KEY="…"')}.get(
        looks.load_rules()["service"]["use"],
        ("platform.openai.com or aistudio.google.com", 'OPENAI_API_KEY="sk-…"      (or GEMINI_API_KEY="…")'))
    return (f"\nGet a key from {where}, then in this terminal:\n"
            f"  export {export}\n" + then)


def test_photos(args: argparse.Namespace, on: bool, line: str) -> None:
    """The owner's test of reference photographs (phototest.py): one outfit of his own garments, drawn from the
    words alone and with the garments' photographs sent along, to compare. Says how each photograph was read, what
    will be drawn and about what it costs, and draws nothing before that was answered with y (or --yes)."""
    from pathlib import Path

    from . import looks, phototest
    from .config import ConfigError
    from .garments import GARMENTS

    folder = Path(args.test_photos).expanduser()
    try:
        photos, skipped = phototest.read(folder)
        convert = phototest.converter()
        sent = [phototest.prepare(photo.file, convert) for photo in photos]
        rules, price = looks.load_rules(), looks.price_each()
    except (phototest.Unusable, ConfigError) as problem:
        sys.exit(f"Nothing was drawn: {problem}")
    n, more = len(photos), args.pictures
    print(f"One outfit from {n} {'photograph' if n == 1 else 'photographs'} in {folder}, read as:")
    for number, (photo, picture) in enumerate(zip(photos, sent), 1):
        print(f"  {number}. {GARMENTS[photo.kind].label + ':':<17}{photo.words}   ({photo.file.name}, "
              f"{max(1, len(picture) // 1024)} KB as sent)")
    if skipped:
        print("Left alone, no photographs: " + ", ".join(skipped))
    print("The image service is told of them, in the picture from words and with the photographs alike:")
    for said in phototest.listed(photos):
        print("  " + said)
    plain = phototest.colourless(photos)
    if plain:
        print("No colour in the name of: " + ", ".join(plain) + ". The picture from words alone has only the names "
              "to go on:\nadd each garment's colour and fabric to its file's name for a fair comparison.")
    if convert is None:
        print("This computer has no `sips` (it is part of macOS): the photographs are sent as they are, less\n"
              "everything but the picture. One taken with a phone held upright may then lie on its side.")
    cost = phototest.estimate(n, more, price)
    print("\nTo draw, on Stilsmith's house model (no photo of a person is used):\n"
          "  1 picture from the words alone, as the app draws today\n"
          f"  {more} {'picture' if more == 1 else 'pictures'} with your {n} photographs sent along\n"
          f"That is {more + 1} pictures billed to your key"
          + (f": about {_usd(cost)}." if cost is not None
             else ". (No price is set in config/looks.toml to estimate from.)")
          + "\nYour photographs go to the image service for this, resized, without where and when they were taken.")
    if not on:      # (the status line is the app's: "… and start the app again" is not what this command needs)
        why = line.removesuffix(" and start the app again").rstrip(".")
        sys.exit(f"\nNothing was drawn: AI pictures are {why}.\n"
                 + _key_help("and run this command again in the same terminal."))
    chosen = looks.service()
    if chosen is None:      # (as `on` said; for the type checker)
        sys.exit("\nNothing was drawn: no key is set.")
    print(f"Drawn by {chosen.label} ({chosen.model}).")
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("\nNothing was drawn: answer in a terminal, or add --yes.")
        if input("\nDraw them? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Nothing was drawn.")
    out = phototest.folder_for(folder)
    print(f"Drawing into {out}\nEach picture takes up to a minute…", flush=True)
    run = phototest.draw(photos, sent, more, out, chosen, rules, lambda said: print("  " + said, flush=True))
    drawn = len(run.drawn)
    if run.problem is not None:
        billed = "it was not billed" if run.problem.free else "it may have been billed all the same"
        sys.exit(f"\nIt stopped at picture {drawn + 1} of {more + 1}: "
                 f"{looks.SAY.get(run.problem.kind, looks.SAY['unknown'])}\n  {run.problem.detail}\n"
                 f"{drawn} {'picture was' if drawn == 1 else 'pictures were'} drawn and billed; the one that failed "
                 f"was not drawn, and {billed}.\nWhat there is: {out / 'compare.html'}")
    print(f"Done: {drawn} pictures. Open this page to compare them:\n  {out / 'compare.html'}")


def check_looks(args: argparse.Namespace) -> None:
    """Say whether the AI pictures are on and, with --test, prove it by drawing one."""
    from . import imagegen, looks

    on, line = looks.status()
    if args.test_photos is not None:
        test_photos(args, on, line)
        return
    print(f"AI pictures of outfits: {line}")
    if not on:
        sys.exit(_key_help())
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
    "draws only what is still missing. "
    "With --clips K it also makes a 5-second clip of each of the first K outfits, from its front picture (the movement "
    "is example under [videos.motion] in config/looks.toml), which visitors see in place of the picture, muted and "
    "looping: in the same estimate (price_per_second_usd under [videos]), under the same --max-cost and --yes, outside "
    "the day's video limits, and again only what is missing. It refuses while AI videos are off."
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
    """The owner's command (EXAMPLE_PICTURES): what drawing the example wardrobe's pictures (and, with --clips, making
    the clips of its first outfits) would cost and, with --yes, doing it one at a time, each waited for: the pictures
    first, as each clip is made from its outfit's picture. guests.py has the example wardrobe and the visitor's order,
    looks.draw_front_now the drawing, videos.make_example_now the clips."""
    from . import db, guests, looks, selection, settings, videos, yes
    from .config import ConfigError

    clips = args.clips or 0
    nothing = "Nothing was drawn or made" if clips else "Nothing was drawn"
    if not settings.PRODUCTION:
        sys.exit("There is no example wardrobe on your own machine: it is for the visitors of the public site. "
                 "Run this where the site runs (deploy/README.md).")
    try:
        on, line = looks.status()
        price = looks.price_each()
        videos_on, video_line = videos.status() if clips else (False, "")
        clip, per_second = (videos.example(), videos.price_per_second()) if clips else (None, None)
    except ConfigError as mistake:
        sys.exit(f"{nothing}: {mistake}")
    if not on:
        sys.exit(f"{nothing}: AI pictures are {line}.")
    if price is None:
        sys.exit(f"{nothing}: the estimate needs price_each_usd under [pictures] in config/looks.toml.")
    if clips and not videos_on:
        sys.exit(f"{nothing}: AI videos are {video_line}.")
    if clips and clip is None:
        sys.exit(f"{nothing}: the clips need their movement, example under [videos.motion] in config/looks.toml.")
    if clips and per_second is None:
        sys.exit(f"{nothing}: the estimate needs price_per_second_usd under [videos] in config/looks.toml.")
    db.init()
    example = db.internal_account(guests.EXAMPLE_EMAIL)     # (not guests.example_id: that is the site's process)
    if example is None:
        sys.exit("There is no example wardrobe here yet: the site makes it when it starts, and its start-up lines "
                 f"say if it could not. {nothing}.")

    outfits_wanted = max(args.outfits, clips)               # a clip is made from its outfit's picture
    with db.as_user(example):
        reading = db.set_read_only(True)     # read as a visitor's page reads the example: nothing can be written
        try:
            w = selection.build()
            first = guests.first_outfits(w, outfits_wanted)
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

        # The clips: of the first K outfits in the order a visitor will see them once the pictures this run draws are
        # there (those with a picture come first, guests.row), each made from that outfit's picture. Worked out now,
        # so that the estimate counts exactly the clips that may be made, and never fewer.
        to_make: list[tuple[int, dict]] = []
        clip_states: list[str] = []          # for each of the first K: there | working | missing | no picture
        if clips:
            pictured = {board["key"] for (_, board), state in zip(first, states) if state == "there"}
            pictured |= {board["key"] for _, board in wanted}
            reading = db.set_read_only(True)
            try:
                after = guests.first_outfits(w, outfits_wanted, pictured=lambda board: board["key"] in pictured)
            finally:
                db.reset_read_only(reading)
            for number, (_, board) in enumerate(after[:clips], 1):
                state = videos.example_state(board) if board["key"] in pictured else "no picture"
                clip_states.append(state)
                if state == "missing":
                    to_make.append((number, board))
        each_clip = (per_second or Decimal(0)) * videos.EXAMPLE_SECONDS
        clip_cost = each_clip * len(to_make)

        print(f"AI pictures: {line}", flush=True)
        if len(first) < outfits_wanted:
            print(f"The example wardrobe: all its {len(first)} outfits, as a visitor sees them (it has no more).")
        else:
            print(f"The example wardrobe: its first {len(first)} outfits, as a visitor sees them.")
        print(f"{states.count('there')} of {len(first)} already there.")
        if "working" in states:
            busy = states.count("working")
            print(f"{busy} {'is' if busy == 1 else 'are'} being drawn already: left alone.")
        if not wanted:
            print("Nothing to draw.")
        else:
            each = (f"{len(wanted)} {'picture' if len(wanted) == 1 else 'pictures'} at ${price}, price_each_usd in "
                    "config/looks.toml")
            if len(wanted) < len(missing):
                print(f"{len(missing)} missing; --sample {args.sample} draws the first {len(wanted)} of them: "
                      f"about {_usd(cost)} ({each}).")
            else:
                print(f"{len(wanted)} to draw: about {_usd(cost)} ({each}).")
        if clips:
            shown = len(clip_states)
            print(f"AI videos: {video_line}")
            print(f"Clips of the first {shown} {'outfit' if shown == 1 else 'outfits'}: "
                  f"{clip_states.count('ready')} already there.")
            if "working" in clip_states:
                busy = clip_states.count("working")
                print(f"{busy} {'is' if busy == 1 else 'are'} being made already: left alone.")
            if "no picture" in clip_states:
                print(f"{clip_states.count('no picture')} will have no picture to make one from: left out.")
            if not to_make:
                print("No clip to make.")
            else:
                print(f"{len(to_make)} {'clip' if len(to_make) == 1 else 'clips'} to make: about {_usd(clip_cost)} "
                      f"({_clips(len(to_make), per_second)}, price_per_second_usd in config/looks.toml).")
            if wanted and to_make:
                print(f"In all: about {_usd(cost + clip_cost)}.")
        if not wanted and not to_make:
            return
        if cost + clip_cost > args.max_cost:
            if clips:
                sys.exit(f"That is more than --max-cost ({_usd(args.max_cost)}), so {nothing.lower()}. Ask for "
                         "fewer with --sample or --clips, or allow more with --max-cost.")
            sys.exit(f"That is more than --max-cost ({_usd(args.max_cost)}), so nothing was drawn. "
                     "Draw fewer with --sample, or allow more with --max-cost.")
        if not args.yes:
            if clips:
                print(f"{nothing}. To go ahead, run this again with --yes.")
            else:
                print("Nothing was drawn. To draw them, run this again with --yes.")
            return
        if not guests.door_open():
            print("Note: visitors cannot look around at the moment (guests = false in config/site.toml).")

        drawn = failed = billed = 0
        if wanted:
            print(f"Drawing {len(wanted)}, one at a time (each takes up to a minute):", flush=True)
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

        made = clips_failed = clips_billed = 0
        if to_make:
            print(f"Making {len(to_make)} {'clip' if len(to_make) == 1 else 'clips'}, one at a time (each takes up to "
                  "two minutes):", flush=True)
        for done, (number, board) in enumerate(to_make, 1):
            said = f"  {done}/{len(to_make)}  #{number}, the {yes.name(board['pieces'])}:"
            now = {"key": board["key"], "pieces": board["pieces"]}       # its picture as it is now, drawn or not
            looks.attach([now])
            front = now["photos"][0].look if now.get("photos") else None
            if front is None or front.status != "ready" or not front.file:
                print(f"{said} its picture is not there, so no clip: nothing sent", flush=True)
                continue
            started = time.time()
            try:
                result, problem = videos.make_example_now(front)
            except ValueError as refusal:
                sys.exit(str(refusal))
            if result == "ready":
                made += 1
                clips_billed += 1
                print(f"{said} ready ({time.time() - started:.0f} seconds)", flush=True)
            elif result != "failed":
                print(f"{said} {'there already' if result == 'there' else 'being made already'}, nothing sent",
                      flush=True)
            else:
                clips_failed += 1
                clips_billed += 0 if problem is None or problem.free else 1
                why = (videos.SAY.get(problem.kind, videos.SAY["unknown"]) + (f" {problem.detail}" if problem.detail
                                                                               else "")) if problem else "not sent"
                print(f"{said} failed. {why}", flush=True)
                if problem is not None and (problem.kind in looks.OPERATORS or problem.kind == "busy"):
                    if done < len(to_make):     # the next ones would only get the same answer
                        print(f"Stopped: the other {len(to_make) - done} were not sent. Run this again once that is "
                              "put right: it makes only what is missing.")
                    break

    if wanted:
        print(f"Done: {drawn} drawn" + (f", {failed} failed" if failed else "") + ".")
        print(f"Spent, by this command's estimate: about {_usd(price * billed)} ({billed} "
              f"{'picture' if billed == 1 else 'pictures'} at ${price}"
              + (", counting those that failed after reaching the image service: it may bill them" if billed > drawn
                 else "") + ").")
    if to_make:
        print(f"Clips done: {made} made" + (f", {clips_failed} failed" if clips_failed else "") + ".")
        print(f"Spent on clips, by this command's estimate: about {_usd(each_clip * clips_billed)} "
              f"({_clips(clips_billed, per_second)}"
              + (", counting those that failed after reaching Google: it may bill them" if clips_billed > made
                 else "") + ").")
    if (drawn or made) and guests.door_open():
        print("Visitors see the new " + ("pictures and clips" if drawn and made else "pictures" if drawn else "clips")
              + " from their next page load.")


def _clips(n: int, per_second: Decimal | None) -> str:
    """'3 clips of 5 seconds at $0.10 a second', for the estimate and what was spent: the price as config/looks.toml
    has it, with cents (0.1 is $0.10; 0.075 stays $0.075)."""
    from .videos import EXAMPLE_SECONDS
    price = per_second or Decimal(0)
    cents = price.quantize(Decimal("0.01")) if price == price.quantize(Decimal("0.01")) else price
    return f"{n} {'clip' if n == 1 else 'clips'} of {EXAMPLE_SECONDS} seconds at ${cents} a second"


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
    from .collect import STORE_ORDER, collected_stores
    from .config import ConfigError
    try:
        collected = collected_stores()
    except ConfigError:         # a typo in the stores' files must not stop the app from starting: refresh says it
        collected = STORE_ORDER
    p_refresh.add_argument("--store", action="append", default=[], choices=collected,
                           help="only this store (repeatable)")
    p_refresh.add_argument("--pool", action="store_true",
                           help="every plain product of the stores' category pages, for the shared list (collect/pool.py)")
    p_refresh.add_argument("--fabric", action="store_true",
                           help="with --pool: read each collected product's own page once, only for its fabric "
                                "(collect/fabric.py)")
    p_refresh.add_argument("--sort-again", action="store_true",
                           help="with --pool: sort the pool's products again with the words as they are now, "
                                "without opening any page (collect/pool.py)")
    p_refresh.add_argument("--max-pages", type=int, default=None, metavar="N",
                           help="with --fabric: at most N product pages a store in this run (default: "
                                "max_product_pages in config/stores.toml)")
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
    p_looks.add_argument("--test-photos", metavar="FOLDER",
                         help="draw the outfit in FOLDER (a photo of each of your own garments, named for what it "
                              "is: “jumper navy merino.jpg”) from words alone and with the photos sent along; "
                              "says what it costs and asks first")
    p_looks.add_argument("--pictures", type=_whole(1, 9), default=3, metavar="N",
                         help="with --test-photos: how many pictures to draw with the photos (default 3, at most 9)")
    p_looks.add_argument("--yes", action="store_true", help="with --test-photos: draw without asking")
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
    p_example.add_argument("--clips", type=_whole(1, MOST), metavar="K",
                           help="also make the 5-second clip of each of the first K outfits, from its picture, which "
                                "visitors see in place of the picture (billed by the second; needs AI videos on)")
    p_example.add_argument("--max-cost", type=_dollars, default=Decimal("1.00"), metavar="USD",
                           help="draw and make nothing if the estimate is above this, in US dollars (default 1.00)")
    p_example.add_argument("--yes", action="store_true",
                           help="draw them (and make the clips); without it, it only says what it would do and what "
                                "that would cost")
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
