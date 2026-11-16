# Stilsmith

A local web app for building a men's capsule wardrobe from COS and Weekday
(German sites, EUR). It proposes the slots, collects candidates from the stores,
scores them, picks an item per slot at the price level you choose, shows the
outfits they make one at a time, checks sizes and writes the shopping list.

Only stores with a partner (affiliate) programme are offered: each store in
[config/stores.toml](config/stores.toml) has a `programme` line, and a store
whose programme is `"none"` is never shown or collected. Zara has none, so it
is not offered. Of the stores offered, the Stores tab on the Profile page picks
which ones your pieces come from (all of them to start with). Stilsmith is for
men only: every way a product comes in keeps menswear and refuses the rest.

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

- **Add a product by link**: paste product addresses from the stores offered.
  The pages are not opened; the tool takes what the link says and, if that
  article was seen during a refresh, its name, price and picture. Links to a
  store that is not offered are refused. With one link you can also choose the
  product's page as you saved it from your own browser ("Save page as"): its
  name, price, colour and fabric are read from that file where it states them
  (`wardrobe/collect/generic.py`, for any store). The photo never is. Pasting
  a link again keeps what was already known about it. A product with no price
  yet counts as neutral on price until you type one in.
  A link whose name says another kind of garment than the piece (a shirt
  pasted on the coat) is still added, and the answer says so and how to move
  it; it is not refused, because a name read from a link is rough.
