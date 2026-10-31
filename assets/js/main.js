/* Dutch Cloud Solutions website: interactions and motion.
   No dependencies, no tracking. Everything degrades to static content without JavaScript. */
(function () {
  'use strict';

  var doc = document.documentElement;
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $ = function (sel, ctx) { return (ctx || document).querySelector(sel); };
  var $$ = function (sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); };

  /* ---------- Year ---------- */
  $$('[data-year]').forEach(function (el) { el.textContent = new Date().getFullYear(); });

  /* ---------- Hero entrance ---------- */
  function heroIn() { document.body.classList.add('is-loaded'); }
  if (document.fonts && document.fonts.ready) {
    Promise.race([document.fonts.ready, new Promise(function (r) { setTimeout(r, 600); })]).then(heroIn);
  } else { setTimeout(heroIn, 100); }

  /* ---------- Theme toggle ---------- */
  var themeBtn = $('[data-theme-toggle]');
  function setThemeLabel() {
    var dark = doc.getAttribute('data-theme') === 'dark';
    if (themeBtn) themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  }
  setThemeLabel();
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var next = doc.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      doc.setAttribute('data-theme', next);
      try { localStorage.setItem('dcs-theme', next); } catch (e) {}
      setThemeLabel();
    });
  }
  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  var onScheme = function (e) {
    var saved = null;
    try { saved = localStorage.getItem('dcs-theme'); } catch (err) {}
    if (!saved) { doc.setAttribute('data-theme', e.matches ? 'dark' : 'light'); setThemeLabel(); }
  };
  if (mq.addEventListener) mq.addEventListener('change', onScheme); else if (mq.addListener) mq.addListener(onScheme);

  /* ---------- Header: over hero, hide on scroll down, mobile menu ---------- */
  var header = $('.site-header');
  var hero = $('.hero');
  var menuBtn = $('[data-menu-toggle]');
  var lastY = window.scrollY;

  function closeMenu() {
    document.body.classList.remove('menu-open');
    if (menuBtn) { menuBtn.setAttribute('aria-expanded', 'false'); menuBtn.setAttribute('aria-label', 'Open menu'); }
  }
  if (menuBtn) {
    menuBtn.addEventListener('click', function () {
      var open = document.body.classList.toggle('menu-open');
      menuBtn.setAttribute('aria-expanded', String(open));
      menuBtn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      if (open) header.classList.remove('is-hidden');
    });
  }
  $$('.primary-nav a').forEach(function (a) { a.addEventListener('click', closeMenu); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });

  /* ---------- Scroll-driven effects (one rAF loop) ---------- */
  var video = $('.hero-video');
  var heroInner = $('.hero-inner');
  var ticking = false;
  function onScroll() {
    var y = window.scrollY;
    var heroH = hero ? hero.offsetHeight : 0;
    var overHero = y < heroH - 80;
    header.setAttribute('data-over-hero', overHero ? 'true' : 'false');
    if (!document.body.classList.contains('menu-open')) {
      header.classList.toggle('is-hidden', y > heroH && y > lastY + 4);
      if (y < lastY - 4) header.classList.remove('is-hidden');
    }
    lastY = y;
    if (!reduceMotion && hero && y < heroH) {
      var p = y / heroH;
      if (video) video.style.transform = 'translate3d(0,' + (y * 0.3).toFixed(1) + 'px,0) scale(' + (1.06 + p * 0.08).toFixed(3) + ')';
      if (heroInner) { heroInner.style.transform = 'translate3d(0,' + (y * -0.12).toFixed(1) + 'px,0)'; heroInner.style.opacity = String(Math.max(0, 1 - p * 1.4)); }
    }
    ticking = false;
  }
  window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();

  /* ---------- Hero video: pause control, reduced motion, offscreen pause ---------- */
  var pauseBtn = $('[data-hero-pause]');
  var userPaused = false;
  function setPaused(paused) {
    if (!video) return;
    if (paused) video.pause(); else { var pr = video.play(); if (pr && pr.catch) pr.catch(function () {}); }
    if (pauseBtn) {
      pauseBtn.setAttribute('aria-pressed', String(paused));
      pauseBtn.setAttribute('aria-label', paused ? 'Play background video' : 'Pause background video');
    }
  }
  if (video) {
    if (reduceMotion) { video.removeAttribute('autoplay'); userPaused = true; setPaused(true); }
    if (pauseBtn) pauseBtn.addEventListener('click', function () { userPaused = !video.paused; setPaused(userPaused); });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { if (!userPaused) { if (en.isIntersecting) setPaused(false); else video.pause(); } });
      }, { threshold: 0.05 }).observe(hero);
    }
  }

  /* ---------- Reveal on scroll ---------- */
  var revealTargets = $$('.reveal, .diagram, [data-lifecycle], [data-spectrum]');
  // stagger siblings in grids
  $$('.practice-grid, .fact-grid, .rules, .stat-grid').forEach(function (grid) {
    $$('.reveal', grid).forEach(function (el, i) { el.style.setProperty('--d', (i * 0.08) + 's'); });
    if (grid.classList.contains('reveal')) return;
  });
  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('is-visible'); io.unobserve(en.target); }
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });
    revealTargets.forEach(function (el) { io.observe(el); });
  } else {
    revealTargets.forEach(function (el) { el.classList.add('is-visible'); });
  }

  /* ---------- Scrollspy ---------- */
  var navLinks = $$('.primary-nav ul a');
  var sections = navLinks.map(function (a) { return $(a.getAttribute('href')); }).filter(Boolean);
  if ('IntersectionObserver' in window) {
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          navLinks.forEach(function (a) {
            var on = a.getAttribute('href') === '#' + en.target.id;
            a.classList.toggle('is-active', on);
            if (on) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
          });
        }
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    sections.forEach(function (s) { spy.observe(s); });
  }

  /* ---------- Accessible tabs helper ---------- */
  function initTabs(tabs, panels, opts) {
    opts = opts || {};
    function select(i, focus) {
      tabs.forEach(function (t, j) {
        var on = i === j;
        t.setAttribute('aria-selected', String(on));
        t.tabIndex = on ? 0 : -1;
        panels[j].hidden = !on;
      });
      if (focus) tabs[i].focus();
      if (opts.onSelect) opts.onSelect(i);
    }
    tabs.forEach(function (t, i) {
      t.addEventListener('click', function () { select(i); if (opts.onUser) opts.onUser(); });
      t.addEventListener('keydown', function (e) {
        var n = tabs.length, k = e.key, next = null;
        if (k === 'ArrowRight' || k === 'ArrowDown') next = (i + 1) % n;
        if (k === 'ArrowLeft' || k === 'ArrowUp') next = (i - 1 + n) % n;
        if (k === 'Home') next = 0;
        if (k === 'End') next = n - 1;
        if (next !== null) { e.preventDefault(); select(next, true); if (opts.onUser) opts.onUser(); }
      });
    });
    return select;
  }

  /* ---------- Sovereignty Spectrum: tabs with auto-cycle ---------- */
  var spectrum = $('[data-spectrum]');
  if (spectrum) {
    var tierTabs = $$('[role="tab"]', spectrum);
    var tierPanels = tierTabs.map(function (t) { return document.getElementById(t.getAttribute('aria-controls')); });
    var CYCLE = 5000, timer = null, current = 0, inView = false;
    tierTabs.forEach(function (t) { var bar = document.createElement('span'); bar.className = 'tier-progress'; t.appendChild(bar); });
    spectrum.style.setProperty('--cycle', (CYCLE / 1000) + 's');
    function restartProgress(i) {
      var bar = tierTabs[i].querySelector('.tier-progress');
      if (bar) { bar.style.animation = 'none'; void bar.offsetWidth; bar.style.animation = ''; }
    }
    var selectTier = initTabs(tierTabs, tierPanels, {
      onSelect: function (i) { current = i; restartProgress(i); },
      onUser: function () { stop(); spectrum.classList.add('is-paused'); }
    });
    function stop() { clearInterval(timer); timer = null; }
    function start() {
      if (reduceMotion || timer || spectrum.classList.contains('is-paused')) return;
      restartProgress(current);
      timer = setInterval(function () { selectTier((current + 1) % tierTabs.length); }, CYCLE);
    }
    if (reduceMotion) spectrum.classList.add('is-paused');
    spectrum.addEventListener('mouseenter', stop);
    spectrum.addEventListener('mouseleave', function () { if (inView) start(); });
    spectrum.addEventListener('focusin', stop);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { inView = en.isIntersecting; if (inView) start(); else stop(); });
      }, { threshold: 0.4 }).observe(spectrum);
    }
  }

  /* ---------- Offer tabs with sliding indicator ---------- */
  var tabsWrap = $('[data-tabs]');
  var selectOffer = null;
  if (tabsWrap) {
    var offerTabs = $$('.tab-list [role="tab"]', tabsWrap);
    var offerPanels = offerTabs.map(function (t) { return document.getElementById(t.getAttribute('aria-controls')); });
    var indicator = $('.tab-indicator', tabsWrap);
    var moveIndicator = function (i) {
      var t = offerTabs[i]; if (!t || !indicator) return;
      indicator.style.width = t.offsetWidth + 'px';
      indicator.style.transform = 'translateX(' + (t.offsetLeft - 4) + 'px)';
    };
    selectOffer = initTabs(offerTabs, offerPanels, { onSelect: moveIndicator });
    window.addEventListener('resize', function () {
      var i = offerTabs.findIndex(function (t) { return t.getAttribute('aria-selected') === 'true'; });
      moveIndicator(i < 0 ? 0 : i);
    });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { moveIndicator(0); });
    moveIndicator(0);
  }
  $$('[data-offer-tab]').forEach(function (a) {
    a.addEventListener('click', function () { if (selectOffer) selectOffer(a.getAttribute('data-offer-tab') === 'enterprise' ? 1 : 0); });
  });

  /* ---------- Count-up figures ---------- */
  var counters = $$('[data-count]');
  function countUp(el) {
    var target = parseFloat(el.getAttribute('data-count'));
    var dec = parseInt(el.getAttribute('data-decimals') || '0', 10);
    var t0 = null, dur = 1400;
    function step(ts) {
      if (!t0) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = (target * eased).toFixed(dec);
      if (p < 1) requestAnimationFrame(step); else el.textContent = target.toFixed(dec);
    }
    requestAnimationFrame(step);
  }
  if ('IntersectionObserver' in window && !reduceMotion) {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { countUp(en.target); cio.unobserve(en.target); } });
    }, { threshold: 0.6 });
    counters.forEach(function (c) { cio.observe(c); });
  }

  /* ---------- Card glow follows the pointer ---------- */
  $$('[data-glow]').forEach(function (card) {
    card.addEventListener('pointermove', function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      card.style.setProperty('--my', (e.clientY - r.top) + 'px');
    });
  });

  /* ---------- Video modal (YouTube loads only on demand, privacy-enhanced domain) ---------- */
  var modal = $('#video-modal');
  var slot = $('[data-video-slot]');
  var PLACEHOLDER = 'YOUR_YOUTUBE_ID';
  var lastFocus = null;
  function openVideo() {
    if (!modal) return;
    lastFocus = document.activeElement;
    var id = (modal.getAttribute('data-youtube-id') || '').trim();
    if (!id || id === PLACEHOLDER) {
      slot.innerHTML =
        '<div class="video-soon"><p class="eyebrow">Video</p><h3>Our introduction video is coming soon.</h3>' +
        '<p>Meanwhile, the sections below walk through both practices, the Sovereignty Spectrum and how an engagement runs.</p>' +
        '<p><a class="btn btn-cta" href="#contact" data-video-close>Talk to us instead</a></p></div>';
    } else {
      var iframe = document.createElement('iframe');
      iframe.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(id) + '?autoplay=1&rel=0&modestbranding=1';
      iframe.title = 'Dutch Cloud Solutions video';
      iframe.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
      iframe.allowFullscreen = true;
      iframe.referrerPolicy = 'strict-origin-when-cross-origin';
      slot.innerHTML = '';
      slot.appendChild(iframe);
    }
    if (typeof modal.showModal === 'function') modal.showModal(); else modal.setAttribute('open', '');
    if (video && !userPaused) video.pause();
  }
  function closeVideo() {
    if (!modal) return;
    slot.innerHTML = '';
    if (typeof modal.close === 'function' && modal.open) modal.close(); else modal.removeAttribute('open');
    if (video && !userPaused) setPaused(false);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  $$('[data-video-open]').forEach(function (b) { b.addEventListener('click', openVideo); });
  if (modal) {
    modal.addEventListener('click', function (e) {
      if (e.target === modal || e.target.closest('[data-video-close]')) closeVideo();
    });
    modal.addEventListener('cancel', function (e) { e.preventDefault(); closeVideo(); });
  }

  /* ---------- Contact form: compose an email, store nothing ---------- */
  var form = $('[data-contact-form]');
  if (form) {
    var err = $('.form-error', form);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var name = form.name.value.trim();
      var company = form.company.value.trim();
      var message = form.message.value.trim();
      var client = (form.querySelector('input[name="client"]:checked') || {}).value || '';
      if (!name || !company || !message) { err.hidden = false; return; }
      err.hidden = true;
      var subject = 'Introduction: ' + company;
      var body = 'Hello,\n\nI am ' + name + ' from ' + company + ', ' + client + '.\n\n' + message + '\n';
      window.location.href = 'mailto:info@dutchcloudsolutions.com?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
    });
  }
})();
