# Working on Capsule

Capsule builds a men's capsule wardrobe (a small set of clothes that all go together)
from COS and Weekday: a product for each piece at the price level you choose, the
outfits they make, and the shopping list. Only stores with a partner (affiliate)
programme are offered (`programme` in `config/stores.toml`, `wardrobe/programmes.py`);
Zara has none. Python, Flask, SQLite, and Jinja pages with
HTMX (which swaps parts of a page without a reload).

Read more in [README.md](README.md) (what it does, running it on your computer) and
[PRODUCTION.md](PRODUCTION.md) (running it for many customers, with accounts).

Words you will meet: a **slot** is one thing the wardrobe needs, such as "white tee";
a **candidate** is a store product that could fill it. The **price level** (Cheapest to
Top, or "Best for budget") decides which candidate each slot gets. A **lock** is a
choice made by hand, which the level leaves alone, and **Own it** means you have the
piece already, so it costs nothing.

## Getting set up on a Mac

About ten minutes the first time, mostly downloads. You need **Python 3.13 or newer**
(we use 3.14): check with `python3 --version`. The Mac's own Python is 3.9 and cannot
run the app (it stops with "No module named 'tomllib'"). Get a newer one with Homebrew
(`brew install python@3.14`; see <https://brew.sh>) or from python.org. You also need
git; GitHub's `gh` command is handy. The repository is public, so anyone can clone it
(if it is ever private again, you need the owner's invitation first).

```bash
git clone https://github.com/haniyacoub/capsule.git   # seconds (or: gh repo clone haniyacoub/capsule)
cd capsule
python3.14 -m venv .venv                  # seconds; or python3, if it said 3.13 or newer
source .venv/bin/activate                 # again in every new terminal
pip install -r requirements.txt -r requirements-dev.txt   # about a minute
python -m playwright install chromium     # once; a few minutes (about 600 MB on disk)
./check.sh                                # under a minute
./check.sh browser                        # about a minute and a half
python -m wardrobe                        # starts at once; open the address it prints
```

Both checks end with "All checks passed." Ctrl+C stops the app; another port:
`python -m wardrobe serve --port 8123`. `./check.sh` uses `.venv/bin/python` when
there is one, so it works in a terminal where the environment is not active;
`PYTHON=/path/to/python ./check.sh` picks another.
Linux works the same way (the GitHub checks run on Ubuntu; add `--with-deps` to the
Playwright line). Windows has not been tried.

That is **local mode**: one person, no login, so `/signup` and `/login` answer 404.
**Production mode** adds accounts and sign-up: to try it, follow "Try production mode
on this machine" in PRODUCTION.md (`gunicorn` comes with requirements-dev.txt; for
another port, change both `--bind` and `SITE_URL`). Do that in a terminal of its own
and close it afterwards: while those settings are set, `python -m wardrobe` will not
start and many tests fail.

## Store data

- Real store data is not in the repository, and you do not need it. On first start
  the app writes invented **demo data** (**mock** in the code) to `data/catalog.json`,
  and the pages say "Demo data — invented items, not real products, prices or
  stock." Everything works on it. Weekday's demo chinos and leather sneakers have no
  picture on purpose: they show what a page does when a store's picture is missing or
  fails to load. To start again from nothing, stop the app and delete `data/`.
- If you need real products, ask the owner for `store_catalog.json`, sent privately,
  never through GitHub. Only production mode reads it: put it in the trial's data
  folder, `data-production/`. Never commit it or put it online: the products and
  pictures belong to the stores.
- The **collector** reads the stores' pages, and it is the owner's to run. Do not run
  `python -m wardrobe refresh`: it visits the stores. (The "Collect real data with …" line at the bottom of
  the Wardrobe page is meant for the owner.) The rule, in the owner's words:

  > Do not crawl whole catalogues. Go only to the category or search pages relevant to
  > each slot, with slow, polite request rates, using a real browser session
  > (Playwright). Do not try to bypass bot protection or captchas. If a store blocks
  > collection, stop and fall back to a manual import where I paste product URLs and
  > the tool extracts what it can.

- To change how store pages are read, work against the sample pages in
  `tests/fixtures`: `tests/test_collect.py` reads those, never the live sites.

## AI pictures (optional, they cost money)

The Outfits page can show each outfit worn by a model (**looks** in the code), drawn
by OpenAI or Google and billed to whoever owns the key, a few cents a picture.

- The key comes only from an environment variable, `OPENAI_API_KEY` or
  `GEMINI_API_KEY` (`GOOGLE_API_KEY` counts too), set in the terminal you start the
  app from (`export GEMINI_API_KEY="…"`) or in your own `~/.zshrc`. Never in a file
  inside the project: see the rules.
- **A key already in your shell for other work gets used, and billed**: pictures are
  drawn as soon as you open Outfits. The app's first lines then say the pictures are
  on. To keep them off:
  `env -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY python -m wardrobe`.
- Without a key everything else works: Outfits shows the product photos and a line
  saying the pictures are switched off. `python -m wardrobe looks` says whether they
  are on. The checks never use a key: the tests remove it, and the walk-through uses
  a stand-in that returns grey cards.
- To try them, use your own key, never someone else's. `per_day` in
  `config/looks.toml` caps pictures a day; `auto = false` draws only when you press
  "See it worn" (keep such changes out of your commits). `python -m wardrobe looks
  --test` draws one billed sample.

## The checks

| Command | What it runs | Time |
| --- | --- | --- |
| `./check.sh` | pyflakes (unused names, typos), mypy (types), bandit (risky patterns), every unit test with coverage | under a minute |
| `./check.sh browser` | the same, then `tests/browser_check.py`: a real browser signs up and goes through the app in 12 steps | about 1.5 minutes |
| `./check.sh audit` | the same, then pip-audit: known vulnerabilities in the packages (optional, needs the internet) | under a minute |

Both `./check.sh` and `./check.sh browser` must pass before you open a pull request.
When one fails:

- `check.sh` prints `== <name>` before each check and stops at the first that fails,
  so the last `==` line names it.
- A failed test prints `FAIL:` or `ERROR:` with its name and the reason; the end says
  `FAILED (…)`. Run one file with `python -m unittest tests.test_app`, one test with
  `python -m unittest tests.test_rules.Composition.test_german_percent_first`.
- Coverage (how much of the code the tests run) must stay at 85% or more; it is 88%
  now. Under 85%, `check.sh` stops and says so, here and on GitHub.
- The walk-through prints each step with `ok`, or `FAILED` and the reason, then a list
  of failures. A failed request or a script error on a page fails the step too.
- Normal noise, not failures: `ResourceWarning` lines, one
  `ValueError: secret internals` traceback (a test causes it on purpose),
  `Email to ada@example.com was not sent`, and a line per request in the walk-through.

On GitHub every pull request runs five checks, about two minutes in all: "Lint, types,
tests (Python 3.13)", "Lint, types, tests (Python 3.14)", "Browser walk-through",
"Known vulnerabilities in the packages" and "Container builds and starts". If one is
red, click it on the pull request and open the failed step, or use `gh pr checks` and
`gh run view <run id> --log-failed`.

## How we work

- **Where you push**: once the owner adds you as a collaborator (accept the invitation
  GitHub emails you), push branches here. Until then, `gh pr create` makes a fork (your
  own copy on GitHub), pushes your branch there and opens the pull request; the checks
  of a pull request from a fork wait until the owner lets them run.
- **main is protected**: GitHub takes a change to it only through a pull request whose
  five checks passed on top of the latest main. Nobody can push to it directly or
  force-push, the owner included.
- **Your commit email is public** in a public repository. To keep yours private, run
  `git config user.email "<address>"` in `capsule` with the address GitHub shows
  under Settings, Emails (it ends in `@users.noreply.github.com`).
- **One branch per change**, named for it (`fix-page-width`), from the latest main:
  `git switch main && git pull && git switch -c <name>`. Never push to main.
- **Say what you are working on** in a GitHub issue first, so two people do not change
  the same files at once.
- **Small pull requests**, one change each. Fill in the template. All five checks must
  be green. If main has moved on, press "Update branch" on the pull request, or
  `git switch main && git pull && git switch - && git merge main`, then push.
- **Who merges**: Claude, the owner's AI assistant, opens pull requests from the
  owner's account (haniyacoub) and merges its own once the five checks are green.
  Yours are merged by the owner, or by Claude when the owner says so: please do not
  merge your own.
- **Squash merges**: a pull request becomes one commit on main (GitHub offers only
  "Squash and merge" here, and deletes the branch afterwards). That commit takes the
  pull request's title, or its commit's message if it has only one, so make both a
  plain sentence about what changed, like "Outfits no longer stretches the page
  sideways on phones and computers". Plain words in test names too:
  `test_baumwolle_is_cotton_not_wool`.
- **A change in behaviour comes with tests**, and with README.md or PRODUCTION.md
  updates when what people do or see changes. The code must also run on Python 3.13
  (the container's version).
- **Working with an AI assistant?** Give it this file: the same rules apply.

## The rules that matter

1. **Never commit anyone's data or a secret**: not `data/`, `data-production/`,
   `deploy/*.env` (`.gitignore` covers these three), nor databases, photos, store
   catalogues or keys. Look at `git status` before every commit, add files by name,
   never `git add -f`. Tests and screenshots use invented people, `@example.com` emails.
2. **AI picture keys come from environment variables only** (set in the terminal, or
   in your own `~/.zshrc`): never in a file inside the project, a commit, a chat, an
   issue or a screenshot. GitHub refuses pushes that contain a known kind of key, but
   do not count on it. If one lands in a commit, cancel it at the service at once and
   tell the owner; deleting the commit is not enough.
3. **The store collector is the owner's to run**, under the rule in "Store data".
4. **Fonts are self-hosted, with an open licence** (such as the SIL Open Font License):
   a German court (LG München I, 2022) found that loading Google Fonts from Google's
   servers breaks data-protection law. Nothing new loads from another site (today
   only the stores' product pictures do).
5. **Learn from other sites' patterns, copy nothing**: no text, images, logos or fonts.
6. **Nothing invented is shown as real**: no made-up products, prices or reviews, no
   fake numbers or urgency ("only 2 left!"). Demo data is fine: the pages say so.
7. **Changing the UI on purpose? Update the tests and the walk-through to the new
   UI.** Never delete or weaken an assertion to make it pass; replace it with one that
   checks the same promise to the customer. A new photo area, for example, still needs
   a check that the photo is gone after "Delete my photo".
8. **Accessible, phone first, dark mode.** WCAG 2.2 AA: enough contrast, all of it
   works by keyboard, every control has a label a screen reader can read, tap targets
   at least 24 by 24 pixels. Design for the phone first (the walk-through checks pages
   390 and 1280 pixels wide). No test covers dark mode: look at it (on a Mac: System
   Settings, Appearance, Dark).
9. **Plain, short English**, British spelling (colour, catalogue): on screen, in tests
   and in commit messages. A message says what happened and what to do next.

## Where things live

```text
wardrobe/                  the code; wardrobe/__init__.py says what each file does
wardrobe/app.py            the web pages (Flask routes)
wardrobe/templates/        the pages: Jinja and HTMX
wardrobe/static/           app.css, app.js, the icon; vendor/ holds htmx
wardrobe/db.py             all the SQL (SQLite)
wardrobe/collect/          the store collector (the owner runs it)
config/                    the rules, in TOML: scoring, stores, size charts, AI pictures
tests/                     unit tests, one file per area; browser_check.py: the walk-through
tests/fixtures/            made-up pages in the stores' shape for the collector's tests
check.sh                   every check in one go
.github/workflows/checks.yml   the five checks GitHub runs
pyproject.toml             settings for mypy, bandit and coverage (the 85% floor)
requirements*.txt          packages: the app, the checks (-dev), the server (-prod)
Dockerfile, gunicorn.conf.py   running it as a service (PRODUCTION.md)
deploy/                    the server set-up; preview.sh (owner only) puts this computer online
data/                      your local data, made on first start; never committed
```

## Where to ask

Ask the owner (haniyacoub on GitHub), or open an issue at
<https://github.com/haniyacoub/capsule/issues>. Issues are public: no keys, personal
details or store data in them. Report a security problem privately: the repository's
Security tab, "Report a vulnerability".

## Licence and terms

All rights reserved: Capsule is not open source. The code is public so that you can
read it and work on it with us; it may not be copied or reused elsewhere without the
owner's written permission. By sending a contribution (a pull request, a patch, code
in an issue), you agree that Capsule may use, change and publish it, including
commercially, without payment. If you do not agree, say so before you send it.
