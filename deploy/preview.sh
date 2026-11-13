#!/bin/sh
# Stilsmith on the internet from this computer, through a temporary Cloudflare tunnel.
#
#   ./deploy/preview.sh
#
# Run it in the Terminal window the service was started in, after stopping the service there
# with Ctrl+C: it needs the same settings (CAPSULE_ENV, SECRET_KEY, WARDROBE_DATA_DIR, and the
# image service's key if you use one). It
#
#   1. opens a tunnel (cloudflared: free, no account) and reads the address Cloudflare gives it,
#   2. starts the service for that address, by invitation: you log in as always, and only
#      people who have the link it prints can create an account,
#   3. stops both when you press Ctrl+C. The address is gone then; the next run gets a new one.
#
# It is for showing Stilsmith to someone or trying it on your phone. It is not a place for
# customers: it runs on this computer, and only while this window is open.
#
# PORT=8000 is used unless you set another.
set -eu
cd "$(dirname "$0")/.."

stop() { printf '\n%s\n' "$*" >&2; exit 1; }

PORT="${PORT:-8000}"
if [ -x .venv/bin/gunicorn ]; then GUNICORN=.venv/bin/gunicorn PYTHON=.venv/bin/python
else GUNICORN="$(command -v gunicorn || true)" PYTHON="$(command -v python3 || true)"; fi

command -v cloudflared >/dev/null 2>&1 \
    || stop "cloudflared is not installed. Install it with:  brew install cloudflared"
[ -n "$GUNICORN" ] && [ -n "$PYTHON" ] \
    || stop "gunicorn was not found. Once:  pip install -r requirements-prod.txt  (inside the project's .venv)"
[ "${CAPSULE_ENV:-}" = "production" ] && [ -n "${SECRET_KEY:-}" ] && [ -n "${WARDROBE_DATA_DIR:-}" ] \
    || stop "The service's settings are not set in this window (CAPSULE_ENV, SECRET_KEY, WARDROBE_DATA_DIR).
Run this in the Terminal window the service was started in, or set them first:
PRODUCTION.md, \"Try production mode on this machine\"."
"$PYTHON" -c 'import socket, sys; sys.exit(socket.socket().connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0)' "$PORT" \
    || stop "Something is already answering on port $PORT. Stop the service first (Ctrl+C in its window), then run this again."

log="$(mktemp "${TMPDIR:-/tmp}/capsule-tunnel.XXXXXX")"
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" > "$log" 2>&1 &
tunnel=$!
trap 'kill "$tunnel" 2>/dev/null || true; rm -f "$log"' EXIT
trap 'exit 130' INT TERM

printf 'Asking Cloudflare for an address'
url=""
tries=0
while [ "$tries" -lt 80 ]; do                      # up to 40 seconds
    url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" | grep -vE '//(api|login)\.' | head -n 1 || true)"
    [ -n "$url" ] && break
    kill -0 "$tunnel" 2>/dev/null || break         # cloudflared gave up
    sleep 0.5
    tries=$((tries + 1))
    printf '.'
done
printf '\n'
if [ -z "$url" ]; then
    printf '\nWhat cloudflared said:\n' >&2
    tail -n 15 "$log" >&2
    stop "Cloudflare did not give an address. The lines above are cloudflared's own; nothing was started."
fi

code="${INVITE_CODE:-$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(9))')}"
name="$("$PYTHON" -c 'from wardrobe.settings import SITE_NAME; print(SITE_NAME)')"     # the product's name (settings.py)

cat <<EOF

$name is on the internet for as long as this window stays open:

    $url

You: open that address and log in as always. (It can take half a minute to answer the first time.)
Someone you invite: send them this link. It carries the invitation code, and nobody without it
can create an account:

    $url/signup?code=$code

Pictures a guest draws are billed to your key, within the limits in config/looks.toml.
Press Ctrl+C to stop. The address is gone then.

EOF

SITE_URL="$url" TRUSTED_PROXY_HOPS=1 INVITE_CODE="$code" \
    "$GUNICORN" --workers 2 --threads 4 --bind "127.0.0.1:$PORT" wardrobe.wsgi:app
