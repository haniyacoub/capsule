#!/bin/sh
# Every check the GitHub workflow runs, on your own machine.
#
#   ./check.sh             lint, types, risky patterns, and the tests with coverage
#   ./check.sh browser     ... and the walk-through in a real browser (tests/browser_check.py)
#   ./check.sh audit       ... and known vulnerabilities in the packages (needs the internet)
#
# First time:
#   source .venv/bin/activate
#   pip install -r requirements.txt -r requirements-dev.txt
#   python -m playwright install chromium        (only for "browser")
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python}"

step() { printf '\n== %s\n' "$1"; }

step "pyflakes: unused names and typos"
"$PY" -m pyflakes wardrobe tests gunicorn.conf.py

step "mypy: types"
"$PY" -m mypy wardrobe

step "bandit: risky patterns"
"$PY" -m bandit -q -c pyproject.toml -r wardrobe gunicorn.conf.py

step "tests, with coverage (expected errors are printed along the way; the verdict is at the end)"
"$PY" -m coverage run -m unittest
"$PY" -m coverage report | tail -n 2

for extra in "$@"; do
    case "$extra" in
        browser)
            step "browser walk-through"
            "$PY" tests/browser_check.py
            ;;
        audit)
            step "pip-audit: known vulnerabilities"
            "$PY" -m pip_audit -r requirements-prod.txt
            ;;
        *)
            echo "Unknown check: $extra (use: browser, audit)"
            exit 2
            ;;
    esac
done

printf '\nAll checks passed.\n'
