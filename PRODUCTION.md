# Stilsmith as a public service

**Status: foundation, not launch-ready.** The app can now run for many
customers, each with their own account and data. What it cannot yet do is show
those customers real products: see "Before customers" below.

## Two ways to run the same code

| | Local (default) | Production |
| --- | --- | --- |
| Start | `python -m wardrobe` | `gunicorn wardrobe.wsgi:app` with `CAPSULE_ENV=production` |
| Users | one implicit user, no login | accounts; every row belongs to one customer |
| Store data | the collector (`refresh`) | **no collector**; a shared store catalogue you publish, or demo data if there is none |
| Protection | same-origin check | CSRF tokens, secure cookies, security headers, login throttling |
| AI pictures | your key, your limit (`per_day`) | your key, a limit per customer and per day, shared between customers |

Your own data from before accounts existed is carried over automatically the
first time the new version starts (a copy is kept as
`data/wardrobe.db.before-accounts`).

## Try production mode on this machine

```bash
source .venv/bin/activate
export CAPSULE_ENV=production
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export SITE_URL=http://127.0.0.1:8000
export WARDROBE_DATA_DIR=./data-production      # keep it apart from your own data
export GEMINI_API_KEY="…"                       # optional: AI pictures of outfits (Google: config/looks.toml)
gunicorn --workers 2 --threads 4 --bind 127.0.0.1:8000 wardrobe.wsgi:app
```

The start-up lines say whether the AI pictures are on. Without a key they are
off and customers see no trace of them: the Outfits page shows the product
photos instead.

Open <http://127.0.0.1:8000>: you get the outfits of the example wardrobe, as a
visitor does (or, with `guests = false` in `config/site.toml`, the public landing
page); create an account to reach the app. Password-reset emails are not sent without `SMTP_URL`.

Customers see invented demo items until the service has a store catalogue. To
give it the products your last refresh collected, run this in a second terminal
(without `CAPSULE_ENV` set):

```bash
python -m wardrobe publish ./data-production
```

It writes `store_catalog.json` into that folder. Each customer's slots are then
matched against it by garment type and colour, from their next page load. Only
the garment types and colours your own capsule collected are in it; a customer's
slot in another colour stays empty.

## Settings

All through environment variables (documented in `wardrobe/settings.py`).

| Variable | Needed | Meaning |
| --- | --- | --- |
| `CAPSULE_ENV` | yes | `production` |
| `SECRET_KEY` | yes | at least 32 random characters; signs the login cookie. Changing it logs everyone out |
| `SITE_URL` | yes | public address, e.g. `https://stilsmith.example`. With `https://` the cookie is marked Secure |
| `WARDROBE_DATA_DIR` | yes | folder for the database, on a disk that survives restarts |
| `TRUSTED_PROXY_HOPS` | usually `1` | number of reverse proxies in front, so addresses and https are read correctly |
| `SMTP_URL`, `MAIL_FROM` | for resets | `smtp://user:password@host:587` (or `smtps://…:465`) |
| `SESSION_DAYS` | no | how long a login lasts (default 30) |
| `INVITE_CODE` | while the service is not open to everyone | if set (8 characters or more), creating an account needs this code. Give it out as `<SITE_URL>/signup?code=<the code>`. Wrong codes count against the sign-up limit per connection |
| `GEMINI_API_KEY` | for AI pictures | Google's key; every picture is billed to it. Only the service named under `[service]` in `config/looks.toml` draws (Google; `OPENAI_API_KEY` counts only with `use = "openai"` there). Model and limits: the same file |

## Deploying

The planned set-up is one small server in the EU running the app in a
container, with Cloudflare in front for the domain, HTTPS and a Tunnel:
[deploy/README.md](deploy/README.md) has the steps, and why Cloudflare cannot
run the app by itself. Any other host that can run a container with a
persistent disk and TLS in front will do as well.

The `Dockerfile` and `deploy/compose.yaml` were written without Docker to hand.
The GitHub checks build the image and start it on every push, which is the
only place they have run. The Tunnel has never been started.

