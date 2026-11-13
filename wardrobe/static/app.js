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
  const step = (direction) => {
    const from = goal === null ? shown() : goal;
    goal = Math.max(0, Math.min(slides.length - 1, from + direction));
    reel.scrollTo({ left: goal * reel.clientWidth, behavior: motion.matches ? 'auto' : 'smooth' });
    keep(goal);       // at once: 'Buy this outfit' may be pressed before the row has come to rest
  };
  // A single outfit has no arrows (outfits.html leaves them out): there is nowhere to move to.
  const prev = document.querySelector('.reel-nav.prev');
  const next = document.querySelector('.reel-nav.next');
  const ends = () => {
    if (!prev || !next) return;
    prev.disabled = reel.scrollLeft < 8;
    next.disabled = reel.scrollLeft > reel.scrollWidth - reel.clientWidth - 8;
  };
  if (prev && next) {
    prev.addEventListener('click', () => step(-1));
    next.addEventListener('click', () => step(1));
  }
  reel.addEventListener('scroll', () => {
    ends();
    clearTimeout(settled);
    settled = setTimeout(() => {      // the scroll has come to rest (after a swipe too)
      goal = null;
      keep(shown());
    }, 200);
  }, { passive: true });
  ends();
  document.addEventListener('keydown', (e) => {
    if (document.querySelector('dialog[open]') || e.target.closest('input, select, textarea')) return;
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
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

// 9. "Open all": every product page of one store, each in its own tab. Browsers
//    hold back tabs they did not expect; if that happens, say so.
document.addEventListener('click', (e) => {
  const button = e.target.closest('[data-open-all]');
  if (!button) return;
  const section = button.closest('.store-list');
  let held = 0;
  section.querySelectorAll('a.buy-product').forEach((link) => {
    if (link.getAttribute('href') === '#') return;
    const tab = window.open(link.href, '_blank');
    if (tab) tab.opener = null; else held += 1;
  });
  if (held) section.querySelector('.open-hint').hidden = false;
});

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

// 12. The starter banner on Outfits (a new customer's, until he saves his profile) stands where the budget bar would.
//     The picture on a phone is sized from that bar's height (--bar-h, see app.css), so here it is the banner's
//     real height, whatever its words wrap to on this screen.
const starter = document.querySelector('.starter');
if (starter && 'ResizeObserver' in window) {
  new ResizeObserver(() => {
    document.documentElement.style.setProperty('--bar-h', `${starter.getBoundingClientRect().height}px`);
  }).observe(starter);
}

// 13. Profile: About you is one form, the model and the photo are others, and sending either of those loads the page
//     again. Sizes, colours or a budget changed in About you and not yet saved would then be lost without a word, so
//     the page asks first. "Changed" is measured against what the page was loaded with, field by field.
const aboutYou = document.getElementById('about-you');
if (aboutYou) {
  const changed = () => [...aboutYou.elements].some((field) => {
    if (field.type === 'checkbox' || field.type === 'radio') return field.checked !== field.defaultChecked;
    if (field.tagName === 'SELECT') {
      const loaded = [...field.options].find((option) => option.defaultSelected) || field.options[0];
      return Boolean(loaded) && field.value !== loaded.value;
    }
    if (field.tagName === 'INPUT' || field.tagName === 'TEXTAREA') return field.value !== field.defaultValue;
    return false;
  });
  document.addEventListener('submit', (e) => {
    // (A form that already asked its own question and was told no, like deleting the photo, is not sent anyway.)
    if (e.defaultPrevented || e.target === aboutYou || !e.target.closest('#model') || !changed()) return;
    if (!window.confirm("You changed your sizes, colours or budget but didn't save them. Leave those changes unsaved?")) {
      e.preventDefault();
    }
  });
}
