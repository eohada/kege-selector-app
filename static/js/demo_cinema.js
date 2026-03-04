/**
 * Demo Cinema Engine v5
 * Fixes: analytics data, EGE tab, lesson tabs, no auto-continue,
 * skip confirmation, fill-all-answers, trainer with real task.
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
  function currentPage() { return (document.body.getAttribute('data-cinema-scene') || '').toLowerCase(); }

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
    this._els.forEach(function (el) { removeEl(el); });
    this._els = [];
    qsa('.cinema-neon-hud').forEach(function (e) { e.classList.remove('cinema-neon-hud'); });
    document.body.classList.remove('cinema-freeze');
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

  /* ── Subtitle (always waits for user unless auto) ──────────────── */
  CE.prototype.showSubtitle = function (text, opts) {
    var self = this;
    opts = opts || {};
    var autoMs   = opts.auto;
    var withBtn  = opts.withContinue !== false && !autoMs;
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
        self._t(function () { removeEl(wrap); resolve(); }, 500);
      }

      if (autoMs) {
        self._t(dismiss, autoMs);
      } else if (btn) {
        btn.onclick = function () { btn.onclick = null; dismiss(); };
      } else {
        self._t(dismiss, 3500);
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

  /* ── Spotlight (box-shadow hole) ───────────────────────────────── */
  CE.prototype.spotlight = function (selector, durationMs, label) {
    var self = this;
    durationMs = durationMs || 3000;
    return new Promise(function (resolve) {
      var el = typeof selector === 'string' ? qs(selector) : selector;
      if (!el) return resolve();
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });

      self._t(function () {
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return resolve();
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
          if (lt > vh - 50) lt = Math.max(8, top - 40);
          lbl.style.top = lt + 'px';
          lbl.style.transform = 'translateX(-50%)';
          self._els.push(lbl);
        }

        requestAnimationFrame(function () {
          hole.classList.add('visible', 'pulse');
          if (lbl) lbl.classList.add('visible');
        });

        self._t(function () {
          hole.classList.remove('visible');
          if (lbl) lbl.classList.remove('visible');
          self._t(function () { removeEl(hole); if (lbl) removeEl(lbl); resolve(); }, 400);
        }, durationMs);
      }, 700);
    });
  };

  CE.prototype.autoScroll = function (sel, ms) {
    var self = this; ms = ms || 2000;
    return new Promise(function (r) { var e = qs(sel); if (!e) return r(); e.scrollIntoView({ behavior: 'smooth', block: 'center' }); self._t(r, ms); });
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

  /* ── Controls ──────────────────────────────────────────────────── */
  CE.prototype.buildControls = function () {
    var self = this, wrap = addEl('div', 'cinema-controls');
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

  /* ── 1: Dashboard ──────────────────────────────────────────────── */
  CE.prototype.sceneDashboard = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Это твой личный командный центр. Всё, что нужно — на одном экране.', { continueLabel: 'Понятно' });
    })
    .then(function () {
      var el = qs('#cinema-notifications') || qs('.hero-actions');
      if (el) return self.spotlight(el, 3000, 'Быстрые действия');
      return wait(300);
    })
    .then(function () {
      var el = qs('#cinema-weak-topics') || qs('[data-cinema="weak-topics"]');
      if (el) return self.spotlight(el, 3000, 'Слабые темы — фокус подготовки');
      return wait(300);
    })
    .then(function () {
      return self.showSubtitle('Любой успех начинается с планирования. Заглянем в расписание.', { continueLabel: 'К расписанию' });
    })
    .then(function () { if (self.running) self.advance(2, '/schedule', 'swipeLeft'); });
  };

  /* ── 2: Schedule ───────────────────────────────────────────────── */
  CE.prototype.sceneSchedule = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Все уроки — в одном расписании. Никаких накладок и забытых занятий.', { continueLabel: 'Понятно' });
    })
    .then(function () {
      var chip = qs('.lesson-chip');
      if (chip) return self.spotlight(chip, 3000, 'Карточка урока');
      var grid = qs('#scheduleGrid');
      if (grid) return self.spotlight(grid, 3000, 'Сетка расписания');
      return wait(500);
    })
    .then(function () {
      return self.showSubtitle('Чтобы подготовиться к уроку, нужна теория. Идём за знаниями.', { continueLabel: 'К теории' });
    })
    .then(function () { if (self.running) self.advance(3, '/theory', 'swipeLeft'); });
  };

  /* ── 3: Theory ─────────────────────────────────────────────────── */
  CE.prototype.sceneTheory = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Здесь собрана вся теория для ЕГЭ по информатике. Каждое задание — отдельный конспект.', { continueLabel: 'Покажи' });
    })
    .then(function () {
      var card = qs('.theory-card');
      if (card) return self.spotlight(card, 3000, 'Конспект по теме');
      return wait(500);
    })
    .then(function () {
      return self.showSubtitle('Теория без практики мертва. Пора решать настоящие задания.', { continueLabel: 'К заданиям' });
    })
    .then(function () { if (self.running) self.advance(4, '/submissions', 'glitch'); });
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
      return self.showSubtitle('Это боевые задания от преподавателя. Дедлайны, ограничения попыток — всё серьёзно.', { continueLabel: 'Покажи' });
    })
    .then(function () {
      var card = qs('.demo-submission-card') || qs('.submission-card');
      if (card) return self.spotlight(card, 3000, 'Карточка задания');
      return wait(500);
    })
    .then(function () {
      return self.showSubtitle('Давай зайдём в задание и решим его прямо сейчас.', { continueLabel: 'Открыть задание' });
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
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      var startBtn = qs('#start-btn');
      if (startBtn) {
        return self.showSubtitle('Ты внутри задания. Нажми кнопку, чтобы начать выполнение и увидеть условия.', { continueLabel: 'Начать выполнение' })
        .then(function () {
          lsSet(LS_TRANSITION, 'fade');
          self.simulateClick(startBtn);
          self.running = false;
        });
      }
      return self.showSubtitle('Перед тобой задания с условиями. Давай заполним все ответы.', { continueLabel: 'Заполнить ответы' });
    })
    .then(function () {
      if (!self.running) return;
      var answers = qsa('.answer-input');
      var chain = Promise.resolve();
      answers.forEach(function (textarea, idx) {
        chain = chain.then(function () {
          textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return wait(400);
        }).then(function () {
          textarea.value = '42';
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
      return wait(400);
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
      return self.showSubtitle('Идеальный результат! 5 из 5 баллов — 100%. Так работают задания на платформе.', { continueLabel: 'Дальше' });
    })
    .then(function () {
      if (!self.running) return;
      var lid = self.ids.lessonId;
      if (lid) self.advance(5, '/lesson/' + lid + '/classwork-tasks', 'swipeLeft');
      else self.advance(6, '/trainer/v2', 'hyperJump');
    });
  };

  /* ── 5: Lesson ─────────────────────────────────────────────────── */
  CE.prototype.sceneLesson = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Это экран урока. Преподаватель ведёт занятие, а ты решаешь задачи прямо здесь.', { continueLabel: 'Покажи' });
    })
    .then(function () {
      var navBar = qs('.task-nav-bar');
      if (navBar) return self.spotlight(navBar, 3000, 'Навигация по заданиям');
      return wait(300);
    })
    .then(function () {
      var navBtns = qsa('.task-nav-btn');
      if (navBtns.length > 1) {
        self.simulateClick(navBtns[0]);
        return wait(600);
      }
      return wait(300);
    })
    .then(function () {
      var card = qs('.task-card');
      if (card) return self.spotlight(card, 3000, 'Карточка задания на уроке');
      return wait(300);
    })
    .then(function () {
      var answerInput = qs('input[id^="submission_"]') || qs('.neo-input[placeholder*="ответ"]');
      if (answerInput) {
        return self.spotlight(answerInput, 2000, 'Поле для ответа').then(function () {
          return self.typeIntoField('42', answerInput);
        });
      }
      return wait(300);
    })
    .then(function () {
      var saveBtn = qs('#cinema-save-draft') || qs('[data-cinema="save-draft"]');
      if (saveBtn) return self.spotlight(saveBtn, 2500, 'Сохрани черновик');
      return wait(300);
    })
    .then(function () {
      return self.showSubtitle('Застрял на задаче? Для этого у нас есть AI-тренажёр.', { continueLabel: 'В тренажёр' });
    })
    .then(function () { if (self.running) self.advance(6, '/trainer/v2', 'hyperJump'); });
  };

  /* ── 6: Trainer — scripted scenario with real task ─────────────── */
  CE.prototype.sceneTrainer = function () {
    var self = this;
    var correctAnswer = self.ids.trainerAnswer || '42';
    var taskNum = self.ids.trainerTaskNumber || 1;
    var wrongAnswer = correctAnswer === '42' ? '99' : '0';
    var answerEl = null;

    self.playEntryTransition()
    .then(function () { return wait(600); })
    .then(function () {
      return self.showSubtitle('Это AI-тренажёр. Здесь можно решать задачи бесконечно — ИИ поможет разобраться в ошибках.', { continueLabel: 'Начнём' });
    })
    .then(function () {
      var dock = qs('#trainerV2Dock') || qs('.trainer-v2-root');
      if (dock) dock.classList.add('cinema-neon-hud');

      var select = qs('#tv2TaskType');
      if (select) {
        select.value = String(taskNum);
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }

      qsa('#tv2NextBtn, #tv2ZenExitBtn').forEach(function (b) {
        b.style.pointerEvents = 'none'; b.style.opacity = '0.3';
      });
      return wait(400);
    })
    .then(function () {
      var startBtn = qs('#tv2StartBtn');
      if (startBtn) return self.spotlight(startBtn, 2500, 'Загрузить задание');
      return wait(300);
    })
    .then(function () {
      return self.showSubtitle('Нажми «начать» — ИИ подберёт задание по выбранной теме.', { continueLabel: 'Загрузить задание' });
    })
    .then(function () {
      var startBtn = qs('#tv2StartBtn');
      if (startBtn) self.simulateClick(startBtn);
      return wait(800);
    })
    .then(function () {
      return self.waitForEl('#tv2AnswerInput', 8000);
    })
    .then(function (el) {
      answerEl = el;
      if (!answerEl) return wait(500);
      return self.showSubtitle('Задание загружено. Попробуй ввести неправильный ответ — посмотрим, как реагирует ИИ.', { continueLabel: 'Ввести ответ' });
    })
    .then(function () {
      if (!answerEl) return wait(300);
      return self.spotlight(answerEl, 2000, 'Поле ответа');
    })
    .then(function () {
      if (!answerEl) return wait(300);
      return self.typeIntoField(wrongAnswer, answerEl);
    })
    .then(function () {
      if (!answerEl) return wait(300);
      var checkBtn = qs('.tv2-fab-primary');
      if (checkBtn) {
        return self.spotlight(checkBtn, 1500, 'Проверить').then(function () {
          self.simulateClick(checkBtn);
          return wait(2500);
        });
      }
      return wait(500);
    })
    .then(function () {
      return self.showAITooltip('Ответ неверный. Подсказка: внимательно перечитай условие — проверь граничные значения и порядок операций.', 4500);
    })
    .then(function () {
      return self.showSubtitle('ИИ даёт подсказку после каждой ошибки. Теперь введём правильный ответ.', { continueLabel: 'Исправить' });
    })
    .then(function () {
      if (!answerEl) return wait(300);
      answerEl.value = '';
      answerEl.dispatchEvent(new Event('input', { bubbles: true }));
      return self.typeIntoField(correctAnswer, answerEl);
    })
    .then(function () {
      if (!answerEl) return wait(300);
      var checkBtn = qs('.tv2-fab-primary');
      if (checkBtn) {
        self.simulateClick(checkBtn);
        return wait(2000);
      }
      return wait(500);
    })
    .then(function () { return self.flash(); })
    .then(function () { return self.showCorrectBadge(); })
    .then(function () {
      var dock = qs('#trainerV2Dock') || qs('.trainer-v2-root');
      if (dock) dock.classList.remove('cinema-neon-hud');
      qsa('#tv2NextBtn, #tv2ZenExitBtn').forEach(function (b) {
        b.style.pointerEvents = ''; b.style.opacity = '';
      });
      return wait(200);
    })
    .then(function () {
      return self.showSubtitle('Вот так работает тренажёр: ошибся — подсказка — исправил. А теперь посмотрим на аналитику.', { continueLabel: 'К аналитике' });
    })
    .then(function () {
      if (!self.running) return;
      var sid = self.ids.studentId;
      if (sid) self.advance(7, '/student/' + sid + '/analytics', 'swipeLeft');
      else { lsSet(LS_SCENE, '8'); self.scene = 8; self.sceneEpilogue(); }
    });
  };

  /* ── 7: Analytics — both tabs ──────────────────────────────────── */
  CE.prototype.sceneAnalytics = function () {
    var self = this;
    self.playEntryTransition()
    .then(function () { return wait(400); })
    .then(function () {
      return self.showSubtitle('Здесь собрана вся аналитика подготовки. Каждое действие на платформе имеет вес.', { continueLabel: 'Покажи' });
    })
    .then(function () {
      var el = qs('.metrics-grid');
      if (el) return self.spotlight(el, 3000, 'Ключевые метрики');
      return wait(400);
    })
    .then(function () {
      var el = qs('.charts-grid');
      if (el) return self.spotlight(el, 3000, 'Графики и тренды');
      return wait(400);
    })
    .then(function () {
      return self.showSubtitle('Это вкладка «Навыки». Теперь переключимся на «Аналитику ЕГЭ».', { continueLabel: 'Переключить' });
    })
    .then(function () {
      var tabBtn = qs('.stats-tab[data-tab="analytics"]');
      if (tabBtn) {
        self.simulateClick(tabBtn);
        return wait(800);
      }
      return wait(300);
    })
    .then(function () {
      var table = qs('#analyticsNodesTable') || qs('.analytics-nodes-table');
      if (table) return self.spotlight(table, 3000, 'Рейтинг по заданиям ЕГЭ');
      return wait(400);
    })
    .then(function () {
      var el = qs('#analyticsPredictedScore');
      if (el) return self.spotlight(el, 2500, 'Прогноз балла ЕГЭ');
      return wait(300);
    })
    .then(function () {
      return self.showSubtitle('Графики, рейтинги, прогноз баллов — всё обновляется в реальном времени.', { continueLabel: 'Финал' });
    })
    .then(function () {
      if (self.running) { lsSet(LS_SCENE, '8'); self.scene = 8; self.sceneEpilogue(); }
    });
  };

  /* ── 8: Epilogue ───────────────────────────────────────────────── */
  CE.prototype.sceneEpilogue = function () {
    var self = this;
    document.body.classList.add('cinema-freeze');
    var ov = addEl('div', 'cinema-overlay'); ov.classList.add('visible'); self._els.push(ov);

    wait(500)
    .then(function () {
      return self.showSubtitle('Платформа готова. Твоя сотка — это вопрос дисциплины и алгоритма. Алгоритм у нас есть.', { continueLabel: 'Выбрать тариф' });
    })
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
      try { var c = metaIds.getAttribute('content'); if (c) lsSet(LS_DEMO_IDS, c); } catch (e) {}
    }

    var engine = new CE();
    engine.start();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 250); });
  } else { setTimeout(init, 250); }
})();
