/**
 * Demo Cinema Engine v7
 * Lesson tabs, theory inside, sidebar, trainer code+assistant, analytics fix, typewriter epilogue.
 */
(function () {
  'use strict';

  var TOTAL_SCENES  = 10;
  var LS_ACTIVE     = 'cinemaActive';
  var LS_SCENE      = 'cinemaScene';
  var LS_TRANSITION = 'cinemaTransition';
  var LS_DEMO_IDS   = 'cinemaDemoIds';
  var TYPEWRITER_MS = 32;

  function qs(s, c) { return (c || document).querySelector(s); }
  function qsa(s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function lsRemove(k) { try { localStorage.removeItem(k); } catch (e) {} }
  function getDemoIds() { try { return JSON.parse(lsGet(LS_DEMO_IDS)) || {}; } catch (e) { return {}; } }
  function currentPage() { return (document.body.getAttribute('data-cinema-scene') || '').toLowerCase(); }

  var TEXTS = {
    ege: {
      theoryIntro: 'Здесь собрана вся теория для ЕГЭ по информатике. Каждое задание — свой конспект.',
      theoryView: 'Изучай теорию перед решением задач. Конспекты доступны по каждому заданию ЕГЭ.',
      analyticsCharts: 'Столбчатая диаграмма — сколько процентов заданий каждого номера ты решаешь верно.',
      analyticsTab: 'Аналитика ЕГЭ',
      ratingLabel: 'Рейтинг по заданиям ЕГЭ',
    },
    oge: {
      theoryIntro: 'Здесь собрана вся теория для ОГЭ по информатике. Каждое задание — свой конспект.',
      theoryView: 'Изучай теорию перед решением задач. Конспекты доступны по каждому заданию ОГЭ.',
      analyticsCharts: 'Столбчатая диаграмма — сколько процентов заданий каждого номера ты решаешь верно.',
      analyticsTab: 'Аналитика ОГЭ',
      ratingLabel: 'Рейтинг по заданиям ОГЭ',
    },
  };
  function examTexts(ids) { var exam = (ids && ids.exam) || 'ege'; return TEXTS[exam] || TEXTS.ege; }

  var SECTION_INTRO = {
    schedule: 'Расписание — все уроки в одном месте. Никаких накладок и забытых занятий.',
    theory: 'Теория — конспекты по каждому заданию ЕГЭ. Открой и посмотри.',
    submissions: 'Задания от преподавателя. Дедлайны, условия — всё по-настоящему.',
    lesson: 'Классная комната — конспект, задания, материалы и диалог в одном уроке.',
    trainer: 'AI-тренажёр — пиши код, ищи ошибку, спрашивай помощника, проверяй ответ.',
    analytics: 'Аналитика — рейтинги по темам, прогноз балла и динамика успеваемости.',
    creator: 'Кто создал платформу — знакомство с автором.',
    final: 'Финал — платформа готова. Твоя сотка — вопрос дисциплины и алгоритма.'
  };

  function addEl(tag, cls, parent) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    (parent || document.body).appendChild(el);
    return el;
  }
  function removeEl(el) { if (el && el.parentNode) el.parentNode.removeChild(el); }

  function placeInstantCover() {
    if (lsGet(LS_ACTIVE) !== 'true') return;
    if (lsGet(LS_SCENE) === '0') return;
    var c = document.createElement('div');
    c.className = 'cinema-instant-cover';
    c.id = 'cinema-instant-cover';
    document.documentElement.appendChild(c);
  }
  placeInstantCover();

  /* ═══════════════════════════════════════════════════════════════════ */
  function CE() {
    this.scene = parseInt(lsGet(LS_SCENE) || '0', 10);
    this.transition = lsGet(LS_TRANSITION) || '';
    this.running = false;
    this._els = [];
    this._tids = [];
    this.ids = getDemoIds();
  }

  CE.prototype._t = function (fn, ms) {
    var self = this;
    var id = setTimeout(function () { if (self.running) fn(); }, ms);
    this._tids.push(id);
    return id;
  };
  CE.prototype._clearT = function () {
    this._tids.forEach(function (id) { clearTimeout(id); });
    this._tids = [];
  };
  CE.prototype._cleanup = function () {
    this._clearT();
    this._clearCurrentSpotlight(null, true);
    this._removeBlockingOverlay();
    this._els.forEach(function (el) { removeEl(el); });
    this._els = [];
    qsa('.cinema-neon-hud').forEach(function (e) { e.classList.remove('cinema-neon-hud'); });
    document.body.classList.remove('cinema-freeze');
  };

  CE.prototype._removeBlockingOverlay = function () {
    var el = document.getElementById('cinema-blocking-overlay');
    if (el && el.parentNode) removeEl(el);
  };

  CE.prototype._updateBlockingOverlay = function (left, top, w, h) {
    var vw = window.innerWidth, vh = window.innerHeight;
    var el = document.getElementById('cinema-blocking-overlay');
    if (!el) {
      el = addEl('div', 'cinema-blocking-overlay');
      el.id = 'cinema-blocking-overlay';
    }
    var r = left + w, b = top + h;
    var poly = 'polygon(0 0,' + vw + 'px 0,' + vw + 'px ' + top + 'px,' + r + 'px ' + top + 'px,' + r + 'px ' + b + 'px,' + left + 'px ' + b + 'px,' + left + 'px ' + top + 'px,' + vw + 'px ' + top + 'px,' + vw + 'px ' + vh + 'px,0 ' + vh + 'px,0 0)';
    el.style.clipPath = poly;
    el.style.webkitClipPath = poly;
  };

  CE.prototype._showBlockingOverlayFull = function () {
    var el = document.getElementById('cinema-blocking-overlay');
    if (!el) {
      el = addEl('div', 'cinema-blocking-overlay');
      el.id = 'cinema-blocking-overlay';
    }
    el.style.clipPath = 'none';
    el.style.webkitClipPath = 'none';
  };
  CE.prototype._removeInstantCover = function () {
    var c = document.getElementById('cinema-instant-cover');
    if (c) removeEl(c);
  };

  CE.prototype.waitForEl = function (sel, ms) {
    ms = ms || 5000;
    return new Promise(function (resolve) {
      var el = qs(sel);
      if (el) return resolve(el);
      var s = Date.now();
      var iv = setInterval(function () {
        el = qs(sel);
        if (el) { clearInterval(iv); resolve(el); return; }
        if (Date.now() - s > ms) { clearInterval(iv); resolve(null); }
      }, 200);
    });
  };

  /* ── Subtitle — ALWAYS waits for user click ────────────────────── */
  CE.prototype.showSubtitle = function (text, opts) {
    var self = this;
    opts = opts || {};
    var btnLabel = opts.continueLabel || 'Далее';

    return new Promise(function (resolve) {
      self._showBlockingOverlayFull();
      var wrap = addEl('div', 'cinema-subtitle-wrap');
      var sub  = addEl('div', 'cinema-subtitle', wrap);
      sub.textContent = text;
      self._els.push(wrap);

      var btn = addEl('button', 'cinema-continue-btn', wrap);
      btn.textContent = btnLabel;

      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          wrap.classList.add('visible');
          sub.classList.add('visible');
          btn.classList.add('visible');
        });
      });

      btn.onclick = function () {
        btn.onclick = null;
        sub.classList.remove('visible');
        sub.classList.add('exit');
        wrap.classList.add('exit');
        setTimeout(function () { removeEl(wrap); resolve(); }, 450);
      };
    });
  };

  /* ── Spotlight + prompt — затемнение, дырка с неоном, текст снизу по центру ── */
  /* При нескольких шагах подряд с одним элементом спотлайт не снимается; дырка подстраивается под размер элемента (ResizeObserver). */
  CE.prototype._updateSpotlightGeometry = function (s) {
    if (!s || !s.element || !s.hole) return;
    var el = s.element;
    var rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    var pad = 10;
    var vw = window.innerWidth, vh = window.innerHeight;
    var w = Math.min(rect.width + pad * 2, vw * 0.9);
    var h = Math.min(rect.height + pad * 2, vh * 0.75);
    var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    var left = Math.max(4, Math.min(cx - w / 2, vw - w - 4));
    var top  = Math.max(4, Math.min(cy - h / 2, vh - h - 4));
    var br = window.getComputedStyle(el).borderRadius || '12px';
    s.hole.style.left = left + 'px';
    s.hole.style.top = top + 'px';
    s.hole.style.width = w + 'px';
    s.hole.style.height = h + 'px';
    s.hole.style.borderRadius = br;
    if (s.lbl) {
      s.lbl.style.left = (left + w / 2) + 'px';
      var lt = top + h + 14;
      if (lt > vh - 80) lt = Math.max(8, top - 40);
      s.lbl.style.top = lt + 'px';
    }
    this._updateBlockingOverlay(left, top, w, h);
  };

  CE.prototype._clearCurrentSpotlight = function (onDone, immediate) {
    var self = this;
    var s = this._currentSpotlight;
    if (!s) { if (onDone) onDone(); return; }
    if (s.resizeObserver) { s.resizeObserver.disconnect(); s.resizeObserver = null; }
    this._currentSpotlight = null;

    function removeAll() {
      if (s.hole && s.hole.parentNode) removeEl(s.hole);
      if (s.lbl && s.lbl.parentNode) removeEl(s.lbl);
      if (s.promptWrap && s.promptWrap.parentNode) removeEl(s.promptWrap);
      self._showBlockingOverlayFull();
      if (onDone) onDone();
    }

    if (immediate) {
      removeAll();
      return;
    }
    s.hole.classList.add('cinema-spotlight-exit');
    if (s.lbl) s.lbl.classList.add('cinema-spotlight-exit');
    if (s.promptWrap) s.promptWrap.classList.add('cinema-spotlight-exit');
    self._t(function () { removeAll(); }, 380);
  };

  CE.prototype.spotlightWithPrompt = function (selector, label, text, btnLabel) {
    var self = this;
    btnLabel = btnLabel || 'Далее';
    return new Promise(function (resolve) {
      var el = typeof selector === 'string' ? qs(selector) : selector;
      if (!el) return self.showSubtitle(text, { continueLabel: btnLabel }).then(resolve);

      el.scrollIntoView({ behavior: 'smooth', block: 'center' });

      self._t(function () {
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return self.showSubtitle(text, { continueLabel: btnLabel }).then(resolve);

        var s = self._currentSpotlight;
        if (s && s.element === el) {
          self._updateSpotlightGeometry(s);
          if (s.labelEl) s.labelEl.textContent = label || '';
          s.promptText.textContent = text;
          s.promptBtn.textContent = btnLabel;
          s.promptBtn.onclick = null;
          s.promptBtn.onclick = function () {
            s.promptBtn.onclick = null;
            resolve();
          };
          return;
        }

        if (s) {
          self._clearCurrentSpotlight(function () {
            self._t(function () { doCreate(el, label, text, btnLabel, resolve); }, 0);
          });
          return;
        }

        doCreate(el, label, text, btnLabel, resolve);
      }, 700);

      function doCreate(el, label, text, btnLabel, resolve) {
        var rect = el.getBoundingClientRect();
        var vw = window.innerWidth, vh = window.innerHeight;
        if (rect.width === 0 && rect.height === 0) return self.showSubtitle(text, { continueLabel: btnLabel }).then(resolve);
        if (rect.left + rect.width < 0 || rect.top + rect.height < 0 || rect.left > vw || rect.top > vh) return self.showSubtitle(text, { continueLabel: btnLabel }).then(resolve);

        var pad = 10;
        var vw = window.innerWidth, vh = window.innerHeight;
        var w = Math.min(rect.width + pad * 2, vw * 0.9);
        var h = Math.min(rect.height + pad * 2, vh * 0.75);
        var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
        var left = Math.max(4, Math.min(cx - w / 2, vw - w - 4));
        var top  = Math.max(4, Math.min(cy - h / 2, vh - h - 4));
        var br = window.getComputedStyle(el).borderRadius || '12px';

        var hole = addEl('div', 'cinema-spotlight-hole');
        hole.style.cssText = 'left:' + left + 'px;top:' + top + 'px;width:' + w + 'px;height:' + h + 'px;border-radius:' + br;
        self._els.push(hole);

        var lbl;
        if (label) {
          lbl = addEl('div', 'cinema-spotlight-label');
          lbl.textContent = label;
          lbl.style.left = (left + w / 2) + 'px';
          var lt = top + h + 14;
          if (lt > vh - 80) lt = Math.max(8, top - 40);
          lbl.style.top = lt + 'px';
          lbl.style.transform = 'translateX(-50%)';
          self._els.push(lbl);
        }

        var promptWrap = addEl('div', 'cinema-spotlight-prompt');
        var promptText = addEl('div', 'cinema-spotlight-prompt-text', promptWrap);
        promptText.textContent = text;
        var promptBtn = addEl('button', 'cinema-continue-btn', promptWrap);
        promptBtn.textContent = btnLabel;
        self._els.push(promptWrap);

        self._updateBlockingOverlay(left, top, w, h);

        requestAnimationFrame(function () {
          hole.classList.add('visible', 'pulse');
          if (lbl) lbl.classList.add('visible');
          promptWrap.classList.add('visible');
          promptBtn.classList.add('visible');
        });

        var spot = { element: el, hole: hole, lbl: lbl, labelEl: lbl, promptWrap: promptWrap, promptText: promptText, promptBtn: promptBtn };
        self._currentSpotlight = spot;

        if (typeof ResizeObserver !== 'undefined') {
          spot.resizeObserver = new ResizeObserver(function () {
            if (self._currentSpotlight === spot) self._updateSpotlightGeometry(spot);
          });
          spot.resizeObserver.observe(el);
        }

        promptBtn.onclick = function () {
          promptBtn.onclick = null;
          resolve();
        };
      }
    });
  };

  /* ── Typewriter ────────────────────────────────────────────────── */
  CE.prototype.typewriter = function (text, container) {
    var self = this;
    return new Promise(function (resolve) {
      var idx = 0;
      var span = addEl('span', '', container);
      var cursor = addEl('span', 'cinema-cursor', container);
      self._els.push(cursor);
      function tick() {
        if (!self.running) return resolve();
        if (idx >= text.length) { removeEl(cursor); return resolve(); }
        span.textContent += text[idx]; idx++;
        self._t(tick, TYPEWRITER_MS);
      }
      self._t(tick, 300);
    });
  };

  CE.prototype.typewriterErase = function (container) {
    var self = this;
    return new Promise(function (resolve) {
      var span = container && container.querySelector ? container.querySelector('span:not(.cinema-cursor)') : (container && container.firstChild);
      if (!span) return resolve();
      var full = span.textContent || '';
      var len = full.length;
      function tick() {
        if (!self.running || len <= 0) { return resolve(); }
        len--;
        span.textContent = full.substring(0, len);
        self._t(tick, TYPEWRITER_MS);
      }
      self._t(tick, 50);
    });
  };

  CE.prototype.showSectionIntro = function (description, btnLabel) {
    var self = this;
    btnLabel = btnLabel || 'Далее';
    return new Promise(function (resolve) {
      self._removeBlockingOverlay();
      document.body.classList.add('cinema-freeze');
      var ov = addEl('div', 'cinema-overlay'); ov.classList.add('visible');
      var wrap = addEl('div', 'cinema-typewriter-wrap');
      var textEl = addEl('div', 'cinema-typewriter', wrap);
      var btn = addEl('button', 'cinema-continue-btn', wrap);
      btn.textContent = btnLabel;
      self.typewriter(description, textEl)
      .then(function () {
        if (!self.running) return;
        requestAnimationFrame(function () {
          btn.classList.add('visible');
        });
        btn.onclick = function () {
          btn.onclick = null;
          self.typewriterErase(textEl)
          .then(function () {
            wrap.classList.add('exit');
            setTimeout(function () {
              removeEl(wrap);
              removeEl(ov);
              document.body.classList.remove('cinema-freeze');
              resolve();
            }, 350);
          });
        };
      });
    });
  };

  /* ── Type into field ───────────────────────────────────────────── */
  CE.prototype.typeIntoField = function (text, el) {
    var self = this;
    return new Promise(function (resolve) {
      if (!el) return resolve();
      el.focus();
      var idx = 0; var val = '';
      el.value = '';
      function tick() {
        if (!self.running || idx >= text.length) {
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          return self._t(resolve, 200);
        }
        val += text[idx]; idx++;
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        self._t(tick, 70);
      }
      self._t(tick, 150);
    });
  };

  CE.prototype.simulateClick = function (el) {
    if (!el) return;
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  };

  /* ═══════════════════════════════════════════════════════════════════
     TRANSITIONS
     ═══════════════════════════════════════════════════════════════════ */
  CE.prototype.playEntryTransition = function () {
    var self = this, type = this.transition;
    this._removeInstantCover();
    if (!type) return Promise.resolve();
    lsRemove(LS_TRANSITION);

    if (type === 'elevatorDoors') {
      return new Promise(function (r) {
        var l = addEl('div', 'cinema-elevator-left'), ri = addEl('div', 'cinema-elevator-right');
        self._els.push(l, ri);
        self._t(function () { l.classList.add('open'); ri.classList.add('open');
          self._t(function () { removeEl(l); removeEl(ri); r(); }, 1300); }, 300);
      });
    }
    if (type === 'swipeLeft') {
      return new Promise(function (r) {
        var c = addEl('div', 'cinema-swipe-cover'); self._els.push(c);
        self._t(function () { c.classList.add('exit-left'); self._t(function () { removeEl(c); r(); }, 750); }, 80);
      });
    }
    if (type === 'glitch') {
      return new Promise(function (r) {
        var la = addEl('div', 'cinema-glitch-layer'); self._els.push(la);
        self._t(function () { la.classList.add('active'); self._t(function () { removeEl(la); r(); }, 700); }, 50);
      });
    }
    if (type === 'hyperJump') {
      return new Promise(function (r) {
        var hs = addEl('div', 'cinema-hyperspace'); addEl('div', 'cinema-hyperspace-stars', hs);
        for (var i = 0; i < 14; i++) {
          var s = addEl('div', 'cinema-hyperspace-streak', hs);
          s.style.transform = 'translate(-50%,-50%) rotate(' + ((i / 14) * 360) + 'deg)';
          s.style.animationDelay = (Math.random() * 0.3).toFixed(2) + 's';
        }
        self._els.push(hs);
        self._t(function () { hs.style.transition = 'opacity 0.7s ease'; hs.style.opacity = '0';
          self._t(function () { removeEl(hs); r(); }, 800); }, 1100);
      });
    }
    if (type === 'fade') {
      return new Promise(function (r) {
        var ov = addEl('div', 'cinema-overlay'); ov.style.opacity = '1'; self._els.push(ov);
        self._t(function () { ov.style.transition = 'opacity 0.8s ease'; ov.style.opacity = '0';
          self._t(function () { removeEl(ov); r(); }, 900); }, 150);
      });
    }
    this._removeInstantCover();
    return Promise.resolve();
  };

  CE.prototype.navigateTo = function (url, transition) {
    this.running = false;
    this._removeBlockingOverlay();
    lsSet(LS_TRANSITION, transition || 'fade');
    var ov = addEl('div', 'cinema-overlay'); ov.classList.add('visible');
    setTimeout(function () { window.location.href = url; }, 450);
  };
  CE.prototype.advance = function (n, url, tr) {
    lsSet(LS_SCENE, String(n));
    this.navigateTo(url, tr);
  };

  /* ── FX ────────────────────────────────────────────────────────── */
  CE.prototype.flash = function () {
    var self = this;
    return new Promise(function (r) { var f = addEl('div', 'cinema-flash'); self._els.push(f);
      requestAnimationFrame(function () { f.classList.add('active'); }); self._t(function () { removeEl(f); r(); }, 600); });
  };
  CE.prototype.showCorrectBadge = function () {
    var self = this;
    return new Promise(function (r) { var b = addEl('div', 'cinema-correct-badge'); b.textContent = 'ВЕРНО';
      self._els.push(b); requestAnimationFrame(function () { b.classList.add('visible'); }); self._t(function () { removeEl(b); r(); }, 2200); });
  };
  CE.prototype.showAITooltip = function (text, ms) {
    var self = this; ms = ms || 3500;
    return new Promise(function (r) {
      var tip = addEl('div', 'cinema-ai-tooltip');
      addEl('div', 'cinema-ai-tooltip-label', tip).textContent = 'AI-АССИСТЕНТ';
      addEl('div', '', tip).textContent = text;
      self._els.push(tip);
      requestAnimationFrame(function () { tip.classList.add('visible'); });
      self._t(function () { tip.classList.remove('visible'); self._t(function () { removeEl(tip); r(); }, 500); }, ms);
    });
  };

  /* ── Controls: отключены (без «Пропустить тур» и точек сцен) ─────── */
  CE.prototype.buildControls = function () {
    this._controls = null;
  };
  CE.prototype.endCinema = function (redirect) {
    this.running = false; this._cleanup(); this._removeInstantCover();
    lsRemove(LS_ACTIVE); lsRemove(LS_SCENE); lsRemove(LS_TRANSITION); lsRemove(LS_DEMO_IDS);
    if (this._controls) removeEl(this._controls);
    document.body.classList.remove('cinema-freeze');
    if (redirect) window.location.href = '/student/dashboard';
  };

  /* ═══════════════════════════════════════════════════════════════════
     SCENES
     ═══════════════════════════════════════════════════════════════════ */

  CE.prototype.scenePrologue = function () {
    var self = this; this._removeInstantCover();
    document.body.classList.add('cinema-freeze');
    self._showBlockingOverlayFull();
    var wrap = addEl('div', 'cinema-typewriter-wrap'); self._els.push(wrap);
    var textEl = addEl('div', 'cinema-typewriter', wrap);
    var btn = addEl('button', 'cinema-enter-btn', wrap);
    btn.textContent = 'Войти в систему';
    self.typewriter('Подготовка к экзаменам — это обычно хаос, куча ссылок и потерянные дедлайны. Мы создали систему. Смотри.', textEl)
    .then(function () {
      if (!self.running) return;
      btn.classList.add('visible');
      btn.onclick = function () {
        btn.onclick = null; removeEl(wrap);
        document.body.classList.remove('cinema-freeze');
        lsSet(LS_SCENE, '1'); lsSet(LS_TRANSITION, 'elevatorDoors');
        self.scene = 1; self.transition = 'elevatorDoors'; self.playScene();
      };
    });
  };

  /* ── 1: Dashboard — sidebar spotlight ──────────────────────────── */
  CE.prototype.sceneDashboard = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Это твой командный центр. Здесь собраны ближайшие уроки, задания и аналитика.');
    })
    .then(function () {
      var el = qs('.nav-links');
      return self.spotlightWithPrompt(el, 'Навигация', 'Это навигационная панель — отсюда ты попадёшь в любой раздел платформы.');
    })
    .then(function () {
      var el = qs('#cinema-weak-topics') || qs('[data-cinema="weak-topics"]');
      return self.spotlightWithPrompt(el, 'Слабые темы', 'Этот блок показывает, где ты теряешь баллы. Система обновляет его автоматически.', 'К расписанию');
    })
    .then(function () {
      if (!self.running) return;
      return self.showSectionIntro(SECTION_INTRO.schedule, 'К расписанию')
        .then(function () { if (self.running) self.advance(2, '/schedule', 'swipeLeft'); });
    });
  };

  /* ── 2: Schedule — informational ───────────────────────────────── */
  CE.prototype.sceneSchedule = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Все уроки — в одном расписании. Никаких накладок и забытых занятий.');
    })
    .then(function () {
      var chip = qs('.lesson-chip') || qs('.day-col__body') || qs('#scheduleGrid');
      return self.spotlightWithPrompt(chip, 'Карточка урока', 'Расписание помогает видеть все занятия на неделе. Ничего не потеряешь.', 'К теории');
    })
    .then(function () {
      if (!self.running) return;
      return self.showSectionIntro(SECTION_INTRO.theory, 'К теории')
        .then(function () { if (self.running) self.advance(3, '/theory', 'swipeLeft'); });
    });
  };

  /* ── 3: Theory — enter a topic ─────────────────────────────────── */
  CE.prototype.sceneTheory = function () {
    var isInsideTopic = /\/theory\/\d+/.test(window.location.pathname);
    if (isInsideTopic) this.sceneTheoryView();
    else this.sceneTheoryIndex();
  };

  CE.prototype.sceneTheoryIndex = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle(examTexts(self.ids).theoryIntro);
    })
    .then(function () {
      var card = qs('.theory-grid .theory-card');
      return self.spotlightWithPrompt(card, 'Конспект по теме', 'Давай откроем один из конспектов и посмотрим, что внутри.', 'Открыть конспект');
    })
    .then(function () {
      if (!self.running) return;
      var card = qs('.theory-grid .theory-card');
      if (card) {
        var href = card.getAttribute('href');
        if (href) {
          lsSet(LS_TRANSITION, 'swipeLeft');
          var ov = addEl('div', 'cinema-overlay'); ov.classList.add('visible');
          self.running = false;
          setTimeout(function () { window.location.href = href; }, 400);
          return;
        }
      }
      return self.showSectionIntro(SECTION_INTRO.submissions, 'К заданиям')
        .then(function () { if (self.running) self.advance(4, '/submissions', 'glitch'); });
    });
  };

  CE.prototype.sceneTheoryView = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Это страница конспекта. Здесь — разбор теории, формулы и примеры решений.');
    })
    .then(function () {
      var content = qs('.theory-view-content') || qs('.theory-content') || qs('.app-content') || qs('.glass-panel');
      return self.spotlightWithPrompt(content, 'Материал конспекта', examTexts(self.ids).theoryView, 'К заданиям');
    })
    .then(function () {
      if (!self.running) return;
      return self.showSectionIntro(SECTION_INTRO.submissions, 'К заданиям')
        .then(function () { if (self.running) self.advance(4, '/submissions', 'glitch'); });
    });
  };

  /* ── 4: Submissions ────────────────────────────────────────────── */
  CE.prototype.sceneSubmissions = function () {
    var page = currentPage();
    if (page === 'submission-work') this.sceneSubmissionWork();
    else this.sceneSubmissionsList();
  };

  CE.prototype.sceneSubmissionsList = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Это задания от преподавателя. Дедлайны, ограничения — всё по-настоящему.');
    })
    .then(function () {
      var card = qs('.demo-submission-card') || qs('.submission-card');
      return self.spotlightWithPrompt(card, 'Карточка задания', 'Давай откроем задание и решим его.', 'Открыть задание');
    })
    .then(function () {
      if (!self.running) return;
      var btn = qs('.demo-highlight-begin') || qs('.demo-btn-begin');
      if (btn) {
        var href = btn.getAttribute('href');
        if (href) { lsSet(LS_TRANSITION, 'swipeLeft'); var ov = addEl('div', 'cinema-overlay'); ov.classList.add('visible');
          self.running = false; setTimeout(function () { window.location.href = href; }, 400); }
      }
    });
  };

  CE.prototype.sceneSubmissionWork = function () {
    var self = this;
    var taskAnswers = self.ids.taskAnswers || {};

    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      var startBtn = qs('#start-btn');
      if (startBtn) {
        return self.showSubtitle('Ты внутри задания. Нажми кнопку, чтобы начать выполнение.', { continueLabel: 'Начать выполнение' })
        .then(function () {
          lsSet(LS_TRANSITION, 'fade');
          self.simulateClick(startBtn);
          self.running = false;
        });
      }
      return self.showSubtitle('Перед тобой задания с условиями. Давай заполним ответы.', { continueLabel: 'Заполнить ответы' });
    })
    .then(function () {
      if (!self.running) return;
      var answers = qsa('.answer-input');
      var chain = Promise.resolve();
      answers.forEach(function (textarea) {
        chain = chain.then(function () {
          textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return wait(400);
        }).then(function () {
          var atId = textarea.getAttribute('data-task-id');
          var realAnswer = (atId && taskAnswers[atId]) ? taskAnswers[atId] : '42';
          textarea.value = realAnswer;
          textarea.dispatchEvent(new Event('input', { bubbles: true }));
          textarea.style.borderColor = 'var(--accent-1, #0af)';
          textarea.style.boxShadow = '0 0 8px rgba(0, 170, 255, 0.3)';
          return wait(500);
        });
      });
      return chain;
    })
    .then(function () {
      if (!self.running) return;
      return self.showSubtitle('Все ответы заполнены! В реальности система проверит их автоматически.', { continueLabel: 'Показать результат' });
    })
    .then(function () {
      if (!self.running) return;
      return self.flash();
    })
    .then(function () {
      if (!self.running) return;
      return self.showSubtitle('Идеальный результат! 5 из 5 баллов — 100%. Так работают задания.', { continueLabel: 'Дальше' });
    })
    .then(function () {
      if (!self.running) return;
      var lid = self.ids.lessonId;
      if (lid) {
        return self.showSectionIntro(SECTION_INTRO.lesson, 'В урок')
          .then(function () { if (self.running) self.advance(5, '/lesson/' + lid + '/classwork-tasks', 'swipeLeft'); });
      }
      return self.showSectionIntro(SECTION_INTRO.trainer, 'В тренажёр')
        .then(function () { if (self.running) self.advance(6, '/trainer/v2', 'hyperJump'); });
    });
  };

  /* ── 5: Lesson — только вкладки: Конспект → Классная работа → Материалы → Заметки → Диалог ── */
  CE.prototype.sceneLesson = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Это классная комната. Здесь проходит урок: конспект, задания, материалы — всё в одном месте.');
    })
    .then(function () {
      var theoryTab = qs('.tab-btn[data-tab="theory"]');
      if (theoryTab) self.simulateClick(theoryTab);
      return wait(500);
    })
    .then(function () {
      var theoryPane = qs('#tab-theory');
      return self.spotlightWithPrompt(theoryPane, 'Конспект урока', 'Вкладка «Конспект» — здесь преподаватель размещает теорию к уроку.');
    })
    .then(function () {
      var tasksTab = qs('.tab-btn[data-tab="tasks"]');
      if (tasksTab) self.simulateClick(tasksTab);
      return wait(500);
    })
    .then(function () {
      var tasksPane = qs('#tab-tasks');
      var card = qs('.task-card');
      return self.spotlightWithPrompt(card || tasksPane, 'Классная работа', 'Вкладка «Классная работа» — задания для решения на уроке.');
    })
    .then(function () {
      var materialsTab = qs('.tab-btn[data-tab="materials"]');
      if (materialsTab) self.simulateClick(materialsTab);
      return wait(500);
    })
    .then(function () {
      var materialsPane = qs('#tab-materials');
      return self.spotlightWithPrompt(materialsPane, 'Материалы', 'Вкладка «Материалы» — файлы, презентации и другие вложения к уроку.');
    })
    .then(function () {
      var notesTab = qs('.tab-btn[data-tab="notes"]');
      if (notesTab) self.simulateClick(notesTab);
      return wait(500);
    })
    .then(function () {
      var notesPane = qs('#tab-notes');
      return self.spotlightWithPrompt(notesPane, 'Заметки', 'Вкладка «Заметки» — здесь можно вести конспект по ходу урока.');
    })
    .then(function () {
      var chatTab = qs('.tab-btn[data-tab="chat"]');
      if (chatTab) self.simulateClick(chatTab);
      return wait(500);
    })
    .then(function () {
      var chatPane = qs('#tab-chat');
      return self.spotlightWithPrompt(chatPane, 'Диалог', 'Вкладка «Диалог» — общение с преподавателем и одноклассниками.');
    })
    .then(function () {
      if (self.ids.exam === 'oge') {
        return self.showSubtitle('Вот так устроена классная комната. Переходим к аналитике.', { continueLabel: 'К аналитике' });
      }
      return self.showSubtitle('Вот так устроена классная комната. Теперь покажем AI-тренажёр.', { continueLabel: 'В тренажёр' });
    })
    .then(function () {
      if (!self.running) return;
      if (self.ids.exam === 'oge') {
        var sid = self.ids.studentId;
        if (sid) {
          return self.showSectionIntro(SECTION_INTRO.analytics, 'К аналитике')
            .then(function () { if (self.running) self.advance(7, '/student/' + sid + '/analytics', 'swipeLeft'); });
        }
        lsSet(LS_SCENE, '8'); self.scene = 8; self.sceneCreatorProfile();
        return;
      }
      var tid = self.ids.trainerTaskId;
      var tn = self.ids.trainerTaskNumber || 1;
      var exam = (self.ids.exam || 'ege');
      var url = '/trainer/v2';
      if (tid) url += '?task_id=' + tid + '&task_type=' + tn;
      else if (tn) url += '?task_type=' + tn;
      if (exam) url += (url.indexOf('?') !== -1 ? '&' : '?') + 'exam=' + encodeURIComponent(exam);
      return self.showSectionIntro(SECTION_INTRO.trainer, 'В тренажёр')
        .then(function () { if (self.running) self.advance(6, url, 'hyperJump'); });
    });
  };

  /* ── Type code into CodeMirror line-by-line ──────────────────── */
  CE.prototype.typeIntoCodeMirror = function (code) {
    var self = this;
    var lines = code.split('\n');
    return new Promise(function (resolve) {
      var cmEl = qs('.CodeMirror');
      if (!cmEl || !cmEl.CodeMirror) return resolve();
      var cm = cmEl.CodeMirror;
      cm.setValue('');
      cm.focus();
      var lineIdx = 0;
      function typeLine() {
        if (!self.running || lineIdx >= lines.length) return resolve();
        var line = lines[lineIdx];
        var charIdx = 0;
        function typeChar() {
          if (!self.running || charIdx >= line.length) {
            if (lineIdx < lines.length - 1) {
              cm.replaceRange('\n', { line: cm.lineCount() - 1, ch: cm.getLine(cm.lineCount() - 1).length });
            }
            lineIdx++;
            self._t(typeLine, 80);
            return;
          }
          var lastLine = cm.lineCount() - 1;
          var lastCh = cm.getLine(lastLine).length;
          cm.replaceRange(line[charIdx], { line: lastLine, ch: lastCh });
          charIdx++;
          self._t(typeChar, 18 + Math.random() * 12);
        }
        typeChar();
      }
      self._t(typeLine, 200);
    });
  };

  /* ── Helper: inject chat messages via trainer localStorage ────── */
  CE.prototype._injectTrainerChat = function (messages) {
    var cfg = window.__TRAINER_V2__ || {};
    var userId = cfg.currentUserId || 0;
    var taskId = (cfg.passthrough && cfg.passthrough.task_id) ? cfg.passthrough.task_id : null;
    if (!taskId) {
      var m = window.location.search.match(/task_id=(\d+)/);
      if (m) taskId = m[1];
    }
    if (!taskId) return;
    var key = 'tv2.chat.' + userId + '.' + taskId;
    var now = Date.now();
    var arr = [];
    messages.forEach(function (msg, i) {
      arr.push({ role: msg.role, content: msg.content, ts: now + i * 1000 });
    });
    try { localStorage.setItem(key, JSON.stringify(arr)); } catch (e) {}
  };

  /* ── Демо: своё окно «Помощник» — ввод вопроса, имитация ожидания нейросети, ответ ── */
  CE.prototype._showDemoChatWindow = function (question, reply) {
    var self = this;
    var old = document.getElementById('cinema-demo-chat-window');
    if (old) old.remove();

    var back = document.createElement('div');
    back.id = 'cinema-demo-chat-window';
    back.className = 'cinema-demo-chat-window';
    var box = document.createElement('div');
    box.className = 'cinema-demo-chat-window-box';
    var title = document.createElement('div');
    title.className = 'cinema-demo-chat-window-title';
    title.textContent = 'Помощник';
    var list = document.createElement('div');
    list.className = 'cinema-demo-chat-window-list';

    var userWrap = document.createElement('div');
    userWrap.className = 'tv2-chat-msg is-user';
    userWrap.innerHTML = '<div class="tv2-chat-meta">ученик</div><div class="tv2-chat-bubble cinema-demo-chat-question"></div>';
    var assistantWrap = document.createElement('div');
    assistantWrap.className = 'tv2-chat-msg is-assistant';
    assistantWrap.innerHTML = '<div class="tv2-chat-meta">помощник</div><div class="tv2-chat-bubble cinema-demo-chat-reply"></div>';
    list.appendChild(userWrap);
    list.appendChild(assistantWrap);
    var foot = document.createElement('div');
    foot.className = 'cinema-demo-chat-window-footer';
    var nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'cinema-demo-chat-window-btn';
    nextBtn.textContent = 'Далее';
    nextBtn.style.display = 'none';
    foot.appendChild(nextBtn);
    box.appendChild(title);
    box.appendChild(list);
    box.appendChild(foot);
    back.appendChild(box);
    document.body.appendChild(back);

    var questionEl = list.querySelector('.cinema-demo-chat-question');
    var replyEl = list.querySelector('.cinema-demo-chat-reply');
    var q = String(question || '');
    var r = String(reply || '');

    function typewriter(el, text, speed) {
      return new Promise(function (resolve) {
        if (!el) return resolve();
        el.textContent = '';
        var idx = 0;
        function tick() {
          if (idx >= text.length) return resolve();
          el.textContent += text[idx];
          idx += 1;
          setTimeout(tick, speed || 28);
        }
        tick();
      });
    }

    function showThinking() {
      replyEl.textContent = 'Помощник печатает...';
      replyEl.classList.add('cinema-demo-thinking');
    }
    function hideThinking() {
      replyEl.textContent = '';
      replyEl.classList.remove('cinema-demo-thinking');
    }

    return typewriter(questionEl, q, 22)
      .then(function () { return wait(400); })
      .then(function () { showThinking(); return wait(2200); })
      .then(function () { hideThinking(); return wait(300); })
      .then(function () { return typewriter(replyEl, r, 20); })
      .then(function () {
        return new Promise(function (resolve) {
          nextBtn.style.display = '';
          nextBtn.onclick = function () {
            nextBtn.onclick = null;
            resolve();
          };
        });
      });
  };
  CE.prototype._hideDemoChatWindow = function () {
    var el = document.getElementById('cinema-demo-chat-window');
    if (el) el.remove();
  };

  /* ── 6: Trainer — полностью по сценарию скриптами: код setValue, свой чат-оверлей ── */
  CE.prototype.sceneTrainer = function () {
    var self = this;
    var correctAnswer = self.ids.trainerAnswer || '10';
    var defaultBuggy = 'results = []\n\nfor N in range(1, 100):\n    b = bin(N)[2:]\n    if N % 2 == 0:\n        b = \'10\' + b\n    else:\n        b = \'1\' + b + \'01\'\n    R = int(b, 2)\n    if R < 30:\n        results.append(R)\n\nif results:\n    print(max(results))';
    var defaultFixed = 'results = []\n\nfor N in range(1, 100):\n    b = bin(N)[2:]\n    if N % 2 == 0:\n        b = \'10\' + b\n    else:\n        b = \'1\' + b + \'01\'\n    R = int(b, 2)\n    if R < 30:\n        results.append(N)\n\nif results:\n    print(max(results))';
    var buggyCode = (self.ids.trainerBuggyCode && self.ids.trainerBuggyCode.trim()) ? self.ids.trainerBuggyCode.trim() : defaultBuggy;
    var fixedCode = (self.ids.trainerFixedCode && self.ids.trainerFixedCode.trim()) ? self.ids.trainerFixedCode.trim() : defaultFixed;
    var buggyLines = buggyCode.split('\n');
    var errorLineNum = 10;
    for (var i = 0; i < buggyLines.length; i++) {
      if (buggyLines[i].indexOf('results.append(R)') !== -1) { errorLineNum = i; break; }
    }
    var demoQuestion = (self.ids.trainerQuestion && self.ids.trainerQuestion.trim()) ? self.ids.trainerQuestion.trim() : 'Привет, помоги разобраться с заданием, код почему-то выводит неправильный ответ!';
    var demoAssistantReply = (self.ids.trainerAssistantReply && self.ids.trainerAssistantReply.trim()) ? self.ids.trainerAssistantReply.trim() : (self.ids.trainerHint && self.ids.trainerHint.trim()) ? self.ids.trainerHint.trim() : 'В условии просят максимальное N, а ты выводишь max из R.';
    var demoCorrectionSubtitle = (self.ids.trainerCorrection && self.ids.trainerCorrection.trim()) ? self.ids.trainerCorrection.trim() : 'Исправлено. Запускаем код.';
    var conditionHtml = (self.ids.trainerConditionHtml && self.ids.trainerConditionHtml.trim()) ? self.ids.trainerConditionHtml.trim() : '';
    if (!conditionHtml) {
      conditionHtml = '<p><strong>№ 23551</strong> (Уровень: Базовый)</p><p>На вход алгоритма подаётся натуральное число N. Алгоритм строит по нему новое число R так:</p><p>1. Строится двоичная запись числа N.<br>2. К этой записи применяются правила: если N чётное, то слева дописывается «10», если N нечётное — слева дописывается «1», справа «01».<br>3. Результат переводится в десятичную систему — это число R.</p><p>Пример: для N = 4 (100₂) получается 10100₂ = 20; для N = 5 (101₂) получается 110101₂ = 53.</p><p>Укажите максимальное число N, после обработки которого с помощью этого алгоритма получается число R, меньшее чем 30. В ответе запишите это число в десятичной системе счисления.</p>';
    }

    self.playEntryTransition()
    .then(function () {
      var dock = qs('#trainerV2Dock') || qs('.trainer-v2-root');
      if (dock) dock.classList.add('cinema-neon-hud');
      qsa('#tv2NextBtn, #tv2ZenExitBtn').forEach(function (b) {
        b.style.pointerEvents = 'none'; b.style.opacity = '0.3';
      });
      return self.waitForEl('.CodeMirror', 8000);
    })
    .then(function () {
      var cond = qs('.tv2-task-content') || qs('#tv2TaskContent');
      if (cond && conditionHtml) { cond.innerHTML = conditionHtml; }
      return wait(200);
    })
    .then(function () {
      var editorBox = qs('.tv2-editor-box');
      return self.spotlightWithPrompt(editorBox, 'Тренажёр', 'Это AI-тренажёр. Задание из сценария подставлено. Сейчас введётся код с ошибкой.', 'Далее');
    })
    .then(function () {
      return self.typeIntoCodeMirror(buggyCode);
    })
    .then(function () {
      var editorBox = qs('.tv2-editor-box');
      return self.spotlightWithPrompt(editorBox, 'Код введён', 'Найди в нём ошибку.', 'Далее');
    })
    .then(function () {
      var cmEl = qs('.CodeMirror');
      if (cmEl && cmEl.CodeMirror) { try { cmEl.CodeMirror.addLineClass(errorLineNum, 'background', 'cinema-error-line'); } catch (e) {} }
      var editorBox = qs('.tv2-editor-box');
      return self.spotlightWithPrompt(editorBox, 'Ошибка в строке', 'Ошибка в подсвеченной строке. Посмотри, подумай. Когда будешь готов — нажми «Далее».', 'Далее');
    })
    .then(function () {
      return self.showSubtitle('Открываем окно помощника: введём вопрос, подождём «ответ» нейросети.', { continueLabel: 'Далее' });
    })
    .then(function () {
      return self._showDemoChatWindow(demoQuestion, demoAssistantReply);
    })
    .then(function () {
      self._hideDemoChatWindow();
      var editorBox = qs('.tv2-editor-box');
      return self.spotlightWithPrompt(editorBox, 'Исправление', 'Ответ помощника прочитан. Переходим к исправлению кода.', 'Далее');
    })
    .then(function () {
      var cmEl = qs('.CodeMirror');
      if (cmEl && cmEl.CodeMirror) {
        try { cmEl.CodeMirror.removeLineClass(errorLineNum, 'background', 'cinema-error-line'); } catch (e) {}
        cmEl.CodeMirror.setValue(fixedCode);
        try { cmEl.CodeMirror.addLineClass(errorLineNum, 'background', 'cinema-fixed-line'); } catch (e) {}
      }
      var editorBox = qs('.tv2-editor-box');
      return self.spotlightWithPrompt(editorBox, 'Код исправлен', demoCorrectionSubtitle, 'Далее');
    })
    .then(function () {
      var cmEl = qs('.CodeMirror');
      if (cmEl && cmEl.CodeMirror) { try { cmEl.CodeMirror.removeLineClass(errorLineNum, 'background', 'cinema-fixed-line'); } catch (e) {} }
      return wait(200);
    })
    .then(function () {
      var runBtn = qs('.tv2-fab-outline');
      return self.spotlightWithPrompt(runBtn, 'Запустить', 'Нажми «Запустить», чтобы выполнить исправленный код.', 'Запустить');
    })
    .then(function () {
      self._clearCurrentSpotlight(null, true);
      self._removeBlockingOverlay();
      var fab = qs('.tv2-fab');
      if (fab) fab.style.display = 'flex';
      var runBtn = qs('.tv2-fab-outline');
      return wait(100);
    })
    .then(function () {
      var runBtn = qs('.tv2-fab-outline');
      if (runBtn) self.simulateClick(runBtn);
      return wait(150);
    })
    .then(function () {
      var runBtn = qs('.tv2-fab-outline');
      if (runBtn) self.simulateClick(runBtn);
      return wait(2050);
    })
    .then(function () {
      var terminalTab = qs('button[data-tab="terminal"]');
      if (terminalTab) self.simulateClick(terminalTab);
      return wait(600);
    })
    .then(function () {
      var answerEl = qs('#tv2AnswerInput');
      return self.spotlightWithPrompt(answerEl, 'Ответ', 'Вводим ответ из вывода: ' + correctAnswer, 'Ввести');
    })
    .then(function () {
      var answerEl = qs('#tv2AnswerInput');
      if (answerEl) { answerEl.value = correctAnswer; answerEl.dispatchEvent(new Event('input', { bubbles: true })); }
      return self.spotlightWithPrompt(answerEl, 'Ответ введён', 'Нажми «Проверить».', 'Проверить');
    })
    .then(function () {
      var answerEl = qs('#tv2AnswerInput');
      if (answerEl) { answerEl.style.borderColor = '#0f0'; answerEl.style.boxShadow = '0 0 12px rgba(0,255,0,0.4)'; }
      var checkBtn = qs('.tv2-fab-primary');
      if (checkBtn) self.simulateClick(checkBtn);
      return wait(1800);
    })
    .then(function () { return self.flash(); })
    .then(function () { return self.showCorrectBadge(); })
    .then(function () {
      self._hideDemoChatWindow();
      var dock = qs('#trainerV2Dock') || qs('.trainer-v2-root');
      if (dock) dock.classList.remove('cinema-neon-hud');
      qsa('#tv2NextBtn, #tv2ZenExitBtn').forEach(function (b) { b.style.pointerEvents = ''; b.style.opacity = ''; });
      var answerEl = qs('#tv2AnswerInput');
      if (answerEl) { answerEl.style.borderColor = ''; answerEl.style.boxShadow = ''; }
      return wait(200);
    })
    .then(function () {
      return self.showSubtitle('Код → ошибка → вопрос помощнику → исправление → запуск → проверка. Так работает тренажёр.', { continueLabel: 'К аналитике' });
    })
    .then(function () {
      if (!self.running) return;
      var sid = self.ids.studentId;
      if (sid) {
        return self.showSectionIntro(SECTION_INTRO.analytics, 'К аналитике')
          .then(function () { if (self.running) self.advance(7, '/student/' + sid + '/analytics', 'swipeLeft'); });
      }
      lsSet(LS_SCENE, '8'); self.scene = 8; self.sceneCreatorProfile();
    });
  };

  /* ── 7: Analytics — hide radar, show both tabs ─────────────────── */
  CE.prototype.sceneAnalytics = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      var radarPanel = qs('#skillsChart');
      if (radarPanel) {
        var panel = radarPanel.closest('.glass-panel');
        if (panel) panel.style.display = 'none';
      }
      var chartsGrid = qs('.charts-grid');
      if (chartsGrid) chartsGrid.style.gridTemplateColumns = '1fr';
      return wait(200);
    })
    .then(function () {
      return self.showSubtitle('Вся аналитика подготовки — в одном месте. Каждое действие на платформе учитывается.');
    })
    .then(function () {
      var el = qs('.metrics-grid');
      return self.spotlightWithPrompt(el, 'Ключевые метрики', 'GPA, процент выполнения, количество уроков — всё обновляется в реальном времени.');
    })
    .then(function () {
      var el = qs('#trendChart');
      var panel = el ? el.closest('.glass-panel') : null;
      return self.spotlightWithPrompt(panel, 'Динамика успеваемости', 'График показывает изменение процента выполнения заданий по неделям.');
    })
    .then(function () {
      var el = qs('#statisticsChart');
      var panel = el ? el.closest('.glass-panel') : null;
      return self.spotlightWithPrompt(panel, 'Процент выполнения по номерам', examTexts(self.ids).analyticsCharts, examTexts(self.ids).analyticsTab);
    })
    .then(function () {
      var tabBtn = qs('.stats-tab[data-tab="analytics"]');
      if (tabBtn) {
        self.simulateClick(tabBtn);
        return wait(2600);
      }
      return wait(500);
    })
    .then(function () {
      var table = qs('#analyticsNodesTable') || qs('.analytics-nodes-table');
      return self.spotlightWithPrompt(table, examTexts(self.ids).ratingLabel, 'Рейтинг по каждой теме обновляется после каждого решения. Чем выше — тем увереннее ты в теме.');
    })
    .then(function () {
      var el = qs('#analyticsPredictedScore');
      return self.spotlightWithPrompt(el, 'Прогноз балла', 'Система прогнозирует твой балл на основе рейтинга по всем темам.', 'Финал');
    })
    .then(function () {
      if (self.running) { lsSet(LS_SCENE, '8'); self.scene = 8; self.sceneCreatorProfile(); }
    });
  };

  /* ── 8: Creator profile — кто создал платформу ──────────────────── */
  CE.prototype.sceneCreatorProfile = function () {
    var self = this;
    self._removeBlockingOverlay();
    document.body.classList.add('cinema-freeze');
    var ov = addEl('div', 'cinema-overlay'); ov.classList.add('visible');
    var wrap = addEl('div', 'cinema-typewriter-wrap');
    var textEl = addEl('div', 'cinema-typewriter', wrap);
    var creatorName = (self.ids.creatorName && self.ids.creatorName.trim()) ? self.ids.creatorName.trim() : 'Команда платформы';
    var intro = 'Платформу создал: ' + creatorName;
    var btn = addEl('button', 'cinema-continue-btn', wrap);
    btn.textContent = 'Далее';
    self.typewriter(intro, textEl)
    .then(function () {
      if (!self.running) return;
      requestAnimationFrame(function () { btn.classList.add('visible'); });
      btn.onclick = function () {
        btn.onclick = null;
        self.typewriterErase(textEl)
        .then(function () {
          setTimeout(function () {
            removeEl(wrap);
            removeEl(ov);
            document.body.classList.remove('cinema-freeze');
            lsSet(LS_SCENE, '9');
            self.scene = 9;
            self.sceneEpilogue();
          }, 350);
        });
      };
    });
  };

  /* ── 9: Epilogue — typewriter + single CTA ─────────────────────── */
  CE.prototype.sceneEpilogue = function () {
    var self = this;
    document.body.classList.add('cinema-freeze');
    var ov = addEl('div', 'cinema-overlay'); ov.classList.add('visible'); self._els.push(ov);

    var wrap = addEl('div', 'cinema-typewriter-wrap'); self._els.push(wrap);
    var textEl = addEl('div', 'cinema-typewriter', wrap);
    var btn = addEl('a', 'cinema-enter-btn', wrap);
    btn.textContent = 'Выбрать тариф и начать подготовку';
    btn.href = '/billing/plans/public';

    wait(600)
    .then(function () {
      return self.typewriter('Платформа готова. Твоя сотка — вопрос дисциплины и алгоритма. Алгоритм у нас есть.', textEl);
    })
    .then(function () {
      if (!self.running) return;
      btn.classList.add('visible');
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        self.endCinema(false);
        window.location.href = '/billing/plans/public';
      });
    });
  };

  /* ── Dispatcher ────────────────────────────────────────────────── */
  CE.prototype.playScene = function () {
    switch (this.scene) {
      case 0: this.scenePrologue(); break;
      case 1: this.sceneDashboard(); break;
      case 2: this.sceneSchedule(); break;
      case 3: this.sceneTheory(); break;
      case 4: this.sceneSubmissions(); break;
      case 5: this.sceneLesson(); break;
      case 6: if (this.ids.exam === 'oge') { this.scene = 7; lsSet(LS_SCENE, '7'); this.sceneAnalytics(); } else { this.sceneTrainer(); } break;
      case 7: this.sceneAnalytics(); break;
      case 8: this.sceneCreatorProfile(); break;
      case 9: this.sceneEpilogue(); break;
      default: this.endCinema(true); break;
    }
  };

  CE.prototype.start = function () {
    if (lsGet(LS_ACTIVE) !== 'true') { this._removeInstantCover(); return; }
    this.running = true;
    this.buildControls();
    this.playScene();
  };

  /* ── Быстрый переход к сцене (только демо) ──────────────────────── */
  function buildSceneJumpPanel() {
    if (qs('#cinema-scene-jump')) return;
    var exam = (getDemoIds().exam || 'ege');
    var base = '/demo/start?exam=' + encodeURIComponent(exam) + '&code=test&cinema_scene=';
    var scenes = [
      { n: 1, label: 'Лифт' },
      { n: 2, label: 'Расписание' },
      { n: 3, label: 'Теория' },
      { n: 4, label: 'Задания' },
      { n: 5, label: 'Урок' },
      { n: 6, label: 'Тренажёр' },
      { n: 7, label: 'Аналитика' },
      { n: 8, label: 'Создатель' },
      { n: 9, label: 'Финал' },
    ];
    var wrap = document.createElement('div');
    wrap.id = 'cinema-scene-jump';
    wrap.className = 'cinema-scene-jump';
    var title = document.createElement('div');
    title.className = 'cinema-scene-jump-title';
    title.textContent = 'Переход к сцене';
    wrap.appendChild(title);
    scenes.forEach(function (s) {
      var a = document.createElement('a');
      a.href = base + s.n;
      a.textContent = s.n + ': ' + s.label;
      a.className = 'cinema-scene-jump-link';
      wrap.appendChild(a);
    });
    document.body.appendChild(wrap);
  }

  /* ── Bootstrap ─────────────────────────────────────────────────── */
  function init() {
    var isDemo = false;
    try {
      if (document.cookie.indexOf('is_demo=true') !== -1) isDemo = true;
      if (lsGet('is_demo') === 'true') isDemo = true;
    } catch (e) {}
    if (!isDemo) return;

    var urlScene = (function () {
      var m = window.location.search.match(/[?&]cinema_scene=(\d)/);
      return m ? m[1] : null;
    })();
    if (urlScene) {
      lsSet(LS_ACTIVE, 'true');
      lsSet(LS_SCENE, urlScene);
    }

    if (!urlScene && document.cookie.indexOf('cinemaMode=prologue') !== -1) {
      lsSet(LS_ACTIVE, 'true');
      lsSet(LS_SCENE, '0');
      lsRemove(LS_TRANSITION);
      document.cookie = 'cinemaMode=; path=/; max-age=0';
    }

    var metaIds = qs('meta[name="cinema-demo-ids"]');
    if (metaIds) {
      try {
        var c = metaIds.getAttribute('content');
        if (c && c.trim().length > 20) {
          var o = JSON.parse(c);
          if (o && typeof o === 'object' && Object.keys(o).length > 0) lsSet(LS_DEMO_IDS, c);
        }
      } catch (e) {}
    }

    buildSceneJumpPanel();

    var engine = new CE();
    engine.start();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 250); });
  } else { setTimeout(init, 250); }
})();
