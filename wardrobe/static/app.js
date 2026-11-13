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
  const isBox = (el) => el instanceof Element && el.matches('.look');
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    const box = e.detail.target;
    if (isBox(box) && box.closest('.stage').contains(document.activeElement)) box.dataset.focus = 'in';
  });
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const box = e.detail.target;
    if (!isBox(box)) return;
    const slide = box.closest('[data-slide]');
    const ready = box.querySelector('.look-pic');
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
    const dot = ready && [...slide.querySelectorAll('.spot')].find(visible);
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
//     frame), rests on its last frame, and is then turned by dragging sideways across it or with the arrow keys: a
//     slider, its value in degrees (a drag across the whole picture is one full turn). "Play again" plays it from
//     the start; "Picture" goes back to the picture and its dots. Dragging uses the turn kept with every frame a
//     keyframe (.vid-drag) where there is one, else the clip itself (its first data-turn-seconds).
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
  const close = (vid) => {
    const { clip, drag } = parts(vid);
    clip.pause();
    if (drag) drag.pause();
    vid.classList.remove('on');
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
    const turn = e.target.closest('.vid-turn');
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
    const turn = e.target.closest && e.target.closest('.vid-turn');
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
  // in the page's one live region. Keyboard focus that was in the part that was replaced goes to what took its place:
  // the button that makes the video, the video itself, "See it move", or the outfit while the video is made.
  const isVid = (el) => el instanceof Element && el.matches('.look-vid');
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    const box = e.detail.target;
    if (isVid(box) && (box.contains(document.activeElement) || document.activeElement === box.closest('[data-slide]'))) {
      box.dataset.focus = 'in';
    }
  });
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const box = e.detail.target;
    if (!isVid(box)) return;
    const focus = box.dataset.focus === 'in';
    delete box.dataset.focus;
    const vid = box.querySelector('[data-vid][data-play]');
    if (vid) {
      // It plays where it can be seen: on the outfit on screen. On another one (swiped away meanwhile) the picture
      // stays, with "See it move" to play it.
      vid.removeAttribute('data-play');
      const slide = box.closest('[data-slide]');
      const row = slide && slide.parentElement;
      const inView = !row || Math.round(row.scrollLeft / row.clientWidth) === [...row.children].indexOf(slide);
      if (!inView) {
        vid.classList.remove('on');
        return;
      }
      open(vid, focus);
      const announce = document.getElementById('announce');    // the same words again are read out only if they change
      if (announce) announce.textContent = announce.textContent === 'Video ready' ? 'Video ready\u00a0' : 'Video ready';
      return;
    }
    if (!focus) return;
    const next = box.querySelector('.vid-bar button, .vid-pill');
    if (next) next.focus({ preventScroll: true });
    else if (box.closest('[data-slide]')) box.closest('[data-slide]').focus({ preventScroll: true });
  });
}
