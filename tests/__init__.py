"""Tests run against a throwaway data folder, never your real data/.

    python -m unittest          (from the project folder, with the venv active)
"""
import atexit
import os
import shutil
import tempfile

_tmp = tempfile.mkdtemp(prefix="capsule-tests-")
os.environ["WARDROBE_DATA_DIR"] = _tmp
# The collection addresses kept on this computer (config/collect.local.toml) are never read by the tests: they run
# the same here as on GitHub, where that file does not exist. A test that needs one names its own.
os.environ["WARDROBE_COLLECT_LOCAL"] = ""
for _name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(_name, None)      # a real key in your shell must never make the tests call a paid service
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)
