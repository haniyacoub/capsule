// The little JavaScript the app needs. Everything else is HTML rendered by
// Python and swapped in by HTMX (static/vendor/htmx.min.js).

// 1. Picture fallback. Every picture sits on a swatch of the item's colour.
//    If the image fails to load, hide it so the swatch and caption show.
function markBroken(img) {
  const pic = img.closest('.pic');
  if (pic) pic.classList.add('noimg');
}
function sweep(root) {
  root.querySelectorAll('.pic img').forEach((img) => {
    if (img.complete && img.naturalWidth === 0) markBroken(img);
  });
}
document.addEventListener('error', (e) => {
  if (e.target instanceof HTMLImageElement) markBroken(e.target);
}, true);
sweep(document);
document.body.addEventListener('htmx:afterSwap', (e) => sweep(e.target));

// 2. Show the slider's number while dragging.
document.addEventListener('input', (e) => {
  if (e.target.id === 'threshold') {
    document.getElementById('thr-out').textContent = e.target.value;
  }
});

// 3. "Are you sure?" for forms that carry a data-confirm message.
document.addEventListener('submit', (e) => {
  const message = e.target.dataset.confirm;
  if (message && !window.confirm(message)) e.preventDefault();
});

// 4. The Print button on the shopping list.
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-print]')) window.print();
});

// 5. Coming back with the browser's Back button: reload, so totals are current.
window.addEventListener('pageshow', (e) => {
  if (e.persisted) window.location.reload();
});

