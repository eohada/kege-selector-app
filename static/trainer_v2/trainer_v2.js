(function () {
  'use strict';

  const cfg = window.__TRAINER_V2__ || {};
  const token = cfg.token;
  if (!token) return;

  const userId = Number(cfg.currentUserId || 0) || 0;
  const rootEl = document.getElementById('trainerV2Root');
  const dockEl = document.getElementById('trainerV2Dock');
  const taskMetaEl = document.getElementById('tv2TaskMeta');
  const taskTypeEl = document.getElementById('tv2TaskType');
  const startBtn = document.getElementById('tv2StartBtn');
  const nextBtn = document.getElementById('tv2NextBtn');
  const presetBtn = document.getElementById('tv2PresetBtn');
  const storageHelpBtn = document.getElementById('tv2StorageHelpBtn');
  const queueInfoEl = document.getElementById('tv2QueueInfo');
  const zenBtn = document.getElementById('tv2ZenBtn');
  const inlineToastArea = document.getElementById('tv2InlineToastArea');

  const LS = {
    theme: 'trainer.themeMode',
    layout: (name) => `tv2.layout.${userId}.${name}`,
    preset: `tv2.preset.${userId}`,
    lastTaskType: `tv2.lastTaskType.${userId}`,
    attempts: (taskId) => `tv2.attempts.${userId}.${taskId}`,
    visited: `tv2.visited.${userId}`,
    pending: `tv2.pending.${userId}`,
    code: (taskId) => `tv2.code.${userId}.${taskId}`,
    answer: (taskId) => `tv2.answer.${userId}.${taskId}`,
    highlights: (taskId) => `tv2.hl.${userId}.${taskId}`,
    scratchMd: (taskId) => `tv2.scratch.md.${userId}.${taskId}`,
    scratchCanvas: (taskId) => `tv2.scratch.canvas.${userId}.${taskId}`,
    versions: (taskId) => `tv2.versions.${userId}.${taskId}`,
    eventLog: `tv2.log.${userId}`,
    chat: (taskId) => `tv2.chat.${userId}.${taskId}`,
    canvasZoomPct: `tv2.canvasZoomPct.${userId}`,
    canvasScalePct: `tv2.canvasScalePct.${userId}`, // legacy key (older "масштаб" slider)
    streak: `tv2.streak.${userId}`
  };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }
  function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }
  function nowMs() { return Date.now(); }

  function safeJsonParse(s, fallback) {
    try { return JSON.parse(s); } catch (_) { return fallback; }
  }

  function lsGet(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v == null ? fallback : v;
    } catch (_) {
      return fallback;
    }
  }

  function lsSet(key, value) {
    try { localStorage.setItem(key, value); } catch (_) {}
  }

  function lsDel(key) {
    try { localStorage.removeItem(key); } catch (_) {}
  }

  function makeId(prefix) {
    const rnd = Math.random().toString(16).slice(2);
    return `${prefix}_${nowMs().toString(16)}_${rnd}`;
  }

  function fmtTime(ts) {
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (_) {
      return String(ts);
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function stripHtmlToText(html) {
    try {
      const div = document.createElement('div');
      div.innerHTML = String(html || '');
      return String(div.textContent || div.innerText || '').replace(/\r/g, '');
    } catch (_) {
      return String(html || '');
    }
  }

  function getTaskConditionText(task) {
    if (!task) return '';
    const direct = (task.content || task.content_text || task.text || '');
    if (direct && String(direct).trim()) return String(direct).trim();
    const html = (task.content_html || task.html || '');
    const txt = stripHtmlToText(html);
    return String(txt || '').trim();
  }

  async function apiFetch(path, opts) {
    const url = `${cfg.baseApi}${path}`;
    const headers = Object.assign({}, (opts && opts.headers) || {});
    headers['X-Trainer-Token'] = token;
    // чтобы глобальный оверлей "Загрузка…" не перекрывал UI тренажёра
    headers['X-No-Loading-Overlay'] = '1';
    if (!headers['Content-Type'] && opts && opts.body) headers['Content-Type'] = 'application/json';
    const res = await fetch(url, Object.assign({}, opts || {}, { headers }));
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      const msg = data && (data.error || data.message) ? String(data.error || data.message) : `http_${res.status}`;
      const err = new Error(msg);
      err.status = res.status;
      err.payload = data;
      throw err;
    }
    return data;
  }

  function pushInlineToast({ kind, title, message, actions }) {
    if (!inlineToastArea) return;
    const el = document.createElement('div');
    el.className = `tv2-inline-toast ${kind || ''}`.trim();
    const t = document.createElement('div');
    t.className = 'title';
    t.textContent = title || '';
    const m = document.createElement('div');
    m.className = 'msg';
    m.textContent = message || '';
    el.appendChild(t);
    el.appendChild(m);
    if (Array.isArray(actions) && actions.length > 0) {
      const row = document.createElement('div');
      row.style.marginTop = '0.65rem';
      row.style.display = 'flex';
      row.style.gap = '0.5rem';
      row.style.flexWrap = 'wrap';
      actions.forEach((a) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = `tv2-btn ${a.danger ? 'tv2-btn-danger' : ''}`.trim();
        b.textContent = a.label || 'ok';
        b.addEventListener('click', () => {
          try { a.onClick && a.onClick(); } finally { el.remove(); }
        });
        row.appendChild(b);
      });
      el.appendChild(row);
    }
    inlineToastArea.appendChild(el);
    setTimeout(() => { if (el.isConnected) el.remove(); }, 9000);
  }

  const State = {
    taskType: null,
    currentTask: null,
    taskLoadedAtMs: null,
    visitedIds: [],
    pending: [],
    eventLog: [],
    layoutName: 'standard',
    glossary: null,
    cm: null,
    md: null,
    scratchCanvas: null,
    scratchCanvasApi: null,
    historyView: null,
    testsView: null,
    terminalView: null,
    conditionView: null,
    editorView: null,
    assistantView: null,
    lastRun: null,
    llmInfo: null
  };

  function logEvent(kind, payload) {
    const entry = { ts: nowMs(), kind: String(kind || 'event'), payload: payload || null };
    State.eventLog.push(entry);
    if (State.eventLog.length > 200) State.eventLog.splice(0, State.eventLog.length - 200);
    lsSet(LS.eventLog, JSON.stringify(State.eventLog));
    if (State.terminalView && typeof State.terminalView.render === 'function') {
      State.terminalView.render();
    }
  }

  function initEventLog() {
    const prev = safeJsonParse(lsGet(LS.eventLog, '[]'), []);
    if (Array.isArray(prev)) State.eventLog = prev;
  }

  function updateQueueBadge() {
    if (!queueInfoEl) return;
    const cnt = State.pending.filter(p => p.status === 'sending').length;
    queueInfoEl.textContent = String(cnt);
    queueInfoEl.style.color = cnt > 0 ? 'var(--tv2-accent)' : 'var(--tv2-muted)';
  }

  function getStreak() {
    return Number(lsGet(LS.streak, '0')) || 0;
  }

  function setStreak(val) {
    lsSet(LS.streak, String(val));
    updateStreakUI();
  }

  function updateStreakUI() {
    const el = document.getElementById('tv2StreakInfo');
    if (!el) return;
    const v = getStreak();
    el.textContent = v;
    if (v > 0) {
      el.classList.add('is-active');
      if (v >= 3) el.classList.add('is-hot');
      else el.classList.remove('is-hot');
      el.classList.remove('bump');
      void el.offsetWidth;
      el.classList.add('bump');
    } else {
      el.classList.remove('is-active', 'is-hot', 'bump');
    }
  }

  function setTaskMeta(task) {
    if (!taskMetaEl) return;
    if (!task) {
      taskMetaEl.textContent = '—';
      return;
    }
    const tn = task.task_number ? `№${task.task_number}` : '—';
    const id = task.task_id ? `id ${task.task_id}` : '';
    taskMetaEl.textContent = `${tn} · ${id}`.trim();
  }

  function parseAttachedFiles(attached) {
    if (!attached) return [];
    if (Array.isArray(attached)) return attached;
    if (typeof attached === 'string') {
      const j = safeJsonParse(attached, null);
      if (Array.isArray(j)) return j;
      if (j && typeof j === 'object') return [j];
      return [];
    }
    if (typeof attached === 'object') return [attached];
    return [];
  }

  function getTrainerThemeMode() {
    const v = (lsGet(LS.theme, 'auto') || '').trim();
    if (v === 'dark' || v === 'light' || v === 'auto') return v;
    return 'auto';
  }

  function effectiveTheme(mode) {
    if (mode === 'dark' || mode === 'light') return mode;
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    return isLight ? 'light' : 'dark';
  }

  function applyTrainerTheme(mode) {
    if (!rootEl) return;
    const m = (mode === 'dark' || mode === 'light' || mode === 'auto') ? mode : 'auto';
    rootEl.setAttribute('data-tv2-theme', m);
    $all('.trainer-v2-theme-btn').forEach((b) => {
      const isActive = b.getAttribute('data-tv2-theme') === m;
      b.classList.toggle('is-active', isActive);
    });
    const eff = effectiveTheme(m);
    try {
      if (State.cm) State.cm.setOption('theme', eff === 'light' ? 'default' : 'dracula');
    } catch (_) {}
    try {
      if (State.md && State.md.codemirror) State.md.codemirror.setOption('theme', eff === 'light' ? 'default' : 'dracula');
    } catch (_) {}
    try {
      if (State.scratchCanvasApi && typeof State.scratchCanvasApi.redraw === 'function') State.scratchCanvasApi.redraw();
    } catch (_) {}
  }

  function initThemeToggle() {
    const m = getTrainerThemeMode();
    applyTrainerTheme(m);
    $all('.trainer-v2-theme-btn').forEach((b) => {
      b.addEventListener('click', () => {
        const mode = b.getAttribute('data-tv2-theme') || 'auto';
        lsSet(LS.theme, mode);
        applyTrainerTheme(mode);
        logEvent('theme_change', { mode });
      });
    });
  }

  function initZenToggle() {
    if (!zenBtn) return;
    zenBtn.addEventListener('click', () => {
      const url = new URL(window.location.href);
      const isZen = url.searchParams.get('zen') === '1' || cfg.zenMode === true;
      try {
        if (State.currentTask && State.currentTask.task_id) {
          saveDraftsForTask(State.currentTask.task_id);
          url.searchParams.set('task_id', String(State.currentTask.task_id));
        }
      } catch (_) {}
      try {
        const t = State.taskType || getTaskTypeFromUI();
        if (Number.isFinite(t) && t >= 1 && t <= 27) url.searchParams.set('task_type', String(t));
      } catch (_) {}
      if (isZen) url.searchParams.delete('zen');
      else url.searchParams.set('zen', '1');
      window.location.href = url.toString();
    });

    const exitBtn = document.getElementById('tv2ZenExitBtn');
    if (exitBtn) {
      exitBtn.addEventListener('click', () => {
        const url = new URL(window.location.href);
        try {
          if (State.currentTask && State.currentTask.task_id) {
            saveDraftsForTask(State.currentTask.task_id);
            url.searchParams.set('task_id', String(State.currentTask.task_id));
          }
        } catch (_) {}
        try {
          const t = State.taskType || getTaskTypeFromUI();
          if (Number.isFinite(t) && t >= 1 && t <= 27) url.searchParams.set('task_type', String(t));
        } catch (_) {}
        url.searchParams.delete('zen');
        window.location.href = url.toString();
      });
    }
  }

  function initVisited() {
    const prev = safeJsonParse(lsGet(LS.visited, '[]'), []);
    if (Array.isArray(prev)) State.visitedIds = prev.filter(x => Number.isFinite(Number(x))).map(x => Number(x));
  }

  function saveVisited() {
    lsSet(LS.visited, JSON.stringify(State.visitedIds.slice(0, 250)));
  }

  async function loadGlossary() {
    try {
      const res = await fetch('/static/trainer_v2/glossary.json', { cache: 'no-store', headers: { 'X-No-Loading-Overlay': '1' } });
      const data = await res.json().catch(() => null);
      if (data && Array.isArray(data.terms)) {
        State.glossary = data.terms
          .map((t) => ({
            key: String(t.key || t.term || ''),
            term: String(t.term || ''),
            title: String(t.title || t.term || ''),
            body: String(t.body || ''),
            url: String(t.url || '/theory')
          }))
          .filter(t => t.term.trim().length > 1);
      } else {
        State.glossary = [];
      }
    } catch (_) {
      State.glossary = [];
    }
  }

  function getTaskTypeFromUI() {
    const v = Number(taskTypeEl && taskTypeEl.value);
    if (!Number.isFinite(v) || v < 1 || v > 27) return 1;
    return v;
  }

  function setTaskTypeInUI(v) {
    if (!taskTypeEl) return;
    taskTypeEl.value = String(v);
  }

  async function streamStart({ taskType, taskId }) {
    const payload = {
      task_type: taskType,
      exclude_task_ids: State.visitedIds.slice(0, 200)
    };
    if (taskId) payload.task_id = taskId;
    const res = await apiFetch('/task/stream/start', { method: 'POST', body: JSON.stringify(payload) });
    return res;
  }

  async function streamNext({ taskType }) {
    const payload = {
      action: 'next',
      task_type: taskType,
      exclude_task_ids: State.visitedIds.slice(0, 200)
    };
    const res = await apiFetch('/task/stream/act', { method: 'POST', body: JSON.stringify(payload) });
    return res;
  }

  async function fetchTask(taskId) {
    const res = await apiFetch(`/task/${encodeURIComponent(taskId)}`, { method: 'GET' });
    return res;
  }

  async function submitAnswer({ taskId, answer, timeSpentSec }) {
    const payload = { task_id: taskId, answer: answer || '' };
    if (timeSpentSec != null) payload.time_spent_sec = timeSpentSec;
    const res = await apiFetch('/task/submit_answer', { method: 'POST', body: JSON.stringify(payload) });
    return res;
  }

  async function runCode({ code, stdin, timeoutSeconds }) {
    const payload = { code: code || '', stdin: stdin || '', timeout_seconds: timeoutSeconds != null ? timeoutSeconds : 2.0 };
    const res = await apiFetch('/code/run', { method: 'POST', body: JSON.stringify(payload) });
    return res;
  }

  function ensureTaskVisited(task) {
    if (!task || !task.task_id) return;
    const id = Number(task.task_id);
    if (!Number.isFinite(id)) return;
    if (!State.visitedIds.includes(id)) {
      State.visitedIds.unshift(id);
      saveVisited();
    }
  }

  function timeSpentSec() {
    if (!State.taskLoadedAtMs) return null;
    const sec = Math.round((nowMs() - State.taskLoadedAtMs) / 1000);
    return clamp(sec, 0, 60 * 60);
  }

  function getCurrentCode() {
    try { return State.cm ? State.cm.getValue() : ''; } catch (_) { return ''; }
  }

  function getCurrentAnswer() {
    if (State.editorView && typeof State.editorView.getAnswer === 'function') return State.editorView.getAnswer();
    return '';
  }

  function setCurrentCode(v) {
    try { if (State.cm) State.cm.setValue(String(v || '')); } catch (_) {}
  }

  function setCurrentAnswer(v) {
    if (State.editorView && typeof State.editorView.setAnswer === 'function') State.editorView.setAnswer(String(v || ''));
  }

  function loadDraftsForTask(taskId) {
    const code = lsGet(LS.code(taskId), '');
    const ans = lsGet(LS.answer(taskId), '');
    setCurrentCode(code);
    setCurrentAnswer(ans);
  }

  function saveDraftsForTask(taskId) {
    const code = getCurrentCode();
    const ans = getCurrentAnswer();
    lsSet(LS.code(taskId), code);
    lsSet(LS.answer(taskId), ans);
  }

  function pushVersion(taskId, kind, note) {
    const code = getCurrentCode();
    const ans = getCurrentAnswer();
    const list = safeJsonParse(lsGet(LS.versions(taskId), '[]'), []);
    const next = Array.isArray(list) ? list : [];
    next.unshift({
      id: makeId('v'),
      ts: nowMs(),
      kind: String(kind || 'snapshot'),
      note: note ? String(note) : '',
      code,
      answer: ans
    });
    if (next.length > 30) next.splice(30);
    lsSet(LS.versions(taskId), JSON.stringify(next));
    if (State.historyView && typeof State.historyView.render === 'function') State.historyView.render();
  }

  function setCurrentTask(task, { keepDrafts } = {}) {
    if (!task) return;
    State.currentTask = task;
    State.taskLoadedAtMs = nowMs();
    setTaskMeta(task);
    ensureTaskVisited(task);
    logEvent('task_open', { task_id: task.task_id, task_number: task.task_number });
    if (!keepDrafts) loadDraftsForTask(task.task_id);
    try { if (State.editorView && State.editorView.updateAttemptsUI) State.editorView.updateAttemptsUI(task.task_id); } catch (_) {}
    if (State.conditionView && typeof State.conditionView.render === 'function') State.conditionView.render();
    if (State.testsView && typeof State.testsView.render === 'function') State.testsView.render();
    if (State.historyView && typeof State.historyView.render === 'function') State.historyView.render();
    try { if (State.assistantView && typeof State.assistantView.loadForTask === 'function') State.assistantView.loadForTask(task.task_id); } catch (_) {}
    if (State.scratchCanvasApi && typeof State.scratchCanvasApi.loadForTask === 'function') State.scratchCanvasApi.loadForTask(task.task_id);
    if (State.md && typeof State.md.value === 'function') {
      const md = lsGet(LS.scratchMd(task.task_id), '');
      State.md.value(md || '');
    }
    nextBtn && (nextBtn.disabled = false);
  }

  async function startFlow() {
    const t = getTaskTypeFromUI();
    State.taskType = t;
    lsSet(LS.lastTaskType, String(t));
    nextBtn && (nextBtn.disabled = true);
    logEvent('stream_start', { task_type: t, passthrough: cfg.passthrough || null });

    const pinnedTaskId = cfg.passthrough && cfg.passthrough.task_id ? Number(cfg.passthrough.task_id) : null;
    const res = await streamStart({ taskType: t, taskId: pinnedTaskId });
    if (res.done || !res.task) {
      pushInlineToast({ kind: 'error', title: 'задачи закончились', message: 'для выбранного типа не удалось подобрать новое задание' });
      nextBtn && (nextBtn.disabled = true);
      setTaskMeta(null);
      return;
    }
    setCurrentTask(res.task, { keepDrafts: false });
  }

  async function goNext() {
    if (!State.taskType) State.taskType = getTaskTypeFromUI();
    const t = State.taskType;
    nextBtn && (nextBtn.disabled = true);
    saveDraftsForTask(State.currentTask && State.currentTask.task_id);
    const res = await streamNext({ taskType: t });
    if (res.done || !res.task) {
      pushInlineToast({ kind: 'error', title: 'задачи закончились', message: 'в этой сессии больше нет новых задач по выбранному типу' });
      nextBtn && (nextBtn.disabled = true);
      return;
    }
    setCurrentTask(res.task, { keepDrafts: false });
  }

  function mountPopover({ anchorRect, title, body, actions }) {
    const pop = document.createElement('div');
    pop.className = 'tv2-popover';
    const t = document.createElement('div');
    t.className = 'tv2-popover-title';
    t.textContent = title || '';
    const b = document.createElement('div');
    b.className = 'tv2-popover-body';
    b.textContent = body || '';
    pop.appendChild(t);
    pop.appendChild(b);
    if (Array.isArray(actions) && actions.length > 0) {
      const row = document.createElement('div');
      row.className = 'tv2-popover-actions';
      actions.forEach((a) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `tv2-btn ${a.danger ? 'tv2-btn-danger' : ''}`.trim();
        btn.textContent = a.label || 'ok';
        btn.addEventListener('click', () => {
          try { a.onClick && a.onClick(); } finally { pop.remove(); }
        });
        row.appendChild(btn);
      });
      pop.appendChild(row);
    }
    document.body.appendChild(pop);

    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const pad = 10;
    const w = pop.offsetWidth;
    const h = pop.offsetHeight;
    const left = clamp(anchorRect.left, pad, vw - w - pad);
    const top = clamp(anchorRect.bottom + 10, pad, vh - h - pad);
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;

    const onDown = (e) => {
      if (!pop.contains(e.target)) pop.remove();
    };
    setTimeout(() => document.addEventListener('mousedown', onDown, { once: true }), 0);
    return pop;
  }

  function walkTextNodes(root, shouldSkip) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => {
        if (!node || !node.parentElement) return NodeFilter.FILTER_REJECT;
        if (shouldSkip && shouldSkip(node)) return NodeFilter.FILTER_REJECT;
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const out = [];
    let n = walker.nextNode();
    while (n) { out.push(n); n = walker.nextNode(); }
    return out;
  }

  function getOffsetInContainer(container, node, offset) {
    const texts = walkTextNodes(container, () => false);
    let acc = 0;
    for (const t of texts) {
      if (t === node) return acc + offset;
      acc += t.nodeValue.length;
    }
    return null;
  }

  function resolveTextEndpoint(container, node, offset, dir) {
    if (!node) return null;
    if (node.nodeType === Node.TEXT_NODE) return { node, offset: clamp(offset, 0, node.nodeValue.length) };
    const texts = walkTextNodes(container, () => false);
    if (texts.length === 0) return null;
    if (dir === 'start') return { node: texts[0], offset: 0 };
    return { node: texts[texts.length - 1], offset: texts[texts.length - 1].nodeValue.length };
  }

  function selectionOffsetsIn(container) {
    const sel = window.getSelection && window.getSelection();
    if (!sel || sel.rangeCount === 0) return null;
    const r = sel.getRangeAt(0);
    if (!r || r.collapsed) return null;
    if (!container.contains(r.commonAncestorContainer)) return null;
    const s = resolveTextEndpoint(container, r.startContainer, r.startOffset, 'start');
    const e = resolveTextEndpoint(container, r.endContainer, r.endOffset, 'end');
    if (!s || !e) return null;
    const a = getOffsetInContainer(container, s.node, s.offset);
    const b = getOffsetInContainer(container, e.node, e.offset);
    if (a == null || b == null) return null;
    const start = Math.min(a, b);
    const end = Math.max(a, b);
    if (end - start < 1) return null;
    return { start, end, text: r.toString() };
  }

  function clearHighlights(container) {
    $all('mark.tv2-hl', container).forEach((m) => {
      const parent = m.parentNode;
      while (m.firstChild) parent.insertBefore(m.firstChild, m);
      parent.removeChild(m);
      parent.normalize();
    });
  }

  function applyHighlightsByOffsets(container, highlights) {
    if (!Array.isArray(highlights) || highlights.length === 0) return;
    const textNodes = walkTextNodes(container, (node) => {
      const p = node.parentElement;
      if (!p) return true;
      if (p.closest('pre, code, a, script, style')) return true;
      return false;
    });
    if (textNodes.length === 0) return;

    const parts = [];
    let acc = 0;
    for (const n of textNodes) {
      const len = n.nodeValue.length;
      parts.push({ node: n, start: acc, end: acc + len });
      acc += len;
    }

    const sorted = highlights
      .map(h => ({ id: h.id || makeId('hl'), start: Number(h.start), end: Number(h.end) }))
      .filter(h => Number.isFinite(h.start) && Number.isFinite(h.end) && h.end > h.start)
      .sort((a, b) => b.start - a.start);

    for (const h of sorted) {
      const start = clamp(h.start, 0, acc);
      const end = clamp(h.end, 0, acc);
      if (end <= start) continue;
      const startPart = parts.find(p => start >= p.start && start <= p.end);
      const endPart = parts.find(p => end >= p.start && end <= p.end);
      if (!startPart || !endPart) continue;

      const range = document.createRange();
      try {
        range.setStart(startPart.node, clamp(start - startPart.start, 0, startPart.node.nodeValue.length));
        range.setEnd(endPart.node, clamp(end - endPart.start, 0, endPart.node.nodeValue.length));
        const mark = document.createElement('mark');
        mark.className = 'tv2-hl';
        mark.setAttribute('data-hl-id', String(h.id));
        range.surroundContents(mark);
      } catch (_) {
        try { range.detach(); } catch (_) {}
      }
    }
  }

  function wrapGlossaryTerms(container) {
    if (!cfg.canViewTheory) return;
    const terms = Array.isArray(State.glossary) ? State.glossary : [];
    if (terms.length === 0) return;

    const sorted = terms.slice().sort((a, b) => b.term.length - a.term.length);
    const esc = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const union = sorted.map(t => esc(t.term.trim())).filter(Boolean);
    if (union.length === 0) return;
    const re = new RegExp(`(${union.join('|')})`, 'gi');

    const skip = (node) => {
      const p = node.parentElement;
      if (!p) return true;
      if (p.closest('pre, code, a, script, style, mark')) return true;
      return false;
    };
    const texts = walkTextNodes(container, skip);

    for (const tn of texts) {
      const raw = tn.nodeValue;
      re.lastIndex = 0;
      if (!re.test(raw)) continue;
      re.lastIndex = 0;

      const frag = document.createDocumentFragment();
      let last = 0;
      let m;
      while ((m = re.exec(raw)) !== null) {
        const idx = m.index;
        const hit = m[0];
        if (idx > last) frag.appendChild(document.createTextNode(raw.slice(last, idx)));
        const span = document.createElement('span');
        span.className = 'tv2-term';
        span.textContent = hit;
        const termObj = sorted.find(t => t.term.toLowerCase() === hit.toLowerCase()) || null;
        if (termObj) span.setAttribute('data-term-key', termObj.key);
        frag.appendChild(span);
        last = idx + hit.length;
      }
      if (last < raw.length) frag.appendChild(document.createTextNode(raw.slice(last)));
      tn.parentNode.replaceChild(frag, tn);
    }
  }

  function initGlossaryTooltips(container) {
    let activePop = null;
    container.addEventListener('mouseover', (e) => {
      const t = e.target && e.target.closest ? e.target.closest('.tv2-term') : null;
      if (!t) return;
      const key = t.getAttribute('data-term-key') || '';
      const termObj = (State.glossary || []).find(x => x.key === key) || null;
      if (!termObj) return;
      if (activePop) activePop.remove();
      const rect = t.getBoundingClientRect();
      activePop = mountPopover({
        anchorRect: rect,
        title: termObj.title,
        body: termObj.body,
        actions: [
          { label: 'открыть теорию', onClick: () => { window.open(termObj.url || '/theory', '_blank', 'noopener'); } }
        ]
      });
    });
    container.addEventListener('mouseout', (e) => {
      const related = e.relatedTarget;
      if (activePop && related && activePop.contains(related)) return;
      if (activePop) { activePop.remove(); activePop = null; }
    });
  }

  function makeConditionComponent() {
    const wrap = document.createElement('div');
    wrap.className = 'tv2-panel tv2-panel-scroll';

    const head = document.createElement('div');
    head.style.display = 'flex';
    head.style.justifyContent = 'space-between';
    head.style.alignItems = 'center';
    head.style.gap = '0.75rem';
    head.style.flexWrap = 'wrap';

    const title = document.createElement('h2');
    title.className = 'tv2-h1';
    title.textContent = 'условие';

    const actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.gap = '0.5rem';
    actions.style.flexWrap = 'wrap';

    const clearHlBtn = document.createElement('button');
    clearHlBtn.type = 'button';
    clearHlBtn.className = 'tv2-btn';
    clearHlBtn.textContent = 'очистить подсветки';
    clearHlBtn.addEventListener('click', () => {
      const task = State.currentTask;
      if (!task) return;
      lsDel(LS.highlights(task.task_id));
      const content = $('.tv2-task-content', wrap);
      if (content) clearHighlights(content);
      logEvent('highlights_clear', { task_id: task.task_id });
    });

    actions.appendChild(clearHlBtn);
    head.appendChild(title);
    head.appendChild(actions);

    const card = document.createElement('div');
    card.className = 'tv2-card';

    const content = document.createElement('div');
    content.className = 'tv2-task-content';
    content.setAttribute('id', 'tv2TaskContent');
    card.appendChild(content);

    const attachWrap = document.createElement('div');
    attachWrap.style.marginTop = '0.85rem';
    attachWrap.style.display = 'grid';
    attachWrap.style.gap = '0.35rem';

    wrap.appendChild(head);
    wrap.appendChild(card);
    wrap.appendChild(attachWrap);

    function render() {
      const task = State.currentTask;
      if (!task) {
        content.innerHTML = '<div class="tv2-muted">задача не выбрана</div>';
        attachWrap.innerHTML = '';
        return;
      }
      const html = String(task.content_html || '').trim();
      content.innerHTML = html || '<div class="tv2-muted">нет условия</div>';

      // подсветки
      try {
        const hls = safeJsonParse(lsGet(LS.highlights(task.task_id), '[]'), []);
        clearHighlights(content);
        applyHighlightsByOffsets(content, hls);
      } catch (_) {}

      // инлайн‑термины
      try {
        wrapGlossaryTerms(content);
      } catch (_) {}

      // вложения
      const files = parseAttachedFiles(task.attached_files);
      if (!files || files.length === 0) {
        attachWrap.innerHTML = '';
      } else {
        attachWrap.innerHTML = '';
        const label = document.createElement('div');
        label.className = 'tv2-muted';
        label.style.fontWeight = '900';
        label.textContent = 'вложения';
        attachWrap.appendChild(label);
        const ul = document.createElement('div');
        ul.style.display = 'grid';
        ul.style.gap = '0.35rem';
        files.forEach((f) => {
          let path = '';
          let name = 'файл';
          if (typeof f === 'string') {
            path = f;
            name = f.split('/').pop() || 'файл';
          } else if (f && typeof f === 'object') {
            path = String(f.path || f.url || '');
            name = String(f.name || f.filename || (path.split('/').pop() || 'файл'));
          }
          if (!path) return;
          const a = document.createElement('a');
          a.className = 'tv2-btn';
          a.style.textDecoration = 'none';
          a.textContent = name;
          if (path.startsWith('http')) {
            a.href = path;
            a.target = '_blank';
            a.rel = 'noopener';
          } else {
            const u = `${cfg.baseApi}/task/${encodeURIComponent(task.task_id)}/attachment?path=${encodeURIComponent(path)}&token=${encodeURIComponent(token)}`;
            a.href = u;
          }
          ul.appendChild(a);
        });
        attachWrap.appendChild(ul);
      }
    }

    // хайлайтер: мини‑popover при выделении
    let hlPop = null;
    const onSel = () => {
      if (hlPop) { hlPop.remove(); hlPop = null; }
      const task = State.currentTask;
      if (!task) return;
      const off = selectionOffsetsIn(content);
      if (!off) return;
      const r = window.getSelection().getRangeAt(0);
      const rect = r.getBoundingClientRect();
      hlPop = mountPopover({
        anchorRect: rect,
        title: 'подсветка',
        body: `выделено: ${off.text.slice(0, 120)}${off.text.length > 120 ? '…' : ''}`,
        actions: [
          {
            label: 'подсветить',
            onClick: () => {
              const list = safeJsonParse(lsGet(LS.highlights(task.task_id), '[]'), []);
              const next = Array.isArray(list) ? list : [];
              const id = makeId('hl');
              next.push({ id, start: off.start, end: off.end });
              lsSet(LS.highlights(task.task_id), JSON.stringify(next));
              try {
                clearHighlights(content);
                applyHighlightsByOffsets(content, next);
              } catch (_) {}
              logEvent('highlight_add', { task_id: task.task_id, start: off.start, end: off.end });
              try { window.getSelection().removeAllRanges(); } catch (_) {}
            }
          },
          {
            label: 'отмена',
            danger: true,
            onClick: () => { try { window.getSelection().removeAllRanges(); } catch (_) {} }
          }
        ]
      });
    };
    content.addEventListener('mouseup', () => setTimeout(onSel, 0));
    content.addEventListener('keyup', () => setTimeout(onSel, 0));

    initGlossaryTooltips(content);

    return { el: wrap, render };
  }

  function pythonBuiltinsDocs() {
    return {
      len: { title: 'len(x)', body: 'возвращает длину последовательности или количество элементов.\n\nпример:\nlen([1,2,3]) → 3' },
      range: { title: 'range(start, stop, step)', body: 'генерирует последовательность целых чисел.\n\nпример:\nfor i in range(5): print(i)' },
      int: { title: 'int(x, base=10)', body: 'преобразует в целое число.\n\nпример:\nint(\"101\", 2) → 5' },
      str: { title: 'str(x)', body: 'преобразует объект в строку.\n\nпример:\nstr(42) → \"42\"' },
      list: { title: 'list(iterable)', body: 'создаёт список.\n\nпример:\nlist(\"abc\") → [\"a\",\"b\",\"c\"]' },
      dict: { title: 'dict(...)', body: 'создаёт словарь.\n\nпример:\ndict(a=1, b=2) → {\"a\":1,\"b\":2}' },
      set: { title: 'set(iterable)', body: 'создаёт множество уникальных элементов.\n\nпример:\nset([1,1,2]) → {1,2}' },
      sum: { title: 'sum(iterable, start=0)', body: 'суммирует значения.\n\nпример:\nsum([1,2,3]) → 6' },
      min: { title: 'min(iterable)', body: 'минимум.\n\nпример:\nmin([3,1,2]) → 1' },
      max: { title: 'max(iterable)', body: 'максимум.\n\nпример:\nmax([3,1,2]) → 3' },
      sorted: { title: 'sorted(iterable, key=None, reverse=False)', body: 'возвращает отсортированный список.\n\nпример:\nsorted([3,1,2]) → [1,2,3]' },
      enumerate: { title: 'enumerate(iterable, start=0)', body: 'возвращает пары (индекс, значение).\n\nпример:\nfor i,x in enumerate([\"a\",\"b\"]): ...' },
      map: { title: 'map(func, iterable)', body: 'применяет функцию ко всем элементам.\n\nпример:\nlist(map(int, [\"1\",\"2\"])) → [1,2]' },
      filter: { title: 'filter(func, iterable)', body: 'фильтрует элементы по условию.\n\nпример:\nlist(filter(lambda x: x%2==0, [1,2,3,4])) → [2,4]' }
    };
  }

  function makeEditorComponent() {
    const wrap = document.createElement('div');
    wrap.className = 'tv2-panel';

    const head = document.createElement('div');
    head.style.display = 'flex';
    head.style.justifyContent = 'space-between';
    head.style.alignItems = 'center';
    head.style.gap = '0.75rem';
    head.style.flexWrap = 'wrap';

    const title = document.createElement('h2');
    title.className = 'tv2-h1';
    title.textContent = 'редактор/ответ';

    const headActions = document.createElement('div');
    headActions.style.display = 'flex';
    headActions.style.gap = '0.5rem';
    headActions.style.flexWrap = 'wrap';

    const snapBtn = document.createElement('button');
    snapBtn.type = 'button';
    snapBtn.className = 'tv2-btn';
    snapBtn.textContent = 'снапшот';
    snapBtn.addEventListener('click', () => {
      const task = State.currentTask;
      if (!task) return;
      pushVersion(task.task_id, 'snapshot', 'ручной снимок');
      pushInlineToast({ kind: 'success', title: 'снапшот', message: 'версия сохранена в истории' });
      logEvent('snapshot', { task_id: task.task_id });
    });

    headActions.appendChild(snapBtn);
    head.appendChild(title);
    head.appendChild(headActions);

    const grid = document.createElement('div');
    grid.className = 'tv2-editor-wrap';

    const editorBox = document.createElement('div');
    editorBox.className = 'tv2-editor-box';
    const editorTa = document.createElement('textarea');
    editorTa.setAttribute('aria-label', 'код');
    editorTa.value = '';
    editorBox.appendChild(editorTa);

    const bottom = document.createElement('div');
    bottom.style.display = 'grid';
    bottom.style.gap = '0.75rem';

    const ans = document.createElement('input');
    ans.className = 'tv2-input';
    ans.placeholder = 'ответ (для проверки)';
    ans.setAttribute('id', 'tv2AnswerInput');

    const btnRow = document.createElement('div');
    btnRow.className = 'tv2-editor-actions';

    const runBtn = document.createElement('button');
    runBtn.type = 'button';
    runBtn.className = 'tv2-btn';
    runBtn.textContent = 'запустить код';

    const sendBtn = document.createElement('button');
    sendBtn.type = 'button';
    sendBtn.className = 'tv2-btn';
    sendBtn.textContent = 'проверить ответ';

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'tv2-btn';
    saveBtn.textContent = 'сохранить черновик';
    saveBtn.addEventListener('click', () => {
      const task = State.currentTask;
      if (!task) return;
      saveDraftsForTask(task.task_id);
      pushInlineToast({ kind: 'success', title: 'черновик', message: 'код и ответ сохранены локально для этой задачи' });
      logEvent('draft_save', { task_id: task.task_id });
    });

    btnRow.appendChild(runBtn);
    btnRow.appendChild(sendBtn);
    btnRow.appendChild(saveBtn);

    bottom.appendChild(ans);
    bottom.appendChild(btnRow);

    grid.appendChild(editorBox);
    grid.appendChild(bottom);

    wrap.appendChild(head);
    wrap.appendChild(grid);

    // CodeMirror init (после mount)
    let cm = null;
    function mountEditor() {
      if (cm) return cm;
      const eff = effectiveTheme(getTrainerThemeMode());
      cm = CodeMirror.fromTextArea(editorTa, {
        mode: 'python',
        theme: eff === 'light' ? 'default' : 'dracula',
        lineNumbers: true,
        indentUnit: 4,
        lineWrapping: true,
        autoCloseBrackets: true,
        matchBrackets: true
      });
      cm.setSize(null, '100%');
      State.cm = cm;

      const docs = pythonBuiltinsDocs();
      cm.getWrapperElement().addEventListener('contextmenu', (e) => {
        e.preventDefault();
        const pos = cm.coordsChar({ left: e.clientX, top: e.clientY });
        const tokenAt = cm.getTokenAt(pos);
        const word = (tokenAt && tokenAt.string) ? tokenAt.string : '';
        const key = word && docs[word] ? word : null;
        if (!key) {
          pushInlineToast({ kind: 'error', title: 'справка', message: 'не удалось найти справку для выбранного слова' });
          return;
        }
        const rect = { left: e.clientX, top: e.clientY, bottom: e.clientY, right: e.clientX };
        mountPopover({
          anchorRect: rect,
          title: docs[key].title,
          body: docs[key].body,
          actions: [{ label: 'ok', onClick: () => {} }]
        });
        logEvent('doc_open', { word: key });
      });

      // автосохранение кода (debounce)
      let t = null;
      cm.on('change', () => {
        const task = State.currentTask;
        if (!task) return;
        if (t) clearTimeout(t);
        t = setTimeout(() => {
          lsSet(LS.code(task.task_id), cm.getValue());
          logEvent('code_autosave', { task_id: task.task_id, len: cm.getValue().length });
        }, 550);
      });

      return cm;
    }

    // автосохранение ответа
    let ansT = null;
    ans.addEventListener('input', () => {
      const task = State.currentTask;
      if (!task) return;
      if (ansT) clearTimeout(ansT);
      ansT = setTimeout(() => {
        lsSet(LS.answer(task.task_id), ans.value);
        logEvent('answer_autosave', { task_id: task.task_id, len: ans.value.length });
      }, 450);
    });

    function getAnswer() { return ans.value || ''; }
    function setAnswer(v) { ans.value = String(v || ''); }

    function getAttempts(taskId) {
      const raw = safeJsonParse(lsGet(LS.attempts(taskId), '{}'), {});
      const used = Number(raw.used || 0);
      return { used: Number.isFinite(used) ? used : 0 };
    }

    function setAttempts(taskId, used) {
      lsSet(LS.attempts(taskId), JSON.stringify({ used: used }));
    }

    function updateAttemptsUI(taskId) {
      const t = getAttempts(taskId);
      if (taskMetaEl) {
        const base = taskMetaEl.textContent || '';
        const cleaned = base.replace(/\s*·\s*попытки:\s*\d+\s*$/i, '').trim();
        taskMetaEl.textContent = `${cleaned} · попытки: ${t.used}`;
      }
    }

    runBtn.addEventListener('click', async () => {
      const task = State.currentTask;
      const code = getCurrentCode();
      if (!task) return;
      if (!code.trim()) {
        pushInlineToast({ kind: 'error', title: 'запуск', message: 'код пустой' });
        return;
      }
      runBtn.disabled = true;
      const original = runBtn.textContent;
      runBtn.textContent = 'запуск...';
      pushVersion(task.task_id, 'run', 'запуск кода');
      try {
        const res = await runCode({ code: code, stdin: '', timeoutSeconds: 2.0 });
        State.lastRun = res.run || res.result || res;
        if (State.terminalView && typeof State.terminalView.render === 'function') State.terminalView.render();
        const ok = State.lastRun && State.lastRun.ok;
        pushInlineToast({
          kind: ok ? 'success' : 'error',
          title: 'запуск',
          message: ok ? 'выполнено (см. терминал)' : 'ошибка (см. терминал)'
        });
        logEvent('run_done', { task_id: task.task_id, ok: !!ok });
      } catch (e) {
        State.lastRun = { ok: false, error: 'runner_error', details: e.message, stdout: '', stderr: '' };
        if (State.terminalView && typeof State.terminalView.render === 'function') State.terminalView.render();
        pushInlineToast({ kind: 'error', title: 'запуск', message: `ошибка: ${e.message}` });
        logEvent('run_fail', { task_id: task.task_id, error: e.message });
      } finally {
        runBtn.disabled = false;
        runBtn.textContent = original;
      }
    });

    sendBtn.addEventListener('click', async () => {
      const task = State.currentTask;
      if (!task) return;
      const val = (ans.value || '').trim();
      if (!val) {
        pushInlineToast({ kind: 'error', title: 'проверка', message: 'сначала нужно ввести ответ' });
        return;
      }

      saveDraftsForTask(task.task_id);
      pushVersion(task.task_id, 'submit', 'проверка ответа');

      const attempts = getAttempts(task.task_id);
      const nextUsedBase = attempts.used + 1;

      sendBtn.disabled = true;
      const originalText = sendBtn.textContent;
      sendBtn.textContent = 'проверка...';

      try {
        const res = await submitAnswer({ taskId: task.task_id, answer: val, timeSpentSec: timeSpentSec() });
        const ok = !!res.is_correct;
        if (ok) {
          setAttempts(task.task_id, nextUsedBase);
          setStreak(getStreak() + 1);
          updateAttemptsUI(task.task_id);
          pushInlineToast({
            kind: 'success',
            title: 'проверка',
            message: `верно · рейтинг: ${res.new_rating != null ? res.new_rating : '—'}`
          });
        } else {
          setAttempts(task.task_id, nextUsedBase);
          setStreak(0);
          updateAttemptsUI(task.task_id);
          pushInlineToast({
            kind: 'error',
            title: 'проверка',
            message: 'неверно · можно попробовать ещё раз'
          });
        }
        logEvent('submit_done', { task_id: task.task_id, is_correct: ok, new_rating: res.new_rating });
      } catch (e) {
        pushInlineToast({ kind: 'error', title: 'проверка', message: `ошибка: ${e.message}` });
        logEvent('submit_fail', { task_id: task.task_id, error: e.message });
      } finally {
        sendBtn.disabled = false;
        sendBtn.textContent = originalText;
      }
    });

    return {
      el: wrap,
      mountEditor,
      getAnswer,
      setAnswer,
      updateAttemptsUI
    };
  }

  function makeTestsComponent() {
    const wrap = document.createElement('div');
    wrap.className = 'tv2-panel tv2-panel-scroll';

    const title = document.createElement('h2');
    title.className = 'tv2-h1';
    title.textContent = 'проверка';

    const list = document.createElement('div');
    list.style.display = 'grid';
    list.style.gap = '0.75rem';

    wrap.appendChild(title);
    wrap.appendChild(list);

    function render() {
      list.innerHTML = '';
      const task = State.currentTask;
      if (!task) {
        list.innerHTML = '<div class="tv2-muted">задача не выбрана</div>';
        return;
      }
      const card = document.createElement('div');
      card.className = 'tv2-card';
      card.innerHTML = `<div class="tv2-muted">проверка ответов выполняется кнопкой «проверить ответ» (без фоновой очереди)</div>`;
      list.appendChild(card);
    }

    return { el: wrap, render };
  }

  function renderSideBySideDiff(a, b) {
    const diff = (window.Diff && window.Diff.diffLines) ? window.Diff.diffLines(a || '', b || '') : [];
    const leftLines = [];
    const rightLines = [];
    diff.forEach((part) => {
      const lines = String(part.value || '').split('\n');
      if (lines.length && lines[lines.length - 1] === '') lines.pop();
      if (part.added) {
        lines.forEach((l) => {
          rightLines.push({ kind: 'add', text: l });
          leftLines.push({ kind: 'empty', text: '' });
        });
      } else if (part.removed) {
        lines.forEach((l) => {
          leftLines.push({ kind: 'del', text: l });
          rightLines.push({ kind: 'empty', text: '' });
        });
      } else {
        lines.forEach((l) => {
          leftLines.push({ kind: 'same', text: l });
          rightLines.push({ kind: 'same', text: l });
        });
      }
    });
    return { leftLines, rightLines };
  }

  function makeHistoryComponent() {
    const wrap = document.createElement('div');
    wrap.className = 'tv2-panel tv2-panel-scroll';

    const title = document.createElement('h2');
    title.className = 'tv2-h1';
    title.textContent = 'история';

    const list = document.createElement('div');
    list.className = 'tv2-history-list';

    const diffCard = document.createElement('div');
    diffCard.className = 'tv2-card';
    diffCard.style.display = 'grid';
    diffCard.style.gap = '0.75rem';

    wrap.appendChild(title);
    wrap.appendChild(list);
    wrap.appendChild(diffCard);

    function render() {
      list.innerHTML = '';
      diffCard.innerHTML = '';
      const task = State.currentTask;
      if (!task) {
        list.innerHTML = '<div class="tv2-muted">задача не выбрана</div>';
        return;
      }
      const versions = safeJsonParse(lsGet(LS.versions(task.task_id), '[]'), []);
      const arr = Array.isArray(versions) ? versions : [];
      if (arr.length === 0) {
        list.innerHTML = '<div class="tv2-muted">пока нет версий. кнопка «снапшот» сохраняет текущую мысль.</div>';
        return;
      }

      const header = document.createElement('div');
      header.className = 'tv2-card';
      header.style.display = 'flex';
      header.style.justifyContent = 'space-between';
      header.style.alignItems = 'center';
      header.style.gap = '0.75rem';
      header.style.flexWrap = 'wrap';

      const left = document.createElement('div');
      left.innerHTML = `<div style="font-weight:900;">версии: ${arr.length}</div><div class="tv2-muted">выберите 2 версии для сравнения или откатитесь</div>`;
      const right = document.createElement('div');
      right.style.display = 'flex';
      right.style.gap = '0.5rem';
      right.style.flexWrap = 'wrap';

      const baseSel = document.createElement('select');
      baseSel.className = 'trainer-v2-select';
      const cmpSel = document.createElement('select');
      cmpSel.className = 'trainer-v2-select';
      arr.forEach((v, idx) => {
        const opt1 = document.createElement('option');
        opt1.value = v.id;
        opt1.textContent = `${idx === 0 ? 'текущая' : v.kind} · ${fmtTime(v.ts)}`;
        const opt2 = opt1.cloneNode(true);
        baseSel.appendChild(opt1);
        cmpSel.appendChild(opt2);
      });
      if (arr.length > 1) cmpSel.selectedIndex = 1;

      const diffBtn = document.createElement('button');
      diffBtn.type = 'button';
      diffBtn.className = 'tv2-btn';
      diffBtn.textContent = 'сравнить';

      right.appendChild(baseSel);
      right.appendChild(cmpSel);
      right.appendChild(diffBtn);
      header.appendChild(left);
      header.appendChild(right);
      diffCard.appendChild(header);

      diffBtn.addEventListener('click', () => {
        const aId = baseSel.value;
        const bId = cmpSel.value;
        const aV = arr.find(x => x.id === aId) || arr[0];
        const bV = arr.find(x => x.id === bId) || arr[0];
        const d = renderSideBySideDiff(aV.code || '', bV.code || '');
        const block = document.createElement('div');
        block.className = 'tv2-diff-wrap';
        const leftCol = document.createElement('div');
        leftCol.className = 'tv2-diff-col';
        const rightCol = document.createElement('div');
        rightCol.className = 'tv2-diff-col';

        const mkPre = (lines) => {
          const pre = document.createElement('pre');
          pre.className = 'tv2-diff-pre';
          pre.innerHTML = lines.map((ln) => {
            const cls = ln.kind === 'add' ? 'tv2-line-add' : (ln.kind === 'del' ? 'tv2-line-del' : '');
            const txt = escapeHtml(ln.text);
            return `<div class="${cls}">${txt || '&nbsp;'}</div>`;
          }).join('');
          return pre;
        };
        leftCol.appendChild(mkPre(d.leftLines));
        rightCol.appendChild(mkPre(d.rightLines));
        block.appendChild(leftCol);
        block.appendChild(rightCol);

        const actions = document.createElement('div');
        actions.style.display = 'flex';
        actions.style.gap = '0.5rem';
        actions.style.flexWrap = 'wrap';
        const restoreBtn = document.createElement('button');
        restoreBtn.type = 'button';
        restoreBtn.className = 'tv2-btn tv2-btn-danger';
        restoreBtn.textContent = 'восстановить выбранную версию';
        restoreBtn.addEventListener('click', () => {
          setCurrentCode(bV.code || '');
          setCurrentAnswer(bV.answer || '');
          saveDraftsForTask(task.task_id);
          pushInlineToast({ kind: 'success', title: 'восстановлено', message: 'код и ответ восстановлены из выбранной версии' });
          logEvent('version_restore', { task_id: task.task_id, version_id: bV.id });
        });
        actions.appendChild(restoreBtn);

        const diffArea = document.createElement('div');
        diffArea.className = 'tv2-card';
        diffArea.style.display = 'grid';
        diffArea.style.gap = '0.75rem';
        diffArea.appendChild(block);
        diffArea.appendChild(actions);

        diffCard.appendChild(diffArea);
      });

      arr.slice(0, 10).forEach((v) => {
        const item = document.createElement('div');
        item.className = 'tv2-history-item';
        const left = document.createElement('div');
        left.innerHTML = `<div style="font-weight:900;">${escapeHtml(v.kind || 'version')}</div><div class="tv2-history-meta">${escapeHtml(fmtTime(v.ts))}${v.note ? ' · ' + escapeHtml(v.note) : ''}</div>`;
        const right = document.createElement('div');
        right.style.display = 'flex';
        right.style.gap = '0.5rem';
        right.style.flexWrap = 'wrap';
        const applyBtn = document.createElement('button');
        applyBtn.type = 'button';
        applyBtn.className = 'tv2-btn';
        applyBtn.textContent = 'применить';
        applyBtn.addEventListener('click', () => {
          setCurrentCode(v.code || '');
          setCurrentAnswer(v.answer || '');
          saveDraftsForTask(task.task_id);
          pushInlineToast({ kind: 'success', title: 'версия', message: 'код и ответ применены' });
          logEvent('version_apply', { task_id: task.task_id, version_id: v.id });
        });
        right.appendChild(applyBtn);
        item.appendChild(left);
        item.appendChild(right);
        list.appendChild(item);
      });
    }

    return { el: wrap, render };
  }

  function makeTerminalComponent() {
    const wrap = document.createElement('div');
    wrap.className = 'tv2-panel tv2-panel-scroll';
    const title = document.createElement('h2');
    title.className = 'tv2-h1';
    title.textContent = 'терминал';
    const list = document.createElement('div');
    list.style.display = 'grid';
    list.style.gap = '0.65rem';
    wrap.appendChild(title);
    wrap.appendChild(list);

    function render() {
      list.innerHTML = '';
      if (State.lastRun) {
        const r = State.lastRun;
        const card = document.createElement('div');
        card.className = 'tv2-card';
        const ok = !!r.ok;
        card.innerHTML =
          `<div style="display:flex; justify-content:space-between; gap:.75rem; flex-wrap:wrap;">` +
          `<div style="font-weight:900;">${ok ? 'выполнено' : 'ошибка'}</div>` +
          `<div class="tv2-muted" style="font-family: var(--tv2-font-mono);">${escapeHtml(r.error || '')}</div>` +
          `</div>` +
          `<div class="tv2-muted" style="margin-top:.5rem; font-weight:900;">stdout</div>` +
          `<pre class="tv2-diff-pre" style="white-space:pre-wrap;">${escapeHtml((r.stdout || '').trim() || '(пусто)')}</pre>` +
          `<div class="tv2-muted" style="margin-top:.5rem; font-weight:900;">stderr</div>` +
          `<pre class="tv2-diff-pre" style="white-space:pre-wrap;">${escapeHtml((r.stderr || '').trim() || '(пусто)')}</pre>` +
          (r.details ? `<div class="tv2-muted" style="margin-top:.5rem; font-weight:900;">details</div><pre class="tv2-diff-pre" style="white-space:pre-wrap;">${escapeHtml(String(r.details).slice(0, 4000))}</pre>` : '');
        list.appendChild(card);
      } else {
        const empty = document.createElement('div');
        empty.className = 'tv2-card';
        empty.innerHTML = '<div class="tv2-muted">пока нет запусков. нажми «запустить код».</div>';
        list.appendChild(empty);
      }
    }

    return { el: wrap, render };
  }

  function makeAssistantComponent() {
    const wrap = document.createElement('div');
    wrap.className = 'tv2-panel tv2-panel-scroll';

    const title = document.createElement('h2');
    title.className = 'tv2-h1';
    title.textContent = 'помощник';

    const status = document.createElement('div');
    status.className = 'tv2-muted';
    status.style.marginTop = '-0.2rem';

    const hintRow = document.createElement('div');
    hintRow.className = 'tv2-chat-actions';

    const hint1 = document.createElement('button');
    hint1.type = 'button';
    hint1.className = 'tv2-btn';
    hint1.textContent = 'подсказка 1';
    const hint2 = hint1.cloneNode(true);
    hint2.textContent = 'подсказка 2';
    const hint3 = hint1.cloneNode(true);
    hint3.textContent = 'подсказка 3';

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'tv2-btn tv2-btn-danger';
    clearBtn.textContent = 'очистить чат';

    hintRow.appendChild(hint1);
    hintRow.appendChild(hint2);
    hintRow.appendChild(hint3);
    hintRow.appendChild(clearBtn);

    const list = document.createElement('div');
    list.className = 'tv2-chat-list';

    const composer = document.createElement('div');
    composer.className = 'tv2-chat-composer';
    const ta = document.createElement('textarea');
    ta.className = 'tv2-chat-input';
    ta.rows = 2;
    ta.placeholder = 'вопрос по условию / коду / ошибке...';
    ta.setAttribute('aria-label', 'сообщение помощнику');
    const send = document.createElement('button');
    send.type = 'button';
    send.className = 'tv2-btn';
    send.textContent = 'отправить';
    composer.appendChild(ta);
    composer.appendChild(send);

    wrap.appendChild(title);
    wrap.appendChild(status);
    wrap.appendChild(hintRow);
    wrap.appendChild(list);
    wrap.appendChild(composer);

    function getTaskId() {
      return (State.currentTask && State.currentTask.task_id) ? Number(State.currentTask.task_id) : null;
    }

    function readChat(taskId) {
      const raw = safeJsonParse(lsGet(LS.chat(taskId), '[]'), []);
      return Array.isArray(raw) ? raw : [];
    }

    function writeChat(taskId, arr) {
      lsSet(LS.chat(taskId), JSON.stringify(Array.isArray(arr) ? arr.slice(-60) : []));
    }

    function appendMsg(taskId, role, content) {
      const arr = readChat(taskId);
      arr.push({ role: role, content: String(content || ''), ts: nowMs() });
      writeChat(taskId, arr);
      render();
    }

    function render() {
      list.innerHTML = '';
      const task = State.currentTask;
      if (!task || !task.task_id) {
        list.innerHTML = '<div class="tv2-muted">задача не выбрана</div>';
        status.textContent = '—';
        return;
      }

      const llm = State.llmInfo;
      if (!llm) status.textContent = 'проверка подключения...';
      else {
        const isOk = !!(llm && llm.picked);
        status.textContent = isOk ? 'подключено' : 'помощник недоступен';
      }

      const arr = readChat(task.task_id);
      if (arr.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'tv2-card';
        empty.innerHTML = '<div class="tv2-muted">подсказки и чат привязаны к текущей задаче. начни с «подсказка 1» или задай вопрос.</div>';
        list.appendChild(empty);
        return;
      }

      arr.slice(-60).forEach((m) => {
        const item = document.createElement('div');
        item.className = `tv2-chat-msg ${m.role === 'user' ? 'is-user' : 'is-assistant'}`.trim();
        const head = document.createElement('div');
        head.className = 'tv2-chat-meta';
        head.textContent = `${m.role === 'user' ? 'ученик' : 'помощник'} · ${fmtTime(m.ts || nowMs())}`;
        const body = document.createElement('div');
        body.className = 'tv2-chat-bubble';
        body.textContent = String(m.content || '');
        item.appendChild(head);
        item.appendChild(body);
        list.appendChild(item);
      });
      list.scrollTop = list.scrollHeight;
    }

    async function fetchHint(level) {
      const taskId = getTaskId();
      if (!taskId) return;
      const lvl = clamp(Number(level) || 1, 1, 5);
      try {
        const res = await apiFetch(`/task/${encodeURIComponent(taskId)}/hint?level=${encodeURIComponent(String(lvl))}`, { method: 'GET' });
        appendMsg(taskId, 'assistant', `подсказка ${res.level}: ${res.hint}`);
      } catch (e) {
        pushInlineToast({ kind: 'error', title: 'подсказка', message: e.message });
      }
    }

    function buildSystemPrompt() {
      return [
        'ты — помощник в тренажёре по подготовке к егэ.',
        'нельзя раскрывать итоговый ответ целиком, даже если он известен.',
        'нужно помогать шагами: уточняющие вопросы, план решения, проверки, типичные ошибки.',
        'если ученик просит “дай ответ”, нужно отказать и предложить подсказку/проверку рассуждений.',
        'если в сообщении есть код/ошибка, сначала объясни причину, затем предложи правку.',
      ].join('\n');
    }

    function buildContextMessage() {
      const task = State.currentTask;
      if (!task) return '';
      const parts = [];
      parts.push(`контекст задачи:`);
      parts.push(`тип: ${State.taskType || task.task_type || '—'}`);
      parts.push(`id: ${task.task_id}`);
      if (task.task_number) parts.push(`номер: ${task.task_number}`);
      const cond = getTaskConditionText(task);
      if (cond) parts.push(`условие:\n${String(cond).slice(0, 9000)}`);
      try {
        const attached = parseAttachedFiles(task.attached_files || task.attachments || task.attached || null);
        if (attached && attached.length) {
          const names = attached
            .map(a => (a && (a.name || a.filename || a.path || a.file)) ? String(a.name || a.filename || a.path || a.file) : '')
            .filter(Boolean)
            .slice(0, 10);
          if (names.length) parts.push(`вложения:\n- ${names.join('\n- ')}`);
        }
      } catch (_) {}
      try {
        const code = getCurrentCode();
        if (code && code.trim()) parts.push(`код ученика:\n${String(code).slice(0, 8000)}`);
      } catch (_) {}
      try {
        const ans = getCurrentAnswer();
        if (ans && String(ans).trim()) parts.push(`ответ ученика:\n${String(ans).slice(0, 2000)}`);
      } catch (_) {}
      return parts.join('\n\n');
    }

    async function sendChat() {
      const taskId = getTaskId();
      if (!taskId) return;
      const text = String(ta.value || '').trim();
      if (!text) return;

      const llm = State.llmInfo;
      const picked = llm && llm.picked ? llm.picked : null;
      if (!picked) {
        pushInlineToast({ kind: 'error', title: 'помощник', message: 'помощник недоступен: llm не настроен на сервере' });
        return;
      }

      ta.value = '';
      appendMsg(taskId, 'user', text);

      const convo = readChat(taskId).filter(x => x && (x.role === 'user' || x.role === 'assistant'));
      const last = convo.slice(-16).map(m => ({ role: m.role, content: String(m.content || '').slice(0, 4000) }));

      const messages = [
        { role: 'system', content: buildSystemPrompt() },
        { role: 'user', content: buildContextMessage() },
        ...last
      ];

      send.disabled = true;
      const prevText = send.textContent;
      send.textContent = '...';
      try {
        const res = await apiFetch('/llm/chat', {
          method: 'POST',
          body: JSON.stringify({
            messages,
            temperature: 0.2,
            max_tokens: 700,
            task_id: taskId,
            task_type: State.taskType || null
          })
        });
        appendMsg(taskId, 'assistant', String(res.answer || '').trim() || '(пустой ответ)');
      } catch (e) {
        pushInlineToast({ kind: 'error', title: 'помощник', message: e.message });
      } finally {
        send.disabled = false;
        send.textContent = prevText;
      }
    }

    hint1.addEventListener('click', () => fetchHint(1));
    hint2.addEventListener('click', () => fetchHint(2));
    hint3.addEventListener('click', () => fetchHint(3));
    clearBtn.addEventListener('click', () => {
      const taskId = getTaskId();
      if (!taskId) return;
      writeChat(taskId, []);
      render();
      pushInlineToast({ kind: 'success', title: 'помощник', message: 'чат очищен для текущей задачи' });
    });

    send.addEventListener('click', () => sendChat());
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendChat();
      }
    });

    function loadForTask(taskId) {
      try {
        const id = Number(taskId);
        if (!Number.isFinite(id)) return;
        render();
      } catch (_) {}
    }

    return { el: wrap, render, loadForTask };
  }

  function createCanvasApi(canvas, taskIdGetter) {
    const ctx = canvas.getContext('2d');
    let dpr = window.devicePixelRatio || 1;
    let strokes = [];
    let drawing = false;
    let cur = null;
    let zoom = 1.0;
    let panX = 0; // css px
    let panY = 0; // css px
    let panning = false;
    let panStartSx = 0;
    let panStartSy = 0;
    let panStartPx = 0;
    let panStartPy = 0;

    function resize() {
      const rect = canvas.getBoundingClientRect();
      dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      redraw();
    }

    function getThemeBg() {
      const m = getTrainerThemeMode();
      const eff = effectiveTheme(m);
      return eff === 'light' ? 'rgba(255,255,255,0.95)' : 'rgba(14,16,21,0.95)';
    }

    function redraw() {
      // фон (в экранных координатах)
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = getThemeBg();
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // линии (в мировых координатах, с трансформацией вида)
      ctx.setTransform(dpr * zoom, 0, 0, dpr * zoom, dpr * panX, dpr * panY);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      strokes.forEach((s) => {
        ctx.strokeStyle = s.color;
        // толщина должна быть стабильной на экране (а не раздуваться при зуме)
        ctx.lineWidth = (s.width * dpr) / zoom;
        ctx.beginPath();
        s.points.forEach((p, idx) => {
          const x = p.x;
          const y = p.y;
          if (idx === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });

      ctx.setTransform(1, 0, 0, 1, 0, 0);
    }

    function save() {
      const tid = taskIdGetter();
      if (!tid) return;
      lsSet(LS.scratchCanvas(tid), JSON.stringify({ strokes }));
      logEvent('scratch_canvas_save', { task_id: tid, strokes: strokes.length });
    }

    function loadForTask(taskId) {
      const data = safeJsonParse(lsGet(LS.scratchCanvas(taskId), '{}'), {});
      strokes = Array.isArray(data.strokes) ? data.strokes : [];
      redraw();
    }

    function pointerPos(e) {
      const rect = canvas.getBoundingClientRect();
      const sx = (e.clientX - rect.left);
      const sy = (e.clientY - rect.top);
      const x = (sx - panX) / zoom;
      const y = (sy - panY) / zoom;
      return { x, y, sx, sy };
    }

    function onDown(e) {
      const pos = pointerPos(e);
      if (e.button === 2) {
        panning = true;
        panStartSx = pos.sx;
        panStartSy = pos.sy;
        panStartPx = panX;
        panStartPy = panY;
        canvas.style.cursor = 'grabbing';
        e.preventDefault();
        return;
      }
      drawing = true;
      const color = ($('#tv2CanvasColor') && $('#tv2CanvasColor').value) || '#00e0ff';
      const width = Number($('#tv2CanvasWidth') && $('#tv2CanvasWidth').value) || 2.5;
      cur = { color, width, points: [{ x: pos.x, y: pos.y }] };
      strokes.push(cur);
      redraw();
      e.preventDefault();
    }

    function onMove(e) {
      const pos = pointerPos(e);
      if (panning) {
        const dx = pos.sx - panStartSx;
        const dy = pos.sy - panStartSy;
        panX = panStartPx + dx;
        panY = panStartPy + dy;
        redraw();
        e.preventDefault();
        return;
      }
      if (!drawing || !cur) return;
      cur.points.push({ x: pos.x, y: pos.y });
      redraw();
      e.preventDefault();
    }

    function onUp(e) {
      if (panning) {
        panning = false;
        canvas.style.cursor = 'crosshair'; // default canvas cursor for drawing
        e.preventDefault();
        return;
      }
      if (!drawing) return;
      drawing = false;
      cur = null;
      save();
      e.preventDefault();
    }

    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    window.addEventListener('resize', () => resize());

    function clampZoom(z) { return clamp(z, 0.5, 3.0); }

    function setZoom(nextZoom, anchorSx, anchorSy) {
      const rect = canvas.getBoundingClientRect();
      const ax = Number.isFinite(anchorSx) ? anchorSx : rect.width / 2;
      const ay = Number.isFinite(anchorSy) ? anchorSy : rect.height / 2;
      const wx = (ax - panX) / zoom;
      const wy = (ay - panY) / zoom;
      zoom = clampZoom(Number(nextZoom) || 1.0);
      panX = ax - wx * zoom;
      panY = ay - wy * zoom;
      try { lsSet(LS.canvasZoomPct, String(Math.round(zoom * 100))); } catch (_) {}
      redraw();
    }

    function wheelZoom(e) {
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const delta = (e.deltaY || 0);
      const factor = delta > 0 ? 0.92 : 1.08;
      setZoom(zoom * factor, sx, sy);
      e.preventDefault();
    }

    canvas.addEventListener('wheel', wheelZoom, { passive: false });

    function loadZoomFromStorage() {
      const saved = Number(lsGet(LS.canvasZoomPct, ''));
      const legacy = Number(lsGet(LS.canvasScalePct, ''));
      const pct = Number.isFinite(saved) ? saved : (Number.isFinite(legacy) ? legacy : 100);
      setZoom(clamp(pct, 50, 300) / 100, null, null);
      // миграция legacy-ключа (best-effort)
      try {
        if (!Number.isFinite(saved) && Number.isFinite(legacy)) lsDel(LS.canvasScalePct);
      } catch (_) {}
    }

    setTimeout(() => { resize(); loadZoomFromStorage(); }, 0);

    return {
      resize,
      redraw,
      loadForTask,
      setZoomPct: (pct) => setZoom(clamp(Number(pct) || 100, 50, 300) / 100, null, null),
      getZoomPct: () => Math.round(zoom * 100),
      resetView: () => { zoom = 1.0; panX = 0; panY = 0; try { lsSet(LS.canvasZoomPct, '100'); } catch (_) {} redraw(); },
      undo: () => { strokes.pop(); redraw(); save(); },
      clear: () => { strokes = []; redraw(); save(); },
      exportPng: () => {
        const url = canvas.toDataURL('image/png');
        const a = document.createElement('a');
        a.href = url;
        a.download = `scratchpad_${taskIdGetter() || 'task'}.png`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
    };
  }

  function makeScratchpadComponent() {
    const wrap = document.createElement('div');
    wrap.className = 'tv2-panel tv2-panel-scroll';

    const title = document.createElement('h2');
    title.className = 'tv2-h1';
    title.textContent = 'черновик';

    const tabs = document.createElement('div');
    tabs.className = 'tv2-scratch-tabs';
    const tabMd = document.createElement('button');
    tabMd.type = 'button';
    tabMd.className = 'tv2-scratch-tab is-active';
    tabMd.textContent = 'markdown';
    const tabCanvas = document.createElement('button');
    tabCanvas.type = 'button';
    tabCanvas.className = 'tv2-scratch-tab';
    tabCanvas.textContent = 'доска';
    tabs.appendChild(tabMd);
    tabs.appendChild(tabCanvas);

    const mdWrap = document.createElement('div');
    mdWrap.className = 'tv2-card';
    const mdTa = document.createElement('textarea');
    mdTa.setAttribute('aria-label', 'scratchpad markdown');
    mdWrap.appendChild(mdTa);

    const canvasCard = document.createElement('div');
    canvasCard.className = 'tv2-card';
    canvasCard.style.display = 'none';
    canvasCard.style.gap = '0.75rem';

    const toolbar = document.createElement('div');
    toolbar.className = 'tv2-canvas-toolbar';

    const color = document.createElement('input');
    color.type = 'color';
    color.id = 'tv2CanvasColor';
    color.value = '#00e0ff';

    const width = document.createElement('input');
    width.type = 'range';
    width.id = 'tv2CanvasWidth';
    width.min = '1';
    width.max = '10';
    width.value = '3';

    const zoomWrap = document.createElement('div');
    zoomWrap.className = 'tv2-canvas-zoom';
    const zoomLabel = document.createElement('div');
    zoomLabel.className = 'tv2-canvas-zoom-label';
    zoomLabel.textContent = 'zoom: 100%';
    const zoomOut = document.createElement('button');
    zoomOut.type = 'button';
    zoomOut.className = 'tv2-btn';
    zoomOut.textContent = '−';
    const zoomIn = document.createElement('button');
    zoomIn.type = 'button';
    zoomIn.className = 'tv2-btn';
    zoomIn.textContent = '+';
    const zoomReset = document.createElement('button');
    zoomReset.type = 'button';
    zoomReset.className = 'tv2-btn';
    zoomReset.textContent = '100%';
    zoomWrap.appendChild(zoomLabel);
    zoomWrap.appendChild(zoomOut);
    zoomWrap.appendChild(zoomIn);
    zoomWrap.appendChild(zoomReset);

    const undoBtn = document.createElement('button');
    undoBtn.type = 'button';
    undoBtn.className = 'tv2-btn';
    undoBtn.textContent = 'undo';

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'tv2-btn tv2-btn-danger';
    clearBtn.textContent = 'clear';

    const exportBtn = document.createElement('button');
    exportBtn.type = 'button';
    exportBtn.className = 'tv2-btn';
    exportBtn.textContent = 'export png';

    toolbar.appendChild(color);
    toolbar.appendChild(width);
    toolbar.appendChild(zoomWrap);
    toolbar.appendChild(undoBtn);
    toolbar.appendChild(clearBtn);
    toolbar.appendChild(exportBtn);

    const cWrap = document.createElement('div');
    cWrap.className = 'tv2-canvas-wrap';
    const canvas = document.createElement('canvas');
    canvas.className = 'tv2-canvas';
    cWrap.appendChild(canvas);

    canvasCard.appendChild(toolbar);
    canvasCard.appendChild(cWrap);

    wrap.appendChild(title);
    wrap.appendChild(tabs);
    wrap.appendChild(mdWrap);
    wrap.appendChild(canvasCard);

    function setTab(name) {
      const isMd = name === 'md';
      tabMd.classList.toggle('is-active', isMd);
      tabCanvas.classList.toggle('is-active', !isMd);
      mdWrap.style.display = isMd ? 'block' : 'none';
      canvasCard.style.display = isMd ? 'none' : 'grid';
      if (!isMd && State.scratchCanvasApi) {
        State.scratchCanvasApi.resize();
        try { syncZoomLabel(); } catch (_) {}
      }
    }

    tabMd.addEventListener('click', () => setTab('md'));
    tabCanvas.addEventListener('click', () => setTab('canvas'));

    let mde = null;
    function mountMd() {
      if (mde) return mde;
      const eff = effectiveTheme(getTrainerThemeMode());
      mde = new EasyMDE({
        element: mdTa,
        spellChecker: false,
        status: false,
        autofocus: false,
        autoDownloadFontAwesome: false,
        toolbar: ['bold', 'italic', 'heading', '|', 'unordered-list', 'ordered-list', 'table', '|', 'preview', 'side-by-side', 'fullscreen'],
        renderingConfig: { singleLineBreaks: false, codeSyntaxHighlighting: false }
      });
      try { mde.codemirror.setOption('theme', eff === 'light' ? 'default' : 'dracula'); } catch (_) {}
      State.md = mde;

      let t = null;
      mde.codemirror.on('change', () => {
        const task = State.currentTask;
        if (!task) return;
        if (t) clearTimeout(t);
        t = setTimeout(() => {
          lsSet(LS.scratchMd(task.task_id), mde.value());
          logEvent('scratch_md_save', { task_id: task.task_id, len: mde.value().length });
        }, 650);
      });
      return mde;
    }

    const canvasApi = createCanvasApi(canvas, () => (State.currentTask && State.currentTask.task_id) || null);
    State.scratchCanvasApi = canvasApi;
    undoBtn.addEventListener('click', () => canvasApi.undo());
    clearBtn.addEventListener('click', () => canvasApi.clear());
    exportBtn.addEventListener('click', () => canvasApi.exportPng());

    function syncZoomLabel() {
      try {
        zoomLabel.textContent = `zoom: ${canvasApi.getZoomPct()}%`;
      } catch (_) {
        zoomLabel.textContent = 'zoom: —';
      }
    }

    zoomOut.addEventListener('click', () => {
      try { canvasApi.setZoomPct(canvasApi.getZoomPct() - 10); } catch (_) {}
      syncZoomLabel();
    });
    zoomIn.addEventListener('click', () => {
      try { canvasApi.setZoomPct(canvasApi.getZoomPct() + 10); } catch (_) {}
      syncZoomLabel();
    });
    zoomReset.addEventListener('click', () => {
      try { canvasApi.resetView(); } catch (_) {}
      syncZoomLabel();
    });

    // обновлять label после зума колёсиком
    canvas.addEventListener('wheel', () => setTimeout(syncZoomLabel, 0), { passive: true });
    setTimeout(syncZoomLabel, 0);

    // export markdown
    const exportMdBtn = document.createElement('button');
    exportMdBtn.type = 'button';
    exportMdBtn.className = 'tv2-btn';
    exportMdBtn.textContent = 'export md';
    exportMdBtn.addEventListener('click', () => {
      const task = State.currentTask;
      if (!task) return;
      const md = (State.md && State.md.value) ? State.md.value() : '';
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `scratchpad_${task.task_id}.md`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
    tabs.appendChild(exportMdBtn);

    return {
      el: wrap,
      mountMd,
      canvasApi
    };
  }

  async function openTaskById(taskId) {
    const id = Number(taskId);
    if (!Number.isFinite(id)) return;
    try {
      const res = await fetchTask(id);
      if (res && res.task) {
        setCurrentTask(res.task, { keepDrafts: true });
        pushInlineToast({ kind: 'success', title: 'возврат', message: `открыта задача id ${id}` });
      }
    } catch (e) {
      pushInlineToast({ kind: 'error', title: 'возврат', message: `не удалось открыть задачу: ${e.message}` });
    }
  }

  function initDockLite() {
    if (!dockEl) return;
    dockEl.innerHTML = '';

    const root = document.createElement('div');
    root.className = 'tv2-lite';

    const left = document.createElement('div');
    left.className = 'tv2-lite-left';
    const resizer = document.createElement('div');
    resizer.className = 'tv2-lite-resizer';
    const right = document.createElement('div');
    right.className = 'tv2-lite-right';

    // left: condition
    const condition = makeConditionComponent();
    State.conditionView = condition;
    left.appendChild(condition.el);

    // right top: editor
    const editorWrap = document.createElement('div');
    editorWrap.style.minHeight = '0';
    const editor = makeEditorComponent();
    State.editorView = editor;
    editorWrap.appendChild(editor.el);

    // vertical resizer between editor and bottom panel
    const vresizer = document.createElement('div');
    vresizer.className = 'tv2-lite-vresizer';

    // bottom: tabs + panels
    const bottom = document.createElement('div');
    bottom.className = 'tv2-lite-bottom';

    const tabs = document.createElement('div');
    tabs.className = 'tv2-lite-tabs';

    const panel = document.createElement('div');
    panel.className = 'tv2-lite-panel';

    const btns = [
      { id: 'terminal', label: 'терминал' },
      { id: 'черновик', label: 'черновик' },
      { id: 'история', label: 'история' },
      { id: 'проверка', label: 'проверка' },
      { id: 'помощник', label: 'помощник' }
    ];
    const btnMap = {};
    btns.forEach((b) => {
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'tv2-lite-tabbtn';
      x.textContent = b.label;
      x.setAttribute('data-tab', b.id);
      tabs.appendChild(x);
      btnMap[b.id] = x;
    });

    // create panels
    const terminal = makeTerminalComponent();
    State.terminalView = terminal;
    const scratch = makeScratchpadComponent();
    const history = makeHistoryComponent();
    State.historyView = history;
    const tests = makeTestsComponent();
    State.testsView = tests;
    const assistant = makeAssistantComponent();
    State.assistantView = assistant;

    const panes = {
      terminal: terminal.el,
      'черновик': scratch.el,
      'история': history.el,
      'проверка': tests.el,
      'помощник': assistant.el
    };

    function setTab(id) {
      Object.keys(btnMap).forEach((k) => btnMap[k].classList.toggle('is-active', k === id));
      panel.innerHTML = '';
      panel.appendChild(panes[id]);
      try {
        if (id === 'terminal') terminal.render();
        if (id === 'история') history.render();
        if (id === 'проверка') tests.render();
        if (id === 'черновик') scratch.mountMd();
        if (id === 'помощник') assistant.render();
      } catch (_) {}
      lsSet(LS.layout('dock_lite_active_tab'), id);
    }

    Object.keys(btnMap).forEach((k) => btnMap[k].addEventListener('click', () => setTab(k)));
    const initialTab = lsGet(LS.layout('dock_lite_active_tab'), 'terminal') || 'terminal';
    setTab(panes[initialTab] ? initialTab : 'terminal');

    bottom.appendChild(tabs);
    bottom.appendChild(panel);

    right.appendChild(editorWrap);
    right.appendChild(vresizer);
    right.appendChild(bottom);

    root.appendChild(left);
    root.appendChild(resizer);
    root.appendChild(right);
    dockEl.appendChild(root);

    // init editors after mount
    setTimeout(() => {
      try { editor.mountEditor(); } catch (_) {}
      try { condition.render(); } catch (_) {}
      if (State.currentTask) loadDraftsForTask(State.currentTask.task_id);
      try { if (State.editorView && State.editorView.updateAttemptsUI && State.currentTask) State.editorView.updateAttemptsUI(State.currentTask.task_id); } catch (_) {}
    }, 0);

    // horizontal resizer
    let isResizing = false;
    let startX = 0;
    let startLeftPx = 0;
    resizer.addEventListener('mousedown', (e) => {
      isResizing = true;
      startX = e.clientX;
      startLeftPx = left.getBoundingClientRect().width;
      document.body.style.cursor = 'col-resize';
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!isResizing) return;
      const dx = e.clientX - startX;
      const total = root.getBoundingClientRect().width;
      const nextPx = clamp(startLeftPx + dx, 240, total - 320);
      const pct = (nextPx / total) * 100;
      root.style.gridTemplateColumns = `minmax(240px, ${pct}%) 10px 1fr`;
      lsSet(LS.layout('dock_lite_left_pct'), String(pct));
    });
    window.addEventListener('mouseup', () => {
      if (!isResizing) return;
      isResizing = false;
      document.body.style.cursor = 'default';
    });

    // vertical resizer
    let isV = false;
    let startY = 0;
    let startTopPx = 0;
    vresizer.addEventListener('mousedown', (e) => {
      isV = true;
      startY = e.clientY;
      startTopPx = editorWrap.getBoundingClientRect().height;
      document.body.style.cursor = 'row-resize';
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!isV) return;
      const dy = e.clientY - startY;
      const total = right.getBoundingClientRect().height;
      const nextTop = clamp(startTopPx + dy, 220, total - 180);
      const bottomH = total - nextTop - 10;
      right.style.gridTemplateRows = `${nextTop}px 10px ${bottomH}px`;
      lsSet(LS.layout('dock_lite_editor_px'), String(nextTop));
    });
    window.addEventListener('mouseup', () => {
      if (!isV) return;
      isV = false;
      document.body.style.cursor = 'default';
    });

    // apply stored sizes
    const leftPct = Number(lsGet(LS.layout('dock_lite_left_pct'), ''));
    if (Number.isFinite(leftPct) && leftPct >= 15 && leftPct <= 75) {
      root.style.gridTemplateColumns = `minmax(240px, ${leftPct}%) 10px 1fr`;
    }
    const editorPx = Number(lsGet(LS.layout('dock_lite_editor_px'), ''));
    if (Number.isFinite(editorPx) && editorPx >= 220) {
      const total = right.getBoundingClientRect().height;
      const bottomH = Math.max(180, total - editorPx - 10);
      right.style.gridTemplateRows = `${editorPx}px 10px ${bottomH}px`;
    }

    // presets
    if (presetBtn) {
      const presets = [
        { name: 'стандарт', left: 40 },
        { name: 'код 80%', left: 20 },
        { name: 'условие 60%', left: 60 },
        { name: 'минимум', left: 50 }
      ];
      let idx = 0;
      const apply = () => {
        const p = presets[idx];
        root.style.gridTemplateColumns = `minmax(240px, ${p.left}%) 10px 1fr`;
        presetBtn.textContent = `пресет: ${p.name}`;
      };
      apply();
      presetBtn.onclick = () => {
        idx = (idx + 1) % presets.length;
        apply();
      };
    }
  }

  function initControls() {
    // passthrough task_type
    const pt = cfg.passthrough || {};
    if (pt.task_type) {
      const t = Number(pt.task_type);
      if (Number.isFinite(t) && t >= 1 && t <= 27) setTaskTypeInUI(t);
    } else {
      const last = Number(lsGet(LS.lastTaskType, ''));
      if (Number.isFinite(last) && last >= 1 && last <= 27) setTaskTypeInUI(last);
    }

    if (startBtn) {
      startBtn.addEventListener('click', () => {
        startFlow().catch((e) => {
          pushInlineToast({ kind: 'error', title: 'старт', message: e.message });
          logEvent('start_fail', { error: e.message });
        });
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        goNext().catch((e) => {
          pushInlineToast({ kind: 'error', title: 'следующее', message: e.message });
          logEvent('next_fail', { error: e.message });
        });
      });
    }

    if (storageHelpBtn) {
      storageHelpBtn.addEventListener('click', () => {
        pushInlineToast({
          kind: 'success',
          title: 'хранение данных',
          message: 'черновики, снапшоты, подсветки и заметки сохраняются локально в браузере (localStorage) и привязаны к пользователю и задаче. если открыть тренажёр в другом браузере/устройстве — данных там не будет.'
        });
      });
    }
  }

  function initFallbackLayout(reason) {
    if (!dockEl) return;
    dockEl.innerHTML = '';
    dockEl.style.height = 'min(78vh, 860px)';
    dockEl.style.background = 'transparent';

    const shell = document.createElement('div');
    shell.style.height = '100%';
    shell.style.display = 'grid';
    shell.style.gridTemplateColumns = 'minmax(260px, 40%) 1fr';
    shell.style.gap = '0';

    const left = document.createElement('div');
    left.style.minWidth = '0';
    left.style.borderRight = '1px solid var(--tv2-stroke-1)';
    const right = document.createElement('div');
    right.style.minWidth = '0';
    right.style.display = 'grid';
    right.style.gridTemplateRows = '1fr auto';
    right.style.minHeight = '0';

    const condition = makeConditionComponent();
    State.conditionView = condition;
    left.appendChild(condition.el);

    const editor = makeEditorComponent();
    State.editorView = editor;
    right.appendChild(editor.el);

    const terminalWrap = document.createElement('div');
    terminalWrap.style.borderTop = '1px solid var(--tv2-stroke-1)';
    terminalWrap.style.background = 'rgba(255,255,255,0.02)';
    terminalWrap.style.padding = '0.5rem';
    terminalWrap.style.display = 'grid';
    terminalWrap.style.gap = '0.5rem';

    const termToggle = document.createElement('button');
    termToggle.type = 'button';
    termToggle.className = 'tv2-btn';
    termToggle.textContent = 'терминал (показать)';

    const termBody = document.createElement('div');
    termBody.style.display = 'none';
    termBody.style.maxHeight = '260px';
    termBody.style.overflow = 'auto';

    const terminal = makeTerminalComponent();
    State.terminalView = terminal;
    termBody.appendChild(terminal.el);

    termToggle.addEventListener('click', () => {
      const open = termBody.style.display !== 'none';
      termBody.style.display = open ? 'none' : 'block';
      termToggle.textContent = open ? 'терминал (показать)' : 'терминал (скрыть)';
      if (!open) terminal.render();
    });

    terminalWrap.appendChild(termToggle);
    terminalWrap.appendChild(termBody);
    right.appendChild(terminalWrap);

    shell.appendChild(left);
    shell.appendChild(right);
    dockEl.appendChild(shell);

    setTimeout(() => {
      try { editor.mountEditor(); } catch (_) {}
      try { condition.render(); } catch (_) {}
      if (State.currentTask) loadDraftsForTask(State.currentTask.task_id);
      try { if (State.editorView && State.editorView.updateAttemptsUI && State.currentTask) State.editorView.updateAttemptsUI(State.currentTask.task_id); } catch (_) {}
    }, 0);

    pushInlineToast({
      kind: 'error',
      title: 'dock ui недоступен',
      message: `переключено на упрощённый режим (split). причина: ${reason || 'unknown'}`
    });

    logEvent('dock_fallback', { reason: String(reason || 'unknown') });

    // presets in fallback: cycle split ratio
    if (presetBtn) {
      const presets = [
        { name: 'стандарт', left: 40 },
        { name: 'код 80%', left: 20 },
        { name: 'условие 60%', left: 60 },
        { name: 'минимум', left: 50 }
      ];
      let idx = 0;
      const apply = () => {
        const p = presets[idx];
        shell.style.gridTemplateColumns = `minmax(260px, ${p.left}%) 1fr`;
        presetBtn.textContent = `пресет: ${p.name}`;
      };
      apply();
      presetBtn.onclick = () => {
        idx = (idx + 1) % presets.length;
        apply();
      };
    }
  }

  function loadPending() {
    const p = safeJsonParse(lsGet(LS.pending, '[]'), []);
    if (Array.isArray(p)) {
      // если страница была перезагружена во время in-flight — помечаем как lost (чтобы не повторять автоматически)
      p.forEach((x) => {
        if (x && x.status === 'sending') x.status = 'lost';
      });
      State.pending = p;
      lsSet(LS.pending, JSON.stringify(State.pending));
      updateQueueBadge();
    }
  }

  function bootstrap() {
    initEventLog();
    initVisited();
    loadPending();
    initThemeToggle();
    initZenToggle();
    initControls();
    initDockLite();
    updateStreakUI();

    loadGlossary().then(() => {
      if (State.conditionView) State.conditionView.render();
    });

    apiFetch('/llm/info', { method: 'GET' })
      .then((r) => { State.llmInfo = (r && r.llm) ? r.llm : null; try { if (State.assistantView && State.assistantView.render) State.assistantView.render(); } catch (_) {} })
      .catch(() => { State.llmInfo = { picked: null }; try { if (State.assistantView && State.assistantView.render) State.assistantView.render(); } catch (_) {} });

    // автозапуск, если task_type задан
    const pt = cfg.passthrough || {};
    if (pt.task_type || pt.task_id) {
      const t = pt.task_type ? Number(pt.task_type) : getTaskTypeFromUI();
      if (Number.isFinite(t) && t >= 1 && t <= 27) setTaskTypeInUI(t);
      startFlow().catch(() => {});
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bootstrap);
  else bootstrap();
})();

