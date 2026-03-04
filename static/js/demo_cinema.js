/**
 * Demo Cinema Engine — state-machine-driven cinematic onboarding tour.
 * Works across full-page reloads by persisting scene index in localStorage.
 */
(function () {
  'use strict';

  /* ── constants ─────────────────────────────────────────────────── */
  var TOTAL_SCENES = 9; // 0=prologue … 7=analytics, 8=epilogue
  var LS_ACTIVE    = 'cinemaActive';
  var LS_SCENE     = 'cinemaScene';
  var LS_TRANSITION = 'cinemaTransition';
  var LS_DEMO_IDS  = 'cinemaDemoIds';    // JSON: {submissionId, lessonId, studentId}
  var TYPEWRITER_MS = 35;

  /* ── helpers ───────────────────────────────────────────────────── */
  function qs(sel, ctx) { return (ctx || document).querySelector(sel); }
  function qsa(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }

  function wait(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }

  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function lsRemove(k) { try { localStorage.removeItem(k); } catch (e) {} }

  function getDemoIds() {
    try { return JSON.parse(lsGet(LS_DEMO_IDS)) || {}; } catch (e) { return {}; }
  }

  function addEl(tag, cls, parent) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    (parent || document.body).appendChild(el);
    return el;
  }

  function removeEl(el) {
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  /* ── Cinema Engine ─────────────────────────────────────────────── */
  function CinemaEngine() {
    this.scene = parseInt(lsGet(LS_SCENE) || '0', 10);
    this.transition = lsGet(LS_TRANSITION) || '';
    this.running = false;
    this._elements = [];
    this._timeouts = [];
    this.ids = getDemoIds();
  }

  CinemaEngine.prototype._timeout = function (fn, ms) {
    var self = this;
    var id = setTimeout(function () {
      if (self.running) fn();
    }, ms);
    this._timeouts.push(id);
    return id;
  };

  CinemaEngine.prototype._clearTimeouts = function () {
    this._timeouts.forEach(function (id) { clearTimeout(id); });
    this._timeouts = [];
  };

  /* ── DOM cleanup ───────────────────────────────────────────────── */
  CinemaEngine.prototype._cleanup = function () {
    this._clearTimeouts();
    this._elements.forEach(function (el) { removeEl(el); });
    this._elements = [];
    qsa('.cinema-spotlight-ring').forEach(function (el) { el.classList.remove('cinema-spotlight-ring'); });
    qsa('.cinema-neon-hud').forEach(function (el) { el.classList.remove('cinema-neon-hud'); });
    var bd = qs('.cinema-backdrop-blur');
    if (bd) removeEl(bd);
    document.body.classList.remove('cinema-freeze');
  };

  /* ── Subtitle ──────────────────────────────────────────────────── */
  CinemaEngine.prototype.showSubtitle = function (text, durationMs) {
    var self = this;
    durationMs = durationMs || 3000;
    return new Promise(function (resolve) {
      var wrap = addEl('div', 'cinema-subtitle-wrap');
      var sub = addEl('div', 'cinema-subtitle', wrap);
      sub.textContent = text;
      self._elements.push(wrap);
      requestAnimationFrame(function () {
        sub.classList.add('visible');
      });
      self._timeout(function () {
        sub.classList.remove('visible');
        sub.classList.add('exit');
        self._timeout(function () {
          removeEl(wrap);
          resolve();
        }, 700);
      }, durationMs);
    });
  };

  /* ── Typewriter ────────────────────────────────────────────────── */
  CinemaEngine.prototype.typewriter = function (text, container) {
    var self = this;
    return new Promise(function (resolve) {
      var idx = 0;
      var span = addEl('span', '', container);
      var cursor = addEl('span', 'cinema-cursor', container);
      self._elements.push(cursor);
      function tick() {
        if (!self.running) return resolve();
        if (idx >= text.length) {
          removeEl(cursor);
          return resolve();
        }
        span.textContent += text[idx];
        idx++;
        self._timeout(tick, TYPEWRITER_MS);
      }
      self._timeout(tick, 300);
    });
  };

  /* ── Typewriter into form field ────────────────────────────────── */
  CinemaEngine.prototype.typeIntoField = function (text, selector) {
    var self = this;
    return new Promise(function (resolve) {
      var el = qs(selector);
      if (!el) return resolve();
      var idx = 0;
      var val = '';
      function tick() {
        if (!self.running || idx >= text.length) {
          if (el) el.dispatchEvent(new Event('input', { bubbles: true }));
          return self._timeout(resolve, 300);
        }
        val += text[idx];
        idx++;
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        self._timeout(tick, 90);
      }
      el.value = '';
      self._timeout(tick, 200);
    });
  };

  /* ── Spotlight ─────────────────────────────────────────────────── */
  CinemaEngine.prototype.spotlight = function (selector, durationMs) {
    var self = this;
    durationMs = durationMs || 3000;
    return new Promise(function (resolve) {
      var el = qs(selector);
      if (!el) return resolve();
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      var bd = qs('.cinema-backdrop-blur') || addEl('div', 'cinema-backdrop-blur');
      self._elements.push(bd);
      requestAnimationFrame(function () {
        bd.classList.add('visible');
        el.classList.add('cinema-spotlight-ring');
      });
      self._timeout(function () {
        el.classList.remove('cinema-spotlight-ring');
        bd.classList.remove('visible');
        self._timeout(function () {
          removeEl(bd);
          resolve();
        }, 500);
      }, durationMs);
    });
  };

  /* ── Auto-scroll ───────────────────────────────────────────────── */
  CinemaEngine.prototype.autoScroll = function (selector, durationMs) {
    var self = this;
    durationMs = durationMs || 2000;
    return new Promise(function (resolve) {
      var el = qs(selector);
      if (!el) return resolve();
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      self._timeout(resolve, durationMs);
    });
  };

  /* ── Transitions ───────────────────────────────────────────────── */
  CinemaEngine.prototype.playEntryTransition = function () {
    var self = this;
    var type = this.transition;
    if (!type) return Promise.resolve();
    lsRemove(LS_TRANSITION);

    if (type === 'elevatorDoors') {
      return new Promise(function (resolve) {
        var left = addEl('div', 'cinema-elevator-left');
        var right = addEl('div', 'cinema-elevator-right');
        self._elements.push(left, right);
        self._timeout(function () {
          left.classList.add('open');
          right.classList.add('open');
          self._timeout(function () {
            removeEl(left);
            removeEl(right);
            resolve();
          }, 1300);
        }, 400);
      });
    }

    if (type === 'swipeLeft') {
      return new Promise(function (resolve) {
        var cover = addEl('div', 'cinema-swipe-cover');
        self._elements.push(cover);
        self._timeout(function () {
          cover.classList.add('exit-left');
          self._timeout(function () {
            removeEl(cover);
            resolve();
          }, 700);
        }, 100);
      });
    }

    if (type === 'glitch') {
      return new Promise(function (resolve) {
        var layer = addEl('div', 'cinema-glitch-layer');
        self._elements.push(layer);
        self._timeout(function () {
          layer.classList.add('active');
          self._timeout(function () {
            removeEl(layer);
            resolve();
          }, 700);
        }, 50);
      });
    }

    if (type === 'hyperJump') {
      return new Promise(function (resolve) {
        var hs = addEl('div', 'cinema-hyperspace');
        var stars = addEl('div', 'cinema-hyperspace-stars', hs);
        for (var i = 0; i < 12; i++) {
          var s = addEl('div', 'cinema-hyperspace-streak', hs);
          var angle = (i / 12) * 360;
          s.style.transform = 'translate(-50%, -50%) rotate(' + angle + 'deg)';
          s.style.animationDelay = (Math.random() * 0.3).toFixed(2) + 's';
        }
        self._elements.push(hs);
        self._timeout(function () {
          removeEl(hs);
          resolve();
        }, 1100);
      });
    }

    if (type === 'fade') {
      return new Promise(function (resolve) {
        var ov = addEl('div', 'cinema-overlay');
        ov.style.opacity = '1';
        self._elements.push(ov);
        self._timeout(function () {
          ov.style.transition = 'opacity 0.8s ease';
          ov.style.opacity = '0';
          self._timeout(function () {
            removeEl(ov);
            resolve();
          }, 900);
        }, 200);
      });
    }

    return Promise.resolve();
  };

  /* ── Navigate (exit + go) ──────────────────────────────────────── */
  CinemaEngine.prototype.navigateTo = function (url, transition) {
    var self = this;
    this.running = false;
    lsSet(LS_TRANSITION, transition || 'fade');

    var ov = addEl('div', 'cinema-overlay');
    ov.classList.add('visible');

    setTimeout(function () {
      window.location.href = url;
    }, 500);
  };

  CinemaEngine.prototype.advanceScene = function (nextScene, url, transition) {
    lsSet(LS_SCENE, String(nextScene));
    this.navigateTo(url, transition);
  };

  /* ── Flash effect ──────────────────────────────────────────────── */
  CinemaEngine.prototype.flash = function () {
    var self = this;
    return new Promise(function (resolve) {
      var f = addEl('div', 'cinema-flash');
      self._elements.push(f);
      requestAnimationFrame(function () { f.classList.add('active'); });
      self._timeout(function () { removeEl(f); resolve(); }, 600);
    });
  };

  /* ── "Correct" badge ───────────────────────────────────────────── */
  CinemaEngine.prototype.showCorrectBadge = function () {
    var self = this;
    return new Promise(function (resolve) {
      var b = addEl('div', 'cinema-correct-badge');
      b.textContent = 'ВЕРНО';
      self._elements.push(b);
      requestAnimationFrame(function () { b.classList.add('visible'); });
      self._timeout(function () { removeEl(b); resolve(); }, 2000);
    });
  };

  /* ── AI tooltip ────────────────────────────────────────────────── */
  CinemaEngine.prototype.showAITooltip = function (text, x, y, durationMs) {
    var self = this;
    durationMs = durationMs || 3500;
    return new Promise(function (resolve) {
      var tip = addEl('div', 'cinema-ai-tooltip');
      var lbl = addEl('div', 'cinema-ai-tooltip-label', tip);
      lbl.textContent = 'AI-АССИСТЕНТ';
      var body = addEl('div', '', tip);
      body.textContent = text;
      if (x !== undefined && y !== undefined) {
        tip.style.left = x + 'px';
        tip.style.top = y + 'px';
      } else {
        tip.style.top = '50%';
        tip.style.left = '50%';
        tip.style.transform = 'translate(-50%, -50%)';
      }
      self._elements.push(tip);
      requestAnimationFrame(function () { tip.classList.add('visible'); });
      self._timeout(function () {
        tip.classList.remove('visible');
        self._timeout(function () { removeEl(tip); resolve(); }, 500);
      }, durationMs);
    });
  };

  /* ── Control widget ────────────────────────────────────────────── */
  CinemaEngine.prototype.buildControls = function () {
    var self = this;
    var wrap = addEl('div', 'cinema-controls');
    self._controls = wrap;

    var pips = addEl('div', 'cinema-progress-pip', wrap);
    for (var i = 0; i < TOTAL_SCENES; i++) {
      var p = addEl('div', 'cinema-pip', pips);
      if (i < self.scene) p.classList.add('done');
      if (i === self.scene) p.classList.add('current');
    }

    var skipBtn = addEl('button', 'cinema-ctrl-btn', wrap);
    skipBtn.textContent = 'Пропустить тур';
    skipBtn.onclick = function () { self.endCinema(true); };
  };

  /* ── End cinema ────────────────────────────────────────────────── */
  CinemaEngine.prototype.endCinema = function (redirect) {
    this.running = false;
    this._cleanup();
    lsRemove(LS_ACTIVE);
    lsRemove(LS_SCENE);
    lsRemove(LS_TRANSITION);
    lsRemove(LS_DEMO_IDS);
    if (this._controls) removeEl(this._controls);
    document.body.classList.remove('cinema-freeze');
    if (redirect) {
      window.location.href = '/student/dashboard';
    }
  };

  /* =================================================================
     SCENE DEFINITIONS
     ================================================================= */

  /* ── 0: Prologue ───────────────────────────────────────────────── */
  CinemaEngine.prototype.scenePrologue = function () {
    var self = this;
    document.body.classList.add('cinema-freeze');

    var wrap = addEl('div', 'cinema-typewriter-wrap');
    self._elements.push(wrap);
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
  CinemaEngine.prototype.sceneDashboard = function () {
    var self = this;

    self.playEntryTransition().then(function () {
      return wait(600);
    }).then(function () {
      return self.showSubtitle('Это твой личный командный центр. Всё, что нужно — на одном экране.', 3500);
    }).then(function () {
      return wait(400);
    }).then(function () {
      var notif = qs('#cinema-notifications') || qs('.hero-actions');
      var weak = qs('#cinema-weak-topics') || qs('[data-cinema="weak-topics"]');
      if (notif) {
        return self.spotlight(notif.id ? '#' + notif.id : '.hero-actions', 2500);
      }
      return wait(500);
    }).then(function () {
      return wait(300);
    }).then(function () {
      return self.showSubtitle('Но любой успех начинается с планирования. Заглянем в будущее.', 3000);
    }).then(function () {
      return wait(500);
    }).then(function () {
      if (self.running) {
        self.advanceScene(2, '/schedule', 'swipeLeft');
      }
    });
  };

  /* ── 2: Schedule ───────────────────────────────────────────────── */
  CinemaEngine.prototype.sceneSchedule = function () {
    var self = this;

    self.playEntryTransition().then(function () {
      return wait(600);
    }).then(function () {
      return self.showSubtitle('Твоё время под строгим контролем. Никаких накладок.', 3500);
    }).then(function () {
      return wait(400);
    }).then(function () {
      var card = qs('#cinema-nearest-lesson') || qs('.schedule-day-col .lesson-card') || qs('.schedule-shell');
      if (card) {
        return self.spotlight(card.id ? '#' + card.id : '.schedule-day-col .lesson-card', 2500);
      }
      return wait(1000);
    }).then(function () {
      return self.showSubtitle('Чтобы выжить на уроке, нужна база. Идём за знаниями.', 3000);
    }).then(function () {
      return wait(500);
    }).then(function () {
      if (self.running) {
        self.advanceScene(3, '/theory', 'swipeLeft');
      }
    });
  };

  /* ── 3: Theory ─────────────────────────────────────────────────── */
  CinemaEngine.prototype.sceneTheory = function () {
    var self = this;

    self.playEntryTransition().then(function () {
      return wait(600);
    }).then(function () {
      return self.showSubtitle('Вся выжимка для ЕГЭ здесь. Без воды и пыльных учебников.', 3500);
    }).then(function () {
      return wait(400);
    }).then(function () {
      var grid = qs('.theory-grid');
      if (grid) {
        return self.autoScroll('.theory-grid', 2000);
      }
      return wait(1000);
    }).then(function () {
      return self.showSubtitle('Теория без практики мертва. Время настоящей проверки.', 3000);
    }).then(function () {
      return wait(500);
    }).then(function () {
      if (self.running) {
        self.advanceScene(4, '/submissions', 'glitch');
      }
    });
  };

  /* ── 4: Submissions ────────────────────────────────────────────── */
  CinemaEngine.prototype.sceneSubmissions = function () {
    var self = this;

    self.playEntryTransition().then(function () {
      return wait(600);
    }).then(function () {
      return self.showSubtitle('Это боевые задания. Здесь есть дедлайны и лимиты попыток. Никаких подсказок.', 3500);
    }).then(function () {
      return wait(400);
    }).then(function () {
      var btn = qs('.demo-highlight-begin') || qs('.demo-btn-begin');
      if (btn) {
        return self.spotlight(
          btn.classList.contains('demo-highlight-begin') ? '.demo-highlight-begin' : '.demo-btn-begin',
          2500
        );
      }
      return wait(1000);
    }).then(function () {
      return self.showSubtitle('Сдано вовремя. А теперь перенесёмся в самый эпицентр — на живой урок.', 3000);
    }).then(function () {
      return wait(500);
    }).then(function () {
      if (!self.running) return;
      var lessonId = self.ids.lessonId;
      if (lessonId) {
        self.advanceScene(5, '/lesson/' + lessonId + '/classwork-tasks', 'swipeLeft');
      } else {
        self.advanceScene(6, '/trainer/v2', 'hyperJump');
      }
    });
  };

  /* ── 5: Lesson classwork ───────────────────────────────────────── */
  CinemaEngine.prototype.sceneLesson = function () {
    var self = this;

    self.playEntryTransition().then(function () {
      return wait(600);
    }).then(function () {
      return self.showSubtitle('Слушаешь преподавателя и сразу решаешь задачи. Всё в одном окне.', 3500);
    }).then(function () {
      return wait(400);
    }).then(function () {
      var saveBtn = qs('#cinema-save-draft') || qs('.btn-save-draft') || qs('[data-cinema="save-draft"]');
      if (saveBtn) {
        var sel = saveBtn.id ? '#' + saveBtn.id : '.btn-save-draft';
        return self.spotlight(sel, 2500);
      }
      return wait(1000);
    }).then(function () {
      return self.showSubtitle('Застрял? Сохрани черновик и доделай позже. Но что если тема совсем не даётся?', 3500);
    }).then(function () {
      return wait(400);
    }).then(function () {
      return self.showSubtitle('Для этого мы создали песочницу. Добро пожаловать в Тренажёр.', 2500);
    }).then(function () {
      return wait(500);
    }).then(function () {
      if (self.running) {
        self.advanceScene(6, '/trainer/v2', 'hyperJump');
      }
    });
  };

  /* ── 6: Trainer (AI) ───────────────────────────────────────────── */
  CinemaEngine.prototype.sceneTrainer = function () {
    var self = this;

    self.playEntryTransition().then(function () {
      return wait(800);
    }).then(function () {
      return self.showSubtitle('Здесь можно тренироваться сколько угодно. ИИ подскажет, если ошибёшься.', 3500);
    }).then(function () {
      return wait(600);
    }).then(function () {
      var dock = qs('#trainerV2Dock') || qs('.trainer-v2-root');
      if (dock) {
        dock.classList.add('cinema-neon-hud');
        return wait(2000).then(function () {
          dock.classList.remove('cinema-neon-hud');
        });
      }
      return wait(1000);
    }).then(function () {
      return self.showAITooltip(
        'Обнаружена ошибка логики. Запускаю протокол коррекции...',
        undefined, undefined, 3000
      );
    }).then(function () {
      return self.flash();
    }).then(function () {
      return self.showCorrectBadge();
    }).then(function () {
      return wait(600);
    }).then(function () {
      return self.showSubtitle('Здесь можно ошибаться. Мы научим, как правильно. А теперь посмотри на свои результаты.', 3500);
    }).then(function () {
      return wait(500);
    }).then(function () {
      if (!self.running) return;
      var sid = self.ids.studentId;
      if (sid) {
        self.advanceScene(7, '/student/' + sid + '/analytics', 'swipeLeft');
      } else {
        lsSet(LS_SCENE, '8');
        self.scene = 8;
        self.sceneEpilogue();
      }
    });
  };

  /* ── 7: Analytics ──────────────────────────────────────────────── */
  CinemaEngine.prototype.sceneAnalytics = function () {
    var self = this;

    self.playEntryTransition().then(function () {
      return wait(600);
    }).then(function () {
      return self.showSubtitle('Каждое твоё действие на платформе имеет вес.', 3500);
    }).then(function () {
      return wait(400);
    }).then(function () {
      var charts = qs('.charts-grid') || qs('.metrics-grid');
      if (charts) {
        return self.spotlight(
          charts.classList.contains('charts-grid') ? '.charts-grid' : '.metrics-grid',
          3000
        );
      }
      return wait(1000);
    }).then(function () {
      return wait(500);
    }).then(function () {
      if (self.running) {
        lsSet(LS_SCENE, '8');
        self.scene = 8;
        self.sceneEpilogue();
      }
    });
  };

  /* ── 8: Epilogue ───────────────────────────────────────────────── */
  CinemaEngine.prototype.sceneEpilogue = function () {
    var self = this;
    document.body.classList.add('cinema-freeze');

    var ov = addEl('div', 'cinema-overlay');
    ov.classList.add('visible');
    self._elements.push(ov);

    wait(600).then(function () {
      return self.showSubtitle(
        'Платформа готова. Твоя сотка — это просто вопрос дисциплины и алгоритма. Алгоритм у нас есть.',
        4500
      );
    }).then(function () {
      return wait(400);
    }).then(function () {
      var ctaWrap = addEl('div', 'cinema-cta-wrap');
      var btn = addEl('a', 'cinema-cta-btn', ctaWrap);
      btn.textContent = 'Выбрать тариф и начать подготовку';
      btn.href = '/billing/plans/public';
      self._elements.push(ctaWrap);
      requestAnimationFrame(function () {
        btn.classList.add('visible');
      });
      btn.addEventListener('click', function () {
        self.endCinema(false);
      });
    });
  };

  /* ── Scene dispatcher ──────────────────────────────────────────── */
  CinemaEngine.prototype.playScene = function () {
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

  /* ── Entry point ───────────────────────────────────────────────── */
  CinemaEngine.prototype.start = function () {
    if (lsGet(LS_ACTIVE) !== 'true') return;
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
        var content = metaIds.getAttribute('content');
        if (content) lsSet(LS_DEMO_IDS, content);
      } catch (e) {}
    }

    var engine = new CinemaEngine();
    engine.start();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 300); });
  } else {
    setTimeout(init, 300);
  }
})();