// 6. Outfits: the arrows and the arrow keys move the reel one outfit at a time.
//    (Swiping needs no code: the reel is a scrolling row that snaps, see app.css.)
//    Keyboard focus and what a screen reader hears go with it (6a-6c below).
//    The chips above the outfits scroll sideways in their own row on a narrow phone. A browser
//    gives keyboard focus to a chip that is only partly in that row without scrolling it in, so
//    its focus ring would be cut off: bring it in, clear of the edge by the row's scroll-padding.
const chipRow = document.querySelector('.toolbar .chips');
if (chipRow) {
  chipRow.addEventListener('focusin', (e) => {
    e.target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  });
}
const reel = document.getElementById('reel');
if (reel) {
  const slides = [...reel.querySelectorAll('[data-slide]')];
  const shown = () => Math.round(reel.scrollLeft / reel.clientWidth);    // which outfit is on screen
  // Your place: the outfit on screen is kept in the page's address (#outfit-<key>), in place of the address
  // before it, never as a new step in the history (Back still leaves the page). So Back from 'Buy this outfit'
  // or from a piece's page, and a reload, show it again. On Back the browser puts back where the page was
  // scrolled to, but not the row, so the row is moved to that outfit here, at once (no slide).
  // ('Show more outfits' leads to the same kind of address: the last outfit you saw.)
  const keep = (index) => {
    const slide = slides[index];
    if (slide && slide.id && window.location.hash !== '#' + slide.id) {
      window.history.replaceState(window.history.state, '', '#' + slide.id);
    }
  };
  const kept = slides.findIndex((slide) => slide.id && '#' + slide.id === window.location.hash);
  if (kept > 0) {
    reel.style.scrollBehavior = 'auto';
    reel.scrollLeft = kept * reel.clientWidth;
    reel.style.scrollBehavior = '';
  }
  // With "reduce motion" asked for in the device's settings, the arrows and the arrow keys show the next outfit
  // at once instead of sliding to it ('auto' follows app.css, which turns the sliding off then).
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  // `goal` is the outfit being scrolled to while the scroll is still under way, so that two
  // quick presses move two outfits instead of the second one being lost mid-scroll.
  let goal = null;
  let settled;

  // 6a. The row by keyboard and screen reader.
  //     Keyboard focus goes with the outfit on screen. When the row moves on while focus is inside another outfit
  //     (on its 'Buy this outfit', say), focus moves to the same thing in the outfit now shown (its 'Buy this
  //     outfit'), so that Enter acts on the outfit you see. Where that outfit has no such thing (no picture yet, so
  //     no dots), focus goes to the outfit itself, which can take focus for that (tabindex -1: never by Tab).
  //     preventScroll: the row slides as it would without this; the page does not jump.
  slides.forEach((slide) => { slide.tabIndex = -1; });
  const visible = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const follow = (index) => {
    const slide = slides[index];
    const here = document.activeElement;
    const from = here && reel.contains(here) ? here.closest('[data-slide]') : null;
    if (!slide || !from || from === slide) return;
    let twin = null;
    if (here !== from && here.classList.length) {
      const same = (root) => [...root.querySelectorAll(`${here.tagName}.${here.classList[0]}`)].filter(visible);
      const theirs = same(slide);
      twin = theirs[Math.min(same(from).indexOf(here), theirs.length - 1)] || null;
    }
    (twin || slide).focus({ preventScroll: true });
  };
  //     What a screen reader hears when the row comes to rest on another outfit ("Outfit 2 of 12, Office,
  //     257.75 €"), and when the picture of the outfit on screen arrives ("Picture ready"): one sentence in the
  //     page's one live region (base.html), only once the row is at rest, never while it scrolls.
  const announce = document.getElementById('announce');
  const say = (words) => {
    if (!announce || !words) return;
    // The same words again (a second picture of the same outfit) are only read out if the text changes.
    announce.textContent = announce.textContent === words ? `${words}\u00a0` : words;   // a no-break space after them
  };
  const describe = (slide) => {
    const title = slide.querySelector('.about-head h2');
    const cost = slide.querySelector('.board-cost');
    if (!title || !cost) return slide.textContent.replace(/\s+/g, ' ').trim();   // "That was 12 of 624. Show more outfits"
    return `${slide.getAttribute('aria-label')}, ${title.firstChild.textContent.trim()}, ${cost.textContent.trim()}`;
  };
  let told = shown();     // the outfit the page opens on (or comes back to) is not announced: the page says it
  const onScreen = () => slides[goal === null ? shown() : goal];    // the outfit on screen, or being moved to
  //     Tab goes through the outfit on screen only. The things to press in the other outfits are taken out of the
  //     Tab order (tabindex -1, their own tabindex kept in data-tab) and given back when their outfit is shown: at
  //     once when an arrow or an arrow key moves the row, so a Tab pressed before it comes to rest already leads
  //     into the outfit being moved to. So Tab from Next leads into the outfit you moved to, and Shift+Tab from
  //     below the row back into it, never into outfit 1, which the browser would scroll back to. The other outfits
  //     are not made inert: swiping, and a screen reader reading the whole row, work as before. What HTMX puts in
  //     (a picture, the heart) is sorted the same way once it is in.
  const pressable = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]';
  const tabInto = (current) => slides.forEach((slide) => slide.querySelectorAll(pressable).forEach((el) => {
    if (slide === current) {
      if (!('tab' in el.dataset)) return;
      if (el.dataset.tab) el.setAttribute('tabindex', el.dataset.tab);
      else el.removeAttribute('tabindex');
      delete el.dataset.tab;
    } else if (el.tabIndex >= 0) {
      el.dataset.tab = el.getAttribute('tabindex') || '';
      el.tabIndex = -1;
    }
  }));
  tabInto(onScreen());
  document.body.addEventListener('htmx:afterSettle', () => tabInto(onScreen()));

  const step = (direction) => {
    const from = goal === null ? shown() : goal;
    goal = Math.max(0, Math.min(slides.length - 1, from + direction));
    reel.scrollTo({ left: goal * reel.clientWidth, behavior: motion.matches ? 'auto' : 'smooth' });
    keep(goal);       // at once: 'Buy this outfit' may be pressed before the row has come to rest
    tabInto(slides[goal]);    // at once too, for the same reason
    follow(goal);
  };
  // A single outfit has no arrows (outfits.html leaves them out): there is nowhere to move to.
  // At either end of the row the arrow says it can go no further (aria-disabled, faded by app.css) and pressing it
  // does nothing. It is not switched off (disabled): that would throw keyboard focus off the arrow you have just
  // pressed to the page, and the next Tab would lead back to outfit 1. So both arrows stay Tab stops.
  const prev = document.querySelector('.reel-nav.prev');
  const next = document.querySelector('.reel-nav.next');
  const ends = () => {
    if (!prev || !next) return;
    prev.setAttribute('aria-disabled', String(reel.scrollLeft < 8));      // 'true' at the first outfit
    next.setAttribute('aria-disabled', String(reel.scrollLeft > reel.scrollWidth - reel.clientWidth - 8));   // at the last
  };
  if (prev && next) {
    [[prev, -1], [next, 1]].forEach(([arrow, direction]) => arrow.addEventListener('click', () => {
      if (arrow.getAttribute('aria-disabled') !== 'true') step(direction);
    }));
  }
  reel.addEventListener('scroll', () => {
    ends();
    clearTimeout(settled);
    settled = setTimeout(() => {      // the scroll has come to rest (after a swipe too)
      goal = null;
      const now = shown();
      keep(now);
      tabInto(slides[now]);
      follow(now);
      if (now !== told) {
        told = now;
        say(describe(slides[now]));
      }
    }, 200);
  }, { passive: true });
  ends();
  // The arrow keys anywhere on the page (not in a field, not with the pop-up open). With Alt, Ctrl, Cmd or Shift
  // they are the browser's (Alt+← is Back). The row moves instead of the browser scrolling it by a few pixels.
  document.addEventListener('keydown', (e) => {
    if (document.querySelector('dialog[open]') || e.target.closest('input, select, textarea')) return;
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    step(e.key === 'ArrowLeft' ? -1 : 1);
  });

  // 6b. When an outfit's picture box is replaced (its picture asked for, drawing, arrived), keyboard focus on what
  //     was in the box ('See it worn', 'Draw again') falls to the page, and focus on a piece's photo under the box
  //     is lost once the picture covers the photos. Then focus goes to the outfit's first dot, or to the outfit
  //     itself until the picture, and its dots, are there. And the outfit on screen says when its picture is ready
  //     (or why a new one was not drawn).
  //     The row of the outfit's small pictures (_shots.html) is also replaced on its own: when 'More photos' is
  //     tapped, and as each picture arrives. Focus that was on 'More photos', which is gone then, goes to the
  //     picture shown, in the row; and the outfit on screen says that the photos are being drawn, and when all are there.
  const isBox = (el) => el instanceof Element && el.matches('.look');
  const isRow = (el) => el instanceof Element && el.matches('.shots');
  let rowFocus = false;
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    const box = e.detail.target;
    if (isBox(box) && box.closest('.stage').contains(document.activeElement)) box.dataset.focus = 'in';
    if (isRow(box)) {
      // … or on the answer to a question asked under the picture before the photos are drawn (_look_ask.html):
      // the question goes when the row comes.
      const here = document.activeElement;
      const asked = box.closest('.look') && box.closest('.look').querySelector('.look-ask-at');
      rowFocus = box.contains(here) || !!(asked && asked.contains(here));
    }
  });
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const was = e.detail.target;
    if (!isRow(was)) return;
    const row = document.getElementById(was.id);
    if (!row) return;
    const drawing = !!row.querySelector('.spin');
    if (row.closest('[data-slide]') === onScreen() && !row.querySelector('.look-msg')) {
      if (drawing && !was.querySelector('.spin')) say('Drawing more photos');
      if (!drawing && was.querySelector('.spin')) say('More photos ready');
    }
    const here = document.activeElement;
    if (rowFocus && (!here || here === document.body)) {
      const shown = row.querySelector('[aria-pressed="true"]');
      if (shown) shown.focus({ preventScroll: true });
    }
    rowFocus = false;
  });
  // A question asked before anything is drawn (_look_ask.html: 'Draw again' on a front picture, whose other photos
  // would go with it; a photo made from the AI picture of a customer who has not yet agreed to that) is put into its
  // own place under the picture. It is said, it is brought above the tab bar where a short phone would hide it, and
  // keyboard focus goes to its first answer. When the other answer ('Keep them', 'Not now') takes the question
  // away, focus goes back to what was pressed ('More photos', a small picture), or to 'Draw again' in the line above.
  let askedFrom = '';       // the id of what was pressed when the question came
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const place = e.detail.target;
    if (!(place instanceof Element) || !place.matches('.look-ask-at')) return;
    const answer = place.querySelector('button');
    if (answer) {
      const sent = e.detail.requestConfig && e.detail.requestConfig.triggeringEvent;
      askedFrom = (sent && sent.submitter && sent.submitter.id) || '';
      say(place.querySelector('.look-msg').textContent.trim());
      if (place.closest('[data-slide]') === onScreen()) {
        const room = innerHeight - (parseFloat(getComputedStyle(document.documentElement).scrollPaddingBottom) || 0);
        const { top, bottom } = place.getBoundingClientRect();
        const by = Math.min(bottom - room, top);
        if (by > 0) window.scrollBy({ top: by, behavior: motion.matches ? 'auto' : 'smooth' });
      }
      answer.focus({ preventScroll: true });
    } else {
      const here = document.activeElement;
      const back = (askedFrom && document.getElementById(askedFrom)) || place.closest('.look').querySelector('.look-line button');
      askedFrom = '';
      if (back && (!here || here === document.body)) back.focus({ preventScroll: true });
    }
  });
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const box = e.detail.target;
    if (!isBox(box)) return;
    const slide = box.closest('[data-slide]');
    const shown = box.querySelector('.look-pic');
    const ready = shown && !box.querySelector('.look-bar.wait');   // not the one kept while "Draw again" draws
    if (ready && slide === onScreen()) {
      const why = box.querySelector('.look-msg');
      say(why ? why.textContent.trim() : 'Picture ready');
    }
    if (box.dataset.focus !== 'in') return;
    const here = document.activeElement;
    const fell = !here || here === document.body || here === slide || (slide.contains(here) && !visible(here));
    if (!fell) {      // focus is still on something you can see (a photo, before the picture comes): leave it there
      delete box.dataset.focus;
      return;
    }
    const dot = shown && [...slide.querySelectorAll('.spot')].find(visible);
    if (dot) {
      dot.focus({ preventScroll: true });
      delete box.dataset.focus;
    } else if (slide === onScreen()) {
      slide.focus({ preventScroll: true });     // the outfit itself, while its picture is drawn
    }
  });

  // 6c. Escape hides the dots' labels (the piece, its store and price), which show on hover and on focus, so that
  //     they never stay over the picture against your will. They show again on the next dot pointed at or focused.
  const looks = reel.closest('.looks');
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !document.querySelector('dialog[open]')) looks.classList.add('hush');
  });
  ['pointerover', 'focusin'].forEach((kind) => looks.addEventListener(kind, (e) => {
    if (e.target.closest('.spot')) looks.classList.remove('hush');
  }));

  // 6d. A piece's dot on the picture and its line in the list beside it are one piece: pointing at one, or reaching
  //     it with the keyboard, marks the other (.lit, app.css), so you see which garment a line is, and which line a
  //     dot is. Both are in the order of the outfit's pieces (outfits.html), so the first dot is the first line.
  const twin = (el) => {
    const slide = el.closest('[data-slide]');
    const [mine, theirs] = el.matches('.spot') ? ['.spot', '.piece-row'] : ['.piece-row', '.spot'];
    return slide.querySelectorAll(theirs)[[...slide.querySelectorAll(mine)].indexOf(el)] || null;
  };
  [['pointerover', true], ['pointerout', false], ['focusin', true], ['focusout', false]].forEach(([kind, on]) => {
    looks.addEventListener(kind, (e) => {
      const el = e.target instanceof Element && e.target.closest('.spot, .piece-row');
      if (!el || (e.relatedTarget instanceof Node && el.contains(e.relatedTarget))) return;   // only moving within it
      if (kind === 'focusin' && !el.matches(':focus-visible')) return;      // a tap is not the keyboard
      const other = twin(el);
      if (other) other.classList.toggle('lit', on);
    });
  });

  // 6e. A computer with a touch screen as well: the dots are out of sight until pointed at (app.css), and a finger
  //     does not point. So a touch on the picture while its dots are out of sight only brings them out (.touched,
  //     app.css), even when it lands on a dot nobody could see; the next touch on a dot opens the piece. They go
  //     again with a touch or a click elsewhere, or once the mouse is moved over the outfits. On a phone the dots
  //     are always there, and none of this happens.
  let unseen = null;       // the dot under a touch that could not be seen: the click that follows opens nothing
  document.addEventListener('pointerdown', (e) => {
    unseen = null;
    const stage = e.target instanceof Element && e.target.closest('#reel .stage');
    const slide = stage && stage.closest('[data-slide]');
    looks.querySelectorAll('.slide.touched').forEach((one) => {
      if (one !== slide && !(e.target instanceof Element && one.contains(e.target.closest('.pieces')))) one.classList.remove('touched');
    });
    if (!slide || e.pointerType !== 'touch') return;
    const dot = slide.querySelector('.spot');
    if (!dot || !visible(dot) || Number(getComputedStyle(dot).opacity) >= 0.5) return;     // no dots, or in sight
    slide.classList.add('touched');
    unseen = e.target.closest('.spot');
  }, true);
  document.addEventListener('click', (e) => {
    const dot = unseen;
    unseen = null;
    if (!dot || !(e.target instanceof Element) || e.target.closest('.spot') !== dot) return;
    e.preventDefault();          // not the link to the piece's page …
    e.stopPropagation();         // … nor the pop-up (HTMX listens on the dot itself)
  }, true);
  looks.addEventListener('pointerover', (e) => {
    if (e.pointerType === 'mouse') looks.querySelectorAll('.slide.touched').forEach((one) => one.classList.remove('touched'));
  });

  // 7. AI pictures: an outfit that stays on screen for a moment has its picture drawn,
  //    by pressing its "See it worn" button for you. The page marks those buttons only
  //    when config/looks.toml says so (pictures.auto).
  const watcher = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      const slide = entry.target;
      clearTimeout(slide.lookTimer);
      if (!entry.isIntersecting) return;
      slide.lookTimer = setTimeout(() => {
        const ask = slide.querySelector('[data-auto-look]');
        if (ask) {
          ask.removeAttribute('data-auto-look');
          htmx.trigger(ask, 'draw');
        }
      }, 1200);
    });
  }, { root: reel, threshold: 0.6 });
  reel.querySelectorAll('[data-slide]').forEach((slide) => watcher.observe(slide));
}

// 8. The pop-up for one piece of an outfit: HTMX fills it, this opens and closes it.
const sheet = document.getElementById('piece');
if (sheet) {
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target.id === 'piece-body' && !sheet.open) sheet.showModal();
  });
  sheet.addEventListener('click', (e) => {
    const box = sheet.getBoundingClientRect();
    const outside = e.target === sheet    // the dark area around it; a key press on a button inside has no position
      && (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom);
    if (outside || e.target.closest('[data-close]')) sheet.close();
  });
}

// 8a. Each piece of an outfit (its photo, its dot on the picture, its line in the list) is a link to the piece's own
//     page, which is what a tap opens without JavaScript (outfits.html). Here HTMX opens the pop-up from it instead,
//     so it is a button: a screen reader calls it one, and Space presses it, as it would a button.
document.querySelectorAll('#reel a[hx-target="#piece-body"]').forEach((link) => link.setAttribute('role', 'button'));
document.addEventListener('keydown', (e) => {
  const link = e.key === ' ' && e.target instanceof Element && e.target.closest('#reel a[role=button][hx-target="#piece-body"]');
  if (!link || e.altKey || e.ctrlKey || e.metaKey) return;
  e.preventDefault();       // not the page scrolling down
  if (!e.repeat) link.click();
});

