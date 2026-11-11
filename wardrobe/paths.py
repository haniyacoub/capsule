"""Where things live on disk."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

# Tests point this somewhere else so they never touch your real data.
# Always a full path. "./data-production" means the folder beside where the app was started, and
# it has to mean that to everything that reads it: Flask, for one, takes a path that is not full
# as lying inside its own folder, and then cannot find the pictures it is asked to send.
DATA_DIR = Path(os.environ.get("WARDROBE_DATA_DIR") or ROOT / "data").resolve()

CATALOG_PATH = DATA_DIR / "catalog.json"  # what the stores sell (replaced on refresh)
DB_PATH = DATA_DIR / "wardrobe.db"        # what you decided (never touched by refresh)
