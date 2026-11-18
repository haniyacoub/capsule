# Stilsmith: product, design and engineering review

17 November 2026. Reviewed: `main` at `914f229` (Round 6d). This branch, `review/product`, holds this report,
its screenshots in [review/shots/](review/shots/) and six small changes ("quick wins") with their tests.

---

## The one-page summary

Stilsmith is unusually honest and carefully built. Every price says when it was read, every AI picture on the
page is labelled, almost every action has Undo, the pages work by keyboard and in dark mode, and the
accessibility checker finds almost nothing. It does not yet feel like a premium fashion product. It feels like a well-documented tool: the
pages lead with sentences, most text is small and grey, and the AI picture, which you call the heart of the
product, is small and shows clothes that are only *like* the ones you would buy.

These are the five changes that would matter most, in order of importance:

1. **Put the real products on the model.** Today the picture is drawn from a written description, so the coat in
   the picture is not the coat in the shop, and the page has to say "Look and fit will differ on the real pieces".
   Zara, Google, Doji and Daydream all dress the person in the actual products. Until Stilsmith does, the heart of
   the product undercuts itself. This needs the stores' written permission to use their product photos for new
   pictures, then work on the prompts. Large effort. See [F22](#f22).
2. **Make the picture the screen.** On a 390 × 664 phone the AI picture is 190 × 285 pixels, about a fifth of the
   screen, because the budget bar, the demo notice, the filters, the title, the answer bar and the tab bar all
   share the first screen with it. The landing page has no picture at all. Give the picture about 310 × 460 pixels
   on a phone (2.6 times the area) and put one approved picture on the landing page. Medium effort. See
   [F16](#f16) and [F3](#f3).
3. **Spend AI money where the customer shows intent.** A new customer can start 30 pictures and a video a day,
   about 1.50 to 2 € of AI, while by a rough estimate a customer earns Stilsmith well under 1 € in his first month.
   The whole site's daily limit of 300 pictures would serve only about 15 to 25 new customers a day. Draw the front
   picture as now, but offer "More photos" and "See it move" for outfits he said yes to, and use a few fixed house
   models whose pictures everyone shares. Medium effort. See [F17](#f17).
4. **Speak German, in half the words.** The interface is English for German customers, beside German product
   names. On the Wardrobe page 85% of the text is 13 pixels or smaller. Cut the words on the main pages by half,
   raise the text size, then translate. Large effort overall; the copy pass is medium. See [F18](#f18) and
   [F23](#f23).
5. **Earn the right to go public.** No store's partner programme has accepted Stilsmith, so there is no licensed
   product data; the legal pages are placeholders; the AI and partner-link labels are not complete. These are
   launch blockers, mostly for you and a lawyer rather than for code. See [F24](#f24), [F20](#f20), [F21](#f21),
   [F11](#f11) and [F2](#f2).

**Built in this branch** (each small, each with tests; `./check.sh browser` passes):

| | Change | Finding |
|---|---|---|
| 1 | The landing page no longer promises "the best-value real product … from COS and Weekday" while the service shows invented demo products. It says the products are invented examples. | [F1](#f1) |
| 2 | The day a store's programme accepts Stilsmith, every page's foot and the shopping list say its links are partner links, instead of silently dropping "Not affiliated with any retailer". | [F2](#f2) |
| 3 | Under the six price levels, the chosen level's meaning is said in words. It was only in a note that a mouse shows, so phones never saw it. | [F6](#f6) |
| 4 | The shopping list starts with the pieces. The three download and print buttons moved to its foot. | [F7](#f7) |
| 5 | An outfit's narrow photo tiles say the price alone ("180 €") instead of a cut-off store name ("WEEKDA…"). | [F8](#f8) |
| 6 | An SQLite version that can freeze the app is named when the app starts, and the browser walk-through stops at once with the reason instead of hanging. | [F15](#f15) |

---

## How this review was done

- **Set-up.** A clone of `main` (the same commit as GitHub) with a fresh Python 3.14 environment made as the
  README's "Setting up from scratch" says; the environment already in the clone had the SQLite problem in
  [F15](#f15). The app ran in production mode (accounts, landing page) on this Mac, bound to `127.0.0.1` only,
  with a data folder outside the repository. **No AI key was set and no paid service was called.** Test accounts
  used `@example.com` addresses.
- **The AI views.** With no key the AI pictures are off, as you asked. To see the picture states (drawing, ready,
  More photos, See it move, the model on Profile, the style chat) I also ran the app with the same offline
  stand-ins the walk-through uses: grey cards instead of pictures, a test-pattern clip, and the canned chat answers
  in `wardrobe/mockchat.py`. Nothing left the machine. These screens show layout and wording, not image quality.
- **Screens.** Every page on phones of 390 × 664 and 360 × 640 and a computer at 1280 × 800, light and dark;
  by mouse, by touch (touch screen emulated in Chromium) and by keyboard alone. Playwright drove a real Chromium.
- **Measurements.** Tap-target sizes, text sizes, page weight and timings measured in the browser; accessibility
  checked with axe-core 4.14.1 on 12 pages, on a phone and a computer, light and dark (48 runs).
- **Checks.** `./check.sh browser` before and after the changes. Before: 939 unit tests and 57 walk-through steps,
  all passing. After: 943 unit tests (94% coverage) and all 58 walk-through steps (one new) pass.
- **Competitors.** Web research, and one look at each public site from a normal browser: one page load, nothing
  clicked, no sign-up, no consent given. COS, Arket, Uniqlo and Mr Porter answered "Access Denied" (HTTP 403) to
  an automated browser, and Ssense and Lyst showed a bot check; I left them alone, as the collector rule says.
- **Not tested:** real AI pictures, real product data (only the demo data), real phones, Safari, VoiceOver.

**Effort:** Small = up to a day. Medium = a few days to a week. Large = more than a week, or it needs someone else
(a store, a lawyer). **Impact:** High = changes whether people trust, buy or come back, or is a legal must. Medium =
a friction many customers meet. Low = polish, or a rare case.

---

## What already works, and should stay

- **Truthful words.** Prices and stock carry the time they were read, sold-out pieces are left out of every
  total and said by name, and the piece pop-up shows store, quality score, fabric, cut, size in stock and the
  date ([review/shots/piece-and-video.png](review/shots/piece-and-video.png)). Few shops are this honest.
- **Undo and feedback everywhere:** after a yes, a no, a swap, a removed outfit.
- **Accessibility is mostly done.** On what is on screen, axe-core found one kind of problem, a small one
  ([F27](#f27)); its contrast warnings were all on outfits that are off screen and faded on purpose. Focus is
  always visible (a 2-pixel ink ring), the keyboard order is logical, every control has a name, and the colour
  contrast of the design's colours is documented in `app.css`.
- **Dark mode** is complete and consistent ([review/shots/dark-mode.png](review/shots/dark-mode.png)).
- **Privacy by design:** one strictly necessary cookie, self-hosted font, body numbers sent to the AI only as
  words, photo consent dated, data export and account deletion on the Account page.
- **Speed:** pages are built in 30 to 80 ms on this machine; no page is wider than a phone.
- **Tests:** 939 unit tests at 94% coverage and a 57-step browser walk-through that checks real promises.

---

## Findings, ordered by impact for the effort

| # | Finding | Effort | Impact | Status |
|---|---|---|---|---|
| [F1](#f1) | The landing page promised real products on demo data | Small | High | Built |
| [F2](#f2) | Partner links would be unlabelled the day a programme accepts | Small | High | Built |
| [F3](#f3) | The landing page shows no picture | Small | High | For you |
| [F4](#f4) | On "Buy this outfit" the main action is a small link | Small | Medium | |
| [F5](#f5) | Profile on a phone shows its form through a narrow strip | Small | Medium | |
| [F6](#f6) | What a price level means is only shown on mouse-over | Small | Medium | Built |
| [F7](#f7) | The shopping list starts with three buttons | Small | Medium | Built |
| [F8](#f8) | Outfit tiles cut store names to "WEEKDA…" | Small | Medium | Built |
| [F9](#f9) | Two different outfits get the same name in the messages | Small | Medium | |
| [F10](#f10) | Choices that look like plain text | Small | Medium | |
| [F11](#f11) | "Full size" shows the AI picture without its label | Small | Medium | |
| [F12](#f12) | Delivery costs and returns per store are not shown | Small | Medium | |
| [F13](#f13) | Three lists to understand: plan, wardrobe, outfits | Small | Medium | |
| [F14](#f14) | The private trial uses one shared password | Small | Medium | For you |
| [F15](#f15) | SQLite 3.51.0 and 3.51.1 can freeze the app | Small | Medium | Built |
| [F16](#f16) | The AI picture is a fifth of a phone screen | Medium | High | |
| [F17](#f17) | AI spend follows views, not intent | Medium | High | |
| [F18](#f18) | Too many words, set too small | Medium | High | |
| [F19](#f19) | Size advice stops short of a size | Medium | High | |
| [F20](#f20) | Legal and trust pages are placeholders | Medium | High | For you |
| [F21](#f21) | GDPR set-up for body data and face photos | Medium | High | For you |
| [F22](#f22) | The clothes on the model are not the products | Large | High | |
| [F23](#f23) | The interface is English | Large | High | |
| [F24](#f24) | No licensed product data yet | Large | High | For you |
| [F25](#f25) | Nothing brings a customer back | Large | High | |
| [F26](#f26) | The welcome asks for sizes first and refuses half an answer | Medium | Medium | |
| [F27](#f27) | Screen readers miss the price on Wardrobe cards | Small | Low | |
| [F28](#f28) | The hero feature is framed as rationed | Small | Low | |
| [F29](#f29) | On a computer, Wardrobe and the list use half the screen | Small | Low | |
| [F30](#f30) | Stylesheet and script are sent with their comments | Small | Low | |
| [F31](#f31) | `--lan` puts the app without a login on the whole Wi-Fi | Small | Low | |

---

<a id="f1"></a>
### F1. The landing page promised real products on demo data (built)

- **Problem.** Until a product list is published, every customer gets invented demo products, and every page says
  "Demo data — invented items, not real products, prices or stock". The landing page said the opposite: Stilsmith
  "picks the best-value real product for each from the high-street stores COS and Weekday". It named those two
  stores because the collector reads them, even though the public service never runs the collector.
- **Where.** Landing page. `wardrobe/templates/landing.html`; the store names come from `shared.stocked()`.
- **Evidence.** [review/shots/landing-before-after.png](review/shots/landing-before-after.png).
- **Change made.** With no published list, the lead now says Stilsmith "picks a product for each and shows you
  every outfit they make. For now the products are invented examples, not real products, prices or stock." With
  a published list it reads as before. New helper `shared.published()`; tests in `tests/test_production.py` and
  `tests/test_programmes.py`.
- **Effort:** Small. **Impact:** High: your rule that every sentence shown must be true.

<a id="f2"></a>
### F2. Partner links would be unlabelled the day a programme accepts (built)

- **Problem.** While no programme has accepted Stilsmith, every page's foot says "Not affiliated with any retailer",
  which is true. Until this change, the day you marked one "approved" that line disappeared and nothing took its
  place, just as the links began to earn commission. German courts treat such links as advertising that must be marked before the
  click (for example [LG München I, 2024](https://www.kanzlei.biz/wettbewerbswidrigkeit-von-ungekennzeichneten-affiliate-links-lg-muenchen-i-09-07-2024-az-1-hk-o-12576-23/);
  [overview](https://www.it-recht-kanzlei.de/affiliate-links-korrekte-kennzeichnung.html)).
- **Where.** Every page's foot (`base.html`, `error.html`); the shopping list and Buy this outfit (`_buy_groups.html`).
- **Change made.** From that day the foot says "Partner links: Stilsmith may earn a commission when you buy at
  COS. You pay the same." Under the store links the list says the same and adds that the commission does not
  change which product is picked for a piece. I checked that this is true: nothing in `selection.py`,
  `scoring.py`, `outfits.py` or `style.py` reads a programme's status. Nothing changes on screen today. Test:
  `test_partner_links_are_said_to_be_partner_links` in `tests/test_store_picker.py`.
- **Still for you.** Have a lawyer confirm the wording, in German, and whether each link needs its own mark (an
  asterisk is common). Note one more fact for the "how we pick" page ([F20](#f20)): Stilsmith offers only stores
  that have a partner programme, which does shape what customers see.
- **Effort:** Small. **Impact:** High (legal).

<a id="f3"></a>
### F3. The landing page shows no picture

- **Problem.** The heart of the product is the AI model view, and the landing page has none: a headline, a
  paragraph and a button, on a phone and on a computer. The template says a picture goes there once one drawn by
  the real service has been approved. Doji's whole home page is one full-length model in an outfit; Alta and
  Daydream lead with one big idea. A stranger decides in seconds.
- **Where.** Landing page. `wardrobe/templates/landing.html` (the comment where the picture goes).
- **Evidence.** [review/shots/landing-desktop.png](review/shots/landing-desktop.png),
  [review/shots/competitors/doji.jpg](review/shots/competitors/doji.jpg).
- **Recommendation.** With your own key, draw the house model in three strong outfits (about 15 cents), choose
  one, and put it in the hero with its "AI picture" label and the outfit's price. One picture, not a gallery.
- **Effort:** Small (you choose; the code is a few lines). **Impact:** High.

<a id="f4"></a>
### F4. On "Buy this outfit" the main action is a small link

- **Problem.** This is the page where Stilsmith earns money. Each piece's product link is a line of small
  underlined text, 20 pixels tall, 5 pixels under another link (the piece's own page), on a phone. That is under
  the 24-pixel minimum of WCAG 2.2 and far under the 44 points Apple recommends for a finger. The one button,
  "Open the first of 5 at Weekday", comes after every piece.
- **Where.** Buy this outfit and the shopping list. `wardrobe/templates/_buy_groups.html`.
- **Evidence.** [review/shots/buy-this-outfit.png](review/shots/buy-this-outfit.png); measured: links 16 and
  20 pixels tall on a 390-pixel phone.
- **Recommendation.** Give each piece one full-width "Open at Weekday" button with the size to choose on it
  ("Open at Weekday · choose L"), and put the store's "Open the first of 5" button under the store's name, before
  its pieces.
- **Effort:** Small. **Impact:** Medium.

<a id="f5"></a>
### F5. Profile on a phone shows its form through a narrow strip

- **Problem.** Profile's first screen on a phone shows a line drawing of a man in a T-shirt and shorts and the
  tab names, and no field to fill in. When you scroll, the drawing (more than a third of the screen) and the tabs
  stay pinned at the top, and Save and the tab bar at the bottom. What is left for the sizes, the colours, the
  style chat and the photo is about 230 pixels of a 664-pixel screen.
- **Where.** Profile on phones of 600 pixels or taller. `app.css`, the rules for `.cc[data-tabs] .cc-stage` and
  `.cc-tabs` under "(max-width: 759.98px) and (min-height: 600px)".
- **Evidence.** [review/shots/profile-phone-scrolling.png](review/shots/profile-phone-scrolling.png); measured:
  drawing 249, tabs 57, Save 73, tab bar 57 pixels.
- **Recommendation.** Pin the drawing only while the Body tab is open, where it shows each choice. On the other
  tabs let the page scroll as one. Show the AI picture of the model, when there is one, instead of the drawing.
- **Effort:** Small (the walk-through's Profile steps need adjusting). **Impact:** Medium.

<a id="f6"></a>
### F6. What a price level means is only shown on mouse-over (built)

- **Problem.** "Cheap" means "about a quarter of the way up each piece's price range"; "Best for budget" means
  something subtler. These explanations were only in each level's mouse-over note, which phones never show.
- **Where.** Wardrobe page. `wardrobe/templates/wardrobe.html`, new `_level_hint.html`.
- **Evidence.** [review/shots/wardrobe-levels-before-after.png](review/shots/wardrobe-levels-before-after.png).
- **Change made.** Under the levels, the chosen level's meaning is now said in the same words, and changes with
  the level. Screen readers hear it with the levels. Tests: `test_the_chosen_price_level_is_said_in_words`
  (`tests/test_app.py`) and the updated count in `tests/test_looks.py`.
- **Effort:** Small. **Impact:** Medium.

<a id="f7"></a>
### F7. The shopping list starts with three buttons (built)

- **Problem.** On a phone the first screen of the shopping list was its title, a sentence and three large outlined
  buttons ("Download for a spreadsheet (.csv)", "Download as text (.md)", "Print") before any piece.
- **Where.** Shopping list. `wardrobe/templates/list.html`.
- **Evidence.** [review/shots/list-before-after.png](review/shots/list-before-after.png).
- **Change made.** The list comes first; the buttons are at its foot after the total. Test:
  `test_the_pieces_come_before_the_downloads` (`tests/test_phase3.py`).
- **Still open.** "(.md)" means nothing to most customers. Drop the Markdown download from the page (the address
  can stay) or call it "Download as plain text".
- **Effort:** Small. **Impact:** Medium.

<a id="f8"></a>
### F8. Outfit tiles cut store names to "WEEKDA…" (built)

- **Problem.** Each piece's photo in an outfit has a caption. On a phone a tile is about 95 pixels wide, too
  narrow for "WEEKDAY · 180 €", so it showed "WEEKDA…", on every outfit. This is what every customer sees while
  the AI picture is drawn (about 20 seconds) and whenever pictures are off. It looks broken.
- **Where.** Outfits and My outfits. `wardrobe/templates/outfits.html`, `app.css` (`.tile .cap`).
- **Evidence.** [review/shots/tiles-before-after.png](review/shots/tiles-before-after.png).
- **Change made.** A tile under 150 pixels wide shows the price alone; the list of pieces under the picture names
  the store. Wider tiles (a computer) are unchanged. New walk-through step: "an outfit's tiles say their price whole".
- **Effort:** Small. **Impact:** Medium.

<a id="f9"></a>
### F9. Two different outfits get the same name in the messages

- **Problem.** The messages after an answer name an outfit by its two main pieces. I added one outfit: "Added the
  outfit with the charcoal wool coat and indigo jeans to your wardrobe". Then I said "Not for me" to the next one,
  which had the same coat and jeans but another top: "The outfit with the charcoal wool coat and indigo jeans will
  not be offered again". A customer reads that as the outfit he just added being thrown away.
- **Where.** Outfits, the line above the outfit. `yes.name` in `wardrobe/yes.py`; `outfits.html`.
- **Evidence.** [review/shots/yes-then-no-same-name.png](review/shots/yes-then-no-same-name.png).
- **Recommendation.** Show the answered outfit's pieces as a row of small photos in the message, with "Undo"
  beside them, and keep the words short ("Not for me: it won't be offered again."). Pictures are the one name
  that is never ambiguous.
- **Effort:** Small. **Impact:** Medium.

<a id="f10"></a>
### F10. Choices that look like plain text

- **Problem.** Unchosen options have no outline or fill: "Everyday · Office · Both" on the welcome, the styles
  and the model's age, height, build and skin on Profile look like a sentence, not like things to tap. Only the
  chosen one is underlined.
- **Where.** Welcome step 3, Profile (You and Body tabs). `app.css`, `.seg` and `.pick`.
- **Evidence.** [review/shots/welcome-steps.png](review/shots/welcome-steps.png) (fourth screen),
  [review/shots/profile-body-desktop.png](review/shots/profile-body-desktop.png).
- **Recommendation.** Give every option a hairline outline (the colour of the input borders) and fill the chosen
  one in ink, as fashion sites commonly do with sizes. Keep the square corners.
- **Effort:** Small. **Impact:** Medium.

<a id="f11"></a>
### F11. "Full size" shows the AI picture without its label

- **Problem.** On the page every picture carries "AI picture". "Full size" opens the picture file by itself in a
  new tab, with no label, ready to be saved and shared. For a picture made from a customer's own photo that is a
  realistic image of a real person. The EU AI Act's transparency rules (Article 50) have applied since
  [2 August 2026](https://digital-strategy.ec.europa.eu/en/factpages/quick-facts-transparency-rules-ai-systems).
- **Where.** Outfits, under the picture. `_look.html` (the "Full size" link) and `app.py` (`look_image`).
- **Evidence.** [review/shots/full-size-has-no-label.png](review/shots/full-size-has-no-label.png).
- **Recommendation.** Open "Full size" in a small page of Stilsmith's own that shows the picture with its label
  and a way back. Later, also write the label into the picture file itself for pictures made from a photo, and
  ask a lawyer what the Act requires of Stilsmith here.
- **Effort:** Small. **Impact:** Medium (legal for pictures of the customer).

<a id="f12"></a>
### F12. Delivery costs and returns per store are not shown

- **Problem.** An outfit from two stores means two deliveries and two returns policies, and in Germany returns
  decide where people buy. The page says "Each store adds its own delivery costs at checkout", which is true but
  leaves the customer to find out. The store registry already has an empty `delivery_note` column for this.
- **Where.** Buy this outfit and the shopping list. `_buy_groups.html`; `config/feeds.toml` (`delivery_note`).
- **Recommendation.** Under each store's name, one line from the store's own terms, for example "Delivery 4.95 €,
  free from 50 €. Free returns within 30 days." Store it with the date you read it and show that date, as with
  prices.
- **Effort:** Small (keeping it true is the work). **Impact:** Medium.

<a id="f13"></a>
### F13. Three lists to understand: plan, wardrobe, outfits

- **Problem.** The Wardrobe page opens with "8 pieces in your wardrobe · 2 outfits you said yes to · 19 in the plan
  your outfits are made from · Edit the plan". The customer has to hold three lists in mind: the plan (what
  outfits are made from), the wardrobe (the pieces of the outfits he said yes to) and his outfits. "Plan" is the
  planner's word, not his.
- **Where.** Wardrobe, the plan page, the welcome, the landing page's steps.
- **Evidence.** [review/shots/wardrobe-levels-before-after.png](review/shots/wardrobe-levels-before-after.png).
- **Recommendation.** Keep two words for the customer: "your wardrobe" and "your outfits". Call the plan
  "the pieces we choose from" and move its link to the bottom of the Wardrobe page. Say the counts as a short
  headline ("8 pieces · 2 outfits") rather than a sentence.
- **Effort:** Small. **Impact:** Medium.

<a id="f14"></a>
### F14. The private trial uses one shared password

- **Problem.** The trial is closed with `SITE_PASSWORD`, one password for everyone (the browser's sign-in box).
  Anyone who has it can pass it on, it cannot be taken back from one person, and it shows nobody's identity.
  Affiliate networks review a site before accepting it, and a reviewer needs a way in.
- **Where.** `wardrobe/app.py` (the site password check), `deploy/`.
- **Recommendation.** Cloudflare is already planned in front of the site. Use its free Access feature with an
  email one-time code for a list of addresses, and give each tester and each network's reviewer their own access.
  Keep `SITE_PASSWORD` as a second lock until Access is proven.
- **Effort:** Small (settings in Cloudflare, no code). **Impact:** Medium.

<a id="f15"></a>
### F15. SQLite 3.51.0 and 3.51.1 can freeze the app (built)

- **Problem.** On this Mac `./check.sh browser` hung at its first page. A stack sample showed eight server threads
  waiting inside SQLite while one closed a connection. The Python in the clone's `.venv` (miniconda 3.13.12)
  carries SQLite 3.51.1; [SQLite 3.51.2](https://www.sqlite.org/releaselog/3_51_2.html) fixed "an obscure
  deadlock". The app opens a connection for each step of a page from several threads, which is how it is hit.
  With Python 3.14 (SQLite 3.50.4) everything passed. The container uses Debian's SQLite and is probably fine.
- **Where.** `wardrobe/db.py`, `wardrobe/app.py` (`bootstrap`), `tests/browser_check.py`.
- **Change made.** `db.sqlite_problem()` names the two versions. The app's start-up lines say so with what to do;
  the walk-through stops at once with the reason instead of failing step after step on timeouts. Test:
  `test_an_sqlite_that_can_freeze_the_app_is_named_at_start`.
- **Effort:** Small. **Impact:** Medium (a frozen site, if it ever reaches production).

<a id="f16"></a>
### F16. The AI picture is a fifth of a phone screen

- **Problem.** On a 390 × 664 phone the finished picture is 190 × 285 pixels, 21% of the screen. On the first
  screen it shares the room with the header, the budget bar, the demo notice, the filters, the outfit's title and
  price, the answer bar and the tab bar, because the design keeps the whole model and "Add to my wardrobe" on the
  first screen. On a 1280 × 800 computer it is 517 × 776 pixels, which is right. Competitors show the person almost
  full screen. On the phone the six photos ("More photos") are 30 × 40-pixel thumbnails.
- **Where.** Outfits on phones. `outfits.html`, `app.css` (`.looks`, `--least`, `--told` and the phone rules).
- **Evidence.** [review/shots/outfits-phone.png](review/shots/outfits-phone.png); measured in the browser.
- **Recommendation.** Picture first on phones: hide the budget bar on Outfits (the answer bar already says what
  a yes adds), move the filters and the shuffle into one small row under the picture, and put the title and price
  on the picture's lower edge. That gives the picture about 310 × 460 pixels, 2.6 times the area, with the yes
  still in reach. Let the six photos open full screen with a swipe between them.
- **Effort:** Medium (the walk-through checks the phone layout closely). **Impact:** High.

<a id="f17"></a>
### F17. AI spend follows views, not intent

- **Problem.** A front picture is drawn for every outfit a customer looks at, and "More photos" (5 pictures) and
  "See it move" (a video) are offered on every outfit. At about 4 to 5 cents a picture (`config/looks.toml`) and
  0.35 to 0.56 $ a clip (README), one curious evening (12 outfits, More photos on two, one video) costs about 1.20
  to 1.60 €, and the daily limits allow about 2 €. The site-wide 300 pictures a day serve about 15 to 25 new
  customers; after that the heart of the product is gone for everyone until the next day ("Today's pictures are
  used up"). See the business section for what a customer earns.
- **Where.** `config/looks.toml` (`auto`, `per_day`, `per_customer_per_day`, `[videos]`), `looks.py`, `videos.py`.
- **Recommendation.** Keep drawing the front picture by itself, but offer "More photos" and "See it move" only on
  outfits in My outfits, where he has said yes. Replace free-form model descriptions with a small set of house
  models (for example three builds, three skin tones, two ages: 18 models): pictures of the same outfit on the
  same house model are already shared between customers, so most front pictures would cost nothing after the
  first. Pictures from a customer's own photo stay his. Until then, set the limits to what you are willing to lose
  in a day.
- **Effort:** Medium. **Impact:** High.

<a id="f18"></a>
### F18. Too many words, set too small

- **Problem.** The pages explain everything in full sentences, and most of it is small. Measured on a phone: 85%
  of the Wardrobe page's text is 13 pixels or smaller, and 21% of the Outfits page's text is 11-pixel labels.
  The landing page's first paragraph (as it reads with real products) is one sentence of 34 words. Each outfit shows two prices (the outfit, 545 €,
  and what a yes adds, 40 €) and the bigger one is the less useful one. The result reads like documentation. Premium sites use few words and let
  the photograph speak.
- **Where.** Every page; the type scale in `app.css` (`--t-xs` 11 px to `--t-3xl` 27 px).
- **Evidence.** [review/shots/outfits-phone.png](review/shots/outfits-phone.png),
  [review/shots/wardrobe-levels-before-after.png](review/shots/wardrobe-levels-before-after.png).
- **Recommendation.** One copy pass with a hard rule: each message at most one line on a phone, details behind a
  "Why?" link that opens the full sentence. Lead each outfit with what a yes adds ("+40 €"). Raise reading text
  to at least 15 pixels and labels to at least 12, and use three text sizes, not seven. Keep every sentence true:
  shorter, not vaguer.
- **Effort:** Medium. **Impact:** High.

<a id="f19"></a>
### F19. Size advice stops short of a size

- **Problem.** The card says "Size: L" and then "Fit: oversized, runs large. Size down for a regular fit." At the
  moment of buying, the customer still has to decide. Wrong size is the main reason Germans send clothes back:
  72.6% of returns according to [KPMG Germany](https://kpmg.com/de/en/media/press-releases/2025/12/retouren-als-chance-kundenerwartungen-verstehen-huerden-verringern.html),
  and partner programmes usually pay only on what is kept. Uniqlo's MySize ASSIST and Zalando's assistant give a
  size.
- **Where.** Wardrobe cards, Buy this outfit, the piece pop-up. `sizecheck.py`, `sizes.py`, `_macros.html`.
- **Recommendation.** Say one size to order and why: "Order M for a regular fit (this coat runs large). L for
  the oversized look." Where the store gives no size chart, say so and keep the warning.
- **Effort:** Medium. **Impact:** High.

<a id="f20"></a>
### F20. Legal and trust pages are placeholders

- **Problem.** Impressum, privacy policy and terms say "Not written yet". There is no page that says who runs
  Stilsmith, how it earns money, or how it picks products. German law asks a site that compares products from
  different traders to explain the main criteria of its ranking (UWG § 5b), and a stranger asks the same
  question before he trusts the picks.
- **Where.** `/legal/*` (`legal.html`); no "about" or "how we pick" page.
- **Recommendation.** Write with a lawyer: Impressum, privacy policy (naming Google, the host and the mail
  provider), terms. Add one plain page, "How Stilsmith picks", from what the code does: price level, quality
  score (fabric, brand, price), your sizes, colours and style; only stores with a partner programme; commission
  does not change a pick. Link it from the foot and from "Picked for you" on each piece.
- **Effort:** Medium (mostly yours). **Impact:** High (launch blocker).

<a id="f21"></a>
### F21. GDPR set-up for body data and face photos

- **Problem.** Stilsmith stores height, weight, chest and waist, and optionally a face photo that is sent to
  Google with each picture. The code is careful (numbers never leave the server, the photo has dated consent and
  can be deleted, there is an export). What is missing is around it: a data-processing agreement with Google for
  the paid Gemini API, the transfer basis to the US, a data-protection impact assessment, retention periods, and
  the names in the privacy policy. PRODUCTION.md already says so.
- **Recommendation.** Treat weight and the photo as sensitive: keep asking clearly before using them, write a
  short impact assessment (new technology, faces, body data), sign Google's processing terms, and keep
  `photos = false` until the privacy policy names Google. Details in the risk section.
- **Effort:** Medium (yours and a lawyer's). **Impact:** High (launch blocker for photos).

<a id="f22"></a>
### F22. The clothes on the model are not the products

- **Problem.** The AI picture is drawn from words: garment type, colour, fabric and the store's description. So
  the picture can never show the real collar, the real check or the real fit, and the page must say "Look and fit
  will differ on the real pieces". Zara's Try-On dresses a customer's own avatar in Zara's actual products; Google's
  try-on uses the merchant's product images; Doji and Daydream dress the person in real catalogue items. Against
  them, a picture of clothes that are only similar weakens the promise.
- **Where.** `looks.py`, `imagegen.py`, `config/looks.toml` (`[text]`). The app already sends a reference picture
  for the five extra photos, so the mechanism exists.
- **Recommendation.** Ask each partner programme, in writing, whether its product photos may be used to make new
  pictures (PRODUCTION.md lists the same question). Where they may, send the product photos as reference pictures
  for the front picture, keep "AI picture" on it, and change the line under it to what is then true. Google Cloud
  sells a [Virtual Try-On API](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/virtual-try-on-api)
  built for this (a picture of a person and of a product in, the person wearing it out); compare it with the
  general image model on cost and faithfulness before choosing.
- **Effort:** Large (permission, then prompt work and checking). **Impact:** High.

<a id="f23"></a>
### F23. The interface is English

- **Problem.** The customers are German men; the pages are English, the stores' product names and colours are
  German ("Colour: Anthrazit"), so many screens mix the two. PRODUCTION.md lists it.
- **Recommendation.** After the copy pass ([F18](#f18)), move every customer-facing sentence into one place
  (Flask-Babel, the usual tool for Flask) and translate with a native writer, not word for word. Start with the
  legal pages, the welcome, Outfits and Buy.
- **Effort:** Large. **Impact:** High.

<a id="f24"></a>
### F24. No licensed product data yet

- **Problem.** No programme has accepted Stilsmith yet; the public service shows demo products; the collector
  cannot run on a server and its data may not be published. The brief mentions Uniqlo and Arket: in the code
  Uniqlo is not offered (no programme was found, `config/feeds.toml`), and Arket is listed for applying but has no
  products. Mr Porter's programme forbids keeping its data (`links_only`), so its products cannot appear in
  outfits.
- **Recommendation.** Apply first to the Awin programmes your research marks as open to product-data sites, give
  their reviewers access ([F14](#f14)), and build the importer against the first real feed file, as PRODUCTION.md
  plans.
- **Effort:** Large (yours). **Impact:** High (launch blocker).

<a id="f25"></a>
### F25. Nothing brings a customer back

- **Problem.** Once he has built a wardrobe there is no reason to return: no email, no news, no price change, no
  outfit of the day. Cladwell's daily outfit is its habit; Lyst brings people back with price drops.
- **Recommendation.** One hook, once feeds exist: "A piece in your wardrobe is cheaper" (or back in your size),
  by email with his explicit consent. It is useful, honest, and leads straight to a purchase.
- **Effort:** Large (feeds, email, consent). **Impact:** High.

<a id="f26"></a>
### F26. The welcome asks for sizes first and refuses half an answer

- **Problem.** The first thing a new customer is asked, before seeing anything, is four sizes, with trouser waist
  and length in inches and no help. If he knows only his shoe size he is told "Give all four sizes, or skip this
  step." Step 2 asks the budget, then lists 25 colours as tick boxes, while Profile has a better tap-to-like
  swatch picker.
- **Where.** `/welcome`. `welcome.html`, `app.py` (`welcome`).
- **Evidence.** [review/shots/welcome-steps.png](review/shots/welcome-steps.png).
- **Recommendation.** Ask what is fun first and what is needed last: what you dress for, then colours (the
  Profile swatches), then budget, then outfits. Ask for sizes when he first opens Buy this outfit, and keep any
  size he gives.
- **Effort:** Medium. **Impact:** Medium.

<a id="f27"></a>
### F27. Screen readers miss the price on Wardrobe cards

- **Problem.** Each Wardrobe card is one link whose name is set to "Charcoal wool coat: see all options", which
  replaces everything inside it: a screen reader never hears the price, store or size. axe-core reports it on all
  8 cards ("label-content-name-mismatch"). Its only other finding, low contrast, was on outfits that are off
  screen and faded on purpose.
- **Where.** `_wardrobe_body.html` (`aria-label` on `.slot-main`).
- **Recommendation.** Remove the `aria-label` so the card's own words are read, and add "see all options" as hidden
  text at the end.
- **Effort:** Small. **Impact:** Low.

<a id="f28"></a>
### F28. The hero feature is framed as rationed

- **Problem.** Next to "More photos": "5 pictures of your 30 a day". On See it move: "1 video left today". Both are
  true, and you chose to say them before the tap. They also make the best feature feel metered.
- **Recommendation.** Say the allowance only when it matters: when fewer than five pictures, or no video, are
  left today.
- **Effort:** Small. **Impact:** Low.

<a id="f29"></a>
### F29. On a computer, Wardrobe and the list use half the screen

- **Problem.** At 1280 pixels the Wardrobe cards and the shopping list keep to a column on the left, and the
  right half of the screen is empty. Outfits uses the width well.
- **Evidence.** [review/shots/wardrobe-desktop.png](review/shots/wardrobe-desktop.png).
- **Recommendation.** Two columns of cards on Wardrobe from 1100 pixels; on the list, the sizes and total in a
  column beside the stores.
- **Effort:** Small. **Impact:** Low (most customers are on phones).

<a id="f30"></a>
### F30. Stylesheet and script are sent with their comments

- **Problem.** `app.css` is 151 KB, 40% of it comments; `app.js` is 84 KB, 34% comments. Compressed they are 41 KB
  and 26 KB, which Cloudflare will do; a phone still has to read every byte.
- **Recommendation.** Leave the source as it is and strip comments when building the container. Low priority.
- **Effort:** Small. **Impact:** Low.

<a id="f31"></a>
### F31. `--lan` puts the app without a login on the whole Wi-Fi

- **Problem.** `python -m wardrobe serve --lan` listens on every network address with no login. The README says
  so plainly, and requests under other host names are refused. Anyone on the same Wi-Fi can still open it.
- **Recommendation.** Keep it for trusted home networks as documented. For anything else use the production
  preview behind Cloudflare Access ([F14](#f14)).
- **Effort:** Small. **Impact:** Low.

---

## The customer journey, moment by moment

A brand-new customer on a 390 × 664 phone, then the same pages on a computer.

| Step | What happens | Moment | Finding |
|---|---|---|---|
| Landing | Headline, paragraph, button; no picture | No proof of the product | [F3](#f3) |
| Landing | "best-value real product … COS and Weekday" on demo data | Untrue | [F1](#f1) built |
| Landing | "Free. You buy straight from the stores … never takes payment." | Good: clear and reassuring | |
| Sign-up | Email, password, 18+ in small print | Fine | |
| Welcome 1 | Four sizes first, inches, no help; half an answer refused | Friction before any value | [F26](#f26) |
| Welcome 2 | Budget, then 25 tick boxes of colours | Long; unlike Profile's picker | [F26](#f26) |
| Welcome 3 | "Everyday · Office · Both" looks like text | What do I tap? | [F10](#f10) |
| Outfits | With pictures off: five small photos, store names cut off | Looks broken | [F8](#f8) built |
| Outfits | "Drawing this outfit on the model · about 20 seconds" | Clear, but a long first wait | [F16](#f16) |
| Outfits | The picture arrives at 190 × 285 pixels | The heart is small | [F16](#f16) |
| Outfits | Outfit price 545 €, a yes adds 40 € | Two prices; the useful one is smaller | [F18](#f18) |
| Outfits | "Added the outfit with the charcoal wool coat and indigo jeans…" | Good: says what happened, with Undo | |
| Outfits | "Not for me" on another outfit: the same name | Did I just lose the one I added? | [F9](#f9) |
| Outfits | Piece pop-up: store, quality, fabric, cut, size in stock, date | Excellent | |
| Outfits | "More photos · 5 pictures of your 30 a day" | Feels metered | [F28](#f28) |
| Outfits | "Full size" opens the bare picture | Label lost | [F11](#f11) |
| Outfits | "See it move": clear offer, plays, can be turned | Good; costly | [F17](#f17) |
| Wardrobe | "8 pieces … 19 in the plan your outfits are made from" | Three lists to hold in mind | [F13](#f13) |
| Wardrobe | Six price levels and a quality slider at the top | Expert controls first; meanings hidden on phones | [F6](#f6) built |
| Wardrobe | "Best for budget" can cost the same as "Cheapest" | Explained once chosen (the note) | |
| Wardrobe | "Size: L" then "runs large, size down" | Which size do I order? | [F19](#f19) |
| Shopping list | Three buttons before the pieces | Wrong order | [F7](#f7) built |
| Buy this outfit | Small stacked links; the store button last | The money moment is fiddly | [F4](#f4) |
| Buy this outfit | No delivery cost or returns per store | Doubt at the till | [F12](#f12) |
| Profile | First screen: a line drawing of a man, no field | Where do I start? | [F5](#f5) |
| Profile | Scrolling: the form in a 230-pixel strip | Hard to fill in | [F5](#f5) |
| Profile | "Described to the AI as: …"; what is sent to Google | Good transparency | |
| Style chat | Answers, then a brief that changes nothing until confirmed | Good: in control | |
| Account | Download a copy, delete the account | Good | |
| Legal pages | "Not written yet" | Blocker | [F20](#f20) |

---

## UX and product

**Is the core loop clear and rewarding?** The loop (see an outfit, say yes or no, the wardrobe grows, buy) is
clear once understood, and the honesty of "what a yes adds" is a real strength. It is not yet rewarding: a yes
produces a sentence and the next outfit. Nothing shows the wardrobe growing, and the picture, which should be the
reward, is small ([F16](#f16)) and not of the real clothes ([F22](#f22)). Make the yes visible: the outfit's pieces
fly into a small "wardrobe" row and the count changes; after a few yeses, say what the wardrobe is worth in
outfits (for example "Your 3 outfits share 7 pieces: about 60 € an outfit"). That cost-per-outfit number is
Stilsmith's best argument and is never said.

**What is missing for trust.** Who runs Stilsmith, how it earns money, how it picks ([F20](#f20)); delivery and
returns per store ([F12](#f12)); a size to order ([F19](#f19)); real products ([F24](#f24)); German ([F23](#f23)).
The honesty in the details is already there.

**What would bring him back.** One useful, honest reason: a price drop or a restock on a piece in his wardrobe
([F25](#f25)). Later: a new outfit from pieces he already has, as Cladwell does daily.

**Onboarding and empty states.** The empty states are good: plain, with one button to the outfits. The welcome
asks the wrong thing first ([F26](#f26)).

**Pricing honesty.** Strong: VAT included, delivery mentioned, dates on prices, sold-out pieces excluded. Add
delivery and returns per store ([F12](#f12)).

**Sizes and fit, returns.** The fit notes are good; the last step, a size, is missing ([F19](#f19)). Returns are
the biggest cost in German fashion and the biggest risk to commissions.

**The role of the AI picture.** It should be the first thing on every outfit, large, and of the real products. It
should also be the landing page. Today it is a promise the rest of the page has to qualify.

**What would make someone buy or pay.** Buying: confidence in look (real products on him), in fit (one size to
order) and in the store (delivery, returns), then a one-tap hand-off per store with the size named. Paying: not
before the picture shows the real products. Then a paid tier for heavy picture and video use of his own photo
could work; Cladwell charges 9.99 $ a month for daily styling advice. The "Pro" mark in the code is the right
place to start.

---

## UI: how premium it feels

- **Typography.** One family, Archivo, with a wide cut for titles: a good, distinctive choice. The scale has seven
  sizes from 11 to 27 pixels and most text sits at 13. Premium menswear sites use fewer, larger sizes for
  reading, and very little text. See [F18](#f18).
- **Spacing.** A consistent 4- and 8-pixel scale, square corners, quiet lines. Calm. The phone's first screen is
  crowded because of the number of bars, not because of spacing ([F16](#f16)).
- **Colour.** Warm off-white, near-black ink, amber and red only for warnings: close to COS and Arket. Keep it.
- **Hierarchy.** Sentences of similar weight compete; the eye finds the price and little else. The picture should
  lead ([F16](#f16)), then the outfit's name and what a yes adds.
- **Imagery.** The product's own image, the AI picture, is small; the landing page has none ([F3](#f3)). The demo
  drawings are fine for a demo.
- **Motion.** Thought through: 100 to 280 ms, quick in, quicker out, and nothing moves for people who ask their
  device for less motion. Keep it.
- **Consistency.** Two different colour pickers ([F26](#f26)); choices that look like text ([F10](#f10)).
- **Next to the competitors.** Doji leads with one full-length person, Alta with one sentence and the app, Daydream
  with one input box. Stilsmith leads with a paragraph. The pieces for a premium look are here (type, colour,
  restraint); what is missing is one large, true picture and fewer words.
- **Accessibility.** axe-core 4.14.1, 48 runs (12 pages × phone and computer × light and dark): on visible content,
  only the Wardrobe card names ([F27](#f27)). Focus is visible on every stop; keyboard order is logical; arrow
  keys move between outfits. Tap targets: most controls are 44 pixels; the product links on Buy and the list are
  16 to 20 ([F4](#f4)). Not checked with VoiceOver or TalkBack.

---

## Competitors: what to learn and what to avoid

Screenshots: [review/shots/competitors/](review/shots/competitors/) (public pages, 17 November 2026, one load each).
COS, Arket, Uniqlo, Mr Porter and Ssense refused the automated browser, so their rows rest on their public help
pages and their well-known page patterns, not on a fresh look today.

| Who | What it is | Learn | Avoid |
|---|---|---|---|
| **Zara Try-On** | In Zara's app: upload a face photo and a full-body photo; an avatar of you wears Zara products and walks and turns ([marketing4ecommerce](https://marketing4ecommerce.net/en/zara-try-on/)). Launched in Spain in late 2025; 7 million sessions in 43 markets within weeks, by Inditex's results ([DRESSX](https://dressx.com/news/zara-turned-one-photoshoot-into-hundreds-of-ai-generated-outfits.-here-s-how-any-brand-can-do-the-same)). | The actual product, on you, moving. German men will know the idea from Zara. | One brand only: Stilsmith's edge is outfits across stores, within a budget. Reviewers mention faces that do not look right ([Perfect Corp](https://www.perfectcorp.com/business/blog/ai-clothes/i-tried-zara-online-virtual-try-on-tool)): keep the face consistent. |
| **Google try-on** | In Search, Shopping and Chrome, with your own photo ([Google, I/O 2025](https://blog.google/products/shopping/google-shopping-ai-mode-virtual-try-on-update/); [Chrome help](https://support.google.com/chrome/answer/18507944)). Its separate app, Doppl, closed on 30 April 2026 ([Google](https://support.google.com/labs/answer/16537062?hl=en)). | One photo, saved, reused for every product; built from the merchants' own product images. | One product at a time, no outfit, no budget. From this review machine the page said "Not available in this location": an open field in Germany. |
| **Stitch Fix** | A stylist picks clothes and sends a box; 20 $ styling fee credited to what you keep ([Stitch Fix](https://www2.stitchfix.com/pricing)). US. | A short note from a stylist on why each piece suits you; fit feedback after each box. | A fee before any value. |
| **Cladwell** | Capsule wardrobe from your own clothes; an outfit each day for the weather; 9.99 $ a month or 79.99 $ a year ([Cladwell](https://cladwell.com/pricing)). | The daily outfit as a habit; colour palettes. | A paywall early. |
| **Whering** | Free social digital wardrobe, "over 10 million" users, a browser extension to save items from any shop ([Whering](https://whering.co.uk/)). | Saving from any store in one tap (Stilsmith's paste-a-link, made easy). | Its landing page opened with a pop-up over a cookie banner (screenshot). |
| **Indyx** | Free digital wardrobe, paid one-to-one stylists, a service that photographs your wardrobe ([Indyx](https://www.myindyx.com/)). | Cost per wear: Stilsmith already knows "in 4 of your outfits"; say "about 9 € an outfit". | Manual cataloguing: about 2 minutes per item ([Closets by Design](https://www.closetsbydesign.com/blog/closet-organizing-apps-worth-it)). |
| **Acloset** | AI wardrobe app, "8 million" users, outfit picks for the weather and your plans; completes a look around one piece you chose ([Acloset](https://www.acloset.app/)); free up to 100 items ([App Store](https://apps.apple.com/us/app/acloset-ai-fashion-assistant/id1542311809)). | "Build an outfit around this piece": a natural entry for Stilsmith. | A long feature list instead of one promise. |
| **Lyst** | Fashion search across thousands of stores, paid by affiliate commission; puts the affiliate average conversion at 1.5% of clicks ([Lyst](https://www.lyst.com/partners/)). | Price-drop alerts and saved items as return reasons; a benchmark for planning revenue. | Endless choice: Stilsmith's value is the small, chosen set. |
| **Mr Porter** | Luxury menswear with an editorial voice (The Journal); 28-day returns, delivery dates up front ([returns](https://www.mrporter.com/en-de/content/help/exchanges-and-returns/), [delivery](https://www.mrporter.com/en-de/content/help/delivery/)). Its programme forbids keeping its data. | Few words, strong opinions, delivery and returns said plainly. | Copying a luxury tone without the photography. |
| **COS** | Minimal, photo-led product pages. | Let one photograph carry the page; fabric in one plain line, as Stilsmith already does. | Browsing by category: Stilsmith's strength is a short list chosen for you. |
| **Arket** | Same group as COS; seasonal edits and product facts. | A capsule told as a story ("the autumn wardrobe, 14 pieces"). | The same: a store's catalogue is the opposite of a capsule. |
| **Uniqlo** | MySize ASSIST: a size from height, weight and age, or from the phone's camera ([Uniqlo](https://www.uniqlo.com/ca/en/special-feature/mysize-assist)). Not offered in Stilsmith (no programme). | Give a size, not a warning ([F19](#f19)). | Advice for one brand's sizes: Stilsmith has to work store by store, as its size charts do. |
| **Ssense** | Type-led, black and white, editorial; showed a bot check. | Strict typography can look premium if the photos are consistent. | Store-like density. |
| **Alta** | AI stylist: your digital closet and your avatar trying looks on; 11 M$ seed in 2025, 20 M$ in October 2026 ([TechCrunch](https://techcrunch.com/2025/06/16/alta-raises-11m-to-bring-clueless-fashion-tech-to-life-with-all-star-investors/), [Fortune](https://fortune.com/2026/10/22/alta-ai-fashion-app-series-a-20-million-forerunner-rent-the-runway/)). | Your own avatar is the product. | Building a social network before the core works. |
| **Doji** | A photorealistic avatar from six selfies and two full-body photos, wearing designer items ([Forbes](https://www.forbes.com/sites/stephaniehirschmiller/2025/05/29/how-ai-virtual-try-on-solutions-google--doji-are-changing-retail/)). | The home page is the person in an outfit ([F3](#f3)). | Eight photos and a wait before anything: Stilsmith's one photo is lighter. |
| **Daydream** | Chat to shop; on 17 November 2026 launched an agent that plans a look, tries it on you from one photo and handles the checkout ([TechCrunch](https://techcrunch.com/2026/11/17/daydreams-new-ai-agent-acts-as-your-personal-stylist-and-can-shop-for-you-too/)). | The chat leads to a real outfit and a purchase. | Stilsmith cannot check out for the stores; make the hand-off excellent instead ([F4](#f4)). |
| **Zalando** | Its assistant now gives size advice from 53 million customers' data ([Modaes](https://www.modaes.com/global/companies/zalando-is-refining-its-ai-assistant-using-sizing-data-from-53-million-customers)); a fitting room with a 3D avatar from your measurements ([Zalando](https://corporate.zalando.com/en/technology/zalando-enhances-its-virtual-fitting-room-enabling-customers-create-3d-avatar-their-body)). | Size advice is now expected. | Competing on data Stilsmith cannot have; use the stores' charts and be honest. |

**What this means for Stilsmith.** Try-on of the actual product is becoming normal, but each big player shows one
brand (Zara), one product (Google) or needs a big set-up (Doji). Nobody shows a German man a whole wardrobe from
several stores, on him, within his budget. That is Stilsmith's place, and it depends on [F22](#f22) and
[F24](#f24).

---

## Business and risk

### Money from partner programmes

- **Commission.** The store notes in `config/feeds.toml` (your research of 13 November 2026) range from 3% to 15%
  of the sale, most with a 30-day cookie.
- **Returns.** Programmes usually pay only on what is kept. Industry estimates put German online fashion returns
  at 40% to 50% or more ([eightX](https://eightx.co/blog/germany-ecommerce-return-rate-benchmark)), and wrong size
  is the reason for most of them ([KPMG](https://kpmg.com/de/en/media/press-releases/2025/12/retouren-als-chance-kundenerwartungen-verstehen-huerden-verringern.html)).
- **Conversion.** Lyst puts the affiliate average at 1.5% of clicks.
- **A worked example (assumptions, not data).** A customer buys one outfit of 250 € at 8% commission: 20 €; after
  45% returns, about 11 €. If one sign-up in 20 does that in his first month, a sign-up earns about 0.55 €.
- **So:** AI spend per customer must stay well under 1 € until conversion is known ([F17](#f17)); and anything that
  reduces returns (a size, real products) raises income directly.

### Cost per customer of AI pictures and video

| | Today's limits | Cost |
|---|---|---|
| A picture | 30 per customer a day, 300 for the site | about 4 to 5 cents (`config/looks.toml`); Google's published prices vary by model and size ([a summary](https://www.aifreeapi.com/en/posts/gemini-image-generation-api-pricing)) |
| A video | 1 per customer a day (5 for Pro), 10 for the site | 0.35 $ for 5 s, 0.56 $ for the 8 s turn (README, Google's list of 15 November 2026) |
| A style-chat message | 20 per customer, 500 for the site | about a tenth of a cent |

A curious first evening (12 outfits looked at, More photos on two, one video) is about 1.20 to 1.60 €; the daily
limits allow about 2 € per customer. The site's own limits cap the total at about 15 € of pictures and 5 $ of
video a day, about 600 € a month at most, which also means the pictures stop for everyone after 15 to 25 new
customers on a busy day. Pictures without a real person are shared between customers asking for the same
outfit on the same model words; house models ([F17](#f17)) make that sharing the normal case.

### GDPR: body measurements and face photos

- **Body data.** Height, weight, chest and waist are personal data; weight can reveal health. Today they stay on
  the server and only words reach Google ("a little shorter than average, lean build"). Keep that, explain it in
  the privacy policy, let him delete them (he can), and keep them optional.
- **Face photos.** Sent to Google with each picture of him. Before anyone but you uploads one: Google named in the
  privacy policy with its location and the agreement; Google's terms for the paid Gemini API signed; the transfer
  basis to the US stated; how long Google keeps requests stated; a short impact assessment; the consent box's
  wording checked by a lawyer. Until then `photos = false`, as PRODUCTION.md says.
- **AI Act.** Article 50 has applied since 2 August 2026. Pictures of a real person made by AI must be marked as
  AI-made; the page does this, "Full size" does not ([F11](#f11)). A grace period for machine-readable marks runs
  to 2 December 2026 for systems already on the market ([Baker Botts](https://www.bakerbotts.com/thought-leadership/publications/2026/september/eu-ai-act-article-50-transparency-obligations-go-live));
  that duty lies mainly with Google as the provider. Ask a lawyer which duties fall on Stilsmith.

### What must be true before going public in Germany

1. Product data you have the right to show, with written permission for the photos ([F24](#f24), [F22](#f22)).
2. Impressum, privacy policy and terms written with a lawyer ([F20](#f20)).
3. Partner links marked as advertising (built, wording to check) and a page that explains how products are
   picked ([F2](#f2), [F20](#f20)).
4. Every AI picture and video labelled, also at full size ([F11](#f11)).
5. Processing agreements with Google, the host and the mail provider; an impact assessment for photos and body
   data ([F21](#f21)).
6. German pages, at least the legal ones and the path to buying ([F23](#f23)).
7. Password-reset email working, daily backups copied off the server, and someone told when the site is down
   (PRODUCTION.md lists all three as not set up).
8. AI limits set to what you can afford on a busy day ([F17](#f17)).

---

## Engineering, where it affects the product

- **The SQLite freeze** ([F15](#f15)) was the one real fragility found; now named at start.
- **Speed.** Pages are built in 30 to 80 ms. The Outfits page is 105 KB of HTML and about 1,260 elements for 12
  outfits; fine. Store product photos will be the heavy part: they load lazily, which is right. AI pictures are
  asked for as JPEG, so they stay light.
- **Phones.** No page is wider than 360 or 390 pixels. The phone layout of Outfits is held together by many tuned
  numbers (`--least: 124px`, `--told`, `--said-h`) so that the whole model always fits the first screen. Relaxing
  that rule ([F16](#f16)) would also remove most of this delicate code.
- **The walk-through** takes about 10 minutes here and is sensitive to a slow machine; its steps check the right
  things. Keep it, and run it on GitHub as now.
- **Noise.** `./check.sh` prints two expected errors ("database is locked", "can't start new thread") that tests
  cause on purpose. They looked like failures to me at first; CONTRIBUTING's list of normal noise now names them.

---

## Roadmap

### Next week

- Review and merge this branch (its six quick wins).
- Draw three outfits on the house model with your key, put the best one on the landing page ([F3](#f3)).
- Set the AI limits to what you can afford to lose in a day ([F17](#f17)).
- Switch the trial to Cloudflare Access, one entry per tester and per network reviewer ([F14](#f14)).
- Small fixes: Buy buttons ([F4](#f4)), Profile on phones ([F5](#f5)), outfit names in messages ([F9](#f9)),
  outlined choices ([F10](#f10)), full-size label ([F11](#f11)), Wardrobe card names ([F27](#f27)).
- Apply to the first Awin programmes that accept product-data sites ([F24](#f24)).

### Next month

- Picture-first phone layout ([F16](#f16)) and the six photos full screen.
- More photos and See it move after a yes; house models ([F17](#f17)).
- The copy pass and the larger type ([F18](#f18), [F13](#f13)).
- A size to order ([F19](#f19)); delivery and returns per store ([F12](#f12)).
- The welcome in a new order ([F26](#f26)).
- Start German: move the strings into one place ([F23](#f23)).
- Ask each programme in writing about using product photos for new pictures ([F22](#f22)).

### Before launch

- Licensed feeds imported, with permission for the photos ([F24](#f24)).
- Real products on the model where permitted; elsewhere, the honest "drawn from words" picture ([F22](#f22)).
- Legal pages, "How Stilsmith picks", processing agreements, impact assessment, labels everywhere ([F20](#f20),
  [F21](#f21), [F11](#f11), [F2](#f2)).
- German throughout ([F23](#f23)).
- Email, backups, monitoring.
- One reason to come back: price drops on his pieces ([F25](#f25)).
- A test on real phones (iPhone Safari with VoiceOver, an Android phone with TalkBack).

---

## Screenshots

All of Stilsmith's screenshots show demo data and test accounts. The AI pictures are the walk-through's grey
stand-ins.

| File | Shows |
|---|---|
| [landing-before-after.png](review/shots/landing-before-after.png) | F1 |
| [landing-desktop.png](review/shots/landing-desktop.png) | F3 |
| [welcome-steps.png](review/shots/welcome-steps.png) | F26, F10 |
| [outfits-phone.png](review/shots/outfits-phone.png) | F16, F8, F28 |
| [yes-then-no-same-name.png](review/shots/yes-then-no-same-name.png) | F9 |
| [tiles-before-after.png](review/shots/tiles-before-after.png) | F8 |
| [full-size-has-no-label.png](review/shots/full-size-has-no-label.png) | F11 |
| [wardrobe-levels-before-after.png](review/shots/wardrobe-levels-before-after.png) | F6, F13, F19 |
| [wardrobe-desktop.png](review/shots/wardrobe-desktop.png) | F29 |
| [list-before-after.png](review/shots/list-before-after.png) | F7 |
| [buy-this-outfit.png](review/shots/buy-this-outfit.png) | F4, F12 |
| [profile-phone-scrolling.png](review/shots/profile-phone-scrolling.png) | F5 |
| [profile-body-desktop.png](review/shots/profile-body-desktop.png) | F10 |
| [piece-and-video.png](review/shots/piece-and-video.png) | what works; F28 |
| [dark-mode.png](review/shots/dark-mode.png) | what works |
| [quick-wins-dark.png](review/shots/quick-wins-dark.png) | the built changes in dark mode (F1, F6, F7, F8) |
| [competitors/](review/shots/competitors/) | Doji, Daydream, Alta, Google try-on, Stitch Fix, Cladwell, Whering, Indyx, Acloset |

The competitor screenshots show other companies' public pages, included here for comparison. The repository is
public: delete `review/shots/competitors/` before merging if you prefer not to publish them.

Content from the sources linked above was rephrased for compliance with licensing restrictions.