// 9. A store's product pages, opened one by one. A browser lets a site open one new tab per tap and holds any
//    more back as pop-ups (the old "Open all" opened the first and lost the rest), so the button under a store is an
//    ordinary link to the next product page not yet opened (_buy_groups.html): nothing can hold that back. Here
//    each line whose page was opened, by the button or by its own link, is ticked; the button moves on to the next
//    and says how many are open. The ticks are kept while this tab stays open (never sent anywhere), so they are
//    still there after a look at another page. When every page was opened the button says "Start again": pressing
//    it opens nothing and takes the ticks off, and the button offers the first page once more.
const OPENED = 'stilsmith-opened-pages';
let openedPages = new Set();
try { openedPages = new Set(JSON.parse(sessionStorage.getItem(OPENED) || '[]')); } catch { /* private window: the ticks last until the page is left */ }
const openedTick = (link) => link.closest('.buy').querySelector('.buy-opened');
const openedKey = (link) => `${openedTick(link).dataset.line} ${link.href}`;     // this piece's product page
const storeLinks = (section) => [...section.querySelectorAll('a.buy-product')].filter((link) => link.getAttribute('href') !== '#');
function showOpened() {
  document.querySelectorAll('.store-list').forEach((section) => {
    const links = storeLinks(section);
    links.forEach((link) => {
      openedTick(link).hidden = !openedPages.has(openedKey(link));
    });
    const button = section.querySelector('[data-open-next]');
    if (!button) return;
    const left = links.filter((link) => !openedPages.has(openedKey(link)));
    const done = links.length - left.length;
    const partly = done > 0 && left.length > 0;
    const all = left.length === 0;
    button.href = (left[0] || links[0]).href;
    button.toggleAttribute('data-start-again', all);      // it opens nothing then (noteOpened): no arrow, no "(opens in a new tab)" (app.css)
    if (all) button.setAttribute('role', 'button');
    else button.removeAttribute('role');
    button.querySelector('[data-open-label]').textContent = all ? 'Start again'
      : partly ? `Open the next at ${button.dataset.store}` : `Open the first of ${links.length} at ${button.dataset.store}`;
    const status = partly ? `${done} of ${links.length} opened. Each press opens one more.` : all ? `All ${links.length} opened.` : '';
    const says = section.querySelector('[data-open-status]');
    if (says.textContent !== status) says.textContent = status;      // said once by a screen reader, not on every look
  });
}
function noteOpened(e) {
  const tapped = e.target instanceof Element && e.target.closest('a.buy-product, a[data-open-next]');
  if (!tapped || tapped.getAttribute('href') === '#' || (e.type === 'auxclick' && e.button !== 1)) return;
  let link = tapped;
  if (tapped.matches('[data-open-next]')) {       // the button stands for the first line not yet opened
    const links = storeLinks(tapped.closest('.store-list'));
    link = links.find((one) => !openedPages.has(openedKey(one)));
    if (!link) {                                   // every page was opened, and it says "Start again": the ticks
      e.preventDefault();                          // go, and no page is opened by this press
      links.forEach((one) => openedPages.delete(openedKey(one)));
    }
  }
  if (link) openedPages.add(openedKey(link));
  try { sessionStorage.setItem(OPENED, JSON.stringify([...openedPages])); } catch { /* as above */ }
  // Shown after the browser has followed the link: moving the button's address on now would send this tap to the next page.
  setTimeout(showOpened, 0);
}
document.addEventListener('click', noteOpened);
document.addEventListener('auxclick', noteOpened);      // a middle click opens a tab too
document.addEventListener('keydown', (e) => {           // "Start again" is a button: Space presses it, as Enter does
  const again = e.key === ' ' && e.target instanceof Element && e.target.closest('a[data-start-again]');
  if (!again || e.altKey || e.ctrlKey || e.metaKey) return;
  e.preventDefault();
  if (!e.repeat) again.click();
});
showOpened();
document.body.addEventListener('htmx:afterSwap', showOpened);

