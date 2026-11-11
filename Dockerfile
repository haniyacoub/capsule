# The public service: the app in production mode behind gunicorn.
# Built and started by the GitHub checks on every push. It has not yet run on a real server.
#
#   docker build -t capsule .
#   docker run -p 8000:8000 -v capsule-data:/data \
#     -e SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
#     -e SITE_URL=https://your-domain.example -e TRUSTED_PROXY_HOPS=1 capsule
#
# Optional, for the AI pictures of outfits: add  -e OPENAI_API_KEY=…  (or GEMINI_API_KEY).
# The pictures and customers' photos are kept on the same volume, under /data/looks and /data/people.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    CAPSULE_ENV=production WARDROBE_DATA_DIR=/data

WORKDIR /app
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY wardrobe ./wardrobe
COPY config ./config
# gunicorn reads this by itself from the folder it starts in: stop if workers keep dying, no control socket.
COPY gunicorn.conf.py .

# The database lives on a volume, owned by an unprivileged user.
RUN useradd --system --uid 10001 capsule && mkdir /data && chown capsule /data
USER capsule
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

# One machine, one SQLite file: a couple of workers with threads is plenty.
CMD ["gunicorn", "--workers", "2", "--threads", "4", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "wardrobe.wsgi:app"]
