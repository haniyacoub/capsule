<!--
Plain, short English. On main this pull request becomes one commit (squash merge), named after
its title, or after its commit's message if it has only one. So make both one sentence about
what changed, such as "Outfits no longer stretches the page sideways on phones".
-->

## What changed and why

<!-- What someone using Stilsmith notices, then why. Link the issue: "Closes #12". -->

## How it was checked

<!-- The commands you ran and what they said, such as
"./check.sh browser: 256 tests, 88% coverage, all 12 steps ok". Add anything you tried by hand. -->

## Screenshots

<!-- Only when something on screen changed: before and after at phone width, and the after in
dark mode too. Demo data and an @example.com account only: no real person's photo, no keys,
no personal details. Delete this section otherwise. -->

## Checklist

<!-- Tick each box. If one does not apply, say why under it. -->

- [ ] `./check.sh` and `./check.sh browser` pass on my machine, and the five checks are green here.
- [ ] New or changed behaviour has tests; coverage is still 85% or more (`check.sh` stops below that).
- [ ] `git status` checked: no `data/`, `data-production/`, `deploy/*.env`, databases, photos, store catalogues or keys in this pull request.
- [ ] No key, password or personal detail in the code, this description, the screenshots or the logs.
- [ ] No store was visited for this (no `refresh`, no Zara link pasted), unless by the owner; reading store pages is tested on `tests/fixtures`.
- [ ] Nothing copied from other sites (no text, images, logos or fonts), and nothing new loads from another site; a new font is self-hosted, with an open licence.
- [ ] Nothing invented is shown as real: no made-up products, prices, reviews or numbers, no fake urgency.
- [ ] If the UI changed on purpose, the tests and the walk-through check the new UI. No assertion was deleted or weakened, only replaced by one that checks the same promise.
- [ ] Works on a phone first, by keyboard and with a screen reader (WCAG 2.2 AA), and in dark mode.
- [ ] Plain, short English (British spelling) on screen, in tests and in commit messages.
- [ ] README.md or PRODUCTION.md updated if what people do or see changed.