// 10. Your photo: make it smaller before it is sent. That is quicker, and the
//     copy carries none of the details a phone stores inside a photo (place, time).
//     What became of the chosen file is said right under it: a small copy of the
//     picture when it is ready to send, or why it cannot be used. A file this
//     browser cannot open as a picture (an iPhone's HEIC, in most browsers) is not
//     sent at all: the server could not use it either.
document.addEventListener('change', async (e) => {
  const input = e.target;
  if (!(input instanceof HTMLInputElement) || input.type !== 'file' || !input.closest('[data-photo-form]')) return;
  const form = input.form;
  const note = form.querySelector('[data-photo-ready]');
  const say = (text, preview) => {
    if (!note) return;
    note.hidden = !text;
    note.classList.toggle('bad', Boolean(text) && !preview);
    note.querySelector('p').textContent = text || '';
    const small = note.querySelector('img');
    small.hidden = !preview;
    if (preview) small.src = preview;
  };
  const file = input.files[0];
  if (!file) { say(''); return; }
  if (typeof createImageBitmap !== 'function') return;    // a very old browser: send it as it is, the server checks it
  const send = form.querySelector('button');
  send.disabled = true;     // not before the smaller copy is in place: the original must not be what is sent
  try {
    const picture = await createImageBitmap(file);
    const scale = Math.min(1, 1280 / Math.max(picture.width, picture.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(picture.width * scale);
    canvas.height = Math.round(picture.height * scale);
    canvas.getContext('2d').drawImage(picture, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((done) => canvas.toBlob(done, 'image/jpeg', 0.88));
    if (!blob) throw new Error('no picture came out');
    const smaller = new DataTransfer();
    smaller.items.add(new File([blob], 'me.jpg', { type: 'image/jpeg' }));
    input.files = smaller.files;
    const thumb = document.createElement('canvas');       // what will be sent, small, so you see it is the right one
    thumb.width = 108;
    thumb.height = 144;
    const fit = Math.max(thumb.width / canvas.width, thumb.height / canvas.height);
    thumb.getContext('2d').drawImage(canvas, (thumb.width - canvas.width * fit) / 2, (thumb.height - canvas.height * fit) / 2,
      canvas.width * fit, canvas.height * fit);
    say('This photo is ready. Tick the box and press the button to use it.', thumb.toDataURL('image/jpeg', 0.8));
  } catch (err) {
    input.value = '';       // nothing is sent
    const heic = /\.hei[cf]$/i.test(file.name) || /hei[cf]/i.test(file.type);
    say(heic
      ? 'This browser cannot open HEIC photos, the kind an iPhone saves. Save a copy as JPEG first '
        + '(in Photos: File, Export. In Preview: File, Export, Format JPEG), then choose that copy.'
      : 'This browser cannot open that file as a picture. Choose a JPEG or PNG photo.');
  }
  send.disabled = false;
});

// 11. A button on a page that has gone out of date (the outfit changed meanwhile): reload.
document.body.addEventListener('htmx:responseError', (e) => {
  if (e.detail.xhr.status === 409) window.location.reload();
});

// 12a. The line over the outfits that says what a change made from an outfit did (Choose, Undo, leaving a piece off)
//      is one to four lines on a phone, by the length of the product's name. The picture gives up room for it (--told,
//      see app.css): the longest line's until this runs. Here it is the room the line really takes, its height and
//      the space under it, so that a shorter line leaves the picture larger. It is measured again when it rewraps.
const saidLine = document.querySelector('main > .said');
if (saidLine && 'ResizeObserver' in window) {
  new ResizeObserver(() => {
    const under = parseFloat(getComputedStyle(saidLine).marginBottom) || 0;
    document.documentElement.style.setProperty('--said-h', `${saidLine.getBoundingClientRect().height + under}px`);
  }).observe(saidLine);
}

// 13. Profile: About you is one form, the model's choices included (the Body tab); the photo's forms are others, and
//     sending one of those loads the page again. Changes made in About you and not yet saved would then be lost without
//     a word, so the page asks first. "Changed" is measured against what the page was loaded with, field by field.
//     "Draw my model" draws the saved choices, so while there are changes a line beside it says to save first.
const aboutYou = document.getElementById('about-you');
if (aboutYou) {
  const changed = () => [...aboutYou.elements].some((field) => {
    if (field.type === 'hidden') return false;           // the open tab (13a) and the form's token
    if (field.type === 'checkbox' || field.type === 'radio') return field.checked !== field.defaultChecked;
    if (field.tagName === 'SELECT') {
      const loaded = [...field.options].find((option) => option.defaultSelected) || field.options[0];
      return Boolean(loaded) && field.value !== loaded.value;
    }
    if (field.tagName === 'INPUT' || field.tagName === 'TEXTAREA') return field.value !== field.defaultValue;
    return false;
  });
  document.addEventListener('submit', (e) => {
    // (A form that already asked its own question and was told no, like deleting the photo, is not sent anyway; nor is
    // one HTMX sends without loading the page, like "Draw my model".)
    if (e.defaultPrevented || e.target === aboutYou || !e.target.closest('[data-cc]') || !changed()) return;
    if (!window.confirm("You changed your profile but didn't save it. Leave those changes unsaved?")) {
      e.preventDefault();
    }
  });
  const sayUnsaved = () => {
    const unsaved = changed();
    document.querySelectorAll('[data-unsaved-note]').forEach((note) => { note.hidden = !unsaved; });
  };
  aboutYou.addEventListener('input', sayUnsaved);
  aboutYou.addEventListener('change', sayUnsaved);
  aboutYou.addEventListener('click', () => setTimeout(sayUnsaved));     // a colour swatch tapped (14)
  document.body.addEventListener('htmx:afterSwap', sayUnsaved);
  sayUnsaved();          // the fields as the browser kept them (Back, a reload), which may not be the ones saved
}

// 13a. Profile: the tabs, a real tablist. One tab is open at a time; the arrow keys (and Home and End) move between the
//      tabs and open them, and Tab goes from the open tab into its controls. The address keeps the open tab
//      (/profile#colours), so a link to a place on the page opens its tab: #budget (the budget bar), #sizes ("Change"
//      by Your sizes), #model (where "Model saved" is said), #photo (where the photo's messages are said), #style (the style chat). The form
//      carries the open tab, so that a save comes back to it. Over the middle, a switch shows the drawn figure or
//      "Your model" (the AI picture); changing a choice that the figure shows brings the figure back.
const profileCreator = document.querySelector('[data-cc]');
if (profileCreator) {
  const tablist = profileCreator.querySelector('[data-cc-tabs]');
  const tabs = [...tablist.querySelectorAll('[role=tab]')];
  const names = tabs.map((tab) => tab.id.slice('tab-'.length));
  const panelsOf = (name) => [...profileCreator.querySelectorAll(`.cc-panel[data-tab="${name}"]`)];
  const tabField = profileCreator.querySelector('[data-cc-tab-field]');
  const tabOf = (hash) => {
    const name = { model: 'body', photo: 'you', style: 'you' }[hash] || hash;
    return names.includes(name) ? name : null;
  };
  // The top of the controls' card, brought back into view when the page was scrolled past it (on a phone it then
  // starts just under the tabs, which stay at the top): what scroll-padding-top keeps clear. On a phone tall enough
  // for the middle to stay at the top (app.css), a tab chosen on the first screen, where its controls start low, also
  // brings them up to there: the middle then sits at the top of the screen, the tabs under it, the controls under them.
  const card = profileCreator.querySelector('.cc-side');
  const stuckMiddle = window.matchMedia('(max-width: 759.98px) and (min-height: 600px)');     // as app.css
  const lessMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const keepInView = () => {
    const clear = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
    const above = card.getBoundingClientRect().top - clear;
    if (above < 0 || (stuckMiddle.matches && above > 1)) {
      window.scrollBy({ top: above, behavior: lessMotion.matches ? 'auto' : 'smooth' });
    }
  };
  const open = (name, focus = false) => {
    tabs.forEach((tab) => {
      const on = tab.id === `tab-${name}`;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      if (!on) return;
      if (focus) tab.focus({ preventScroll: true });
      // In the row of tabs that scrolls sideways on a phone, the open one comes whole into it.
      const row = tablist.getBoundingClientRect();
      const box = tab.getBoundingClientRect();
      if (box.left < row.left) tablist.scrollLeft -= row.left - box.left + 16;
      else if (box.right > row.right) tablist.scrollLeft += box.right - row.right + 16;
    });
    names.forEach((other) => panelsOf(other).forEach((panel) => { panel.hidden = other !== name; }));
    tabField.value = name;
  };
  const choose = (name, focus = false) => {
    open(name, focus);
    history.replaceState(history.state, '', `#${name}`);
    keepInView();
  };
  profileCreator.querySelectorAll('.cc-panel').forEach((panel) => panel.setAttribute('role', 'tabpanel'));
  tablist.addEventListener('click', (e) => {
    const tab = e.target.closest('[role=tab]');
    if (tab) choose(tab.id.slice('tab-'.length));
  });
  tablist.addEventListener('keydown', (e) => {
    const at = tabs.indexOf(document.activeElement);
    const to = { ArrowRight: at + 1, ArrowDown: at + 1, ArrowLeft: at - 1, ArrowUp: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (at < 0 || to === undefined) return;
    e.preventDefault();
    choose(names[(to + tabs.length) % tabs.length], true);
  });
  // The place an address names (#budget, #colours …): its tab opens, and it is brought into view when it is not on the
  // screen (a field or a message by its own name, or else the top of the controls' card).
  const land = (asked) => {
    const name = tabOf(asked);
    if (!name) return;
    open(name);
    const place = document.getElementById(asked) || card;
    const box = place.getBoundingClientRect();
    if (box.top < 0 || box.top > window.innerHeight * 0.6) place.scrollIntoView({ block: 'start' });
  };
  // On such a phone the first screen shows the middle and the whole row of tabs above the tab bar. Where what is above
  // the middle (the title, a note, a message after a save) leaves too little room for it at 40% of the screen, it is
  // made shorter, down to 30% (--cc-stage, app.css), rather than the tabs falling under the tab bar. Worked out again
  // only when the width changes: a phone's address bar that hides on scrolling changes the height, and the middle
  // must not jump then.
  const fitMiddle = () => {
    document.documentElement.style.removeProperty('--cc-stage');
    if (!stuckMiddle.matches) return;
    const bar = document.querySelector('nav.tabs');
    const floor = bar ? bar.getBoundingClientRect().top : window.innerHeight;
    const room = floor - (profileCreator.getBoundingClientRect().top + window.scrollY) - tablist.getBoundingClientRect().height - 2;
    const stage = profileCreator.querySelector('.cc-stage').getBoundingClientRect().height;
    if (room < stage) {
      document.documentElement.style.setProperty('--cc-stage', `${Math.floor(Math.max(room, 0.3 * window.innerHeight))}px`);
    }
  };
  // The tabs work from here on: app.css lays the page out around the middle. Save goes last in the card, after the
  // photo's forms of the You tab, so that it can stay at the bottom of the screen on every tab and comes last by
  // keyboard too (without JavaScript it stays right under the fields it saves).
  const asked = decodeURIComponent(location.hash.slice(1));
  const saveBar = card.querySelector('.cc-save');
  if (saveBar) card.append(saveBar);
  profileCreator.dataset.tabs = '';
  tablist.hidden = false;
  fitMiddle();
  let fittedWidth = window.innerWidth;
  window.addEventListener('resize', () => {
    if (window.innerWidth === fittedWidth) return;
    fittedWidth = window.innerWidth;
    fitMiddle();
  });
  open(tabOf(asked) || names[0]);
  // Where the page lands: a message at the top (after a save) is seen first; else the place the address names.
  if (document.querySelector('main > .flash')) window.scrollTo(0, 0);
  else land(asked);
  // A link to another place on this same page (the budget bar's, on Profile) changes only the address.
  window.addEventListener('hashchange', () => land(decodeURIComponent(location.hash.slice(1))));

  const switcher = profileCreator.querySelector('[data-cc-switch]');
  if (switcher) {
    const views = [...profileCreator.querySelectorAll('[data-view]')];
    const show = (view) => {
      views.forEach((one) => { one.hidden = one.dataset.view !== view; });
      switcher.querySelectorAll('[data-show]').forEach((button) => {
        button.setAttribute('aria-pressed', String(button.dataset.show === view));
      });
    };
    switcher.addEventListener('click', (e) => {
      const button = e.target.closest('[data-show]');
      if (button) show(button.dataset.show);
    });
    profileCreator.addEventListener('change', (e) => {
      if (e.target.closest('#panel-body') || ['height_cm', 'weight_kg', 'chest_cm', 'waist_cm'].includes(e.target.name)) show('figure');
    });
    show('figure');
    switcher.hidden = false;
    // "Draw my model" and its picture are swapped in by HTMX: keyboard focus stays in the middle, and a screen reader
    // hears when the picture is ready.
    const box = profileCreator.querySelector('[data-model-picture]');
    box.tabIndex = -1;
    document.body.addEventListener('htmx:beforeSwap', (e) => {
      if (e.detail.target === box) box.dataset.focus = box.contains(document.activeElement) ? 'in' : '';
    });
    document.body.addEventListener('htmx:afterSwap', (e) => {
      if (e.detail.target !== box) return;
      const ready = box.querySelector('.cc-pic-img');
      if (ready && box.dataset.was !== 'ready') {
        const announce = document.getElementById('announce');
        if (announce) announce.textContent = 'Your model is drawn';
      }
      box.dataset.was = ready ? 'ready' : '';
      if (box.dataset.focus === 'in' && !box.contains(document.activeElement)) {
        (box.querySelector('button') || box).focus({ preventScroll: true });
      }
      delete box.dataset.focus;
    });
  }
}

// 13b. Profile: the drawn figure in the middle takes the choices as they are made: the model's height (on "Any", the
//      height in cm under Sizes), build (on "Any", the one his own height and weight under Sizes give), skin, hair
//      colour, haircut and beard, and says them in words under it. The
//      outlines of every build and haircut come with the page (#figure-data, from figure.py). A new build or height is
//      reached in a short eased change (200 ms); skin and hair fade (app.css); nothing moves for people who ask their
//      device for less motion.
if (profileCreator) {
  const svg = profileCreator.querySelector('[data-figure]');
  const data = JSON.parse(document.getElementById('figure-data').textContent);
  const form = document.getElementById('about-you');
  const man = svg.querySelector('.fig-man');
  const said = profileCreator.querySelector('[data-figure-words]');
  const still = window.matchMedia('(prefers-reduced-motion: reduce)');
  const parts = ['skin', 'tee', 'briefs', 'lines', 'creases'];
  const choice = (group) => {
    const on = form.querySelector(`input[name="${group}"]:checked`);
    return on ? on.value : '';
  };
  const centimetres = () => {
    const field = form.elements.height_cm;
    const typed = Math.round(Number(field.value));
    const cm = Number.isFinite(typed) && field.value !== '' ? typed : Number(field.defaultValue);
    return Math.max(data.lowest, Math.min(data.highest, cm));
  };
  // The customer's own build, for a build left on "Any": worked out from the height and weight under Sizes as
  // person.py does (weight / height², data.ownBuilds), once any of height, weight, chest or waist is no longer the
  // example's (data.example). Until then, and with a build chosen, there is none. What the form would refuse or
  // correct on saving (profile.py) is read here the same way.
  const typedNumber = (name, low, high, whole) => {
    const field = form.elements[name];
    const text = field.value.replace(',', '.').trim();
    const number = Number(text);
    if (text === '' || !Number.isFinite(number)) return whole ? Number(field.defaultValue) : null;
    if (whole) return Math.max(low, Math.min(high, Math.trunc(number)));
    return number >= low && number <= high ? Math.round(number * 10) / 10 : null;
  };
  const ownBuild = () => {
    if (choice('build')) return null;
    const body = {
      height_cm: typedNumber('height_cm', data.lowest, data.highest, true), weight_kg: typedNumber('weight_kg', 40, 200, true),
      chest_cm: typedNumber('chest_cm', 70, 150, false), waist_cm: typedNumber('waist_cm', 55, 150, false),
    };
    if (Object.keys(body).every((key) => body[key] === data.example[key])) return null;
    const ratio = body.weight_kg / ((body.height_cm / 100) ** 2);
    const found = data.ownBuilds.find(([below]) => below === null || ratio < below);
    return found ? { label: found[1], figure: found[2] } : null;
  };
  const NUMBER = /-?\d+(?:\.\d+)?/g;
  // An outline part of the way from one shape to another of the same build of numbers (figure.py keeps them so).
  const between = (from, to, t) => {
    const a = from.match(NUMBER) || [];
    const b = to.match(NUMBER) || [];
    if (t >= 1 || a.length !== b.length) return to;
    let i = 0;
    return to.replace(NUMBER, () => {
      const value = Number(a[i]) + (Number(b[i]) - Number(a[i])) * t;
      i += 1;
      return String(Math.round(value * 10) / 10);
    });
  };
  const place = (scale) => {
    man.setAttribute('transform', `matrix(${scale.toFixed(4)} 0 0 ${scale.toFixed(4)} 0 ${(400 * (1 - scale)).toFixed(2)})`);
    man.dataset.scale = scale.toFixed(4);
  };
  const drawBody = (paths) => parts.forEach((part) => {
    svg.querySelectorAll(`[data-part="${part}"]`).forEach((path) => path.setAttribute('d', paths[part]));
  });
  let shown = { scale: Number(man.dataset.scale), paths: Object.fromEntries(parts.map((part) => [part, svg.querySelector(`[data-part="${part}"]`).getAttribute('d')])) };
  let moving = 0;
  const words = () => {
    const height = { short: 'short', medium: 'average height', tall: 'tall' }[choice('height')] || `${centimetres()} cm`;
    const build = choice('build');
    const skin = choice('skin');
    const colour = choice('hair');
    const cut = choice('cut');
    let hair = 'any hair';
    if (cut === 'shaved') hair = 'shaved head';
    else if (cut || colour) hair = `${[cut && data.cut[cut], colour && data.hairColour[colour].label].filter(Boolean).join(' ')} hair`;
    const beard = { none: 'clean-shaven', stubble: 'stubble', short: 'short beard', full: 'full beard' }[choice('beard')];
    const own = ownBuild();
    const all = [height, build ? `${data.build[build]} build` : own ? `${own.label} build` : 'any build', skin ? `${data.skin[skin].label} skin` : 'any skin tone', hair];
    if (beard) all.push(beard);
    const text = all.join(', ');
    return text.charAt(0).toUpperCase() + text.slice(1);
  };
  const redraw = () => {
    // Colours, hair and beard change at once (the colours fade by themselves, app.css).
    const skin = choice('skin');
    const colour = choice('hair');
    svg.style.setProperty('--skin', skin ? data.skin[skin].colour : data.paper);
    svg.style.setProperty('--detail', skin ? data.skin[skin].detail : data.paperDetail);     // the lines on the skin
    svg.style.setProperty('--hair', colour ? data.hairColour[colour].colour : data.paper);
    const cut = data.hair[choice('cut')] ? choice('cut') : 'short';
    svg.querySelector('[data-part="hair"]').setAttribute('d', data.hair[cut].front);
    svg.querySelector('[data-part="hair-back"]').setAttribute('d', data.hair[cut].back);
    svg.querySelectorAll('.fig-hair').forEach((path) => path.classList.toggle('shaved', cut === 'shaved'));
    const beard = choice('beard');
    const beardPath = svg.querySelector('[data-part="beard"]');
    beardPath.setAttribute('d', data.beards[beard] || '');
    beardPath.setAttribute('class', `fig-beard${beard ? ` ${beard}` : ''}`);
    said.textContent = words();
    // The body and the height move, from wherever they are now.
    const target = {
      scale: (data.heights[choice('height')] || centimetres()) / data.reference,
      paths: data.builds[choice('build') || (ownBuild() || { figure: 'average' }).figure],
    };
    const from = shown;
    const same = from.scale === target.scale && parts.every((part) => from.paths[part] === target.paths[part]);
    if (same) return;
    moving += 1;
    const run = moving;
    const start = performance.now();
    const step = (now) => {
      if (run !== moving) return;                              // a newer change took over from here
      // (A frame's time can be a little before the change was made: never before the start, so nothing moves back.)
      const t = still.matches ? 1 : Math.max(0, Math.min(1, (now - start) / 200));
      const eased = 1 - (1 - t) ** 3;                          // ease-out: quick at first, settling gently
      shown = {
        scale: from.scale + (target.scale - from.scale) * eased,
        paths: Object.fromEntries(parts.map((part) => [part, between(from.paths[part], target.paths[part], eased)])),
      };
      place(shown.scale);
      drawBody(shown.paths);
      if (t < 1) requestAnimationFrame(step);
      else shown = target;
    };
    if (still.matches) step(start);
    else requestAnimationFrame(step);
  };
  const FIGURE = new Set(['height', 'build', 'skin', 'hair', 'cut', 'beard', 'height_cm', 'weight_kg', 'chest_cm', 'waist_cm']);
  form.addEventListener('input', (e) => { if (FIGURE.has(e.target.name)) redraw(); });
  form.addEventListener('change', (e) => { if (FIGURE.has(e.target.name)) redraw(); });
  redraw();          // the choices as the browser kept them (Back, a reload), which may not be the ones saved
}

// 13c. Profile: the Stores tab. At least one store with products stays ticked: unticking the last one ticks it again
//      at once, and a line under the stores says why (also to a screen reader). A store with no products yet
//      (data-empty: only pasted links come from it) does not count, however many of those are ticked. Without
//      JavaScript the save says it instead.
const storePick = document.querySelector('[data-store-pick]');
if (storePick) {
  const storeSaid = document.querySelector('[data-store-said]');
  storePick.addEventListener('change', (e) => {
    const box = e.target;
    const ticked = storePick.querySelectorAll('input[name=stores]:not([data-empty]):checked').length;
    if (!box.checked && !box.hasAttribute('data-empty') && ticked === 0) {
      box.checked = true;
      storeSaid.textContent = 'At least one store with products must stay ticked: your pieces need a store to come from.';
      storeSaid.hidden = false;
      const announce = document.getElementById('announce');
      if (announce) announce.textContent = storeSaid.textContent;
    } else {
      storeSaid.hidden = true;       // any other tick or untick takes the line away again
      storeSaid.textContent = '';
    }
  });
}

// 13d. Profile: the style chat (_style_chat.html). While a message is on its way to the server (and from there to
//      Google, which can take some seconds), the page says so: the button, which HTMX switches off, reads
//      "Sending…", a line under the field says the answer can take a few seconds, and the live region reads it out.
//      After it, HTMX puts the whole chat in again, with the answer and the brief it suggests. The keyboard stays
//      in the message field (the new one, in place of the one that was typed in), so the next message can be
//      written at once; the page moves so that the answer and the field are on the screen together; and the new
//      answer, or what went wrong, is read out by the page's one live region (base.html), which was on the page
//      before the answer came. A message that no answer came back for (the connection was cut, or the server
//      answered with an error) is said under the field, with his words still in it. It does not say whether the
//      message was counted: from here that cannot be known.
const chatHeard = (words) => {
  const announce = document.getElementById('announce');
  if (announce) announce.textContent = announce.textContent === words ? `${words}\u00a0` : words;   // the same words again are read again
};
const chatForm = (e) => {
  const form = e.detail.elt;
  return form instanceof Element && form.matches('#style-chat .chat-say') ? form : null;
};
document.body.addEventListener('htmx:beforeRequest', (e) => {
  const form = chatForm(e);
  if (!form) return;
  const button = form.querySelector('button');
  const wait = form.querySelector('[data-chat-wait]');
  if (button) button.textContent = 'Sending…';
  if (wait) {
    wait.textContent = 'Sending your message. The answer can take a few seconds.';
    wait.classList.remove('flash', 'bad');
    wait.hidden = false;
    chatHeard(wait.textContent);
  }
  form.setAttribute('aria-busy', 'true');
});
['htmx:sendError', 'htmx:timeout', 'htmx:responseError'].forEach((name) => {
  document.body.addEventListener(name, (e) => {
    const form = chatForm(e);
    if (!form || (e.detail.xhr && e.detail.xhr.status === 409)) return;      // 409: the page is reloaded (11)
    const button = form.querySelector('button');
    const wait = form.querySelector('[data-chat-wait]');
    if (button) button.textContent = 'Send';
    form.removeAttribute('aria-busy');
    if (!wait) return;
    wait.textContent = name === 'htmx:responseError'
      ? 'Something went wrong with that message. Load the page again and try once more.'
      : 'No answer came back. Check your connection and send it again.';
    wait.classList.add('flash', 'bad');
    wait.hidden = false;
    chatHeard(wait.textContent);
  });
});
// The answer and the field on the screen together: the page moves up until the field and Send are above whatever
// stands at the bottom of the screen (the Save bar, the tab bar, a phone's keyboard), but never so far that the
// first line of the answer leaves at the top, under the tabs that stick there. A long answer is read first.
const chatInView = (chat, said, field) => {
  const gap = 8;
  const view = window.visualViewport;
  let floor = view ? view.offsetTop + view.height : window.innerHeight;
  document.querySelectorAll('.cc-save, nav.tabs').forEach((bar) => {
    const box = bar.getBoundingClientRect();
    if (box.height && box.top > window.innerHeight / 2) floor = Math.min(floor, box.top);
  });
  const tabs = document.querySelector('.cc-tabs');
  const ceiling = tabs ? Math.max(0, tabs.getBoundingClientRect().bottom) : 0;
  const button = chat.querySelector('.chat-say button');
  const lowest = Math.max(field.getBoundingClientRect().bottom, button ? button.getBoundingClientRect().bottom : 0);
  const first = said.getBoundingClientRect().top - gap - ceiling;      // how far the answer's start is below the top
  const by = first < 0 ? first : Math.min(lowest + gap - floor, first);
  if (by > 0 || first < 0) window.scrollBy({ top: by, behavior: 'auto' });      // at once: he is about to type
};
document.body.addEventListener('htmx:afterSwap', (e) => {
  const was = e.detail.target;
  if (!(was instanceof Element) || was.id !== 'style-chat') return;
  const chat = document.getElementById('style-chat');
  if (!chat) return;
  const field = chat.querySelector('.chat-say textarea');
  if (field) {
    field.focus({ preventScroll: true });
    field.setSelectionRange(field.value.length, field.value.length);     // after his words, when they came back unsent
  }
  const said = chat.querySelector('[data-chat-said]') || chat.querySelector('[data-chat-new]');
  if (!said) return;
  if (field) chatInView(chat, said, field);
  let words = said.textContent.replace(/\s+/g, ' ').trim();
  if (!said.matches('[data-chat-said]') && chat.querySelector('[data-brief="suggested"]')) {
    words += ' A suggested style brief is below. It is not in use yet.';
  }
  chatHeard(words);
});

// 14. Profile: the colours as swatches to tap. Once: a colour you like, numbered in the order you tapped it (1 counts
//     most, which is how the plan reads "most important first"). Twice: a colour to avoid. Three times: neither.
//     The swatches only fill in About you's two text fields ("Colours you like", "Colours to avoid") with the colours'
//     names, in the order tapped, so what is saved is exactly what typing them would save, and a tap counts as a
//     change not yet saved (13). The fields are hidden while the swatches work; without JavaScript the swatches stay
//     hidden and the fields are typed in.
const swatchGrid = document.querySelector('[data-swatches]');
if (swatchGrid) {
  const swatchForm = swatchGrid.closest('form');
  const likedField = swatchForm.elements.liked;
  const avoidField = swatchForm.elements.refused;
  const swatches = [...swatchGrid.querySelectorAll('[data-colour]')];
  const said = swatchGrid.querySelector('[data-swatch-said]');
  const known = swatches.map((swatch) => swatch.dataset.colour);       // the names, as the fields write them
  const ordinals = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth'];
  // What the page was loaded with (or what the browser kept in the fields): names, most important first.
  const read = (field) => field.value.split(',').map((name) => name.trim().toLowerCase())
    .filter((name, at, all) => known.includes(name) && all.indexOf(name) === at);
  let liked = read(likedField);
  let avoided = read(avoidField).filter((name) => !liked.includes(name));
  // Each swatch shows its state (app.css draws it from data-state) and says it to a screen reader:
  // "Navy: liked, first", "Black: avoided", or just "Olive".
  const show = () => swatches.forEach((swatch) => {
    const name = swatch.dataset.colour;
    const place = liked.indexOf(name);
    const label = swatch.querySelector('span').textContent;
    let state = '';
    let words = label;
    if (place >= 0) {
      state = 'like';
      words = `${label}: liked, ${ordinals[place] || 'number ' + (place + 1)}`;
    } else if (avoided.includes(name)) {
      state = 'avoid';
      words = `${label}: avoided`;
    }
    swatch.dataset.state = state;
    swatch.setAttribute('aria-pressed', String(state !== ''));
    swatch.setAttribute('aria-label', words);
    swatch.querySelector('b').textContent = place >= 0 ? String(place + 1) : '';
  });
  swatchGrid.addEventListener('click', (e) => {
    const swatch = e.target.closest('[data-colour]');
    if (!swatch) return;
    const name = swatch.dataset.colour;
    if (liked.includes(name)) {                   // liked: now avoided, and the colours liked after it move up one
      liked = liked.filter((other) => other !== name);
      avoided.push(name);
    } else if (avoided.includes(name)) {          // avoided: now neither
      avoided = avoided.filter((other) => other !== name);
    } else {                                      // neither: liked, after the ones liked before it
      liked.push(name);
    }
    likedField.value = liked.join(', ');
    avoidField.value = avoided.join(', ');
    show();
    said.textContent = swatch.getAttribute('aria-label');     // a screen reader hears the new state
  });
  show();
  swatchGrid.hidden = false;
  swatchForm.querySelector('[data-typed-colours]').hidden = true;
}

// 15. "See it move": an outfit's AI video (videos.py, _video.html). The part of the picture box about the video
//     (.look-vid) is filled by HTMX on its own. A video that is ready lies over the picture (.vid.on): it plays once,
//     muted (with "reduce motion" asked for in the device's settings it does not play by itself, and shows its last
//     frame) and rests on its last frame. The front picture's video (data-turns) is then turned by dragging sideways
//     across it or with the arrow keys: a slider, its value in degrees (a drag across the whole picture is one full
//     turn). The video of another of the outfit's pictures (walking, the café …) only plays. "Play again" plays it from
//     the start; "Show picture" goes back to the picture and its dots. Dragging uses the turn kept with every frame
//     a keyframe (.vid-drag) where there is one, else the clip itself (its first data-turn-seconds).
{
  const still = window.matchMedia('(prefers-reduced-motion: reduce)');
  const STEP = 15;                  // degrees per arrow key; Page Up and Page Down turn a quarter
  const parts = (vid) => ({
    clip: vid.querySelector('.vid-clip'),
    drag: vid.querySelector('.vid-drag'),
    turn: vid.querySelector('.vid-turn'),
  });
  // Where a video can go to: before it has loaded, the time is kept and set once it knows its length.
  const seek = (video, time) => {
    if (video.readyState >= 1) {
      video.currentTime = Math.max(0, Math.min(time, video.duration - 0.05));
    } else {
      video.dataset.at = String(time);
      video.preload = 'auto';
      if (video.networkState === 0 || video.networkState === 3) video.load();
    }
  };
  document.addEventListener('loadedmetadata', (e) => {
    const video = e.target;
    if (!(video instanceof HTMLVideoElement) || !('at' in video.dataset)) return;
    const time = Number(video.dataset.at);
    delete video.dataset.at;
    seek(video, time === Infinity ? video.duration : time);
  }, true);
  // Showing the clip itself (to play), or the turn (to drag).
  const show = (vid, which) => {
    const { clip, drag } = parts(vid);
    if (!drag) return clip;
    clip.hidden = which !== clip;
    drag.hidden = which !== drag;
    if (which === drag) clip.pause();
    return which;
  };
  const play = (vid) => {
    const { clip } = parts(vid);
    show(vid, clip);
    clip.preload = 'auto';
    clip.currentTime = 0;
    clip.play().catch(() => {});      // a browser that will not play it by itself: it shows its first frame
  };
  // The video over the picture: played once, or (reduce motion) resting on its last frame at once.
  const open = (vid, focus) => {
    vid.classList.add('on');
    const { clip, turn } = parts(vid);
    if (still.matches) {
      show(vid, clip);
      seek(clip, Infinity);
    } else {
      play(vid);
    }
    if (focus) turn.focus({ preventScroll: true });
  };
  // Back to the picture, and its dots.
  const shut = (vid) => {
    const { clip, drag } = parts(vid);
    clip.pause();
    if (drag) drag.pause();
    vid.classList.remove('on');
  };
  const close = (vid) => {
    shut(vid);
    vid.querySelector('.vid-pill').focus({ preventScroll: true });
  };
  // Turning: `degrees` from 0 to 360 is a moment in the turn.
  const turnTo = (vid, degrees) => {
    const { clip, drag, turn } = parts(vid);
    const value = Math.round(Math.max(0, Math.min(360, degrees)));
    const video = show(vid, drag || clip);
    const span = drag && drag.readyState >= 1 ? drag.duration : Number(vid.dataset.turnSeconds) || 6;
    video.pause();
    seek(video, (value / 360) * span);
    turn.setAttribute('aria-valuenow', String(value));
    turn.setAttribute('aria-valuetext', `${value} degrees`);
  };
  const degreesOf = (vid) => Number(parts(vid).turn.getAttribute('aria-valuenow')) || 0;

  document.addEventListener('click', (e) => {
    const vid = e.target.closest('[data-vid]');
    if (!vid) return;
    if (e.target.closest('[data-vid-open]')) open(vid, true);
    else if (e.target.closest('[data-vid-again]')) play(vid);
    else if (e.target.closest('[data-vid-close]')) close(vid);
  });
  // Dragging sideways across the video turns the model (a drag across its whole width is one full turn).
  let held = null;
  document.addEventListener('pointerdown', (e) => {
    const turn = e.target.closest('[data-turns] .vid-turn');
    if (!turn || e.button !== 0) return;
    const vid = turn.closest('[data-vid]');
    held = { vid, turn, x: e.clientX, from: degreesOf(vid), width: turn.getBoundingClientRect().width };
    turn.setPointerCapture(e.pointerId);
    turn.classList.add('held');
    turnTo(vid, held.from);
  });
  document.addEventListener('pointermove', (e) => {
    if (!held) return;
    turnTo(held.vid, held.from + ((e.clientX - held.x) / held.width) * 360);
  });
  const letGo = () => {
    if (!held) return;
    held.turn.classList.remove('held');
    held = null;
  };
  document.addEventListener('pointerup', letGo);
  document.addEventListener('pointercancel', letGo);
  // The arrow keys on the video turn it, and only it: the outfit row does not move on (6), the page does not scroll.
  document.addEventListener('keydown', (e) => {
    const turn = e.target.closest && e.target.closest('[data-turns] .vid-turn');
    if (!turn || e.altKey || e.ctrlKey || e.metaKey) return;
    const vid = turn.closest('[data-vid]');
    const now = degreesOf(vid);
    const to = {
      ArrowRight: now + STEP, ArrowUp: now + STEP, ArrowLeft: now - STEP, ArrowDown: now - STEP,
      PageUp: now + 90, PageDown: now - 90, Home: 0, End: 360,
    }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    turnTo(vid, to);
  }, true);

  // What HTMX puts in. A video that has just been made plays (data-play) and, on the outfit on screen, is announced
  // in the page's one live region ("Video ready"); so is the start of its making ("Making the video"), once, not
  // at each of the few seconds' asks that follow. Keyboard focus that was in the part that was replaced goes to what
  // took its place: the box to tick or the button that makes the video (the offer's words describe both; the offer is
  // brought into view first, bringUp), the video itself, "See it move", or the outfit while the video is made.
  const isVid = (el) => el instanceof Element && el.matches('.look-vid');
  const tell = (words) => {
    const announce = document.getElementById('announce');    // the same words again are read out only if they change
    if (announce) announce.textContent = announce.textContent === words ? `${words}\u00a0` : words;
  };
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    const box = e.detail.target;
    if (!isVid(box)) return;
    if (box.contains(document.activeElement) || document.activeElement === box.closest('[data-slide]')) {
      box.dataset.focus = 'in';
    }
    box.dataset.making = box.querySelector('.vid-bar.wait') ? 'was' : '';
  });
  // Whether this box's outfit is the one on screen in the row (not swiped away meanwhile).
  const inRow = (box) => {
    const slide = box.closest('[data-slide]');
    const row = slide && slide.parentElement;
    return !row || Math.round(row.scrollLeft / row.clientWidth) === [...row.children].indexOf(slide);
  };
  // A video left showing when the row moves on to another outfit goes back to its picture. Otherwise, coming back
  // to that outfit later, the model stood there (the video's last frame) without the dots on his pieces, and nothing
  // said why. "See it move" plays it again.
  if (reel) {
    let rest;
    reel.addEventListener('scroll', () => {
      clearTimeout(rest);
      rest = setTimeout(() => reel.querySelectorAll('.vid.on').forEach((vid) => { if (!inRow(vid)) shut(vid); }), 200);
    }, { passive: true });
  }
  // The offer stands under the picture, in place of its line and the small pictures (app.css, .vid-bar.ask). On a short phone
  // that is below the tab bar, out of sight: a tap on "See it move" would seem to do nothing, and keyboard focus would
  // go to a button nobody can see. So the page goes up just far enough for the whole offer to show above the tab bar
  // (the room html's scroll-padding-bottom keeps for it), never so far that its top leaves the screen; only the
  // page, never the row of outfits. At once where less motion is asked for, else a short glide. The same for every
  // kind of offer: what a video is, why one was not made, that none are left today. It only ever brings up an offer
  // that is below: one that comes while the customer has read on past the picture (a video that could not be made,
  // a minute after the tap) is above the screen, and the page stays where he is.
  const bringUp = (offer) => {
    const room = innerHeight - (parseFloat(getComputedStyle(document.documentElement).scrollPaddingBottom) || 0);
    const { top, bottom } = offer.getBoundingClientRect();
    const by = Math.min(bottom - room, top);
    if (by > 0) window.scrollBy({ top: by, behavior: still.matches ? 'auto' : 'smooth' });
  };
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const box = e.detail.target;
    if (!isVid(box)) return;
    const focus = box.dataset.focus === 'in';
    const wasMaking = box.dataset.making === 'was';
    delete box.dataset.focus;
    delete box.dataset.making;
    if (box.querySelector('.vid-bar.wait') && !wasMaking) tell('Making the video');
    const vid = box.querySelector('[data-vid][data-play]');
    if (vid) {
      // It plays where it can be seen: on the outfit on screen. On another one (swiped away meanwhile) the picture
      // stays, with "See it move" to play it.
      vid.removeAttribute('data-play');
      if (!inRow(box)) {
        vid.classList.remove('on');
        return;
      }
      open(vid, focus);
      tell('Video ready');
      return;
    }
    // An offer on the outfit on screen (after a tap, or when a video being made could not be) is brought into view.
    const offer = box.querySelector('.vid-bar.ask');
    if (offer && inRow(box)) bringUp(offer);
    if (!focus) return;
    const next = box.querySelector('.vid-bar input[type="checkbox"], .vid-bar button, .vid-pill');
    if (next) next.focus({ preventScroll: true });
    else if (box.closest('[data-slide]')) box.closest('[data-slide]').focus({ preventScroll: true });
  });
}

