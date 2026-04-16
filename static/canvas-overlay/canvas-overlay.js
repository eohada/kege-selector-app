/**
 * BooCanvasOverlay — рисование поверх интерфейса платформы.
 * Привязка к конкретному заданию (task_id + context).
 * Сохранение штрихов на сервер, доступ для преподавателя.
 *
 * API:
 *   window.BooCanvasOverlay.open()
 *   window.BooCanvasOverlay.close()
 *   window.BooCanvasOverlay.toggle()
 *   window.BooCanvasOverlay.setContext(taskId, contextType, contextId)
 */
(function () {
  'use strict';

  const COLOR_PRESETS = [
    '#ef4444', '#f97316', '#eab308',
    '#22c55e', '#3b82f6', '#8b5cf6',
    '#ec4899', '#06b6d4', '#000000',
  ];

  let isOpen = false;
  let taskId = null;
  let contextType = 'submission';
  let contextId = null;

  let overlay = null;
  let canvas = null;
  let ctx = null;
  let toolbar = null;
  let fab = null;
  let fabBadge = null;

  let dpr = 1;
  let strokes = [];
  let redoStack = [];
  let drawing = false;
  let currentStroke = null;
  let tool = 'pen'; // 'pen' | 'eraser'
  let penColor = '#ef4444';
  let penSize = 3;
  let dirty = false;
  let saveTimer = null;
  let pendingSavePromise = null;

  function storageKey() {
    if (!taskId) return null;
    return `boo.canvas.${contextType || 'submission'}.${contextId || 'none'}.${taskId}`;
  }

  function saveLocal() {
    const key = storageKey();
    if (!key) return;
    try {
      localStorage.setItem(key, JSON.stringify(strokes));
    } catch (_) {}
  }

  function loadLocal() {
    const key = storageKey();
    if (!key) return null;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  // Toolbar drag state
  let tbDragging = false;
  let tbDragStart = { x: 0, y: 0, left: 0, top: 0 };

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  function init() {
    if (overlay) return;
    createFab();
    createOverlay();
    createToolbar();

    window.addEventListener('resize', resizeCanvas);
    document.addEventListener('keydown', onKeyDown);
  }

  function createFab() {
    fab = document.createElement('button');
    fab.className = 'boo-canvas-fab';
    fab.type = 'button';
    fab.title = 'Заметки (рисование)';
    fab.innerHTML = '<i class="ph-bold ph-pencil-line"></i>';
    fabBadge = document.createElement('div');
    fabBadge.className = 'fab-badge';
    fabBadge.style.display = 'none';
    fab.appendChild(fabBadge);
    fab.addEventListener('click', toggle);
    document.body.appendChild(fab);
    syncFabVisibility();
  }

  function createOverlay() {
    overlay = document.createElement('div');
    overlay.className = 'boo-canvas-overlay';
    canvas = document.createElement('canvas');
    overlay.appendChild(canvas);
    document.body.appendChild(overlay);

    ctx = canvas.getContext('2d');

    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointercancel', onPointerUp);
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  function createToolbar() {
    toolbar = document.createElement('div');
    toolbar.className = 'boo-canvas-toolbar';

    // Drag handle
    toolbar.addEventListener('pointerdown', onToolbarDragStart);

    // Pen button
    const penBtn = mkBtn('ph-pencil-simple', 'Карандаш', () => setTool('pen'));
    penBtn.id = 'boo-tb-pen';
    penBtn.classList.add('active');
    toolbar.appendChild(penBtn);

    // Eraser button
    const eraserBtn = mkBtn('ph-eraser', 'Ластик', () => setTool('eraser'));
    eraserBtn.id = 'boo-tb-eraser';
    toolbar.appendChild(eraserBtn);

    toolbar.appendChild(mkSep());

    // Color presets
    const presets = document.createElement('div');
    presets.className = 'tb-color-presets';
    COLOR_PRESETS.forEach(c => {
      const s = document.createElement('div');
      s.className = 'tb-color-swatch';
      s.style.background = c;
      s.title = c;
      s.addEventListener('click', () => {
        penColor = c;
        colorInput.value = c;
        setTool('pen');
      });
      presets.appendChild(s);
    });
    toolbar.appendChild(presets);

    // Custom color
    const colorInput = document.createElement('input');
    colorInput.type = 'color';
    colorInput.className = 'tb-color-picker';
    colorInput.value = penColor;
    colorInput.title = 'Произвольный цвет';
    colorInput.addEventListener('input', (e) => {
      penColor = e.target.value;
      setTool('pen');
    });
    toolbar.appendChild(colorInput);

    toolbar.appendChild(mkSep());

    // Size slider
    const sizeLabel = document.createElement('div');
    sizeLabel.className = 'tb-size-label';
    sizeLabel.textContent = penSize + 'px';
    toolbar.appendChild(sizeLabel);

    const sizeSlider = document.createElement('input');
    sizeSlider.type = 'range';
    sizeSlider.className = 'tb-size-slider';
    sizeSlider.min = '1';
    sizeSlider.max = '20';
    sizeSlider.value = String(penSize);
    sizeSlider.addEventListener('input', (e) => {
      penSize = Number(e.target.value);
      sizeLabel.textContent = penSize + 'px';
    });
    toolbar.appendChild(sizeSlider);

    toolbar.appendChild(mkSep());

    // Undo
    toolbar.appendChild(mkBtn('ph-arrow-counter-clockwise', 'Отменить (Ctrl+Z)', undo));
    // Redo
    toolbar.appendChild(mkBtn('ph-arrow-clockwise', 'Вернуть (Ctrl+Y)', redo));
    // Clear
    toolbar.appendChild(mkBtn('ph-trash', 'Очистить всё', clearAll));

    toolbar.appendChild(mkSep());

    // Save
    toolbar.appendChild(mkBtn('ph-floppy-disk', 'Сохранить', () => saveToServer()));

    // Close
    const closeBtn = mkBtn('ph-x', 'Закрыть', close);
    closeBtn.style.color = 'var(--error, #ef4444)';
    toolbar.appendChild(closeBtn);

    document.body.appendChild(toolbar);
    toolbar.style.display = 'none';
  }

  function mkBtn(icon, title, handler) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tb-btn';
    btn.title = title;
    btn.innerHTML = `<i class="ph-bold ${icon}"></i>`;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      handler();
    });
    return btn;
  }

  function mkSep() {
    const d = document.createElement('div');
    d.className = 'tb-separator';
    return d;
  }

  function setTool(t) {
    tool = t;
    const penBtn = document.getElementById('boo-tb-pen');
    const eraserBtn = document.getElementById('boo-tb-eraser');
    if (penBtn) penBtn.classList.toggle('active', t === 'pen');
    if (eraserBtn) eraserBtn.classList.toggle('active', t === 'eraser');
    canvas.style.cursor = t === 'eraser' ? 'cell' : 'crosshair';
  }

  // --- Drawing ---

  function resizeCanvas() {
    if (!canvas) return;
    const doc = document.documentElement;
    const body = document.body;
    const width = Math.max(
      doc ? doc.scrollWidth : 0,
      doc ? doc.clientWidth : 0,
      body ? body.scrollWidth : 0,
      body ? body.clientWidth : 0,
      window.innerWidth || 0
    );
    const height = Math.max(
      doc ? doc.scrollHeight : 0,
      doc ? doc.clientHeight : 0,
      body ? body.scrollHeight : 0,
      body ? body.clientHeight : 0,
      window.innerHeight || 0
    );
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    if (overlay) {
      overlay.style.width = width + 'px';
      overlay.style.height = height + 'px';
    }
    redraw();
  }

  function redraw() {
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    strokes.forEach(s => drawStroke(s));
  }

  function drawStroke(s) {
    if (!s.points || s.points.length < 1) return;
    ctx.save();
    if (s.eraser) {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.strokeStyle = 'rgba(0,0,0,1)';
    } else {
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = s.color || '#000';
    }
    ctx.lineWidth = s.width || 3;
    ctx.beginPath();
    s.points.forEach((p, i) => {
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.stroke();
    ctx.restore();
  }

  function pointerPos(e) {
    return { x: e.pageX, y: e.pageY };
  }

  function onPointerDown(e) {
    if (e.button !== 0) return;
    resizeCanvas();
    drawing = true;
    const pos = pointerPos(e);
    currentStroke = {
      color: tool === 'eraser' ? null : penColor,
      width: tool === 'eraser' ? penSize * 3 : penSize,
      eraser: tool === 'eraser',
      points: [pos],
    };
    strokes.push(currentStroke);
    redoStack = [];
    redraw();
    e.preventDefault();
  }

  function onPointerMove(e) {
    if (!drawing || !currentStroke) return;
    currentStroke.points.push(pointerPos(e));
    redraw();
    e.preventDefault();
  }

  function onPointerUp(e) {
    if (!drawing) return;
    drawing = false;
    currentStroke = null;
    dirty = true;
    saveLocal();
    scheduleSave();
    e.preventDefault();
  }

  function undo() {
    if (!strokes.length) return;
    redoStack.push(strokes.pop());
    dirty = true;
    redraw();
    saveLocal();
    scheduleSave();
  }

  function redo() {
    if (!redoStack.length) return;
    strokes.push(redoStack.pop());
    dirty = true;
    redraw();
    saveLocal();
    scheduleSave();
  }

  function clearAll() {
    if (!strokes.length) return;
    if (!confirm('Очистить все заметки?')) return;
    strokes = [];
    redoStack = [];
    dirty = true;
    redraw();
    saveLocal();
    scheduleSave();
  }

  // --- Persistence ---

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveToServer(), 3000);
  }

  async function saveToServer() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    if (!taskId) return;
    if (!dirty && strokes.length === 0) return;

    const body = {
      task_id: taskId,
      context_type: contextType,
      context_id: contextId,
      strokes: strokes,
    };

    pendingSavePromise = (async () => {
      try {
        await fetch('/api/canvas/save', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify(body),
        });
        dirty = false;
        saveLocal();
        updateBadge();
      } catch (e) {
        console.warn('Canvas save failed:', e);
      } finally {
        pendingSavePromise = null;
      }
    })();
    await pendingSavePromise;
  }

  async function waitPendingSave() {
    if (pendingSavePromise) {
      try {
        await pendingSavePromise;
      } catch (_) {}
    }
  }

  async function loadFromServer() {
    if (!taskId) { strokes = []; redraw(); return; }
    const localStrokes = loadLocal();
    if (Array.isArray(localStrokes)) {
      strokes = localStrokes;
      redraw();
      updateBadge();
    }
    await waitPendingSave();
    try {
      const params = new URLSearchParams({ task_id: taskId, context_type: contextType });
      if (contextId) params.set('context_id', contextId);
      const res = await fetch('/api/canvas/load?' + params.toString(), {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const data = await res.json();
      if (data.success && data.strokes) {
        const parsed = typeof data.strokes === 'string' ? JSON.parse(data.strokes) : data.strokes;
        if (Array.isArray(parsed) && (parsed.length > 0 || !Array.isArray(localStrokes))) {
          strokes = parsed;
        } else if (!Array.isArray(localStrokes)) {
          strokes = [];
        }
      } else if (!Array.isArray(localStrokes)) {
        strokes = [];
      }
    } catch (e) {
      if (!Array.isArray(localStrokes)) {
        strokes = [];
      }
    }
    redoStack = [];
    dirty = false;
    saveLocal();
    redraw();
    updateBadge();
  }

  function updateBadge() {
    if (fabBadge) {
      fabBadge.style.display = strokes.length > 0 ? '' : 'none';
    }
  }

  // --- Open/Close ---

  async function open() {
    if (isOpen || !hasValidContext()) return;
    isOpen = true;
    resizeCanvas();
    overlay.classList.add('active');
    toolbar.style.display = '';
    fab.style.display = 'none';
    await loadFromServer();
  }

  function close() {
    if (!isOpen) return;
    if (dirty) {
      saveToServer();
    }
    isOpen = false;
    overlay.classList.remove('active');
    toolbar.style.display = 'none';
    fab.style.display = '';
    drawing = false;
    currentStroke = null;
    syncFabVisibility();
  }

  function toggle() {
    if (!hasValidContext()) return;
    if (isOpen) close(); else open();
  }

  function setContext(tid, ctype, cid) {
    const normalizedTaskId = Number.isFinite(Number(tid)) && Number(tid) > 0 ? Number(tid) : null;
    const normalizedContextId = Number.isFinite(Number(cid)) && Number(cid) > 0 ? Number(cid) : null;
    const changed = normalizedTaskId !== taskId || ctype !== contextType || normalizedContextId !== contextId;
    taskId = normalizedTaskId;
    contextType = ctype || 'submission';
    contextId = normalizedContextId;
    syncFabVisibility();
    if (!hasValidContext() && isOpen) {
      close();
      strokes = [];
      redoStack = [];
      redraw();
      updateBadge();
      return;
    }
    if (changed && isOpen) loadFromServer();
    if (changed && !isOpen) {
      checkExistingDrawing();
    }
  }

  function hasValidContext() {
    return Number.isFinite(taskId) && taskId > 0;
  }

  function syncFabVisibility() {
    if (!fab) return;
    fab.style.display = hasValidContext() ? '' : 'none';
  }

  async function checkExistingDrawing() {
    if (!taskId) { updateBadge(); return; }
    await waitPendingSave();
    try {
      const params = new URLSearchParams({ task_id: taskId, context_type: contextType });
      if (contextId) params.set('context_id', contextId);
      const res = await fetch('/api/canvas/load?' + params.toString(), {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const data = await res.json();
      if (data.success && data.exists) {
        const parsed = typeof data.strokes === 'string' ? JSON.parse(data.strokes) : data.strokes;
        strokes = Array.isArray(parsed) ? parsed : [];
      } else {
        const localStrokes = loadLocal();
        strokes = Array.isArray(localStrokes) ? localStrokes : [];
      }
      saveLocal();
      updateBadge();
    } catch (_) {}
  }

  // --- Keyboard ---

  function onKeyDown(e) {
    if (!isOpen) return;
    if (e.key === 'Escape') { close(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) { undo(); e.preventDefault(); }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { redo(); e.preventDefault(); }
  }

  // --- Toolbar drag ---

  function onToolbarDragStart(e) {
    if (e.target.closest('.tb-btn, input, .tb-color-swatch')) return;
    tbDragging = true;
    toolbar.classList.add('dragging');
    tbDragStart = {
      x: e.clientX,
      y: e.clientY,
      left: toolbar.offsetLeft,
      top: toolbar.offsetTop,
    };
    toolbar.setPointerCapture(e.pointerId);
    const onMove = (ev) => {
      if (!tbDragging) return;
      const dx = ev.clientX - tbDragStart.x;
      const dy = ev.clientY - tbDragStart.y;
      toolbar.style.left = (tbDragStart.left + dx) + 'px';
      toolbar.style.top = (tbDragStart.top + dy) + 'px';
      toolbar.style.transform = 'none';
    };
    const onUp = () => {
      tbDragging = false;
      toolbar.classList.remove('dragging');
      toolbar.removeEventListener('pointermove', onMove);
      toolbar.removeEventListener('pointerup', onUp);
    };
    toolbar.addEventListener('pointermove', onMove);
    toolbar.addEventListener('pointerup', onUp);
    e.preventDefault();
  }

  // --- Auto-init ---

  function autoDetectContext() {
    const body = document.body;
    const tid = body.dataset.canvasTaskId;
    const ctype = body.dataset.canvasContextType;
    const cid = body.dataset.canvasContextId;
    if (tid) {
      setContext(Number(tid), ctype || 'submission', cid ? Number(cid) : null);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { init(); autoDetectContext(); });
  } else {
    init();
    autoDetectContext();
  }

  window.BooCanvasOverlay = { open, close, toggle, setContext };
})();
