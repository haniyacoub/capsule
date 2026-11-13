"""Entry point for a production web server.

    CAPSULE_ENV=production SECRET_KEY=… gunicorn wardrobe.wsgi:app

On your own machine you don't need this: `python -m wardrobe` starts the app.
"""
import logging

from . import looks, settings
from .app import create_app
from .config import ConfigError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
if settings.PRODUCTION and not settings.SMTP_URL:
    logging.getLogger("capsule").warning("SMTP_URL is not set: password-reset emails will not be sent.")

if settings.PRODUCTION and settings.on_this_machine():
    logging.getLogger("capsule").info("SITE_URL points at this machine: treated as a trial run, so when a picture "
                                      "fails the page shows the image service's own words.")
try:
    logging.getLogger("capsule").info("AI pictures of outfits: %s", looks.status()[1])
except ConfigError as problem:
    # For the operator, in the log. Visitors and customers never read it: a page that needs the file shows
    # Capsule's own 500 page, and the log gets the message again.
    logging.getLogger("capsule").error("%s", problem)

app = create_app()