// 17. The wardrobe is the outfits he said yes to (yes.py): the two answers under an outfit, "Add to my wardrobe" and
//     "Not for me". Each is a plain form, and the whole page comes back after it (the total, what every other outfit
//     would add and their order change with a yes).
// 17a. On a phone the answers are not under the outfit, where a short screen hides them below the tab bar: what a yes
//      adds, the warning if it would take him over his budget, and the two answers stand in a bar that stays above
//      the tab bar (#dock, app.css), for the outfit that is showing. The outfit's own box (.yes-box, outfits.html)
//      is moved in there, and back to its outfit when another one shows or the window becomes a computer's: the same
//      forms and buttons, in one place at a time. The page is told the bar's height (--dock-h), so its foot and the
//      picture leave room for it. Without JavaScript the box simply stays under its outfit.
const dock = document.getElementById('dock');
const answerOnScreen = () => {     // the box with the answers of the outfit on screen, wherever it stands now
  const row = document.getElementById('reel');
  if (!row) return null;
  const slide = row.querySelectorAll('[data-slide]')[Math.round(row.scrollLeft / row.clientWidth)];
  return (dock && dock.querySelector('[data-answer]')) || (slide && slide.querySelector('[data-answer]')) || null;
};
if (dock && document.getElementById('reel')) {
  const row = document.getElementById('reel');
  const phone = window.matchMedia('(max-width: 759.98px)');
  const all = [...row.querySelectorAll('[data-slide]')];
  // Each outfit's box, and a mark that keeps its place in the outfit while it is in the bar.
  const boxes = new Map();
  all.forEach((slide) => {
    const box = slide.querySelector('[data-answer]');
    if (box) boxes.set(slide, { box, home: document.createComment('its answers are in the bar above the tabs') });
  });
  let inDock = null;
  const measure = () => document.documentElement.style.setProperty('--dock-h', `${dock.hidden ? 0 : dock.offsetHeight}px`);
  const sync = () => {
    const want = (phone.matches && boxes.get(all[Math.round(row.scrollLeft / row.clientWidth)])) || null;
    if (want === inDock) return;
    const held = inDock && inDock.box.contains(document.activeElement) ? document.activeElement : null;
    if (inDock) inDock.home.replaceWith(inDock.box);
    inDock = want;
    if (want) {
      want.box.replaceWith(want.home);
      dock.append(want.box);
      // The buttons of an outfit that was not on screen were out of the Tab order (6a): these are the ones to press now.
      want.box.querySelectorAll('[data-tab]').forEach((el) => {
        if (el.dataset.tab) el.setAttribute('tabindex', el.dataset.tab);
        else el.removeAttribute('tabindex');
        delete el.dataset.tab;
      });
      // Keyboard focus that was on an answer stays on the same answer, now of the outfit that shows.
      const twin = held && want.box.querySelector(held.matches('.quiet') ? '.quiet' : '.btn.yes');
      if (held) (twin || want.box.querySelector('button')).focus({ preventScroll: true });
    }
    dock.hidden = !want;
    measure();
  };
  row.addEventListener('scroll', sync, { passive: true });
  phone.addEventListener('change', sync);
  if ('ResizeObserver' in window) new ResizeObserver(measure).observe(dock);
  sync();
}