- **Database:** one SQLite file in WAL mode. That is deliberate: nothing else to
  run, and it comfortably serves a small service on one machine. It rules out
  running several machines at once. Move to PostgreSQL when you need a second
  machine or see lock waits; the SQL is in one file (`wardrobe/db.py`).
- **Backups:** `sqlite3 "$WARDROBE_DATA_DIR/wardrobe.db" ".backup '/backups/capsule-$(date +%F).db'"`
  on a schedule, copied off the machine. Not set up.
- **Health check:** `GET /healthz`.
- **If workers keep dying:** gunicorn starts a new worker for every one that
  dies, without limit. When something kills each worker as it starts, that is a
  loop of several a second: on 2026-11-11 a reload on a Mac went through 3,485
  workers in five minutes. [gunicorn.conf.py](gunicorn.conf.py), which gunicorn
  reads by itself when it is started from this folder, stops the service after
  a handful of workers have died within seconds of starting, and says why in
  its last lines. It also switches off gunicorn's control socket, which the
  service does not use and which is what made that reload fatal on macOS.
- **After changing the code:** `kill -HUP <the pid gunicorn prints first>`
  starts fresh workers and retires the old ones without dropping requests.
  Settings typed into the terminal (a key, `SITE_URL`) need a stop and a start
  instead.

## Logs: what is written down, and for how long

On the server (`deploy/compose.yaml`) Docker keeps what each container prints:

- **The app's access log**, one line per request (`gunicorn.conf.py`): the
  time, the method and the path (without the `?…` part), the status, the size
  of the answer, how long it took, and the browser's name for itself (its user
  agent). For example:
  `[19/Nov/2026:10:15:02 +0000] "GET /outfits" 200 48213 87ms "Mozilla/5.0 (iPhone; …)"`.
  Not in it: the visitor's network (IP) address, the name typed into the
  browser's password box while `SITE_PASSWORD` is set, the `?…` part of the
  address (an invitation code can be in it), and the page the visitor came
  from. The path is kept, so the line of a visit to a password-reset link
  (`/reset/…`) holds that link's one-time code.
- **The app's own lines:** what is on and off when it starts; each AI picture
  or video drawn or not drawn, by its key, with the service's own words when
  it failed; a settings or program error, with the method and path and
  Python's account of the error; and, while `SMTP_URL` is not set, the email
  address a password-reset email could not be sent to (never the link).
- **gunicorn's own lines:** starting, stopping, its workers, and a request it
  could not read, with the address that request came from. Behind the tunnel
  that is the tunnel container's address, not the visitor's.
- **The tunnel's lines** (cloudflared, at its default level, `info`).
  Cloudflare's documentation says its `debug` level writes each request's URL,
  method and all its headers, and Cloudflare puts the visitor's network address
  into a header: do not run it at that level on the server.

**How long.** Docker writes each container's log into files of at most 1 MB
and keeps at most three of them: when the newest is full, a new one is started
and the oldest is deleted. So at most about 3 MB per container. A restart keeps
the log; replacing the container (`up -d --build` after the code has changed)
deletes it. Docker deletes by size, not by age, so how many days that is depends
on how busy the site is: one access line takes 250 to 300 bytes as Docker stores
it, so 3 MB is roughly 10,000 requests. To read them:
`docker compose -f deploy/compose.yaml logs app`.

**Also kept, in the data folder** (on the volume, so it outlives the
container): `looks/problems.log`, one line for each AI picture or
video that failed (the time, the kind of problem, the service and model, the
picture's key and the service's words). At 512 KB it becomes
`looks/problems.old.log`, in place of the one before: at most about 1 MB.

On your own machine gunicorn writes no access log unless you ask it to
(`--access-logfile`), and `python -m wardrobe` writes no line per request.

## The example wardrobe's pictures

Visitors without an account see an outfit's AI picture only where one has been
drawn already, and they never cause one to be drawn. To draw them, run this by
hand where the service runs. On the server, put
`docker compose -f deploy/compose.yaml exec app` in front of each line
([deploy/README.md](deploy/README.md)):

