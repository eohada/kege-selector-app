/**
 * BooStudy Demo Companion UI Component
 * Renders Boo mascot, speech bubble, dialog interactions, chapter HUD, and emotion states.
 * Visual Canon compliant: No emojis, Phosphor icons, reduced motion friendly, authentic 3D mascot.
 */
(function (global) {
  'use strict';

  var MASCOT_ASSETS = {
    happy: '/static/images/profile/hero_ghost.png',
    curious: '/static/images/lesson/lesson_task_mascot.png',
    thinking: '/static/images/lesson/lesson_task_mascot.png',
    celebrating: '/static/images/profile/modal_ghost_trophy.png',
    gentle_warning: '/static/images/profile/hero_ghost.png',
  };

  function BooCompanion() {
    this.engine = null;
    this.scenario = null;
    this.rootEl = null;
    this.hudBarEl = null;
    this.hudTextEl = null;
    this.hudDotsEl = null;
    this.cardEl = null;
    this.avatarBtn = null;
    this.messageBox = null;
    this.characterTagEl = null;
    this.choicesContainer = null;
    this.actionsContainer = null;
    this.isMinimized = false;
    this.isTyping = false;
    this._typingTimer = null;
    this._lastSpokenKey = null;
    this._guidedObjective = null;
    this._guidedBlockTimer = null;
  }

  BooCompanion.prototype.init = function (engine, scenario) {
    var self = this;
    this.engine = engine;
    this.scenario = scenario;

    if (document.getElementById('boo-companion-root')) {
      this.rootEl = document.getElementById('boo-companion-root');
    } else {
      this.rootEl = document.createElement('div');
      this.rootEl.id = 'boo-companion-root';
      document.body.appendChild(this.rootEl);
    }

    this._buildDOM();
    this._bindEvents();
    var navigationEntry = window.performance && performance.getEntriesByType ? performance.getEntriesByType('navigation')[0] : null;
    var restoredByBrowser = !!(navigationEntry && navigationEntry.type === 'back_forward');
    var canonicalUrl = sessionStorage.getItem('boostudy_demo_current_url');
    if (restoredByBrowser && canonicalUrl && new URL(canonicalUrl, window.location.origin).origin === window.location.origin && canonicalUrl !== window.location.href) {
      window.location.replace(canonicalUrl);
      return this;
    }
    if (!restoredByBrowser) sessionStorage.setItem('boostudy_demo_current_url', window.location.href);
    window.addEventListener('pageshow', function (event) {
      if (!event.persisted) return;
      var current = sessionStorage.getItem('boostudy_demo_current_url');
      if (current && new URL(current, window.location.origin).origin === window.location.origin && current !== window.location.href) window.location.replace(current);
    });
    document.body.classList.add('boo-page-enter');
    window.requestAnimationFrame(function () { document.body.classList.remove('boo-page-enter'); });

    if ((window.location.pathname || '').indexOf('/task-workspace') !== -1) {
      document.body.classList.add('boo-workspace-active');
    }

    var state = this.engine.getState();
    // The chapter-one UI lives only on /demo. Product pages must never acquire
    // a floating companion that can cover their controls during restoration.
    if (state.chapter_id !== 'chapter_1' || (window.location.pathname || '') !== '/demo') this.rootEl.classList.add('boo-no-chat');
    this.renderStep(state.chapter_id, state.step_id);
    if (state.mode === 'explore') {
      this.rootEl.classList.add('boo-explore-mode');
    } else if (state.chapter_id === 'chapter_2' && state.step_id === 'chapter2_mission') {
      window.setTimeout(function () { self.showChapter2PageDialogue(); }, 180);
    } else {
      // A chapter card only introduces the destination.  On the real product
      // page Boo immediately gives the learner one concrete next action.
      window.setTimeout(function () { self.showProductSceneDialogue(); }, 240);
    }
    // The welcome page hides the dashboard for one paint while this real
    // cinematic layer is being mounted.  Revealing it here eliminates the
    // dashboard flash between chapters one and two.
    document.documentElement.classList.remove('boo-cinematic-boot');
    if (state.chapter_id === 'chapter_3' && state.step_id === 'trial_intro' && this.cinemaEl.hidden && !this.engine.hasActionCompleted('demo:chapter3:mode_prompted')) {
      this.showWorkspaceStory();
    }
    if (state.chapter_id === 'chapter_10' && state.step_id === 'finale') {
      this.showFinale();
    }

    // Проверка редиректа из заблокированной зоны
    if (window.location.search.indexOf('demo_blocked=1') !== -1) {
      setTimeout(function () {
        self.showOutOfBoundsWarning();
      }, 500);
    }

    return this;
  };

  BooCompanion.prototype._buildDOM = function () {
    var self = this;
    this.rootEl.innerHTML = [
      '<div class="boo-hud-bar" id="boo-hud-bar">',
      '  <div class="boo-hud-badge">',
      '    <i class="ph-bold ph-compass"></i>',
      '    <span id="boo-hud-chapter-text">Демонстрация · кабинет через полгода</span>',
      '  </div>',
      '  <div class="boo-hud-dots" id="boo-hud-dots">',
      '    <span class="boo-hud-dot is-active" id="boo-dot-1" title="Глава 1: Знакомство"></span>',
      '    <span class="boo-hud-dot" id="boo-dot-2" title="Глава 2: Учебная база"></span>',
      '    <span class="boo-hud-dot" id="boo-dot-3" title="Глава 3: Первое испытание"></span>',
      '  </div>',
      '</div>',
      '<button type="button" class="boo-director-trigger" id="boo-director-trigger" aria-label="Открыть режиссёрскую панель" aria-expanded="false" title="Режиссёрский режим"><i class="ph-bold ph-clapperboard"></i></button>',
      '<aside class="boo-director-panel" id="boo-director-panel" hidden aria-label="Режиссёрский режим">',
      ' <header><span><i class="ph-bold ph-clapperboard"></i> Режиссёрский режим</span><button type="button" data-director-action="close" aria-label="Закрыть панель"><i class="ph-bold ph-x"></i></button></header>',
      ' <p>Быстрый переход по демо-сценам</p><div class="boo-director-chapters">',
      '  <button type="button" data-director-chapter="chapter_1"><b>01</b><span>Знакомство</span></button><button type="button" data-director-chapter="chapter_2"><b>02</b><span>Кабинет</span></button><button type="button" data-director-chapter="chapter_3"><b>03</b><span>Испытание</span></button><button type="button" data-director-chapter="chapter_4"><b>04</b><span>Разбор</span></button><button type="button" data-director-chapter="chapter_5"><b>05</b><span>Ошибки</span></button><button type="button" data-director-chapter="chapter_6"><b>06</b><span>Маршрут</span></button><button type="button" data-director-chapter="chapter_7"><b>07</b><span>Аналитика</span></button><button type="button" data-director-chapter="chapter_8"><b>08</b><span>Расписание</span></button><button type="button" data-director-chapter="chapter_9"><b>09</b><span>Профиль</span></button><button type="button" data-director-chapter="chapter_10"><b>10</b><span>Финал</span></button>',
      ' </div><footer><button type="button" data-director-action="motion"><i class="ph-bold ph-lightning"></i> Анимации</button><button type="button" data-director-action="reset"><i class="ph-bold ph-arrow-counter-clockwise"></i> Сбросить демо</button></footer>',
      '</aside>',
      '<aside class="boo-story-guide" id="boo-story-guide" aria-live="polite" hidden><img id="boo-story-guide-mascot" src="/static/images/demo/boo-dialogue-v1.png" alt="Бу"><div><span><i class="ph-bold ph-compass"></i> Бу подсказывает</span><strong id="boo-story-guide-text"></strong><button type="button" id="boo-story-guide-action">Показать следующий шаг <i class="ph-bold ph-arrow-right"></i></button></div><button class="boo-story-guide-close" type="button" aria-label="Скрыть подсказку"><i class="ph-bold ph-x"></i></button></aside>',
      '<div class="boo-focus-veil" id="boo-focus-veil" hidden aria-hidden="true"></div>',
      '<div class="boo-focus-hole" id="boo-focus-hole" hidden aria-hidden="true"></div>',
      '<section class="boo-novel-dialogue" id="boo-novel-dialogue" hidden aria-modal="true" role="dialog" aria-labelledby="boo-novel-name"><div class="boo-novel-backdrop"></div><div class="boo-novel-mascot"><img src="/static/images/demo/boo-dialogue-v1.png" alt="Бу"></div><div class="boo-novel-box"><div class="boo-novel-name" id="boo-novel-name">Бу</div><p class="boo-novel-text" id="boo-novel-text" aria-live="polite"></p><div class="boo-novel-actions" id="boo-novel-actions"></div><button type="button" class="boo-novel-close" id="boo-novel-close">Продолжить <i class="ph-bold ph-arrow-right"></i></button></div></section>',
      '<section class="boo-route-guard" id="boo-route-guard" hidden aria-live="assertive"><div class="boo-route-guard-backdrop"></div><div class="boo-route-guard-card"><img src="/static/images/demo/boo-dialogue-v1.png" alt="Бу"><div><span>Бу ведёт сценарий</span><h2>Сюда пока не нужно.</h2><p id="boo-route-guard-text">Сейчас важнее следующий кадр истории.</p><button type="button" id="boo-route-guard-close">Вернуться к кадру <i class="ph-bold ph-arrow-right"></i></button></div></div></section>',
      '<div class="boo-chapter2-mission" id="boo-chapter2-mission" hidden aria-live="polite" tabindex="-1">',
      '  <span class="boo-mission-icon"><i class="ph-bold ph-compass"></i></span>',
      '  <span><small>Демонстрационный маршрут</small><strong id="boo-chapter2-mission-count">Кабинет через полгода</strong></span>',
      '</div>',
      '<div class="boo-companion-card" id="boo-card">',
      '  <div class="boo-card-header">',
      '    <div class="boo-character-tag">',
      '      <span class="boo-tag-dot"></span>',
      '      <span id="boo-character-tag-text">Бу</span>',
      '    </div>',
      '    <div class="boo-controls">',
      '      <button type="button" class="boo-control-btn" id="boo-help-btn" title="Подсказка" aria-label="Подсказка">',
      '        <i class="ph-bold ph-question"></i>',
      '      </button>',
      '      <button type="button" class="boo-control-btn" id="boo-toggle-motion" title="Тумблер анимаций" aria-label="Тумблер анимаций">',
      '        <i class="ph-bold ph-lightning"></i>',
      '      </button>',
      '      <button type="button" class="boo-control-btn" id="boo-minimize-btn" title="Свернуть" aria-label="Свернуть">',
      '        <i class="ph-bold ph-caret-down"></i>',
      '      </button>',
      '    </div>',
      '  </div>',
      '  <div class="boo-message-box" id="boo-message-box"></div>',
      '  <div class="boo-choices-grid" id="boo-choices-box"></div>',
      '  <div class="boo-actions-box" id="boo-actions-box"></div>',
      '</div>',
      '<section class="boo-story-mode" id="boo-story-mode" hidden aria-modal="true" role="dialog" aria-labelledby="boo-story-title" tabindex="-1">',
      '  <div class="boo-story-backdrop"></div><header class="boo-story-nav"><span><i class="ph-bold ph-graduation-cap"></i> BooStudy <small>Демо-версия</small></span><b>Учебная база</b></header>',
      '  <div class="boo-story-stage"><aside class="boo-story-visual"><p>Твоя новая<br>учебная база</p><img src="/static/images/demo/boo-onboarding-hero-v2.png" alt="Бу с учебными материалами"></aside><div class="boo-story-panel"><span>Глава 2 · Твоя учебная база</span><h2 id="boo-story-title">Добро пожаловать в учебную базу!</h2><p id="boo-story-message"></p><div class="boo-story-highlights"><span><i class="ph-bold ph-book-open"></i> Уроки</span><span><i class="ph-bold ph-clipboard-text"></i> Задания</span><span><i class="ph-bold ph-chart-line-up"></i> Прогресс</span></div><button type="button" id="boo-story-start">Показывай! <i class="ph-bold ph-arrow-right"></i></button></div></div>',
      '</section>',
      '<section class="boo-workspace-story" id="boo-workspace-story" hidden aria-modal="true" role="dialog" aria-labelledby="boo-workspace-story-title" tabindex="-1">',
      ' <div class="boo-workspace-backdrop"></div><header class="boo-workspace-nav"><span><i class="ph-bold ph-graduation-cap"></i> BooStudy <small>Демо-версия</small></span><b>Первое испытание</b></header><div class="boo-workspace-story-stage"><aside class="boo-workspace-story-visual"><p>Первое<br>испытание</p><img src="/static/images/lesson/lesson_task_mascot.png" alt="Бу готовит первое испытание"></aside><div class="boo-workspace-story-card"><span>Первое испытание</span><h2 id="boo-workspace-story-title">Выбери способ решения</h2><p>Здесь можно быстро записать ответ или написать код. Это настоящие режимы рабочего пространства — начни с удобного для себя.</p><div class="boo-workspace-mode-actions"><button type="button" id="boo-workspace-answer"><i class="ph-bold ph-pencil-simple"></i> Режим «Ответ»</button><button type="button" id="boo-workspace-code"><i class="ph-bold ph-code"></i> Режим «Код»</button></div></div></div>',
      '</section>',
      '<section class="boo-finale-mode" id="boo-finale-mode" hidden aria-modal="true" role="dialog" aria-labelledby="boo-finale-title" tabindex="-1">',
      '  <div class="boo-finale-backdrop"></div><header class="boo-finale-nav"><span><i class="ph-bold ph-graduation-cap"></i> BooStudy <small>Демо-версия</small></span><b>Твой следующий шаг</b></header><div class="boo-finale-stage"><aside class="boo-finale-visual"><span>Ты справился!</span><img src="/static/images/demo/boo-dialogue-v1.png" alt="Бу рядом"></aside><div class="boo-finale-panel"><p class="boo-finale-kicker">Теперь ты видел не обещание, а путь</p><h2 id="boo-finale-title">Как начнём?</h2><p id="boo-finale-message"></p><div class="boo-finale-summary" id="boo-finale-summary"></div><div class="boo-finale-actions"><button type="button" data-finale-action="booking">Оставить заявку на вводный урок</button><button type="button" data-finale-action="formats">Посмотреть тарифы</button><button type="button" data-finale-action="telegram">Написать Бу в Telegram</button></div><form id="boo-intro-request" hidden><p class="boo-request-explainer">Оставь контакт и удобное время: куратор BooStudy свяжется с тобой и поможет выбрать формат. После отправки повторять заявку не нужно.</p><label>Имя<input name="name" required maxlength="120" autocomplete="name"></label><label>Класс<input name="grade" required maxlength="30"></label><label>Цель<input name="goal" required maxlength="120"></label><label>Telegram, телефон или email<input name="contact" required maxlength="250" placeholder="@username, +7 900 000-00-00 или email" aria-describedby="boo-contact-error"></label><small id="boo-contact-error" role="alert"></small><label>Удобные дата и время<input name="slot" type="datetime-local" required></label><label><input name="consent" type="checkbox" required> Согласен(на) на обработку данных и связь по заявке (<a href="/legal/privacy" target="_blank" rel="noopener">политика</a>)</label><p id="boo-request-status" role="status" aria-live="polite"></p><button type="submit">Отправить заявку</button><button type="button" data-finale-action="cancel-booking">Назад к вариантам</button></form></div></div>',
      '</section>',
      '<section class="boo-cinema-mode" id="boo-cinema-mode" hidden aria-modal="true" role="dialog" aria-labelledby="boo-cinema-title" tabindex="-1">',
      '  <div class="boo-cinema-backdrop"></div>',
      '  <header class="boo-cinema-nav"><span class="boo-cinema-brand"><i class="ph-bold ph-graduation-cap"></i> BooStudy <small>Демо-версия</small></span><span id="boo-cinema-progress">Демо · маршрут</span></header>',
      '  <div class="boo-cinema-stage"><aside class="boo-cinema-visual"><div class="boo-cinema-orbit"></div><img id="boo-cinema-mascot" src="/static/images/profile/hero_ghost.png" alt="Бу"><span class="boo-cinema-note" id="boo-cinema-note"></span></aside><article class="boo-cinema-panel"><p id="boo-cinema-kicker"></p><h2 id="boo-cinema-title"></h2><p id="boo-cinema-message"></p><div class="boo-cinema-points" id="boo-cinema-points"></div><div class="boo-cinema-actions" id="boo-cinema-actions"></div></article></div>',
      '</section>',
      '<div class="boo-scene-feedback" id="boo-scene-feedback" role="status" aria-live="polite" hidden></div>',
      '<button type="button" class="boo-avatar-button emotion-happy" id="boo-avatar-btn" title="Поговорить с Бу" aria-label="Поговорить с Бу">',
      '  <div class="boo-avatar-img-wrap">',
      '    <img id="boo-mascot-img" src="' + MASCOT_ASSETS.happy + '" alt="Бу" class="boo-avatar-img">',
      '  </div>',
      '  <span class="boo-avatar-ping" id="boo-avatar-ping"></span>',
      '</button>',
    ].join('\n');

    this.hudBarEl = document.getElementById('boo-hud-bar');
    this.hudTextEl = document.getElementById('boo-hud-chapter-text');
    this.hudDotsEl = document.getElementById('boo-hud-dots');
    this.directorTrigger = document.getElementById('boo-director-trigger');
    this.directorPanel = document.getElementById('boo-director-panel');
    this.storyGuide = document.getElementById('boo-story-guide');
    this.novelEl = document.getElementById('boo-novel-dialogue');
    this.focusVeilEl = document.getElementById('boo-focus-veil');
    this.focusHoleEl = document.getElementById('boo-focus-hole');
    this.novelTextEl = document.getElementById('boo-novel-text');
    this.novelActionsEl = document.getElementById('boo-novel-actions');
    this.cardEl = document.getElementById('boo-card');
    this.avatarBtn = document.getElementById('boo-avatar-btn');
    this.messageBox = document.getElementById('boo-message-box');
    this.characterTagEl = document.getElementById('boo-character-tag-text');
    this.choicesContainer = document.getElementById('boo-choices-box');
    this.actionsContainer = document.getElementById('boo-actions-box');
    this.missionEl = document.getElementById('boo-chapter2-mission');
    this.storyEl = document.getElementById('boo-story-mode');
    this.workspaceStoryEl = document.getElementById('boo-workspace-story');
    this.finaleEl = document.getElementById('boo-finale-mode');
    this.cinemaEl = document.getElementById('boo-cinema-mode');
    this.feedbackEl = document.getElementById('boo-scene-feedback');
    var introRequestForm = document.getElementById('boo-intro-request');
    if (introRequestForm) {
      introRequestForm.insertAdjacentHTML('beforeend',
        '<div class="boo-request-followup" id="boo-request-followup" hidden>' +
          '<strong>Заявка у меня</strong><span>Отвечу в Telegram.</span>' +
          '<div><button type="button" data-finale-action="formats">Тарифы</button>' +
          '<button type="button" data-finale-action="return-finale">К финалу</button></div>' +
        '</div>');
    }

    // The guided demo is linear. Keep the old chapter-jump control available
    // only for an explicitly requested presenter session, and remove the
    // unexplained mission counter from the learner-facing header.
    if (this.hudDotsEl) this.hudDotsEl.hidden = true;
    if (this.directorTrigger && new URLSearchParams(window.location.search).get('director') !== '1') this.directorTrigger.hidden = true;

    // Кнопка сворачивания
    document.getElementById('boo-minimize-btn').addEventListener('click', function () {
      self.toggleMinimize();
    });

    // Кнопка помощи / контекстной подсказки
    document.getElementById('boo-help-btn').addEventListener('click', function () {
      self._onHelpClicked();
    });

    // Аватарка разворачивает бабл
    this.avatarBtn.addEventListener('click', function () {
      if (self.isMinimized) {
        self.toggleMinimize();
      } else {
        self._onAvatarClicked();
      }
    });

    // Тумблер анимаций
    document.getElementById('boo-toggle-motion').addEventListener('click', function () {
      document.documentElement.classList.toggle('demo-no-motion');
      var isReduced = document.documentElement.classList.contains('demo-no-motion');
      self.say(isReduced ? 'Режим без анимаций включён.' : 'Анимации включены.', 'thinking');
    });
    document.getElementById('boo-story-start').addEventListener('click', function () {
      self._startChapter2Mission();
    });
    document.addEventListener('keydown', function (event) {
      self._handleOverlayKeydown(event);
    });
    this._startChapter2Mission = function () {
      self._hideOverlay(self.storyEl, self.missionEl);
      self.rootEl.classList.add('boo-no-chat');
      self.engine.completeAction('demo:chapter2:started');
      self.engine.goToStep('chapter2_mission', 'chapter_2');
      if ((window.location.pathname || '') === '/demo') { self.navigate('/dashboard'); return; }
      self.say('Пойдём по порядку: сначала откроем программу обучения. После неё Бу вернёт тебя в кабинет к уроку и работам.', 'curious');
      window.setTimeout(function () { if (self.missionEl && !self.missionEl.hidden) self.missionEl.focus(); }, 0);
    };
    document.getElementById('boo-workspace-answer').addEventListener('click', function () { self._selectWorkspaceMode('answer'); });
    document.getElementById('boo-workspace-code').addEventListener('click', function () { self._selectWorkspaceMode('code'); });
    var activateFinalAction = function (event) {
      var button = event.target.closest('[data-finale-action]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      self._handleFinalAction(button.getAttribute('data-finale-action'));
    };
    this.finaleEl.addEventListener('click', activateFinalAction);
    document.getElementById('boo-intro-request').addEventListener('submit', function (event) { self._submitIntroRequest(event); });
    this.cinemaEl.addEventListener('click', function (event) {
      var button = event.target.closest('[data-cinema-action]');
      if (!button) return;
      var action = button.getAttribute('data-cinema-action');
      if (action === 'close') {
        // A cinematic scene is a required stop in the linear demo. Closing it
        // without taking the primary action leaves no active next step.
        var primary = document.querySelector('#boo-cinema-actions [data-cinema-action]');
        if (primary) self._handleActionButton(primary.getAttribute('data-cinema-action'), {}, self.engine.getState().chapter_id);
      } else self._handleActionButton(action, {}, self.engine.getState().chapter_id);
    });
    this.directorTrigger.addEventListener('click', function () { self.toggleDirector(); });
    this.directorPanel.addEventListener('click', function (event) {
      var chapterButton = event.target.closest('[data-director-chapter]');
      if (chapterButton) { self.jumpToChapter(chapterButton.getAttribute('data-director-chapter')); return; }
      var actionButton = event.target.closest('[data-director-action]');
      if (!actionButton) return;
      var action = actionButton.getAttribute('data-director-action');
      if (action === 'close') self.toggleDirector(false);
      else if (action === 'motion') document.getElementById('boo-toggle-motion').click();
      else if (action === 'reset') self.jumpToChapter('chapter_1');
    });
    document.getElementById('boo-story-guide-action').addEventListener('click', function () {
      self._focusNextObjective();
    });
    document.querySelector('.boo-story-guide-close').addEventListener('click', function () {
      self.storyGuide.hidden = true;
    });
    document.getElementById('boo-route-guard-close').addEventListener('click', function () { self.hideRouteGuard(); self._focusNextObjective(); });
    document.getElementById('boo-novel-close').addEventListener('click', function () { self._continueNovelDialogue(); });
    document.addEventListener('keydown', function (event) {
      if (!self.novelEl || self.novelEl.hidden) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        self._continueNovelDialogue();
      } else if (event.key === 'Enter' && self.isTyping) {
        event.preventDefault();
        self._revealNovelText();
      }
    });
    // Keep ordinary product links from cutting abruptly between demo scenes.
    // Modified clicks, downloads and external links retain native browser behaviour.
    document.addEventListener('click', function (event) {
      var link = event.target.closest && event.target.closest('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
          link.target || link.hasAttribute('download') || link.origin !== window.location.origin) return;
      if (link.closest('[data-demo-target="upcoming-lesson"]') && self.engine.getState().chapter_id === 'chapter_2') {
        event.preventDefault();
        self._onTargetInteracted('upcoming-lesson');
        self.say('Этот урок появится в расписании позже. В демо не нужно ждать преподавателя: урок отмечен, а дальше можно открыть работы или программу.', 'happy');
        return;
      }
      if (link.closest('[data-demo-target="past-lesson"]') && self.engine.getState().chapter_id === 'chapter_2') {
        event.preventDefault();
        return;
      }
      // A course card is the next deliberately opened part of the programme
      // tour.  It must remain available while every unrelated page is guarded.
      if ((self._isChapter2ProgramList() || (self.engine.getState().chapter_id === 'chapter_6' && self.engine.getState().step_id === 'route_intro')) && link.matches('[data-demo-program-course]')) {
        event.preventDefault();
        self.navigate(link.href);
        return;
      }
      if (!link.closest('#boo-companion-root') && !link.closest('[data-demo-target]') && self.engine.getState().chapter_id !== 'chapter_1' && self.engine.getState().chapter_id !== 'chapter_10') {
        event.preventDefault(); self.showRouteGuard(); return;
      }
      if (!link.closest('#boo-companion-root') && !link.hasAttribute('data-demo-target')) self._recordDetour(link);
      event.preventDefault();
      self.navigate(link.href);
    });
  };

  BooCompanion.prototype.navigate = function (url) {
    if (!url) return;
    this._navigating = true;
    try {
      var next = new URL(url, window.location.origin);
      if (next.origin === window.location.origin) sessionStorage.setItem('boostudy_demo_current_url', next.href);
    } catch (_) {}
    if (document.documentElement.classList.contains('demo-no-motion') || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.location.assign(url);
      return;
    }
    document.body.classList.add('boo-page-leave');
    window.setTimeout(function () { window.location.assign(url); }, 190);
  };

  BooCompanion.prototype.toggleDirector = function (open) {
    if (!this.directorPanel) return;
    var willOpen = open === undefined ? this.directorPanel.hidden : open;
    this.directorPanel.hidden = !willOpen;
    this.directorTrigger.setAttribute('aria-expanded', String(willOpen));
    if (willOpen) {
      var state = this.engine.getState();
      this.directorPanel.querySelectorAll('[data-director-chapter]').forEach(function (button) {
        button.classList.toggle('is-current', button.getAttribute('data-director-chapter') === state.chapter_id);
      });
      this.directorPanel.querySelector('[data-director-chapter]').focus();
    } else this.directorTrigger.focus();
  };

  BooCompanion.prototype.jumpToChapter = function (chapter) {
    var self = this;
    if (!chapter) return;
    this.directorPanel.classList.add('is-loading');
    var csrf = document.querySelector('meta[name="csrf-token"]');
    fetch('/demo/api/director', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf && csrf.content || '' },
      body: JSON.stringify({ chapter: chapter })
    }).then(function (response) {
      if (!response.ok) throw new Error('director jump rejected');
      return response.json();
    }).then(function (data) {
      self.navigate(data.url || '/dashboard');
    }).catch(function () {
      self.directorPanel.classList.remove('is-loading');
      self.say('Не удалось перейти к этой сцене. Попробуй ещё раз.', 'gentle_warning');
    });
  };

  BooCompanion.prototype.showChapter2Story = function () {
    if (!this.storyEl) return;
    var name = this.engine.getState().student_name || 'Демо-ученик';
    document.getElementById('boo-story-message').textContent = name + ', добро пожаловать в свою учебную базу! Я уже кое-что для тебя подготовил. Здесь будут твои занятия, задания, результаты и всё, что поможет двигаться к цели. Давай вместе посмотрим, как всё устроено!';
    this._showOverlay(this.storyEl, document.getElementById('boo-story-start'));
  };

  BooCompanion.prototype.showWorkspaceStory = function () {
    if (!this.workspaceStoryEl) return;
    // The workspace mode chooser is a true foreground scene.  Do not leave a
    // fixed companion card above its controls on small viewports.
    if (this.storyGuide) this.storyGuide.hidden = true;
    this._showOverlay(this.workspaceStoryEl, document.getElementById('boo-workspace-answer'));
  };

  BooCompanion.prototype.showFinale = function () {
    if (!this.finaleEl) return;
    var state = this.engine.getState();
    var goalNames = { ege_80: 'ЕГЭ 80+', ege_90: 'ЕГЭ 90+', oge_5: 'ОГЭ на 5', programming: 'научиться программировать', choosing: 'пока выбираю' };
    document.getElementById('boo-finale-message').textContent = (state.student_name || 'Ты') + ', теперь ты видел не обещание, а путь: цель, практика, поддержка и рост. Выбери, с какого первого шага начнём.';
    var summary = document.getElementById('boo-finale-summary');
    summary.replaceChildren();
    [
      'Цель: ' + (goalNames[state.goal] || 'выбранный маршрут'),
      'Программа → урок → практика',
      'Работа над ошибками → аналитика',
      'Расписание → профиль'
    ].forEach(function (item) {
      var span = document.createElement('span');
      span.textContent = item;
      summary.appendChild(span);
    });
    var form = document.getElementById('boo-intro-request');
    var requestSent = !!(state.flags && state.flags.intro_request_sent);
    var status = document.getElementById('boo-request-status');
    var contactError = document.getElementById('boo-contact-error');
    if (contactError) contactError.textContent = '';
    if (requestSent && status) status.textContent = 'Заявка уже у Бу. Здесь можно изменить слот или контакт.';
    var actions = this.finaleEl.querySelector('.boo-finale-actions');
    if (actions) {
      var booking = actions.querySelector('[data-finale-action="booking"]');
      if (booking && state.goal === 'choosing') booking.classList.add('is-primary');
      else if (actions.querySelector('[data-finale-action="formats"]')) actions.querySelector('[data-finale-action="formats"]').classList.add('is-primary');
    }
    var primaryAction = state.goal === 'choosing' ? 'booking' : 'formats';
    this._showOverlay(this.finaleEl, this.finaleEl.querySelector('[data-finale-action="' + primaryAction + '"]'));
    this.engine.completeAction('demo:finale:shown');
  };

  BooCompanion.prototype._recordFinalChoice = function (choice) {
    this.engine.completeAction('demo:finale:cta_' + choice, { choice: choice });
    var hint = document.getElementById('boo-request-status');
    if (hint) hint.textContent = 'Следующий шаг открыт';
    var buttons = this.finaleEl.querySelectorAll('[data-finale-action]');
    buttons.forEach(function (button) { button.classList.remove('is-selected'); });
    var buttonAction = choice === 'plans' ? 'formats' : choice;
    var selected = this.finaleEl.querySelector('[data-finale-action="' + buttonAction + '"]');
    if (selected) {
      selected.classList.add('is-selected');
      selected.setAttribute('aria-label', selected.textContent.trim() + ' — следующий шаг открыт');
    }
  };

  BooCompanion.prototype._handleFinalAction = function (action) {
    if (action === 'booking') { this._recordFinalChoice('booking'); this._openIntroRequest(); }
    else if (action === 'cancel-booking') this._closeIntroRequest();
    else if (action === 'return-finale') this._closeIntroRequest();
    else if (action === 'formats') { this._recordFinalChoice('plans'); window.open('/billing/plans/public', '_blank', 'noopener'); }
    else if (action === 'telegram') {
      this._recordFinalChoice('telegram');
      var state = this.engine.getState();
      var message = 'Привет! Я прошёл демо BooStudy и хочу подобрать формат подготовки. Подскажите, пожалуйста, с чего начать? ' + (state.student_name || '');
      window.open('https://t.me/eohada?text=' + encodeURIComponent(message), '_blank', 'noopener');
    }
  };

  BooCompanion.prototype._openIntroRequest = function () {
    var form = document.getElementById('boo-intro-request');
    if (!form) return;
    var state = this.engine.getState();
    form.hidden = false;
    var followup = document.getElementById('boo-request-followup');
    if (followup) followup.hidden = true;
    form.querySelector('[name="name"]').value = state.student_name || '';
    form.querySelector('[name="grade"]').value = state.grade || '';
    form.querySelector('[name="goal"]').value = ({ ege_80: 'ЕГЭ 80+', ege_90: 'ЕГЭ 90+', oge_5: 'ОГЭ на 5', programming: 'научиться программировать', choosing: 'пока выбираю' })[state.goal] || state.goal || '';
    var slot = form.querySelector('[name="slot"]');
    if (!slot.value) {
      var date = new Date(Date.now() + 3 * 86400000);
      date.setHours(18, 0, 0, 0);
      slot.value = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    }
    var status = document.getElementById('boo-request-status');
    if (status && state.flags && state.flags.intro_request_sent) status.textContent = 'Заявка уже у Бу. Измени удобное время или контакт — новую заявку создавать не будем.';
    form.scrollIntoView({ behavior: 'smooth', block: 'center' });
    form.querySelector('[name="contact"]').focus({ preventScroll: true });
  };

  BooCompanion.prototype._closeIntroRequest = function () {
    var form = document.getElementById('boo-intro-request');
    if (form) form.hidden = true;
    var followup = document.getElementById('boo-request-followup');
    if (followup) followup.hidden = true;
    this._recordFinalChoice('finale');
  };

  BooCompanion.prototype._submitIntroRequest = function (event) {
    event.preventDefault();
    var form = event.currentTarget;
    var status = document.getElementById('boo-request-status');
    var consent = form.querySelector('[name="consent"]');
    if (!consent.checked) {
      status.textContent = 'Чтобы отправить заявку, нужно согласиться на обработку данных и связь. Это нужно, чтобы Бу мог ответить тебе.';
      consent.focus();
      return;
    }
    var payload = Object.fromEntries(new FormData(form).entries());
    payload.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    payload.consent = true;
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
    if (csrf && csrf.content) headers['X-CSRFToken'] = csrf.content;
    var self = this;
    var submitButton = form.querySelector('button[type="submit"], button[data-request-submit]');
    if (submitButton) submitButton.disabled = true;
    status.textContent = 'Отправляю Бу…';
    fetch('/demo/api/request', { method: 'POST', headers: headers, body: JSON.stringify(payload) })
      .then(function (response) { return response.json().then(function (data) { if (!response.ok) throw new Error(data.error || 'Не удалось отправить заявку.'); return data; }); })
      .then(function (data) {
        self.engine.setFlag('intro_request_sent', true);
        self._recordFinalChoice('booking');
        status.textContent = data.existing ? 'Заявка уже у Бу. Время и контакт обновлены. Отвечу в Telegram.' : 'Заявка у меня. Отвечу в Telegram.';
        var followup = document.getElementById('boo-request-followup');
        if (followup) followup.hidden = false;
        if (submitButton) submitButton.disabled = true;
      })
      .catch(function (error) {
        if (submitButton) submitButton.disabled = false;
        if (error && error.message) {
          var contact = form.querySelector('[name="contact"]');
          if (contact && /контакт|Telegram|email/i.test(error.message)) {
            contact.setAttribute('aria-invalid', 'true');
            if (contactError) contactError.textContent = error.message;
            contact.focus();
          }
        }
        status.textContent = 'Не получилось отправить автоматически — проверь поля и попробуй ещё раз.';
        self._introRequestFailure = true;
      });
  };

  BooCompanion.prototype._showOverlay = function (overlay, focusTarget) {
    if (!overlay) return;
    if (!overlay.hidden) return;
    this._overlayReturnFocus = document.activeElement;
    overlay.hidden = false;
    this._animateScene(overlay);
    this.rootEl.classList.add('boo-story-active');
    if (focusTarget) focusTarget.focus();
  };

  BooCompanion.prototype._hideOverlay = function (overlay, fallbackFocus) {
    if (overlay) overlay.hidden = true;
    this.rootEl.classList.remove('boo-story-active');
    var focusTarget = fallbackFocus || this._overlayReturnFocus;
    if (focusTarget && document.contains(focusTarget)) focusTarget.focus();
  };

  BooCompanion.prototype._handleOverlayKeydown = function (event) {
    var overlays = [this.finaleEl, this.workspaceStoryEl, this.storyEl];
    var active = overlays.find(function (overlay) { return overlay && !overlay.hidden; });
    if (!active) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      if (active === this.storyEl) this._startChapter2Mission();
      else if (active === this.workspaceStoryEl) this._selectWorkspaceMode('answer');
      else this._hideOverlay(this.finaleEl);
      return;
    }
    if (event.key !== 'Tab') return;
    var focusable = Array.prototype.slice.call(active.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'));
    if (!focusable.length) return;
    var currentIndex = focusable.indexOf(document.activeElement);
    if (event.shiftKey && (currentIndex <= 0)) {
      event.preventDefault();
      focusable[focusable.length - 1].focus();
    } else if (!event.shiftKey && currentIndex === focusable.length - 1) {
      event.preventDefault();
      focusable[0].focus();
    }
  };

  BooCompanion.prototype._selectWorkspaceMode = function (mode) {
    var modeButton = document.querySelector('[data-workspace-mode="' + mode + '"]');
    if (modeButton) modeButton.click();
    this.engine.completeAction('demo:chapter3:mode_prompted', { mode: mode });
    this.engine.setFlag('trial_mode', mode);
    this.engine.goToStep('trial_input', 'chapter_3');
    this._hideOverlay(this.workspaceStoryEl);
    this.rootEl.classList.add('boo-no-chat');
    window.setTimeout(function () { this._startTrialModeGuide(mode); }.bind(this), 280);
  };

  BooCompanion.prototype._bindEvents = function () {
    var self = this;

    this.engine.on('step_changed', function (ev) {
      self.renderStep(ev.chapterId, ev.stepId);
    });

    // Analytics contains its own clickable readiness controls.  On narrow
    // screens a click on the guided progress surface can otherwise bubble
    // into that drawer before the chapter transition is rendered.  The
    // guided target owns this gesture, so dispatch it here and stop the
    // product handler from mounting a competing layer.
    document.addEventListener('click', function (e) {
      var analyticsTarget = e.target.closest && e.target.closest('[data-demo-target="analytics-progress"]');
      if (!analyticsTarget || self.engine.getState().chapter_id !== 'chapter_7') return;
      e.preventDefault();
      e.stopImmediatePropagation();
      self._onTargetInteracted('analytics-progress');
    }, true);

    // Chapter 2 is deliberately a three-act guided sequence.  Capture the
    // click before normal navigation so a later card cannot skip its scene.
    document.addEventListener('click', function (e) {
      var gatedTarget = e.target.closest && e.target.closest('[data-demo-target]');
      if (!gatedTarget || self.engine.getState().chapter_id !== 'chapter_2' || self.engine.getState().step_id !== 'chapter2_mission') return;
      var currentTarget = gatedTarget.getAttribute('data-demo-target');
      // The programme has its own nested tour: course card → modules. These
      // are part of the already selected programme scene, not premature
      // chapter branches.
      if ((self._isChapter2ProgramList() && currentTarget === 'route-module') ||
          (self._isChapter2ProgramCourse() && currentTarget === 'program-module') ||
          // This is the explicit exit after the module has been shown.  It
          // used to be caught by the dashboard-only gate below, so a click on
          // “Вернуться в кабинет” opened a detour warning instead of taking
          // the learner back to the second cabinet scene.
          (self._isChapter2ProgramCourse() && currentTarget === 'program-return') ||
          ((window.location.pathname || '').indexOf('/lesson/') === 0 && currentTarget === 'lesson-room-tour')) return;
      var expectedTarget = self._nextDashboardTarget();
      if (expectedTarget && currentTarget !== expectedTarget) {
        e.preventDefault(); e.stopImmediatePropagation();
        self.say('Эта сцена будет следующей. Сначала закончим текущий шаг — я уже подсветил его.', 'gentle_warning');
        return;
      }
      // A linked target is still a scene marker during the guided tour; the
      // normal link should not cut away before Boo reacts to the discovery.
      if (e.target.closest('a[href]')) e.preventDefault();
    }, true);

    // Клик по элементам с data-demo-target
    document.addEventListener('click', function (e) {
      var targetEl = e.target.closest('[data-demo-target]');
      if (targetEl) {
        var targetName = targetEl.getAttribute('data-demo-target');
        self._onTargetInteracted(targetName);
      }
      if (e.target.closest && e.target.closest('#tw-run') && self.engine.getState().chapter_id === 'chapter_3' && self.engine.getState().step_id === 'trial_input' && self.engine.getFlag('trial_mode', 'answer') === 'code') {
        var startedAt = Date.now();
        var inspectResult = function () {
          var output = document.getElementById('tw-output');
          var outputText = output ? output.textContent.trim() : '';
          if (!outputText || outputText.indexOf('Код выполняется...') !== -1) {
            if (Date.now() - startedAt < 15000) window.setTimeout(inspectResult, 250);
            return;
          }
          if (outputText.indexOf('Время:') === -1 && outputText.indexOf('Ошибка Python:') === -1 && Date.now() - startedAt < 15000) {
            window.setTimeout(inspectResult, 250);
            return;
          }
          var printedValue = outputText.split(/\r?\n/)[0].trim();
          if (printedValue === '12') {
            self.engine.completeAction('trial_completed', { mode: 'code', output: printedValue });
            self.engine.goToStep('victory', 'chapter_3');
            return;
          }
          var attempts = Number(self.engine.getFlag('trial_code_attempts', 0)) + 1;
          self.engine.setFlag('trial_code_attempts', attempts);
          if (attempts >= 2) {
            var solution = document.querySelector('.tw-solution-accordion');
            if (solution) { solution.open = true; solution.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
            self.showNovelDialogue('Не сошлось — бывает. Вот решение: перебери marks, добавляй в total только числа, для которых number >= 3, и выведи total. Для списка [3, 1, 4, 1, 5] получится 12. Теперь покажу, как спокойно разбирать такие моменты.', 'Бу · разбор решения', { buttons: [{ label: 'Перейти к работе над ошибками', action: 'start_mistakes' }] });
            return;
          }
          self.showNovelDialogue('Почти. Проверь условие отбора: в сумму попадают только числа не меньше 3. Запусти ещё раз — если не выйдет, я покажу решение.', 'Бу · твой проводник', { buttons: [{ label: 'Вернуться к редактору', action: 'focus_code_editor' }] });
        };
        window.setTimeout(inspectResult, 250);
      }
    });
  };

  BooCompanion.prototype._onTargetInteracted = function (targetName) {
    var state = this.engine.getState();
    var currentChapter = state.chapter_id;

    if (currentChapter === 'chapter_2') {
      if (this._isChapter2ProgramCourse() && targetName === 'program-return') {
        this.navigate('/dashboard');
        return;
      }
      if (this._isChapter2ProgramList() && targetName === 'route-module') return;
      if (this._isChapter2ProgramCourse() && targetName === 'program-module') {
        this.engine.completeAction('demo:chapter2:module_opened');
        this.showNovelDialogue('Это один учебный модуль: внутри лежат занятия по одной теме, а курс собирает их в понятный порядок. Этого достаточно для знакомства — вернёмся к следующему кадру.', 'Бу · твой проводник', { buttons: [{ label: 'Вернуться в кабинет', action: 'return_dashboard' }] });
        return;
      }
      if (targetName === 'lesson-room-tour') {
        this.showNovelDialogue('Вот маршрут прошедшего урока: подготовка, практика и итог. Рядом остаются теория, доска и материалы — всё занятие собрано в одном рабочем пространстве.', 'Бу · твой проводник', { buttons: [{ label: 'Вернуться в кабинет', action: 'return_dashboard' }] });
        return;
      }
      var eventMap = {
        'upcoming-lesson': 'demo:dashboard:lesson_explored',
        'past-lesson': 'demo:dashboard:lesson_explored',
        'recent-assignments': 'demo:dashboard:assignments_explored',
        'learning-program': 'demo:dashboard:program_explored'
      };
      var eventName = eventMap[targetName];
      if (!eventName || !this.engine.completeAction(eventName, { target: targetName })) return;

      var reactions = {
        'past-lesson': 'Сейчас покажу комнату уже прошедшего урока. Это настоящее рабочее пространство BooStudy, и ждать начала не придётся.',
        'upcoming-lesson': 'Здесь будут появляться занятия. В демо мы не отправляем тебя в комнату ожидания: отметим урок и двинемся дальше.',
        'recent-assignments': 'Здесь собраны все твои работы. Кстати, я приготовил для тебя кое-что интересное!',
        'learning-program': 'А это твой учебный маршрут! Здесь видно, что уже пройдено и какие темы ждут впереди.'
      };
      this._updateMissionProgress();
      // The last discovery cuts to a full chapter scene.  Never leave a
      // visual-novel line mounted underneath that scene.
      if (this.engine.getState().step_id === 'chapter2_discovery') return;
      if (targetName === 'learning-program') {
        this.navigate(this.engine.getState().program_url || '/courses');
        return;
      }
      if (targetName === 'upcoming-lesson') {
        var lessonTarget = document.querySelector('[data-demo-target="upcoming-lesson"]');
        var lessonId = this.engine.getState().lesson_id;
        this.navigate((lessonTarget && lessonTarget.getAttribute('data-demo-lesson-url')) || (lessonId ? '/lesson/' + encodeURIComponent(lessonId) + '/room' : '/dashboard'));
        return;
      }
      if (targetName === 'past-lesson') {
        var pastLesson = document.querySelector('[data-demo-target="past-lesson"]');
        if (pastLesson && pastLesson.href) {
          var separator = pastLesson.href.indexOf('?') === -1 ? '?' : '&';
          this.navigate(pastLesson.href + separator + 'demo_preview=1');
        }
        return;
      }
      this.say(reactions[targetName], 'happy');
      return;
    }

    // On the catalogue the course card is a navigation door, not the module
    // itself.  Completing the route there previously skipped the course page
    // before Boo could introduce its module.
    if (currentChapter === 'chapter_6' && targetName === 'route-module' && (window.location.pathname || '') === (state.program_url || '').split('?')[0]) return;

    // A real product page has more than the one highlighted card.  Interacting
    // with an adjacent feature is still a narrative choice, not a failure.
    // Later chapters complete through real platform components, not merely on
    // route entry.  This keeps a refreshed page and a repeated click idempotent.
    var chapterEvents = {
      chapter_4: { 'theory-material': ['demo:library:material_opened', 'library_opened', 'В теории важен не только ответ: теперь ты видишь принцип, по которому строится решение.'] },
      chapter_5: { 'mistake-review': ['demo:mistakes:review_opened', 'mistakes_opened', 'Посмотри на комментарий наставника: ошибка не оценивает тебя, она показывает следующий понятный шаг.'] },
      chapter_6: {
        'route-module': ['demo:route:module_opened', 'route_opened', 'Маршрут открыт. Здесь видно, что уже получилось, что в работе и какой шаг ждёт дальше.'],
        'program-module': ['demo:route:module_opened', 'route_opened', 'Вот один модуль маршрута: занятия собраны в последовательность по теме. Мы не будем уходить в урок — сначала закончим эту сцену вместе.']
      },
      chapter_7: { 'analytics-progress': ['demo:wins:analytics_opened', 'wins_opened', 'Вот как отдельные уроки, задания и попытки складываются в твой настоящий прогресс.'] },
      chapter_8: { 'schedule-week': ['demo:schedule:week_opened', 'schedule_opened', 'Два вечерних занятия и самостоятельная практика между ними — это пример устойчивого ритма. Настоящее расписание мы не трогали.'] },
      chapter_9: { 'profile-achievements-action': ['demo:profile:achievements_opened', 'profile_opened', 'Уровень, серия и достижения отмечают твой собственный путь. Не рейтинг, а маленькие поводы заметить рост.'] }
    };
    var chapterMap = chapterEvents[currentChapter];
    if (targetName && currentChapter !== 'chapter_1' && !(chapterMap && chapterMap[targetName]) && targetName !== 'schedule-continue' && targetName !== 'profile-continue') {
      this.engine.completeAction('demo:branch:detour:' + targetName, { target: targetName, chapter: currentChapter });
      this.say('Это тоже часть твоей учебной базы. Осмотрись спокойно — компас сохранит следующий сюжетный шаг.', 'curious');
    }
    if (currentChapter === 'chapter_8' && state.step_id === 'schedule_opened' && targetName === 'schedule-continue') {
      this._handleActionButton('open_profile', {}, currentChapter);
      return;
    }
    if (currentChapter === 'chapter_9' && state.step_id === 'profile_opened' && targetName === 'profile-continue') {
      this._handleActionButton('goto_finale', {}, currentChapter);
      return;
    }
    if (chapterMap && chapterMap[targetName]) {
      var detail = chapterMap[targetName];
      if (!this.engine.completeAction(detail[0], { target: targetName })) return;
      this.engine.goToStep(detail[1], currentChapter);
      // These scenes cut to a full chapter card.  A second novel line here
      // would recreate the exact overlapping-layer bug the demo is avoiding.
      if (currentChapter === 'chapter_4' || currentChapter === 'chapter_5') return;
      if (currentChapter === 'chapter_6') {
        this.showNovelDialogue(detail[2], 'Бу · твой проводник', { buttons: [{ label: 'Вернуться в кабинет', action: 'return_dashboard_and_wins' }] });
        return;
      }
      if (currentChapter === 'chapter_7') {
        this.showNovelDialogue(detail[2], 'Бу · твой проводник', { buttons: [{ label: 'Открыть расписание', action: 'open_schedule' }] });
        return;
      }
      if (currentChapter === 'chapter_8') {
        this.showNovelDialogue(detail[2], 'Бу · твой проводник', { buttons: [{ label: 'Посмотреть профиль', action: 'open_profile' }] });
        return;
      }
      if (currentChapter === 'chapter_9') {
        this.showNovelDialogue(detail[2], 'Бу · твой проводник', { buttons: [{ label: 'К финалу', action: 'goto_finale' }] });
        return;
      }
      this.say(detail[2], 'happy');
    }
  };

  BooCompanion.prototype._recordDetour = function (link) {
    var state = this.engine.getState();
    if (!state.chapter_id || state.chapter_id === 'chapter_1' || state.chapter_id === 'chapter_10') return;
    var path = link.pathname || '';
    if (!path || path === window.location.pathname) return;
    this.engine.completeAction('demo:branch:detour:' + path.replace(/[^a-z0-9]+/gi, '_').slice(0, 48), {
      from: window.location.pathname,
      to: path,
      chapter: state.chapter_id
    });
  };

  BooCompanion.prototype._updateStoryGuide = function (chapterId, stepId) {
    // The demo has one dialogue surface: the visual-novel scene.  Keeping a
    // second fixed prompt in the lower corner made two instructions compete
    // for attention, especially on small screens.
    if (this.storyGuide) this.storyGuide.hidden = true;
  };

  BooCompanion.prototype._startTrialModeGuide = function (mode) {
    if (mode === 'code') {
      this._prepareCodeTrial();
      this.showNovelDialogue('Ты выбрал режим «Код». Это отдельная мини-задача: напиши цикл, который сложит числа не меньше 3 из списка. Я покажу редактор, затем ты запустишь программу и увидишь результат.', 'Бу · твой проводник', { buttons: [{ label: 'Показать редактор', action: 'focus_code_editor' }] });
      return;
    }
    this.showNovelDialogue('Ты выбрал режим «Ответ». Проследи исходный алгоритм вручную по пяти командам: начинаем с score = 0, после каждой команды запиши новое значение. В конце введи итог.', 'Бу · твой проводник', { buttons: [{ label: 'Показать поле ответа', action: 'focus_answer_input' }] });
  };

  BooCompanion.prototype._prepareCodeTrial = function () {
    var content = document.querySelector('#tw-task-panel .tw-task-content');
    var editor = document.getElementById('tw-code');
    if (!content || !editor || content.dataset.demoCodeTask === 'ready') return;
    content.dataset.demoCodeTask = 'ready';
    content.dataset.demoOriginalHtml = content.innerHTML;
    content.innerHTML = '<p><strong>Мини-задача для режима «Код».</strong> Дан список <code>marks = [3, 1, 4, 1, 5]</code>. Напиши цикл, который сложит только числа не меньше <code>3</code>, и выведи результат.</p><p>Ожидаемый результат после запуска — <strong>12</strong>. Сначала допиши цикл, затем нажми «Запустить».</p>';
    editor.value = 'marks = [3, 1, 4, 1, 5]\ntotal = 0\n\n# перебери marks и добавь в total числа >= 3\n\nprint(total)';
    editor.dispatchEvent(new Event('input', { bubbles: true }));
  };

  BooCompanion.prototype._focusTrialControls = function (mode) {
    if (mode !== 'code') {
      var answerMode = document.querySelector('[data-workspace-mode="answer"]');
      if (answerMode && !answerMode.classList.contains('is-active')) answerMode.click();
    }
    var isVisibleEditable = function (element) {
      if (!element || element.disabled || element.readOnly || element.type === 'hidden' || element.hidden) return false;
      if (element.closest('.is-workspace-hidden')) return false;
      var styles = window.getComputedStyle(element);
      var rect = element.getBoundingClientRect();
      return styles.display !== 'none' && styles.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    var answerInput = Array.prototype.find.call(document.querySelectorAll(
      '[data-demo-target="task-input"], #tw-answer, input[name="answer"], textarea.tw-long-answer'
    ), isVisibleEditable);
    var answerSubmit = Array.prototype.find.call(document.querySelectorAll(
      '[data-demo-target="task-submit"], #tw-submit-work'
    ), function (element) {
      if (!element || element.disabled || element.hidden) return false;
      var rect = element.getBoundingClientRect();
      return window.getComputedStyle(element).display !== 'none' && rect.width > 0 && rect.height > 0;
    });
    var targets = mode === 'code'
      ? [document.getElementById('tw-code'), document.getElementById('tw-run')]
      : [answerInput, answerSubmit];
    this._activateGuidedObjective(targets.filter(Boolean), mode === 'code' ? 'Напиши код и запусти' : 'Введи ответ и отправь');
    var primary = targets[0];
    if (primary) {
      primary.focus && primary.focus({ preventScroll: true });
      primary.scrollIntoView({ behavior: document.documentElement.classList.contains('demo-no-motion') ? 'auto' : 'smooth', block: 'center' });
      var companion = this;
      window.setTimeout(function () { companion._setFocusHole(primary); }, 260);
    }
  };

  BooCompanion.prototype.handleWrongTrialAnswer = function (result) {
    var state = result && result.state || this.engine.getState();
    var attempts = Number((state.flags || {}).trial_attempts || 1);
    if (attempts >= 2) {
      var solution = document.querySelector('.tw-solution-accordion');
      if (solution) { solution.open = true; solution.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
      this.showNovelDialogue('Не сошлось — бывает. Вот решение по шагам: 0 → 2 → 4 → 5 → 4 → 5. После каждой команды меняй только текущее значение. Теперь покажу отдельную работу над ошибками: наставник поможет исправить ход, а не поставит крест на попытке.', 'Бу · разбор решения', { buttons: [{ label: 'Перейти к работе над ошибками', action: 'start_mistakes' }] });
      return;
    }
    this.showNovelDialogue('Почти. Ошибка — обычная часть обучения. ' + ((result && result.hint) || 'На шаге DOWN вычти 1 из текущего значения и продолжай.'), 'Бу · твой проводник', { buttons: [{ label: 'Попробовать ещё раз', action: 'retry_trial' }] });
  };

  BooCompanion.prototype._focusNextObjective = function () {
    var state = this.engine.getState();
    // Product-page scenes use the same close button as every other novel
    // line. Closing it must never strand the learner without the next cue.
    if (state.chapter_id === 'chapter_2' && state.step_id === 'chapter2_mission') {
      if (this._isChapter2ProgramList()) return this._focusGuidedPageTarget('[data-demo-program-course]', 'Открой свой курс');
      if (this._isChapter2ProgramCourse()) {
        if (this.engine.hasActionCompleted('demo:chapter2:module_opened')) {
          var returnButton = document.querySelector('[data-demo-target="program-return"]');
          if (returnButton) returnButton.hidden = false;
          return this._focusGuidedPageTarget('[data-demo-target="program-return"]', 'Вернись в кабинет');
        }
        return this._focusGuidedPageTarget('[data-demo-target="program-module"]', 'Открой модуль курса');
      }
      if ((window.location.pathname || '').indexOf('/lesson/') === 0) return this._focusGuidedPageTarget('[data-demo-target="lesson-room-tour"]', 'Посмотри маршрут урока');
    }
    if (state.chapter_id === 'chapter_6' && state.step_id === 'route_intro') {
      var routePath = window.location.pathname || '';
      if (routePath === (state.program_url || '').split('?')[0]) return this._focusGuidedPageTarget('[data-demo-program-course]', 'Открой свой курс');
      if (/^\/courses\/\d+(?:\/student\/\d+)?\/?$/.test(routePath)) return this._focusGuidedPageTarget('[data-demo-target="program-module"]', 'Открой модуль маршрута');
    }
    // Route and analytics use explicit dialogue CTAs.  Closing a line must
    // never silently skip a whole chapter.
    if (state.step_id === 'mistakes_opened') {
      this._focusTrialControls('answer');
      return;
    }
    if (state.step_id === 'chapter2_mission') {
      if ((window.location.pathname || '') !== '/dashboard') return;
      var branches = [
        ['demo:dashboard:program_explored', '[data-demo-target="learning-program"]', 'Сначала откроем программу обучения.'],
        ['demo:dashboard:lesson_explored', '[data-demo-target="past-lesson"]', 'Теперь заглянем в комнату уже прошедшего урока.'],
        ['demo:dashboard:assignments_explored', '[data-demo-target="recent-assignments"]', 'А теперь откроем карточку работ.']
      ];
      var branch = branches.filter(function (item) { return !this.engine.hasActionCompleted(item[0]); }, this)[0];
      if (branch) { this._focusGuidedPageTarget(branch[1], branch[2]); return; }
    }
    if (state.step_id === 'trial_input') {
      this._focusTrialControls(this.engine.getFlag('trial_mode', 'answer'));
      return;
    }
    if (state.step_id === 'schedule_opened') {
      var scheduleContinue = document.querySelector('[data-demo-target="schedule-continue"]');
      if (scheduleContinue) scheduleContinue.hidden = false;
      return this._focusGuidedPageTarget('[data-demo-target="schedule-continue"]', 'Продолжи к профилю');
    }
    if (state.step_id === 'profile_opened') {
      var profileContinue = document.querySelector('[data-demo-target="profile-continue"]');
      if (profileContinue) profileContinue.hidden = false;
      return this._focusGuidedPageTarget('[data-demo-target="profile-continue"]', 'Перейди к финалу');
    }
    var targetByStep = {
      chapter2_mission: '[data-demo-target="learning-program"]',
      chapter2_discovery: '[data-demo-target="recent-assignments"]',
      trial_intro: '[data-demo-target="task-card"]',
      trial_input: '[data-demo-target="task-input"]',
      library_intro: '[data-demo-target="theory-material"]',
      mistakes_intro: 'a[href*="/submissions/"]',
      route_intro: '[data-demo-target="route-module"], main',
      wins_intro: '[data-demo-target="analytics-progress"]'
    };
    if (state.step_id === 'trial_retry') return this._focusTrialControls(this.engine.getFlag('trial_mode', 'answer'));
    var target = document.querySelector(targetByStep[state.step_id]);
    if (target) this._focusGuidedPageTarget(targetByStep[state.step_id], 'Следующий шаг');
    else this.say('Этот шаг откроется из текущей сцены — воспользуйся основной кнопкой в истории.', 'curious');
  };

  BooCompanion.prototype._updateMissionProgress = function () {
    var events = [
      'demo:dashboard:lesson_explored',
      'demo:dashboard:assignments_explored',
      'demo:dashboard:program_explored'
    ];
    var done = events.filter(this.engine.hasActionCompleted.bind(this.engine)).length;
    var mission = document.getElementById('boo-chapter2-mission-count');
    if (mission) mission.textContent = done + '/3';
    if (done === 3 && this.engine.getState().step_id === 'chapter2_mission') {
      this.engine.goToStep('chapter2_discovery', 'chapter_2');
      this.engine.completeAction('demo:chapter2:trial_discovered');
    }
  };

  BooCompanion.prototype.showRouteGuard = function () {
    var guard = document.getElementById('boo-route-guard');
    if (!guard) return;
    var state = this.engine.getState();
    guard.hidden = true;
    this.showNovelDialogue('Сюда пока не нужно. Сейчас глава ' + (state.chapter_id || '').replace('chapter_', '') + ' ведёт нас к следующему важному действию. Я подсвечу его после закрытия.', 'Бу ведёт сценарий', { warning: true });
  };
  BooCompanion.prototype.hideRouteGuard = function () { var guard = document.getElementById('boo-route-guard'); if (guard) guard.hidden = true; this.closeNovelDialogue(); };

  BooCompanion.prototype._onHelpClicked = function () {
    var state = this.engine.getState();
    if (state.chapter_id === 'chapter_1') {
      this.say('Введи своё имя и выбери цель подготовки, чтобы мы перешли в демонстрационный кабинет!', 'curious');
    } else if (state.chapter_id === 'chapter_2') {
      this.say('Здесь собраны твои уроки и работы. Ты можешь изучить карточки или нажать «К первому заданию», чтобы перейти к тесту.', 'happy', {
        buttons: [{ label: 'К первому заданию', action: 'goto_trial' }]
      });
    } else if (state.chapter_id === 'chapter_3') {
      this.say('Проследи за пятью командами по одной: начни со score = 0, затем применяй +2 для UP, +1 для RIGHT и −1 для DOWN. Так ты найдёшь ответ сам.', 'thinking');
    }
  };

  BooCompanion.prototype._onAvatarClicked = function () {
    var state = this.engine.getState();
    if (state.step_id === 'ready_for_trial') {
      this.say('Я готов перенести тебя в Task Workspace к первому заданию!', 'celebrating', {
        buttons: [{ label: 'Перейти к испытанию', action: 'goto_trial' }]
      });
    } else {
      this.say('Я рядом! Если возникнут вопросы — кликай по кнопке с вопросом или по заданиям на экране.', 'happy');
    }
  };

  BooCompanion.prototype.showCinema = function (chapterId, stepId) {
    if (!this.cinemaEl) return;
    // A chapter card owns the entire stage.  It is never shown under a
    // dialogue: the line returns only after the learner enters the next page.
    this._hideNovelImmediately();
    var scenes = {
      chapter_2: {
        chapter2_discovery: { kicker: 'Глава 2 · Твоя учебная база', title: 'Ты нашёл своё первое испытание.', message: 'Уроки, задания и маршрут уже на своих местах. Теперь можно перейти в рабочую область и попробовать решить настоящую задачу — в своём темпе.', note: 'Первое испытание готово', action: 'goto_trial', label: 'Открыть первое испытание', points: ['Учебная база открыта', 'Маршрут найден', 'Рабочая область ждёт'] }
      },
      chapter_3: {
        trial_intro: { kicker: 'Глава 3 · Первое испытание', title: 'Твоё первое испытание уже ждёт.', message: 'Проследи за коротким алгоритмом и найди число, которое он напечатает. Его можно решить руками, а затем выбрать короткий ответ или код.', note: 'Задача · След по алгоритму', action: 'goto_trial', label: 'Открыть первое испытание', points: ['Решается руками', 'Два режима решения', 'Подсказка рядом'] },
        trial_retry: { kicker: 'Глава 3 · Точка роста', title: 'Первый ответ — это только начало.', message: 'Проверим конкретный шаг и попробуем снова. Если вторая попытка тоже не сойдётся, я тут же покажу решение — здесь можно ошибаться без тупика.', note: 'Ошибка сохранена без штрафа', action: 'retry_trial', label: 'Вернуться к ответу', secondaryAction: 'view_solution', secondaryLabel: 'Показать решение', points: ['Подсказка про один шаг', 'Повтор без штрафа', 'Решение можно открыть'] },
        victory: { kicker: 'Глава 3 · Первое испытание', title: 'Первое испытание пройдено!', message: 'Ты проследил алгоритм и проверил своё решение. Теперь на отдельной странице Бу покажет, как устроена поддержка, если ответ сначала не сходится.', note: 'Заслуженная первая победа', action: 'view_solution', label: 'Посмотреть решение', points: ['Ответ проверен', 'Ошибка не тупик', 'Разбор ведёт к росту'] }
      },
      chapter_4: {
        library_intro: { kicker: 'Глава 4 · Секретная библиотека', title: 'За ответом всегда есть принцип.', message: 'Бу открыл для тебя объяснение к первому испытанию. Здесь теория помогает читать алгоритм по шагам, а не угадывать результат.', note: 'Открой разбор алгоритма', action: 'goto_theory', label: 'Открыть теорию', points: ['Разбор решения', 'Трассировка шагов', 'Мини-вопрос для закрепления'] },
        library_opened: { kicker: 'Глава 4 · Секретная библиотека', title: 'Теперь ты понимаешь, почему ответ работает.', message: 'Ты не просто увидел число — ты разобрал принцип. Следующий шаг покажет, как BooStudy помогает спокойно исправлять ошибки.', note: 'Принцип найден', action: 'start_mistakes', label: 'К работе над ошибками', points: ['Теория открыта', 'Проверка пройдена', 'Следующая история готова'] }
      },
      chapter_5: {
        mistakes_intro: { kicker: 'Глава 5 · Ошибаться — нормально', title: 'Ошибка — это точка, с которой начинается рост.', message: 'Сейчас откроется повторная попытка с подсказкой. Впиши новый ответ — это единственное действие этого кадра.', note: 'Повторная попытка готова', action: 'goto_assignments', label: 'Открыть повторную попытку', points: ['Подсказка рядом', 'Один ответ', 'Без штрафа'] },
        mistakes_opened: { kicker: 'Глава 5 · Ошибаться — нормально', title: 'Ты увидел, как ошибка становится навыком.', message: 'Комментарий уже рядом с работой. Исправь ответ, а затем Бу покажет твой персональный маршрут — без давления и с понятными шагами.', note: 'Попробовать ещё раз', action: 'goto_mistake_retry', label: 'Исправить ответ', points: ['Разбор открыт', 'Повторная попытка доступна', 'Навык можно закрепить'] }
      },
      chapter_6: {
        route_intro: { kicker: 'Глава 6 · Твой маршрут', title: 'Учёба становится понятнее, когда виден путь.', message: 'Это не общий список тем. Бу собрал живую индивидуальную траекторию: что уже получилось, на чём сфокусироваться сейчас и что будет дальше.', note: 'Открой свой путь', action: 'goto_program', label: 'Посмотреть маршрут', points: ['Пройдено', 'В фокусе', 'Следующий шаг'] },
        route_opened: { kicker: 'Глава 6 · Твой маршрут', title: 'У каждого шага теперь есть своё место.', message: 'Ты открыл модуль и увидел, что движение вперёд не обязано быть хаотичным. Осталось посмотреть, как это складывается в твои маленькие победы.', note: 'Маршрут открыт', action: 'start_wins', label: 'Посмотреть победы', points: ['Модуль открыт', 'Статусы понятны', 'Цель ближе'] }
      },
      chapter_7: {
        wins_intro: { kicker: 'Глава 7 · Маленькие победы', title: 'Твои усилия можно увидеть.', message: 'В аналитике задания, уроки и попытки складываются в историю прогресса. Здесь нет абстрактных цифр — только понятная картина твоего движения.', note: 'Посмотри на прогресс', action: 'goto_analytics', label: 'Открыть аналитику', points: ['Решённые задания', 'Динамика результатов', 'Ближайшая цель'] },
        wins_opened: { kicker: 'Глава 7 · Маленькие победы', title: 'Рост виден в цифрах.', message: 'За полгода в этом примере результат вырос с 48% до 74% благодаря регулярным урокам и практике. Теперь посмотрим, как такой ритм помещается в неделю.', note: 'Рост без гонки', action: 'open_schedule', label: 'Посмотреть расписание', points: ['36 проведённых уроков', '160 решённых задач', '7 освоенных тем'] }
      },
      chapter_8: {
        schedule_intro: { kicker: 'Твой ритм · Расписание', title: 'Регулярность — это посильный план.', message: 'Здесь пример живой учебной недели: два вечерних занятия и короткая самостоятельная практика. Настоящее расписание в демо не меняется.', note: 'Неделя без перегруза', action: 'open_schedule', label: 'Открыть расписание', points: ['Два занятия в неделю', 'Практика между ними', 'Ближайшее — вечером'] }
      },
      chapter_9: {
        profile_intro: { kicker: 'Твой профиль · Достижения', title: 'Посмотри, сколько уже получилось.', message: 'Уровень, серия занятий и достижения отмечают путь, а не сравнивают тебя с другими. Заглянем в профиль — потом вернёмся к финальному выбору.', note: 'Прогресс принадлежит тебе', action: 'open_profile', label: 'Открыть профиль', points: ['Личный уровень', 'Серия занятий', 'Три достижения'] }
      }
    };
    var scene = scenes[chapterId] && scenes[chapterId][stepId];
    if (!scene) return;
    var sceneKey = chapterId + ':' + stepId + ':' + window.location.pathname;
    if (!this.cinemaEl.hidden && this._visibleSceneKey === sceneKey) return;
    var state = this.engine.getState();
    if (chapterId === 'chapter_3' && stepId === 'trial_retry' && Number((state.flags || {}).trial_attempts || 1) < 2) {
      scene = Object.assign({}, scene, { secondaryAction: null, secondaryLabel: null });
    }
    var currentPath = window.location.pathname || '';
    var pathFor = function (url) { return (url || '').split('?')[0]; };
    var isProgramDestination = currentPath === pathFor(state.program_url) || /^\/courses\/\d+(?:\/student\/\d+)?\/?$/.test(currentPath);
    // When Chapter 3 is already open in the workspace, the cinematic scene
    // must continue *inside* that place rather than navigate to it again.
    if (chapterId === 'chapter_3' && stepId === 'trial_intro' && currentPath.indexOf('/task-workspace') === 0) {
      scene = Object.assign({}, scene, { action: 'choose_trial_mode', label: 'Выбрать способ решения' });
    }
    // Intro scenes belong to the transition *from* a page. On the destination
    // we deliberately reveal the actual product surface for the next action.
    var isDestination = (stepId === 'library_intro' && currentPath === pathFor(state.theory_url)) ||
      (stepId === 'mistakes_intro' && currentPath === '/submissions') ||
      (stepId === 'mistakes_opened' && currentPath.indexOf('/task-workspace') === 0) ||
      ((stepId === 'route_intro' || stepId === 'route_opened') && isProgramDestination) ||
      ((stepId === 'wins_intro' || stepId === 'wins_opened') && currentPath === pathFor(state.analytics_url)) ||
      (stepId === 'schedule_intro' && currentPath.indexOf('/schedule') === 0) ||
      (stepId === 'profile_intro' && currentPath.indexOf('/workspace/profile') === 0);
    this.rootEl.classList.add('boo-no-chat');
    if (isDestination) {
      this.hideCinema();
      // Loading a page is not an interaction.  Auto-completing here used to
      // skip the route and analytics scenes before the learner saw them.
      return;
    }
    document.getElementById('boo-cinema-progress').textContent = 'Демо · ' + (scene.kicker.split('·').pop() || 'следующая сцена').trim();
    document.getElementById('boo-cinema-kicker').textContent = scene.kicker;
    document.getElementById('boo-cinema-title').textContent = scene.title;
    document.getElementById('boo-cinema-message').textContent = scene.message;
    document.getElementById('boo-cinema-note').textContent = scene.note;
    var cinematicMascots = {
      chapter_2: '/static/images/demo/boo-onboarding-hero-v2.png',
      chapter_3: '/static/images/lesson/lesson_task_mascot.png',
      chapter_4: '/static/images/demo/boo-library-v3.png',
      chapter_5: '/static/images/profile/hero_ghost.png',
      chapter_6: '/static/images/demo/boo-route-v3.png',
      chapter_7: '/static/images/theory/ghost_rocket.png'
    };
    this.cinemaEl.dataset.chapter = chapterId;
    document.getElementById('boo-cinema-mascot').src = cinematicMascots[chapterId] || MASCOT_ASSETS.happy;
    var points = document.getElementById('boo-cinema-points');
    points.replaceChildren();
    (scene.points || []).forEach(function (point) {
      var item = document.createElement('span');
      item.textContent = '✓ ' + point;
      points.appendChild(item);
    });
    var cinemaActions = document.getElementById('boo-cinema-actions');
    cinemaActions.replaceChildren();
    var primary = document.createElement('button');
    primary.type = 'button';
    primary.dataset.cinemaAction = scene.action;
    primary.textContent = scene.label + ' →';
    cinemaActions.appendChild(primary);
    if (scene.secondaryAction) {
      var secondary = document.createElement('button');
      secondary.type = 'button';
      secondary.className = 'is-secondary';
      secondary.dataset.cinemaAction = scene.secondaryAction;
      secondary.textContent = scene.secondaryLabel;
      cinemaActions.appendChild(secondary);
    }
    this.cinemaEl.hidden = false;
    this._visibleSceneKey = sceneKey;
    this._animateScene(this.cinemaEl);
    this.rootEl.classList.add('boo-cinema-active');
    this.cinemaEl.querySelector('[data-cinema-action]').focus();
  };

  BooCompanion.prototype.hideCinema = function () {
    if (this.cinemaEl) this.cinemaEl.hidden = true;
    this._visibleSceneKey = null;
    this.rootEl.classList.remove('boo-cinema-active');
  };

  BooCompanion.prototype._animateScene = function (element) {
    if (!element || document.documentElement.classList.contains('demo-no-motion') || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    element.classList.remove('boo-scene-enter');
    // Force a new compositor animation without changing layout or focus.
    void element.offsetWidth;
    element.classList.add('boo-scene-enter');
  };

  BooCompanion.prototype.renderStep = function (chapterId, stepId) {
    var self = this;
    if (this._navigating) return;
    if (!this.scenario || !this.scenario.chapters[chapterId]) return;
    var chapter = this.scenario.chapters[chapterId];
    var step = chapter.steps[stepId];
    if (!step) return;

    this._updateStoryGuide(chapterId, stepId);

    var state = this.engine.getState();
    var studentName = state.student_name || 'Демо-ученик';
    var cinematicChapter = (chapterId === 'chapter_2' && stepId === 'chapter2_discovery') || (chapterId === 'chapter_3' && (stepId === 'trial_intro' || stepId === 'victory')) || ['chapter_4', 'chapter_5', 'chapter_6', 'chapter_7'].indexOf(chapterId) !== -1;
    if (cinematicChapter) this.showCinema(chapterId, stepId);
    else if (this.cinemaEl && !this.cinemaEl.hidden) this.hideCinema();

    // 1. Обновление плашки HUD
    this._updateHUD(chapterId, stepId);
    if (this.missionEl) {
      // Progress belongs to the narrated scene, not to a persistent dashboard
      // badge that competes with the current action.
      this.missionEl.hidden = true;
      this._updateMissionProgress();
    }

    // 2. Установка тега говорящего
    if (this.characterTagEl) {
      this.characterTagEl.textContent = step.characterTag || 'Бу';
    }

    // 3. Установка эмоции
    this.setEmotion(step.emotion || 'happy');

    // 4. Форматирование реплики
    var rawMsg = step.templateMessage ? step.templateMessage.replace('{name}', studentName) : (step.message || step.fallbackMessage || '');
    var stepKey = chapterId + ':' + stepId + ':' + rawMsg;
    if (this._lastSpokenKey !== stepKey) {
      this._lastSpokenKey = stepKey;
      this.typeMessage(rawMsg);
    }

    // 5. Отрисовка вариантов выбора
    this.choicesContainer.innerHTML = '';
    if (step.choices && step.choices.length > 0) {
      step.choices.forEach(function (choice) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'boo-chip-btn';
        chip.textContent = choice.label;
        chip.addEventListener('click', function () {
          if (choice.flag) self.engine.setFlag(choice.flag, true);
          self.engine.completeAction('choice_' + choice.id, { choice: choice.id });
          if (choice.nextStep) {
            self.engine.goToStep(choice.nextStep, chapterId);
          }
        });
        self.choicesContainer.appendChild(chip);
      });
    }

    // 6. Отрисовка основных кнопок действия
    this.actionsContainer.innerHTML = '';
    if (step.buttons && step.buttons.length > 0) {
      step.buttons.forEach(function (btn) {
        var actBtn = document.createElement('button');
        actBtn.type = 'button';
        actBtn.className = btn.secondary ? 'boo-secondary-btn' : 'boo-primary-btn';
        actBtn.textContent = btn.label;
        actBtn.addEventListener('click', function () {
          self._handleActionButton(btn.action, step, chapterId);
        });
        self.actionsContainer.appendChild(actBtn);
      });
    }

    // 7. A visual-novel line owns the screen until the learner dismisses it.
    // In particular, chapter 2 must not reveal the next card before Bu has
    // finished introducing the current scene.
    var deferFocus = (chapterId === 'chapter_2' && stepId === 'chapter2_mission') || (this.novelEl && !this.novelEl.hidden);
    if (deferFocus) {
      this._highlightTarget(null);
      if (this.focusHoleEl) this.focusHoleEl.hidden = true;
    } else this._highlightTarget(step.target);

    // Разворачиваем карточку, если была свернута
    if (this.isMinimized) {
      this.toggleMinimize();
    }
  };

  BooCompanion.prototype._updateHUD = function (chapterId, stepId) {
    if (!this.hudTextEl) return;
    var chMap = {
      chapter_1: { num: '', title: 'Знакомство' },
      chapter_2: { num: '', title: 'Учебная база' },
      chapter_3: { num: '', title: 'Первое испытание' },
      chapter_4: { num: '', title: 'Теория' },
      chapter_5: { num: '', title: 'Работа над ошибками' },
      chapter_6: { num: '', title: 'Учебный маршрут' },
      chapter_7: { num: '', title: 'Аналитика' },
      chapter_8: { num: '', title: 'Расписание' },
      chapter_9: { num: '', title: 'Профиль' },
      chapter_10: { num: '', title: 'Финал' },
    };
    var info = chMap[chapterId] || { num: '1/3', title: 'Демоверсия', activeDot: 1 };
    this.hudTextEl.textContent = 'Демо · пример через полгода · ' + info.title;

    var dot1 = document.getElementById('boo-dot-1');
    var dot2 = document.getElementById('boo-dot-2');
    var dot3 = document.getElementById('boo-dot-3');

    if (dot1 && dot2 && dot3) {
      dot1.className = 'boo-hud-dot' + (info.activeDot === 1 ? ' is-active' : (info.activeDot > 1 ? ' is-done' : ''));
      dot2.className = 'boo-hud-dot' + (info.activeDot === 2 ? ' is-active' : (info.activeDot > 2 ? ' is-done' : ''));
      dot3.className = 'boo-hud-dot' + (info.activeDot === 3 ? ' is-active' : (info.activeDot > 3 ? ' is-done' : ''));
    }
  };

  BooCompanion.prototype._handleActionButton = function (action, step, chapterId) {
    var self = this;
    if (action === 'next') {
      if (step.nextStep) {
        this.engine.goToStep(step.nextStep, chapterId);
      }
    } else if (action === 'goto_dashboard') {
      // The Chapter 1 CTA is the only user-facing entry to a new dashboard
      // tour.  Ask the server to create that clean session before navigating;
      // do not optimistically reuse any previous Chapter 2 checkpoint.
      if ((window.location.pathname || '') === '/demo') {
        this._startFreshDashboardTour();
      } else this.navigate('/dashboard');
    } else if (action === 'focus_cards') {
      this.engine.goToStep('explore_cards', 'chapter_2');
      var card = document.querySelector('[data-demo-target="recent-assignments"]') || document.querySelector('[data-demo-target="upcoming-lesson"]');
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    } else if (action === 'start_chapter2_mission') {
      this.engine.completeAction('demo:chapter2:started');
      this.engine.goToStep('chapter2_mission', 'chapter_2');
      this.say('Пойдём по порядку: сначала откроем программу обучения. После неё Бу вернёт тебя в кабинет к уроку и работам.', 'curious');
    } else if (action === 'dismiss_trial') {
      this.engine.goToStep('ready_for_trial', 'chapter_2');
      this.say('Хорошо, осматривайся дальше. Первое испытание будет ждать в карточке текущих работ.', 'happy');
    } else if (action === 'goto_trial') {
      var state = this.engine.getState();
      var subId = state.submission_id;
      this.engine.goToStep('trial_intro', 'chapter_3');
      this.hideCinema();
      if (subId && state.assignment_task_id) {
        this.navigate('/task-workspace/?context_type=submission_task&context_id=' + encodeURIComponent(subId) + '&assignment_task_id=' + encodeURIComponent(state.assignment_task_id));
      } else {
        this.navigate('/assignments');
      }
    } else if (action === 'choose_trial_mode') {
      this.hideCinema();
      this.showWorkspaceStory();
    } else if (action === 'retry_trial') {
      this.engine.completeAction('demo:branch:retry_trial');
      this.engine.goToStep('trial_input', 'chapter_3', { allowRewind: true });
      this.hideCinema();
      var retryInput = document.querySelector('[data-demo-target="task-input"]') || document.querySelector('#tw-answer');
      var retrySubmit = document.querySelector('[data-demo-target="task-submit"]') || document.querySelector('#tw-submit-work');
      if (retryInput) retryInput.disabled = false;
      if (retrySubmit) {
        retrySubmit.disabled = false;
        retrySubmit.innerHTML = '<i class="ph-bold ph-paper-plane-tilt"></i> Отправить ответ';
      }
      this._handleActionButton('focus_input', {}, 'chapter_3');
    } else if (action === 'branch_to_library') {
      this.engine.completeAction('demo:branch:theory_first');
      this.engine.setFlag('learning_path', 'theory_first');
      this.engine.goToStep('library_intro', 'chapter_4');
    } else if (action === 'focus_input') {
      this.engine.goToStep('trial_input', 'chapter_3');
      var input = document.querySelector('[data-demo-target="task-input"]') || document.querySelector('#tw-answer') || document.querySelector('input[name="answer"]');
      if (input) {
        input.focus();
        input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    } else if (action === 'focus_answer_input') {
      this._focusTrialControls('answer');
    } else if (action === 'focus_code_editor') {
      this._prepareCodeTrial();
      this._focusTrialControls('code');
    } else if (action === 'focus_program_course') {
      this._focusGuidedPageTarget('[data-demo-program-course]', 'Открой свой курс');
    } else if (action === 'focus_program_modules') {
      this._focusGuidedPageTarget('[data-demo-target="program-module"]', 'Открой модуль курса');
    } else if (action === 'focus_route_module') {
      this._focusGuidedPageTarget('[data-demo-target="program-module"]', 'Открой модуль маршрута');
    } else if (action === 'focus_route_course') {
      this._focusGuidedPageTarget('[data-demo-program-course]', 'Открой свой курс');
    } else if (action === 'focus_theory_material') {
      this._focusGuidedPageTarget('[data-demo-target="theory-material"]', 'Открой разбор');
    } else if (action === 'focus_mistake_review') {
      this._focusGuidedPageTarget('[data-demo-target="mistake-review"]', 'Открой разбор ошибки');
    } else if (action === 'focus_analytics_progress') {
      this._focusGuidedPageTarget('[data-demo-target="analytics-progress"]', 'Посмотри прогресс');
    } else if (action === 'focus_demo_schedule') {
      this._focusGuidedPageTarget('[data-demo-target="schedule-week"]', 'Посмотри план недели');
    } else if (action === 'focus_demo_achievements') {
      var achievementsAction = document.querySelector('[data-demo-target="profile-achievements-action"]');
      if (achievementsAction) achievementsAction.hidden = false;
      this._focusGuidedPageTarget('[data-demo-target="profile-achievements-action"]', 'Открой витрину достижений');
    } else if (action === 'open_schedule') {
      this.hideCinema();
      this.engine.goToStep('schedule_intro', 'chapter_8');
      this.navigate(this.engine.getState().schedule_url || '/schedule?timezone=Europe%2FMoscow');
    } else if (action === 'open_profile') {
      this.hideCinema();
      var profileState = this.engine.getState();
      if (profileState.step_id === 'schedule_opened') this.engine.goToStep('profile_intro', 'chapter_9');
      this.navigate(profileState.profile_url || '/workspace/profile');
    } else if (action === 'return_dashboard') {
      this.navigate('/dashboard');
    } else if (action === 'return_dashboard_and_wins') {
      this.engine.goToStep('wins_intro', 'chapter_7');
      this.navigate('/dashboard');
    } else if (action === 'show_hint') {
      this.say('Сделай короткую трассировку: 0 → 2 → 4 → 5 → 4 → 5. Это не хитрость, а обычный способ читать программу руками.', 'thinking');
    } else if (action === 'view_solution') {
      this.hideCinema();
      var solAcc = document.querySelector('.tw-solution-accordion');
      if (solAcc) {
        solAcc.open = true;
        solAcc.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      var solutionBridge = this.engine.getFlag('trial_passed', false)
        ? 'Ты справился с заданием. А теперь важный вопрос: что делать, если в другой задаче ты ошибёшься? Для этого как раз есть работа над ошибками — она помогает спокойно найти сбой и попробовать ещё раз.'
        : 'Смотри на ход по строкам: было 0, после UP стало 2, после второго UP — 4, после RIGHT — 5, после DOWN — 4, после последнего RIGHT — 5. Ошибка — не тупик: теперь покажу отдельную работу над ошибками и исправленную попытку.';
      this.showNovelDialogue(solutionBridge, 'Бу · разбор решения', { buttons: [{ label: 'Перейти к работе над ошибками', action: 'start_mistakes' }] });
    } else if (action === 'goto_plans') {
      this.navigate('/billing/plans/public');
    } else if (action === 'goto_theory') {
      var theoryUrl = this.engine.getState().theory_url;
      this.hideCinema();
      this.navigate(theoryUrl || '/theory');
    } else if (action === 'start_library') {
      this.engine.goToStep('library_intro', 'chapter_4');
    } else if (action === 'start_mistakes') {
      this.hideCinema();
      this.engine.goToStep('mistakes_intro', 'chapter_5');
      this.navigate('/submissions');
    } else if (action === 'goto_assignments') {
      this.hideCinema();
      // The error-work scene starts with the reviewed card, not with the
      // retry editor.  Otherwise the visitor never sees the mentor comment
      // and the deliberately highlighted "wrong step" from this chapter.
      this.engine.goToStep('mistakes_intro', 'chapter_5');
      this.navigate('/submissions');
    } else if (action === 'goto_mistake_retry') {
      var retryId = this.engine.getState().mistake_submission_id;
      var retryTaskId = this.engine.getState().mistake_assignment_task_id;
      if (retryId && retryTaskId) {
        this.hideCinema();
        this.navigate('/task-workspace/?context_type=submission_task&context_id=' + encodeURIComponent(retryId) + '&assignment_task_id=' + encodeURIComponent(retryTaskId));
      }
      else this.say('Сначала открой разбор ошибки — я подготовлю повторную попытку.', 'thinking');
    } else if (action === 'goto_program') {
      var programLink = document.querySelector('[data-demo-target="learning-program"]');
      var programUrl = this.engine.getState().program_url;
      this.hideCinema();
      this.navigate(programUrl || (programLink && programLink.href ? programLink.href : '/courses'));
    } else if (action === 'start_route') {
      this.engine.goToStep('route_intro', 'chapter_6');
    } else if (action === 'goto_analytics') {
      var analyticsLink = document.querySelector('[data-demo-analytics-url]');
      var analyticsUrl = this.engine.getState().analytics_url;
      this.hideCinema();
      this.navigate(analyticsUrl || (analyticsLink && analyticsLink.dataset.demoAnalyticsUrl
        ? analyticsLink.dataset.demoAnalyticsUrl
        : '/dashboard'));
    } else if (action === 'goto_finale') {
      this.hideCinema();
      this.engine.goToStep('finale', 'chapter_10');
      this.showFinale();
    } else if (action === 'start_wins') {
      this.engine.goToStep('wins_intro', 'chapter_7');
      this.navigate(this.engine.getState().analytics_url || '/dashboard');
    } else if (action === 'restart') {
      this.engine.reset().then(function () {
        self.navigate('/demo');
      });
    }
  };

  BooCompanion.prototype._startFreshDashboardTour = function () {
    var self = this;
    var state = this.engine.getState();
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
    if (csrf && csrf.content) headers['X-CSRFToken'] = csrf.content;
    this._navigating = true;
    fetch('/demo/api/init', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({
        student_name: state.student_name || 'Демо-ученик',
        exam: state.exam || 'ege',
        goal: state.goal || 'ege',
        grade: state.grade || '11',
        start_at_dashboard: true
      })
    }).then(function (response) {
      if (!response.ok) throw new Error('dashboard tour init rejected');
      return response.json();
    }).then(function (data) {
      if (!data.success || !data.state) throw new Error('dashboard tour init failed');
      self.engine.applyServerState(data.state);
      self.navigate(data.dashboard_url || '/dashboard');
    }).catch(function () {
      self._navigating = false;
      self.say('Не удалось открыть учебную базу. Попробуй ещё раз.', 'gentle_warning');
    });
  };

  BooCompanion.prototype.setEmotion = function (emotion) {
    if (!this.avatarBtn) return;
    var emo = emotion || 'happy';
    this.avatarBtn.className = 'boo-avatar-button emotion-' + emo;

    var mascotImg = document.getElementById('boo-mascot-img');
    if (mascotImg) {
      var assetUrl = MASCOT_ASSETS[emo] || MASCOT_ASSETS.happy;
      if (mascotImg.getAttribute('src') !== assetUrl) {
        mascotImg.src = assetUrl;
      }
    }
  };

  BooCompanion.prototype.typeMessage = function (text) {
    var self = this;
    if (!this.messageBox) return;

    if (this._typingTimer) {
      clearInterval(this._typingTimer);
      this._typingTimer = null;
    }

    if (document.documentElement.classList.contains('demo-no-motion') || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      this.messageBox.replaceChildren();
      var immediate = document.createElement('p');
      immediate.textContent = text;
      this.messageBox.appendChild(immediate);
      return;
    }

    this.messageBox.innerHTML = '';
    var p = document.createElement('p');
    this.messageBox.appendChild(p);

    var idx = 0;
    var len = text.length;
    this.isTyping = true;

    var onSkip = function () {
      if (self._typingTimer) {
        clearInterval(self._typingTimer);
        self._typingTimer = null;
      }
      p.textContent = text;
      self.isTyping = false;
      self.messageBox.removeEventListener('click', onSkip);
    };
    this.messageBox.addEventListener('click', onSkip);

    this._typingTimer = setInterval(function () {
      if (idx < len) {
        p.textContent += text.charAt(idx);
        idx++;
      } else {
        clearInterval(self._typingTimer);
        self._typingTimer = null;
        self.isTyping = false;
        self.messageBox.removeEventListener('click', onSkip);
      }
    }, 16);
  };

  BooCompanion.prototype.say = function (text, emotion, options) {
    var self = this;
    options = options || {};
    this.setEmotion(emotion || 'happy');
    this.typeMessage(text);
    this.showNovelDialogue(text, (this.characterTagEl && this.characterTagEl.textContent) || 'Бу', options);
    // Cinematic and product guidance use the single story-guide surface.
    // A second fixed toast used to cover it and caused contradictory prompts.

    if (options.buttons && options.buttons.length > 0) {
      this.actionsContainer.innerHTML = '';
      options.buttons.forEach(function (btn) {
        var actBtn = document.createElement('button');
        actBtn.type = 'button';
        actBtn.className = btn.secondary ? 'boo-secondary-btn' : 'boo-primary-btn';
        actBtn.textContent = btn.label;
        actBtn.addEventListener('click', function () {
          self._handleActionButton(btn.action, {}, self.engine.getState().chapter_id);
        });
        self.actionsContainer.appendChild(actBtn);
      });
    }

    if (this.isMinimized) {
      this.toggleMinimize();
    }
  };

  BooCompanion.prototype.showNovelDialogue = function (text, name, options) {
    var self = this;
    if (!this.novelEl) return;
    options = options || {};
    this._clearGuidedObjective();
    this.novelEl.hidden = false;
    this.novelEl.classList.remove('is-settled');
    if (this.focusVeilEl) this.focusVeilEl.hidden = true;
    if (this.focusHoleEl) this.focusHoleEl.hidden = true;
    this.novelEl.classList.toggle('is-warning', !!options.warning);
    document.getElementById('boo-novel-name').textContent = name || 'Бу';
    this.novelActionsEl.innerHTML = '';
    var choices = options.buttons || [];
    // A line with an explicit action has one exit. Leaving the generic
    // "Continue" beside it allowed a learner to close a terminal line without
    // taking its route and re-open the very same scene in a loop.
    this._novelContinuationAction = choices.length === 1 ? choices[0].action : null;
    var closeButton = document.getElementById('boo-novel-close');
    if (closeButton) {
      closeButton.hidden = choices.length > 0;
      closeButton.setAttribute('aria-hidden', choices.length > 0 ? 'true' : 'false');
    }
    choices.forEach(function (btn) {
      var action = document.createElement('button');
      action.type = 'button'; action.className = 'boo-novel-choice'; action.textContent = btn.label;
      // Some browsers defer a synthetic click while the dialogue is animating.
      // Run the choice on pointer release as well, with one shared guard, so a
      // real click and an Enter key both reach the next deterministic scene.
      var fired = false;
      var activateChoice = function (event) {
        if (fired) return;
        fired = true;
        if (event) { event.preventDefault(); event.stopPropagation(); }
        self.closeNovelDialogue();
        self._handleActionButton(btn.action, {}, self.engine.getState().chapter_id);
      };
      action.addEventListener('pointerup', activateChoice);
      action.addEventListener('click', activateChoice);
      self.novelActionsEl.appendChild(action);
    });
    var target = this.novelTextEl;
    if (this._novelTypingTimer) clearInterval(this._novelTypingTimer);
    target.textContent = '';
    target.setAttribute('tabindex', '0');
    target.onclick = function () { self._revealNovelText(); };
    if (document.documentElement.classList.contains('demo-no-motion') || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { target.textContent = text; this.isTyping = false; return; }
    var i = 0;
    this.isTyping = true;
    this._novelFullText = text;
    this._novelTypingTimer = setInterval(function () { target.textContent += text.charAt(i++); if (i >= text.length) { clearInterval(self._novelTypingTimer); self._novelTypingTimer = null; self.isTyping = false; } }, 18);
  };

  BooCompanion.prototype._revealNovelText = function () {
    if (!this.isTyping) return;
    if (this._novelTypingTimer) clearInterval(this._novelTypingTimer);
    this._novelTypingTimer = null;
    this.isTyping = false;
    if (this.novelTextEl) this.novelTextEl.textContent = this._novelFullText || this.novelTextEl.textContent;
  };

  BooCompanion.prototype.closeNovelDialogue = function () {
    if (!this.novelEl) return;
    if (this._novelTypingTimer) { clearInterval(this._novelTypingTimer); this._novelTypingTimer = null; }
    this.novelEl.classList.add('is-settled');
    if (this.focusVeilEl) this.focusVeilEl.hidden = true;
    window.setTimeout(function () {
      var dialogue = document.getElementById('boo-novel-dialogue');
      if (dialogue && dialogue.classList.contains('is-settled')) dialogue.hidden = true;
    }, document.documentElement.classList.contains('demo-no-motion') ? 0 : 260);
  };

  BooCompanion.prototype._continueNovelDialogue = function () {
    var action = this._novelContinuationAction;
    this._novelContinuationAction = null;
    this.closeNovelDialogue();
    if (action) {
      this._handleActionButton(action, {}, this.engine.getState().chapter_id);
      return;
    }
    this._focusNextObjective();
  };

  BooCompanion.prototype._hideNovelImmediately = function () {
    if (this._novelTypingTimer) {
      clearInterval(this._novelTypingTimer);
      this._novelTypingTimer = null;
    }
    if (!this.novelEl) return;
    this.novelEl.classList.remove('is-settled');
    this.novelEl.hidden = true;
    if (this.focusVeilEl) this.focusVeilEl.hidden = true;
    if (this.focusHoleEl) this.focusHoleEl.hidden = true;
  };

  BooCompanion.prototype.showDashboardMissionIntro = function () {
    if (!this.novelEl || !this.novelEl.hidden) return;
    this.showNovelDialogue('Сейчас ты увидишь пример кабинета после полугода регулярных занятий. Это демонстрационный маршрут по информатике: сначала программа, затем уже прошедший урок, задание, работа над ошибками, аналитика, расписание и профиль. Я буду возвращать тебя на точную следующую сцену.', 'Бу · твой проводник');
  };

  BooCompanion.prototype.showProductSceneDialogue = function () {
    if (!this.novelEl || !this.novelEl.hidden || (this.cinemaEl && !this.cinemaEl.hidden)) return;
    var state = this.engine.getState();
    var path = window.location.pathname || '';
    var pathFor = function (url) { return (url || '').split('?')[0]; };
    var onProgram = !!state.program_url && path === pathFor(state.program_url);
    var onProgramCourse = /^\/courses\/\d+(?:\/student\/\d+)?\/?$/.test(path);
    var onTheory = !!state.theory_url && path === pathFor(state.theory_url);
    var onAnalytics = !!state.analytics_url && path === pathFor(state.analytics_url);

    if (state.chapter_id === 'chapter_4' && state.step_id === 'library_intro' && onTheory) {
      this.showNovelDialogue('Это разбор решения. Не нужно угадывать: открой материал, и я покажу, как читать алгоритм по шагам.', 'Бу · твой проводник', { buttons: [{ label: 'Показать разбор', action: 'focus_theory_material' }] });
      return;
    }
    if (state.chapter_id === 'chapter_5' && state.step_id === 'mistakes_intro' && path === '/submissions') {
      this.showNovelDialogue('Это отдельная работа над ошибками: сначала посмотрим комментарий наставника и неверный шаг, а затем откроем исправленную попытку.', 'Бу · твой проводник', { buttons: [{ label: 'Показать разбор ошибки', action: 'focus_mistake_review' }] });
      return;
    }
    if (state.chapter_id === 'chapter_5' && state.step_id === 'mistakes_opened' && path.indexOf('/task-workspace') === 0) {
      if (state.flags && state.flags.mistakes_fixed) {
        this.showNovelDialogue('Готово — ты исправил именно тот шаг, где сбился счёт. Ошибка стала навыком. Теперь посмотрим, как регулярная практика отражается на прогрессе.', 'Бу · твой проводник', { buttons: [{ label: 'Посмотреть аналитику', action: 'start_wins' }] });
        return;
      }
      this.showNovelDialogue('Это работа над ошибками. Сначала нажми «Показать поле ответа», затем введи правильный результат — 5 — и нажми «Отправить ответ». Я подсвечу оба шага.', 'Бу · твой проводник', { buttons: [{ label: 'Показать поле ответа', action: 'focus_answer_input' }] });
      return;
    }
    if (state.chapter_id === 'chapter_6' && state.step_id === 'route_intro' && onProgram) {
      this._lockGuidedBackLinks();
      this.showNovelDialogue('Это каталог твоих программ. Откроем единственный активный курс, а уже внутри я покажу один модуль маршрута.', 'Бу · твой проводник', { buttons: [{ label: 'Открыть курс', action: 'focus_route_course' }] });
      return;
    }
    if (state.chapter_id === 'chapter_6' && state.step_id === 'route_intro' && onProgramCourse) {
      this._lockGuidedBackLinks();
      this._lockGuidedCourseLessonLinks();
      this.showNovelDialogue('Это твой маршрут. Я покажу один модуль — так видно, как темы и занятия складываются в понятную последовательность. В сами занятия сейчас не уходим.', 'Бу · твой проводник', { buttons: [{ label: 'Показать модуль', action: 'focus_route_module' }] });
      return;
    }
    if (state.chapter_id === 'chapter_7' && state.step_id === 'wins_intro' && onAnalytics) {
      this.showNovelDialogue('Это не задание и здесь ничего не нужно «решать». Посмотри на одну карточку прогресса: она собирает маленькие шаги в понятный результат.', 'Бу · твой проводник', { buttons: [{ label: 'Показать прогресс', action: 'focus_analytics_progress' }] });
      return;
    }
    if (state.chapter_id === 'chapter_8' && state.step_id === 'schedule_intro' && path.indexOf('/schedule') === 0) {
      this.showNovelDialogue('Вот пример недели относительно текущей даты: два занятия вечером, самостоятельная практика между ними и ближайший урок через пару дней около 18:00. Настоящее расписание не меняется.', 'Бу · твой проводник', { buttons: [{ label: 'Показать неделю', action: 'focus_demo_schedule' }] });
      return;
    }
    if (state.chapter_id === 'chapter_8' && state.step_id === 'schedule_opened' && path.indexOf('/schedule') === 0) {
      this.showNovelDialogue('Ты увидел пример недели и безопасный учебный ритм. Следом заглянем в профиль ученика.', 'Бу · твой проводник', { buttons: [{ label: 'Посмотреть профиль', action: 'open_profile' }] });
      return;
    }
    if (state.chapter_id === 'chapter_9' && state.step_id === 'profile_intro' && path.indexOf('/workspace/profile') === 0) {
      this.showNovelDialogue('Вот пример профиля после полугода занятий: личный уровень, серия и достижения. Это демонстрационные данные — они не меняют профиль.', 'Бу · твой проводник', { buttons: [{ label: 'Показать достижения', action: 'focus_demo_achievements' }] });
      return;
    }
    if (state.chapter_id === 'chapter_9' && state.step_id === 'profile_opened' && path.indexOf('/workspace/profile') === 0) {
      this.showNovelDialogue('Ты увидел профиль и достижения — теперь можно перейти к финалу и выбрать удобный первый шаг.', 'Бу · твой проводник', { buttons: [{ label: 'К финалу', action: 'goto_finale' }] });
    }
  };

  BooCompanion.prototype._isChapter2ProgramList = function () {
    var state = this.engine.getState();
    var path = window.location.pathname || '';
    return state.chapter_id === 'chapter_2' && !!state.program_url && path === state.program_url.split('?')[0];
  };

  BooCompanion.prototype._isChapter2ProgramCourse = function () {
    var state = this.engine.getState();
    return state.chapter_id === 'chapter_2' && /^\/courses\/\d+(?:\/student\/\d+)?\/?$/.test(window.location.pathname || '');
  };

  BooCompanion.prototype._clearGuidedObjective = function () {
    this._guidedObjective = null;
    document.documentElement.classList.remove('boo-objective-lock');
    document.querySelectorAll('.boo-target-pulse').forEach(function (element) {
      element.classList.remove('boo-target-pulse');
      element.removeAttribute('data-boo-next-label');
    });
    if (this.focusVeilEl) this.focusVeilEl.hidden = true;
    if (this.focusHoleEl) this.focusHoleEl.hidden = true;
    if (this._focusUpdateHandler) {
      window.removeEventListener('scroll', this._focusUpdateHandler, true);
      window.removeEventListener('resize', this._focusUpdateHandler);
      this._focusUpdateHandler = null;
    }
    this._focusTarget = null;
  };

  BooCompanion.prototype._activateGuidedObjective = function (elements, label) {
    var targets = (elements || []).filter(Boolean);
    if (!targets.length) return false;
    this._clearGuidedObjective();
    var selectors = targets.map(function (element) {
      if (element.id) return '#' + (window.CSS && CSS.escape ? CSS.escape(element.id) : element.id);
      var targetName = element.getAttribute && element.getAttribute('data-demo-target');
      return targetName ? '[data-demo-target="' + targetName + '"]' : null;
    }).filter(Boolean);
    if (!selectors.length) return false;
    this._guidedObjective = { selectors: selectors, label: label || 'Сделай следующий шаг' };
    targets.forEach(function (element, index) {
      element.classList.add('boo-target-pulse');
      if (index === 0 && label) element.setAttribute('data-boo-next-label', label);
    });
    var primary = targets[0];
    this._focusTarget = primary;
    primary.scrollIntoView({ behavior: 'auto', block: 'center' });
    var self = this;
    // The focal frame belongs to the viewport, not to the product element.
    // Keep the page scrollable after centering. The learner may need to read
    // the task context and teacher feedback before acting on the highlighted
    // control; the frame follows scroll/resize below.
    window.requestAnimationFrame(function () {
      self._setFocusHole(primary);
      self._focusUpdateHandler = function () {
        if (self._focusTarget && !self._focusTarget.hidden) self._setFocusHole(self._focusTarget);
      };
      window.addEventListener('scroll', self._focusUpdateHandler, true);
      window.addEventListener('resize', self._focusUpdateHandler);
      window.setTimeout(self._focusUpdateHandler, 80);
      window.setTimeout(self._focusUpdateHandler, 260);
    });
    primary.focus && primary.focus({ preventScroll: true });
    return true;
  };

  BooCompanion.prototype._showGuidedDetour = function () {
    var self = this;
    if (this._guidedBlockTimer || (this.novelEl && !this.novelEl.hidden)) return;
    this._guidedBlockTimer = window.setTimeout(function () { self._guidedBlockTimer = null; }, 300);
    var objective = this._guidedObjective;
    this.showNovelDialogue('Сюда вернёмся чуть позже. Сейчас нужен один небольшой шаг — «' + ((objective && objective.label) || 'следующий шаг') + '». После реплики я снова подсвечу его.', 'Бу · твой проводник', { warning: true });
  };

  BooCompanion.prototype._focusGuidedPageTarget = function (selector, label) {
    if (selector === '[data-demo-target="analytics-progress"]') {
      // The canonical demo owns the analytics screen as one guided scene.
      // Remove the optional product drill-down layer so it cannot cover the
      // highlighted progress surface or steal the next gesture.
      ['readiness-backdrop', 'readiness-drawer'].forEach(function (id) {
        var layer = document.getElementById(id);
        if (layer) layer.remove();
      });
    }
    if (selector === '[data-demo-target="program-module"]' && typeof window.toggleAllModules === 'function') {
      window.toggleAllModules(false);
    }
    var target = document.querySelector(selector);
    if (!target) {
      this.showNovelDialogue('Этот элемент пока не загрузился. Обнови страницу — я верну тебя к нужному месту.', 'Бу · твой проводник');
      return;
    }
    this._activateGuidedObjective([target], label);
  };

  BooCompanion.prototype._lockGuidedBackLinks = function () {
    document.querySelectorAll('[data-demo-program-return]').forEach(function (link) {
      link.classList.add('boo-guided-locked');
      link.setAttribute('aria-disabled', 'true');
      link.setAttribute('tabindex', '-1');
      link.setAttribute('title', 'Сначала завершим осмотр программы вместе с Бу');
    });
  };

  BooCompanion.prototype._lockGuidedCourseLessonLinks = function () {
    document.querySelectorAll('[data-demo-program-lesson-link]').forEach(function (link) {
      link.classList.add('boo-guided-locked');
      link.setAttribute('aria-disabled', 'true');
      link.setAttribute('tabindex', '-1');
      link.setAttribute('title', 'Сейчас знакомимся с маршрутом — к занятиям вернёмся по сценарию');
    });
  };

  BooCompanion.prototype.showChapter2PageDialogue = function () {
    if (!this.novelEl || !this.novelEl.hidden) return;
    var state = this.engine.getState();
    var path = window.location.pathname || '';
    if (path === '/dashboard' || path === '/main/dashboard' || path === '/student/dashboard') {
      var next = this._nextDashboardTarget();
      var copy = {
        'learning-program': 'Сначала откроем программу обучения. Там ты увидишь не обещание, а настоящий маршрут с модулями и темами.',
        'past-lesson': 'Программа уже открыта. Теперь посмотрим комнату уже прошедшего урока — это настоящее рабочее пространство, не экран ожидания.',
        'upcoming-lesson': 'Программа уже открыта. Возвращаемся к базе: теперь покажу тебе, как выглядит комната ближайшего урока.',
        'recent-assignments': 'Урок посмотрели. Остался раздел работ — там тебя ждёт первое испытание.'
      };
      this.showNovelDialogue(copy[next] || 'Учебная база собрана. Теперь можно перейти к первому испытанию.', 'Бу · твой проводник');
      return;
    }
    if (this._isChapter2ProgramList()) {
      this._lockGuidedBackLinks();
      this.showNovelDialogue('Это твоя программа обучения. В ней лежит не абстрактная схема, а твой реальный курс. Откроем его и посмотрим, как устроены модули и занятия.', 'Бу · твой проводник', { buttons: [{ label: 'Открыть мой курс', action: 'focus_program_course' }] });
      return;
    }
    if (this._isChapter2ProgramCourse()) {
      this._lockGuidedBackLinks();
      this._lockGuidedCourseLessonLinks();
      if (this.engine.hasActionCompleted('demo:chapter2:module_opened')) {
        var backButton = document.querySelector('[data-demo-target="program-return"]');
        if (backButton) backButton.hidden = false;
        this.showNovelDialogue('Мы посмотрели модуль и увидели, как темы складываются в курс. Возвращаемся в кабинет — там следующий кадр: комната уже прошедшего урок.', 'Бу · твой проводник', { buttons: [{ label: 'Вернуться в кабинет', action: 'return_dashboard' }] });
        return;
      }
      this.showNovelDialogue('Это уже сам курс: сверху видна цель, а ниже — модули. Я покажу один из них: в нём занятия собраны в последовательность по теме.', 'Бу · твой проводник', { buttons: [{ label: 'Показать модуль', action: 'focus_program_modules' }] });
      return;
    }
    // Query parameters (for example `demo_preview=1`) and a trailing slash
    // are presentation details, not a different scene.  Treat every lesson
    // room as the same guided stop; otherwise a valid room can fall through
    // to the generic "unknown page" redirect a moment after it opens.
    if (path.indexOf('/lesson/') === 0 && /\/room\/?$/.test(path)) {
      this.showNovelDialogue('Это комната уже прошедшего урока. Здесь собраны маршрут занятия, материалы и задания — заглянем внутрь, а затем Бу вернёт тебя в кабинет.', 'Бу · твой проводник');
      return;
    }
    // Chapter 2 has only three valid destinations: dashboard, programme list,
    // and the selected course. Never label an unrelated product page as a
    // lesson room; restore the learner to the current story frame instead.
    this.navigate('/dashboard');
  };

  BooCompanion.prototype._nextDashboardTarget = function () {
    var order = [
      ['demo:dashboard:program_explored', 'learning-program'],
      ['demo:dashboard:lesson_explored', 'past-lesson'],
      ['demo:dashboard:assignments_explored', 'recent-assignments']
    ];
    var next = order.filter(function (item) { return !this.engine.hasActionCompleted(item[0]); }, this)[0];
    return next ? next[1] : null;
  };

  BooCompanion.prototype._setFocusHole = function (target) {
    var hole = this.focusHoleEl || document.getElementById('boo-focus-hole');
    if (!hole || !target) return;
    // Product pages may replace the highlighted card while async content
    // settles. Resolve the current highlighted node instead of measuring a
    // detached/stale element captured before that render.
    if (this._guidedObjective && this._guidedObjective.selectors) {
      target = document.querySelector(this._guidedObjective.selectors.map(function (selector) {
        return selector + '.boo-target-pulse';
      }).join(', ')) || target;
    }
    var rect = target.getBoundingClientRect();
    // Fit the marker to the control itself.  A wide rectangular gap made the
    // focus indicator look like a duplicated button around the product CTA.
    var pad = 3;
    var style = window.getComputedStyle(target);
    var radius = Math.max(
      parseFloat(style.borderTopLeftRadius) || 0,
      parseFloat(style.borderTopRightRadius) || 0,
      parseFloat(style.borderBottomRightRadius) || 0,
      parseFloat(style.borderBottomLeftRadius) || 0
    );
    // Keep the frame congruent with the target even when a responsive card
    // touches the viewport edge. Clamping the frame independently creates a
    // visibly displaced cut-out and breaks keyboard-guided navigation.
    hole.style.left = (rect.left - pad) + 'px';
    hole.style.top = (rect.top - pad) + 'px';
    hole.style.width = (rect.width + pad * 2) + 'px';
    hole.style.height = (rect.height + pad * 2) + 'px';
    hole.style.borderRadius = Math.max(8, radius + pad) + 'px';
    hole.hidden = false;
  };

  BooCompanion.prototype._highlightTarget = function (targetName) {
    document.querySelectorAll('.demo-focus-target').forEach(function (el) {
      el.classList.remove('demo-focus-target');
    });
    document.querySelectorAll('.boo-target-pulse').forEach(function (el) {
      el.classList.remove('boo-target-pulse');
    });

    if (!targetName) return;

    var el = document.querySelector('[data-demo-target="' + targetName + '"]');
    if (el) {
      el.classList.add('demo-focus-target');
      el.classList.add('boo-target-pulse');
    }
  };

  BooCompanion.prototype.toggleMinimize = function () {
    this.isMinimized = !this.isMinimized;
    if (this.cardEl) {
      this.cardEl.classList.toggle('boo-hidden', this.isMinimized);
    }
    var minBtn = document.getElementById('boo-minimize-btn');
    if (minBtn) {
      minBtn.innerHTML = this.isMinimized ? '<i class="ph-bold ph-caret-up"></i>' : '<i class="ph-bold ph-caret-down"></i>';
    }
  };

  BooCompanion.prototype.showOutOfBoundsWarning = function () {
    var oob = (this.scenario && this.scenario.outOfBounds) ? this.scenario.outOfBounds.blockedArea : null;
    var msg = oob ? oob.message : 'Этот раздел станет доступен после регистрации. Давай вернёмся в учебный кабинет!';
    this.say(msg, 'gentle_warning', {
      buttons: [{ label: 'Вернуться в кабинет', action: 'goto_dashboard' }]
    });
  };

  global.BooCompanion = new BooCompanion();

})(typeof window !== 'undefined' ? window : this);