// 17b. After an answer the page has come back (on the next outfit in line: its address names it, app.py). It is
//      scrolled to where it was when he answered, so he goes on from there and need not scroll down again for every
//      outfit. If the line that says what was done ("Added the outfit with … Undo") is then above the screen, it
//      stays in sight at the screen's top while he is scrolled down (app.css, .said.in-sight).
//      After an answer given with the keyboard, the keyboard would be at the page's top, some twenty presses of Tab
//      from the next answer. So it is put where the answering goes on: on "Add to my wardrobe" of the outfit now
//      showing. Under My outfits, where the next button would take another outfit out, it goes to Undo in the line
//      that says what was done. That line is read out to a screen reader, as it was there before the page finished
//      loading. Only after the keyboard gave the answer: after a tap or a click the keyboard is given nothing (a
//      button that had it would say yes at the next press of the space bar, meant to scroll).
//      Both are noted while the form is sent, kept for this tab only and forgotten at once.
document.addEventListener('submit', (e) => {
  const form = e.target instanceof HTMLFormElement ? e.target : null;
  if (!form || !form.matches('form.save, form.no, [data-answered] form')) return;
  const by = e.submitter || document.activeElement;
  try {
    if (document.getElementById('reel')) window.sessionStorage.setItem('answered-at', String(Math.round(window.scrollY)));
    if (by instanceof Element && by.matches(':focus-visible')) window.sessionStorage.setItem('answered-by-keyboard', '1');
  } catch (err) { /* no storage (private mode): the page comes back at its top, the keyboard with it, as without this */ }
});
(() => {
  let byKeyboard = false;
  let scrolledTo = null;
  try {
    byKeyboard = window.sessionStorage.getItem('answered-by-keyboard') === '1';
    scrolledTo = window.sessionStorage.getItem('answered-at');
    window.sessionStorage.removeItem('answered-by-keyboard');
    window.sessionStorage.removeItem('answered-at');
  } catch (err) { /* as above */ }
  const said = document.querySelector('[data-answered]');
  if (!said && !(byKeyboard && document.getElementById('reel'))) return;
  const put = () => {
    if (said && scrolledTo !== null && document.getElementById('reel')) {
      const top = Math.max(0, Math.min(parseInt(scrolledTo, 10) || 0, document.documentElement.scrollHeight - window.innerHeight));
      window.scrollTo({ top, behavior: 'instant' });
      if (said.getBoundingClientRect().bottom < 8) said.classList.add('in-sight');
    }
    if (!byKeyboard) {
      // After a tap or a click: the address the page came back to names the outfit to show ("#outfit-…"), and the
      // browser gives that outfit the keyboard, with a ring around all of it. Nobody is using the keyboard: no ring.
      const here = document.activeElement;
      if (here instanceof HTMLElement && here.matches('[data-slide]')) here.blur();
      return;
    }
    const undo = said && said.querySelector('button');
    const box = answerOnScreen();
    const next = (document.querySelector('.looks.saved') || !box) ? undo : (box.querySelector('.btn.yes') || undo);
    if (next) next.focus({ preventScroll: true });
    const announce = document.getElementById('announce');
    if (said && announce) {
      const words = [...said.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent).join(' ');
      // A moment later: a screen reader reads a live region only when it changes after the page has been read in.
      setTimeout(() => {
        announce.textContent = `${words.replace(/\s+/g, ' ').trim()}${undo && next !== undo ? ' Undo is at the top of the page.' : ''}`;
      }, 300);
    }
  };
  // Once the page has loaded and the browser has gone to the outfit its address names: that step moves the keyboard too.
  if (document.readyState === 'complete') setTimeout(put, 0);
  else window.addEventListener('load', () => setTimeout(put, 0));
})();

