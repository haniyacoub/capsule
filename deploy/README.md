# Putting Stilsmith on the internet, behind Cloudflare

## What Cloudflare is for here

Cloudflare cannot run this app by itself. Its own hosting (Workers and Pages)
runs code that has no disk, and its Containers start from a fresh disk every
time they wake up. Stilsmith keeps a database file, the AI pictures and
customers' photos on disk, and draws pictures in the background. Making it fit
would mean rewriting how it stores everything.

What Cloudflare does well for it is everything in front: the domain, HTTPS,
protection against floods of requests, and a **Tunnel** that connects a server
to the internet without that server opening a single port. So the set-up is:

```text
visitor  ->  Cloudflare (your domain, HTTPS)  ->  Tunnel  ->  one small server running the app in a container
```

## What you need

1. A Cloudflare account with your domain on it (bought there or moved there).
2. A Linux server with Docker, **in the EU**: customers' data lives on its disk.
   The smallest size any provider sells is enough to start (1 to 2 GB of memory).

Both cost money and need your name on them, so they are yours to set up.

## Steps

1. **Create the tunnel.** In the Cloudflare dashboard, under Zero Trust, find
   Tunnels (the menus move around) and create one of the "cloudflared" kind.
   Copy its token. Add a public hostname: your domain, service type HTTP,
   address `app:8000`.
2. **Put the code on the server.** The repository is public, so no key is
   needed:

   ```bash
   git clone https://github.com/haniyacoub/capsule.git && cd capsule
   cp deploy/app.env.example deploy/app.env          # then edit: SECRET_KEY, SITE_URL, INVITE_CODE, email, AI key
   cp deploy/tunnel.env.example deploy/tunnel.env    # then paste the tunnel's token
   docker compose -f deploy/compose.yaml up -d --build
   docker compose -f deploy/compose.yaml logs -f app # the first lines say what is on and off
   ```

3. **Open your domain.** You should see the outfits of the example wardrobe (the
   website's own words are at `/about`).
4. **Keep it closed to the public for now.** Until the product data is
   licensed (PRODUCTION.md, "Before customers") the site must not be open to
   everyone. `INVITE_CODE` in `deploy/app.env` does that: the example's outfits
   and `/about` are public, creating an account needs the code, and the link to hand out is
   `https://your-domain/signup?code=<the code>`. The app refuses to start on
   the example's placeholder. To keep the whole site private, every page
   included (a trial before the Impressum and the product data are ready),
   set `SITE_PASSWORD` in `deploy/app.env`: every page then first asks for it.
   For a second lock in front of the whole site, add the hostname under Access
   in Cloudflare Zero Trust and allow only the email addresses you invite.

   **Behind Cloudflare Access nobody needs a second proof.** Cloudflare has
   checked each visitor's email address with a code before a page opens, and
   says whose it is in a signed token on every request. Set `ACCESS_TEAM` and
   `ACCESS_AUD` in `deploy/app.env` (the example file says where each is found)
   and Stilsmith reads that token (`wardrobe/access.py`):

   - Someone you have put on Cloudflare's list opens the site, types the code
     Cloudflare emails him, and on "Create account" finds his address and one
     button: no form, no password. From then on Cloudflare's check opens his
     account.
   - An account with a password stays as it is. The check never opens it.
   - Inviting someone is one step: add the address in Cloudflare (Zero Trust >
     Access controls > Policies, Edit your policy, add it under Include, Save).
   - To make someone an owner before he has an account:
     `docker compose -f deploy/compose.yaml exec app python -m wardrobe owner add EMAIL`.
     The account he makes with the button is an owner from its first page.

   After the restart the app's first lines say `Cloudflare Access: on …`, and
   after the first visitor `the first token was checked and believed`. A line
   `a request's token was not believed (InvalidAudienceError)` means the tag is
   not this application's; nobody is let in or kept out by that, everyone just
   gets the forms with a password. With `SITE_PASSWORD` or `INVITE_CODE` set
   as well, those still ask for what they ask for.
5. **Give it products.** On your own machine, `python -m wardrobe publish
   ./out` writes `out/store_catalog.json`; copy it to the server and into the
   app's data: `docker compose -f deploy/compose.yaml cp store_catalog.json app:/data/`.

## Afterwards

- **A new version:** `git pull && docker compose -f deploy/compose.yaml up -d --build`.
  The data stays: it is on a volume, not in the container.
- **The example wardrobe's pictures** (the AI pictures that visitors without an
  account see; PRODUCTION.md has the details). On the server, in the folder
  with the code:

  ```bash
  docker compose -f deploy/compose.yaml exec app python -m wardrobe example-pictures
  docker compose -f deploy/compose.yaml exec app python -m wardrobe example-pictures --sample 3 --yes
  docker compose -f deploy/compose.yaml exec app python -m wardrobe example-pictures --yes
  docker compose -f deploy/compose.yaml exec app python -m wardrobe example-pictures --clips 3 --max-cost 3
  ```

  - The first line only says how many pictures are there already, how many it
    would draw, and what that would cost. It draws nothing.
  - The second draws three, to look at first.
  - The third draws the rest of the first 12.
  - It runs inside the app's container, so it uses the site's data and the key
    in `deploy/app.env`. Each picture is billed to that key.
  - It draws nothing if its estimate is above `--max-cost` (1.00 US dollar
    unless you give another).
  - Each picture shows on the site as soon as it is drawn.
  - The fourth line says what the clips of the first 3 outfits would cost (about
    50 cents each, in the same estimate as the pictures); with `--yes` it makes
    them, and visitors see them play in place of those pictures.
- **A copy of the database** (not automated yet, and it should be):

  ```bash
  docker compose -f deploy/compose.yaml exec app python -c "import sqlite3; sqlite3.connect('/data/wardrobe.db').backup(sqlite3.connect('/data/backup.db'))"
  docker compose -f deploy/compose.yaml cp app:/data/backup.db ./capsule-$(date +%F).db
  ```

## A preview from your own Mac, without a server, an account or a domain

For showing Stilsmith to someone, or trying it on your phone. Not a place for
customers: it runs on your Mac and only while a Terminal window is open.

In the Terminal window the service runs in, stop it with Ctrl+C, then:

```bash
./deploy/preview.sh
```

It needs `cloudflared` (`brew install cloudflared`; free, and this kind of
tunnel needs no Cloudflare account). The script opens a tunnel, reads the
address Cloudflare gives it (something like
`https://four-random-words.trycloudflare.com`), and starts the service for
that address **by invitation**: you log in as always, and only people who have
the link it prints can create an account. Ctrl+C stops both. The address is
gone then, and the next run gets a new one.

Pictures a guest draws are billed to your key, within the limits in
`config/looks.toml`.

With a Cloudflare account and a domain, the tunnel of step 1 can end on your
Mac instead of a server and keep one address: set its public hostname to
`http://localhost:8000` and run `cloudflared tunnel run --token <the token>`
while the service is running, with `SITE_URL`, `TRUSTED_PROXY_HOPS=1` and
`INVITE_CODE` set as in `deploy/app.env.example`.

## What has and has not been run

Written without Docker or a Cloudflare account to hand. The GitHub checks build
the image and start the `app` service from `compose.yaml` on every push. The
`tunnel` service, the Cloudflare steps and the backup lines above have not been
run by anyone yet: expect to adjust a detail the first time.

`preview.sh` is tested with a stand-in for `cloudflared` that says what the
real one says (`tests/test_preview.py`): the service it starts, the invitation,
the stop. No real tunnel has been opened with it yet, so the first run is the
first time Cloudflare's side is seen.
