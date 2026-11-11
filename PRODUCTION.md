# Capsule as a public service

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
export OPENAI_API_KEY="sk-…"                    # optional: AI pictures of outfits (or GEMINI_API_KEY)
gunicorn --workers 2 --threads 4 --bind 127.0.0.1:8000 wardrobe.wsgi:app
```

The start-up lines say whether the AI pictures are on. Without a key they are
off and customers see no trace of them: the Outfits page shows the product
photos instead.

Open <http://127.0.0.1:8000>: you get the public landing page; create an account
to reach the app. Password-reset emails are not sent without `SMTP_URL`.

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
| `SITE_URL` | yes | public address, e.g. `https://capsule.example`. With `https://` the cookie is marked Secure |
| `WARDROBE_DATA_DIR` | yes | folder for the database, on a disk that survives restarts |
| `TRUSTED_PROXY_HOPS` | usually `1` | number of reverse proxies in front, so addresses and https are read correctly |
| `SMTP_URL`, `MAIL_FROM` | for resets | `smtp://user:password@host:587` (or `smtps://…:465`) |
| `SESSION_DAYS` | no | how long a login lasts (default 30) |
| `OPENAI_API_KEY` or `GEMINI_API_KEY` | for AI pictures | the image service's key; every picture is billed to it. Which service, model and limits: `config/looks.toml` |

## Deploying

The planned set-up is one small server in the EU running the app in a
container, with Cloudflare in front for the domain, HTTPS and a Tunnel:
[deploy/README.md](deploy/README.md) has the steps, and why Cloudflare cannot
run the app by itself. Any other host that can run a container with a
persistent disk and TLS in front will do as well.

The `Dockerfile` and `deploy/compose.yaml` were written without Docker to hand.
The GitHub checks build the image and start it on every push, which is the
only place they have run.

- **Database:** one SQLite file in WAL mode. That is deliberate: nothing else to
  run, and it comfortably serves a small service on one machine. It rules out
  running several machines at once. Move to PostgreSQL when you need a second
  machine or see lock waits; the SQL is in one file (`wardrobe/db.py`).
- **Backups:** `sqlite3 "$WARDROBE_DATA_DIR/wardrobe.db" ".backup '/backups/capsule-$(date +%F).db'"`
  on a schedule, copied off the machine. Not set up.
- **Health check:** `GET /healthz`.

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
- Public landing page, installable on a phone's home screen, and pages for
  Impressum, privacy policy and terms **that are placeholders**.
- AI pictures of outfits, if a key is set (see the README for what they are):
  - Spending is capped in `config/looks.toml`: `per_customer_per_day` and
    `per_day` for the whole service. A picture that shows no real person is
    drawn once and shared by every customer who asks for the same outfit.
  - Only the stores' own words and the menu choices reach the image service.
    Anything a customer typed (slot names, links, items added by hand) is left
    out of the description.
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
   - **Zara**: no feed open to a service like this was found. Do not plan the
     launch around it.

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
     Set the two limits to what you are willing to pay per day.
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
- Telling customers that links may earn a commission, once they do (required
  for affiliate links in Germany), and keeping commission out of the ranking.
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
