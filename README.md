# Stilsmith

A local web app for building a men's capsule wardrobe from COS and Weekday
(German sites, EUR). It proposes the slots, collects candidates from the stores,
scores them, picks an item per slot at the price level you choose, shows the
outfits they make one at a time, checks sizes and writes the shopping list.

Only stores with a partner (affiliate) programme are offered: each store in
[config/stores.toml](config/stores.toml) has a `programme` line, and a store
whose programme is `"none"` is never shown or collected. Zara has none, so it
is not offered.

Run as described here, everything stays on this computer: no accounts, no
cloud, no paid APIs. There is one exception, and it is off until you switch it
on: [AI pictures of your outfits](#ai-pictures-of-outfits-optional-costs-money),
drawn by an outside image service with your own key. The same code can also run
as a public service with customer accounts; that is described in
[PRODUCTION.md](PRODUCTION.md).

Working on the code? Start with [CONTRIBUTING.md](CONTRIBUTING.md).

Stilsmith was called Capsule before. Names inside the code keep that old name on
purpose, so that a server already running carries on unchanged: the environment
variable `CAPSULE_ENV` (and its friends), the package `wardrobe`, the data folders,
the database and the repository's name. The product's name on every page, email
and message comes from one setting, `SITE_NAME` in `wardrobe/settings.py`.

## Run it

In the folder that holds the code:

```bash
source .venv/bin/activate
python -m wardrobe
```

Open <http://127.0.0.1:8000>. Stop with `Ctrl+C`. If port 8000 is busy the app
picks the next free one and prints it; `python -m wardrobe serve --port 8123`
chooses one.

Setting up from scratch (a new machine, or a deleted `.venv`). It needs Python
3.13 or newer: check with `python3 --version` (a Mac's own Python is 3.9; get a
newer one with `brew install python@3.14`, then use `python3.14` below).

```bash
git clone https://github.com/haniyacoub/capsule.git && cd capsule
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium     # for ./check.sh browser, and if Google Chrome is missing; about 600 MB
```

### On your phone

```bash
python -m wardrobe serve --lan
```

It prints an address like `http://192.168.x.x:8000`; open that on a phone on the
same Wi-Fi. There is no login, so anyone on that network can open it while it
runs. Use it on a network you trust, and leave `--lan` off otherwise.

Without a login the app answers only when it is asked for by this computer's
own address: `localhost`, a numeric address like the one above, or a name
ending in `.local`. A request arriving under any other name is refused, which
stops a web page elsewhere from talking to it through your browser.

## Refresh the data

```bash
python -m wardrobe refresh                      # every slot, every store: 20 to 30 minutes
python -m wardrobe refresh --store cos          # one store
python -m wardrobe refresh --slot white-tee     # one slot (ids are shown when you mistype one)
python -m wardrobe refresh --max 3              # fewer candidates per slot, faster
```

The collector is for your own machine and for testing only: run it by hand,
never on a schedule, and never as the source for the public site, which is to
use the stores' licensed product feeds ([PRODUCTION.md](PRODUCTION.md#before-customers)).

A Chrome window opens and reads, for each slot, only the category pages listed
for that garment type in [config/stores.toml](config/stores.toml). It is slow on
purpose: one page at a time, a few seconds apart. Leave the window alone and keep
working. The result goes to `data/catalog.json` with the collection time; the
app shows it on the next page load.

What each store gives:

| Store | Collected | Not collected |
| --- | --- | --- |
| Weekday | name, price, colour, picture, sizes in stock | fabric |
| COS | name, price, colour, picture | fabric, sizes in stock |

COS and Weekday answer "Access Denied" when an automated browser opens a product
page, and the collector does not try to get around that: it reads their category
pages only. For those two stores the fabric is **estimated from the product
name** (marked "≈ … estimated", and scored a little lower), and COS items say
"check that your size is in stock".

How it behaves:

- It uses a normal, visible Chrome with its own profile (`data/browser-profile`).
  Nothing about the browser is disguised. Headless browsers are refused outright.
- It reads each store's `robots.txt` first and skips anything disallowed. Search
  pages are disallowed at both, which is why it uses category pages.
- The first refusal, captcha or error from a store ends that store for the run.
  Nothing is retried. What was collected up to there is kept.
- Category addresses change when a store reorganises its menu. If the refresh
  says a page no longer exists, paste the new address into `config/stores.toml`.

### Adding things by hand

On any slot's page:

- **Add a product by link**: paste COS or Weekday product addresses. The pages
  are not opened; the tool takes what the link says and, if that article was
  seen during a refresh, its name, price and picture. Links to a store that is
  not offered are refused.
- **Add details** on a candidate: type the fabric as printed on the product page
  ("80% Wolle, 20% Polyamid"), the sizes in stock, or a price. These win over
  collected data and survive the next refresh.

To go back to the invented demo data: `python -m wardrobe mock --yes`.

## Edit the scoring rules

Open [config/scoring.toml](config/scoring.toml), change a number, save, reload
the page. No restart. Each option's "How it's rated", on a piece's page, shows the result.

The score is a weighted average of three parts, all in that file:

| Part | What to edit | Example |
| --- | --- | --- |
| Fabric | `[fabric.fibres]` is the value of each fibre; `[fabric.by_category.<garment>]` overrides it per garment | make polyester hurt more in trousers: lower `polyester` under `[fabric.by_category.trousers]` |
| Brand | `[brand.cos]`, `[brand.weekday]`: 0–100 per garment type | trust Weekday more for knitwear: raise `knit` under `[brand.weekday]` |
| Price | `[price.bands.<garment>]`: the fair price band | accept pricier coats: raise the upper `fair` value and `steep_above` under `[price.bands.coat]` |

`[weights]` sets how much each part counts. `[fabric.adjustments]` holds the
"mostly synthetic" penalty and the wool-rich bonus. `[fabric.name_guess]` controls
the estimate used when a store gives no composition. If you make a typo, the app
shows a page naming the file and the problem instead of crashing (on a live site
the page is Stilsmith's own error page and the file and line are in the log).

## Price levels

Two controls on the Wardrobe page decide what fills each slot. Neither is a
config value. Under each choice is what the whole wardrobe would cost with it.

- **Price level**: Cheapest, Cheap, Medium, Expensive, Top. For each slot the
  candidates in stock are lined up by price and the level says where on that
  line to pick: the lowest price, a quarter of the way up, the middle, three
  quarters, the highest.
- **Best for budget** is the sixth choice, and not a level: it looks at the
  whole wardrobe. Every slot starts on its cheapest option, and what is left of
  your budget pays for upgrades, first where a euro buys the most quality on
  the pieces you would wear in the most outfits (shoes and trousers are in
  many, one of eight tops in few). It never goes over the budget; if even the
  cheapest options do, it says so. Locked and owned pieces count as money
  already spent. The rule is `fit_budget` in `wardrobe/selection.py`.
- **Minimum quality**: only candidates scoring at least this are lined up at
  all. 0 means anything goes.

"Top" is the dearest option these stores sell for a slot; none of them is
a luxury brand. To rename a level, change its label in `MODES` at the top of
`wardrobe/selection.py`.

## Size check

Every candidate carries notes about things to check before ordering: an
oversized or slim cut, a half shoe size, a trouser length the item doesn't come
in, one-length garments if you are tall or short. If you enter your chest and
waist on the Profile page, it also compares you with each store's size chart and
says where you fall between two sizes.

The charts are in [config/size_charts.toml](config/size_charts.toml) and are
**approximate**: COS and Zara ask automated visitors not to open their size
guides, so the figures were not collected. Correct them from the size guide on a
product page before relying on a "between sizes" note.

## Outfits and the shopping list

- **Outfits** shows one outfit at a time: swipe, or use the arrows. Tap a piece
  to see the product and its price, swap it for another candidate, wear a
  different piece in its place, or leave it off. The heart saves an outfit;
  saved outfits keep their pieces even after the wardrobe or the store data
  changes.
- **Buy this outfit** lists the outfit's pieces store by store with the size to
  order. "Open all" brings up every product page of one store at once. Each
  store has its own basket and checkout, so nothing can pay for all of them in
  one go.
- **List**: everything selected now, grouped by store, with the size to order,
  links, subtotals and the notes above. Download it as Markdown or CSV, or print.

## AI pictures of outfits (optional, costs money)

With a key from an image service, the Outfits page shows each outfit worn by a
model instead of as separate product photos, with a dot on every piece that
opens the same pop-up.

What happens: for each outfit the app sends a written description (the model,
each piece's garment type, colour, fabric, cut and the store's product text) to
OpenAI or Google, and gets one picture back. Your name, sizes and budget are
not sent. The service bills every picture to your key, a few cents each.
Pictures are kept in `data/looks/` and never paid for twice.

Switch it on:

```bash
export OPENAI_API_KEY="sk-…"        # from platform.openai.com, or:
export GEMINI_API_KEY="…"           # from aistudio.google.com
python -m wardrobe
```

For Google, use a key from a Google Cloud project with billing switched on:
Google's image models have no free tier, and its terms forbid free keys for a
service used by people in the EU.

The key lives in the terminal you typed it into. To have it in every new
terminal, add the `export` line to the file `~/.zshrc`. Never put it in a file
inside this folder.

```bash
python -m wardrobe looks            # is it on, and which service draws?
python -m wardrobe looks --test     # draw one sample picture (billed) and say what went wrong if it fails
```

Things to know:

- The clothes in a picture are close to the products, not the products
  themselves: the service draws from words, not from the product photos.
- **Your model**, on the Profile page, sets who wears the outfits: age, height,
  build, skin, hair, beard. Each picture is drawn afresh, so the face differs a
  little between outfits. Upload **your own photo** there and the pictures show
  you instead. Only the picture is kept, in `data/people/`: where and when it
  was taken, which a phone writes into the file, is cut out first. It is sent
  to the service with every picture. It has to be a JPEG or PNG: an iPhone's
  HEIC photo cannot be opened by most browsers, and the page says so as soon
  as you choose one (save a copy as JPEG in Photos or Preview first).
- By default a picture is drawn as soon as you look at an outfit. Set
  `auto = false` in [config/looks.toml](config/looks.toml) to draw only when
  you press "See it worn". `per_day` in the same file caps how many are started
  in 24 hours.
- **Scenes:** under each picture, Studio, Street, Library and Café. The studio
  picture is the one drawn by itself; another scene is drawn only when you tap
  it. Each scene is a picture of its own: billed and counted in `per_day` like
  any other, and kept, so switching back and forth costs nothing. The scenes
  and their words are under `[scenes]` in `config/looks.toml`. The words
  describe the place and the light only: the model, the pose and the clothes
  stay the same, and so do the dots.
- **See it move:** on a finished picture, in any scene, "See it move" asks
  Google's video model for an 8-second clip that starts from that picture: the
  model turns round once, then poses. It plays once (muted), and can then be
  played again or dragged round, sideways or with the arrow keys. It needs
  `GEMINI_API_KEY`, also where OpenAI draws the pictures, and costs far more
  than a picture (about $0.56 to $0.81 a clip in November 2026), so it has its
  own limits under `[videos]` in `config/looks.toml`: one a day per customer,
  five for Pro accounts and owners, ten for the whole site; on your own machine
  only the site's. A video is kept in `data/videos/` and shown again for free;
  where ffmpeg is installed its turn is kept a second time for smooth
  dragging. Pro is a mark on an account, with nothing to buy:
  `python -m wardrobe pro add you@example.com` (also `pro remove`, `pro list`).
- The same file holds the service and model names, the picture quality, the
  wording sent to the service, and where the dots sit on the picture.
- The services rename their models every few months. If pictures stop with
  "does not know the model", put the current name in `config/looks.toml`.
  OpenAI may ask you to verify your organisation before its image models work.
- The connection to both services was written from their documentation of
  November 2026 and tested up to the point where a real key is needed. If the
  first picture fails, the message under the outfit says why, in the service's
  own words, and the same line is added to `data/looks/problems.log`.
- After a failure that needs you (wrong key, no credit, a model name the
  service does not know) the app leaves the service alone for five minutes
  instead of asking again for every outfit you open. Restarting the app clears
  that, and outfits that failed before are then tried afresh.
- What counts against `per_day`: every picture asked for, except a request the
  service certainly did nothing with (it could not be reached, or it turned
  the request away: wrong key, no credit, unknown model, "slow down"). A
  picture the service refused to draw, or an answer that could not be read,
  may have been charged for, so it counts.
- Pictures are drawn two at a time; the rest wait their turn and say so.

## Store feeds (licensed product data)

The public site will take products only from stores whose affiliate programme
has accepted Stilsmith, through the product feed that the programme's network
licenses to approved partners. None has accepted yet, so for now this runs on
three invented sample stores (Musterhaus, Nordfaden, Kleiderwerk) whose feeds
are files in `tests/fixtures/feeds/`.

```bash
python -m wardrobe stores sync              # copy config/feeds.toml into the database
python -m wardrobe stores                   # each store: status, products, feed date, stale or failed
python -m wardrobe feeds                    # every approved store whose feed changed
python -m wardrobe feeds --store musterhaus --from tests/fixtures/feeds/musterhaus.csv   # a file you have
python -m wardrobe stores end musterhaus    # a programme ended: all its products go at once
```

- Stores are listed in [config/feeds.toml](config/feeds.toml) with their network,
  status, feed format and address. Secrets never go there: an address names
  them, `{AWIN_API_TOKEN}`, and they are read from environment variables.
- Every store found with a partner programme for Germany (research of 13 Nov
  2026: OTTO, Breuninger, P&C, COS, Pull&Bear, Levi's and 23 more) is listed
  there, not applied to yet, with its programme's page and notes (what is
  unconfirmed, what the programme requires). `/stores` shows them grouped by
  network in the order to apply, so it doubles as the checklist for applying.
  A store whose programme forbids keeping its data (`links_only = true`, MR
  PORTER) is never imported. Stores with no programme (Zara, the main Zalando
  shop, Uniqlo, Hugo Boss and others) are not listed.
- Formats: Google Shopping (Awin's product API as JSON Lines, Webgains and others
  as CSV or TSV), Awin's standard CSV and Tradedoubler's JSON. Rakuten's files
  come in a later round.
- An import replaces that store's products in one go: whatever is missing from
  the new file is gone, and a failure part-way keeps the old products, as does
  a download that stops short of the size its server announced. A product
  without a price or a link is skipped and counted. A file that would remove
  more than half of a store's products (once it has 10 or more) is refused and
  the old products stay, until you import it with `--force`.
- A download is skipped when the store's `rules.check_url`, or the file's own
  time for a feed on this computer, says the feed has not changed. Otherwise
  it is downloaded, and imported unless its Last-Modified time shows it is the
  version already imported. Only one `feeds` run goes at a time, and Awin's
  API is asked at most 5 times a minute, from one run to the next too.
  Tradedoubler allows 3 downloads of one version a day, so its feed is
  downloaded at most every 8 hours, unless its `check_url` says it changed
  after the last download. A feed older than its refresh hours plus a day is
  marked stale.
- Products come only from approved stores: `--from` imports a file only for an
  approved store or an invented sample store. Such a file is dated by the
  newest time its products carry (an old feed copied today still shows as
  old), or by the file's own time if they carry none.
- It is separate from the collector: nothing from `refresh` or its snapshot goes
  into these tables, and the planner does not use them yet.
- Owners see every listed store and its current products at `/stores`, with
  filters by store, category, colour, size in stock and words, and no export.
  On your own machine you are the owner; in production, sign up, then mark the
  account: `python -m wardrobe owner add you@example.com` (also `owner remove`,
  `owner list`). Anyone else gets "We can't find that page" there.

## Checks

```bash
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt    # once
./check.sh                # lint, types, risky patterns, the tests with coverage: under a minute
./check.sh browser        # ... and a walk-through in a real browser (once: python -m playwright install chromium)
./check.sh audit          # ... and known vulnerabilities in the packages the app runs on
```

The tests (`python -m unittest`) never touch your data, the stores or an image
service: they run on a throwaway folder, saved store pages and a stand-in for
the AI pictures. The browser walk-through (`tests/browser_check.py`) starts the
app by itself and does what a new customer would. On GitHub the same checks
run on every push, together with building the container
(`.github/workflows/checks.yml`).

## Where everything lives

```text
config/scoring.toml        quality score rules
config/stores.toml         which category pages the collector reads, and how slowly
config/size_charts.toml    each store's size labels and body measurements
config/looks.toml          AI pictures and videos: service, limits, wording, where the dots sit
config/feeds.toml          the stores whose licensed product feeds are imported (see "Store feeds")
data/catalog.json          what the stores sell (rewritten by refresh)
data/wardrobe.db           your profile, slots, locks, saved outfits (SQLite)
data/looks/                AI pictures already drawn (safe to delete: they are drawn again when asked for),
                           and problems.log: why a picture could not be drawn
data/videos/               AI videos already made ("See it move"), each with its turn for dragging
data/people/               your photo, if you uploaded one
data/wardrobe.db.before-accounts   copy made when the database gained accounts; delete when happy
data/browser-profile/      the collector's own Chrome profile (cookies and cache; safe to delete)
wardrobe/                  the code; wardrobe/__init__.py lists what each file does
tests/                     python -m unittest; browser_check.py is the walk-through in a browser
check.sh                   every check in one go (see "Checks")
gunicorn.conf.py           read by gunicorn in production mode: stop if workers keep dying (PRODUCTION.md)
deploy/                    running it on a server behind Cloudflare, or a preview from this Mac (deploy/README.md)
```

To start over, stop the app and delete the `data/` folder.

## Good to know

- **Swapping a candidate locks it**, so the price level and slider can't undo
  a manual choice. Tap the lock to hand the slot back to automatic.
- **If nothing reaches the minimum quality**, the slot shows the best-scoring
  item in stock with a warning, so the total stays meaningful.
- **"In stock"** means in stock in your size from the Profile page, translated
  to each store's own labels with the tables in `config/size_charts.toml` (there,
  a W32 waist is `32/32` on jeans and `48` in COS and Weekday trousers).
- **Outfit rules** are the constants at the top of `wardrobe/outfits.py`.
- **A true virtual try-on** (the actual garments, from their product photos, on
  you) is not built. The hook is `wardrobe/tryon.py`: set a provider there and
  a "Try on" button appears under every outfit. The AI pictures above are a
  different thing: drawn from descriptions.
- The stores' terms of use may restrict automated access. The collector is
  deliberately light (category pages, slow, stops at the first refusal), and
  everything it does you can also do by hand with the two forms above.
- The interface uses [htmx](https://htmx.org) 2.0.4, stored locally in
  `wardrobe/static/vendor/`; your browser loads nothing from the internet
  except the product pictures, which come straight from the stores.