```bash
python -m wardrobe example-pictures                      # says what it would draw and cost; draws nothing
python -m wardrobe example-pictures --sample 3 --yes     # draws the first 3 that are missing, to look at them first
python -m wardrobe example-pictures --yes                # draws the rest of the first 12
python -m wardrobe example-pictures --clips 3            # ... and says what the clips of the first 3 would cost
python -m wardrobe example-pictures --clips 3 --max-cost 3 --yes    # makes them
```

- It looks at the example wardrobe's first 12 outfits in the order a visitor
  sees them (one page). `--outfits 24` also takes the 12 that "Show more
  outfits" adds.
- It first says how many already have their picture, how many it would draw,
  and what that would cost. The cost is an estimate: `price_each_usd` in
  `config/looks.toml`, 5 US cents a picture, rounded up from Google's price list.
- Without `--yes` it draws nothing.
- If the estimate is above `--max-cost` it draws nothing. That ceiling is 1.00
  US dollar unless you give another.
- It draws one picture at a time and waits for each. Each is of Stilsmith's
  house model, never of anyone's photo, and it shows on the site as soon as it
  is drawn.
- At the end it says what it drew, what failed and why, and what was spent by
  its estimate.
- Each picture is billed to the key, like any other. They do not count against
  the day's limits in `config/looks.toml`: `--max-cost` is this command's limit.
- Running it again draws only what is still missing.
- It refuses, with one line saying why, while AI pictures are off, and on your
  own machine, which has no example wardrobe.
- `--clips K` also makes a 5-second clip of each of the first K outfits, from
  its front picture: a visitor sees it in place of the picture, muted and
  looping, labelled "AI video" (only the outfit on screen plays; with less
  motion asked for, the picture stays, with a button to play it). The movement
  is `example` under `[videos.motion]` in `config/looks.toml`: a slight turn
  and back, so the cut and the drape show from the side, the feet stay put (the
  dots stay on the pieces) and the loop does not jump. The clips are in the same
  estimate (`price_per_second_usd` under `[videos]`, 10 US cents a second, so
  about 50 cents a clip), under the same `--max-cost` and `--yes`, outside the
  day's video limits, and again only what is missing. The pictures are drawn
  first, as each clip is made from one. It refuses, in one line, while AI videos
  are off.
