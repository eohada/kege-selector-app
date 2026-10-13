/**
 * BooStudy Demo Engine
 * Declarative state machine, event bus, and synchronization for interactive demo experience.
 */
(function (global) {
  'use strict';

  var STORAGE_KEY = 'boostudy_demo_state_v1';

  function csrfHeaders(extra) {
    var headers = Object.assign({
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
    }, extra || {});
    var token = document.querySelector('meta[name="csrf-token"]');
    if (token && token.content) headers['X-CSRFToken'] = token.content;
    return headers;
  }
  // Keep browser restoration aligned with the server-side demo state.  A
  // version bump intentionally discards stale cinematic routes from older UI.
  var SCENARIO_VERSION = 5;

  var STEP_RANKS = {
    'welcome': 0,
    'name_input': 1,
    'goal_selection': 2,
    'finish_ch1': 3,
    'dashboard_intro': 4,
    'chapter2_mission': 5,
    'chapter2_discovery': 6,
    'ready_for_trial': 7,
    'trial_intro': 8,
    'trial_input': 9,
    'trial_retry': 10,
    'victory': 11,
    'library_intro': 12,
    'library_opened': 13,
    'mistakes_intro': 14,
    'mistakes_opened': 15,
    'route_intro': 16,
    'route_opened': 17,
    'wins_intro': 18,
    'wins_opened': 19,
    'schedule_intro': 20,
    'schedule_opened': 21,
    'profile_intro': 22,
    'profile_opened': 23,
    'finale': 24
  };

  var CHAPTER_RANKS = {
    'chapter_1': 1,
    'chapter_2': 2,
    'chapter_3': 3,
    'chapter_4': 4,
    'chapter_5': 5,
    'chapter_6': 6,
    'chapter_7': 7,
    'chapter_8': 8,
    'chapter_9': 9,
    'chapter_10': 10
  };

  function DemoEngine() {
    this._listeners = {};
    this._state = {
      version: SCENARIO_VERSION,
      chapter_id: 'chapter_1',
      step_id: 'welcome',
      student_name: 'Демо-ученик',
      exam: 'ege',
      goal: 'ege',
      grade: '11',
      completed_actions: [],
      flags: {},
      history: [],
      demo_session_id: null,
      director_revision: 0,
      submission_id: null,
      assignment_id: null,
      assignment_task_id: null,
      task_id: null,
      mistake_submission_id: null,
      mistake_assignment_task_id: null,
    };
    this._isInitialized = false;
    this._syncQueue = Promise.resolve();
  }

  DemoEngine.prototype.init = function (serverConfig) {
    if (this._isInitialized) {
      if (serverConfig && typeof serverConfig === 'object') {
        this._mergeState(serverConfig, true);
      }
      return this;
    }

    // 1. Попытка загрузить локальное состояние
    var localData = null;
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (raw) localData = JSON.parse(raw);
    } catch (e) {
      console.warn('[DemoEngine] Error reading localStorage:', e);
    }

    if (localData && localData.version === SCENARIO_VERSION) {
      this._mergeState(localData, false);
    }

    if (serverConfig && typeof serverConfig === 'object') {
      // Серверное состояние имеет приоритет над старым локальным
      this._mergeState(serverConfig, true);
    }

    // 2. Автоматическое распознавание страницы
    this._autoDetectPageContext();

    this._saveLocal();
    this._isInitialized = true;
    this.emit('initialized', this.getState());
    return this;
  };

  DemoEngine.prototype._mergeState = function (source, isServer) {
    if (!source || typeof source !== 'object') return;

    var currentRank = STEP_RANKS[this._state.step_id] !== undefined ? STEP_RANKS[this._state.step_id] : 0;
    var sourceStep = source.step_id;
    var sourceRank = sourceStep && STEP_RANKS[sourceStep] !== undefined ? STEP_RANKS[sourceStep] : -1;

    // The server is authoritative when a new demo session starts or when the
    // presenter deliberately rewinds the story.  The former rank-only merge
    // made an old localStorage checkpoint silently override Director mode.
    var isNewSession = isServer && source.demo_session_id && source.demo_session_id !== this._state.demo_session_id;
    var isDirectorJump = isServer && Number(source.director_revision || 0) > Number(this._state.director_revision || 0);
    var replaceProgress = isNewSession || isDirectorJump;
    if (replaceProgress) {
      this._state.chapter_id = source.chapter_id || 'chapter_1';
      this._state.step_id = source.step_id || 'welcome';
      this._state.completed_actions = Array.isArray(source.completed_actions) ? source.completed_actions.slice() : [];
      this._state.flags = source.flags && typeof source.flags === 'object' ? Object.assign({}, source.flags) : {};
      this._state.history = Array.isArray(source.history) ? source.history.slice(-50) : [];
    }

    if (source.demo_session_id) this._state.demo_session_id = source.demo_session_id;
    if (source.director_revision !== undefined) this._state.director_revision = Number(source.director_revision) || 0;
    if (source.student_name) this._state.student_name = source.student_name;
    if (source.exam) this._state.exam = source.exam;
    if (source.goal) this._state.goal = source.goal;
    if (source.grade) this._state.grade = source.grade;
    if (source.submission_id) this._state.submission_id = source.submission_id;
    if (source.assignment_id) this._state.assignment_id = source.assignment_id;
    if (source.assignment_task_id) this._state.assignment_task_id = source.assignment_task_id;
    if (source.task_id) this._state.task_id = source.task_id;
    if (source.lesson_id) this._state.lesson_id = source.lesson_id;
    // URLs belong to the server-authoritative demo dataset. Keeping them on
    // rehydration lets later chapters open the specific real material instead
    // of falling back to a generic section after a page navigation.
    if (source.theory_url) this._state.theory_url = source.theory_url;
    if (source.program_url) this._state.program_url = source.program_url;
    if (source.analytics_url) this._state.analytics_url = source.analytics_url;
    if (source.schedule_url) this._state.schedule_url = source.schedule_url;
    if (source.profile_url) this._state.profile_url = source.profile_url;
    if (source.billing_url) this._state.billing_url = source.billing_url;
    if (source.mistake_submission_id) this._state.mistake_submission_id = source.mistake_submission_id;
    if (source.mistake_assignment_task_id) this._state.mistake_assignment_task_id = source.mistake_assignment_task_id;

    if (!replaceProgress && Array.isArray(source.completed_actions)) {
      for (var i = 0; i < source.completed_actions.length; i++) {
        var act = source.completed_actions[i];
        if (this._state.completed_actions.indexOf(act) === -1) {
          this._state.completed_actions.push(act);
        }
      }
    }

    if (!replaceProgress && source.flags && typeof source.flags === 'object') {
      this._state.flags = Object.assign({}, this._state.flags, source.flags);
    }

    if (isServer) {
      if (replaceProgress) return;
      if (sourceRank >= currentRank || (source.chapter_id && (CHAPTER_RANKS[source.chapter_id] || 1) > (CHAPTER_RANKS[this._state.chapter_id] || 1))) {
        if (source.chapter_id) this._state.chapter_id = source.chapter_id;
        if (sourceStep) this._state.step_id = sourceStep;
      }
    } else {
      if (sourceRank > currentRank) {
        if (source.chapter_id) this._state.chapter_id = source.chapter_id;
        if (sourceStep) this._state.step_id = sourceStep;
      }
    }
  };

  DemoEngine.prototype.applyServerState = function (serverState) {
    var before = this.getState();
    this._mergeState(serverState, true);
    this._saveLocal();
    if (before.chapter_id !== this._state.chapter_id || before.step_id !== this._state.step_id) {
      this.emit('step_changed', {
        prevStep: before.step_id,
        prevChapter: before.chapter_id,
        stepId: this._state.step_id,
        chapterId: this._state.chapter_id,
        state: this.getState(),
      });
    }
    return this.getState();
  };

  DemoEngine.prototype._autoDetectPageContext = function () {
    // URLs are presentation context, never story progress. Advancing because
    // a page happened to load caused browser refresh/back to skip scenes.
    return;
  };

  DemoEngine.prototype.emitSemanticEvent = function (eventName, payload) {
    if (!eventName) return;
    payload = payload || {};

    this.completeAction(eventName, payload);

    // Семантическое продвижение по условиям сценария
    if (this._state.chapter_id === 'chapter_2') {
      // Chapter 2 advances only after its three independent mission events.
      // This avoids a delayed navigation response skipping the exploration scene.
    }

    if (typeof window !== 'undefined' && window.dispatchEvent) {
      try {
        window.dispatchEvent(new CustomEvent(eventName, { detail: payload }));
      } catch (e) {}
    }

    this.emit(eventName, payload);
  };

  DemoEngine.prototype.getState = function () {
    return JSON.parse(JSON.stringify(this._state));
  };

  DemoEngine.prototype.hasActionCompleted = function (actionId) {
    if (!actionId) return false;
    return (this._state.completed_actions || []).indexOf(actionId) !== -1;
  };

  DemoEngine.prototype.completeAction = function (actionId, payload) {
    if (!actionId) return false;

    // Защита от повторного выполнения (идемпотентность)
    var isNew = !this.hasActionCompleted(actionId);
    if (isNew) {
      this._state.completed_actions.push(actionId);
    }

    // Добавляем запись в историю
    this._state.history.push({
      action_id: actionId,
      timestamp: new Date().toISOString(),
      payload: payload || {},
    });
    if (this._state.history.length > 50) {
      this._state.history.shift();
    }

    this._saveLocal();
    this._syncServerEvent(actionId, payload);

    this.emit('action_completed', {
      actionId: actionId,
      isNew: isNew,
      payload: payload || {},
      state: this.getState(),
    });

    return isNew;
  };

  DemoEngine.prototype.goToStep = function (stepId, chapterId, options) {
    if (!stepId) return;

    var prevStep = this._state.step_id;
    var prevChapter = this._state.chapter_id;

    var prevRank = STEP_RANKS[prevStep] !== undefined ? STEP_RANKS[prevStep] : 0;
    var newRank = STEP_RANKS[stepId] !== undefined ? STEP_RANKS[stepId] : prevRank;

    // Предотвращаем случайный откат назад внутри главы
    if (newRank < prevRank && (chapterId === prevChapter || !chapterId) && !(options && options.allowRewind)) {
      return;
    }

    this._state.step_id = stepId;
    if (chapterId) {
      this._state.chapter_id = chapterId;
    }

    this._saveLocal();
    this._syncServerEvent('transition_step', { step_id: stepId, chapter_id: this._state.chapter_id });

    this.emit('step_changed', {
      prevStep: prevStep,
      prevChapter: prevChapter,
      stepId: stepId,
      chapterId: this._state.chapter_id,
      state: this.getState(),
    });
  };

  DemoEngine.prototype.setFlag = function (flagName, value) {
    if (!flagName) return;
    if (!this._state.flags) this._state.flags = {};
    this._state.flags[flagName] = value;
    this._saveLocal();
    this.emit('flag_changed', { flag: flagName, value: value, state: this.getState() });
  };

  DemoEngine.prototype.getFlag = function (flagName, defaultValue) {
    if (!this._state.flags) return defaultValue;
    return this._state.flags[flagName] !== undefined ? this._state.flags[flagName] : defaultValue;
  };

  DemoEngine.prototype.on = function (event, callback) {
    if (!this._listeners[event]) {
      this._listeners[event] = [];
    }
    this._listeners[event].push(callback);
    return this;
  };

  DemoEngine.prototype.off = function (event, callback) {
    if (!this._listeners[event]) return this;
    this._listeners[event] = this._listeners[event].filter(function (fn) {
      return fn !== callback;
    });
    return this;
  };

  DemoEngine.prototype.emit = function (event, data) {
    var list = this._listeners[event];
    if (!list || !list.length) return;
    for (var i = 0; i < list.length; i++) {
      try {
        list[i](data);
      } catch (err) {
        console.error('[DemoEngine] Listener error on event ' + event + ':', err);
      }
    }
  };

  DemoEngine.prototype.reset = function () {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}

    return fetch('/demo/api/exit', {
      method: 'POST',
      headers: csrfHeaders(),
    }).then(function (r) {
      return r.json();
    });
  };

  DemoEngine.prototype._saveLocal = function () {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this._state));
    } catch (e) {
      console.warn('[DemoEngine] Failed to save state to localStorage:', e);
    }
  };

  DemoEngine.prototype._syncServerEvent = function (actionId, payload) {
    var self = this;
    var eventData = {
      action_id: actionId,
      payload: payload || {},
    };
    // Обычное событие проверяется относительно актуальной серверной сцены.
    // Локальный step к моменту отправки может уже устареть, поэтому передаём
    // его только для самой команды перехода.
    if (actionId === 'transition_step') {
      eventData.step_id = self._state.step_id;
      eventData.chapter_id = self._state.chapter_id;
    }
    // Preserve action order: a transition that requires an action must never
    // reach the authoritative server before that action's event.
    this._syncQueue = this._syncQueue.catch(function () {}).then(function () {
      return fetch('/demo/api/event', {
        method: 'POST',
        headers: csrfHeaders(),
        body: JSON.stringify(eventData),
      }).then(function (response) {
        if (!response.ok) throw new Error('Demo event rejected');
        return response.json();
      });
    }).catch(function (e) {
      // Offline or network error handled gracefully; localStorage preserves state.
      console.warn('[DemoEngine] Server event sync deferred:', e);
    });
    return this._syncQueue;
  };

  // Экспорт синглтона в глобальную область
  global.BooDemoEngine = new DemoEngine();

})(typeof window !== 'undefined' ? window : this);
