"""Where things live on disk."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

# Tests point this somewhere else so they never touch your real data.
DATA_DIR = Path(os.environ.get("WARDROBE_DATA_DIR") or ROOT / "data")

CATALOG_PATH = DATA_DIR / "catalog.json"  # what the stores sell (replaced on refresh)
DB_PATH = DATA_DIR / "wardrobe.db"        # what you decided (never touched by refresh)