- The example wardrobe is planned for its own budget, `example_budget` in
  `config/site.toml` (600 €: everyday and the office, at "Best for budget").
  Changing it replans the example at the next start, so its outfits change:
  run this command again, as the pictures drawn before show other outfits.
  (An outfit of the very same products as one drawn before keeps its picture:
  a picture is named by the outfit's whole description.)

## What is in place

- Accounts: sign-up, log-in, log-out, password reset by emailed one-hour link,
  password change that signs out other devices.
- Passwords stored only as salted scrypt hashes. Wrong-password attempts are
  limited per address and per connection; sign-ups per connection per hour.
- Each customer's profile, slots, choices, saved outfits and added items are
  separate; the database layer refuses to run a query without a signed-in user.
- A copy of your data (JSON) and account deletion, on the Account page.
- CSRF token on every form and HTMX request; session cookie HttpOnly,
  SameSite=Lax, Secure on https; Content-Security-Policy and related headers;
  plain error pages; no stack traces to visitors.
- Public pages: what Stilsmith is (`/about`, the words of the landing page
  there was; linked from a visitor's header and from the foot of every page),
  installable on a phone's home screen, and pages for Impressum, privacy policy
  and terms **that are placeholders**. While no product list is published
  `/about` says the products are invented examples, and names no store.
- Visitors without an account (`guests = true` in `config/site.toml`, the
  default; `false` closes the door again, and `/` is the landing page again):
  the home page, `/`, is the outfits of one example wardrobe, the same for every
  visitor (`wardrobe/guests.py`), with a title and a description for search
  results in its own numbers. On his first three outfits a hint each says what
  the example is, in its own numbers (in the form "12 pieces from 2 stores,
  combined into 84 outfits": no price, no budget, no store's name), that a piece can be tapped (swapping it needs an
  account), and what the picture is; each can be put away, and nothing of that
  is stored, so they come back on the next visit. Each piece shows its name and colour, drawn by the app;
  an outfit's AI picture shows only where one was drawn already (a visitor never
  causes a drawing), and the outfits that have one come first. "The example
  wardrobe's pictures" below says how to draw them. Stores, prices,
  sizes, links and the stores' photos are left out of those pages on the server,
  and every button leads to "Create your account". The example wardrobe is an
  account Stilsmith makes for itself at start-up
  (`example-wardrobe@stilsmith.invalid`, no password: nobody can log in to it);
  a visitor reads it with the database read-only, so nothing he does is stored
  and no cookie is set. A newly published product list reaches it at the next
  restart. SITE_PASSWORD still comes first.
- Partner links said to be partner links: from the day a real store is marked
  `approved` (config/feeds.toml, then `python -m wardrobe stores sync`), the foot
  of every page says "Partner links: Stilsmith may earn a commission when you buy
  at …. You pay the same." in place of "Not affiliated with any retailer", and
  the shopping list and Buy this outfit say it under the stores' links, with
  that the commission does not change which product is picked for a piece.
- AI pictures of outfits, if a key is set (see the README for what they are):
  - Spending is capped in `config/looks.toml`: `per_customer_per_day` and
    `per_day` for the whole service. A picture that shows no real person is
    drawn once and shared by every customer who asks for the same outfit.
    The front picture is drawn for every outfit looked at; "More photos" and
    "See it move" only for outfits the customer added to his wardrobe
    (`more_only_on_yes` in `config/looks.toml`; owners and Pro accounts are
    not held to it), and the server refuses them otherwise.
  - Only the stores' own words, the menu choices and the customer's body in
    words reach the image service. The body is the height, weight, chest and
    waist from Profile turned into a few words ("a little shorter than
    average, lean build"), never the numbers, and only once the customer has
    entered his own (`wardrobe/person.py`, "the body from Profile"). Anything
    a customer typed (slot names, links, items added by hand) is left out of
    the description.
  - A customer may upload a photo of themselves after ticking a consent box.
    Only the picture is stored (what a phone writes into the file about place,
    time and device is cut out), under their account. It is sent to the image
    service with each picture, visible to nobody else, and deleted with the
    pictures made from it when they remove it or delete the account.
    `photos = false` in `config/looks.toml` switches uploads off; photos
    already stored can still be deleted by their owners.
  - What counts against the limits: every picture asked for, unless the
    service certainly did nothing with the request. Deleting an account does
    not give its pictures back to the day's total, and "Try again" on a
    picture the service refuses stops at the customer's allowance.
  - A photo the image service cannot use is that customer's failure: it does
    not pause pictures for everybody else.
  - Videos of outfits ("See it move", with `GEMINI_API_KEY`): `[videos]` in
    `config/looks.toml` caps them apart from the pictures, at one a day per
    customer, five for Pro accounts (`python -m wardrobe pro add EMAIL`) and
    owners, and ten for the whole service. Each of an outfit's pictures has
    its own clip (the front one's 8-second turn, 5 seconds for the others),
    and each clip counts as one video. A video of a picture drawn from a
    customer's photo is shown only to them and deleted with the photo and the
    account. The container installs ffmpeg for smooth dragging.
  - When the service refuses for a reason only you can fix (key, credit,
    model name), customers read "Pictures are not available at the moment".
    The reason is in the server log and in `looks/problems.log` in the data
    folder. While `SITE_URL` still points at this machine (a trial, no outside
    customers) the reason is shown on the page too.
  - After such a failure each worker leaves the image service alone for five
    minutes, so a broken key is not tried again for every outfit a customer
    opens. A restart clears it. Requests that fail are not counted against
    anyone's daily allowance.
  - Pictures are drawn in the background by the web workers themselves, two at
    a time per worker. That is fine for a small service; a busy one wants a
    proper job queue.

## Before customers

These block a launch, and most are yours rather than code:

1. **A product data source you have the right to use.** The collector reads the
   stores from your own Chrome; it cannot run on a server (the stores refuse
   it) and republishing their products and pictures commercially needs their
   agreement. The usual route is the retailers' affiliate programmes, which
   provide product feeds with prices, pictures and links. As of November 2026:
   - **COS** runs one through the Rakuten network, covering Germany, with
     product feeds (<https://www.cos.com/en-ch/affiliates>). You join Rakuten
     first, then apply to COS.
   - **Weekday** offers data feeds in EUR, by applying directly or through the
     Klarna Creator Platform or LTK (<https://www.weekday.com/en-dk/discount/affiliate>).
   - **Zara**: no feed open to a service like this was found, so Stilsmith does
     not offer it (`programme = "none"` in `config/stores.toml`; its products in
     an older `store_catalog.json` are skipped, and customers who had them get
     their pieces picked again, with one message on the Wardrobe page).

   Before building on a feed, get its terms in writing: does it list which
   sizes are in stock, and the fabric? May the pictures be shown, stored, or
   used to make other pictures? How old may the data be when shown? The app
   already says "check that your size is in stock" where a store gives no
   sizes, and shows when prices and stock were last read; a feed that is hours
   old needs the same honesty. The alternative to feeds is customers adding
   their own items, with no shared catalogue. `publish` makes the service show what you
   collected, which is fine for trying it on your own machine and is exactly
   what must not go public without that agreement.
2. **Legal pages.** Impressum, privacy policy and terms need your business
   details and a lawyer's text. `/legal/privacy` lists what the service really
   stores, as a starting point. Also have the use of the retailers' names
   checked.
3. **Email.** An SMTP provider for password resets. Confirming a new address by
   email is not built.
4. **Hosting.** A host in the EU, a domain, TLS, backups and monitoring.
5. **Language.** The interface is English; German customers will expect German.
6. **AI pictures, if you offer them.** Decide these before customers use them:
   - *Cost.* Each picture is billed to your key, and by default one is drawn
     whenever a customer looks at an outfit (`auto` in `config/looks.toml`).
     The five further photos and the videos cost more and are offered only on
     the outfits he said yes to (`more_only_on_yes`). Set the limits to what you
     are willing to pay per day.
   - *The style chat.* It comes on with the Gemini key the pictures need, and it
     has a switch of its own: `on` under `[chat]` in `config/style.toml`, whose
     comment says why it may have to be off on a public site (a data protection
     officer). `python -m wardrobe chat` says whether it is on, and if not, why.
   - *Customers' photos.* A face photo is personal data of a sensitive kind.
     Offering the upload needs the image service named in the privacy policy,
     a data-processing agreement with it, and a lawyer's look at the consent
     wording (the box in the app is a starting point, not legal text). Until
     then, set `photos = false`.
   - *Labelling.* Every picture is captioned "AI picture". Have it checked
     whether that meets the EU's transparency rules for AI-generated images.
   - *The first real picture.* The connection to OpenAI and Google is written
     from their documentation and has been run only up to the point where a
     key is needed. Run `python -m wardrobe looks --test` with your key before
     customers see the feature.

## Not built yet

- An importer for a licensed product feed. The shared catalogue it would fill
  exists (`store_catalog.json`, see `wardrobe/shared.py`); today only `publish`
  writes it, and only for the colours of your own capsule. It is not written
  ahead of time because each network's feed has its own columns: build it
  against the first real feed file.
- A lawyer's wording, in German, for the partner-link notice (see "What is in
  place"), and whether each link needs a mark of its own. Commission is kept out
  of the ranking today (nothing that picks a product reads a programme's status);
  keep it that way, as the notice says so.
- Choosing *which* pieces to buy. "Best for budget" picks the product for each
  slot; the slots themselves still come from the profile. A wardrobe that also
  drops or adds slots to get the most outfits per euro is the next step in
  that direction.
- Email verification, an admin view, usage limits beyond log-in and sign-up.
- Automated deployment, error alerting, a load test, an accessibility review.
- Native iOS/Android apps. The site installs to the home screen instead.
- One checkout for a whole outfit. The stores offer no way to fill their
  baskets or pay from outside; "Buy this outfit" opens their product pages.
  Selling an outfit in one payment means becoming the seller (stock or
  agreements with the stores, payments, returns), which is a business decision
  before it is code.
- Clothes in the AI pictures that are the actual products. The pictures are
  drawn from descriptions; using the stores' product photos as the source
  needs their permission, like the product data itself.
