"""Tests run against a throwaway data folder, never your real data/.

    python -m unittest          (from the project folder, with the venv active)
"""
import atexit
import os
import shutil
import tempfile

_tmp = tempfile.mkdtemp(prefix="capsule-tests-")
os.environ["WARDROBE_DATA_DIR"] = _tmp
for _name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(_name, None)      # a real key in your shell must never make the tests call a paid service
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)