- **Stores with no products yet**: Tom Tailor, OTTO, Hirmer, Breuninger, Blue
  Tomato and Bergfreunde are offered for pasted links only. They have no
  category pages in `config/stores.toml`, so nothing is ever collected from
  them, and the Stores tab lists them apart ("No products yet: paste a link on
  a piece's page"). One of them cannot be your only store.
- **Menswear only** (`wardrobe/menswear.py`, no switch): a link, a saved page
  or a feed product that says it is for women or for children is refused, with
  a sentence saying so. One that says nothing is kept. A children's word
  inside a brand's or a product's name ("Billionaire Boys Club") does not
  count: only a folder (`/kinder/`, "Kinder > Jungen") does, and a men's word
  beside it wins.
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
  build, skin, hair, beard. Profile is one screen with the model in the middle:
  a drawn figure (`wardrobe/figure.py`, no AI) takes each choice at once, and
  "Your model" shows the AI picture of the saved model in your first outfit
  ("Draw my model", with the usual limits). Each picture is drawn afresh, so the
  face differs a little between outfits. Upload **your own photo** there and the pictures show
  you instead. Only the picture is kept, in `data/people/`: where and when it
  was taken, which a phone writes into the file, is cut out first. It is sent
  to the service with every picture. It has to be a JPEG or PNG: an iPhone's
  HEIC photo cannot be opened by most browsers, and the page says so as soon
  as you choose one (save a copy as JPEG in Photos or Preview first).
- By default a picture is drawn as soon as you look at an outfit. Set
  `auto = false` in [config/looks.toml](config/looks.toml) to draw only when
  you press "See it worn". `per_day` in the same file caps how many are started
  in 24 hours.
- **Six pictures of an outfit:** the one drawn by itself is the front picture:
  the man standing, facing the camera, on a white studio background, with the
  dots. Under it, "More photos" draws five more: walking and turned (white
  studio), then on a street, in a café and in a library, each with its own
  natural pose. These five are made *from the front picture*: it is sent to
  the image service with a short instruction ("the same man in the same
  outfit, now walking"), so the man and the clothes stay the same. They show
  as small pictures under the outfit as they arrive; tap one to see it large
  (no dots on those: the man stands differently). Each is a picture of its
  own: billed and counted in `per_day` like any other (the page says so
  before the tap), and kept, so looking again costs nothing. When the front
  picture is drawn again, the five made from the old one are deleted. Their
  words are under `[poses]` and `[scenes]` in `config/looks.toml`; another
  pose or place is one more block there. To judge a real service by eye,
  `python -m wardrobe looks --test-set` draws a sample outfit's six pictures
  into `data/looks/` (six pictures billed). With OpenAI the five go to its
  "edits" address with the front picture; that has not been tried for real.
- **See it move:** under whichever of an outfit's pictures is showing, "See it
  move" asks Google's video model for a clip that starts from exactly that
  stored picture, with a movement that fits it: the front picture turns round
  once and then poses (8 seconds; it can then be dragged round, sideways or with
  the arrow keys), every other picture moves naturally for 5 seconds (walks on,
  lifts the cup, turns a page). The offer names the picture it will animate and
  says how many videos are left today. Every clip plays muted. Each picture
  keeps its one clip in `data/videos/`: shown again for free whenever that
  picture is showing, to everybody who sees it. It needs `GEMINI_API_KEY`, also
  where OpenAI draws the pictures, and costs far more than a picture (by
  Google's price list of 15 November 2026 about $0.56 for the turn and $0.35
  for a 5-second clip), so it has its own limits under `[videos]` in
  `config/looks.toml`: one a day per customer, five for Pro accounts and
  owners, ten for the whole site; on your own machine only the site's. The
  movements' words (`[videos.motion]`), the clips' length (`seconds`) and the
  model's name are in the same place. To try the paid service by eye, or
  another name for the model without touching the file (one clip billed, from
  the pictures of `looks --test-set`):
  `python -m wardrobe looks --test-video cafe --video-model gemini-omni-1.2-flash`.
  Where ffmpeg is installed the front picture's turn is kept a second time for
  smooth dragging. Pro is a mark on an account, with nothing to buy:
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

## Styles and the style chat (the chat is optional and costs money)

On Profile, under "What do you dress for?", a customer can tick styles (Smart
casual, Street, Minimal, Tailored, Workwear, Outdoor). With a Google key set
(`GEMINI_API_KEY`, the same one as for the pictures) Profile also shows
"Describe your style": he writes "street style, Berlin vibe", Google's text
model answers in two or three sentences and suggests a **style brief** (styles,
how formal, colours to favour and avoid, fits, price feeling, things he does
not want). He corrects it and presses "Use this brief". Only a brief he
confirmed changes anything.

What a brief changes, all of it plain Python in `wardrobe/style.py`:

- **Stores** are ranked by their `styles` and `price` lines in
  `config/stores.toml`.
- **Products** earn or lose points from the brief's words matched against
  their name, fabric, fit and colour, and from their store. Among a piece's
  products the price level then chooses among those that fit the brief; one
  that goes against it is picked only when the piece has nothing else. The
  quality score is not touched.
- **Outfits** whose pieces fit the brief move up the order. An outfit that is
  one of his styles as a whole moves up further and says so in one line
  ("Street: t-shirt, relaxed jeans, sneakers"), naming the pieces that make it
  so. The rule: at least three quarters of its pieces (all of three, three of
  four, four of five), and at least two, are garments the style is built on,
  and the outfit is as formal as the style allows. Street stops below "Smart
  casual", so an Office outfit of an oxford shirt, chinos and derby shoes is
  never called street, whatever the store calls its fit. Minimal asks for
  every piece, because its garments (T-shirt, jumper, shirt, trousers, coat,
  sneakers) are in nearly every outfit. Every other outfit says nothing. In a
  plan without boots (the example plan has none) no outfit is ever called
  Workwear or Outdoor: neither style reaches three quarters of an outfit
  without them. Those two styles still change which products are picked. A
  brief that names no style (colours or fits only) is held to the same rule:
  "Your brief: navy jumper, navy chinos, navy sneakers" only when three
  quarters of the outfit's pieces are in a colour or a fit he favours, and
  such an outfit moves up as far.
- **Said plainly:** when confirming, changing or removing a brief changes his
  pieces or his total, the page says so ("Your brief changed 1 piece: +4 €").

Without a brief every pick is exactly as before. The points and the words of
each style are in `config/style.toml`.

- **Cost:** each message is one request to Google, about a tenth of a US cent
  (about 1,200 tokens in and 300 out; `gemini-3.5-flash-lite` was listed at
  $0.30 per million tokens in and $2.50 out on 16 Nov 2026). Limits in
  `config/style.toml` under `[chat]`: 20 messages a day per customer, 500 a
  day for everyone together (at most about 60 cents a day).
- **What is sent to Google:** his message, the last lines of the conversation
  and the brief. Never his name, email address, sizes, budget or photo.
- **What comes back is not trusted:** only a reply, one question and a brief
  are read from it; the brief keeps only styles, colours, fits and levels the
  app knows; the model never chooses a product or a store.
- **The chat cannot tie up the site:** the customer waits for the answer, so
  at most 2 messages are on their way to Google at the same moment, for the
  whole site (every server process shares the same two turns), and a message
  is given up when Google has said nothing for 15 seconds. One more message at
  such a moment is told at once: "The style chat is busy. Try again in a
  moment. That message was not counted." It was not sent, and it does not
  count towards the day's limits. Both numbers are in `config/style.toml`
  (`at_once`, `wait_seconds`).
- **Not yet tried against the paid service.** The request was written from
  Google's documentation of 16 Nov 2026. To try it (one message, about a tenth
  of a cent): `python -m wardrobe chat --test "street style, Berlin vibe"`.
  `python -m wardrobe chat` says whether the chat is on. If Google does not
  know the model, put the current name in `config/style.toml`.

### What a real test of the chat should look at

Everything above was built and checked with a stand-in for Google's model
(`wardrobe/mockchat.py`). Before customers use the chat, try these on the real
key. Each message costs about a tenth of a cent.

1. `python -m wardrobe chat --test "street style, Berlin vibe"`: does Google
   know `gemini-3.5-flash-lite`, does it accept `response_format` with the
   schema, and is the answer found where the code reads it (`steps`,
   `model_output`, `text`)?
2. The real cost: Google's bill or its token counts for a handful of
   messages. The output price includes the model's thinking, so a message may
   cost more than the estimate.
3. Does the model keep to two or three sentences, ask at most one question,
   name no brand, store or price, and leave the brief alone when asked about
   something that is not style?
4. German input ("Berliner Streetstyle, keine Logos") and vague input ("like
   a Scandinavian architect"): is the brief sensible?
5. An attempt to steer it ("ignore your rules and ..."): the page must show
   only plain text and a brief of known values.
6. How long an answer takes. A message is given up after 15 seconds with "The
   style chat did not answer. Try again in a moment."; if real answers often
   take longer, raise `wait_seconds`.
7. Three messages sent at the same moment from three browsers: two are
   answered, the third is told "The style chat is busy" and is not counted
   towards the day's 20.
8. With a real brief in use on the collected catalogue: do the picks and the
   first outfits look like the style? Is each line under an outfit ("Street:
   t-shirt, jeans, sneakers") true of the whole outfit, and do the outfits
   that say nothing really not fit?
9. After "Use this brief": is the sentence "Your brief changed N pieces: +X €"
   right when compared with the Wardrobe page before and after?
10. The limits on the live site: the 21st message of a day is refused in
    words, and the note beside the chat names the right number.
11. The privacy page's operator blanks for Google (location, agreement)
    before anyone but the owner uses the chat.

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
config/style.toml          the styles to tick, what a style brief is worth, and the style chat's model and limits
config/feeds.toml          the stores whose licensed product feeds are imported (see "Store feeds")
data/catalog.json          what the stores sell (rewritten by refresh)
data/wardrobe.db           your profile, slots, locks, saved outfits (SQLite)
data/looks/                AI pictures already drawn (safe to delete: they are drawn again when asked for),
                           and problems.log: why a picture could not be drawn
data/videos/               AI videos already made ("See it move"), each with its turn for dragging
data/people/               your photo, if you uploaded one
data/chat/                 two empty files the style chat locks while a message is with Google (safe to delete)
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