// 16. Motion (app.css "Motion" says how things move, and that nothing does for people who ask their device for less
//     motion). Here: which way a page slides in, and a tap while it does (16a), the AI picture that develops in once
//     its file has arrived (16b), the heart as an outfit is saved (16c), and the budget bar's line going to its new
//     length (16d). How long each takes is read from app.css's tokens, never set here.
{
  const less = window.matchMedia('(prefers-reduced-motion: reduce)');
  const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const ms = (name) => parseFloat(token(name)) || 0;

  // 16a. Pages. Which way the new page's content slides in is said to the browser's view transition as its type when
  //      the page is shown: along the tabs (Outfits, Wardrobe, Shopping, Profile) "forward", from the right, or
  //      "back", from the left; through the browser's history (Back, Forward), the way it went. Anything else rises a
  //      little (app.css). And while a page slides in, the browser gives every tap to the page as a whole rather than
  //      to what is under the finger, so a quick tap (on the next tab, say) would be lost: a tap then ends the slide at
  //      once and goes on to what it was meant for (a link or a button is pressed, a field gets the focus).
  let sliding = null;       // the page change under way, if any
  let lostTap = false;      // a tap that began while it was
  const tabAt = (url) => {
    const path = new URL(url, window.location.href).pathname;
    return [...document.querySelectorAll('nav.tabs a')].findIndex((link) => link.pathname === path);
  };
  window.addEventListener('pagereveal', (e) => {
    const change = e.viewTransition;
    if (!change) return;
    sliding = change;
    change.finished.finally(() => {
      if (sliding === change) sliding = null;
    });
    const came = window.navigation && window.navigation.activation;
    if (!came || !came.from || !came.entry) return;
    let way = 0;
    if (came.navigationType === 'traverse') {
      way = came.entry.index - came.from.index;
    } else {
      const from = tabAt(came.from.url);
      const to = tabAt(came.entry.url);
      if (from >= 0 && to >= 0) way = to - from;
    }
    if (way) change.types.add(way > 0 ? 'forward' : 'back');
  });
  document.addEventListener('pointerdown', () => {
    if (!sliding) return;
    sliding.skipTransition();
    sliding = null;
    lostTap = true;
  }, true);
  document.addEventListener('click', (e) => {
    if (!lostTap) return;
    lostTap = false;
    if (e.target !== document.documentElement) return;       // it reached what it was meant for after all
    const under = document.elementFromPoint(e.clientX, e.clientY);
    const meant = under && under.closest('a[href], button, label, summary, input, select, textarea, [role="button"]');
    if (!meant) return;
    e.preventDefault();
    e.stopPropagation();
    if (meant.matches('select, textarea, input:not([type="checkbox"], [type="radio"], [type="submit"], [type="button"])')) meant.focus();
    else meant.click();
  }, true);

  // 16b. The AI picture develops in. When HTMX puts a finished picture in (drawn at last, or a small picture tapped), it
  //      stays hidden until its file has arrived, over the pieces' photos, or over the picture it replaces (kept for
  //      that moment, .look-was), and then comes up over them (app.css). With less motion asked for it simply shows
  //      once it is whole. Pictures of the outfits off screen that are still loading when the page opens do the same.
  const develop = (pic, was) => {
    const img = pic.querySelector('img');
    if (!img) return;
    pic.dataset.develop = 'wait';
    let under = null;
    if (was) {
      under = document.createElement('div');
      under.className = 'look-was';
      under.setAttribute('aria-hidden', 'true');
      was.alt = '';
      under.append(was);
      pic.before(under);
    }
    const done = () => {
      delete pic.dataset.develop;
      if (under) under.remove();
    };
    const go = () => {
      if (pic.dataset.develop !== 'wait') return;
      if (less.matches) {
        done();
        return;
      }
      pic.dataset.develop = 'go';
      setTimeout(done, ms('--dur-slow') + 60);     // once it, and its dots, have come up
    };
    if (img.complete) {
      void getComputedStyle(pic).opacity;        // hidden first, so that it can come up from there
      go();
    } else {
      img.addEventListener('load', go, { once: true });
      img.addEventListener('error', done, { once: true });
      setTimeout(go, 10000);                       // a file that never quite arrives is shown as it is
    }
  };
  const isLook = (el) => el instanceof Element && el.matches('.look');
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    const box = e.detail.target;
    if (!isLook(box)) return;
    const img = box.querySelector('.look-pic img');
    box.lookWas = img && img.complete && img.naturalWidth ? img : null;
  });
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const box = e.detail.target;
    if (!isLook(box)) return;
    const was = box.lookWas;
    delete box.lookWas;
    const pic = box.querySelector('.look-pic');
    const img = pic && pic.querySelector('img');
    if (!img) return;
    if (was && was.src === img.src) {
      // The same picture again (kept under the band while "Draw again" draws, or a new version refused): the picture
      // that was on screen goes straight back in, so that not one frame is without it.
      img.replaceWith(was);
      return;
    }
    develop(pic, was);
  });
  const row = document.getElementById('reel');
  if (row) {
    const here = Math.round(row.scrollLeft / row.clientWidth);
    row.querySelectorAll('[data-slide]').forEach((slide, index) => {
      const img = slide.querySelector('.look-pic img');
      if (img && index !== here && !img.complete) develop(img.closest('.look-pic'), null);
    });
  }

  // 16c. The heart, as an outfit is saved: HTMX puts in the heart's new state, which grows into its place (app.css).
  let hearted = null;
  document.addEventListener('click', (e) => {
    const heart = e.target instanceof Element && e.target.closest('.heart');
    if (heart) hearted = heart.id;
  }, true);
  document.body.addEventListener('htmx:load', (e) => {
    const heart = hearted && document.getElementById(hearted);
    if (!heart || !e.target.contains(heart)) return;
    hearted = null;
    if (!heart.classList.contains('on')) return;
    heart.classList.add('pop');
    setTimeout(() => heart.classList.remove('pop'), ms('--dur-slow') + 50);
  });

  // 16d. The budget bar's line, when the total changes (a price level, a lock): it goes from its old length to the new
  //      one rather than jumping there. Only drawn differently (transform), so nothing on the page moves.
  let length = null;
  document.body.addEventListener('htmx:oobBeforeSwap', (e) => {
    if (!e.detail.target || e.detail.target.id !== 'summary') return;
    const line = e.detail.target.querySelector('.bar i');
    length = line ? parseFloat(line.style.width) : null;
  });
  document.body.addEventListener('htmx:oobAfterSwap', (e) => {
    // (HTMX says this on everything its answer has swapped in so far, once for each part: only the bar, for the bar.)
    const bar = e.detail.target && e.detail.target.id === 'summary' && e.target instanceof Element && e.target.id === 'summary';
    if (!bar) return;
    const line = e.target.querySelector('.bar i');
    const now = line && parseFloat(line.style.width);
    const from = length;
    length = null;
    if (!now || !from || from === now || less.matches) return;
    line.animate([{ transform: `scaleX(${from / now})` }, { transform: 'none' }],
      { duration: ms('--dur-slow'), easing: token('--ease-out') });
  });
}
