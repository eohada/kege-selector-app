/**
 * Demo Cinema Engine v2 — cinematic onboarding with:
 *  - dark scrim behind every subtitle (always readable)
 *  - "Далее" buttons so the user controls the pace
 *  - instant black cover on page load to prevent white flash
 */
(function () {
  'use strict';

  var TOTAL_SCENES  = 9;
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

  function addEl(tag, cls, parent) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    (parent || document.body).appendChild(el);
    return el;
  }
  function removeEl(el) { if (el && el.parentNode) el.parentNode.removeChild(el); }

  /* ─── Instant cover: placed synchronously on first load ────────── */
  function placeInstantCover() {
    if (lsGet(LS_ACTIVE) !== 'true') return;
    if (lsGet(LS_SCENE) === '0') return;
    var c = document.createElement('div');
    c.className = 'cinema-instant-cover';
    c.id = 'cinema-instant-cover';
    document.documentElement.appendChild(c);
  }
  placeInstantCover();

  /* ═══════════════════════════════════════════════════════════════════
     CinemaEngine
     ═══════════════════════════════════════════════════════════════════ */
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
    this._els.forEach(function (el) { removeEl(el); });
    this._els = [];
    qsa('.cinema-spotlight-ring').forEach(function (e) { e.classList.remove('cinema-spotlight-ring'); });
    qsa('.cinema-neon-hud').forEach(function (e) { e.classList.remove('cinema-neon-hud'); });
    var bd = qs('.cinema-backdrop-blur');
    if (bd) removeEl(bd);
    document.body.classList.remove('cinema-freeze');
  };

  /* ── remove instant cover ──────────────────────────────────────── */
  CE.prototype._removeInstantCover = function () {
    var c = document.getElementById('cinema-instant-cover');
    if (c) removeEl(c);
  };

  /* ── Subtitle with dark scrim + optional "Далее" ───────────────── */
  CE.prototype.showSubtitle = function (text, opts) {
    var self = this;
    opts = opts || {};
    var autoMs   = opts.auto;
    var withBtn  = opts.withContinue;
    var btnLabel = opts.continueLabel || 'Далее';

    return new Promise(function (resolve) {
      var wrap = addEl('div', 'cinema-subtitle-wrap');
      var sub  = addEl('div', 'cinema-subtitle', wrap);
      sub.textContent = text;
      self._els.push(wrap);

      var btn;
      if (withBtn) {
        btn = addEl('button', 'cinema-continue-btn', wrap);
        btn.textContent = btnLabel;
      }

      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          wrap.classList.add('visible');
          sub.classList.add('visible');
          if (btn) btn.classList.add('visible');
        });
      });

      function dismiss() {
        sub.classList.remove('visible');
        sub.classList.add('exit');
        wrap.classList.add('exit');
        self._t(function () { removeEl(wrap); resolve(); }, 550);
      }

      if (withBtn && btn) {
        btn.onclick = function () {
          btn.onclick = null;
          dismiss();
        };
      } else if (autoMs) {
        self._t(dismiss, autoMs);
      } else {
        self._t(dismiss, 3500);
      }
    });
  };

  /* ── Typewriter (prologue black screen) ────────────────────────── */
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
        span.textContent += text[idx];
        idx++;
        self._t(tick, TYPEWRITER_MS);
      }
      self._t(tick, 300);
    });
  };

  /* ── Spotlight ─────────────────────────────────────────────────── */
  CE.prototype.spotlight = function (selector, durationMs) {
    var self = this;
    durationMs = durationMs || 3000;
    return new Promise(function (resolve) {
      var el = qs(selector);
      if (!el) return resolve();
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });

      var bd = qs('.cinema-backdrop-blur') || addEl('div', 'cinema-backdrop-blur');
      self._els.push(bd);

      self._t(function () {
        bd.classList.add('visible');
        el.classList.add('cinema-spotlight-ring');
      }, 300);

      self._t(function () {
        el.classList.remove('cinema-spotlight-ring');
        bd.classList.remove('visible');
        self._t(function () { removeEl(bd); resolve(); }, 500);
      }, 300 + durationMs);
    });
  };

  /* ── Auto-scroll ───────────────────────────────────────────────── */
  CE.prototype.autoScroll = function (selector, ms) {
    var self = this;
    ms = ms || 2000;
    return new Promise(function (resolve) {
      var el = qs(selector);
      if (!el) return resolve();
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      self._t(resolve, ms);
    });
  };

  /* ══════════════════════════════════════════════════════════════════
     TRANSITIONS
     ══════════════════════════════════════════════════════════════════ */
  CE.prototype.playEntryTransition = function () {
    var self = this;
    var type = this.transition;
    this._removeInstantCover();
    if (!type) { return Promise.resolve(); }
    lsRemove(LS_TRANSITION);

    if (type === 'elevatorDoors') {
      return new Promise(function (resolve) {
        var left  = addEl('div', 'cinema-elevator-left');
        var right = addEl('div', 'cinema-elevator-right');
        self._els.push(left, right);
        self._t(function () {
          left.classList.add('open');
          right.classList.add('open');
          self._t(function () { removeEl(left); removeEl(right); resolve(); }, 1300);
        }, 300);
      });
    }

    if (type === 'swipeLeft') {
      return new Promise(function (resolve) {
        var cover = addEl('div', 'cinema-swipe-cover');
        self._els.push(cover);
        self._t(function () {
          cover.classList.add('exit-left');
          self._t(function () { removeEl(cover); resolve(); }, 750);
        }, 80);
      });
    }

    if (type === 'glitch') {
      return new Promise(function (resolve) {
        var layer = addEl('div', 'cinema-glitch-layer');
        self._els.push(layer);
        self._t(function () {
          layer.classList.add('active');
          self._t(function () { removeEl(layer); resolve(); }, 700);
        }, 50);
      });
    }

    if (type === 'hyperJump') {
      return new Promise(function (resolve) {
        var hs = addEl('div', 'cinema-hyperspace');
        addEl('div', 'cinema-hyperspace-stars', hs);
        for (var i = 0; i < 14; i++) {
          var s = addEl('div', 'cinema-hyperspace-streak', hs);
          s.style.transform = 'translate(-50%,-50%) rotate(' + ((i / 14) * 360) + 'deg)';
          s.style.animationDelay = (Math.random() * 0.3).toFixed(2) + 's';
        }
        self._els.push(hs);
        self._t(function () { removeEl(hs); resolve(); }, 1200);
      });
    }

    if (type === 'fade') {
      return new Promise(function (resolve) {
        var ov = addEl('div', 'cinema-overlay');
        ov.style.opacity = '1';
        self._els.push(ov);
        self._t(function () {
          ov.style.transition = 'opacity 0.8s ease';
          ov.style.opacity = '0';
          self._t(function () { removeEl(ov); resolve(); }, 900);
        }, 150);
      });
    }

    this._removeInstantCover();
    return Promise.resolve();
  };

  /* ── Navigate ──────────────────────────────────────────────────── */
  CE.prototype.navigateTo = function (url, transition) {
    this.running = false;
    lsSet(LS_TRANSITION, transition || 'fade');
    var ov = addEl('div', 'cinema-overlay');
    ov.classList.add('visible');
    setTimeout(function () { window.location.href = url; }, 450);
  };

  CE.prototype.advance = function (next, url, transition) {
    lsSet(LS_SCENE, String(next));
    this.navigateTo(url, transition);
  };

  /* ── FX helpers ────────────────────────────────────────────────── */
  CE.prototype.flash = function () {
    var self = this;
    return new Promise(function (resolve) {
      var f = addEl('div', 'cinema-flash');
      self._els.push(f);
      requestAnimationFrame(function () { f.classList.add('active'); });
      self._t(function () { removeEl(f); resolve(); }, 600);
    });
  };

  CE.prototype.showCorrectBadge = function () {
    var self = this;
    return new Promise(function (resolve) {
      var b = addEl('div', 'cinema-correct-badge');
      b.textContent = 'ВЕРНО';
      self._els.push(b);
      requestAnimationFrame(function () { b.classList.add('visible'); });
      self._t(function () { removeEl(b); resolve(); }, 2200);
    });
  };

  CE.prototype.showAITooltip = function (text, durationMs) {
    var self = this;
    durationMs = durationMs || 3500;
    return new Promise(function (resolve) {
      var tip = addEl('div', 'cinema-ai-tooltip');
      var lbl = addEl('div', 'cinema-ai-tooltip-label', tip);
      lbl.textContent = 'AI-АССИСТЕНТ';
      var body = addEl('div', '', tip);
      body.textContent = text;
      tip.style.top = '50%';
      tip.style.left = '50%';
      tip.style.transform = 'translate(-50%, -50%)';
      self._els.push(tip);
      requestAnimationFrame(function () { tip.classList.add('visible'); });
      self._t(function () {
        tip.classList.remove('visible');
        self._t(function () { removeEl(tip); resolve(); }, 500);
      }, durationMs);
    });
  };

  /* ── Controls widget ───────────────────────────────────────────── */
  CE.prototype.buildControls = function () {
    var self = this;
    var wrap = addEl('div', 'cinema-controls');
    self._controls = wrap;

    var pips = addEl('div', 'cinema-progress-pip', wrap);
    for (var i = 0; i < TOTAL_SCENES; i++) {
      var p = addEl('div', 'cinema-pip', pips);
      if (i < self.scene) p.classList.add('done');
      if (i === self.scene) p.classList.add('current');
    }

    var skip = addEl('button', 'cinema-ctrl-btn', wrap);
    skip.textContent = 'Пропустить тур';
    skip.onclick = function () { self.endCinema(true); };
  };

  /* ── End cinema ────────────────────────────────────────────────── */
  CE.prototype.endCinema = function (redirect) {
    this.running = false;
    this._cleanup();
    this._removeInstantCover();
    lsRemove(LS_ACTIVE);
    lsRemove(LS_SCENE);
    lsRemove(LS_TRANSITION);
    lsRemove(LS_DEMO_IDS);
    if (this._controls) removeEl(this._controls);
    document.body.classList.remove('cinema-freeze');
    if (redirect) window.location.href = '/student/dashboard';
  };

  /* ═══════════════════════════════════════════════════════════════════
     SCENES
     ═══════════════════════════════════════════════════════════════════ */

  /* ── 0: Prologue ───────────────────────────────────────────────── */
  CE.prototype.scenePrologue = function () {
    var self = this;
    this._removeInstantCover();
    document.body.classList.add('cinema-freeze');

    var wrap = addEl('div', 'cinema-typewriter-wrap');
    self._els.push(wrap);
    var textEl = addEl('div', 'cinema-typewriter', wrap);
    var btn = addEl('button', 'cinema-enter-btn', wrap);
    btn.textContent = 'Войти в систему';

    self.typewriter(
      'Подготовка к экзаменам — это обычно хаос, куча ссылок и потерянные дедлайны. Мы создали систему. Смотри.',
      textEl
    ).then(function () {
      if (!self.running) return;
      btn.classList.add('visible');
      btn.onclick = function () {
        btn.onclick = null;
        removeEl(wrap);
        document.body.classList.remove('cinema-freeze');
        lsSet(LS_SCENE, '1');
        lsSet(LS_TRANSITION, 'elevatorDoors');
        self.scene = 1;
        self.transition = 'elevatorDoors';
        self.playScene();
      };
    });
  };

  /* ── 1: Dashboard ──────────────────────────────────────────────── */
  CE.prototype.sceneDashboard = function () {
    var self = this;

    self.playEntryTransition()
    .then(function () { return wait(500); })
    .then(function () {
      return self.showSubtitle('Это твой личный командный центр. Всё, что нужно — на одном экране.', { withContinue: true });
    })
    .then(function () { return wait(300); })
    .then(function () {
      var el = qs('#cinema-notifications') || qs('.hero-actions');
      if (el) return self.spotlight(el.id ? '#' + el.id : '.hero-actions', 2500);
      return wait(400);
    })
    .then(function () {
      var el = qs('#cinema-weak-topics') || qs('[data-cinema="weak-topics"]');
      if (el) return self.spotlight(el.id ? '#' + el.id : '[data-cinema="weak-topics"]', 2500);
      return wait(400);
    })
    .then(function () {
      return self.showSubtitle('Но любой успех начинается с планирования. Заглянем в будущее.', { withContinue: true, continueLabel: 'К расписанию' });
    })
    .then(function () {
      if (self.running) self.advance(2, '/schedule', 'swipeLeft');
    });
  };

  /* ── 2: Schedule ───────────────────────────────────────────────── */
  CE.prototype.sceneSchedule = function () {
    var self = this;

    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Твоё время под строгим контролем. Никаких накладок.', { withContinue: true });
    })
    .then(function () { return wait(200); })
    .then(function () {
      var el = qs('#cinema-nearest-lesson') || qs('.schedule-shell');
      if (el) return self.spotlight(el.id ? '#' + el.id : '.schedule-shell', 2500);
      return wait(800);
    })
    .then(function () {
      return self.showSubtitle('Чтобы выжить на уроке, нужна база. Идём за знаниями.', { withContinue: true, continueLabel: 'К теории' });
    })
    .then(function () {
      if (self.running) self.advance(3, '/theory', 'swipeLeft');
    });
  };

  /* ── 3: Theory ─────────────────────────────────────────────────── */
  CE.prototype.sceneTheory = function () {
    var self = this;

    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Вся выжимка для ЕГЭ здесь. Без воды и пыльных учебников.', { withContinue: true });
    })
    .then(function () { return wait(200); })
    .then(function () {
      var g = qs('.theory-grid');
      if (g) return self.autoScroll('.theory-grid', 2000);
      return wait(800);
    })
    .then(function () {
      return self.showSubtitle('Теория без практики мертва. Время настоящей проверки.', { withContinue: true, continueLabel: 'К заданиям' });
    })
    .then(function () {
      if (self.running) self.advance(4, '/submissions', 'glitch');
    });
  };

  /* ── 4: Submissions ────────────────────────────────────────────── */
  CE.prototype.sceneSubmissions = function () {
    var self = this;

    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Это боевые задания. Здесь есть дедлайны и лимиты попыток. Никаких подсказок.', { withContinue: true });
    })
    .then(function () { return wait(200); })
    .then(function () {
      var btn = qs('.demo-highlight-begin') || qs('.demo-btn-begin');
      if (btn) {
        return self.spotlight(
          btn.classList.contains('demo-highlight-begin') ? '.demo-highlight-begin' : '.demo-btn-begin',
          3000
        );
      }
      return wait(800);
    })
    .then(function () {
      return self.showSubtitle('Сдано вовремя. А теперь перенесёмся в самый эпицентр — на живой урок.', { withContinue: true, continueLabel: 'К уроку' });
    })
    .then(function () {
      if (!self.running) return;
      var lid = self.ids.lessonId;
      if (lid) {
        self.advance(5, '/lesson/' + lid + '/classwork-tasks', 'swipeLeft');
      } else {
        self.advance(6, '/trainer/v2', 'hyperJump');
      }
    });
  };

  /* ── 5: Lesson ─────────────────────────────────────────────────── */
  CE.prototype.sceneLesson = function () {
    var self = this;

    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Слушаешь преподавателя и сразу решаешь задачи. Всё в одном окне.', { withContinue: true });
    })
    .then(function () { return wait(200); })
    .then(function () {
      var s = qs('#cinema-save-draft') || qs('[data-cinema="save-draft"]');
      if (s) return self.spotlight(s.id ? '#' + s.id : '[data-cinema="save-draft"]', 2500);
      return wait(800);
    })
    .then(function () {
      return self.showSubtitle('Застрял? Сохрани черновик и доделай позже. Но что если тема совсем не даётся?', { auto: 3500 });
    })
    .then(function () {
      return self.showSubtitle('Для этого мы создали песочницу. Добро пожаловать в Тренажёр.', { withContinue: true, continueLabel: 'В тренажёр' });
    })
    .then(function () {
      if (self.running) self.advance(6, '/trainer/v2', 'hyperJump');
    });
  };

  /* ── 6: Trainer ────────────────────────────────────────────────── */
  CE.prototype.sceneTrainer = function () {
    var self = this;

    self.playEntryTransition()
    .then(function () { return wait(500); })
    .then(function () {
      return self.showSubtitle('Здесь можно тренироваться сколько угодно. ИИ подскажет, если ошибёшься.', { withContinue: true });
    })
    .then(function () { return wait(300); })
    .then(function () {
      var dock = qs('#trainerV2Dock') || qs('.trainer-v2-root');
      if (dock) {
        dock.classList.add('cinema-neon-hud');
        return wait(2200).then(function () { dock.classList.remove('cinema-neon-hud'); });
      }
      return wait(800);
    })
    .then(function () {
      return self.showAITooltip('Обнаружена ошибка логики. Запускаю протокол коррекции...', 3000);
    })
    .then(function () { return self.flash(); })
    .then(function () { return self.showCorrectBadge(); })
    .then(function () {
      return self.showSubtitle('Здесь можно ошибаться. Мы научим, как правильно. А теперь — твои результаты.', { withContinue: true, continueLabel: 'К аналитике' });
    })
    .then(function () {
      if (!self.running) return;
      var sid = self.ids.studentId;
      if (sid) {
        self.advance(7, '/student/' + sid + '/analytics', 'swipeLeft');
      } else {
        lsSet(LS_SCENE, '8'); self.scene = 8; self.sceneEpilogue();
      }
    });
  };

  /* ── 7: Analytics ──────────────────────────────────────────────── */
  CE.prototype.sceneAnalytics = function () {
    var self = this;

    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Каждое твоё действие на платформе имеет вес.', { withContinue: true });
    })
    .then(function () { return wait(200); })
    .then(function () {
      var ch = qs('.charts-grid') || qs('.metrics-grid');
      if (ch) return self.spotlight(ch.classList.contains('charts-grid') ? '.charts-grid' : '.metrics-grid', 3000);
      return wait(800);
    })
    .then(function () {
      return self.showSubtitle('Графики, тренды, прогноз баллов — всё наглядно.', { withContinue: true, continueLabel: 'Финал' });
    })
    .then(function () {
      if (self.running) { lsSet(LS_SCENE, '8'); self.scene = 8; self.sceneEpilogue(); }
    });
  };

  /* ── 8: Epilogue ───────────────────────────────────────────────── */
  CE.prototype.sceneEpilogue = function () {
    var self = this;
    document.body.classList.add('cinema-freeze');

    var ov = addEl('div', 'cinema-overlay');
    ov.classList.add('visible');
    self._els.push(ov);

    wait(500)
    .then(function () {
      return self.showSubtitle(
        'Платформа готова. Твоя сотка — это просто вопрос дисциплины и алгоритма. Алгоритм у нас есть.',
        { auto: 4500 }
      );
    })
    .then(function () { return wait(300); })
    .then(function () {
      var ctaWrap = addEl('div', 'cinema-cta-wrap');
      var btn = addEl('a', 'cinema-cta-btn', ctaWrap);
      btn.textContent = 'Выбрать тариф и начать подготовку';
      btn.href = '/billing/plans/public';
      self._els.push(ctaWrap);
      requestAnimationFrame(function () { btn.classList.add('visible'); });
      btn.addEventListener('click', function () { self.endCinema(false); });
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
      case 6: this.sceneTrainer(); break;
      case 7: this.sceneAnalytics(); break;
      case 8: this.sceneEpilogue(); break;
      default: this.endCinema(true); break;
    }
  };

  CE.prototype.start = function () {
    if (lsGet(LS_ACTIVE) !== 'true') { this._removeInstantCover(); return; }
    this.running = true;
    this.buildControls();
    this.playScene();
  };

  /* ── Bootstrap ─────────────────────────────────────────────────── */
  function init() {
    var isDemo = false;
    try {
      if (document.cookie.indexOf('is_demo=true') !== -1) isDemo = true;
      if (lsGet('is_demo') === 'true') isDemo = true;
    } catch (e) {}
    if (!isDemo) return;

    if (document.cookie.indexOf('cinemaMode=prologue') !== -1) {
      lsSet(LS_ACTIVE, 'true');
      lsSet(LS_SCENE, '0');
      lsRemove(LS_TRANSITION);
      document.cookie = 'cinemaMode=; path=/; max-age=0';
    }

    var metaIds = qs('meta[name="cinema-demo-ids"]');
    if (metaIds) {
      try {
        var c = metaIds.getAttribute('content');
        if (c) lsSet(LS_DEMO_IDS, c);
      } catch (e) {}
    }

    var engine = new CE();
    engine.start();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 200); });
  } else {
    setTimeout(init, 200);
  }
})();
