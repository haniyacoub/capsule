# Putting Capsule on the internet, behind Cloudflare

## What Cloudflare is for here

Cloudflare cannot run this app by itself. Its own hosting (Workers and Pages)
runs code that has no disk, and its Containers start from a fresh disk every
time they wake up. Capsule keeps a database file, the AI pictures and
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
2. **Put the code on the server.** The repository is private, so give the
   server a read-only deploy key (GitHub: the repository's Settings, Deploy
   keys), then:

   ```bash
   git clone git@github.com:haniyacoub/capsule.git && cd capsule
   cp deploy/app.env.example deploy/app.env          # then edit: SECRET_KEY, SITE_URL, email, AI key
   cp deploy/tunnel.env.example deploy/tunnel.env    # then paste the tunnel's token
   docker compose -f deploy/compose.yaml up -d --build
   docker compose -f deploy/compose.yaml logs -f app # the first lines say what is on and off
   ```

3. **Open your domain.** You should see the landing page.
4. **Keep it closed to the public for now.** In Cloudflare Zero Trust, under
   Access, add the hostname as an application and allow only the email
   addresses you invite. Until the product data is licensed (PRODUCTION.md,
   "Before customers") the site must not be open to everyone.
5. **Give it products.** On your own machine, `python -m wardrobe publish
   ./out` writes `out/store_catalog.json`; copy it to the server and into the
   app's data: `docker compose -f deploy/compose.yaml cp store_catalog.json app:/data/`.

## Afterwards

- **A new version:** `git pull && docker compose -f deploy/compose.yaml up -d --build`.
  The data stays: it is on a volume, not in the container.
- **A copy of the database** (not automated yet, and it should be):

  ```bash
  docker compose -f deploy/compose.yaml exec app python -c "import sqlite3; sqlite3.connect('/data/wardrobe.db').backup(sqlite3.connect('/data/backup.db'))"
  docker compose -f deploy/compose.yaml cp app:/data/backup.db ./capsule-$(date +%F).db
  ```

## A preview from your own Mac, without a server

The same tunnel can end on your Mac instead: install `cloudflared`
(`brew install cloudflared`), set the tunnel's public hostname to
`http://localhost:8000`, and run `cloudflared tunnel run --token <the token>`
while the app is running. The site is then reachable on your domain for as
long as the Mac is on. Good for showing it to someone; not a place for
customers' data. Put Access in front (step 4) first.

## What has and has not been run

Written without Docker or a Cloudflare account to hand. The GitHub checks build
the image and start the `app` service from `compose.yaml` on every push. The
`tunnel` service, the Cloudflare steps and the backup lines above have not been
run by anyone yet: expect to adjust a detail the first time.
