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
  const queueInfoEl = document.getElementById('tv2QueueInfo');
  const zenBtn = document.getElementById('tv2ZenBtn');
  const inlineToastArea = document.getElementById('tv2InlineToastArea');

  const LS = {
    theme: 'trainer.themeMode',
    layout: (name) => `tv2.layout.${userId}.${name}`,
    preset: `tv2.preset.${userId}`,
    lastTaskType: `tv2.lastTaskType.${userId}`,
    visited: `tv2.visited.${userId}`,
    pending: `tv2.pending.${userId}`,
    code: (taskId) => `tv2.code.${userId}.${taskId}`,
    answer: (taskId) => `tv2.answer.${userId}.${taskId}`,
    highlights: (taskId) => `tv2.hl.${userId}.${taskId}`,
    scratchMd: (taskId) => `tv2.scratch.md.${userId}.${taskId}`,
    scratchCanvas: (taskId) => `tv2.scratch.canvas.${userId}.${taskId}`,
    versions: (taskId) => `tv2.versions.${userId}.${taskId}`,
    eventLog: `tv2.log.${userId}`
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

  async function apiFetch(path, opts) {
    const url = `${cfg.baseApi}${path}`;
    const headers = Object.assign({}, (opts && opts.headers) || {});
    headers['X-Trainer-Token'] = token;
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
    golden: null,
    glossary: null,
    cm: null,
    md: null,
    scratchCanvas: null,
    scratchCanvasApi: null,
    historyView: null,
    testsView: null,
    terminalView: null,
    conditionView: null,
    editorView: null
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
      if (isZen) url.searchParams.delete('zen');
      else url.searchParams.set('zen', '1');
      window.location.href = url.toString();
    });

    const exitBtn = document.getElementById('tv2ZenExitBtn');
    if (exitBtn) {
      exitBtn.addEventListener('click', () => {
        const url = new URL(window.location.href);
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
      const res = await fetch('/static/trainer_v2/glossary.json', { cache: 'no-store' });
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
    if (State.conditionView && typeof State.conditionView.render === 'function') State.conditionView.render();
    if (State.testsView && typeof State.testsView.render === 'function') State.testsView.render();
    if (State.historyView && typeof State.historyView.render === 'function') State.historyView.render();
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

    const sendBtn = document.createElement('button');
    sendBtn.type = 'button';
    sendBtn.className = 'tv2-btn';
    sendBtn.textContent = 'отправить (в фоне)';

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

    sendBtn.addEventListener('click', async () => {
      const task = State.currentTask;
      if (!task) return;
      const val = (ans.value || '').trim();
      if (!val) {
        pushInlineToast({ kind: 'error', title: 'проверка', message: 'сначала нужно ввести ответ' });
        return;
      }

      saveDraftsForTask(task.task_id);
      pushVersion(task.task_id, 'submit', 'отправка на проверку');

      const pendingId = makeId('p');
      const entry = {
        id: pendingId,
        taskId: task.task_id,
        taskType: task.task_number,
        answer: val,
        code: getCurrentCode(),
        createdAt: nowMs(),
        status: 'sending'
      };
      State.pending.unshift(entry);
      if (State.pending.length > 50) State.pending.splice(50);
      lsSet(LS.pending, JSON.stringify(State.pending));
      updateQueueBadge();
      if (State.testsView && typeof State.testsView.render === 'function') State.testsView.render();

      pushInlineToast({
        kind: 'success',
        title: 'проверка отправлена',
        message: 'можно переходить к следующей задаче; результат придёт в уведомлении'
      });

      logEvent('submit_async_start', { task_id: task.task_id, pending_id: pendingId });

      // переход к следующей задаче сразу
      goNext().catch((e) => {
        pushInlineToast({ kind: 'error', title: 'следующее', message: `не удалось открыть следующее задание: ${e.message}` });
      });

      // фоновая проверка
      try {
        const res = await submitAnswer({ taskId: entry.taskId, answer: entry.answer, timeSpentSec: timeSpentSec() });
        entry.status = 'done';
        entry.result = res;
        lsSet(LS.pending, JSON.stringify(State.pending));
        updateQueueBadge();

        const ok = !!res.is_correct;
        if (ok) {
          pushInlineToast({
            kind: 'success',
            title: 'проверка',
            message: `задача №${task.task_number} · верно · рейтинг: ${res.new_rating != null ? res.new_rating : '—'}`
          });
        } else {
          pushInlineToast({
            kind: 'error',
            title: 'проверка',
            message: `задача №${task.task_number} · неверно · можно вернуться и поправить`,
            actions: [
              { label: 'вернуться', onClick: () => openTaskById(entry.taskId) }
            ]
          });
        }

        logEvent('submit_async_done', { task_id: entry.taskId, is_correct: ok, new_rating: res.new_rating });
        if (State.testsView && typeof State.testsView.render === 'function') State.testsView.render();
      } catch (e) {
        entry.status = 'failed';
        entry.error = e.message;
        lsSet(LS.pending, JSON.stringify(State.pending));
        updateQueueBadge();
        pushInlineToast({
          kind: 'error',
          title: 'проверка',
          message: `ошибка проверки: ${e.message}`,
          actions: [{ label: 'вернуться', onClick: () => openTaskById(entry.taskId) }]
        });
        logEvent('submit_async_fail', { task_id: entry.taskId, error: e.message });
        if (State.testsView && typeof State.testsView.render === 'function') State.testsView.render();
      }
    });

    return {
      el: wrap,
      mountEditor,
      getAnswer,
      setAnswer
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
      const items = State.pending.slice(0, 20);
      const relevant = items.filter(p => p.taskId === task.task_id).slice(0, 6);
      if (relevant.length === 0) {
        const card = document.createElement('div');
        card.className = 'tv2-card';
        card.innerHTML = `<div class="tv2-muted">пока нет проверок для этой задачи</div>`;
        list.appendChild(card);
        return;
      }
      relevant.forEach((p) => {
        const card = document.createElement('div');
        card.className = 'tv2-card';
        const status = p.status;
        const head = document.createElement('div');
        head.style.display = 'flex';
        head.style.justifyContent = 'space-between';
        head.style.gap = '0.75rem';
        head.style.flexWrap = 'wrap';
        const left = document.createElement('div');
        left.innerHTML = `<div style="font-weight:900;">${escapeHtml(status)}</div><div class="tv2-muted">отправлено: ${escapeHtml(fmtTime(p.createdAt))}</div>`;
        const right = document.createElement('div');
        right.className = 'tv2-muted';
        right.style.fontFamily = 'var(--tv2-font-mono)';
        right.textContent = `id: ${p.id}`;
        head.appendChild(left);
        head.appendChild(right);
        card.appendChild(head);

        const body = document.createElement('div');
        body.style.marginTop = '0.6rem';
        body.style.display = 'grid';
        body.style.gap = '0.35rem';
        body.innerHTML = `<div class="tv2-muted">ответ: <span style="color:var(--tv2-text); font-weight:900;">${escapeHtml(p.answer || '')}</span></div>`;
        if (p.result) {
          body.innerHTML += `<div class="tv2-muted">вердикт: <span style="font-weight:900; color:${p.result.is_correct ? 'var(--tv2-success)' : 'var(--tv2-danger)'};">${p.result.is_correct ? 'верно' : 'неверно'}</span></div>`;
          body.innerHTML += `<div class="tv2-muted">ожидалось: <span style="color:var(--tv2-text); font-weight:900;">${escapeHtml(p.result.expected || '—')}</span></div>`;
          body.innerHTML += `<div class="tv2-muted">рейтинг: <span style="color:var(--tv2-text); font-weight:900;">${escapeHtml(p.result.new_rating != null ? p.result.new_rating : '—')}</span></div>`;
        }
        if (p.error) {
          body.innerHTML += `<div class="tv2-muted">ошибка: <span style="color:var(--tv2-danger); font-weight:900;">${escapeHtml(p.error)}</span></div>`;
        }
        card.appendChild(body);
        list.appendChild(card);
      });
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
    title.textContent = 'лог';
    const list = document.createElement('div');
    list.style.display = 'grid';
    list.style.gap = '0.65rem';
    wrap.appendChild(title);
    wrap.appendChild(list);

    function render() {
      list.innerHTML = '';
      const arr = State.eventLog.slice(-60).reverse();
      if (arr.length === 0) {
        list.innerHTML = '<div class="tv2-muted">лог пуст</div>';
        return;
      }
      arr.forEach((e) => {
        const card = document.createElement('div');
        card.className = 'tv2-card';
        card.innerHTML = `<div style="display:flex; justify-content:space-between; gap:.75rem; flex-wrap:wrap;">\n` +
          `<div style="font-weight:900;">${escapeHtml(e.kind)}</div>\n` +
          `<div class="tv2-muted" style="font-family: var(--tv2-font-mono);">${escapeHtml(fmtTime(e.ts))}</div>\n` +
          `</div>` +
          (e.payload ? `<pre class="tv2-diff-pre" style="white-space:pre-wrap; background: transparent; border:0; padding:.6rem 0 0 0;">${escapeHtml(JSON.stringify(e.payload, null, 2))}</pre>` : '');
        list.appendChild(card);
      });
    }

    return { el: wrap, render };
  }

  function createCanvasApi(canvas, taskIdGetter) {
    const ctx = canvas.getContext('2d');
    let dpr = window.devicePixelRatio || 1;
    let strokes = [];
    let drawing = false;
    let cur = null;

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
      ctx.save();
      ctx.scale(1, 1);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = getThemeBg();
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      strokes.forEach((s) => {
        ctx.strokeStyle = s.color;
        ctx.lineWidth = s.width * dpr;
        ctx.beginPath();
        s.points.forEach((p, idx) => {
          const x = p.x * dpr;
          const y = p.y * dpr;
          if (idx === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });
      ctx.restore();
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
      const x = (e.clientX - rect.left);
      const y = (e.clientY - rect.top);
      return { x, y };
    }

    function onDown(e) {
      drawing = true;
      const pos = pointerPos(e);
      const color = ($('#tv2CanvasColor') && $('#tv2CanvasColor').value) || '#00e0ff';
      const width = Number($('#tv2CanvasWidth') && $('#tv2CanvasWidth').value) || 2.5;
      cur = { color, width, points: [{ x: pos.x, y: pos.y }] };
      strokes.push(cur);
      redraw();
      e.preventDefault();
    }

    function onMove(e) {
      if (!drawing || !cur) return;
      const pos = pointerPos(e);
      cur.points.push({ x: pos.x, y: pos.y });
      redraw();
      e.preventDefault();
    }

    function onUp(e) {
      if (!drawing) return;
      drawing = false;
      cur = null;
      save();
      e.preventDefault();
    }

    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    window.addEventListener('resize', () => resize());

    setTimeout(resize, 0);

    return {
      resize,
      redraw,
      loadForTask,
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
      if (!isMd && State.scratchCanvasApi) State.scratchCanvasApi.resize();
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

  function defaultLayoutConfig() {
    return {
      settings: {
        hasHeaders: true,
        constrainDragToContainer: true,
        reorderEnabled: true,
        selectionEnabled: false,
        popoutWholeStack: false,
        blockedPopoutsThrowError: true,
        closePopoutsOnUnload: true,
        showPopoutIcon: false,
        showMaximiseIcon: true,
        showCloseIcon: false
      },
      dimensions: {
        borderWidth: 6,
        minItemHeight: 120,
        minItemWidth: 220,
        headerHeight: 30,
        dragProxyWidth: 300,
        dragProxyHeight: 200
      },
      content: []
    };
  }

  function presetLayouts() {
    const base = defaultLayoutConfig();
    const mk = (content) => Object.assign({}, base, { content });
    const stackRight = {
      type: 'stack',
      content: [
        { type: 'component', componentName: 'scratchpad', title: 'черновик' },
        { type: 'component', componentName: 'history', title: 'история' },
        { type: 'component', componentName: 'tests', title: 'проверка' },
        { type: 'component', componentName: 'terminal', title: 'лог' }
      ]
    };

    return {
      standard: mk([{
        type: 'row',
        content: [
          { type: 'component', componentName: 'condition', title: 'условие', width: 38 },
          {
            type: 'column',
            width: 62,
            content: [
              { type: 'component', componentName: 'editor', title: 'редактор/ответ', height: 60 },
              stackRight
            ]
          }
        ]
      }]),
      code80: mk([{
        type: 'row',
        content: [
          { type: 'component', componentName: 'condition', title: 'условие', width: 20 },
          {
            type: 'column',
            width: 80,
            content: [
              { type: 'component', componentName: 'editor', title: 'редактор/ответ', height: 68 },
              stackRight
            ]
          }
        ]
      }]),
      condition60: mk([{
        type: 'row',
        content: [
          { type: 'component', componentName: 'condition', title: 'условие', width: 60 },
          {
            type: 'column',
            width: 40,
            content: [
              { type: 'component', componentName: 'editor', title: 'редактор/ответ', height: 58 },
              stackRight
            ]
          }
        ]
      }]),
      minimum: mk([{
        type: 'row',
        content: [
          { type: 'component', componentName: 'condition', title: 'условие', width: 50 },
          { type: 'component', componentName: 'editor', title: 'редактор/ответ', width: 50 }
        ]
      }]),
      zen: (function() {
        const z = defaultLayoutConfig();
        z.settings.hasHeaders = false;
        z.settings.showMaximiseIcon = false;
        z.settings.showPopoutIcon = false;
        z.settings.showCloseIcon = false;
        z.dimensions.headerHeight = 0;
        z.content = [{
          type: 'row',
          content: [
            { type: 'component', componentName: 'condition', title: 'условие', width: 55 },
            { type: 'component', componentName: 'editor', title: 'редактор/ответ', width: 45 }
          ]
        }];
        return z;
      })()
    };
  }

  function initDockLayout() {
    if (!dockEl) return;
    const presets = presetLayouts();
    if (cfg.zenMode === true) {
      State.layoutName = 'zen';
    } else {
      const savedPreset = (lsGet(LS.preset, 'standard') || 'standard').trim();
      State.layoutName = presets[savedPreset] ? savedPreset : 'standard';
    }

    function buildLayoutConfig() {
      const stored = safeJsonParse(lsGet(LS.layout(State.layoutName), 'null'), null);
      if (stored && typeof stored === 'object' && Array.isArray(stored.content) && stored.content.length) return stored;
      return presets[State.layoutName];
    }

    function mount(config) {
      dockEl.innerHTML = '';
      const gl = new GoldenLayout(config, dockEl);

      gl.registerComponent('condition', (container) => {
        const comp = makeConditionComponent();
        State.conditionView = comp;
        container.getElement().append(comp.el);
        setTimeout(() => comp.render(), 0);
      });

      gl.registerComponent('editor', (container) => {
        const comp = makeEditorComponent();
        State.editorView = comp;
        container.getElement().append(comp.el);
        setTimeout(() => {
          comp.mountEditor();
          if (State.currentTask) loadDraftsForTask(State.currentTask.task_id);
        }, 0);
      });

      gl.registerComponent('scratchpad', (container) => {
        const comp = makeScratchpadComponent();
        container.getElement().append(comp.el);
        setTimeout(() => {
          comp.mountMd();
          if (State.currentTask) {
            const md = lsGet(LS.scratchMd(State.currentTask.task_id), '');
            try { if (State.md) State.md.value(md || ''); } catch (_) {}
            try { if (State.scratchCanvasApi) State.scratchCanvasApi.loadForTask(State.currentTask.task_id); } catch (_) {}
          }
        }, 0);
      });

      gl.registerComponent('history', (container) => {
        const comp = makeHistoryComponent();
        State.historyView = comp;
        container.getElement().append(comp.el);
        setTimeout(() => comp.render(), 0);
      });

      gl.registerComponent('tests', (container) => {
        const comp = makeTestsComponent();
        State.testsView = comp;
        container.getElement().append(comp.el);
        setTimeout(() => comp.render(), 0);
      });

      gl.registerComponent('terminal', (container) => {
        const comp = makeTerminalComponent();
        State.terminalView = comp;
        container.getElement().append(comp.el);
        setTimeout(() => comp.render(), 0);
      });

      gl.on('stateChanged', () => {
        try {
          const st = gl.toConfig();
          lsSet(LS.layout(State.layoutName), JSON.stringify(st));
        } catch (_) {}
      });

      gl.init();
      State.golden = gl;
    }

    mount(buildLayoutConfig());

    // preset button
    const order = ['standard', 'code80', 'condition60', 'minimum'];
    function presetLabel(name) {
      if (name === 'standard') return 'пресет: стандарт';
      if (name === 'code80') return 'пресет: код 80%';
      if (name === 'condition60') return 'пресет: условие 60%';
      if (name === 'minimum') return 'пресет: минимум';
      return 'пресет';
    }
    if (presetBtn) {
      presetBtn.textContent = presetLabel(State.layoutName);
      presetBtn.addEventListener('click', () => {
        if (cfg.zenMode === true) return;
        const idx = order.indexOf(State.layoutName);
        const next = order[(idx + 1) % order.length];
        State.layoutName = next;
        lsSet(LS.preset, next);
        presetBtn.textContent = presetLabel(next);
        mount(buildLayoutConfig());
        logEvent('preset_change', { preset: next });
      });
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

    const condition = makeConditionComponent();
    State.conditionView = condition;
    left.appendChild(condition.el);

    const editor = makeEditorComponent();
    State.editorView = editor;
    right.appendChild(editor.el);

    shell.appendChild(left);
    shell.appendChild(right);
    dockEl.appendChild(shell);

    setTimeout(() => {
      try { editor.mountEditor(); } catch (_) {}
      try { condition.render(); } catch (_) {}
      if (State.currentTask) loadDraftsForTask(State.currentTask.task_id);
    }, 0);

    pushInlineToast({
      kind: 'error',
      title: 'dock ui недоступен',
      message: `переключено на упрощённый режим (split). причина: ${reason || 'unknown'}`
    });

    logEvent('dock_fallback', { reason: String(reason || 'unknown') });
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
    try {
      if (typeof window.GoldenLayout === 'function') initDockLayout();
      else initFallbackLayout('goldenlayout_not_loaded');
    } catch (e) {
      initFallbackLayout(e && e.message ? e.message : 'goldenlayout_init_failed');
    }

    loadGlossary().then(() => {
      if (State.conditionView) State.conditionView.render();
    });

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

