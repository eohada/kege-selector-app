/**
 * BooStudy Whiteboard OS — полнофункциональная интерактивная доска для уроков и домашних заданий.
 *
 * Возможности:
 * - Все типы выделения: одиночное, множественное, прямоугольное (Marquee), произвольное (Lasso).
 * - Трансформация: перемещение, масштабирование (8 handles), свободный поворот (rotation handle), отражение (flip).
 * - Рисование: карандаш, перо, кисть, маркер-хайлайтер, стирание штрихов / объектов, лазерная указка с затуханием, пипетка.
 * - Стилизация: сплошные, пунктирные, штриховые линии, сглаживание, сила нажатия, скетч-стиль с вибрацией, автовыпрямление и автоопределение фигур.
 * - Библиотека фигур 2D и 3D: прямоугольники, эллипсы, треугольники, ромб, трапеция, многоугольник, звезда, облако, скобки, куб, цилиндр, конус, пирамида, выноски, блок-схемы, графы, умные соединители.
 * - Геометрические инструменты: интерактивная линейка (см/мм), транспортир (0-180°), циркуль, координатные оси и сетка, точки с координатами.
 * - Текст и формулы: типографика, Markdown, редактор LaTeX с формулами (KaTeX) и быстрой палитрой математических символов.
 * - Информатика и STEM: таблицы истинности, симулятор логических схем (AND/OR/NOT/XOR), двоичный калькулятор и перевод систем счисления, графы (Дейкстра, BFS, DFS), деревья Фано, Черепаха, построение графиков функций y=f(x), числовые прямые.
 * - Интерактивные карточки: стикеры Miro, флеш-карточки (3D flip), спойлеры со скрытым ответом, чек-листы, счётчики, таймеры, кубик/ГСЧ.
 * - Медиа: вставка картинок (Ctrl+V, Drag & Drop, URL), поворот, прозрачность, снимок области холста, экспорт в PNG/SVG/PDF/JSON.
 * - Холст: многостраничность, сетки (в точку, клетка, линейка, миллиметровка, координатная), интерактивная миникарта, полноэкранный режим.
 * - Каталог инструментов (Ctrl+K) с категоризацией и поиском.
 */
(function () {
  'use strict';

  // Do not initialize whiteboard overlay in embedded answer window
  if (typeof window !== 'undefined') {
    if (window.location.search.includes('embedded=answer') ||
        document.body?.classList.contains('tw-embedded-answer') ||
        document.documentElement?.classList.contains('tw-embedded-answer')) {
      return;
    }
  }

  // --- Palettes & Constants ---
  const COLOR_PRESETS = [
    '#0f172a', '#6366f1', '#3b82f6', '#06b6d4',
    '#10b981', '#84cc16', '#f59e0b', '#ef4444',
    '#ec4899', '#8b5cf6', '#64748b', '#ffffff'
  ];

  const HIGHLIGHTER_COLORS = [
    '#fef08a', '#bbf7d0', '#bfdbfe', '#fbcfe8', '#fed7aa', '#ddd6fe'
  ];

  const NOTE_THEMES = [
    { id: 'yellow', color: '#fef08a', name: 'Жёлтый' },
    { id: 'purple', color: '#ede9fe', name: 'Фиолетовый' },
    { id: 'blue', color: '#dbeafe', name: 'Синий' },
    { id: 'green', color: '#dcfce7', name: 'Зелёный' },
    { id: 'pink', color: '#fce7f3', name: 'Розовый' },
    { id: 'orange', color: '#ffedd5', name: 'Оранжевый' }
  ];

  const SIZE_PRESETS = [
    { size: 2, label: '2px', dot: 3, name: 'Тонкая' },
    { size: 4, label: '4px', dot: 5, name: 'Средняя' },
    { size: 8, label: '8px', dot: 8, name: 'Маркер' },
    { size: 14, label: '14px', dot: 12, name: 'Жирная' }
  ];

  const LASER_COLOR_PRESETS = [
    { color: '#ef4444', name: 'Неоновый красный' },
    { color: '#10b981', name: 'Изумрудный луч' },
    { color: '#06b6d4', name: 'Неоновый циан' },
    { color: '#3b82f6', name: 'Электрический синий' },
    { color: '#a855f7', name: 'Неоновый фиолетовый' },
    { color: '#ec4899', name: 'Яркий розовый' },
    { color: '#f59e0b', name: 'Янтарно-золотой' },
    { color: '#ffffff', name: 'Белоснежный луч' },
    { color: '#84cc16', name: 'Лаймовый луч' }
  ];

  const LASER_SIZE_PRESETS = [
    { width: 4, label: 'Тонкий', name: '4px' },
    { width: 7, label: 'Средний', name: '7px' },
    { width: 12, label: 'Толстый', name: '12px' }
  ];

  // --- Global State ---
  let isOpen = false;
  let taskId = null;
  let contextType = 'submission';
  let contextId = null;

  // Multi-page System
  let pages = [
    { id: 'page_1', title: 'Страница 1', background: 'dots', strokes: [] }
  ];
  let currentPageId = 'page_1';
  let strokes = []; // Pointer to active page strokes
  let redoStack = [];
  let selectedIds = new Set();
  let clipboardObjects = [];
  const imageCache = new Map();
  let recentColors = ['#0f172a', '#6366f1', '#10b981', '#f59e0b'];

  // Active Tool & Properties
  // Tools: 'select', 'lasso', 'pan', 'pen', 'pencil', 'brush', 'highlighter',
  //        'eraser_stroke', 'eraser_object', 'laser', 'eyedropper',
  //        'shape', 'connector', 'note', 'text', 'math', 'ruler', 'protractor'
  let tool = 'pen';
  let currentShape = 'rectangle';
  let penColor = '#6366f1';
  let highlighterColor = '#fef08a';
  let penSize = 3;
  let penOpacity = 1;
  let strokeStyle = 'solid'; // 'solid', 'dashed', 'dotted', 'sketch'
  let isStrictShape = false;
  let fillColor = null; // null or hex
  let shapeFill = 'none'; // 'none' | 'semi' | 'solid'
  let airbrushDensity = 0.75; // 0.25 | 0.5 | 0.75 | 1.0

  const ALL_SHAPE_IDS = [
    'rectangle', 'square', 'rounded-rect', 'circle', 'ellipse', 'semicircle', 'sector',
    'triangle', 'right-triangle', 'equilateral-triangle', 'rhombus', 'parallelogram', 'trapezoid', 'polygon', 'star',
    'cloud', 'callout', 'brackets', 'cube', 'cylinder', 'cone', 'pyramid',
    'line', 'arrow', 'double-arrow', 'curved-arrow',
    'process', 'decision', 'io', 'terminal'
  ];

  // Viewport Transform
  let viewScale = 1;
  let viewOffsetX = 0;
  let viewOffsetY = 0;
  let dpr = 1;

  // Laser Pointer State
  let laserTrail = [];
  let laserAnimFrame = null;
  let laserCanvas = null;
  let laserCtx = null;
  let laserCleared = true;
  let lastLaserHover = null;
  let laserColor = '#ef4444';
  try {
    const savedLColor = localStorage.getItem('boo_whiteboard_laser_color');
    if (savedLColor) laserColor = savedLColor;
  } catch (_) {}
  let laserWidth = 7;
  try {
    const savedLWidth = parseInt(localStorage.getItem('boo_whiteboard_laser_width') || '7', 10);
    if (savedLWidth) laserWidth = savedLWidth;
  } catch (_) {}
  let laserMenu = null;
  let remoteLaserColor = null;
  let remoteLaserWidth = null;
  let currentBrush = 'pen'; // 'pen' | 'pencil' | 'brush' | 'highlighter'

  // Realtime Sync Adapter & Remote State
  let realtimeSyncAdapter = null;
  const remoteLiveStrokes = new Map();
  let isReadOnly = false;

  // DOM Elements
  let overlay = null;
  let canvas = null;
  let ctx = null;
  let objectLayer = null;
  let selectionBox = null;
  let marqueeBox = null;
  let contextBar = null;
  let toolbar = null;
  let brushMenu = null;
  let shapesMenu = null;
  let propPopover = null;
  let zoomIsland = null;
  let pagesBar = null;
  let minimapEl = null;
  let minimapCanvas = null;
  let minimapCtx = null;
  let catalogModal = null;
  let exportModal = null;
  let mathModal = null;
  let bgSelectorPopover = null;
  let saveStatus = null;
  let clearConfirm = null;
  let fab = null;
  let fabBadge = null;
  let embeddedTarget = null;
  let hiddenFileInput = null;
  let textEditor = null;

  // Eraser Menu & Sizing
  let eraserSize = 24;
  try {
    const savedEraser = localStorage.getItem('boo_whiteboard_eraser_size');
    if (savedEraser) eraserSize = Math.max(6, Math.min(100, parseInt(savedEraser, 10) || 24));
  } catch (e) {}
  let eraserMenu = null;
  let moreMenu = null;


  // Interaction State
  let isPointerDown = false;
  let interactionMode = null; // 'draw' | 'pan' | 'move' | 'resize' | 'rotate' | 'marquee' | 'lasso'
  let currentStroke = null;
  let lassoPoints = [];
  let panStart = null;
  let spaceKeyHeld = false;
  let middlePanActive = false;
  let dragStartPos = { x: 0, y: 0 };
  let lastMoveSyncTime = 0;
  let lastResizeSyncTime = 0;
  let resizeHandle = null;
  let resizeStartBounds = null;
  let resizeSnapshot = null;
  let moveSnapshot = null;
  let rotateStartAngle = 0;
  let rotateCenter = { x: 0, y: 0 };
  let marqueeStart = { x: 0, y: 0 };

  // Alignment Guides
  let activeGuides = []; // array of { type: 'h'|'v', pos: number }

  // Toolbar drag state
  let tbDragging = false;
  let tbDragStart = { x: 0, y: 0, left: 0, top: 0 };

  // Persistence State
  let dirty = false;
  let saveTimer = null;
  let pendingSavePromise = null;
  const LOAD_CACHE_TTL_MS = 15000;
  const LOAD_DEBOUNCE_MS = 250;
  let loadState = { key: null, lastAt: 0, lastData: null, promise: null };
  let checkTimer = null;

  function generateId(prefix = 'obj') {
    return `${prefix}_${Math.random().toString(36).slice(2, 9)}_${Date.now().toString(36)}`;
  }

  function getActivePage() {
    let p = pages.find((pg) => pg.id === currentPageId);
    if (!p) {
      if (currentPageId) {
        p = { id: currentPageId, title: `Страница ${pages.length + 1}`, background: 'dots', strokes: [] };
        pages.push(p);
      } else {
        p = pages[0] || { id: 'page_1', title: 'Страница 1', background: 'dots', strokes: [] };
        currentPageId = p.id;
      }
    }
    return p;
  }

  function syncPageStrokes() {
    const page = getActivePage();
    strokes = page.strokes;
  }

  function storageKey() {
    if (!taskId && !contextId) return null;
    return `boo.canvas.${contextType || 'submission'}.${contextId || 'none'}.${taskId || 'general'}`;
  }

  function contextKey() {
    if (!taskId && !contextId) return null;
    return `${contextType || 'submission'}:${contextId || 'none'}:${taskId || 'general'}`;
  }

  function saveLocal() {
    const key = storageKey();
    if (!key) return;
    try {
      const payload = {
        version: 2,
        pages,
        currentPageId,
        strokes, // legacy compatibility
      };
      localStorage.setItem(key, JSON.stringify(payload));
    } catch (_) {}
  }

  function loadLocal() {
    const key = storageKey();
    if (!key) return null;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed;
    } catch (_) {
      return null;
    }
  }

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  // --- Initialization & DOM Setup ---

  function init() {
    if (overlay && document.body.contains(overlay)) return;

    if (overlay && !document.body.contains(overlay)) {
      try {
        overlay?.remove();
        toolbar?.remove();
        brushMenu?.remove();
        shapesMenu?.remove();
        laserMenu?.remove();
        propPopover?.remove();
        zoomIsland?.remove();
        pagesBar?.remove();
        minimapEl?.remove();
        catalogModal?.remove();
        exportModal?.remove();
        mathModal?.remove();
        bgSelectorPopover?.remove();
        saveStatus?.remove();
        clearConfirm?.remove();
        fab?.remove();
        hiddenFileInput?.remove();
        eraserMenu?.remove();
        moreMenu?.remove();
        laserCanvas?.remove();
      } catch (e) {}
      overlay = null;
      canvas = null;
      ctx = null;
      laserCanvas = null;
      laserCtx = null;
      laserMenu = null;
      eraserMenu = null;
      moreMenu = null;
    }

    createFileInput();
    createFab();
    createOverlay();
    createToolbar();
    createBrushMenu();
    createShapesMenu();
    createLaserMenu();
    createEraserMenu();
    createMoreMenu();
    createPropPopover();
    createZoomIsland();
    createPagesBar();
    createMinimap();
    createCatalogModal();
    createExportModal();
    createMathModal();
    createBgSelectorPopover();
    createSaveStatus();
    createClearConfirm();

    window.removeEventListener('resize', resizeCanvas);
    document.removeEventListener('keydown', onKeyDown);
    document.removeEventListener('keyup', onKeyUp);
    document.removeEventListener('paste', onPaste);
    document.removeEventListener('pointerdown', onGlobalPointerDown);

    window.addEventListener('resize', resizeCanvas);
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('keyup', onKeyUp);
    document.addEventListener('paste', onPaste);
    document.addEventListener('pointerdown', onGlobalPointerDown);

    startLaserLoop();
    ensureKaTeXLoaded();
  }

  function createFileInput() {
    hiddenFileInput = document.createElement('input');
    hiddenFileInput.type = 'file';
    hiddenFileInput.accept = 'image/*,application/pdf';
    hiddenFileInput.style.display = 'none';
    hiddenFileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files[0]) {
        const file = e.target.files[0];
        if (file.type.startsWith('image/')) {
          compressAndInsertImage(file);
        } else if (file.type === 'application/pdf') {
          insertPdfPlaceholder(file);
        }
        e.target.value = '';
      }
    });
    document.body.appendChild(hiddenFileInput);
  }

  function createFab() {
    fab = document.createElement('button');
    fab.className = 'boo-canvas-fab';
    fab.type = 'button';
    fab.title = 'BooStudy Whiteboard OS';
    fab.innerHTML = '<i class="ph-bold ph-chalkboard-teacher"></i>';
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
    overlay.className = 'boo-canvas-overlay boo-bg-dots';
    overlay.dataset.tool = tool;

    canvas = document.createElement('canvas');
    canvas.setAttribute('aria-label', 'Область интерактивной доски BooStudy.');
    canvas.tabIndex = 0;
    overlay.appendChild(canvas);

    // Interactive DOM Object Layer
    objectLayer = document.createElement('div');
    objectLayer.className = 'boo-canvas-object-layer';
    overlay.appendChild(objectLayer);

    // Selection Bounding Box
    selectionBox = document.createElement('div');
    selectionBox.className = 'boo-canvas-selection-box';
    selectionBox.style.display = 'none';

    // 8 Resize Handles + Rotation Handle
    const handles = ['tl', 'tc', 'tr', 'mr', 'br', 'bc', 'bl', 'ml'];
    handles.forEach((h) => {
      const handleEl = document.createElement('div');
      handleEl.className = `boo-canvas-handle handle-${h}`;
      handleEl.dataset.handle = h;
      handleEl.addEventListener('pointerdown', (e) => onHandlePointerDown(e, h));
      selectionBox.appendChild(handleEl);
    });

    const rotHandle = document.createElement('div');
    rotHandle.className = 'boo-canvas-handle handle-rot';
    rotHandle.title = 'Повернуть объект';
    rotHandle.addEventListener('pointerdown', onRotatePointerDown);
    selectionBox.appendChild(rotHandle);

    overlay.appendChild(selectionBox);

    // Marquee Selection Box
    marqueeBox = document.createElement('div');
    marqueeBox.className = 'boo-canvas-marquee';
    marqueeBox.style.display = 'none';
    overlay.appendChild(marqueeBox);

    // Topmost Canvas for Laser Pointer (ALWAYS on top of all elements)
    laserCanvas = document.createElement('canvas');
    laserCanvas.className = 'boo-canvas-laser-top';
    laserCanvas.setAttribute('aria-hidden', 'true');
    laserCanvas.style.pointerEvents = 'none';
    laserCanvas.style.position = 'absolute';
    laserCanvas.style.top = '0';
    laserCanvas.style.left = '0';
    laserCanvas.style.width = '100%';
    laserCanvas.style.height = '100%';
    laserCanvas.style.zIndex = '2147483647';
    overlay.appendChild(laserCanvas);
    laserCtx = laserCanvas.getContext('2d');

    // Floating Context Bar
    createContextBar();

    document.body.appendChild(overlay);
    ctx = canvas.getContext('2d');

    // Canvas & Pointer Interaction Events
    canvas.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
    canvas.addEventListener('pointerleave', () => {
      if (tool === 'laser' && !isPointerDown) {
        lastLaserHover = null;
        drawLaserTop();
      }
    });
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('dblclick', (e) => {
      const origin = canvasOrigin();
      const screenX = e.clientX - origin.left;
      const screenY = e.clientY - origin.top;
      const hit = hitTest(screenX, screenY);
      if (hit) {
        if (hit.type === 'text') {
          const p = hit.points[0];
          const activeRect = getActiveTaskContentRect();
          const sp = pointToScreen(p, hit, activeRect);
          beginTextEntry({ clientX: sp.x, clientY: sp.y }, hit.space, p, hit);
        } else if (hit.type === 'math') {
          openMathModal(hit);
        }
      }
    });

    overlay.addEventListener('wheel', onWheel, { passive: false });

    // Drag & Drop
    overlay.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });
    overlay.addEventListener('drop', (e) => {
      e.preventDefault();
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        compressAndInsertImage(e.dataTransfer.files[0], e.clientX, e.clientY);
      }
    });
  }

  // --- Left Dock Toolbar ---

  function createToolbar() {
    toolbar = document.createElement('div');
    toolbar.className = 'boo-canvas-toolbar tw-canvas-toolbar-polished';
    toolbar.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      onToolbarDragStart(e);
    });
    toolbar.addEventListener('mousedown', (e) => e.stopPropagation());
    toolbar.addEventListener('pointerup', (e) => e.stopPropagation());
    toolbar.addEventListener('mouseup', (e) => e.stopPropagation());

    // 1. Select (V) / Lasso toggle
    const selectBtn = mkBtn('ph-cursor', 'Выделение (V) / Двойной клик: Лассо', () => {
      if (tool === 'select') setTool('lasso');
      else setTool('select');
    });
    selectBtn.id = 'boo-tb-select';
    toolbar.appendChild(selectBtn);

    // 2. Hand / Pan (H)
    const panBtn = mkBtn('ph-hand', 'Рука / Перемещение (H)', () => setTool('pan'));
    panBtn.id = 'boo-tb-pan';
    toolbar.appendChild(panBtn);

    // 3. Pen / Brush Flyout (P)
    const penBtn = mkBtn('ph-pencil-simple-line', 'Кисти и перья (P) — нажмите для выбора', () => {
      const brushIds = ['pen', 'ballpoint', 'fountain_pen', 'pencil', 'brush', 'felt_tip', 'highlighter', 'neon', 'airbrush', 'dashed_pen'];
      if (!brushIds.includes(tool)) {
        setTool(currentBrush || 'ballpoint');
      }
      toggleBrushMenu();
    });
    penBtn.id = 'boo-tb-pen';
    penBtn.classList.add('active', 'tb-btn-has-menu');
    toolbar.appendChild(penBtn);

    // 4. Color & Thickness Quick Button (opens detailed props popover)
    const propsBtn = document.createElement('button');
    propsBtn.type = 'button';
    propsBtn.className = 'tb-props-btn';
    propsBtn.id = 'boo-tb-props';
    propsBtn.title = 'Параметры кисти, цвет и размер';
    propsBtn.setAttribute('aria-label', propsBtn.title);
    propsBtn.innerHTML = `
      <span class="tb-props-swatch" style="background-color: ${penColor}"></span>
      <span class="tb-props-size-badge">${penSize}</span>
    `;
    propsBtn.addEventListener('pointerdown', (e) => e.stopPropagation());
    propsBtn.addEventListener('mousedown', (e) => e.stopPropagation());
    propsBtn.addEventListener('pointerup', (e) => e.stopPropagation());
    propsBtn.addEventListener('mouseup', (e) => e.stopPropagation());
    propsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePropPopover();
    });
    toolbar.appendChild(propsBtn);

    // 5. Shapes Flyout (R)
    const shapeBtn = mkBtn('ph-rectangle', 'Библиотека фигур 2D/3D (R)', () => {
      if (tool !== 'shape' && !ALL_SHAPE_IDS.includes(tool)) {
        setTool('shape');
      }
      toggleShapesMenu();
    });
    shapeBtn.id = 'boo-tb-shape';
    shapeBtn.classList.add('tb-btn-has-menu');
    toolbar.appendChild(shapeBtn);

    // 6. Eraser (E) with thickness menu
    const eraserBtn = mkBtn('ph-eraser', `Ластик (E) — ${eraserSize}px`, () => {
      if (tool !== 'eraser_stroke' && tool !== 'eraser_object') {
        setTool('eraser_stroke');
      }
      toggleEraserMenu();
    });
    eraserBtn.id = 'boo-tb-eraser';
    eraserBtn.classList.add('tb-btn-has-menu');
    toolbar.appendChild(eraserBtn);

    // 7. More Tools Flyout (...)
    const moreBtn = mkBtn('ph-dots-three-outline-vertical', 'Ещё инструменты', () => {
      toggleMoreMenu();
    });
    moreBtn.id = 'boo-tb-more';
    moreBtn.classList.add('tb-btn-has-menu');
    toolbar.appendChild(moreBtn);

    toolbar.appendChild(mkSep());

    // 17. Undo & Redo
    const undoBtn = mkBtn('ph-arrow-counter-clockwise', 'Отменить (Ctrl+Z)', undo);
    undoBtn.id = 'boo-tb-undo';
    toolbar.appendChild(undoBtn);

    const redoBtn = mkBtn('ph-arrow-clockwise', 'Вернуть (Ctrl+Y)', redo);
    redoBtn.id = 'boo-tb-redo';
    toolbar.appendChild(redoBtn);

    // 18. Export
    const exportBtn = mkBtn('ph-export', 'Экспорт доски (PNG/SVG/PDF/JSON)', () => openExportModal());
    exportBtn.id = 'boo-tb-export';
    toolbar.appendChild(exportBtn);

    // 19. Clear All
    const clearBtn = mkBtn('ph-trash', 'Очистить страницу', () => {
      if (!strokes.length) return;
      toggleClearConfirm();
    });
    clearBtn.id = 'boo-tb-clear';
    toolbar.appendChild(clearBtn);

    // 20. Close (Overlay mode)
    const closeBtn = mkBtn('ph-x', 'Закрыть холст (Esc)', close);
    closeBtn.className += ' tb-close-btn';
    toolbar.appendChild(closeBtn);

    document.body.appendChild(toolbar);
    toolbar.style.display = 'none';
    setTool(tool);
    updateShapeIcon();
  }

  // --- Extended Shapes Flyout Menu ---

  function createShapesMenu() {
    shapesMenu = document.createElement('div');
    shapesMenu.className = 'boo-canvas-shapes-menu';
    shapesMenu.style.display = 'none';

    // 1. Stroke Color Section
    const colorSec = document.createElement('div');
    colorSec.className = 'boo-shapes-menu-section';
    colorSec.innerHTML = `
      <div class="boo-shapes-menu-label">
        <span>Цвет контура</span>
      </div>
    `;
    const colorGrid = document.createElement('div');
    colorGrid.className = 'boo-brush-color-grid';
    COLOR_PRESETS.forEach((c) => {
      const sw = document.createElement('button');
      sw.type = 'button';
      sw.className = 'boo-brush-color-swatch' + (penColor.toLowerCase() === c.toLowerCase() ? ' active' : '');
      sw.dataset.color = c;
      sw.style.backgroundColor = c;
      sw.title = c;
      sw.setAttribute('aria-label', `Цвет контура ${c}`);
      sw.addEventListener('click', (e) => {
        e.stopPropagation();
        setPenColor(c);
      });
      colorGrid.appendChild(sw);
    });
    const customLabel = document.createElement('label');
    customLabel.className = 'boo-brush-custom-color';
    customLabel.title = 'Свой цвет';
    customLabel.innerHTML = `
      <i class="ph-bold ph-plus" style="font-size: 13px;"></i>
      <input type="color" class="boo-brush-native-color" value="${penColor}">
    `;
    const nativeColorInput = customLabel.querySelector('input');
    nativeColorInput.addEventListener('input', (e) => setPenColor(e.target.value));
    colorGrid.appendChild(customLabel);
    colorSec.appendChild(colorGrid);
    shapesMenu.appendChild(colorSec);

    // 2. Fill Style Section
    const fillSec = document.createElement('div');
    fillSec.className = 'boo-shapes-menu-section';
    fillSec.innerHTML = `
      <div class="boo-shapes-menu-label">
        <span>Заливка фигуры</span>
      </div>
      <div class="boo-shapes-fill-group">
        <button type="button" class="boo-shapes-fill-btn ${shapeFill === 'none' ? 'active' : ''}" data-fill="none">
          <i class="ph-bold ph-square" style="font-size: 13px;"></i>
          <span>Контур</span>
        </button>
        <button type="button" class="boo-shapes-fill-btn ${shapeFill === 'semi' ? 'active' : ''}" data-fill="semi">
          <i class="ph-bold ph-square-half" style="font-size: 13px;"></i>
          <span>25% фон</span>
        </button>
        <button type="button" class="boo-shapes-fill-btn ${shapeFill === 'solid' ? 'active' : ''}" data-fill="solid">
          <i class="ph-bold ph-square" style="font-size: 13px; opacity: 0.9;"></i>
          <span>Сплошная</span>
        </button>
      </div>
    `;
    fillSec.querySelectorAll('.boo-shapes-fill-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        setShapeFill(btn.dataset.fill);
      });
    });
    shapesMenu.appendChild(fillSec);

    // 3. Stroke Width Section
    const strokeWidthSec = document.createElement('div');
    strokeWidthSec.className = 'boo-shapes-menu-section';
    strokeWidthSec.innerHTML = `
      <div class="boo-shapes-menu-label">
        <span>Толщина контура</span>
        <span class="boo-brush-size-val" id="boo-shape-size-text">${penSize}px</span>
      </div>
      <div class="boo-brush-size-presets">
        <button type="button" class="boo-brush-size-btn ${penSize === 1 ? 'active' : ''}" data-size="1">1px</button>
        <button type="button" class="boo-brush-size-btn ${penSize === 2 ? 'active' : ''}" data-size="2">2px</button>
        <button type="button" class="boo-brush-size-btn ${penSize === 4 ? 'active' : ''}" data-size="4">4px</button>
        <button type="button" class="boo-brush-size-btn ${penSize === 8 ? 'active' : ''}" data-size="8">8px</button>
      </div>
    `;
    strokeWidthSec.querySelectorAll('.boo-brush-size-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        setPenSize(Number(btn.dataset.size));
        const txt = document.getElementById('boo-shape-size-text');
        if (txt) txt.textContent = `${penSize}px`;
      });
    });
    shapesMenu.appendChild(strokeWidthSec);

    // 4. Shape Categories
    const categories = [
      {
        title: 'Основные 2D',
        shapes: [
          { id: 'rectangle', icon: 'ph-rectangle', title: 'Прямоугольник (R)' },
          { id: 'square', icon: 'ph-square', title: 'Квадрат (строгий 1:1)' },
          { id: 'rounded-rect', icon: 'ph-square', title: 'Скруглённый прямоугольник' },
          { id: 'circle', icon: 'ph-circle', title: 'Круг (строгий 1:1)' },
          { id: 'ellipse', icon: 'ph-circle', title: 'Эллипс (O)' },
          { id: 'semicircle', icon: 'ph-circle-half', title: 'Полукруг' },
        ]
      },
      {
        title: 'Геометрия и многоугольники',
        shapes: [
          { id: 'triangle', icon: 'ph-triangle', title: 'Треугольник' },
          { id: 'right-triangle', icon: 'ph-polygon', title: 'Прямоугольный треугольник' },
          { id: 'equilateral-triangle', icon: 'ph-triangle', title: 'Равносторонний треугольник' },
          { id: 'rhombus', icon: 'ph-diamond', title: 'Ромб' },
          { id: 'parallelogram', icon: 'ph-parallelogram', title: 'Параллелограмм' },
          { id: 'trapezoid', icon: 'ph-trapezoid', title: 'Трапеция' },
          { id: 'polygon', icon: 'ph-hexagon', title: 'Правильный 6-угольник' },
          { id: 'star', icon: 'ph-star', title: '5-конечная звезда' },
        ]
      },
      {
        title: 'Специальные и аннотации',
        shapes: [
          { id: 'callout', icon: 'ph-chat-circle-dots', title: 'Выноска с текстом' },
          { id: 'brackets', icon: 'ph-brackets-curly', title: 'Фигурные скобки' },
        ]
      },
      {
        title: '3D Фигуры',
        shapes: [
          { id: 'cube', icon: 'ph-cube', title: '3D Куб' },
          { id: 'cylinder', icon: 'ph-cylinder', title: '3D Цилиндр' },
          { id: 'cone', icon: 'ph-funnel', title: '3D Конус' },
          { id: 'pyramid', icon: 'ph-triangle', title: '3D Пирамида' },
        ]
      },
      {
        title: 'Линии и связи',
        shapes: [
          { id: 'line', icon: 'ph-line-segment', title: 'Прямая линия (L)' },
          { id: 'arrow', icon: 'ph-arrow-up-right', title: 'Стрелка' },
          { id: 'double-arrow', icon: 'ph-arrows-horizontal', title: 'Двусторонняя стрелка' },
          { id: 'curved-arrow', icon: 'ph-arrow-bend-right-up', title: 'Изогнутая стрелка' },
        ]
      },
      {
        title: 'Блок-схемы',
        shapes: [
          { id: 'process', icon: 'ph-square', title: 'Процесс (прямоугольник)' },
          { id: 'decision', icon: 'ph-diamond', title: 'Условие (ромб)' },
          { id: 'io', icon: 'ph-parallelogram', title: 'Ввод / Вывод' },
          { id: 'terminal', icon: 'ph-pill', title: 'Начало / Конец' },
        ]
      }
    ];

    categories.forEach((cat) => {
      const catHead = document.createElement('div');
      catHead.className = 'boo-shapes-menu-label';
      catHead.style.marginTop = '4px';
      catHead.textContent = cat.title;
      shapesMenu.appendChild(catHead);

      const grid = document.createElement('div');
      grid.className = 'boo-shapes-grid';

      cat.shapes.forEach((s) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'tb-shape-opt' + (currentShape === s.id ? ' active' : '');
        btn.dataset.shape = s.id;
        btn.title = s.title;
        btn.setAttribute('aria-label', s.title);
        btn.innerHTML = `<i class="ph-bold ${s.icon}"></i>`;
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          currentShape = s.id;
          const isConn = ['line', 'arrow', 'double-arrow', 'curved-arrow'].includes(s.id);
          if (selectedIds.size > 0) {
            strokes.forEach((stroke) => {
              if (selectedIds.has(stroke.id)) {
                stroke.type = isConn ? 'connector' : 'shape';
                stroke.shape = s.id;
                stroke.fill = shapeFill;
                stroke.fillColor = penColor;
              }
            });
            dirty = true;
            saveLocal();
            redraw();
            updateSelectionBox();
            scheduleSave();
          } else {
            setTool('shape');
          }
          toggleShapesMenu(false);
          updateShapeIcon();
        });
        grid.appendChild(btn);
      });
      shapesMenu.appendChild(grid);
    });

    document.body.appendChild(shapesMenu);
  }

  // --- Extended Brush Flyout Menu ---

  function createBrushMenu() {
    brushMenu = document.createElement('div');
    brushMenu.className = 'boo-canvas-brush-menu';
    brushMenu.style.display = 'none';

    // 1. Color Palette Section
    const colorSec = document.createElement('div');
    colorSec.className = 'boo-brush-menu-section';
    colorSec.innerHTML = `
      <div class="boo-brush-menu-label">
        <span>Цвет линии</span>
      </div>
    `;
    const colorGrid = document.createElement('div');
    colorGrid.className = 'boo-brush-color-grid';
    COLOR_PRESETS.forEach((c) => {
      const sw = document.createElement('button');
      sw.type = 'button';
      sw.className = 'boo-brush-color-swatch' + (penColor.toLowerCase() === c.toLowerCase() ? ' active' : '');
      sw.dataset.color = c;
      sw.style.backgroundColor = c;
      sw.title = c;
      sw.setAttribute('aria-label', `Выбрать цвет ${c}`);
      sw.addEventListener('click', (e) => {
        e.stopPropagation();
        setPenColor(c);
      });
      colorGrid.appendChild(sw);
    });
    const customLabel = document.createElement('label');
    customLabel.className = 'boo-brush-custom-color';
    customLabel.title = 'Свой цвет';
    customLabel.innerHTML = `
      <i class="ph-bold ph-plus" style="font-size: 13px;"></i>
      <input type="color" class="boo-brush-native-color" value="${penColor}">
    `;
    const nativeColorInput = customLabel.querySelector('input');
    nativeColorInput.addEventListener('input', (e) => {
      setPenColor(e.target.value);
    });
    colorGrid.appendChild(customLabel);
    colorSec.appendChild(colorGrid);
    brushMenu.appendChild(colorSec);

    // 2. Thickness / Size Section
    const sizeSec = document.createElement('div');
    sizeSec.className = 'boo-brush-menu-section';
    sizeSec.innerHTML = `
      <div class="boo-brush-menu-label">
        <span>Толщина</span>
        <span class="boo-brush-size-val" id="boo-brush-size-text">${penSize}px</span>
      </div>
    `;
    const sizePresets = document.createElement('div');
    sizePresets.className = 'boo-brush-size-presets';
    SIZE_PRESETS.forEach((p) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'boo-brush-size-btn' + (penSize === p.size ? ' active' : '');
      b.dataset.size = p.size;
      b.title = `${p.name} (${p.label})`;
      b.setAttribute('aria-label', `${p.name} (${p.label})`);
      b.innerHTML = `<span class="size-dot" style="width: ${p.dot}px; height: ${p.dot}px;"></span><span>${p.label}</span>`;
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        setPenSize(p.size);
      });
      sizePresets.appendChild(b);
    });
    sizeSec.appendChild(sizePresets);

    const slider = document.createElement('input');
    slider.type = 'range';
    slider.className = 'boo-brush-slider';
    slider.id = 'boo-brush-slider';
    slider.min = '1';
    slider.max = '28';
    slider.value = String(penSize);
    slider.addEventListener('input', (e) => {
      setPenSize(Number(e.target.value));
    });
    sizeSec.appendChild(slider);
    brushMenu.appendChild(sizeSec);

    // 3. Airbrush Density Section
    const airbrushDensitySec = document.createElement('div');
    airbrushDensitySec.className = 'boo-brush-menu-section';
    airbrushDensitySec.id = 'boo-airbrush-density-section';
    airbrushDensitySec.style.display = (currentBrush === 'airbrush' || tool === 'airbrush') ? 'flex' : 'none';
    airbrushDensitySec.innerHTML = `
      <div class="boo-brush-menu-label">
        <span>Плотность распыления</span>
        <span class="boo-brush-size-val" id="boo-airbrush-density-text">${Math.round(airbrushDensity * 100)}%</span>
      </div>
      <div class="boo-brush-size-presets">
        <button type="button" class="boo-brush-density-btn ${airbrushDensity === 0.25 ? 'active' : ''}" data-density="0.25">25%</button>
        <button type="button" class="boo-brush-density-btn ${airbrushDensity === 0.5 ? 'active' : ''}" data-density="0.5">50%</button>
        <button type="button" class="boo-brush-density-btn ${airbrushDensity === 0.75 ? 'active' : ''}" data-density="0.75">75%</button>
        <button type="button" class="boo-brush-density-btn ${airbrushDensity === 1 ? 'active' : ''}" data-density="1">100%</button>
      </div>
      <input type="range" class="boo-brush-slider" id="boo-airbrush-density-slider" min="15" max="100" value="${Math.round(airbrushDensity * 100)}">
    `;
    airbrushDensitySec.querySelectorAll('.boo-brush-density-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        setAirbrushDensity(Number(btn.dataset.density));
      });
    });
    const densitySlider = airbrushDensitySec.querySelector('#boo-airbrush-density-slider');
    densitySlider.addEventListener('input', (e) => {
      setAirbrushDensity(Number(e.target.value) / 100);
    });
    brushMenu.appendChild(airbrushDensitySec);

    // 4. Brush Engine Selection
    const brushesLabel = document.createElement('div');
    brushesLabel.className = 'boo-brush-menu-label';
    brushesLabel.style.padding = '4px 2px 0 2px';
    brushesLabel.innerHTML = `<span>Тип кисти / пера</span>`;
    brushMenu.appendChild(brushesLabel);

    const brushes = [
      { id: 'fountain_pen', icon: 'ph-pen-nib', title: 'Каллиграфическое перо', desc: 'Скошенное перо, динамическая толщина' },
      { id: 'ballpoint', icon: 'ph-pencil-simple-line', title: 'Шариковая ручка', desc: 'Чёткая гладкая линия для записей' },
      { id: 'pencil', icon: 'ph-pencil', title: 'Графитный карандаш', desc: 'Текстура графита и бумажного зерна' },
      { id: 'brush', icon: 'ph-paint-brush', title: 'Художественная кисть', desc: 'Мягкий акварельный мазок щетиной' },
      { id: 'felt_tip', icon: 'ph-pen', title: 'Фломастер (скетч)', desc: 'Сочный цвет для скетчноутинга' },
      { id: 'highlighter', icon: 'ph-highlighter', title: 'Текстовыделитель', desc: 'Полупрозрачный маркер multiply' },
      { id: 'neon', icon: 'ph-sparkle', title: 'Неоновое перо (Glow)', desc: 'Светящийся люминесцентный ореол' },
      { id: 'airbrush', icon: 'ph-spray-bottle', title: 'Аэрограф (спрей)', desc: 'Мягкое распыление микро-точек' },
      { id: 'dashed_pen', icon: 'ph-line-dashed', title: 'Технический пунктир', desc: 'Прерывистая чертёжная линия' },
    ];

    brushes.forEach((b) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tb-brush-opt' + ((tool === b.id || currentBrush === b.id) ? ' active' : '');
      btn.dataset.brush = b.id;
      btn.innerHTML = `
        <i class="ph-bold ${b.icon}"></i>
        <div class="tb-brush-text">
          <span class="tb-brush-title">${b.title}</span>
          <span class="tb-brush-desc">${b.desc}</span>
        </div>
      `;
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        currentBrush = b.id;
        brushMenu.querySelectorAll('.tb-brush-opt').forEach((opt) => opt.classList.remove('active'));
        btn.classList.add('active');
        if (airbrushDensitySec) {
          airbrushDensitySec.style.display = b.id === 'airbrush' ? 'flex' : 'none';
        }
        setTool(b.id === 'highlighter' ? 'highlighter' : b.id);
        if (selectedIds.size > 0) {
          strokes.forEach((stroke) => {
            if (selectedIds.has(stroke.id)) {
              if (b.id === 'highlighter') {
                stroke.type = 'highlighter';
                stroke.brush = 'highlighter';
                stroke.opacity = 0.38;
                stroke.color = stroke.color || highlighterColor;
                stroke.width = Math.max(16, penSize * 3.5);
              } else {
                stroke.type = 'stroke';
                stroke.brush = b.id;
                stroke.width = getBrushDefaultWidth(b.id, tool);
                stroke.opacity = getBrushDefaultOpacity(b.id, tool);
                if (b.id === 'dashed_pen') stroke.style = 'dashed';
                else if (stroke.style === 'dashed') stroke.style = 'solid';
              }
            }
          });
          dirty = true;
          saveLocal();
          redraw();
          updateSelectionBox();
          scheduleSave();
        }
        toggleBrushMenu(false);
        updateBrushIcon();
      });
      brushMenu.appendChild(btn);
    });

    document.body.appendChild(brushMenu);
  }

  // --- Extended Laser Pointer Flyout Menu ---

  function createLaserMenu() {
    laserMenu = document.createElement('div');
    laserMenu.className = 'boo-canvas-laser-menu';
    laserMenu.style.display = 'none';

    // 1. Color Palette Section
    const colorSec = document.createElement('div');
    colorSec.className = 'boo-laser-menu-section';
    colorSec.innerHTML = `
      <div class="boo-laser-menu-label">
        <span>Цвет лазера</span>
      </div>
    `;
    const colorGrid = document.createElement('div');
    colorGrid.className = 'boo-laser-color-grid';
    LASER_COLOR_PRESETS.forEach((preset) => {
      const sw = document.createElement('button');
      sw.type = 'button';
      sw.className = 'boo-laser-color-swatch' + (laserColor.toLowerCase() === preset.color.toLowerCase() ? ' active' : '');
      sw.dataset.color = preset.color;
      sw.style.backgroundColor = preset.color;
      sw.title = preset.name;
      sw.setAttribute('aria-label', preset.name);
      sw.addEventListener('click', (e) => {
        e.stopPropagation();
        setLaserColor(preset.color);
      });
      colorGrid.appendChild(sw);
    });

    // Native Color Picker
    const customLabel = document.createElement('label');
    customLabel.className = 'boo-laser-custom-color';
    customLabel.title = 'Свой цвет лазера';
    customLabel.innerHTML = `
      <i class="ph-bold ph-plus" style="font-size: 13px;"></i>
      <input type="color" class="boo-laser-native-color" value="${laserColor}">
    `;
    const nativeColorInput = customLabel.querySelector('input');
    nativeColorInput.addEventListener('input', (e) => {
      setLaserColor(e.target.value);
    });
    colorGrid.appendChild(customLabel);
    colorSec.appendChild(colorGrid);
    laserMenu.appendChild(colorSec);

    // 2. Thickness / Size Section
    const sizeSec = document.createElement('div');
    sizeSec.className = 'boo-laser-menu-section';
    sizeSec.innerHTML = `
      <div class="boo-laser-menu-label">
        <span>Толщина луча</span>
        <span class="boo-laser-size-val" id="boo-laser-size-text">${laserWidth}px</span>
      </div>
    `;
    const sizePresets = document.createElement('div');
    sizePresets.className = 'boo-laser-size-presets';
    LASER_SIZE_PRESETS.forEach((p) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'boo-laser-size-btn' + (laserWidth === p.width ? ' active' : '');
      b.dataset.width = p.width;
      b.title = `${p.label} (${p.name})`;
      b.textContent = p.label;
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        setLaserWidth(p.width);
      });
      sizePresets.appendChild(b);
    });
    sizeSec.appendChild(sizePresets);

    const slider = document.createElement('input');
    slider.type = 'range';
    slider.className = 'boo-brush-slider';
    slider.id = 'boo-laser-slider';
    slider.min = '3';
    slider.max = '20';
    slider.value = String(laserWidth);
    slider.addEventListener('input', (e) => {
      setLaserWidth(Number(e.target.value));
    });
    sizeSec.appendChild(slider);
    laserMenu.appendChild(sizeSec);

    document.body.appendChild(laserMenu);
  }

  function setLaserColor(c) {
    if (!c) return;
    laserColor = c;
    try {
      localStorage.setItem('boo_whiteboard_laser_color', c);
    } catch (_) {}
    updateLaserUi();
    if (tool === 'laser' && lastLaserHover) {
      drawLaserTop(lastLaserHover);
    }
  }

  function setLaserWidth(w) {
    if (!w || isNaN(w)) return;
    laserWidth = Math.max(2, Math.min(30, Number(w)));
    try {
      localStorage.setItem('boo_whiteboard_laser_width', String(laserWidth));
    } catch (_) {}
    updateLaserUi();
    if (tool === 'laser' && lastLaserHover) {
      drawLaserTop(lastLaserHover);
    }
  }

  function updateLaserUi() {
    const ind = toolbar?.querySelector('.tb-laser-indicator');
    if (ind) {
      ind.style.backgroundColor = laserColor;
      ind.style.boxShadow = `0 0 6px ${laserColor}`;
    }
    if (!laserMenu) return;
    laserMenu.querySelectorAll('.boo-laser-color-swatch').forEach((sw) => {
      sw.classList.toggle('active', sw.dataset.color?.toLowerCase() === laserColor.toLowerCase());
    });
    const nativeInp = laserMenu.querySelector('.boo-laser-native-color');
    if (nativeInp) nativeInp.value = laserColor;
    laserMenu.querySelectorAll('.boo-laser-size-btn').forEach((b) => {
      b.classList.toggle('active', Number(b.dataset.width) === laserWidth);
    });
    const sizeText = document.getElementById('boo-laser-size-text');
    if (sizeText) sizeText.textContent = `${laserWidth}px`;
    const slider = document.getElementById('boo-laser-slider');
    if (slider) slider.value = String(laserWidth);
  }

  // --- Contextual Floating Action Bar ---

  function createContextBar() {
    contextBar = document.createElement('div');
    contextBar.className = 'boo-canvas-context-bar';
    contextBar.style.display = 'none';
    overlay.appendChild(contextBar);
  }

  function updateContextBar() {
    if (!contextBar) return;
    if (selectedIds.size === 0) {
      contextBar.style.display = 'none';
      return;
    }

    const box = getSelectionScreenBox();
    if (!box) {
      contextBar.style.display = 'none';
      return;
    }

    const selectedStrokes = strokes.filter((s) => selectedIds.has(s.id));
    const hasNote = selectedStrokes.some((s) => s.type === 'note');
    const firstStroke = selectedStrokes[0];

    contextBar.innerHTML = '';

    if (hasNote) {
      // Color themes for Sticky Notes
      NOTE_THEMES.forEach((theme) => {
        const sw = document.createElement('button');
        sw.type = 'button';
        sw.className = 'ctx-swatch' + (firstStroke?.colorTheme === theme.id ? ' active' : '');
        sw.style.backgroundColor = theme.color;
        sw.title = theme.name;
        sw.addEventListener('click', (e) => {
          e.stopPropagation();
          selectedStrokes.forEach((s) => {
            if (s.type === 'note') s.colorTheme = theme.id;
          });
          dirty = true;
          saveLocal();
          redraw();
          updateSelectionBox();
          scheduleSave();
        });
        contextBar.appendChild(sw);
      });
    } else {
      // Color swatches for strokes / shapes / text
      const colors = ['#0f172a', '#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#ffffff'];
      colors.forEach((c) => {
        const sw = document.createElement('button');
        sw.type = 'button';
        sw.className = 'ctx-swatch' + (firstStroke?.color === c ? ' active' : '');
        sw.style.backgroundColor = c;
        sw.title = c;
        sw.addEventListener('click', (e) => {
          e.stopPropagation();
          selectedStrokes.forEach((s) => { s.color = c; });
          dirty = true;
          saveLocal();
          redraw();
          updateSelectionBox();
          scheduleSave();
        });
        contextBar.appendChild(sw);
      });

      contextBar.appendChild(mkCtxSep());

      // Line style: Solid / Dashed / Dotted
      const dashBtn = mkCtxBtn('ph-line-dashed', 'Стиль линии: сплошная / пунктир', () => {
        const nextStyle = firstStroke?.style === 'dashed' ? 'dotted' : (firstStroke?.style === 'dotted' ? 'solid' : 'dashed');
        selectedStrokes.forEach((s) => { s.style = nextStyle; });
        dirty = true;
        saveLocal();
        redraw();
        updateSelectionBox();
      });
      contextBar.appendChild(dashBtn);

      // Thickness adjustments
      const minusBtn = mkCtxBtn('ph-minus', 'Уменьшить размер', () => {
        selectedStrokes.forEach((s) => {
          if (s.type === 'text') s.fontSize = Math.max(10, (s.fontSize || 18) - 2);
          else s.width = Math.max(1, (s.width || 3) - 1);
        });
        dirty = true;
        saveLocal();
        redraw();
        updateSelectionBox();
        scheduleSave();
      });
      contextBar.appendChild(minusBtn);

      const sizeBadge = document.createElement('span');
      sizeBadge.className = 'ctx-size-badge';
      const curSize = firstStroke?.type === 'text' ? (firstStroke.fontSize || 18) : (firstStroke?.width || penSize);
      sizeBadge.textContent = `${curSize}`;
      contextBar.appendChild(sizeBadge);

      const plusBtn = mkCtxBtn('ph-plus', 'Увеличить размер', () => {
        selectedStrokes.forEach((s) => {
          if (s.type === 'text') s.fontSize = Math.min(64, (s.fontSize || 18) + 2);
          else s.width = Math.min(32, (s.width || 3) + 1);
        });
        dirty = true;
        saveLocal();
        redraw();
        updateSelectionBox();
        scheduleSave();
      });
      contextBar.appendChild(plusBtn);

      contextBar.appendChild(mkCtxSep());

      // Flip Horizontal & Vertical
      const flipHBtn = mkCtxBtn('ph-arrows-horizontal', 'Отразить по горизонтали', () => flipSelected('h'));
      contextBar.appendChild(flipHBtn);

      const flipVBtn = mkCtxBtn('ph-arrows-vertical', 'Отразить по вертикали', () => flipSelected('v'));
      contextBar.appendChild(flipVBtn);

      // Lock / Unlock
      const lockBtn = mkCtxBtn(firstStroke?.locked ? 'ph-lock-simple' : 'ph-lock-simple-open', firstStroke?.locked ? 'Разблокировать' : 'Заблокировать', () => {
        const targetLock = !firstStroke?.locked;
        selectedStrokes.forEach((s) => { s.locked = targetLock; });
        dirty = true;
        saveLocal();
        redraw();
        updateSelectionBox();
      });
      contextBar.appendChild(lockBtn);

      // Group / Ungroup
      if (selectedStrokes.length > 1) {
        const grpBtn = mkCtxBtn('ph-selection-plus', 'Сгруппировать (Ctrl+G)', groupSelected);
        contextBar.appendChild(grpBtn);
      }
    }

    if (firstStroke?.type === 'math') {
      const editMathBtn = mkCtxBtn('ph-pencil-simple', 'Редактировать формулу (LaTeX)', () => {
        openMathModal(firstStroke);
      });
      contextBar.appendChild(editMathBtn);
    } else if (firstStroke?.type === 'text') {
      const editTxtBtn = mkCtxBtn('ph-pencil-simple', 'Редактировать текст', () => {
        const p = firstStroke.points[0];
        const activeRect = getActiveTaskContentRect();
        const sp = pointToScreen(p, firstStroke, activeRect);
        beginTextEntry({ clientX: sp.x, clientY: sp.y }, firstStroke.space, p, firstStroke);
      });
      contextBar.appendChild(editTxtBtn);
    }

    contextBar.appendChild(mkCtxSep());

    // Duplicate
    const dupBtn = mkCtxBtn('ph-copy', 'Дублировать (Ctrl+D)', duplicateSelected);
    contextBar.appendChild(dupBtn);

    // Layer ordering
    const frontBtn = mkCtxBtn('ph-arrow-fat-up', 'На передний план', bringToFront);
    contextBar.appendChild(frontBtn);

    const bottomBtn = mkCtxBtn('ph-arrow-fat-down', 'На задний план', sendToBack);
    contextBar.appendChild(bottomBtn);

    contextBar.appendChild(mkCtxSep());

    // Delete
    const delBtn = mkCtxBtn('ph-trash', 'Удалить (Del)', deleteSelected);
    delBtn.classList.add('is-danger');
    contextBar.appendChild(delBtn);

    // Position context bar above or below selection box
    contextBar.style.display = 'flex';
    const barW = contextBar.offsetWidth || 260;
    const barLeft = Math.max(10, Math.min(window.innerWidth - barW - 10, box.x + box.width / 2 - barW / 2));
    let barTop = box.y - 50;
    if (barTop < 10) barTop = box.y + box.height + 12;
    contextBar.style.left = `${barLeft}px`;
    contextBar.style.top = `${barTop}px`;
  }

  function mkCtxBtn(icon, title, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ctx-btn';
    btn.title = title;
    btn.setAttribute('aria-label', title);
    btn.innerHTML = `<i class="ph-bold ${icon}"></i>`;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      onClick();
    });
    return btn;
  }

  function mkCtxSep() {
    const s = document.createElement('div');
    s.className = 'ctx-separator';
    return s;
  }

  // --- Properties Popover ---

  function createPropPopover() {
    propPopover = document.createElement('div');
    propPopover.className = 'boo-canvas-props-popover';

    const head = document.createElement('div');
    head.className = 'boo-props-head';
    head.innerHTML = `
      <span class="boo-props-title">Параметры рисования</span>
      <button type="button" class="boo-props-close-btn" aria-label="Закрыть">&times;</button>
    `;
    head.querySelector('.boo-props-close-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      togglePropPopover(false);
    });
    propPopover.appendChild(head);

    // Brush / Tool Type Section
    const brushSection = document.createElement('div');
    brushSection.className = 'boo-props-section';
    brushSection.innerHTML = `
      <div class="boo-props-label"><span>Тип инструмента / кисти</span></div>
      <div class="boo-brush-type-grid">
        <button type="button" class="boo-brush-type-btn ${tool === 'pen' ? 'active' : ''}" data-tool="pen" title="Перо">
          <i class="ph-bold ph-pencil-simple" style="font-size: 15px;"></i>
          <span>Перо</span>
        </button>
        <button type="button" class="boo-brush-type-btn ${tool === 'pencil' ? 'active' : ''}" data-tool="pencil" title="Карандаш">
          <i class="ph-bold ph-pencil" style="font-size: 15px;"></i>
          <span>Карандаш</span>
        </button>
        <button type="button" class="boo-brush-type-btn ${tool === 'brush' ? 'active' : ''}" data-tool="brush" title="Кисть">
          <i class="ph-bold ph-paint-brush" style="font-size: 15px;"></i>
          <span>Кисть</span>
        </button>
        <button type="button" class="boo-brush-type-btn ${tool === 'highlighter' ? 'active' : ''}" data-tool="highlighter" title="Маркер">
          <i class="ph-bold ph-highlighter" style="font-size: 15px;"></i>
          <span>Маркер</span>
        </button>
      </div>
    `;
    brushSection.querySelectorAll('.boo-brush-type-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const targetTool = btn.dataset.tool;
        brushSection.querySelectorAll('.boo-brush-type-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        if (selectedIds.size > 0) {
          strokes.forEach((stroke) => {
            if (selectedIds.has(stroke.id)) {
              if (targetTool === 'pencil') { stroke.width = 1.5; stroke.style = 'solid'; }
              else if (targetTool === 'brush') { stroke.width = Math.max(6, penSize * 2); stroke.style = 'sketch'; }
              else if (targetTool === 'highlighter') { stroke.type = 'highlighter'; stroke.opacity = 0.38; stroke.width = Math.max(14, penSize * 3); }
              else { stroke.type = 'stroke'; stroke.width = penSize; stroke.style = strokeStyle; }
            }
          });
          dirty = true;
          saveLocal();
          redraw();
          updateSelectionBox();
          scheduleSave();
        } else {
          setTool(targetTool);
        }
      });
    });
    propPopover.appendChild(brushSection);

    // Thickness Section
    const sizeSection = document.createElement('div');
    sizeSection.className = 'boo-props-section';
    sizeSection.innerHTML = `
      <div class="boo-props-label">
        <span>Толщина</span>
        <span class="boo-props-size-val" id="boo-props-size-text">${penSize}px</span>
      </div>
    `;

    const sizePresets = document.createElement('div');
    sizePresets.className = 'boo-props-size-presets';
    SIZE_PRESETS.forEach((p) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'boo-props-size-btn' + (penSize === p.size ? ' active' : '');
      b.dataset.size = p.size;
      b.title = `${p.name} (${p.label})`;
      b.innerHTML = `<span class="size-dot" style="width: ${p.dot}px; height: ${p.dot}px;"></span><span class="size-txt">${p.label}</span>`;
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        setPenSize(p.size);
      });
      sizePresets.appendChild(b);
    });
    sizeSection.appendChild(sizePresets);

    const slider = document.createElement('input');
    slider.type = 'range';
    slider.className = 'boo-props-slider';
    slider.id = 'boo-props-slider';
    slider.min = '1';
    slider.max = '28';
    slider.value = String(penSize);
    slider.addEventListener('input', (e) => setPenSize(Number(e.target.value)));
    sizeSection.appendChild(slider);
    propPopover.appendChild(sizeSection);

    // Color Section
    const colorSection = document.createElement('div');
    colorSection.className = 'boo-props-section';
    colorSection.innerHTML = `<div class="boo-props-label"><span>Цвет</span></div>`;

    const colorGrid = document.createElement('div');
    colorGrid.className = 'boo-props-color-grid';
    COLOR_PRESETS.forEach((c) => {
      const s = document.createElement('button');
      s.type = 'button';
      s.className = 'boo-props-color-swatch' + (penColor.toLowerCase() === c.toLowerCase() ? ' active' : '');
      s.dataset.color = c;
      s.style.backgroundColor = c;
      s.title = c;
      s.addEventListener('click', (e) => {
        e.stopPropagation();
        setPenColor(c);
      });
      colorGrid.appendChild(s);
    });

    const customBtn = document.createElement('label');
    customBtn.className = 'boo-props-custom-color';
    customBtn.title = 'Свой цвет';
    customBtn.innerHTML = `
      <i class="ph-bold ph-plus"></i>
      <input type="color" class="boo-props-color-native-input" value="${penColor}">
    `;
    const nativeColorInput = customBtn.querySelector('input');
    nativeColorInput.addEventListener('input', (e) => setPenColor(e.target.value));
    colorGrid.appendChild(customBtn);
    colorSection.appendChild(colorGrid);
    propPopover.appendChild(colorSection);

    // Style & Smoothing Section
    const styleSection = document.createElement('div');
    styleSection.className = 'boo-props-section';
    styleSection.innerHTML = `
      <div class="boo-props-label"><span>Стиль штриха</span></div>
      <div style="display: flex; gap: 4px;">
        <button type="button" class="boo-confirm-btn ${strokeStyle === 'solid' ? 'boo-confirm-danger' : 'boo-confirm-cancel'}" id="btn-style-solid">Сплошная</button>
        <button type="button" class="boo-confirm-btn ${strokeStyle === 'dashed' ? 'boo-confirm-danger' : 'boo-confirm-cancel'}" id="btn-style-dashed">Штрих</button>
        <button type="button" class="boo-confirm-btn ${strokeStyle === 'sketch' ? 'boo-confirm-danger' : 'boo-confirm-cancel'}" id="btn-style-sketch">Скетч</button>
      </div>
    `;
    function updateStyleBtns(newStyle) {
      strokeStyle = newStyle;
      styleSection.querySelector('#btn-style-solid').className = `boo-confirm-btn ${newStyle === 'solid' ? 'boo-confirm-danger' : 'boo-confirm-cancel'}`;
      styleSection.querySelector('#btn-style-dashed').className = `boo-confirm-btn ${newStyle === 'dashed' ? 'boo-confirm-danger' : 'boo-confirm-cancel'}`;
      styleSection.querySelector('#btn-style-sketch').className = `boo-confirm-btn ${newStyle === 'sketch' ? 'boo-confirm-danger' : 'boo-confirm-cancel'}`;
      if (selectedIds.size > 0) {
        selectedIds.forEach((id) => {
          const s = strokes.find((item) => item.id === id);
          if (s) s.style = newStyle;
        });
        dirty = true;
        saveLocal();
        redraw();
        updateSelectionBox();
        scheduleSave();
      }
    }
    styleSection.querySelector('#btn-style-solid').addEventListener('click', () => updateStyleBtns('solid'));
    styleSection.querySelector('#btn-style-dashed').addEventListener('click', () => updateStyleBtns('dashed'));
    styleSection.querySelector('#btn-style-sketch').addEventListener('click', () => updateStyleBtns('sketch'));
    propPopover.appendChild(styleSection);

    document.body.appendChild(propPopover);
  }

  // --- Multi-Page Navigation Bar (Bottom Center) ---

  function createPagesBar() {
    pagesBar = document.createElement('div');
    pagesBar.className = 'boo-canvas-pages-bar';

    renderPageTabs();
    document.body.appendChild(pagesBar);
  }

  function renderPageTabs() {
    if (!pagesBar) return;
    pagesBar.innerHTML = '';

    pages.forEach((pg, index) => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'boo-page-tab' + (pg.id === currentPageId ? ' active' : '');
      tab.innerHTML = `<span>${pg.title || ('Стр ' + (index + 1))}</span>`;
      tab.addEventListener('click', (e) => {
        e.stopPropagation();
        switchPage(pg.id);
      });
      pagesBar.appendChild(tab);
    });

    // Add page button
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'boo-page-btn';
    addBtn.title = 'Добавить новую страницу';
    addBtn.innerHTML = '<i class="ph-bold ph-plus"></i>';
    addBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      addNewPage();
    });
    pagesBar.appendChild(addBtn);

    // Background switcher button
    const bgBtn = document.createElement('button');
    bgBtn.type = 'button';
    bgBtn.className = 'boo-page-btn';
    bgBtn.title = 'Фон холста (точки, клетка, линейка, координатная)';
    bgBtn.innerHTML = '<i class="ph-bold ph-grid-four"></i>';
    bgBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleBgSelectorPopover();
    });
    pagesBar.appendChild(bgBtn);
  }

  function switchPage(pageId) {
    if (!pageId) return;
    let target = pages.find((p) => p.id === pageId);
    if (!target) {
      target = { id: pageId, title: `Страница ${pages.length + 1}`, background: getActivePage()?.background || 'dots', strokes: [] };
      pages.push(target);
    }
    currentPageId = pageId;
    remoteLiveStrokes.clear();
    syncPageStrokes();
    selectedIds.clear();
    applyCanvasBackground(target.background || 'dots');
    renderPageTabs();
    redraw();
    syncDomWidgets();
    updateSelectionBox();
    updateMinimap();
  }

  function addNewPage(customTitle, customId) {
    const newId = customId || generateId('page');
    const existing = pages.find((p) => p.id === newId);
    if (existing) {
      switchPage(newId);
      return newId;
    }
    const newPage = {
      id: newId,
      title: customTitle || `Страница ${pages.length + 1}`,
      background: getActivePage().background || 'dots',
      strokes: []
    };
    pages.push(newPage);
    switchPage(newId);
    dirty = true;
    saveLocal();
    scheduleSave();
    return newId;
  }

  function deletePage(pageId) {
    if (!pageId || pages.length <= 1) return;
    const idx = pages.findIndex((p) => p.id === pageId);
    if (idx >= 0) {
      pages.splice(idx, 1);
      if (currentPageId === pageId) {
        switchPage(pages[0].id);
      } else {
        renderPageTabs();
      }
      dirty = true;
      saveLocal();
      scheduleSave();
    }
  }

  function applyCanvasBackground(bgType) {
    if (!overlay) return;
    overlay.className = `boo-canvas-overlay boo-bg-${bgType || 'dots'}` + (embeddedTarget ? ' is-embedded' : '') + (isOpen ? ' active' : '');
    const curPage = getActivePage();
    curPage.background = bgType;
  }

  function createBgSelectorPopover() {
    bgSelectorPopover = document.createElement('div');
    bgSelectorPopover.className = 'boo-bg-selector-popover';

    const bgOptions = [
      { id: 'dots', icon: 'ph-circle-notch', name: 'В точку' },
      { id: 'grid', icon: 'ph-grid-four', name: 'В клетку' },
      { id: 'ruled', icon: 'ph-rows', name: 'В линейку' },
      { id: 'millimeter', icon: 'ph-checkerboard', name: 'Миллиметровка' },
      { id: 'coord', icon: 'ph-crosshair', name: 'Координатная' },
      { id: 'plain', icon: 'ph-square', name: 'Чистый белый' }
    ];

    bgOptions.forEach((opt) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'boo-bg-opt';
      b.innerHTML = `<i class="ph-bold ${opt.icon}"></i> <span>${opt.name}</span>`;
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        applyCanvasBackground(opt.id);
        toggleBgSelectorPopover(false);
        dirty = true;
        saveLocal();
        scheduleSave();
      });
      bgSelectorPopover.appendChild(b);
    });

    document.body.appendChild(bgSelectorPopover);
  }

  function toggleBgSelectorPopover(show) {
    if (!bgSelectorPopover) return;
    const next = typeof show === 'boolean' ? show : (bgSelectorPopover.style.display === 'none' || !bgSelectorPopover.classList.contains('active'));
    if (next) {
      if (pagesBar) {
        bgSelectorPopover.style.left = `${pagesBar.offsetLeft + pagesBar.offsetWidth / 2}px`;
        bgSelectorPopover.style.bottom = `${window.innerHeight - pagesBar.offsetTop + 8}px`;
      }
      bgSelectorPopover.style.display = 'grid';
      bgSelectorPopover.classList.add('active');
    } else {
      bgSelectorPopover.style.display = 'none';
      bgSelectorPopover.classList.remove('active');
    }
  }

  // --- Interactive Minimap (Bottom Right) ---

  function createMinimap() {
    minimapEl = document.createElement('div');
    minimapEl.className = 'boo-canvas-minimap';

    minimapCanvas = document.createElement('canvas');
    minimapCanvas.width = 140;
    minimapCanvas.height = 90;
    minimapCtx = minimapCanvas.getContext('2d');
    minimapEl.appendChild(minimapCanvas);

    const vpBox = document.createElement('div');
    vpBox.className = 'boo-minimap-viewport';
    vpBox.id = 'boo-minimap-vp';
    minimapEl.appendChild(vpBox);

    minimapEl.addEventListener('click', (e) => {
      e.stopPropagation();
      fitContentToScreen();
    });

    document.body.appendChild(minimapEl);
  }

  function updateMinimap() {
    if (!minimapCtx || !minimapCanvas) return;
    minimapCtx.clearRect(0, 0, minimapCanvas.width, minimapCanvas.height);

    // Draw small representations of strokes
    minimapCtx.fillStyle = '#6366f1';
    const mw = minimapCanvas.width;
    const mh = minimapCanvas.height;

    strokes.forEach((s) => {
      if (!s.points || s.points.length === 0) return;
      const p = s.points[0];
      const mx = ((p.x % 2000) / 2000) * mw;
      const my = ((p.y % 1200) / 1200) * mh;
      minimapCtx.fillRect(mx, my, 4, 4);
    });

    const vp = document.getElementById('boo-minimap-vp');
    if (vp) {
      vp.style.left = '20px';
      vp.style.top = '15px';
      vp.style.width = '70px';
      vp.style.height = '50px';
    }
  }

  // --- Zoom Island (Bottom Left) ---

  function createZoomIsland() {
    zoomIsland = document.createElement('div');
    zoomIsland.className = 'boo-canvas-zoom-island';

    const zoomOut = document.createElement('button');
    zoomOut.type = 'button';
    zoomOut.className = 'tb-zoom-btn';
    zoomOut.title = 'Уменьшить масштаб (-)';
    zoomOut.innerHTML = '<i class="ph-bold ph-minus"></i>';
    zoomOut.addEventListener('click', (e) => {
      e.stopPropagation();
      zoomBy(1 / 1.2);
    });

    const zoomBadge = document.createElement('button');
    zoomBadge.type = 'button';
    zoomBadge.className = 'tb-zoom-badge';
    zoomBadge.id = 'boo-tb-zoom-label';
    zoomBadge.title = 'Сбросить масштаб (100%)';
    zoomBadge.textContent = '100%';
    zoomBadge.addEventListener('click', (e) => {
      e.stopPropagation();
      resetZoom();
    });

    const zoomIn = document.createElement('button');
    zoomIn.type = 'button';
    zoomIn.className = 'tb-zoom-btn';
    zoomIn.title = 'Увеличить масштаб (+)';
    zoomIn.innerHTML = '<i class="ph-bold ph-plus"></i>';
    zoomIn.addEventListener('click', (e) => {
      e.stopPropagation();
      zoomBy(1.2);
    });

    const fitBtn = document.createElement('button');
    fitBtn.type = 'button';
    fitBtn.className = 'tb-zoom-btn';
    fitBtn.title = 'Подогнать под экран';
    fitBtn.innerHTML = '<i class="ph-bold ph-corners-out"></i>';
    fitBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      fitContentToScreen();
    });

    zoomIsland.append(zoomOut, zoomBadge, zoomIn, fitBtn);
    document.body.appendChild(zoomIsland);
  }

  function fitContentToScreen() {
    if (!strokes.length) {
      resetZoom();
      return;
    }
    viewScale = 1;
    viewOffsetX = 0;
    viewOffsetY = 0;
    updateZoomBadge();
    redraw();
    updateSelectionBox();
  }

  // --- Tool Catalog Modal (Ctrl+K) ---

  function createCatalogModal() {
    catalogModal = document.createElement('div');
    catalogModal.className = 'boo-canvas-catalog-overlay';
    catalogModal.style.display = 'none';

    const modal = document.createElement('div');
    modal.className = 'boo-canvas-catalog-modal';
    modal.innerHTML = `
      <div class="boo-catalog-header">
        <div class="boo-catalog-title"><i class="ph-bold ph-squares-four"></i> Каталог инструментов BooStudy Whiteboard</div>
        <div class="boo-catalog-search">
          <i class="ph-bold ph-magnifying-glass"></i>
          <input type="text" id="boo-catalog-filter" placeholder="Поиск инструментов (Ctrl+K)...">
        </div>
        <button type="button" class="boo-catalog-close" id="boo-catalog-close-btn">&times;</button>
      </div>
      <div class="boo-catalog-tabs">
        <button type="button" class="boo-cat-tab active" data-tab="all">Все</button>
        <button type="button" class="boo-cat-tab" data-tab="math">Математика</button>
        <button type="button" class="boo-cat-tab" data-tab="cs">Информатика</button>
        <button type="button" class="boo-cat-tab" data-tab="shapes">Фигуры 2D/3D</button>
        <button type="button" class="boo-cat-tab" data-tab="widgets">Интерактив</button>
      </div>
      <div class="boo-catalog-body" id="boo-catalog-grid"></div>
    `;

    modal.querySelector('#boo-catalog-close-btn').addEventListener('click', () => closeCatalogModal());
    modal.querySelectorAll('.boo-cat-tab').forEach((tabBtn) => {
      tabBtn.addEventListener('click', () => {
        modal.querySelectorAll('.boo-cat-tab').forEach((t) => t.classList.remove('active'));
        tabBtn.classList.add('active');
        populateCatalogGrid(tabBtn.dataset.tab, modal.querySelector('#boo-catalog-filter').value);
      });
    });

    modal.querySelector('#boo-catalog-filter').addEventListener('input', (e) => {
      const activeTab = modal.querySelector('.boo-cat-tab.active')?.dataset.tab || 'all';
      populateCatalogGrid(activeTab, e.target.value);
    });

    catalogModal.appendChild(modal);
    document.body.appendChild(catalogModal);

    populateCatalogGrid('all');
  }

  const CATALOG_ITEMS = [
    // Math
    { id: 'math', cat: 'math', icon: 'ph-function', name: 'Редактор формул LaTeX', desc: 'Визуальный ввод дробей, степеней, интегралов и матриц' },
    { id: 'function_graph', cat: 'math', icon: 'ph-chart-line', name: 'График функции y=f(x)', desc: 'Интерактивное построение функций на декартовой плоскости' },
    { id: 'number_line', cat: 'math', icon: 'ph-arrows-horizontal', name: 'Числовая прямая', desc: 'Интервалы, неравенства и координатные отметки' },

    // CS & Informatics
    { id: 'truth_table', cat: 'cs', icon: 'ph-table', name: 'Таблица истинности', desc: 'Автоматический расчёт логических выражений' },
    { id: 'logic_gates', cat: 'cs', icon: 'ph-cpu', name: 'Логические схемы AND/OR/NOT', desc: 'Симулятор логических элементов с живыми проводами' },
    { id: 'binary_calc', cat: 'cs', icon: 'ph-binary', name: 'Двоичный калькулятор', desc: 'Перевод систем счисления (2, 8, 10, 16) и побитовые операции' },
    { id: 'fano_tree', cat: 'cs', icon: 'ph-tree-structure', name: 'Дерево Фано', desc: 'Построение кодовых деревьев и проверка условия префиксности' },
    { id: 'graph', cat: 'cs', icon: 'ph-graph', name: 'Граф и алгоритм Дейкстры', desc: 'Вершины, рёбра, матрица смежности и поиск путей' },
    { id: 'turtle', cat: 'cs', icon: 'ph-navigation-arrow', name: 'Исполнитель Черепаха', desc: 'Пошаговое выполнение алгоритмов движения' },

    // Interactive & Widgets
    { id: 'flashcard', cat: 'widgets', icon: 'ph-cards', name: 'Флеш-карточка', desc: 'Переворачиваемая двусторонняя обучающая карточка' },
    { id: 'spoiler', cat: 'widgets', icon: 'ph-eye-slash', name: 'Спойлер со скрытым ответом', desc: 'Блок с размытием, открывающийся по клику' },
    { id: 'checklist', cat: 'widgets', icon: 'ph-check-square', name: 'Чек-лист', desc: 'Интерактивный список с галочками' },
    { id: 'counter', cat: 'widgets', icon: 'ph-plus-minus', name: 'Интерактивный счётчик', desc: 'Табло с кнопками увеличения и уменьшения' },
    { id: 'timer', cat: 'widgets', icon: 'ph-timer', name: 'Таймер и секундомер', desc: 'Обратный отсчёт времени для самостоятельной работы' },
    { id: 'dice', cat: 'widgets', icon: 'ph-cube', name: 'Виртуальный кубик / ГСЧ', desc: 'Случайное число от 1 до 6 для игровых механик' },

    // Shapes
    { id: 'cube', cat: 'shapes', icon: 'ph-cube', name: '3D Куб', desc: 'Проекция куба со скрытыми штриховыми линиями' },
    { id: 'cylinder', cat: 'shapes', icon: 'ph-cylinder', name: '3D Цилиндр', desc: 'Геометрический цилиндр с верхним и нижним основанием' },
    { id: 'cone', cat: 'shapes', icon: 'ph-funnel', name: '3D Конус', desc: 'Конус с вершиной и основанием' },
    { id: 'pyramid', cat: 'shapes', icon: 'ph-triangle', name: '3D Пирамида', desc: 'Пирамида с рёбрами и высотой' },
    { id: 'process', cat: 'shapes', icon: 'ph-square', name: 'Блок процесса', desc: 'Прямоугольный блок алгоритма' },
    { id: 'decision', cat: 'shapes', icon: 'ph-diamond', name: 'Блок условия', desc: 'Ромб ветвления блок-схемы' },
  ];

  function populateCatalogGrid(filterCat = 'all', searchQuery = '') {
    const grid = document.getElementById('boo-catalog-grid');
    if (!grid) return;
    grid.innerHTML = '';

    const query = searchQuery.trim().toLowerCase();
    const filtered = CATALOG_ITEMS.filter((item) => {
      const matchCat = filterCat === 'all' || item.cat === filterCat;
      const matchText = !query || item.name.toLowerCase().includes(query) || item.desc.toLowerCase().includes(query);
      return matchCat && matchText;
    });

    filtered.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'boo-tool-card';
      card.innerHTML = `
        <i class="ph-bold ${item.icon}"></i>
        <strong>${item.name}</strong>
        <p>${item.desc}</p>
      `;
      card.addEventListener('click', () => {
        closeCatalogModal();
        activateCatalogItem(item.id);
      });
      grid.appendChild(card);
    });
  }

  function activateCatalogItem(itemId) {
    if (['cube', 'cylinder', 'cone', 'pyramid', 'process', 'decision'].includes(itemId)) {
      currentShape = itemId;
      setTool('shape');
    } else if (itemId === 'math') {
      openMathModal();
    } else {
      // Create widget at canvas center
      insertInteractiveWidget(itemId);
    }
  }

  function openCatalogModal() {
    if (catalogModal) {
      catalogModal.style.display = 'flex';
      catalogModal.classList.add('active');
    }
  }

  function closeCatalogModal() {
    if (catalogModal) {
      catalogModal.style.display = 'none';
      catalogModal.classList.remove('active');
    }
  }

  // --- Interactive Widgets Insertion & Logic ---

  function insertInteractiveWidget(type) {
    const space = getActiveTaskContentRect();
    const origin = canvasOrigin();
    const centerEv = { pageX: origin.left + window.innerWidth / 3, pageY: origin.top + window.innerHeight / 3 };
    const p1 = pointForEvent(centerEv, space);

    const widget = {
      id: generateId('wdg_' + type),
      type: 'widget',
      widgetType: type,
      points: [p1, { x: p1.x + 240 / viewScale, y: p1.y + 160 / viewScale }],
      data: getInitialWidgetData(type),
      space: space ? { left: space.left, top: space.top, width: space.width, height: space.height, task_id: space.task_id } : null,
    };

    strokes.push(widget);
    selectedIds.clear();
    selectedIds.add(widget.id);
    setTool('select');
    dirty = true;
    saveLocal();
    redraw();
    updateSelectionBox();
    scheduleSave();
  }

  function getInitialWidgetData(type) {
    if (type === 'flashcard') return { front: 'Формула корней квадратного уравнения', back: 'x = (-b ± √D) / (2a)\nD = b² - 4ac', flipped: false };
    if (type === 'spoiler') return { text: 'Правильный ответ: 42 (нажмите, чтобы скрыть)', revealed: false };
    if (type === 'checklist') return { items: [{ text: 'Проверить ОДЗ', done: true }, { text: 'Найти корни производной', done: false }, { text: 'Записать ответ', done: false }] };
    if (type === 'counter') return { count: 0 };
    if (type === 'timer') return { seconds: 300, running: false };
    if (type === 'dice') return { value: 6 };
    if (type === 'truth_table') return { formula: '(A and B) or not C', vars: ['A', 'B', 'C'] };
    if (type === 'logic_gates') return { in1: 1, in2: 0, gate: 'AND' };
    if (type === 'binary_calc') return { value: 25 };
    if (type === 'function_graph') return { expr: 'x*x - 4' };
    if (type === 'number_line') return { from: -5, to: 5, interval: [1, 4] };
    if (type === 'fano_tree') return { codes: { A: '00', B: '01', C: '1' } };
    return {};
  }

  // --- Eraser Menu & Thickness Control ---

  function createEraserMenu() {
    eraserMenu = document.createElement('div');
    eraserMenu.className = 'boo-canvas-eraser-menu';
    eraserMenu.style.display = 'none';

    // 1. Mode Selector (Strokes / Objects)
    const modeSec = document.createElement('div');
    modeSec.className = 'boo-eraser-menu-section';
    modeSec.innerHTML = `
      <div class="boo-eraser-menu-label">
        <span>Режим ластика</span>
      </div>
      <div class="boo-eraser-mode-group">
        <button type="button" class="boo-eraser-mode-btn" data-mode="eraser_stroke" title="Стирать нарисованные линии как обычной стёркой">
          <i class="ph-bold ph-eraser"></i>
          <span>Штрихи</span>
        </button>
        <button type="button" class="boo-eraser-mode-btn" data-mode="eraser_object" title="Удалять целый объект (фигуру, стикер, линию) в 1 клик">
          <i class="ph-bold ph-trash"></i>
          <span>Объекты</span>
        </button>
      </div>
    `;
    modeSec.querySelectorAll('.boo-eraser-mode-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        setTool(btn.dataset.mode);
        updateEraserUi();
      });
    });
    eraserMenu.appendChild(modeSec);

    // 2. Thickness / Size Section
    const sizeSec = document.createElement('div');
    sizeSec.className = 'boo-eraser-menu-section';
    sizeSec.innerHTML = `
      <div class="boo-eraser-menu-label">
        <span>Толщина ластика</span>
        <span class="boo-eraser-size-val" id="boo-eraser-size-text">${eraserSize}px</span>
      </div>
      <div class="boo-eraser-size-presets">
        <button type="button" class="boo-eraser-size-btn" data-size="12" title="Тонкий (12px)">
          <span class="boo-eraser-dot" style="width: 8px; height: 8px;"></span>
          <span>12</span>
        </button>
        <button type="button" class="boo-eraser-size-btn" data-size="24" title="Стандартный (24px)">
          <span class="boo-eraser-dot" style="width: 14px; height: 14px;"></span>
          <span>24</span>
        </button>
        <button type="button" class="boo-eraser-size-btn" data-size="48" title="Широкий (48px)">
          <span class="boo-eraser-dot" style="width: 22px; height: 22px;"></span>
          <span>48</span>
        </button>
        <button type="button" class="boo-eraser-size-btn" data-size="80" title="Очень широкий (80px)">
          <span class="boo-eraser-dot" style="width: 30px; height: 30px;"></span>
          <span>80</span>
        </button>
      </div>
      <div class="boo-eraser-slider-row">
        <input type="range" class="boo-eraser-slider" id="boo-eraser-slider" min="6" max="100" step="2" value="${eraserSize}">
      </div>
      <div class="boo-eraser-preview-wrap">
        <div class="boo-eraser-preview-dot" id="boo-eraser-preview-dot"></div>
      </div>
    `;

    sizeSec.querySelectorAll('.boo-eraser-size-btn').forEach((b) => {
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        setEraserSize(Number(b.dataset.size));
      });
    });

    const slider = sizeSec.querySelector('#boo-eraser-slider');
    slider.addEventListener('input', (e) => {
      setEraserSize(Number(e.target.value));
    });

    eraserMenu.appendChild(sizeSec);
    document.body.appendChild(eraserMenu);
  }

  function setEraserSize(size) {
    eraserSize = Math.max(6, Math.min(100, Math.round(size)));
    try {
      localStorage.setItem('boo_whiteboard_eraser_size', String(eraserSize));
    } catch (e) {}
    updateEraserUi();
  }

  function updateEraserUi() {
    const txt = document.getElementById('boo-eraser-size-text');
    if (txt) txt.textContent = `${eraserSize}px`;

    const slider = document.getElementById('boo-eraser-slider');
    if (slider) slider.value = String(eraserSize);

    if (eraserMenu) {
      eraserMenu.querySelectorAll('.boo-eraser-size-btn').forEach((b) => {
        b.classList.toggle('active', Number(b.dataset.size) === eraserSize);
      });
      eraserMenu.querySelectorAll('.boo-eraser-mode-btn').forEach((b) => {
        b.classList.toggle('active', b.dataset.mode === (tool === 'eraser_object' ? 'eraser_object' : 'eraser_stroke'));
      });
      const dot = document.getElementById('boo-eraser-preview-dot');
      if (dot) {
        const visualSize = Math.max(6, Math.min(48, eraserSize));
        dot.style.width = `${visualSize}px`;
        dot.style.height = `${visualSize}px`;
      }
    }

    const eraserBtn = document.getElementById('boo-tb-eraser');
    if (eraserBtn) {
      eraserBtn.title = `Ластик (E) — ${eraserSize}px`;
    }
  }

  function toggleEraserMenu(show) {
    if (!eraserMenu || !toolbar) return;
    const isCurrentlyActive = eraserMenu.classList.contains('active') && eraserMenu.style.display !== 'none';
    const next = typeof show === 'boolean' ? show : !isCurrentlyActive;
    if (next) {
      toggleBrushMenu(false);
      toggleShapesMenu(false);
      toggleLaserMenu(false);
      toggleMoreMenu(false);
      togglePropPopover(false);
      toggleClearConfirm(false);
      updateEraserUi();
      const eraserBtn = document.getElementById('boo-tb-eraser');
      eraserMenu.style.display = 'flex';
      eraserMenu.classList.add('active');
      positionFlyoutNextTo(eraserMenu, eraserBtn);
    } else {
      eraserMenu.style.display = 'none';
      eraserMenu.classList.remove('active');
    }
  }

  // --- Expandable "More Tools" Flyout Panel ---

  function createMoreMenu() {
    moreMenu = document.createElement('div');
    moreMenu.className = 'boo-canvas-more-menu';
    moreMenu.style.display = 'none';

    const header = document.createElement('div');
    header.className = 'boo-more-menu-header';
    header.innerHTML = `<span>Дополнительные инструменты</span>`;
    moreMenu.appendChild(header);

    const list = document.createElement('div');
    list.className = 'boo-more-menu-list';

    const items = [
      {
        id: 'connector',
        icon: 'ph-arrow-up-right',
        title: 'Стрелка / Соединитель',
        badge: 'A',
        action: () => { setTool('connector'); toggleMoreMenu(false); },
      },
      {
        id: 'note',
        icon: 'ph-notepad',
        title: 'Стикер / Заметка',
        badge: 'S',
        action: () => { setTool('note'); toggleMoreMenu(false); },
      },
      {
        id: 'text',
        icon: 'ph-text-t',
        title: 'Текст',
        badge: 'T',
        action: () => { setTool('text'); toggleMoreMenu(false); },
      },
      {
        id: 'math',
        icon: 'ph-function',
        title: 'Формула LaTeX / Математика',
        badge: 'F',
        action: () => { openMathModal(); toggleMoreMenu(false); },
      },
      {
        id: 'laser',
        icon: 'ph-sparkle',
        title: 'Лазерная указка',
        badge: 'L',
        action: () => {
          if (tool !== 'laser') setTool('laser');
          toggleLaserMenu();
          toggleMoreMenu(false);
        },
      },
      {
        id: 'eyedropper',
        icon: 'ph-eyedropper',
        title: 'Пипетка цвета',
        badge: '',
        action: () => { setTool('eyedropper'); toggleMoreMenu(false); },
      },
      {
        id: 'image',
        icon: 'ph-image',
        title: 'Вставить изображение',
        badge: 'I',
        action: () => { hiddenFileInput?.click(); toggleMoreMenu(false); },
      },
    ];

    items.forEach((it) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'boo-more-item-btn';
      btn.dataset.toolId = it.id;
      btn.innerHTML = `
        <i class="ph-bold ${it.icon}"></i>
        <span class="boo-more-item-label">${it.title}</span>
        ${it.badge ? `<kbd class="boo-more-kbd">${it.badge}</kbd>` : ''}
      `;
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        it.action();
      });
      list.appendChild(btn);
    });

    const sep = document.createElement('div');
    sep.className = 'boo-more-menu-sep';
    list.appendChild(sep);

    // Catalog placeholder (Clock icon, unclickable / disabled)
    const clockBtn = document.createElement('button');
    clockBtn.type = 'button';
    clockBtn.className = 'boo-more-item-btn is-placeholder';
    clockBtn.disabled = true;
    clockBtn.title = 'Каталог инструментов (скоро)';
    clockBtn.innerHTML = `
      <i class="ph-bold ph-clock"></i>
      <span class="boo-more-item-label">Каталог инструментов</span>
      <span class="boo-more-soon-badge">скоро</span>
    `;
    list.appendChild(clockBtn);

    moreMenu.appendChild(list);
    document.body.appendChild(moreMenu);
  }

  function toggleMoreMenu(show) {
    if (!moreMenu || !toolbar) return;
    const isCurrentlyActive = moreMenu.classList.contains('active') && moreMenu.style.display !== 'none';
    const next = typeof show === 'boolean' ? show : !isCurrentlyActive;
    if (next) {
      toggleBrushMenu(false);
      toggleShapesMenu(false);
      toggleLaserMenu(false);
      toggleEraserMenu(false);
      togglePropPopover(false);
      toggleClearConfirm(false);
      updateMoreMenuUi();
      const moreBtn = document.getElementById('boo-tb-more');
      moreMenu.style.display = 'flex';
      moreMenu.classList.add('active');
      positionFlyoutNextTo(moreMenu, moreBtn);
    } else {
      moreMenu.style.display = 'none';
      moreMenu.classList.remove('active');
    }
  }

  function updateMoreMenuUi() {
    if (!moreMenu) return;
    const moreToolIds = ['connector', 'note', 'text', 'laser', 'eyedropper'];
    moreMenu.querySelectorAll('.boo-more-item-btn').forEach((btn) => {
      const tId = btn.dataset.toolId;
      if (!tId) return;
      btn.classList.toggle('active', tool === tId);
    });
    const moreBtn = document.getElementById('boo-tb-more');
    if (moreBtn) {
      moreBtn.classList.toggle('active', moreToolIds.includes(tool));
    }
  }

  // --- LaTeX Formula Editor Modal ---

  function createMathModal() {
    mathModal = document.createElement('div');
    mathModal.className = 'boo-canvas-catalog-overlay boo-canvas-math-modal';
    mathModal.style.display = 'none';

    const modal = document.createElement('div');
    modal.className = 'boo-canvas-catalog-modal';
    modal.style.maxWidth = '540px';
    modal.innerHTML = `
      <div class="boo-catalog-header">
        <div class="boo-catalog-title"><i class="ph-bold ph-function"></i> Редактор математических формул (LaTeX)</div>
        <button type="button" class="boo-catalog-close" id="boo-math-close-btn">&times;</button>
      </div>
      <div style="padding: 16px 20px; display: flex; flex-direction: column; gap: 12px;">
        <div style="display: flex; gap: 5px; flex-wrap: wrap;">
          <button type="button" class="boo-cat-tab" data-snippet="\\frac{a}{b}">a/b (Дробь)</button>
          <button type="button" class="boo-cat-tab" data-snippet="x^{2}">x² (Степень)</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\sqrt{x}">√x (Корень)</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\sum_{i=1}^{n}">∑</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\lim_{x \\to \\infty}">lim</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\int_{a}^{b}">∫</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\land">∧ (И)</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\lor">∨ (ИЛИ)</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\neg">¬ (НЕ)</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\in">∈</button>
          <button type="button" class="boo-cat-tab" data-snippet="\\cup">∪</button>
        </div>
        <textarea id="boo-math-latex-input" style="width: 100%; height: 90px; padding: 10px; font-family: ui-monospace, monospace; font-size: 13px; border: 1px solid #cbd5e1; border-radius: 10px; outline: none;" placeholder="Введите формулу в формате LaTeX, например: x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}">x = \\frac{-b \\pm \\sqrt{D}}{2a}</textarea>
        <div id="boo-math-preview-render" style="min-height: 44px; padding: 10px; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 16px;"></div>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <button type="button" class="boo-confirm-btn boo-confirm-cancel" id="boo-math-cancel-btn">Отмена</button>
          <button type="button" class="boo-confirm-btn boo-confirm-danger" id="boo-math-insert-btn">Вставить на доску</button>
        </div>
      </div>
    `;

    modal.querySelector('#boo-math-close-btn').addEventListener('click', () => closeMathModal());
    modal.querySelector('#boo-math-cancel-btn').addEventListener('click', () => closeMathModal());

    const input = modal.querySelector('#boo-math-latex-input');
    const preview = modal.querySelector('#boo-math-preview-render');

    modal.querySelectorAll('[data-snippet]').forEach((b) => {
      b.addEventListener('click', () => {
        input.value += b.dataset.snippet;
        updateMathPreview();
      });
    });

    input.addEventListener('input', () => updateMathPreview());

    const insertBtn = modal.querySelector('#boo-math-insert-btn');
    insertBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      try {
        const latex = input.value.trim();
        if (latex) {
          insertMathFormula(latex, editingMathObj?.id);
        }
      } catch (err) {
        console.error('Error inserting math formula:', err);
      } finally {
        closeMathModal();
      }
    });

    input.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        insertBtn.click();
      }
    });

    mathModal.appendChild(modal);
    document.body.appendChild(mathModal);

    function updateMathPreview() {
      const val = input.value.trim();
      if (window.katex && typeof window.katex.renderToString === 'function') {
        try {
          preview.innerHTML = window.katex.renderToString(val, { displayMode: true, throwOnError: false });
        } catch (e) {
          preview.textContent = val;
        }
      } else {
        preview.textContent = `$${val}$`;
        ensureKaTeXLoaded(updateMathPreview);
      }
    }
  }

  let editingMathObj = null;
  let katexLoadingPromise = null;

  function ensureKaTeXLoaded(callback) {
    if (window.katex && typeof window.katex.renderToString === 'function') {
      if (typeof callback === 'function') callback();
      return;
    }
    if (!katexLoadingPromise) {
      katexLoadingPromise = new Promise((resolve) => {
        if (!document.querySelector('link[href*="katex"]')) {
          const link = document.createElement('link');
          link.rel = 'stylesheet';
          link.href = '/static/katex/katex/katex.css';
          document.head.appendChild(link);
        }
        if (!window.katex) {
          const script = document.createElement('script');
          script.src = '/static/katex/katex/katex.js';
          script.onload = () => {
            resolve(true);
            syncDomWidgets();
          };
          script.onerror = () => resolve(false);
          document.head.appendChild(script);
        } else {
          resolve(true);
        }
      });
    }
    if (typeof callback === 'function') {
      katexLoadingPromise.then(() => {
        if (window.katex) callback();
      });
    }
  }

  function openMathModal(mathObj) {
    editingMathObj = mathObj || null;
    const input = mathModal?.querySelector('#boo-math-latex-input');
    const insertBtn = mathModal?.querySelector('#boo-math-insert-btn');
    if (input) {
      input.value = mathObj ? (mathObj.latex || '') : 'x = \\frac{-b \\pm \\sqrt{D}}{2a}';
    }
    if (insertBtn) {
      insertBtn.textContent = mathObj ? 'Сохранить изменения' : 'Вставить на доску';
    }
    const preview = mathModal?.querySelector('#boo-math-preview-render');
    if (preview && input) {
      const updatePreview = () => {
        const val = input.value.trim();
        if (window.katex && typeof window.katex.renderToString === 'function') {
          try {
            preview.innerHTML = window.katex.renderToString(val, { displayMode: true, throwOnError: false });
          } catch (_) { preview.textContent = val; }
        } else {
          preview.textContent = `$${val}$`;
          ensureKaTeXLoaded(updatePreview);
        }
      };
      updatePreview();
    }
    if (mathModal) {
      mathModal.style.display = 'flex';
      mathModal.classList.add('active');
    }
    setTimeout(() => {
      input?.focus();
      input?.select();
    }, 50);
  }

  function closeMathModal() {
    editingMathObj = null;
    if (mathModal) {
      mathModal.style.display = 'none';
      mathModal.classList.remove('active');
    }
  }

  function insertMathFormula(latex, existingId) {
    if (existingId) {
      const existing = strokes.find((s) => s.id === existingId);
      if (existing) {
        existing.latex = latex;
        dirty = true;
        saveLocal();
        redraw();
        syncDomWidgets();
        updateSelectionBox();
        scheduleSave();
        return;
      }
    }

    const space = getActiveTaskContentRect();
    const origin = canvasOrigin();
    const width = canvas ? (canvas.width / Math.max(dpr, 1)) : (embeddedTarget ? embeddedTarget.clientWidth : window.innerWidth);
    const height = canvas ? (canvas.height / Math.max(dpr, 1)) : (embeddedTarget ? embeddedTarget.clientHeight : window.innerHeight);

    const centerEv = {
      pageX: origin.left + width / 2,
      pageY: origin.top + height / 2,
      clientX: origin.left - window.scrollX + width / 2,
      clientY: origin.top - window.scrollY + height / 2,
    };
    const p1 = pointForEvent(centerEv, space);
    const mathW = 200 / Math.max(viewScale, 0.1);
    const mathH = 60 / Math.max(viewScale, 0.1);
    const startX = p1.x - mathW / 2;
    const startY = p1.y - mathH / 2;
    const pt1 = {
      x: startX,
      y: startY,
    };
    if (space) {
      pt1.rx = (startX - space.left) / Math.max(space.width, 1);
      pt1.ry = (startY - space.top) / Math.max(space.height, 1);
    }
    const pt2 = {
      x: startX + mathW,
      y: startY + mathH,
    };
    if (space) {
      pt2.rx = (startX + mathW - space.left) / Math.max(space.width, 1);
      pt2.ry = (startY + mathH - space.top) / Math.max(space.height, 1);
    }

    const mathObj = {
      id: generateId('math'),
      page_id: currentPageId,
      type: 'math',
      latex,
      fontSize: 22,
      color: '#0f172a',
      points: [pt1, pt2],
      space: space ? { left: space.left, top: space.top, width: space.width, height: space.height, task_id: space.task_id } : null,
    };

    strokes.push(mathObj);
    const curPage = getActivePage();
    if (curPage) {
      curPage.strokes = strokes;
    }
    selectedIds.clear();
    selectedIds.add(mathObj.id);
    setTool('select');
    dirty = true;
    saveLocal();
    redraw();
    syncDomWidgets();
    updateSelectionBox();
    scheduleSave();
    realtimeSyncAdapter?.onStrokeCommit?.(mathObj);
  }

  // --- Export Modal (PNG, SVG, PDF, JSON) ---

  function createExportModal() {
    exportModal = document.createElement('div');
    exportModal.className = 'boo-canvas-catalog-overlay';
    exportModal.style.display = 'none';

    const modal = document.createElement('div');
    modal.className = 'boo-canvas-export-modal';
    modal.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <strong style="font-size: 15px; color: #0f172a;"><i class="ph-bold ph-export"></i> Экспорт доски BooStudy</strong>
        <button type="button" class="boo-catalog-close" id="boo-export-close-btn">&times;</button>
      </div>
      <p style="font-size: 12px; color: #64748b; margin: 0;">Выберите формат для сохранения конспекта или решения:</p>
      <div class="boo-export-options">
        <button type="button" class="boo-export-btn" id="boo-exp-png"><i class="ph-bold ph-file-png"></i> <span>Изображение PNG</span></button>
        <button type="button" class="boo-export-btn" id="boo-exp-svg"><i class="ph-bold ph-file-svg"></i> <span>Векторный SVG</span></button>
        <button type="button" class="boo-export-btn" id="boo-exp-pdf"><i class="ph-bold ph-file-pdf"></i> <span>Документ PDF</span></button>
        <button type="button" class="boo-export-btn" id="boo-exp-json"><i class="ph-bold ph-file-code"></i> <span>Файл проекта BooStudy (.json)</span></button>
      </div>
    `;

    modal.querySelector('#boo-export-close-btn').addEventListener('click', () => closeExportModal());
    modal.querySelector('#boo-exp-png').addEventListener('click', () => { exportPNG(); closeExportModal(); });
    modal.querySelector('#boo-exp-svg').addEventListener('click', () => { exportSVG(); closeExportModal(); });
    modal.querySelector('#boo-exp-pdf').addEventListener('click', () => { exportPDF(); closeExportModal(); });
    modal.querySelector('#boo-exp-json').addEventListener('click', () => { exportJSON(); closeExportModal(); });

    exportModal.appendChild(modal);
    document.body.appendChild(exportModal);
  }

  function openExportModal() {
    if (exportModal) {
      exportModal.style.display = 'flex';
      exportModal.classList.add('active');
    }
  }

  function closeExportModal() {
    if (exportModal) {
      exportModal.style.display = 'none';
      exportModal.classList.remove('active');
    }
  }

  function exportPNG() {
    if (!canvas) return;
    const link = document.createElement('a');
    link.download = `boostudy_whiteboard_${Date.now()}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }

  function exportSVG() {
    let svgContent = `<svg xmlns="http://www.w3.org/2000/svg" width="${canvas.width}" height="${canvas.height}">\n`;
    svgContent += `<rect width="100%" height="100%" fill="#ffffff" />\n`;
    strokes.forEach((s) => {
      if (s.points && s.points.length > 1) {
        const d = s.points.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
        svgContent += `<path d="${d}" stroke="${s.color || '#000'}" stroke-width="${s.width || 3}" fill="none" stroke-linecap="round" />\n`;
      }
    });
    svgContent += `</svg>`;
    const blob = new Blob([svgContent], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.download = `boostudy_whiteboard_${Date.now()}.svg`;
    link.href = url;
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportPDF() {
    window.print();
  }

  function exportJSON() {
    const data = {
      version: 2,
      pages,
      currentPageId,
      strokes,
      createdAt: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.download = `boostudy_board_${Date.now()}.json`;
    link.href = url;
    link.click();
    URL.revokeObjectURL(url);
  }

  // --- Laser Pointer Animation Loop & Rendering (ALWAYS Topmost) ---

  function drawLaserTop() {
    if (!laserCtx || !laserCanvas) return;

    if (embeddedTarget) {
      const arena = embeddedTarget.closest('#trainer-arena-view');
      if (arena && laserCanvas.parentElement !== arena) {
        arena.appendChild(laserCanvas);
        laserCanvas.style.position = 'absolute';
        laserCanvas.style.zIndex = '999999';
        laserCanvas.style.pointerEvents = 'none';
      }
      if (arena) {
        const origin = canvasOrigin();
        const aRect = arena.getBoundingClientRect();
        laserCanvas.style.left = `${origin.left - aRect.left}px`;
        laserCanvas.style.top = `${origin.top - aRect.top}px`;
      }
    }

    if (canvas && (laserCanvas.width !== canvas.width || laserCanvas.height !== canvas.height)) {
      laserCanvas.width = canvas.width;
      laserCanvas.height = canvas.height;
      laserCanvas.style.width = canvas.style.width;
      laserCanvas.style.height = canvas.style.height;
    }

    if (laserTrail.length === 0) {
      if (!laserCleared) {
        laserCtx.setTransform(1, 0, 0, 1, 0, 0);
        laserCtx.clearRect(0, 0, laserCanvas.width, laserCanvas.height);
        laserCleared = true;
      }
      return;
    }

    laserCleared = false;
    laserCtx.setTransform(1, 0, 0, 1, 0, 0);
    laserCtx.clearRect(0, 0, laserCanvas.width, laserCanvas.height);

    laserCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    laserCtx.lineCap = 'round';
    laserCtx.lineJoin = 'round';

    let offsetX = 0;
    let offsetY = 0;
    if (laserCanvas.parentElement && laserCanvas.parentElement.id === 'lesson-os-top-laser-layer') {
      const topRect = laserCanvas.parentElement.getBoundingClientRect();
      const origin = canvasOrigin();
      offsetX = origin.left - topRect.left;
      offsetY = origin.top - topRect.top;
    }

    const now = Date.now();
    const lColor = (interactionMode === 'laser' ? laserColor : (remoteLaserColor || laserColor)) || '#ef4444';
    const baseWidth = Math.max(3, (interactionMode === 'laser' ? laserWidth : (remoteLaserWidth || laserWidth || 6)));

    if (laserTrail.length > 1) {
      // Pass 1: Outer neon glowing bloom
      laserCtx.save();
      laserCtx.shadowColor = lColor;
      laserCtx.shadowBlur = 14;
      for (let i = 0; i < laserTrail.length - 1; i++) {
        const p1 = laserTrail[i];
        const p2 = laserTrail[i + 1];
        if (p2.isStart) continue;
        const age = now - p2.t;
        if (age >= 1200) continue;
        const alpha = Math.max(0, 1 - age / 1200);

        laserCtx.beginPath();
        laserCtx.strokeStyle = hexToRgba(lColor, alpha * 0.7);
        laserCtx.lineWidth = Math.max(2, baseWidth * 1.5 * alpha);
        laserCtx.moveTo(p1.x + offsetX, p1.y + offsetY);
        laserCtx.lineTo(p2.x + offsetX, p2.y + offsetY);
        laserCtx.stroke();
      }
      laserCtx.restore();

      // Pass 2: Intense white-hot core
      laserCtx.save();
      laserCtx.shadowColor = '#ffffff';
      laserCtx.shadowBlur = 6;
      for (let i = 0; i < laserTrail.length - 1; i++) {
        const p1 = laserTrail[i];
        const p2 = laserTrail[i + 1];
        if (p2.isStart) continue;
        const age = now - p2.t;
        if (age >= 1200) continue;
        const alpha = Math.max(0, 1 - age / 1200);

        laserCtx.beginPath();
        laserCtx.strokeStyle = `rgba(255, 255, 255, ${alpha * 0.9})`;
        laserCtx.lineWidth = Math.max(1, baseWidth * 0.45 * alpha);
        laserCtx.moveTo(p1.x + offsetX, p1.y + offsetY);
        laserCtx.lineTo(p2.x + offsetX, p2.y + offsetY);
        laserCtx.stroke();
      }
      laserCtx.restore();
    }

    // Pass 3: Glowing laser head dot at current dragging tip
    if (laserTrail.length > 0) {
      const tip = laserTrail[laserTrail.length - 1];
      laserCtx.save();
      laserCtx.beginPath();
      laserCtx.arc(tip.x + offsetX, tip.y + offsetY, baseWidth * 0.85, 0, Math.PI * 2);
      laserCtx.fillStyle = '#ffffff';
      laserCtx.shadowColor = lColor;
      laserCtx.shadowBlur = 16;
      laserCtx.fill();
      laserCtx.restore();
    }
  }

  function startLaserLoop() {
    function loop() {
      const now = Date.now();
      if (laserTrail.length > 0) {
        laserTrail = laserTrail.filter((p) => now - p.t < 1200);
        drawLaserTop();
      } else if (!laserCleared) {
        drawLaserTop();
      }
      laserAnimFrame = requestAnimationFrame(loop);
    }
    laserAnimFrame = requestAnimationFrame(loop);
  }

  // --- Rendering Engine ---

  function hexToRgba(hex, alpha = 1) {
    if (!hex || typeof hex !== 'string') return `rgba(239, 68, 68, ${alpha})`;
    if (!hex.startsWith('#')) return hex;
    const h = hex.replace('#', '');
    const r = parseInt(h.length === 3 ? h[0] + h[0] : h.substring(0, 2), 16) || 0;
    const g = parseInt(h.length === 3 ? h[1] + h[1] : h.substring(2, 4), 16) || 0;
    const b = parseInt(h.length === 3 ? h[2] + h[2] : h.substring(4, 6), 16) || 0;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function syncCanvasBackgroundTransform() {
    if (!overlay) return;
    const curPage = getActivePage();
    const bgType = curPage.background || 'dots';
    if (bgType === 'plain') {
      overlay.style.backgroundPosition = '';
      overlay.style.backgroundSize = '';
      return;
    }
    const baseSize = (bgType === 'ruled') ? 28 : (bgType === 'millimeter' || bgType === 'coord' ? 40 : 24);
    const curSize = baseSize * viewScale;
    const width = canvas ? (canvas.width / Math.max(dpr, 1)) : window.innerWidth;
    const height = canvas ? (canvas.height / Math.max(dpr, 1)) : window.innerHeight;
    const originX = width / 2 - (width / 2) * viewScale + viewOffsetX;
    const originY = height / 2 - (height / 2) * viewScale + viewOffsetY;
    const posX = ((originX % curSize) + curSize) % curSize;
    const posY = ((originY % curSize) + curSize) % curSize;
    overlay.style.backgroundPosition = `${posX}px ${posY}px`;
    overlay.style.backgroundSize = (bgType === 'ruled') ? `100% ${curSize}px` : `${curSize}px ${curSize}px`;
  }

  function redraw() {
    if (!ctx) return;
    syncCanvasBackgroundTransform();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    const activeRect = getActiveTaskContentRect();

    // 1. Draw strokes & shapes on canvas
    strokes.forEach((s) => {
      if (s.type === 'note' || s.type === 'widget' || s.type === 'math') return;
      drawStroke(s, activeRect);
    });

    if (remoteLiveStrokes.size > 0) {
      remoteLiveStrokes.forEach((s) => {
        if (s.page_id && s.page_id !== currentPageId) return;
        if (s.type === 'note' || s.type === 'widget' || s.type === 'math') return;
        drawStroke(s, activeRect);
      });
    }

    // 2. Draw smart alignment guides
    if (activeGuides.length > 0) {
      ctx.save();
      ctx.strokeStyle = '#6366f1';
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      activeGuides.forEach((g) => {
        ctx.beginPath();
        if (g.type === 'v') {
          ctx.moveTo(g.pos, 0);
          ctx.lineTo(g.pos, canvas.height / dpr);
        } else {
          ctx.moveTo(0, g.pos);
          ctx.lineTo(canvas.width / dpr, g.pos);
        }
        ctx.stroke();
      });
      ctx.restore();
    }

    // 4. Synchronize DOM sticky notes and interactive widgets
    syncDomWidgets(activeRect);
    updateMinimap();
  }

  function drawStroke(s, activeRect) {
    if (!s.points || s.points.length < 1) return;
    const screenPoints = s.points.map((p) => pointToScreen(p, s, activeRect));

    ctx.save();

    // Line Styles: Solid, Dashed, Dotted
    if (s.style === 'dashed') ctx.setLineDash([8, 6]);
    else if (s.style === 'dotted') ctx.setLineDash([2, 4]);
    else ctx.setLineDash([]);

    // Eraser Stroke
    if (s.eraser) {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.strokeStyle = 'rgba(0,0,0,1)';
      ctx.fillStyle = 'rgba(0,0,0,1)';
      ctx.lineWidth = (s.width || eraserSize || 24) * viewScale;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      if (screenPoints.length === 1) {
        ctx.arc(screenPoints[0].x, screenPoints[0].y, ((s.width || eraserSize || 24) * viewScale) / 2, 0, Math.PI * 2);
        ctx.fill();
      } else {
        screenPoints.forEach((point, index) => {
          if (index === 0) ctx.moveTo(point.x, point.y);
          else ctx.lineTo(point.x, point.y);
        });
        ctx.stroke();
      }
      ctx.restore();
      return;
    }

    // Highlighter
    if (s.type === 'highlighter') {
      ctx.globalCompositeOperation = 'multiply';
      ctx.globalAlpha = s.opacity || 0.38;
      ctx.strokeStyle = s.color || highlighterColor;
      ctx.lineWidth = Math.max(14, (s.width || 6) * 3.5) * viewScale;
      ctx.beginPath();
      screenPoints.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.stroke();
      ctx.restore();
      return;
    }

    ctx.globalCompositeOperation = 'source-over';
    ctx.strokeStyle = s.color || '#000';
    ctx.lineWidth = (s.width || s.size || 3) * viewScale;

    // Text Object
    if (s.type === 'text') {
      ctx.fillStyle = s.color || '#000';
      const fSize = Math.max(12, Number(s.fontSize) || 20) * viewScale;
      ctx.font = `600 ${fSize}px system-ui, sans-serif`;
      ctx.textBaseline = 'top';
      ctx.fillText(String(s.text || ''), screenPoints[0].x, screenPoints[0].y);
      ctx.restore();
      return;
    }

    // Math Formula on Canvas
    if (s.type === 'math') {
      ctx.fillStyle = s.color || '#0f172a';
      const fSize = Math.max(14, Number(s.fontSize) || 20) * viewScale;
      ctx.font = `italic ${fSize}px "KaTeX_Main", "Times New Roman", serif`;
      ctx.textBaseline = 'top';
      ctx.fillText(String(s.latex || ''), screenPoints[0].x, screenPoints[0].y);
      ctx.restore();
      return;
    }

    // Image Object
    if (s.type === 'image') {
      const [start, end] = screenPoints;
      if (start && end) {
        const x = Math.min(start.x, end.x);
        const y = Math.min(start.y, end.y);
        const w = Math.abs(end.x - start.x);
        const h = Math.abs(end.y - start.y);
        let cached = imageCache.get(s.src);
        if (!cached) {
          cached = new Image();
          cached.src = s.src;
          cached.onload = () => redraw();
          imageCache.set(s.src, cached);
        }
        if (cached instanceof HTMLImageElement && cached.complete && cached.naturalWidth > 0) {
          try {
            ctx.drawImage(cached, x, y, w, h);
          } catch (_) {}
        }
      }
      ctx.restore();
      return;
    }

    // Connectors, Lines & Arrows
    if (s.type === 'connector' || ['line', 'arrow', 'double-arrow', 'curved-arrow'].includes(s.shape)) {
      const [start, end] = screenPoints;
      if (start && end) {
        ctx.beginPath();
        if (s.shape === 'curved-arrow') {
          const midX = (start.x + end.x) / 2;
          const midY = Math.min(start.y, end.y) - 30 * viewScale;
          ctx.moveTo(start.x, start.y);
          ctx.quadraticCurveTo(midX, midY, end.x, end.y);
        } else {
          ctx.moveTo(start.x, start.y);
          ctx.lineTo(end.x, end.y);
        }
        ctx.stroke();

        // Arrow head at end point (only for arrows, not plain lines)
        if (s.shape !== 'line') {
          const angle = Math.atan2(end.y - start.y, end.x - start.x);
          const headLen = Math.max(10 * viewScale, (s.width || 3) * 3 * viewScale);
          ctx.beginPath();
          ctx.moveTo(end.x, end.y);
          ctx.lineTo(end.x - headLen * Math.cos(angle - Math.PI / 6), end.y - headLen * Math.sin(angle - Math.PI / 6));
          ctx.moveTo(end.x, end.y);
          ctx.lineTo(end.x - headLen * Math.cos(angle + Math.PI / 6), end.y - headLen * Math.sin(angle + Math.PI / 6));
          ctx.stroke();

          // Double arrow head at start point
          if (s.shape === 'double-arrow') {
            ctx.beginPath();
            ctx.moveTo(start.x, start.y);
            ctx.lineTo(start.x + headLen * Math.cos(angle - Math.PI / 6), start.y + headLen * Math.sin(angle - Math.PI / 6));
            ctx.moveTo(start.x, start.y);
            ctx.lineTo(start.x + headLen * Math.cos(angle + Math.PI / 6), start.y + headLen * Math.sin(angle + Math.PI / 6));
            ctx.stroke();
          }
        }
      }
      ctx.restore();
      return;
    }

    // 2D & 3D Shapes
    if (s.type === 'shape') {
      const [start, end] = screenPoints;
      if (!start || !end) {
        ctx.restore();
        return;
      }
      const x = Math.min(start.x, end.x);
      const y = Math.min(start.y, end.y);
      const w = Math.abs(end.x - start.x);
      const h = Math.abs(end.y - start.y);

      ctx.beginPath();

      if (s.shape === 'rectangle' || s.shape === 'process') {
        ctx.rect(x, y, w, h);
      } else if (s.shape === 'square') {
        const sDim = Math.min(w, h);
        ctx.rect(x, y, sDim, sDim);
      } else if (s.shape === 'rounded-rect' || s.shape === 'terminal') {
        const r = Math.min(16 * viewScale, w / 2, h / 2);
        if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
        else ctx.rect(x, y, w, h);
      } else if (s.shape === 'circle') {
        const rad = Math.min(w, h) / 2;
        ctx.arc(x + rad, y + rad, Math.max(0.5, rad), 0, Math.PI * 2);
      } else if (s.shape === 'ellipse') {
        ctx.ellipse(x + w / 2, y + h / 2, Math.max(0.5, w / 2), Math.max(0.5, h / 2), 0, 0, Math.PI * 2);
      } else if (s.shape === 'semicircle') {
        ctx.ellipse(x + w / 2, y + h, Math.max(0.5, w / 2), Math.max(0.5, h), 0, Math.PI, Math.PI * 2);
        ctx.closePath();
      } else if (s.shape === 'sector') {
        ctx.moveTo(x + w / 2, y + h / 2);
        ctx.arc(x + w / 2, y + h / 2, Math.min(w, h) / 2, -Math.PI / 4, Math.PI * 1.15);
        ctx.closePath();
      } else if (s.shape === 'triangle') {
        ctx.moveTo(x + w / 2, y);
        ctx.lineTo(x + w, y + h);
        ctx.lineTo(x, y + h);
        ctx.closePath();
      } else if (s.shape === 'right-triangle') {
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + h);
        ctx.lineTo(x + w, y + h);
        ctx.closePath();
      } else if (s.shape === 'equilateral-triangle') {
        const side = Math.min(w, h);
        const triH = (Math.sqrt(3) / 2) * side;
        const triY = y + (h - triH) / 2;
        ctx.moveTo(x + w / 2, triY);
        ctx.lineTo(x + w / 2 + side / 2, triY + triH);
        ctx.lineTo(x + w / 2 - side / 2, triY + triH);
        ctx.closePath();
      } else if (s.shape === 'rhombus' || s.shape === 'decision') {
        ctx.moveTo(x + w / 2, y);
        ctx.lineTo(x + w, y + h / 2);
        ctx.lineTo(x + w / 2, y + h);
        ctx.lineTo(x, y + h / 2);
        ctx.closePath();
      } else if (s.shape === 'parallelogram' || s.shape === 'io') {
        const skew = w * 0.22;
        ctx.moveTo(x + skew, y);
        ctx.lineTo(x + w, y);
        ctx.lineTo(x + w - skew, y + h);
        ctx.lineTo(x, y + h);
        ctx.closePath();
      } else if (s.shape === 'trapezoid') {
        ctx.moveTo(x + w * 0.25, y);
        ctx.lineTo(x + w * 0.75, y);
        ctx.lineTo(x + w, y + h);
        ctx.lineTo(x, y + h);
        ctx.closePath();
      } else if (s.shape === 'polygon') {
        const cx = x + w / 2, cy = y + h / 2;
        const rx = w / 2, ry = h / 2;
        for (let i = 0; i < 6; i++) {
          const a = (i * Math.PI) / 3 - Math.PI / 6;
          const px = cx + rx * Math.cos(a);
          const py = cy + ry * Math.sin(a);
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();
      } else if (s.shape === 'star') {
        drawStar(ctx, x + w / 2, y + h / 2, 5, w / 2, w / 4);
      } else if (s.shape === 'cloud') {
        drawCloud(ctx, x, y, w, h);
      } else if (s.shape === 'callout') {
        drawCallout(ctx, x, y, w, h);
      } else if (s.shape === 'brackets') {
        drawBrackets(ctx, start, end, s);
      } else if (s.shape === 'cube') {
        drawCube(ctx, x, y, w, h);
      } else if (s.shape === 'cylinder') {
        drawCylinder(ctx, x, y, w, h);
      } else if (s.shape === 'cone') {
        drawCone(ctx, x, y, w, h);
      } else if (s.shape === 'pyramid') {
        drawPyramid(ctx, x, y, w, h);
      } else if (s.shape === 'line') {
        ctx.moveTo(start.x, start.y);
        ctx.lineTo(end.x, end.y);
      }

      if (s.fill && s.fill !== 'none' && !['line', 'brackets', 'cube', 'cylinder', 'cone', 'pyramid'].includes(s.shape)) {
        ctx.fillStyle = s.fillColor || s.color || penColor;
        ctx.globalAlpha = s.fill === 'semi' ? 0.25 : 0.88;
        ctx.fill();
        ctx.globalAlpha = s.opacity || 1;
      }

      ctx.stroke();
      ctx.restore();
      return;
    }

    // Freehand Stroke with Specialized Brush Physics & Rendering
    const bType = s.brush || (s.style === 'sketch' ? 'pencil' : 'ballpoint');
    if (bType === 'fountain_pen') {
      drawFountainPenStroke(ctx, screenPoints, s, viewScale);
    } else if (bType === 'pencil') {
      drawPencilStroke(ctx, screenPoints, s, viewScale);
    } else if (bType === 'brush' || bType === 'watercolor') {
      drawWatercolorBrushStroke(ctx, screenPoints, s, viewScale);
    } else if (bType === 'felt_tip') {
      drawFeltTipStroke(ctx, screenPoints, s, viewScale);
    } else if (bType === 'neon') {
      drawNeonStroke(ctx, screenPoints, s, viewScale);
    } else if (bType === 'airbrush') {
      drawAirbrushStroke(ctx, screenPoints, s, viewScale, activeRect);
    } else if (bType === 'dashed_pen' || s.style === 'dashed') {
      drawDashedPenStroke(ctx, screenPoints, s, viewScale);
    } else {
      drawBallpointStroke(ctx, screenPoints, s, viewScale);
    }
    ctx.restore();
  }

  // --- Specialized Brush Rendering Engines ---

  function getBrushDefaultWidth(brushType, currentTool) {
    if (currentTool === 'eraser_stroke' || currentTool === 'eraser' || currentTool === 'eraser_object') return eraserSize;
    if (brushType === 'highlighter' || currentTool === 'highlighter') return Math.max(16, penSize * 3.5);
    if (brushType === 'airbrush') return Math.max(16, penSize * 3.5);
    if (brushType === 'brush' || brushType === 'watercolor') return Math.max(7, penSize * 2.2);
    if (brushType === 'felt_tip') return Math.max(5, penSize * 1.5);
    if (brushType === 'fountain_pen') return Math.max(4, penSize * 1.3);
    if (brushType === 'neon') return Math.max(4, penSize * 1.2);
    if (brushType === 'pencil') return Math.max(1.8, penSize * 0.85);
    if (brushType === 'ballpoint' || brushType === 'pen') return Math.max(1.5, penSize * 0.9);
    if (brushType === 'dashed_pen') return Math.max(2, penSize);
    return penSize;
  }

  function getBrushDefaultOpacity(brushType, currentTool) {
    if (brushType === 'highlighter' || currentTool === 'highlighter') return 0.38;
    if (brushType === 'airbrush') return 0.75;
    if (brushType === 'brush' || brushType === 'watercolor') return 0.65;
    if (brushType === 'pencil') return 0.72;
    if (brushType === 'felt_tip') return 0.85;
    return penOpacity || 1;
  }

  function drawFountainPenStroke(c, points, s, scale) {
    if (!points || points.length < 1) return;
    const baseW = Math.max(2, (s.width || 4) * scale);
    const color = s.color || '#0f172a';
    c.fillStyle = color;
    c.globalAlpha = s.opacity || 0.95;

    if (points.length === 1) {
      c.beginPath();
      c.arc(points[0].x, points[0].y, baseW * 0.4, 0, Math.PI * 2);
      c.fill();
      return;
    }

    const angle = Math.PI / 4; // 45 degree calligraphy chisel cut
    const cosA = Math.cos(angle);
    const sinA = Math.sin(angle);

    for (let i = 0; i < points.length - 1; i++) {
      const p1 = points[i];
      const p2 = points[i + 1];
      const moveAngle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
      const factor = Math.max(0.2, Math.abs(Math.sin(moveAngle - angle)));
      const w = baseW * factor;
      const ox = (w / 2) * cosA;
      const oy = (w / 2) * sinA;

      c.beginPath();
      c.moveTo(p1.x - ox, p1.y - oy);
      c.lineTo(p1.x + ox, p1.y + oy);
      c.lineTo(p2.x + ox, p2.y + oy);
      c.lineTo(p2.x - ox, p2.y - oy);
      c.closePath();
      c.fill();

      c.beginPath();
      c.arc(p2.x, p2.y, w * 0.35, 0, Math.PI * 2);
      c.fill();
    }
  }

  function drawBallpointStroke(c, points, s, scale) {
    if (!points || points.length < 1) return;
    c.strokeStyle = s.color || '#0f172a';
    c.lineWidth = Math.max(1, (s.width || 2) * scale);
    c.lineCap = 'round';
    c.lineJoin = 'round';
    c.globalAlpha = s.opacity || 0.95;

    c.beginPath();
    if (points.length === 1) {
      c.arc(points[0].x, points[0].y, c.lineWidth / 2, 0, Math.PI * 2);
      c.fill();
      return;
    }
    points.forEach((p, i) => {
      if (i === 0) c.moveTo(p.x, p.y);
      else {
        const prev = points[i - 1];
        c.quadraticCurveTo(prev.x, prev.y, (prev.x + p.x) / 2, (prev.y + p.y) / 2);
      }
    });
    c.lineTo(points[points.length - 1].x, points[points.length - 1].y);
    c.stroke();
  }

  function drawPencilStroke(c, points, s, scale) {
    if (!points || points.length < 1) return;
    const w = Math.max(1.2, (s.width || 2) * scale);
    const color = s.color || '#334155';
    c.strokeStyle = color;
    c.fillStyle = color;
    c.lineCap = 'round';
    c.lineJoin = 'round';

    if (points.length === 1) {
      c.globalAlpha = (s.opacity || 0.72);
      c.beginPath();
      c.arc(points[0].x, points[0].y, w * 0.6, 0, Math.PI * 2);
      c.fill();
      return;
    }

    // 1. Organic graphite line with slight texture jitter
    c.globalAlpha = (s.opacity || 0.72) * 0.75;
    c.lineWidth = w;
    c.beginPath();
    points.forEach((p, i) => {
      const jx = Math.sin(i * 12.9898 + p.x * 0.05) * 0.35 * scale;
      const jy = Math.cos(i * 78.233 + p.y * 0.05) * 0.35 * scale;
      if (i === 0) c.moveTo(p.x + jx, p.y + jy);
      else c.lineTo(p.x + jx, p.y + jy);
    });
    c.stroke();

    // 2. Paper grain graphite speckles along the stroke path
    c.globalAlpha = 0.25;
    for (let i = 0; i < points.length - 1; i += 2) {
      const p1 = points[i];
      const p2 = points[i + 1];
      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      const dist = Math.hypot(dx, dy);
      const steps = Math.max(1, Math.floor(dist / (4 * scale)));
      for (let sIdx = 0; sIdx <= steps; sIdx++) {
        const t = sIdx / steps;
        const seed = Math.sin((i + t) * 91.3 + p1.x * 0.5) * 10000;
        const rnd1 = (seed - Math.floor(seed)) - 0.5;
        const rnd2 = ((seed * 1.5) - Math.floor(seed * 1.5)) - 0.5;
        const gx = p1.x + dx * t + rnd1 * w * 1.5;
        const gy = p1.y + dy * t + rnd2 * w * 1.5;
        const grainR = Math.max(0.4, (w * 0.3) * (0.6 + Math.abs(rnd1)));
        c.beginPath();
        c.arc(gx, gy, grainR, 0, Math.PI * 2);
        c.fill();
      }
    }
  }

  function drawWatercolorBrushStroke(c, points, s, scale) {
    if (!points || points.length < 1) return;
    const baseW = Math.max(6, (s.width || 8) * scale);
    const color = s.color || '#4338ca';
    c.lineCap = 'round';
    c.lineJoin = 'round';

    if (points.length === 1) {
      c.fillStyle = color;
      c.globalAlpha = s.opacity || 0.6;
      c.beginPath();
      c.arc(points[0].x, points[0].y, baseW / 2, 0, Math.PI * 2);
      c.fill();
      return;
    }

    const bristleOffsets = [-0.3, 0, 0.3];
    const bristleAlphas = [0.22, 0.35, 0.22];

    bristleOffsets.forEach((bOff, bIdx) => {
      c.strokeStyle = color;
      c.globalAlpha = (s.opacity || 0.6) * bristleAlphas[bIdx];
      c.lineWidth = baseW * (0.65 + (bIdx === 1 ? 0.35 : 0));
      c.beginPath();
      points.forEach((p, i) => {
        let bx = p.x;
        let by = p.y;
        if (i < points.length - 1) {
          const next = points[i + 1];
          const nx = -(next.y - p.y);
          const ny = next.x - p.x;
          const nlen = Math.hypot(nx, ny) || 1;
          bx += (nx / nlen) * bOff * baseW * 0.4;
          by += (ny / nlen) * bOff * baseW * 0.4;
        }
        if (i === 0) c.moveTo(bx, by);
        else {
          const prev = points[i - 1];
          const midX = (prev.x + bx) / 2;
          const midY = (prev.y + by) / 2;
          c.quadraticCurveTo(prev.x, prev.y, midX, midY);
        }
      });
      c.stroke();
    });
  }

  function drawFeltTipStroke(c, points, s, scale) {
    if (!points || points.length < 1) return;
    const w = Math.max(3, (s.width || 5) * scale);
    c.strokeStyle = s.color || '#e11d48';
    c.lineWidth = w;
    c.lineCap = 'round';
    c.lineJoin = 'round';
    c.globalAlpha = s.opacity || 0.85;

    c.beginPath();
    if (points.length === 1) {
      c.arc(points[0].x, points[0].y, w / 2, 0, Math.PI * 2);
      c.fill();
      return;
    }
    points.forEach((p, i) => {
      if (i === 0) c.moveTo(p.x, p.y);
      else {
        const prev = points[i - 1];
        c.quadraticCurveTo(prev.x, prev.y, (prev.x + p.x) / 2, (prev.y + p.y) / 2);
      }
    });
    c.lineTo(points[points.length - 1].x, points[points.length - 1].y);
    c.stroke();
  }

  function drawNeonStroke(c, points, s, scale) {
    if (!points || points.length < 1) return;
    const baseW = Math.max(3, (s.width || 4) * scale);
    const color = s.color || '#06b6d4';
    c.lineCap = 'round';
    c.lineJoin = 'round';

    if (points.length === 1) {
      c.save();
      c.fillStyle = color;
      c.shadowColor = color;
      c.shadowBlur = 12 * scale;
      c.beginPath();
      c.arc(points[0].x, points[0].y, baseW, 0, Math.PI * 2);
      c.fill();
      c.restore();
      return;
    }

    // 1. Outer Glow Aura
    c.save();
    c.strokeStyle = color;
    c.shadowColor = color;
    c.shadowBlur = 12 * scale;
    c.lineWidth = baseW * 2.4;
    c.globalAlpha = 0.65;
    c.beginPath();
    points.forEach((p, i) => {
      if (i === 0) c.moveTo(p.x, p.y);
      else {
        const prev = points[i - 1];
        c.quadraticCurveTo(prev.x, prev.y, (prev.x + p.x) / 2, (prev.y + p.y) / 2);
      }
    });
    c.lineTo(points[points.length - 1].x, points[points.length - 1].y);
    c.stroke();
    c.restore();

    // 2. Middle Body
    c.strokeStyle = color;
    c.lineWidth = baseW;
    c.globalAlpha = 0.9;
    c.beginPath();
    points.forEach((p, i) => {
      if (i === 0) c.moveTo(p.x, p.y);
      else {
        const prev = points[i - 1];
        c.quadraticCurveTo(prev.x, prev.y, (prev.x + p.x) / 2, (prev.y + p.y) / 2);
      }
    });
    c.lineTo(points[points.length - 1].x, points[points.length - 1].y);
    c.stroke();

    // 3. Inner Bright Core
    c.strokeStyle = '#ffffff';
    c.lineWidth = Math.max(1.5, baseW * 0.35);
    c.globalAlpha = 0.95;
    c.beginPath();
    points.forEach((p, i) => {
      if (i === 0) c.moveTo(p.x, p.y);
      else {
        const prev = points[i - 1];
        c.quadraticCurveTo(prev.x, prev.y, (prev.x + p.x) / 2, (prev.y + p.y) / 2);
      }
    });
    c.lineTo(points[points.length - 1].x, points[points.length - 1].y);
    c.stroke();
  }

  function renderAirbrushToCache(s) {
    if (!s || !s.points || s.points.length < 1) return;
    const sprayRadius = Math.max(10, (s.width || 18) * 1.5);
    const color = s.color || '#8b5cf6';
    const density = typeof s.density === 'number' ? s.density : (airbrushDensity || 0.75);

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    s.points.forEach((p) => {
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x);
      maxY = Math.max(maxY, p.y);
    });

    const pad = Math.ceil(sprayRadius + 20);
    const w = Math.min(4096, Math.max(30, Math.ceil(maxX - minX + pad * 2)));
    const h = Math.min(4096, Math.max(30, Math.ceil(maxY - minY + pad * 2)));

    const offCanvas = document.createElement('canvas');
    offCanvas.width = w;
    offCanvas.height = h;
    const oc = offCanvas.getContext('2d');
    if (!oc) return;

    const ox = minX - pad;
    const oy = minY - pad;

    // Dabs in local offscreen coordinates
    const localPoints = s.points.map((p) => ({ x: p.x - ox, y: p.y - oy, p: p.p || 0.5 }));
    const dabs = [];
    if (localPoints.length === 1) {
      dabs.push({ x: localPoints[0].x, y: localPoints[0].y, p: localPoints[0].p });
    } else {
      const stepDist = Math.max(6, sprayRadius * 0.32);
      let accumulated = 0;
      dabs.push({ x: localPoints[0].x, y: localPoints[0].y, p: localPoints[0].p });

      for (let i = 1; i < localPoints.length; i++) {
        const prev = localPoints[i - 1];
        const curr = localPoints[i];
        const dx = curr.x - prev.x;
        const dy = curr.y - prev.y;
        const segLen = Math.hypot(dx, dy);
        if (segLen <= 0.001) continue;

        let curDist = stepDist - accumulated;
        while (curDist <= segLen) {
          const t = curDist / segLen;
          dabs.push({
            x: prev.x + dx * t,
            y: prev.y + dy * t,
            p: prev.p + (curr.p - prev.p) * t,
          });
          curDist += stepDist;
        }
        accumulated = segLen - (curDist - stepDist);
      }
    }

    const particlesPerDab = Math.max(10, Math.round(20 * density * Math.min(2.2, sprayRadius / 15)));
    const outerParticles = [];
    const coreParticles = [];

    for (let k = 0; k < dabs.length; k++) {
      const dab = dabs[k];
      const r = sprayRadius * (0.75 + dab.p * 0.45);

      for (let d = 0; d < particlesPerDab; d++) {
        const h1 = Math.sin(k * 127.1 + d * 311.7) * 43758.5453;
        const rnd1 = h1 - Math.floor(h1);

        const h2 = Math.cos(k * 269.5 + d * 183.3) * 43758.5453;
        const rnd2 = h2 - Math.floor(h2);

        const rndAng = rnd1 * Math.PI * 2;
        const rndR = Math.pow(rnd2, 0.72) * r;
        const dotX = dab.x + Math.cos(rndAng) * rndR;
        const dotY = dab.y + Math.sin(rndAng) * rndR;

        const distNorm = rndR / r;
        const dotSize = Math.max(0.65, (0.95 + rnd1 * 1.5) * (0.55 + (1 - distNorm) * 0.65));

        if (distNorm > 0.55) {
          outerParticles.push({ x: dotX, y: dotY, r: dotSize });
        } else {
          coreParticles.push({ x: dotX, y: dotY, r: dotSize });
        }
      }
    }

    oc.fillStyle = color;

    // Outer mist
    if (outerParticles.length > 0) {
      oc.globalAlpha = Math.min(0.85, (s.opacity || 0.65) * 0.35 * (0.5 + density * 0.5));
      oc.beginPath();
      for (let i = 0; i < outerParticles.length; i++) {
        const pt = outerParticles[i];
        oc.moveTo(pt.x + pt.r, pt.y);
        oc.arc(pt.x, pt.y, pt.r, 0, Math.PI * 2);
      }
      oc.fill();
    }

    // Dense core
    if (coreParticles.length > 0) {
      oc.globalAlpha = Math.min(0.95, (s.opacity || 0.65) * 0.82 * (0.55 + density * 0.45));
      oc.beginPath();
      for (let i = 0; i < coreParticles.length; i++) {
        const pt = coreParticles[i];
        oc.moveTo(pt.x + pt.r, pt.y);
        oc.arc(pt.x, pt.y, pt.r, 0, Math.PI * 2);
      }
      oc.fill();
    }

    s._cacheCanvas = offCanvas;
    s._cacheOrigin = { x: ox, y: oy, w: w, h: h };
  }

  function drawAirbrushStroke(c, points, s, scale, activeRect) {
    if (!s || !s.points || s.points.length < 1) return;

    if (!(s._cacheCanvas instanceof HTMLCanvasElement)) {
      renderAirbrushToCache(s);
    }

    if ((s._cacheCanvas instanceof HTMLCanvasElement) && s._cacheOrigin) {
      try {
        const sp = pointToScreen({ x: s._cacheOrigin.x, y: s._cacheOrigin.y }, s, activeRect);
        const sw = s._cacheOrigin.w * scale;
        const sh = s._cacheOrigin.h * scale;
        c.drawImage(s._cacheCanvas, sp.x, sp.y, sw, sh);
      } catch (err) {
        console.warn('drawAirbrushStroke drawImage error:', err);
      }
    }
  }

  function drawDashedPenStroke(c, points, s, scale) {
    if (!points || points.length < 1) return;
    c.strokeStyle = s.color || '#0f172a';
    c.lineWidth = Math.max(1.5, (s.width || 2) * scale);
    c.lineCap = 'butt';
    c.lineJoin = 'miter';
    c.globalAlpha = s.opacity || 1;
    c.setLineDash([8 * scale, 5 * scale]);

    c.beginPath();
    points.forEach((p, i) => {
      if (i === 0) c.moveTo(p.x, p.y);
      else c.lineTo(p.x, p.y);
    });
    c.stroke();
    c.setLineDash([]);
  }

  // --- 3D Shape Drawing Helpers ---

  function drawCube(c, x, y, w, h) {
    const d = Math.min(w, h) * 0.3;
    // Front face
    c.rect(x, y + d, w - d, h - d);
    // Top face
    c.moveTo(x, y + d);
    c.lineTo(x + d, y);
    c.lineTo(x + w, y);
    c.lineTo(x + w - d, y + d);
    // Right face
    c.lineTo(x + w - d, y + h);
    c.lineTo(x + w, y + h - d);
    c.lineTo(x + w, y);
  }

  function drawCylinder(c, x, y, w, h) {
    const ry = h * 0.15;
    // Top ellipse
    c.ellipse(x + w / 2, y + ry, w / 2, ry, 0, 0, Math.PI * 2);
    // Sides
    c.moveTo(x, y + ry);
    c.lineTo(x, y + h - ry);
    c.moveTo(x + w, y + ry);
    c.lineTo(x + w, y + h - ry);
    // Bottom ellipse half
    c.ellipse(x + w / 2, y + h - ry, w / 2, ry, 0, 0, Math.PI);
  }

  function drawCone(c, x, y, w, h) {
    const ry = h * 0.15;
    // Apex to bottom base
    c.moveTo(x + w / 2, y);
    c.lineTo(x, y + h - ry);
    c.moveTo(x + w / 2, y);
    c.lineTo(x + w, y + h - ry);
    // Base ellipse
    c.ellipse(x + w / 2, y + h - ry, w / 2, ry, 0, 0, Math.PI);
  }

  function drawPyramid(c, x, y, w, h) {
    // Apex
    const apexX = x + w / 2;
    const apexY = y;
    // Base points
    c.moveTo(apexX, apexY);
    c.lineTo(x, y + h);
    c.lineTo(x + w * 0.8, y + h);
    c.lineTo(apexX, apexY);
    c.lineTo(x + w, y + h * 0.85);
    c.lineTo(x + w * 0.8, y + h);
  }

  function drawStar(c, cx, cy, spikes, outerRadius, innerRadius) {
    let rot = (Math.PI / 2) * 3;
    let x = cx;
    let y = cy;
    const step = Math.PI / spikes;

    c.moveTo(cx, cy - outerRadius);
    for (let i = 0; i < spikes; i++) {
      x = cx + Math.cos(rot) * outerRadius;
      y = cy + Math.sin(rot) * outerRadius;
      c.lineTo(x, y);
      rot += step;
      x = cx + Math.cos(rot) * innerRadius;
      y = cy + Math.sin(rot) * innerRadius;
      c.lineTo(x, y);
      rot += step;
    }
    c.lineTo(cx, cy - outerRadius);
    c.closePath();
  }

  function drawCloud(c, x, y, w, h) {
    const r = Math.min(w, h) * 0.22;
    c.moveTo(x + r, y + h - r);
    c.arc(x + r, y + h - r, r, Math.PI * 0.5, Math.PI * 1.5);
    c.arc(x + w * 0.35, y + r * 1.1, r * 1.15, Math.PI * 0.9, Math.PI * 1.9);
    c.arc(x + w * 0.68, y + r * 1.05, r * 1.25, Math.PI * 1.2, Math.PI * 0.1);
    c.arc(x + w - r, y + h - r, r, Math.PI * 1.5, Math.PI * 0.5);
    c.closePath();
  }

  function drawCallout(c, x, y, w, h) {
    const bubbleH = h * 0.76;
    const r = Math.min(12, w * 0.1, bubbleH * 0.25);
    c.moveTo(x + r, y);
    c.lineTo(x + w - r, y);
    c.arcTo(x + w, y, x + w, y + r, r);
    c.lineTo(x + w, y + bubbleH - r);
    c.arcTo(x + w, y + bubbleH, x + w - r, y + bubbleH, r);
    c.lineTo(x + w * 0.45, y + bubbleH);
    c.lineTo(x + w * 0.22, y + h);
    c.lineTo(x + w * 0.28, y + bubbleH);
    c.lineTo(x + r, y + bubbleH);
    c.arcTo(x, y + bubbleH, x, y + bubbleH - r, r);
    c.lineTo(x, y + r);
    c.arcTo(x, y, x + r, y, r);
    c.closePath();
  }

  function drawBrackets(c, start, end, s) {
    if (!start) return;
    const pEnd = end || { x: start.x + 40, y: start.y + 120 };
    const x = Math.min(start.x, pEnd.x);
    const y = Math.min(start.y, pEnd.y);
    const w = Math.max(12, Math.abs(pEnd.x - start.x));
    const h = Math.max(12, Math.abs(pEnd.y - start.y));

    // Horizontal if width noticeably exceeds height, otherwise vertical
    const isHorizontal = w > h * 1.15;
    const flipH = !!(s && s.flipH);
    const flipV = !!(s && s.flipV);

    if (isHorizontal) {
      // Horizontal curly brace: top brace (⏞) or bottom brace (⏟)
      let pointUp = start.y <= pEnd.y;
      if (flipV) pointUp = !pointUp;

      const midX = x + w / 2;
      const cornerR = Math.min(18, w * 0.15, h * 0.4);
      const peakW = Math.min(24, w * 0.2);

      if (pointUp) {
        // Peak at top (y), endpoints at bottom (y + h)
        const peakY = y;
        const baseY = y + h;
        const armY = y + h * 0.5;

        c.moveTo(x, baseY);
        c.bezierCurveTo(x + cornerR, baseY, x + cornerR, armY, midX - peakW, armY);
        c.bezierCurveTo(midX - peakW * 0.4, armY, midX - 3, peakY, midX, peakY);
        c.bezierCurveTo(midX + 3, peakY, midX + peakW * 0.4, armY, midX + peakW, armY);
        c.bezierCurveTo(x + w - cornerR, armY, x + w - cornerR, baseY, x + w, baseY);
      } else {
        // Peak at bottom (y + h), endpoints at top (y)
        const peakY = y + h;
        const baseY = y;
        const armY = y + h * 0.5;

        c.moveTo(x, baseY);
        c.bezierCurveTo(x + cornerR, baseY, x + cornerR, armY, midX - peakW, armY);
        c.bezierCurveTo(midX - peakW * 0.4, armY, midX - 3, peakY, midX, peakY);
        c.bezierCurveTo(midX + 3, peakY, midX + peakW * 0.4, armY, midX + peakW, armY);
        c.bezierCurveTo(x + w - cornerR, armY, x + w - cornerR, baseY, x + w, baseY);
      }
    } else {
      // Vertical curly brace: left brace ({) or right brace (})
      let pointLeft = start.x <= pEnd.x;
      if (flipH) pointLeft = !pointLeft;

      const midY = y + h / 2;
      const cornerR = Math.min(18, h * 0.15, w * 0.4);
      const peakH = Math.min(24, h * 0.2);

      if (pointLeft) {
        // Left brace {: peak points left (x), endpoints at right (x + w)
        const peakX = x;
        const baseX = x + w;
        const armX = x + w * 0.5;

        c.moveTo(baseX, y);
        c.bezierCurveTo(baseX, y + cornerR, armX, y + cornerR, armX, midY - peakH);
        c.bezierCurveTo(armX, midY - peakH * 0.4, peakX, midY - 3, peakX, midY);
        c.bezierCurveTo(peakX, midY + 3, armX, midY + peakH * 0.4, armX, midY + peakH);
        c.bezierCurveTo(armX, y + h - cornerR, baseX, y + h - cornerR, baseX, y + h);
      } else {
        // Right brace }: peak points right (x + w), endpoints at left (x)
        const peakX = x + w;
        const baseX = x;
        const armX = x + w * 0.5;

        c.moveTo(baseX, y);
        c.bezierCurveTo(baseX, y + cornerR, armX, y + cornerR, armX, midY - peakH);
        c.bezierCurveTo(armX, midY - peakH * 0.4, peakX, midY - 3, peakX, midY);
        c.bezierCurveTo(peakX, midY + 3, armX, midY + peakH * 0.4, armX, midY + peakH);
        c.bezierCurveTo(armX, y + h - cornerR, baseX, y + h - cornerR, baseX, y + h);
      }
    }
  }

  // --- DOM Widgets Syncing ---

  function syncDomWidgets(activeRect) {
    if (!objectLayer) return;
    const curActiveRect = activeRect || getActiveTaskContentRect();

    const domStrokes = strokes.filter((s) => s.type === 'note' || s.type === 'widget' || s.type === 'math');
    const existingIds = new Set(domStrokes.map((s) => s.id));

    Array.from(objectLayer.querySelectorAll('.boo-canvas-sticky-note, .boo-canvas-widget, .boo-canvas-math-card')).forEach((el) => {
      if (!existingIds.has(el.dataset.objId)) {
        el.remove();
      }
    });

    domStrokes.forEach((item) => {
      const strokeIndex = strokes.findIndex((s) => s.id === item.id);
      let el = objectLayer.querySelector(`[data-obj-id="${item.id}"]`);
      if (!el) {
        if (item.type === 'note') {
          el = createNoteDom(item);
        } else if (item.type === 'math') {
          el = createMathDom(item);
        } else {
          el = createWidgetDom(item);
        }
        objectLayer.appendChild(el);
      } else if (item.type === 'math') {
        updateMathCardContent(el, item);
      }

      // Update position and dimensions
      const p1 = pointToScreen(item.points[0], item, curActiveRect);
      const p2 = pointToScreen(item.points[1] || item.points[0], item, curActiveRect);
      const x = Math.min(p1.x, p2.x);
      const y = Math.min(p1.y, p2.y);
      const w = Math.max(item.type === 'math' ? 60 : 140, Math.abs(p2.x - p1.x));
      const h = Math.max(item.type === 'math' ? 36 : 90, Math.abs(p2.y - p1.y));

      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      if (item.type !== 'math') {
        el.style.width = `${w}px`;
        el.style.height = `${h}px`;
      }
      el.style.zIndex = `${Math.max(2, strokeIndex + 2)}`;

      if (item.type === 'math') {
        el.style.transformOrigin = 'top left';
        el.style.transform = `${item.rotation ? `rotate(${item.rotation}deg) ` : ''}${viewScale !== 1 ? `scale(${viewScale})` : ''}`;
        el.classList.toggle('is-selected', selectedIds.has(item.id));
        const cardW = Math.max(60, el.offsetWidth || 120);
        const cardH = Math.max(36, el.offsetHeight || 44);
        item.points[1] = {
          x: item.points[0].x + cardW / Math.max(viewScale, 0.1),
          y: item.points[0].y + cardH / Math.max(viewScale, 0.1),
        };
      } else {
        el.style.transformOrigin = 'center center';
        el.style.transform = item.rotation ? `rotate(${item.rotation}deg)` : '';
        if (item.type === 'note') {
          el.style.fontSize = `${Math.max(11, 14 * viewScale)}px`;
        }
      }
      if (typeof el._onResize === 'function') {
        el._onResize(w, h);
      }
    });
  }

  function createMathDom(item) {
    const el = document.createElement('div');
    el.className = 'boo-canvas-math-card';
    el.dataset.objId = item.id;
    updateMathCardContent(el, item);

    el.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      openMathModal(item);
    });

    el.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.boo-math-edit-btn')) return;
      if (tool === 'laser') {
        onPointerDown(e);
        return;
      }
      if (tool === 'eraser_object') {
        e.stopPropagation();
        deleteSingleStroke(item.id);
        return;
      }
      if (tool !== 'select' && tool !== 'eraser_stroke') {
        setTool('select');
      }
      if (tool === 'select') {
        e.stopPropagation();
        if (!selectedIds.has(item.id)) {
          if (!e.shiftKey) selectedIds.clear();
          selectedIds.add(item.id);
          updateSelectionBox();
        }
        startMoveSelection(e);
      }
    });

    return el;
  }

  function updateMathCardContent(el, item) {
    let rendered = item.latex || '';
    if (window.katex && typeof window.katex.renderToString === 'function') {
      try {
        rendered = window.katex.renderToString(item.latex || '', { displayMode: true, throwOnError: false });
      } catch (err) {
        rendered = `<span style="font-style: italic; color: #ef4444;">${item.latex}</span>`;
      }
    } else {
      rendered = `<span style="font-style: italic; font-family: serif; font-size: 16px;">${item.latex || ''}</span>`;
      ensureKaTeXLoaded(() => updateMathCardContent(el, item));
    }
    el.innerHTML = `
      <div class="boo-math-content">${rendered}</div>
      <button type="button" class="boo-math-edit-btn" title="Редактировать формулу (LaTeX)">
        <i class="ph-bold ph-pencil-simple"></i>
      </button>
    `;
    const btn = el.querySelector('.boo-math-edit-btn');
    if (btn) {
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        openMathModal(item);
      });
    }
  }

  function createNoteDom(note) {
    const el = document.createElement('div');
    el.className = `boo-canvas-sticky-note note-${note.colorTheme || 'yellow'}`;
    el.dataset.objId = note.id;

    const ta = document.createElement('textarea');
    ta.placeholder = 'Введите текст заметки...';
    ta.value = note.text || '';
    ta.addEventListener('input', (ev) => {
      note.text = ev.target.value;
      dirty = true;
      saveLocal();
      scheduleSave();
    });
    ta.addEventListener('focus', () => {
      el.classList.add('is-editing');
      if (tool !== 'select') setTool('select');
      selectedIds.clear();
      selectedIds.add(note.id);
      updateSelectionBox();
    });
    ta.addEventListener('blur', () => el.classList.remove('is-editing'));

    el.addEventListener('pointerdown', (ev) => {
      if (tool === 'laser') {
        onPointerDown(ev);
        return;
      }
      if (ev.target.tagName === 'TEXTAREA' && el.classList.contains('is-editing')) return;
      if (tool === 'select' || tool === 'eraser_object') {
        ev.stopPropagation();
        if (tool === 'eraser_object') {
          deleteSingleStroke(note.id);
          return;
        }
        if (ev.shiftKey) {
          if (selectedIds.has(note.id)) selectedIds.delete(note.id);
          else selectedIds.add(note.id);
        } else {
          selectedIds.clear();
          selectedIds.add(note.id);
        }
        updateSelectionBox();
        startMoveSelection(ev);
      }
    });

    el.appendChild(ta);
    return el;
  }

  const WIDGET_METAS = {
    flashcard: { title: 'Флеш-карточка', icon: 'ph-cards' },
    spoiler: { title: 'Скрытый блок', icon: 'ph-eye-slash' },
    checklist: { title: 'Чек-лист задачи', icon: 'ph-check-square' },
    counter: { title: 'Счётчик', icon: 'ph-plus-minus' },
    timer: { title: 'Таймер / Секундомер', icon: 'ph-timer' },
    dice: { title: 'Кубик / ГСЧ', icon: 'ph-cube' },
    truth_table: { title: 'Таблица истинности', icon: 'ph-table' },
    logic_gates: { title: 'Логический элемент', icon: 'ph-cpu' },
    binary_calc: { title: 'Системы счисления', icon: 'ph-binary' },
    function_graph: { title: 'График функции', icon: 'ph-chart-line' },
    fano_tree: { title: 'Дерево Фано', icon: 'ph-tree-structure' },
    turtle: { title: 'Исполнитель Черепаха', icon: 'ph-navigation-arrow' },
    number_line: { title: 'Числовая прямая', icon: 'ph-arrows-horizontal' },
    graph: { title: 'Граф / Узлы и рёбра', icon: 'ph-circles-three' },
  };

  function createWidgetDom(item) {
    const el = document.createElement('div');
    const wType = item.widgetType || 'generic';
    el.className = `boo-canvas-widget boo-widget-${wType} boo-widget-${wType.replace(/_/g, '-')}`;
    el.dataset.objId = item.id;
    if (!item.data) item.data = getInitialWidgetData(item.widgetType);

    const meta = WIDGET_METAS[item.widgetType] || { title: item.widgetType || 'Интерактив', icon: 'ph-squares-four' };

    // 1. Drag Handle Header
    const header = document.createElement('div');
    header.className = 'boo-widget-drag-handle';
    header.innerHTML = `
      <span class="boo-drag-title"><i class="ph-bold ${meta.icon}"></i> ${meta.title}</span>
      <div class="boo-drag-actions">
        <button type="button" class="boo-widget-btn-mini boo-btn-del" title="Удалить виджет">&times;</button>
      </div>
    `;
    header.addEventListener('pointerdown', (e) => {
      if (tool === 'laser') {
        onPointerDown(e);
        return;
      }
      e.stopPropagation();
      if (tool !== 'select') setTool('select');
      if (e.shiftKey) {
        if (selectedIds.has(item.id)) selectedIds.delete(item.id);
        else selectedIds.add(item.id);
      } else {
        if (!selectedIds.has(item.id)) {
          selectedIds.clear();
          selectedIds.add(item.id);
        }
      }
      updateSelectionBox();
      startMoveSelection(e);
    });
    header.querySelector('.boo-btn-del').addEventListener('click', (e) => {
      e.stopPropagation();
      deleteSingleStroke(item.id);
    });
    el.appendChild(header);

    // 2. Body Container
    const body = document.createElement('div');
    body.className = 'boo-widget-body';
    body.addEventListener('pointerdown', (e) => {
      if (tool === 'laser') {
        onPointerDown(e);
        return;
      }
      e.stopPropagation();
      if (['INPUT', 'BUTTON', 'TEXTAREA', 'SELECT', 'CANVAS'].includes(e.target.tagName)) return;
      if (tool === 'select') {
        if (!selectedIds.has(item.id)) {
          selectedIds.clear();
          selectedIds.add(item.id);
          updateSelectionBox();
        }
      }
    });
    body.addEventListener('keydown', (e) => e.stopPropagation());
    body.addEventListener('keyup', (e) => e.stopPropagation());
    el.appendChild(body);

    const saveWidget = () => {
      dirty = true;
      saveLocal();
      scheduleSave();
    };

    // 3. Concrete Widget Renderers
    if (item.widgetType === 'truth_table') {
      const formulaVal = item.data.formula || '(A and B) or not C';
      body.innerHTML = `
        <div class="boo-tt-input-row">
          <input type="text" class="boo-tt-formula-input" value="${formulaVal}" placeholder="(A and B) or not C">
        </div>
        <div style="display: flex; gap: 3px; flex-wrap: wrap; margin-bottom: 4px;">
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-tt-preset" data-f="A and B" style="padding: 2px 4px; font-size: 9px;">AND</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-tt-preset" data-f="A or B" style="padding: 2px 4px; font-size: 9px;">OR</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-tt-preset" data-f="not A" style="padding: 2px 4px; font-size: 9px;">NOT</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-tt-preset" data-f="A xor B" style="padding: 2px 4px; font-size: 9px;">XOR</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-tt-preset" data-f="A -> B" style="padding: 2px 4px; font-size: 9px;">A → B</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-tt-preset" data-f="(A and B) or not C" style="padding: 2px 4px; font-size: 9px;">(A∧B)∨¬C</button>
        </div>
        <div class="boo-tt-table-wrap">
          <table class="boo-tt-table">
            <thead></thead>
            <tbody></tbody>
          </table>
        </div>
      `;

      const input = body.querySelector('.boo-tt-formula-input');
      const thead = body.querySelector('thead');
      const tbody = body.querySelector('tbody');

      function evalBool(formula, varVals) {
        let expr = formula.toLowerCase();
        expr = expr.replace(/->/g, ' <= ')
                   .replace(/<->/g, ' === ')
                   .replace(/\bxor\b|\^/gi, ' !== ')
                   .replace(/\band\b|&/gi, ' && ')
                   .replace(/\bor\b|\|/gi, ' || ')
                   .replace(/\bnot\b|!/gi, ' ! ');
        Object.keys(varVals).forEach((k) => {
          expr = expr.replace(new RegExp(`\\b${k.toLowerCase()}\\b`, 'g'), varVals[k] ? 'true' : 'false');
        });
        try {
          return Boolean(Function(`"use strict"; return (${expr})`)());
        } catch (_) {
          return false;
        }
      }

      function renderTruthTable() {
        const formStr = input.value.trim() || 'A and B';
        item.data.formula = formStr;
        const matches = formStr.match(/\b[A-Za-z]\b/g) || [];
        const reserved = new Set(['and', 'or', 'not', 'xor', 'x', 'y', 'z', 'f', 't']);
        const vars = Array.from(new Set(matches.map((m) => m.toUpperCase()))).filter((v) => !reserved.has(v.toLowerCase())).sort();
        const activeVars = vars.length > 0 ? vars.slice(0, 4) : ['A', 'B'];

        thead.innerHTML = `<tr>${activeVars.map((v) => `<th>${v}</th>`).join('')}<th>F</th></tr>`;

        const rowCount = Math.pow(2, activeVars.length);
        let rowsHtml = '';
        for (let r = 0; r < rowCount; r++) {
          const varVals = {};
          let rowCells = '';
          for (let col = 0; col < activeVars.length; col++) {
            const bit = (r >> (activeVars.length - 1 - col)) & 1;
            varVals[activeVars[col]] = bit;
            rowCells += `<td>${bit}</td>`;
          }
          const computed = evalBool(formStr, varVals) ? 1 : 0;
          const overrideVal = item.data.overrides?.[r];
          const finalVal = overrideVal !== undefined ? overrideVal : computed;
          rowsHtml += `<tr>${rowCells}<td class="val-${finalVal} boo-tt-f-cell" data-row="${r}" title="Нажмите для переключения">${finalVal}</td></tr>`;
        }
        tbody.innerHTML = rowsHtml;

        tbody.querySelectorAll('.boo-tt-f-cell').forEach((cell) => {
          cell.addEventListener('click', (e) => {
            e.stopPropagation();
            const rIdx = Number(cell.dataset.row);
            if (!item.data.overrides) item.data.overrides = {};
            const curVal = cell.textContent.trim() === '1' ? 1 : 0;
            item.data.overrides[rIdx] = curVal ? 0 : 1;
            renderTruthTable();
            saveWidget();
          });
        });
      }

      input.addEventListener('input', () => {
        delete item.data.overrides;
        renderTruthTable();
        saveWidget();
      });

      body.querySelectorAll('.boo-tt-preset').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          input.value = btn.dataset.f;
          delete item.data.overrides;
          renderTruthTable();
          saveWidget();
        });
      });

      renderTruthTable();
    } else if (item.widgetType === 'function_graph') {
      const exprVal = item.data.expr || 'x^2 - 4';
      body.innerHTML = `
        <div style="display: flex; align-items: center; gap: 4px; margin-bottom: 4px;">
          <span style="font-weight: 700; font-size: 11px; color: #6366f1;">y =</span>
          <input type="text" class="boo-fg-expr" value="${exprVal}" style="flex: 1; font-size: 11px; padding: 2px 6px; border: 1px solid #cbd5e1; border-radius: 6px; font-family: ui-monospace, monospace;">
        </div>
        <div style="display: flex; gap: 3px; flex-wrap: wrap; margin-bottom: 4px;">
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-fg-p" data-e="x^2 - 4" style="padding: 1px 4px; font-size: 9px;">x²-4</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-fg-p" data-e="sin(x)" style="padding: 1px 4px; font-size: 9px;">sin(x)</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-fg-p" data-e="2*x - 1" style="padding: 1px 4px; font-size: 9px;">2x-1</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-fg-p" data-e="abs(x) - 2" style="padding: 1px 4px; font-size: 9px;">|x|-2</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-fg-p" data-e="x^3 - 3*x" style="padding: 1px 4px; font-size: 9px;">x³-3x</button>
        </div>
        <canvas class="boo-func-canvas"></canvas>
      `;

      const exprInput = body.querySelector('.boo-fg-expr');
      const canvasEl = body.querySelector('.boo-func-canvas');

      function evalMath(expr, xVal) {
        let s = expr.toLowerCase()
          .replace(/\^/g, '**')
          .replace(/\bsin\b/g, 'Math.sin')
          .replace(/\bcos\b/g, 'Math.cos')
          .replace(/\btan\b/g, 'Math.tan')
          .replace(/\babs\b/g, 'Math.abs')
          .replace(/\bsqrt\b/g, 'Math.sqrt')
          .replace(/\bpi\b/g, 'Math.PI')
          .replace(/(\d)x/g, '$1*x')
          .replace(/x/g, `(${xVal})`);
        try {
          return Number(Function(`"use strict"; return (${s})`)());
        } catch (_) {
          return NaN;
        }
      }

      function drawGraph() {
        const dprVal = window.devicePixelRatio || 1;
        const cw = canvasEl.clientWidth || 240;
        const ch = Math.max(80, canvasEl.clientHeight || 120);
        canvasEl.width = Math.floor(cw * dprVal);
        canvasEl.height = Math.floor(ch * dprVal);
        const gctx = canvasEl.getContext('2d');
        gctx.scale(dprVal, dprVal);
        gctx.clearRect(0, 0, cw, ch);

        const xMin = -6, xMax = 6, yMin = -6, yMax = 6;
        const toScreenX = (x) => ((x - xMin) / (xMax - xMin)) * cw;
        const toScreenY = (y) => ch - ((y - yMin) / (yMax - yMin)) * ch;

        // Grid
        gctx.strokeStyle = '#f1f5f9';
        gctx.lineWidth = 1;
        for (let gx = -6; gx <= 6; gx += 2) {
          gctx.beginPath();
          gctx.moveTo(toScreenX(gx), 0);
          gctx.lineTo(toScreenX(gx), ch);
          gctx.stroke();
        }
        for (let gy = -6; gy <= 6; gy += 2) {
          gctx.beginPath();
          gctx.moveTo(0, toScreenY(gy));
          gctx.lineTo(cw, toScreenY(gy));
          gctx.stroke();
        }

        // Axes
        gctx.strokeStyle = '#94a3b8';
        gctx.lineWidth = 1.5;
        gctx.beginPath();
        gctx.moveTo(0, toScreenY(0));
        gctx.lineTo(cw, toScreenY(0));
        gctx.moveTo(toScreenX(0), 0);
        gctx.lineTo(toScreenX(0), ch);
        gctx.stroke();

        // Labels
        gctx.fillStyle = '#64748b';
        gctx.font = '9px system-ui';
        gctx.fillText('x', cw - 10, toScreenY(0) - 3);
        gctx.fillText('y', toScreenX(0) + 3, 10);

        // Curve
        gctx.strokeStyle = '#6366f1';
        gctx.lineWidth = 2.5;
        gctx.beginPath();
        let first = true;
        for (let px = 0; px <= cw; px += 2) {
          const xVal = xMin + (px / cw) * (xMax - xMin);
          const yVal = evalMath(exprInput.value, xVal);
          if (!Number.isFinite(yVal) || isNaN(yVal)) {
            first = true;
            continue;
          }
          const py = toScreenY(yVal);
          if (py < -50 || py > ch + 50) {
            first = true;
            continue;
          }
          if (first) {
            gctx.moveTo(px, py);
            first = false;
          } else {
            gctx.lineTo(px, py);
          }
        }
        gctx.stroke();
      }

      exprInput.addEventListener('input', () => {
        item.data.expr = exprInput.value;
        drawGraph();
        saveWidget();
      });

      body.querySelectorAll('.boo-fg-p').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          exprInput.value = btn.dataset.e;
          item.data.expr = btn.dataset.e;
          drawGraph();
          saveWidget();
        });
      });

      el._onResize = () => drawGraph();
      setTimeout(drawGraph, 50);
    } else if (item.widgetType === 'checklist') {
      const items = item.data.items || [{ text: 'Проверить ОДЗ', done: true }, { text: 'Решить уравнение', done: false }];
      item.data.items = items;

      function renderChecklist() {
        body.innerHTML = '';
        const listWrap = document.createElement('div');
        listWrap.style.display = 'flex';
        listWrap.style.flexDirection = 'column';
        listWrap.style.gap = '3px';

        items.forEach((ci, idx) => {
          const row = document.createElement('div');
          row.className = `boo-check-item ${ci.done ? 'done' : ''}`;
          row.innerHTML = `
            <input type="checkbox" ${ci.done ? 'checked' : ''}>
            <input type="text" class="boo-check-text" value="${ci.text || ''}" placeholder="Пункт чек-листа...">
            <button type="button" class="boo-check-del">&times;</button>
          `;
          row.querySelector('input[type="checkbox"]').addEventListener('change', (e) => {
            ci.done = e.target.checked;
            row.classList.toggle('done', ci.done);
            saveWidget();
          });
          const textInput = row.querySelector('.boo-check-text');
          textInput.addEventListener('input', (e) => {
            ci.text = e.target.value;
            saveWidget();
          });
          row.querySelector('.boo-check-del').addEventListener('click', (e) => {
            e.stopPropagation();
            items.splice(idx, 1);
            renderChecklist();
            saveWidget();
          });
          listWrap.appendChild(row);
        });
        body.appendChild(listWrap);

        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'boo-check-add';
        addBtn.textContent = '+ Добавить пункт';
        addBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          items.push({ text: '', done: false });
          renderChecklist();
          saveWidget();
          const lastInput = body.querySelector('.boo-check-item:last-child .boo-check-text');
          if (lastInput) lastInput.focus();
        });
        body.appendChild(addBtn);
      }
      renderChecklist();
    } else if (item.widgetType === 'flashcard') {
      header.querySelector('.boo-drag-actions').insertAdjacentHTML('afterbegin', `
        <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-fc-flip-btn" style="padding: 2px 6px; font-size: 10px; margin-right: 4px;">
          <i class="ph-bold ph-arrows-clockwise"></i> Перевернуть
        </button>
      `);

      body.innerHTML = `
        <div class="boo-flashcard-inner">
          <div class="boo-flashcard-front">
            <span style="font-size: 10px; font-weight: 700; color: #64748b; margin-bottom: 4px;">Вопрос (лицевая сторона):</span>
            <textarea class="boo-fc-ta boo-fc-front-ta" placeholder="Введите вопрос...">${item.data.front || ''}</textarea>
          </div>
          <div class="boo-flashcard-back">
            <span style="font-size: 10px; font-weight: 700; color: #4338ca; margin-bottom: 4px;">Ответ (оборотная сторона):</span>
            <textarea class="boo-fc-ta boo-fc-back-ta" placeholder="Введите ответ...">${item.data.back || ''}</textarea>
          </div>
        </div>
      `;

      const flipBtn = header.querySelector('.boo-fc-flip-btn');
      flipBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        el.classList.toggle('is-flipped');
      });

      const frontTa = body.querySelector('.boo-fc-front-ta');
      frontTa.addEventListener('input', (e) => {
        item.data.front = e.target.value;
        saveWidget();
      });

      const backTa = body.querySelector('.boo-fc-back-ta');
      backTa.addEventListener('input', (e) => {
        item.data.back = e.target.value;
        saveWidget();
      });
    } else if (item.widgetType === 'spoiler') {
      let isEdit = false;
      const eyeBtn = document.createElement('button');
      eyeBtn.type = 'button';
      eyeBtn.className = 'boo-widget-btn-mini';
      eyeBtn.innerHTML = '<i class="ph-bold ph-eye"></i>';
      eyeBtn.title = 'Показать / скрыть';
      header.querySelector('.boo-drag-actions').prepend(eyeBtn);

      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'boo-widget-btn-mini';
      editBtn.innerHTML = '<i class="ph-bold ph-pencil"></i>';
      editBtn.title = 'Редактировать текст';
      header.querySelector('.boo-drag-actions').insertBefore(editBtn, eyeBtn.nextSibling);

      function renderSpoiler() {
        if (isEdit) {
          body.innerHTML = `<textarea class="boo-spoiler-ta" placeholder="Введите скрытый текст...">${item.data.text || ''}</textarea>`;
          const ta = body.querySelector('.boo-spoiler-ta');
          ta.addEventListener('input', (e) => {
            item.data.text = e.target.value;
            saveWidget();
          });
        } else {
          body.innerHTML = `
            <div class="boo-spoiler-hidden ${item.data.revealed ? 'revealed' : ''}">
              ${item.data.text || 'Ответ скрыт (нажмите для просмотра)'}
            </div>
            <div class="boo-spoiler-hint">Нажмите на блок или глаз, чтобы открыть</div>
          `;
          body.querySelector('.boo-spoiler-hidden').addEventListener('click', () => {
            item.data.revealed = !item.data.revealed;
            renderSpoiler();
          });
        }
      }

      eyeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        item.data.revealed = !item.data.revealed;
        renderSpoiler();
      });

      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        isEdit = !isEdit;
        editBtn.style.color = isEdit ? '#6366f1' : '';
        renderSpoiler();
      });

      renderSpoiler();
    } else if (item.widgetType === 'counter') {
      body.innerHTML = `
        <input type="text" class="boo-counter-title" value="${item.data.title || 'Счётчик'}" placeholder="Название...">
        <div class="boo-counter-row">
          <button type="button" class="boo-counter-btn" data-d="-5">-5</button>
          <button type="button" class="boo-counter-btn" data-d="-1">-1</button>
          <input type="number" class="boo-counter-input" value="${item.data.count || 0}">
          <button type="button" class="boo-counter-btn" data-d="1">+1</button>
          <button type="button" class="boo-counter-btn" data-d="5">+5</button>
          <button type="button" class="boo-counter-btn boo-counter-rst" title="Сбросить">0</button>
        </div>
      `;

      const titleInput = body.querySelector('.boo-counter-title');
      const numInput = body.querySelector('.boo-counter-input');

      titleInput.addEventListener('input', (e) => {
        item.data.title = e.target.value;
        saveWidget();
      });

      numInput.addEventListener('input', (e) => {
        item.data.count = Number(e.target.value) || 0;
        saveWidget();
      });

      body.querySelectorAll('.boo-counter-btn').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (btn.classList.contains('boo-counter-rst')) {
            item.data.count = 0;
          } else {
            const delta = Number(btn.dataset.d) || 0;
            item.data.count = (item.data.count || 0) + delta;
          }
          numInput.value = item.data.count;
          saveWidget();
        });
      });
    } else if (item.widgetType === 'timer') {
      let sec = item.data.seconds !== undefined ? item.data.seconds : 300;
      let isRunning = false;
      let timerInterval = null;
      let mode = item.data.mode || 'timer'; // 'timer' or 'stopwatch'

      body.innerHTML = `
        <div style="display: flex; gap: 4px; justify-content: center; margin-bottom: 4px;">
          <button type="button" class="boo-confirm-btn ${mode === 'timer' ? 'boo-confirm-danger' : 'boo-confirm-cancel'} btn-mode-tm">Таймер</button>
          <button type="button" class="boo-confirm-btn ${mode === 'stopwatch' ? 'boo-confirm-danger' : 'boo-confirm-cancel'} btn-mode-sw">Секундомер</button>
        </div>
        <div class="boo-timer-display">
          <input type="number" class="boo-timer-input boo-timer-min" min="0" max="99" value="${Math.floor(sec / 60)}">
          <span>:</span>
          <input type="number" class="boo-timer-input boo-timer-sec" min="0" max="59" value="${String(sec % 60).padStart(2, '0')}">
        </div>
        <div class="boo-timer-controls">
          <button type="button" class="boo-timer-btn boo-timer-run">Старт</button>
          <button type="button" class="boo-timer-btn boo-timer-reset">Сброс</button>
        </div>
      `;

      const minInp = body.querySelector('.boo-timer-min');
      const secInp = body.querySelector('.boo-timer-sec');
      const runBtn = body.querySelector('.boo-timer-run');
      const resetBtn = body.querySelector('.boo-timer-reset');

      function updateTimerInputs() {
        minInp.value = Math.floor(sec / 60);
        secInp.value = String(sec % 60).padStart(2, '0');
        item.data.seconds = sec;
      }

      minInp.addEventListener('change', () => {
        sec = Math.max(0, Number(minInp.value) * 60 + Number(secInp.value));
        updateTimerInputs();
        saveWidget();
      });

      secInp.addEventListener('change', () => {
        sec = Math.max(0, Number(minInp.value) * 60 + Number(secInp.value));
        updateTimerInputs();
        saveWidget();
      });

      runBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (isRunning) {
          clearInterval(timerInterval);
          isRunning = false;
          runBtn.textContent = 'Старт';
        } else {
          isRunning = true;
          runBtn.textContent = 'Пауза';
          timerInterval = setInterval(() => {
            if (mode === 'timer') {
              if (sec > 0) {
                sec--;
                updateTimerInputs();
              } else {
                clearInterval(timerInterval);
                isRunning = false;
                runBtn.textContent = 'Старт';
                body.querySelector('.boo-timer-display').style.color = '#ef4444';
                setTimeout(() => { body.querySelector('.boo-timer-display').style.color = ''; }, 3000);
              }
            } else {
              sec++;
              updateTimerInputs();
            }
          }, 1000);
        }
      });

      resetBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (timerInterval) clearInterval(timerInterval);
        isRunning = false;
        runBtn.textContent = 'Старт';
        sec = mode === 'timer' ? 300 : 0;
        updateTimerInputs();
        saveWidget();
      });

      body.querySelector('.btn-mode-tm').addEventListener('click', (e) => {
        e.stopPropagation();
        mode = 'timer';
        item.data.mode = 'timer';
        sec = 300;
        updateTimerInputs();
        body.querySelector('.btn-mode-tm').className = 'boo-confirm-btn boo-confirm-danger btn-mode-tm';
        body.querySelector('.btn-mode-sw').className = 'boo-confirm-btn boo-confirm-cancel btn-mode-sw';
      });

      body.querySelector('.btn-mode-sw').addEventListener('click', (e) => {
        e.stopPropagation();
        mode = 'stopwatch';
        item.data.mode = 'stopwatch';
        sec = 0;
        updateTimerInputs();
        body.querySelector('.btn-mode-tm').className = 'boo-confirm-btn boo-confirm-cancel btn-mode-tm';
        body.querySelector('.btn-mode-sw').className = 'boo-confirm-btn boo-confirm-danger btn-mode-sw';
      });
    } else if (item.widgetType === 'dice') {
      let sides = item.data.sides || 6;
      let val = item.data.value || 6;
      let history = item.data.history || [];

      body.innerHTML = `
        <div style="display: flex; gap: 4px; justify-content: center; margin-bottom: 4px;">
          <button type="button" class="boo-confirm-btn ${sides === 6 ? 'boo-confirm-danger' : 'boo-confirm-cancel'} boo-d-s" data-s="6">d6</button>
          <button type="button" class="boo-confirm-btn ${sides === 12 ? 'boo-confirm-danger' : 'boo-confirm-cancel'} boo-d-s" data-s="12">d12</button>
          <button type="button" class="boo-confirm-btn ${sides === 20 ? 'boo-confirm-danger' : 'boo-confirm-cancel'} boo-d-s" data-s="20">d20</button>
          <button type="button" class="boo-confirm-btn ${sides === 100 ? 'boo-confirm-danger' : 'boo-confirm-cancel'} boo-d-s" data-s="100">100</button>
        </div>
        <div class="boo-dice-cube">${val}</div>
        <div style="text-align: center;">
          <button type="button" class="boo-dice-btn">Бросить кубик</button>
        </div>
        <div class="boo-dice-hist" style="font-size: 10px; color: #94a3b8; text-align: center; margin-top: 4px;">
          ${history.length ? 'История: ' + history.slice(-4).join(', ') : 'Нажмите, чтобы бросить'}
        </div>
      `;

      const cubeEl = body.querySelector('.boo-dice-cube');
      const histEl = body.querySelector('.boo-dice-hist');

      body.querySelector('.boo-dice-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        cubeEl.style.transform = 'rotate(360deg) scale(1.2)';
        setTimeout(() => {
          val = Math.floor(Math.random() * sides) + 1;
          cubeEl.textContent = val;
          cubeEl.style.transform = 'none';
          history.push(val);
          item.data.value = val;
          item.data.history = history;
          histEl.textContent = 'История: ' + history.slice(-4).join(', ');
          saveWidget();
        }, 200);
      });

      body.querySelectorAll('.boo-d-s').forEach((b) => {
        b.addEventListener('click', (e) => {
          e.stopPropagation();
          sides = Number(b.dataset.s);
          item.data.sides = sides;
          body.querySelectorAll('.boo-d-s').forEach((btn) => btn.className = 'boo-confirm-btn boo-confirm-cancel boo-d-s');
          b.className = 'boo-confirm-btn boo-confirm-danger boo-d-s';
          saveWidget();
        });
      });
    } else if (item.widgetType === 'logic_gates') {
      let gate = item.data.gate || 'AND';
      let in1 = item.data.in1 !== undefined ? item.data.in1 : 1;
      let in2 = item.data.in2 !== undefined ? item.data.in2 : 0;

      body.innerHTML = `
        <div style="display: flex; justify-content: center; margin-bottom: 6px;">
          <select class="boo-gate-sel" style="font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; border: 1px solid #cbd5e1; outline: none;">
            <option value="AND" ${gate === 'AND' ? 'selected' : ''}>И (AND)</option>
            <option value="OR" ${gate === 'OR' ? 'selected' : ''}>ИЛИ (OR)</option>
            <option value="NOT" ${gate === 'NOT' ? 'selected' : ''}>НЕ (NOT)</option>
            <option value="XOR" ${gate === 'XOR' ? 'selected' : ''}>XOR</option>
            <option value="NAND" ${gate === 'NAND' ? 'selected' : ''}>И-НЕ (NAND)</option>
            <option value="NOR" ${gate === 'NOR' ? 'selected' : ''}>ИЛИ-НЕ (NOR)</option>
          </select>
        </div>
        <div class="boo-gate-row">
          <button type="button" class="boo-gate-in ${in1 ? 'on' : ''}" id="btn-in1">A: ${in1}</button>
          <button type="button" class="boo-gate-in ${in2 ? 'on' : ''}" id="btn-in2">B: ${in2}</button>
          <span class="boo-gate-badge">${gate}</span>
          <span>=</span>
          <span class="boo-gate-out" id="lbl-out">0</span>
        </div>
      `;

      const gateSel = body.querySelector('.boo-gate-sel');
      const btnIn1 = body.querySelector('#btn-in1');
      const btnIn2 = body.querySelector('#btn-in2');
      const lblOut = body.querySelector('#lbl-out');

      function updateGate() {
        let out = 0;
        if (gate === 'AND') out = (in1 && in2) ? 1 : 0;
        else if (gate === 'OR') out = (in1 || in2) ? 1 : 0;
        else if (gate === 'NOT') out = (!in1) ? 1 : 0;
        else if (gate === 'XOR') out = (in1 !== in2) ? 1 : 0;
        else if (gate === 'NAND') out = (!(in1 && in2)) ? 1 : 0;
        else if (gate === 'NOR') out = (!(in1 || in2)) ? 1 : 0;

        btnIn2.style.display = gate === 'NOT' ? 'none' : '';
        lblOut.textContent = out;
        lblOut.className = 'boo-gate-out ' + (out ? 'on' : '');
        item.data.gate = gate;
        item.data.in1 = in1;
        item.data.in2 = in2;
        saveWidget();
      }

      gateSel.addEventListener('change', () => {
        gate = gateSel.value;
        body.querySelector('.boo-gate-badge').textContent = gate;
        updateGate();
      });

      btnIn1.addEventListener('click', (e) => {
        e.stopPropagation();
        in1 = in1 ? 0 : 1;
        btnIn1.textContent = `A: ${in1}`;
        btnIn1.className = 'boo-gate-in ' + (in1 ? 'on' : '');
        updateGate();
      });

      btnIn2.addEventListener('click', (e) => {
        e.stopPropagation();
        in2 = in2 ? 0 : 1;
        btnIn2.textContent = `B: ${in2}`;
        btnIn2.className = 'boo-gate-in ' + (in2 ? 'on' : '');
        updateGate();
      });

      updateGate();
    } else if (item.widgetType === 'binary_calc') {
      let val = item.data.value || 25;

      body.innerHTML = `
        <div class="boo-bin-bits"></div>
        <div class="boo-bin-row"><span>DEC:</span> <input type="number" class="boo-bin-input boo-b-dec" value="${val}"></div>
        <div class="boo-bin-row"><span>BIN:</span> <input type="text" class="boo-bin-input boo-b-bin" value="${(val >>> 0).toString(2).padStart(8, '0')}"></div>
        <div class="boo-bin-row"><span>HEX:</span> <input type="text" class="boo-bin-input boo-b-hex" value="${val.toString(16).toUpperCase()}"></div>
        <div class="boo-bin-row"><span>OCT:</span> <input type="text" class="boo-bin-input boo-b-oct" value="${val.toString(8)}"></div>
      `;

      const bitsWrap = body.querySelector('.boo-bin-bits');
      const decInp = body.querySelector('.boo-b-dec');
      const binInp = body.querySelector('.boo-b-bin');
      const hexInp = body.querySelector('.boo-b-hex');
      const octInp = body.querySelector('.boo-b-oct');

      function updateCalcUI() {
        val = Math.max(0, Math.min(255, val));
        decInp.value = val;
        binInp.value = (val >>> 0).toString(2).padStart(8, '0');
        hexInp.value = val.toString(16).toUpperCase();
        octInp.value = val.toString(8);

        bitsWrap.innerHTML = '';
        for (let b = 7; b >= 0; b--) {
          const bitVal = (val >> b) & 1;
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'boo-bit-btn' + (bitVal ? ' active' : '');
          btn.textContent = bitVal;
          btn.title = `Бит ${b} (${Math.pow(2, b)})`;
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            val = val ^ (1 << b);
            item.data.value = val;
            updateCalcUI();
            saveWidget();
          });
          bitsWrap.appendChild(btn);
        }
      }

      decInp.addEventListener('input', () => {
        val = Number(decInp.value) || 0;
        item.data.value = val;
        updateCalcUI();
        saveWidget();
      });

      binInp.addEventListener('input', () => {
        val = parseInt(binInp.value, 2) || 0;
        item.data.value = val;
        updateCalcUI();
        saveWidget();
      });

      hexInp.addEventListener('input', () => {
        val = parseInt(hexInp.value, 16) || 0;
        item.data.value = val;
        updateCalcUI();
        saveWidget();
      });

      octInp.addEventListener('input', () => {
        val = parseInt(octInp.value, 8) || 0;
        item.data.value = val;
        updateCalcUI();
        saveWidget();
      });

      updateCalcUI();
    } else if (item.widgetType === 'fano_tree') {
      const codes = item.data.codes || { A: '00', B: '01', C: '10', D: '11' };
      item.data.codes = codes;

      function renderFano() {
        body.innerHTML = `
          <table class="boo-fano-table">
            <thead><tr><th style="width: 40px;">Символ</th><th>Код</th><th style="width: 24px;"></th></tr></thead>
            <tbody></tbody>
          </table>
          <button type="button" class="boo-check-add" id="btn-fano-add">+ Добавить символ</button>
          <div class="boo-fano-badge" id="lbl-fano-status"></div>
        `;

        const tbody = body.querySelector('tbody');
        Object.entries(codes).forEach(([sym, code]) => {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><input type="text" class="boo-fano-input boo-fano-sym" value="${sym}" maxlength="2"></td>
            <td><input type="text" class="boo-fano-input boo-fano-code" value="${code}"></td>
            <td><button type="button" class="boo-check-del">&times;</button></td>
          `;
          tr.querySelector('.boo-fano-sym').addEventListener('input', (e) => {
            const newSym = e.target.value.trim().toUpperCase();
            if (newSym && newSym !== sym) {
              codes[newSym] = code;
              delete codes[sym];
              saveWidget();
              validateFano();
            }
          });
          tr.querySelector('.boo-fano-code').addEventListener('input', (e) => {
            codes[sym] = e.target.value.trim();
            saveWidget();
            validateFano();
          });
          tr.querySelector('.boo-check-del').addEventListener('click', (e) => {
            e.stopPropagation();
            delete codes[sym];
            renderFano();
            saveWidget();
          });
          tbody.appendChild(tr);
        });

        body.querySelector('#btn-fano-add').addEventListener('click', (e) => {
          e.stopPropagation();
          const nextSym = String.fromCharCode(65 + Object.keys(codes).length);
          codes[nextSym] = '0';
          renderFano();
          saveWidget();
        });

        validateFano();
      }

      function validateFano() {
        const badge = body.querySelector('#lbl-fano-status');
        if (!badge) return;
        const entries = Object.entries(codes);
        let violation = null;

        for (let i = 0; i < entries.length; i++) {
          for (let j = 0; j < entries.length; j++) {
            if (i !== j) {
              const [sym1, c1] = entries[i];
              const [sym2, c2] = entries[j];
              if (c1 && c2 && c2.startsWith(c1)) {
                violation = `'${c1}' (${sym1}) префикс для '${c2}' (${sym2})`;
                break;
              }
            }
          }
          if (violation) break;
        }

        if (violation) {
          badge.className = 'boo-fano-badge invalid';
          badge.textContent = `⚠️ Нарушение: ${violation}`;
        } else {
          badge.className = 'boo-fano-badge valid';
          badge.textContent = `✓ Условие Фано выполняется`;
        }
      }

      renderFano();
    } else if (item.widgetType === 'turtle') {
      const codeVal = item.data.code || 'repeat 4 [ fd 40 rt 90 ]';
      body.innerHTML = `
        <div style="display: flex; gap: 3px; margin-bottom: 4px;">
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-t-p" data-c="repeat 4 [ fd 40 rt 90 ]" style="padding: 2px 4px; font-size: 9px;">Квадрат</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-t-p" data-c="repeat 3 [ fd 50 rt 120 ]" style="padding: 2px 4px; font-size: 9px;">Треугольник</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-t-p" data-c="repeat 5 [ fd 45 rt 144 ]" style="padding: 2px 4px; font-size: 9px;">Звезда</button>
        </div>
        <textarea class="boo-turtle-ta">${codeVal}</textarea>
        <div style="display: flex; gap: 4px; margin: 4px 0;">
          <button type="button" class="boo-confirm-btn boo-confirm-danger boo-t-run" style="padding: 3px 8px; font-size: 10px;">▶ Запустить</button>
          <button type="button" class="boo-confirm-btn boo-confirm-cancel boo-t-clear" style="padding: 3px 8px; font-size: 10px;">Очистить</button>
        </div>
        <canvas class="boo-turtle-canvas"></canvas>
      `;

      const ta = body.querySelector('.boo-turtle-ta');
      const canvasEl = body.querySelector('.boo-turtle-canvas');

      function runTurtle() {
        const dprVal = window.devicePixelRatio || 1;
        const cw = canvasEl.clientWidth || 240;
        const ch = Math.max(80, canvasEl.clientHeight || 110);
        canvasEl.width = Math.floor(cw * dprVal);
        canvasEl.height = Math.floor(ch * dprVal);
        const tctx = canvasEl.getContext('2d');
        tctx.scale(dprVal, dprVal);
        tctx.clearRect(0, 0, cw, ch);

        let curX = cw / 2;
        let curY = ch / 2;
        let angle = -90; // pointing up

        tctx.strokeStyle = '#6366f1';
        tctx.lineWidth = 2;
        tctx.beginPath();
        tctx.moveTo(curX, curY);

        let script = ta.value;
        item.data.code = script;

        // Simple parser for repeat N [ commands ]
        script = script.replace(/repeat\s+(\d+)\s*\[([^\]]+)\]/gi, (_, n, block) => {
          return Array(Number(n)).fill(block).join(' ');
        });

        const tokens = script.trim().split(/\s+/);
        for (let i = 0; i < tokens.length; i++) {
          const cmd = tokens[i].toLowerCase();
          const arg = Number(tokens[i + 1]) || 0;
          if (cmd === 'fd') {
            const rad = (angle * Math.PI) / 180;
            curX += arg * Math.cos(rad);
            curY += arg * Math.sin(rad);
            tctx.lineTo(curX, curY);
            i++;
          } else if (cmd === 'bk') {
            const rad = (angle * Math.PI) / 180;
            curX -= arg * Math.cos(rad);
            curY -= arg * Math.sin(rad);
            tctx.lineTo(curX, curY);
            i++;
          } else if (cmd === 'rt') {
            angle += arg;
            i++;
          } else if (cmd === 'lt') {
            angle -= arg;
            i++;
          }
        }
        tctx.stroke();

        // Draw small turtle head
        tctx.fillStyle = '#10b981';
        tctx.beginPath();
        tctx.arc(curX, curY, 4, 0, Math.PI * 2);
        tctx.fill();
      }

      body.querySelector('.boo-t-run').addEventListener('click', (e) => {
        e.stopPropagation();
        runTurtle();
        saveWidget();
      });

      body.querySelector('.boo-t-clear').addEventListener('click', (e) => {
        e.stopPropagation();
        const tctx = canvasEl.getContext('2d');
        tctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
      });

      body.querySelectorAll('.boo-t-p').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          ta.value = btn.dataset.c;
          runTurtle();
          saveWidget();
        });
      });

      ta.addEventListener('input', () => {
        item.data.code = ta.value;
        saveWidget();
      });

      el._onResize = () => runTurtle();
      setTimeout(runTurtle, 50);
    } else if (item.widgetType === 'number_line') {
      if (item.data.min === undefined) item.data.min = -5;
      if (item.data.max === undefined) item.data.max = 5;
      if (!item.data.points) item.data.points = [{ val: -2, solid: true, label: 'x₁' }, { val: 3, solid: false, label: 'x₂' }];
      if (!item.data.interval) item.data.interval = [-2, 3];

      body.innerHTML = `
        <div class="boo-nl-canvas-wrap">
          <canvas class="boo-nl-canvas" style="width: 100%; height: 100%;"></canvas>
        </div>
        <div class="boo-nl-ctrls">
          <button type="button" class="boo-nl-btn boo-nl-add-pt">+ Точка</button>
          <button type="button" class="boo-nl-btn boo-nl-toggle-type">Закраш./Выкол.</button>
          <button type="button" class="boo-nl-btn boo-nl-set-range">[-5; 5]</button>
          <button type="button" class="boo-nl-btn boo-nl-preset1">x ≥ 2</button>
          <button type="button" class="boo-nl-btn boo-nl-preset2">[-2; 3)</button>
          <button type="button" class="boo-nl-btn boo-nl-preset3">[0; 5]</button>
        </div>
      `;

      const cvs = body.querySelector('.boo-nl-canvas');
      let isDraggingPt = null;

      function renderNL() {
        const rect = cvs.parentElement.getBoundingClientRect();
        cvs.width = Math.max(260, rect.width) * (window.devicePixelRatio || 1);
        cvs.height = Math.max(90, rect.height) * (window.devicePixelRatio || 1);
        const nctx = cvs.getContext('2d');
        nctx.setTransform(window.devicePixelRatio || 1, 0, 0, window.devicePixelRatio || 1, 0, 0);
        const w = rect.width || 300;
        const h = rect.height || 100;
        nctx.clearRect(0, 0, w, h);

        const pad = 36;
        const lineY = h / 2 + 10;
        const minVal = Number(item.data.min) || -5;
        const maxVal = Number(item.data.max) || 5;
        const range = Math.max(1, maxVal - minVal);

        function valToX(v) {
          return pad + ((v - minVal) / range) * (w - pad * 2);
        }

        // Draw intervals / hatching
        if (item.data.interval && item.data.interval.length === 2) {
          const x1 = Math.max(pad, valToX(item.data.interval[0]));
          const x2 = Math.min(w - pad, valToX(item.data.interval[1]));
          nctx.save();
          nctx.fillStyle = 'rgba(99, 102, 241, 0.15)';
          nctx.fillRect(x1, lineY - 24, x2 - x1, 24);
          nctx.strokeStyle = 'rgba(99, 102, 241, 0.5)';
          nctx.lineWidth = 1.5;
          for (let hx = x1; hx <= x2; hx += 8) {
            nctx.beginPath();
            nctx.moveTo(hx, lineY);
            nctx.lineTo(Math.min(x2, hx + 12), lineY - 24);
            nctx.stroke();
          }
          nctx.restore();
        }

        // Main axis line with arrow
        nctx.beginPath();
        nctx.strokeStyle = '#0f172a';
        nctx.lineWidth = 2.5;
        nctx.moveTo(pad - 10, lineY);
        nctx.lineTo(w - pad + 18, lineY);
        nctx.stroke();

        // Arrow tip
        nctx.beginPath();
        nctx.fillStyle = '#0f172a';
        nctx.moveTo(w - pad + 24, lineY);
        nctx.lineTo(w - pad + 12, lineY - 6);
        nctx.lineTo(w - pad + 12, lineY + 6);
        nctx.closePath();
        nctx.fill();

        // Axis label X
        nctx.font = 'italic bold 13px sans-serif';
        nctx.fillText('x', w - pad + 18, lineY - 10);

        // Tick marks & numbers
        const step = range <= 12 ? 1 : (range <= 24 ? 2 : 5);
        nctx.font = '10px sans-serif';
        nctx.textAlign = 'center';
        nctx.fillStyle = '#64748b';
        for (let v = Math.ceil(minVal); v <= maxVal; v += step) {
          const tx = valToX(v);
          nctx.beginPath();
          nctx.moveTo(tx, lineY - 4);
          nctx.lineTo(tx, lineY + 4);
          nctx.strokeStyle = '#94a3b8';
          nctx.lineWidth = 1;
          nctx.stroke();
          nctx.fillText(String(v), tx, lineY + 18);
        }

        // Draw points
        item.data.points.forEach((pt) => {
          const px = valToX(pt.val);
          nctx.beginPath();
          nctx.arc(px, lineY, 6, 0, Math.PI * 2);
          if (pt.solid) {
            nctx.fillStyle = '#4f46e5';
            nctx.fill();
            nctx.strokeStyle = '#312e81';
            nctx.lineWidth = 2;
            nctx.stroke();
          } else {
            nctx.fillStyle = '#ffffff';
            nctx.fill();
            nctx.strokeStyle = '#4f46e5';
            nctx.lineWidth = 2.5;
            nctx.stroke();
          }
          nctx.fillStyle = '#1e1b4b';
          nctx.font = 'bold 11px sans-serif';
          nctx.fillText(`${pt.label || 'x'}=${Math.round(pt.val * 10) / 10}`, px, lineY - 12);
        });
      }

      cvs.addEventListener('pointerdown', (e) => {
        const rect = cvs.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const pad = 36;
        const range = Math.max(1, (Number(item.data.max) || 5) - (Number(item.data.min) || -5));
        const clickedVal = (Number(item.data.min) || -5) + ((mx - pad) / (rect.width - pad * 2)) * range;

        const ptIdx = item.data.points.findIndex((pt) => {
          const px = pad + ((pt.val - (Number(item.data.min) || -5)) / range) * (rect.width - pad * 2);
          return Math.abs(px - mx) < 14;
        });

        if (ptIdx !== -1) {
          isDraggingPt = ptIdx;
          cvs.setPointerCapture(e.pointerId);
        } else {
          const newPt = { val: Math.round(clickedVal * 2) / 2, solid: true, label: `x${item.data.points.length + 1}` };
          item.data.points.push(newPt);
          isDraggingPt = item.data.points.length - 1;
          renderNL();
          saveWidget();
        }
        e.stopPropagation();
      });

      cvs.addEventListener('pointermove', (e) => {
        if (isDraggingPt === null) return;
        const rect = cvs.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const pad = 36;
        const minVal = Number(item.data.min) || -5;
        const maxVal = Number(item.data.max) || 5;
        const range = Math.max(1, maxVal - minVal);
        let val = minVal + ((mx - pad) / (rect.width - pad * 2)) * range;
        val = Math.max(minVal, Math.min(maxVal, Math.round(val * 2) / 2));
        item.data.points[isDraggingPt].val = val;
        renderNL();
        e.stopPropagation();
      });

      cvs.addEventListener('pointerup', () => {
        if (isDraggingPt !== null) {
          isDraggingPt = null;
          saveWidget();
        }
      });

      body.querySelector('.boo-nl-add-pt').addEventListener('click', (e) => {
        e.stopPropagation();
        const val = Math.round((Math.random() * 6 - 3) * 2) / 2;
        item.data.points.push({ val, solid: true, label: `x${item.data.points.length + 1}` });
        renderNL();
        saveWidget();
      });

      body.querySelector('.boo-nl-toggle-type').addEventListener('click', (e) => {
        e.stopPropagation();
        if (item.data.points.length > 0) {
          const last = item.data.points[item.data.points.length - 1];
          last.solid = !last.solid;
          renderNL();
          saveWidget();
        }
      });

      body.querySelector('.boo-nl-set-range').addEventListener('click', (e) => {
        e.stopPropagation();
        const curMin = Number(item.data.min) || -5;
        if (curMin === -5) { item.data.min = -10; item.data.max = 10; }
        else if (curMin === -10) { item.data.min = 0; item.data.max = 10; }
        else { item.data.min = -5; item.data.max = 5; }
        e.currentTarget.textContent = `[${item.data.min}; ${item.data.max}]`;
        renderNL();
        saveWidget();
      });

      body.querySelector('.boo-nl-preset1').addEventListener('click', (e) => {
        e.stopPropagation();
        item.data.min = -5; item.data.max = 10;
        item.data.points = [{ val: 2, solid: true, label: 'x₁' }];
        item.data.interval = [2, 10];
        renderNL();
        saveWidget();
      });

      body.querySelector('.boo-nl-preset2').addEventListener('click', (e) => {
        e.stopPropagation();
        item.data.min = -5; item.data.max = 5;
        item.data.points = [{ val: -2, solid: true, label: 'x₁' }, { val: 3, solid: false, label: 'x₂' }];
        item.data.interval = [-2, 3];
        renderNL();
        saveWidget();
      });

      body.querySelector('.boo-nl-preset3').addEventListener('click', (e) => {
        e.stopPropagation();
        item.data.min = -4; item.data.max = 6;
        item.data.points = [{ val: 0, solid: true, label: 'A' }, { val: 5, solid: true, label: 'B' }];
        item.data.interval = [0, 5];
        renderNL();
        saveWidget();
      });

      el._onResize = () => renderNL();
      setTimeout(renderNL, 60);
    } else if (item.widgetType === 'graph') {
      if (!item.data.nodes) {
        item.data.nodes = [
          { id: 'A', x: 60, y: 50 },
          { id: 'B', x: 200, y: 50 },
          { id: 'C', x: 130, y: 130 },
          { id: 'D', x: 250, y: 130 }
        ];
      }
      if (!item.data.edges) {
        item.data.edges = [
          { from: 'A', to: 'B', weight: '7' },
          { from: 'B', to: 'C', weight: '3' },
          { from: 'A', to: 'C', weight: '4' },
          { from: 'B', to: 'D', weight: '9' }
        ];
      }
      if (item.data.directed === undefined) item.data.directed = false;

      body.innerHTML = `
        <div class="boo-graph-canvas-wrap">
          <canvas class="boo-graph-canvas" style="width: 100%; height: 100%;"></canvas>
        </div>
        <div class="boo-graph-ctrls">
          <button type="button" class="boo-graph-btn boo-g-add-node">+ Вершина</button>
          <button type="button" class="boo-graph-btn boo-g-toggle-dir">${item.data.directed ? 'Ориентированный →' : 'Неориентированный —'}</button>
          <button type="button" class="boo-graph-btn boo-g-preset-k4">Полный K₄</button>
          <button type="button" class="boo-graph-btn boo-g-preset-tree">Дерево</button>
          <button type="button" class="boo-graph-btn boo-g-preset-cycle">Цикл C₅</button>
          <button type="button" class="boo-graph-btn boo-g-clear">Очистить</button>
        </div>
      `;

      const gcvs = body.querySelector('.boo-graph-canvas');
      let dragNodeId = null;
      let selectedNodeId = null;

      function renderGraph() {
        const rect = gcvs.parentElement.getBoundingClientRect();
        gcvs.width = Math.max(260, rect.width) * (window.devicePixelRatio || 1);
        gcvs.height = Math.max(160, rect.height) * (window.devicePixelRatio || 1);
        const gctx = gcvs.getContext('2d');
        gctx.setTransform(window.devicePixelRatio || 1, 0, 0, window.devicePixelRatio || 1, 0, 0);
        const w = rect.width || 300;
        const h = rect.height || 180;
        gctx.clearRect(0, 0, w, h);

        const nodeMap = new Map();
        item.data.nodes.forEach((n) => nodeMap.set(n.id, n));

        // Draw edges
        item.data.edges.forEach((ed) => {
          const n1 = nodeMap.get(ed.from);
          const n2 = nodeMap.get(ed.to);
          if (!n1 || !n2) return;

          gctx.beginPath();
          gctx.strokeStyle = '#475569';
          gctx.lineWidth = 2;
          gctx.moveTo(n1.x, n1.y);
          gctx.lineTo(n2.x, n2.y);
          gctx.stroke();

          // Directed arrow
          if (item.data.directed) {
            const angle = Math.atan2(n2.y - n1.y, n2.x - n1.x);
            const r = 16;
            const ax = n2.x - Math.cos(angle) * r;
            const ay = n2.y - Math.sin(angle) * r;
            gctx.beginPath();
            gctx.fillStyle = '#475569';
            gctx.moveTo(ax, ay);
            gctx.lineTo(ax - Math.cos(angle - 0.4) * 10, ay - Math.sin(angle - 0.4) * 10);
            gctx.lineTo(ax - Math.cos(angle + 0.4) * 10, ay - Math.sin(angle + 0.4) * 10);
            gctx.closePath();
            gctx.fill();
          }

          // Edge weight
          if (ed.weight) {
            const mx = (n1.x + n2.x) / 2;
            const my = (n1.y + n2.y) / 2;
            gctx.fillStyle = '#ffffff';
            gctx.beginPath();
            gctx.arc(mx, my, 9, 0, Math.PI * 2);
            gctx.fill();
            gctx.strokeStyle = '#cbd5e1';
            gctx.lineWidth = 1;
            gctx.stroke();

            gctx.fillStyle = '#6366f1';
            gctx.font = 'bold 10px sans-serif';
            gctx.textAlign = 'center';
            gctx.textBaseline = 'middle';
            gctx.fillText(String(ed.weight), mx, my);
          }
        });

        // Draw nodes
        item.data.nodes.forEach((n) => {
          const isSel = selectedNodeId === n.id;
          gctx.beginPath();
          gctx.arc(n.x, n.y, 16, 0, Math.PI * 2);
          gctx.fillStyle = isSel ? '#ede9fe' : '#ffffff';
          gctx.fill();
          gctx.strokeStyle = isSel ? '#6366f1' : '#334155';
          gctx.lineWidth = isSel ? 3 : 2;
          gctx.stroke();

          gctx.fillStyle = '#0f172a';
          gctx.font = 'bold 12px sans-serif';
          gctx.textAlign = 'center';
          gctx.textBaseline = 'middle';
          gctx.fillText(n.id, n.x, n.y);
        });
      }

      gcvs.addEventListener('pointerdown', (e) => {
        const rect = gcvs.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        const hitNode = item.data.nodes.find((n) => Math.hypot(n.x - mx, n.y - my) <= 18);
        if (hitNode) {
          if (selectedNodeId && selectedNodeId !== hitNode.id) {
            const existing = item.data.edges.find((ed) => (ed.from === selectedNodeId && ed.to === hitNode.id) || (!item.data.directed && ed.from === hitNode.id && ed.to === selectedNodeId));
            if (!existing) {
              const weight = String(Math.floor(Math.random() * 9) + 1);
              item.data.edges.push({ from: selectedNodeId, to: hitNode.id, weight });
            }
            selectedNodeId = null;
          } else {
            selectedNodeId = hitNode.id;
            dragNodeId = hitNode.id;
            gcvs.setPointerCapture(e.pointerId);
          }
        } else {
          selectedNodeId = null;
        }
        renderGraph();
        e.stopPropagation();
      });

      gcvs.addEventListener('pointermove', (e) => {
        if (!dragNodeId) return;
        const rect = gcvs.getBoundingClientRect();
        const mx = Math.max(20, Math.min(rect.width - 20, e.clientX - rect.left));
        const my = Math.max(20, Math.min(rect.height - 20, e.clientY - rect.top));
        const node = item.data.nodes.find((n) => n.id === dragNodeId);
        if (node) {
          node.x = mx;
          node.y = my;
          renderGraph();
        }
        e.stopPropagation();
      });

      gcvs.addEventListener('pointerup', () => {
        if (dragNodeId) {
          dragNodeId = null;
          saveWidget();
        }
      });

      body.querySelector('.boo-g-add-node').addEventListener('click', (e) => {
        e.stopPropagation();
        const rect = gcvs.getBoundingClientRect();
        const id = String.fromCharCode(65 + (item.data.nodes.length % 26)) + (item.data.nodes.length >= 26 ? Math.floor(item.data.nodes.length / 26) : '');
        const x = Math.floor(Math.random() * (rect.width - 60)) + 30;
        const y = Math.floor(Math.random() * (rect.height - 60)) + 30;
        item.data.nodes.push({ id, x, y });
        renderGraph();
        saveWidget();
      });

      body.querySelector('.boo-g-toggle-dir').addEventListener('click', (e) => {
        e.stopPropagation();
        item.data.directed = !item.data.directed;
        e.currentTarget.textContent = item.data.directed ? 'Ориентированный →' : 'Неориентированный —';
        renderGraph();
        saveWidget();
      });

      body.querySelector('.boo-g-preset-k4').addEventListener('click', (e) => {
        e.stopPropagation();
        item.data.nodes = [
          { id: 'A', x: 70, y: 40 }, { id: 'B', x: 230, y: 40 },
          { id: 'C', x: 70, y: 140 }, { id: 'D', x: 230, y: 140 }
        ];
        item.data.edges = [
          { from: 'A', to: 'B', weight: '2' }, { from: 'B', to: 'D', weight: '4' },
          { from: 'D', to: 'C', weight: '6' }, { from: 'C', to: 'A', weight: '3' },
          { from: 'A', to: 'D', weight: '5' }, { from: 'B', to: 'C', weight: '7' }
        ];
        renderGraph();
        saveWidget();
      });

      body.querySelector('.boo-g-preset-tree').addEventListener('click', (e) => {
        e.stopPropagation();
        item.data.nodes = [
          { id: 'Root', x: 150, y: 35 },
          { id: 'L', x: 80, y: 95 }, { id: 'R', x: 220, y: 95 },
          { id: 'L1', x: 50, y: 145 }, { id: 'L2', x: 110, y: 145 }
        ];
        item.data.edges = [
          { from: 'Root', to: 'L', weight: '1' }, { from: 'Root', to: 'R', weight: '2' },
          { from: 'L', to: 'L1', weight: '3' }, { from: 'L', to: 'L2', weight: '4' }
        ];
        renderGraph();
        saveWidget();
      });

      body.querySelector('.boo-g-preset-cycle').addEventListener('click', (e) => {
        e.stopPropagation();
        const r = 60, cx = 150, cy = 90;
        item.data.nodes = ['A', 'B', 'C', 'D', 'E'].map((id, i) => {
          const ang = (i * 2 * Math.PI) / 5 - Math.PI / 2;
          return { id, x: Math.round(cx + r * Math.cos(ang)), y: Math.round(cy + r * Math.sin(ang)) };
        });
        item.data.edges = [
          { from: 'A', to: 'B', weight: '1' }, { from: 'B', to: 'C', weight: '2' },
          { from: 'C', to: 'D', weight: '3' }, { from: 'D', to: 'E', weight: '4' },
          { from: 'E', to: 'A', weight: '5' }
        ];
        renderGraph();
        saveWidget();
      });

      body.querySelector('.boo-g-clear').addEventListener('click', (e) => {
        e.stopPropagation();
        item.data.nodes = [];
        item.data.edges = [];
        renderGraph();
        saveWidget();
      });

      el._onResize = () => renderGraph();
      setTimeout(renderGraph, 60);
    } else {
      body.innerHTML = `
        <div style="font-size: 12px; font-weight: 600; color: #475569; padding: 10px;">
          Модуль ${item.widgetType} активен.
        </div>
      `;
    }

    return el;
  }

  // --- Selection Box & Marquee Logic ---

  function getStrokeScreenBounds(s, activeRect = getActiveTaskContentRect()) {
    if (!s.points || s.points.length === 0) return null;
    const pts = s.points.map((p) => pointToScreen(p, s, activeRect));

    if (s.type === 'note' || s.type === 'image' || s.type === 'shape' || s.type === 'widget' || s.type === 'math') {
      const [p1, p2] = pts;
      if (!p1 || !p2) return null;
      const x = Math.min(p1.x, p2.x);
      const y = Math.min(p1.y, p2.y);
      const width = Math.max(6, Math.abs(p2.x - p1.x));
      const height = Math.max(6, Math.abs(p2.y - p1.y));
      return { x, y, width, height };
    }

    if (s.type === 'text') {
      const p = pts[0];
      const fSize = Math.max(12, Number(s.fontSize) || 20) * viewScale;
      const approxW = Math.max(20, (s.text?.length || 1) * fSize * 0.6);
      const approxH = fSize * 1.3;
      return { x: p.x, y: p.y, width: approxW, height: approxH };
    }

    // Freehand stroke / highlighter / polyline
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    pts.forEach((p) => {
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x);
      maxY = Math.max(maxY, p.y);
    });
    const pad = Math.max(4, (s.width || 3) * viewScale / 2);
    return {
      x: minX - pad,
      y: minY - pad,
      width: Math.max(8, maxX - minX + pad * 2),
      height: Math.max(8, maxY - minY + pad * 2),
    };
  }

  function getSelectionScreenBox() {
    if (selectedIds.size === 0) return null;
    const activeRect = getActiveTaskContentRect();
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    let found = 0;

    selectedIds.forEach((id) => {
      const s = strokes.find((item) => item.id === id);
      if (!s) return;
      const b = getStrokeScreenBounds(s, activeRect);
      if (b) {
        minX = Math.min(minX, b.x);
        minY = Math.min(minY, b.y);
        maxX = Math.max(maxX, b.x + b.width);
        maxY = Math.max(maxY, b.y + b.height);
        found++;
      }
    });

    if (found === 0) return null;
    return {
      x: minX,
      y: minY,
      width: Math.max(10, maxX - minX),
      height: Math.max(10, maxY - minY),
    };
  }

  function updateSelectionBox() {
    if (!selectionBox) return;
    if (tool !== 'select' || selectedIds.size === 0) {
      selectionBox.style.display = 'none';
      if (contextBar) contextBar.style.display = 'none';
      return;
    }

    const box = getSelectionScreenBox();
    if (!box) {
      selectionBox.style.display = 'none';
      if (contextBar) contextBar.style.display = 'none';
      return;
    }

    selectionBox.style.display = 'block';
    selectionBox.style.left = `${box.x - 4}px`;
    selectionBox.style.top = `${box.y - 4}px`;
    selectionBox.style.width = `${box.width + 8}px`;
    selectionBox.style.height = `${box.height + 8}px`;

    updateContextBar();
  }

  // --- Hit Testing ---

  function hitTest(screenX, screenY) {
    const activeRect = getActiveTaskContentRect();
    for (let i = strokes.length - 1; i >= 0; i--) {
      const s = strokes[i];
      const bounds = getStrokeScreenBounds(s, activeRect);
      if (!bounds) continue;

      if (screenX >= bounds.x && screenX <= bounds.x + bounds.width &&
          screenY >= bounds.y && screenY <= bounds.y + bounds.height) {

        if (s.type === 'shape' && (s.shape === 'line' || s.shape === 'arrow')) {
          const p1 = pointToScreen(s.points[0], s, activeRect);
          const p2 = pointToScreen(s.points[1], s, activeRect);
          if (distToSegment({ x: screenX, y: screenY }, p1, p2) <= 12) return s;
          continue;
        }

        if (s.type === 'stroke' || !s.type) {
          const pts = s.points.map((p) => pointToScreen(p, s, activeRect));
          let hit = false;
          for (let j = 0; j < pts.length - 1; j++) {
            if (distToSegment({ x: screenX, y: screenY }, pts[j], pts[j + 1]) <= Math.max(8, (s.width || 3) * viewScale)) {
              hit = true;
              break;
            }
          }
          if (hit) return s;
          continue;
        }

        return s;
      }
    }
    return null;
  }

  function distToSegment(p, a, b) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const lenSq = dx * dx + dy * dy;
    if (lenSq === 0) return Math.hypot(p.x - a.x, p.y - a.y);
    let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
  }

  function pointInPolygon(p, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i].x, yi = poly[i].y;
      const xj = poly[j].x, yj = poly[j].y;
      const intersect = ((yi > p.y) !== (yj > p.y)) &&
        (p.x < (xj - xi) * (p.y - yi) / (yj - yi) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  // --- Pointer Handlers ---

  function onPointerDown(e) {
    // Middle-click pans canvas
    if (e.button === 1) {
      e.preventDefault();
      middlePanActive = true;
      isPointerDown = true;
      interactionMode = 'pan';
      panStart = { x: e.clientX, y: e.clientY, offsetX: viewOffsetX, offsetY: viewOffsetY };
      canvas.setPointerCapture?.(e.pointerId);
      updateCursor();
      return;
    }

    if (e.button !== 0) return;
    if (isReadOnly && !['select', 'pan'].includes(tool)) {
      e.preventDefault();
      return;
    }
    toggleBrushMenu(false);
    toggleShapesMenu(false);
    toggleLaserMenu(false);
    togglePropPopover(false);
    toggleClearConfirm(false);
    resizeCanvas();
    isPointerDown = true;
    const origin = canvasOrigin();
    const screenX = e.clientX - origin.left;
    const screenY = e.clientY - origin.top;

    // Eyedropper: pick color directly from canvas
    if (tool === 'eyedropper') {
      try {
        const pixel = ctx.getImageData(screenX * dpr, screenY * dpr, 1, 1).data;
        const hex = `#${((1 << 24) + (pixel[0] << 16) + (pixel[1] << 8) + pixel[2]).toString(16).slice(1)}`;
        setPenColor(hex);
        setTool('pen');
      } catch (_) {}
      e.preventDefault();
      return;
    }

    // Space key pan override
    if (spaceKeyHeld || tool === 'pan') {
      interactionMode = 'pan';
      panStart = { x: e.clientX, y: e.clientY, offsetX: viewOffsetX, offsetY: viewOffsetY };
      canvas.setPointerCapture?.(e.pointerId);
      updateCursor();
      e.preventDefault();
      return;
    }

    // Laser pointer
    if (tool === 'laser') {
      interactionMode = 'laser';
      laserTrail.push({ x: screenX, y: screenY, t: Date.now(), isStart: true });
      drawLaserTop();
      realtimeSyncAdapter?.onLaserMove?.({ x: (screenX - viewOffsetX) / viewScale, y: (screenY - viewOffsetY) / viewScale }, true, { color: laserColor, width: laserWidth, isStart: true });
      canvas.setPointerCapture?.(e.pointerId);
      e.preventDefault();
      return;
    }

    // Lasso selection tool
    if (tool === 'lasso') {
      interactionMode = 'lasso';
      lassoPoints = [{ x: screenX, y: screenY }];
      canvas.setPointerCapture?.(e.pointerId);
      e.preventDefault();
      return;
    }

    // Select Tool
    if (tool === 'select') {
      let hit = hitTest(screenX, screenY);
      // If clicking inside current selection bounding box, treat as hit on the selected items!
      if (!hit && selectedIds.size > 0) {
        const selBox = getSelectionScreenBox();
        if (selBox && screenX >= selBox.x && screenX <= selBox.x + selBox.width &&
            screenY >= selBox.y && screenY <= selBox.y + selBox.height) {
          const firstId = selectedIds.values().next().value;
          hit = strokes.find((s) => s.id === firstId);
        }
      }
      if (hit) {
        if (e.shiftKey) {
          if (selectedIds.has(hit.id)) selectedIds.delete(hit.id);
          else selectedIds.add(hit.id);
        } else {
          if (!selectedIds.has(hit.id)) {
            selectedIds.clear();
            selectedIds.add(hit.id);
          }
        }
        updateSelectionBox();
        startMoveSelection(e);
      } else {
        // Marquee selection
        if (!e.shiftKey) selectedIds.clear();
        updateSelectionBox();
        interactionMode = 'marquee';
        marqueeStart = { x: screenX, y: screenY };
        marqueeBox.style.display = 'block';
        marqueeBox.style.left = `${screenX}px`;
        marqueeBox.style.top = `${screenY}px`;
        marqueeBox.style.width = '0px';
        marqueeBox.style.height = '0px';
      }
      canvas.setPointerCapture?.(e.pointerId);
      e.preventDefault();
      return;
    }

    // Eraser Object tool
    if (tool === 'eraser_object') {
      const hit = hitTest(screenX, screenY);
      if (hit) {
        deleteSingleStroke(hit.id);
        e.preventDefault();
        return;
      }
    }

    // Sticky Note Creation
    if (tool === 'note') {
      createStickyNoteAt(e);
      e.preventDefault();
      return;
    }

    // Text Tool
    if (tool === 'text') {
      const space = embeddedTarget ? null : getActiveTaskContentRect();
      const pos = pointForEvent(e, space);
      beginTextEntry(e, space, pos);
      e.preventDefault();
      return;
    }

    // Drawing / Shapes / Highlighter
    interactionMode = 'draw';
    const space = embeddedTarget ? null : getActiveTaskContentRect();
    const pos = pointForEvent(e, space);
    pos.p = (e.pressure !== undefined && e.pressure > 0) ? e.pressure : 0.5;
    pos.t = Date.now();
    const shape = ALL_SHAPE_IDS.includes(tool) ? tool : (tool === 'shape' ? currentShape : (tool === 'connector' ? 'arrow' : null));
    const isConnector = tool === 'connector' || ['line', 'arrow', 'double-arrow', 'curved-arrow'].includes(shape);
    const isHighlighter = tool === 'highlighter' || currentBrush === 'highlighter';
    const bId = isHighlighter ? 'highlighter' : (shape ? null : (currentBrush || 'ballpoint'));

    currentStroke = {
      id: generateId(shape ? 'shp' : (isHighlighter ? 'hl' : 'strk')),
      page_id: currentPageId,
      type: isConnector ? 'connector' : (shape ? 'shape' : (isHighlighter ? 'highlighter' : 'stroke')),
      brush: bId || 'ballpoint',
      shape: shape || 'rectangle',
      color: tool === 'eraser_stroke' ? null : (isHighlighter ? highlighterColor : penColor),
      fill: shape ? (shapeFill || 'none') : 'none',
      fillColor: penColor,
      density: bId === 'airbrush' ? airbrushDensity : undefined,
      width: getBrushDefaultWidth(bId, tool),
      opacity: getBrushDefaultOpacity(bId, tool),
      style: bId === 'dashed_pen' ? 'dashed' : strokeStyle,
      eraser: tool === 'eraser_stroke',
      space: space ? {
        left: space.left,
        top: space.top,
        width: space.width,
        height: space.height,
        task_id: space.task_id,
      } : null,
      points: [pos],
    };

    strokes.push(currentStroke);
    redoStack = [];
    redraw();
    realtimeSyncAdapter?.onStrokeLive?.('start', currentStroke);
    canvas.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  }

  function onPointerMove(e) {
    const origin = canvasOrigin();
    const screenX = e.clientX - origin.left;
    const screenY = e.clientY - origin.top;

    if (!isPointerDown) {
      return;
    }

    // Pan mode
    if (interactionMode === 'pan' && panStart) {
      viewOffsetX = panStart.offsetX + e.clientX - panStart.x;
      viewOffsetY = panStart.offsetY + e.clientY - panStart.y;
      redraw();
      updateSelectionBox();
      realtimeSyncAdapter?.onCameraChange?.(viewOffsetX, viewOffsetY, viewScale);
      e.preventDefault();
      return;
    }

    // Laser pointer
    if (interactionMode === 'laser') {
      laserTrail.push({ x: screenX, y: screenY, t: Date.now(), isStart: false });
      drawLaserTop();
      realtimeSyncAdapter?.onLaserMove?.({ x: (screenX - viewOffsetX) / viewScale, y: (screenY - viewOffsetY) / viewScale }, true, { color: laserColor, width: laserWidth, isStart: false });
      e.preventDefault();
      return;
    }

    // Lasso selection
    if (interactionMode === 'lasso') {
      lassoPoints.push({ x: screenX, y: screenY });
      redraw();
      // Draw lasso polyline on canvas
      ctx.save();
      ctx.strokeStyle = '#6366f1';
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      lassoPoints.forEach((p, idx) => {
        if (idx === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.stroke();
      ctx.restore();
      e.preventDefault();
      return;
    }

    // Marquee Selection Mode
    if (interactionMode === 'marquee') {
      const left = Math.min(marqueeStart.x, screenX);
      const top = Math.min(marqueeStart.y, screenY);
      const width = Math.abs(screenX - marqueeStart.x);
      const height = Math.abs(screenY - marqueeStart.y);
      marqueeBox.style.left = `${left}px`;
      marqueeBox.style.top = `${top}px`;
      marqueeBox.style.width = `${width}px`;
      marqueeBox.style.height = `${height}px`;
      e.preventDefault();
      return;
    }

    // Move Selection Mode
    if (interactionMode === 'move') {
      let dx = (e.clientX - dragStartPos.x) / viewScale;
      let dy = (e.clientY - dragStartPos.y) / viewScale;

      // Smart Alignment Guides
      activeGuides = [];
      const curBox = getSelectionScreenBox();
      if (curBox) {
        strokes.forEach((other) => {
          if (selectedIds.has(other.id)) return;
          const ob = getStrokeScreenBounds(other);
          if (!ob) return;
          if (Math.abs(curBox.x - ob.x) < 5) activeGuides.push({ type: 'v', pos: ob.x });
          if (Math.abs(curBox.y - ob.y) < 5) activeGuides.push({ type: 'h', pos: ob.y });
        });
      }

      selectedIds.forEach((id) => {
        const stroke = strokes.find((s) => s.id === id);
        const snapshot = moveSnapshot?.get(id);
        if (!stroke || !snapshot || stroke.locked) return;

        stroke.points = snapshot.map((p) => {
          const np = { ...p, x: p.x + dx, y: p.y + dy };
          if (stroke.space) {
            np.rx = (np.x - stroke.space.left) / stroke.space.width;
            np.ry = (np.y - stroke.space.top) / stroke.space.height;
          }
          return np;
        });
      });

      redraw();
      syncDomWidgets();
      updateSelectionBox();

      const now = performance.now();
      if (now - (lastMoveSyncTime || 0) > 28) {
        lastMoveSyncTime = now;
        const updated = strokes.filter((s) => selectedIds.has(s.id));
        if (updated.length) {
          const syncStrokes = updated.map((s) => {
            if (s.type === 'image' && s.src) {
              const { src, ...rest } = s;
              return rest;
            }
            return s;
          });
          realtimeSyncAdapter?.onStrokesUpdate?.(syncStrokes);
        }
      }

      e.preventDefault();
      return;
    }

    // Resize Selection Mode
    if (interactionMode === 'resize') {
      applyResize(e);
      e.preventDefault();
      return;
    }

    // Rotate Selection Mode
    if (interactionMode === 'rotate') {
      applyRotate(e);
      e.preventDefault();
      return;
    }

    // Draw / Shape Mode
    if (interactionMode === 'draw' && currentStroke) {
      const point = pointForEvent(e, currentStroke.space);
      point.p = (e.pressure !== undefined && e.pressure > 0) ? e.pressure : 0.5;
      point.t = Date.now();
      if (currentStroke.type === 'shape' || currentStroke.type === 'connector') {
        let finalPt = point;
        const p0 = currentStroke.points[0];
        const isStrict1to1 = e.shiftKey || ['square', 'circle', 'cube', 'star', 'equilateral-triangle'].includes(currentStroke.shape);
        if (isStrict1to1 && p0) {
          const dx = point.x - p0.x;
          const dy = point.y - p0.y;
          const maxDist = Math.max(Math.abs(dx), Math.abs(dy));
          finalPt = {
            ...point,
            x: p0.x + (dx >= 0 ? maxDist : -maxDist),
            y: p0.y + (dy >= 0 ? maxDist : -maxDist),
          };
        }
        currentStroke.points[1] = finalPt;
      } else {
        currentStroke.points.push(point);
      }
      redraw();
      realtimeSyncAdapter?.onStrokeLive?.('move', { stroke_id: currentStroke.id, stroke: currentStroke });
      e.preventDefault();
    }
  }

  function onPointerUp(e) {
    if (!isPointerDown) return;
    isPointerDown = false;
    middlePanActive = false;
    activeGuides = [];

    if (interactionMode === 'pan') {
      panStart = null;
      interactionMode = null;
      updateCursor();
      realtimeSyncAdapter?.onCameraChange?.(viewOffsetX, viewOffsetY, viewScale);
      return;
    }

    if (interactionMode === 'laser') {
      interactionMode = null;
      realtimeSyncAdapter?.onLaserMove?.(null, false);
      return;
    }

    // Finish Lasso Selection
    if (interactionMode === 'lasso') {
      interactionMode = null;
      if (lassoPoints.length > 3) {
        const activeRect = getActiveTaskContentRect();
        strokes.forEach((s) => {
          const b = getStrokeScreenBounds(s, activeRect);
          if (b && pointInPolygon({ x: b.x + b.width / 2, y: b.y + b.height / 2 }, lassoPoints)) {
            selectedIds.add(s.id);
          }
        });
      }
      lassoPoints = [];
      setTool('select');
      updateSelectionBox();
      redraw();
      return;
    }

    // Finish Marquee Selection
    if (interactionMode === 'marquee') {
      marqueeBox.style.display = 'none';
      const origin = canvasOrigin();
      const screenX = e.clientX - origin.left;
      const screenY = e.clientY - origin.top;
      const left = Math.min(marqueeStart.x, screenX);
      const top = Math.min(marqueeStart.y, screenY);
      const width = Math.abs(screenX - marqueeStart.x);
      const height = Math.abs(screenY - marqueeStart.y);

      if (width > 4 || height > 4) {
        const activeRect = getActiveTaskContentRect();
        strokes.forEach((s) => {
          const b = getStrokeScreenBounds(s, activeRect);
          if (b && !(b.x + b.width < left || b.x > left + width || b.y + b.height < top || b.y > top + height)) {
            selectedIds.add(s.id);
          }
        });
      }
      updateSelectionBox();
      interactionMode = null;
      return;
    }

    if (interactionMode === 'move' || interactionMode === 'resize' || interactionMode === 'rotate') {
      const updated = strokes.filter((s) => selectedIds.has(s.id));
      interactionMode = null;
      moveSnapshot = null;
      resizeSnapshot = null;
      dirty = true;
      saveLocal();
      scheduleSave();
      if (updated.length) {
        const syncStrokes = updated.map((s) => {
          if (s.type === 'image' && s.src) {
            const { src, ...rest } = s;
            return rest;
          }
          return s;
        });
        realtimeSyncAdapter?.onStrokesUpdate?.(syncStrokes);
      }
      return;
    }

    if (interactionMode === 'draw') {
      if (currentStroke && (currentStroke.type === 'shape' || currentStroke.type === 'connector')) {
        // If user clicked without dragging, provide default dimensions so the shape appears immediately
        if (currentStroke.points.length < 2 || (Math.abs(currentStroke.points[0].x - currentStroke.points[1].x) < 3 && Math.abs(currentStroke.points[0].y - currentStroke.points[1].y) < 3)) {
          const p0 = currentStroke.points[0];
          const isSq = ['square', 'circle', 'cube', 'star', 'equilateral-triangle'].includes(currentStroke.shape);
          const defW = isSq ? 90 : 130;
          const defH = isSq ? 90 : 85;
          currentStroke.points[1] = {
            x: p0.x + defW,
            y: p0.y + defH,
            p: 0.5,
            t: Date.now(),
          };
          redraw();
        }
      }

      // Auto-shape recognition & line straightening
      if (currentStroke && currentStroke.points.length > 5 && isStrictShape) {
        recognizeGeometricShape(currentStroke);
      }

      if (currentStroke && currentStroke.brush === 'airbrush') {
        renderAirbrushToCache(currentStroke);
      }

      const finished = currentStroke;
      interactionMode = null;
      currentStroke = null;
      dirty = true;
      saveLocal();
      scheduleSave();
      if (finished) {
        finished.page_id = finished.page_id || currentPageId;
        realtimeSyncAdapter?.onStrokeLive?.('end', { stroke_id: finished.id, page_id: finished.page_id });
        realtimeSyncAdapter?.onStrokeCommit?.(finished);
      }
    }

    if (e && e.pointerId !== undefined) {
      try { e.target?.releasePointerCapture?.(e.pointerId); } catch (_) {}
      try { canvas.releasePointerCapture?.(e.pointerId); } catch (_) {}
    }
  }

  // --- Auto Shape Recognition ---

  function recognizeGeometricShape(s) {
    const pts = s.points;
    const p1 = pts[0];
    const p2 = pts[pts.length - 1];
    const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);

    // If start and end are close: Circle / Rectangle
    if (dist < 40) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      pts.forEach((p) => {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x);
        maxY = Math.max(maxY, p.y);
      });
      const w = maxX - minX;
      const h = maxY - minY;
      const aspect = Math.abs(w - h) / Math.max(w, h);

      s.type = 'shape';
      s.shape = aspect < 0.25 ? 'ellipse' : 'rounded-rect';
      s.points = [{ x: minX, y: minY }, { x: maxX, y: maxY }];
      redraw();
    } else {
      // Check straight line deviation
      let maxDev = 0;
      pts.forEach((p) => {
        maxDev = Math.max(maxDev, distToSegment(p, p1, p2));
      });
      if (maxDev < 15) {
        s.type = 'shape';
        s.shape = 'line';
        s.points = [p1, p2];
        redraw();
      }
    }
  }

  // --- Move, Resize & Rotate Operations ---

  function startMoveSelection(e) {
    interactionMode = 'move';
    isPointerDown = true;
    dragStartPos = { x: e.clientX, y: e.clientY };
    moveSnapshot = new Map();
    selectedIds.forEach((id) => {
      const s = strokes.find((item) => item.id === id);
      if (s) {
        moveSnapshot.set(id, JSON.parse(JSON.stringify(s.points)));
      }
    });
    if (e.target && typeof e.target.setPointerCapture === 'function') {
      try { e.target.setPointerCapture(e.pointerId); } catch (_) {}
    }
  }

  function getSelectionWorldBounds() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    let count = 0;
    selectedIds.forEach((id) => {
      const s = strokes.find((item) => item.id === id);
      if (!s || !s.points || s.points.length === 0) return;
      if (s.type === 'text') {
        const p = s.points[0];
        const fSize = Math.max(12, Number(s.fontSize) || 20);
        const textLen = (s.text && s.text.length) ? s.text.length : 4;
        const approxW = Math.max(24, textLen * fSize * 0.62);
        const approxH = fSize * 1.3;
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x + approxW);
        maxY = Math.max(maxY, p.y + approxH);
        count++;
        return;
      }
      s.points.forEach((p) => {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x);
        maxY = Math.max(maxY, p.y);
        count++;
      });
    });
    if (count === 0) return null;
    return {
      x: minX,
      y: minY,
      width: Math.max(15, maxX - minX),
      height: Math.max(15, maxY - minY),
      cx: (minX + maxX) / 2,
      cy: (minY + maxY) / 2,
    };
  }

  let resizeStartWorldBounds = null;

  function onHandlePointerDown(e, handle) {
    e.stopPropagation();
    e.preventDefault();
    interactionMode = 'resize';
    isPointerDown = true;
    resizeHandle = handle;
    dragStartPos = { x: e.clientX, y: e.clientY };
    resizeStartWorldBounds = getSelectionWorldBounds();
    resizeSnapshot = new Map();
    selectedIds.forEach((id) => {
      const s = strokes.find((item) => item.id === id);
      if (s && s.points) {
        resizeSnapshot.set(id, {
          points: JSON.parse(JSON.stringify(s.points)),
          fontSize: s.fontSize || 20,
        });
      }
    });
    try {
      e.target?.setPointerCapture?.(e.pointerId);
    } catch (_) {}
  }

  function applyResize(e) {
    if (!resizeStartWorldBounds || !resizeHandle) return;
    const dx = (e.clientX - dragStartPos.x) / viewScale;
    const dy = (e.clientY - dragStartPos.y) / viewScale;

    const origX = resizeStartWorldBounds.x;
    const origY = resizeStartWorldBounds.y;
    const origW = resizeStartWorldBounds.width;
    const origH = resizeStartWorldBounds.height;

    let newW = origW;
    let newH = origH;
    let anchorX = origX;
    let anchorY = origY;

    if (resizeHandle.includes('r')) {
      newW = origW + dx;
      anchorX = origX;
    } else if (resizeHandle.includes('l')) {
      newW = origW - dx;
      anchorX = origX + origW;
    }

    if (resizeHandle.includes('b')) {
      newH = origH + dy;
      anchorY = origY;
    } else if (resizeHandle.includes('t')) {
      newH = origH - dy;
      anchorY = origY + origH;
    }

    newW = Math.max(15, newW);
    newH = Math.max(15, newH);

    let scaleX = newW / origW;
    let scaleY = newH / origH;

    if (e.shiftKey) {
      const s = Math.max(scaleX, scaleY);
      scaleX = s;
      scaleY = s;
    }

    selectedIds.forEach((id) => {
      const stroke = strokes.find((s) => s.id === id);
      const snapshot = resizeSnapshot?.get(id);
      if (!stroke || !snapshot) return;

      if (stroke.type === 'text') {
        const snapPts = snapshot.points || snapshot;
        const origP = snapPts[0];
        const baseFontSize = snapshot.fontSize || stroke.fontSize || 20;

        let scale = 1;
        if (resizeHandle.includes('r') || resizeHandle.includes('l')) {
          scale = scaleX;
          if (resizeHandle.includes('t') || resizeHandle.includes('b')) {
            scale = Math.max(scaleX, scaleY);
          }
        } else if (resizeHandle.includes('t') || resizeHandle.includes('b')) {
          scale = scaleY;
        }

        stroke.fontSize = Math.max(10, Math.min(160, Math.round(baseFontSize * scale)));

        let nextX = origP.x;
        let nextY = origP.y;

        if (resizeHandle.includes('l')) {
          nextX = (origX + origW) - newW;
        } else if (resizeHandle.includes('r')) {
          nextX = origX;
        }

        if (resizeHandle.includes('t')) {
          nextY = (origY + origH) - newH;
        } else if (resizeHandle.includes('b')) {
          nextY = origY;
        }

        stroke.points = [{ x: nextX, y: nextY }];
        if (stroke.space && origP.rx !== undefined) {
          stroke.points[0].rx = (nextX - stroke.space.left) / Math.max(stroke.space.width, 1);
          stroke.points[0].ry = (nextY - stroke.space.top) / Math.max(stroke.space.height, 1);
        }
        return;
      }

      if (stroke.brush === 'airbrush') {
        stroke._cacheCanvas = null;
      }

      const snapPts = snapshot.points || snapshot;
      stroke.points = snapPts.map((origP) => {
        const nextX = anchorX + (origP.x - anchorX) * scaleX;
        const nextY = anchorY + (origP.y - anchorY) * scaleY;
        const pt = { x: nextX, y: nextY };
        if (stroke.space && origP.rx !== undefined) {
          pt.rx = (nextX - stroke.space.left) / Math.max(stroke.space.width, 1);
          pt.ry = (nextY - stroke.space.top) / Math.max(stroke.space.height, 1);
        }
        return pt;
      });
    });

    dirty = true;
    redraw();
    syncDomWidgets();
    updateSelectionBox();

    const now = performance.now();
    if (now - (lastResizeSyncTime || 0) > 28) {
      lastResizeSyncTime = now;
      const updated = strokes.filter((s) => selectedIds.has(s.id));
      if (updated.length) {
        const syncStrokes = updated.map((s) => {
          if (s.type === 'image' && s.src) {
            const { src, ...rest } = s;
            return rest;
          }
          return s;
        });
        realtimeSyncAdapter?.onStrokesUpdate?.(syncStrokes);
      }
    }
  }

  function onRotatePointerDown(e) {
    e.stopPropagation();
    e.preventDefault();
    interactionMode = 'rotate';
    isPointerDown = true;
    const box = getSelectionScreenBox();
    const worldBox = getSelectionWorldBounds();
    if (!box || !worldBox) return;

    rotateCenter = { x: worldBox.cx, y: worldBox.cy };
    const screenCenter = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    rotateStartAngle = Math.atan2(e.clientY - screenCenter.y, e.clientX - screenCenter.x);
    try {
      e.target?.setPointerCapture?.(e.pointerId);
    } catch (_) {}
  }

  function applyRotate(e) {
    const box = getSelectionScreenBox();
    if (!box) return;
    const screenCenter = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    const currentAngle = Math.atan2(e.clientY - screenCenter.y, e.clientX - screenCenter.x);
    const dAngle = currentAngle - rotateStartAngle;
    rotateStartAngle = currentAngle;

    const cos = Math.cos(dAngle);
    const sin = Math.sin(dAngle);

    selectedIds.forEach((id) => {
      const s = strokes.find((item) => item.id === id);
      if (!s || !s.points) return;
      s.rotation = Math.round(((s.rotation || 0) + (dAngle * 180 / Math.PI)) % 360);
      s.points.forEach((p) => {
        const rx = p.x - rotateCenter.x;
        const ry = p.y - rotateCenter.y;
        p.x = rotateCenter.x + rx * cos - ry * sin;
        p.y = rotateCenter.y + rx * sin + ry * cos;
        if (s.space && p.rx !== undefined) {
          p.rx = (p.x - s.space.left) / Math.max(s.space.width, 1);
          p.ry = (p.y - s.space.top) / Math.max(s.space.height, 1);
        }
      });
      if (s.brush === 'airbrush') {
        s._cacheCanvas = null;
      }
    });

    dirty = true;
    redraw();
    syncDomWidgets();
    updateSelectionBox();
  }

  function flipSelected(direction = 'h') {
    const wBox = getSelectionWorldBounds();
    if (!wBox) return;
    const cx = wBox.cx;
    const cy = wBox.cy;

    selectedIds.forEach((id) => {
      const s = strokes.find((item) => item.id === id);
      if (!s || !s.points) return;
      s.points.forEach((p) => {
        if (direction === 'h') p.x = 2 * cx - p.x;
        else p.y = 2 * cy - p.y;
        if (s.space && p.rx !== undefined) {
          p.rx = (p.x - s.space.left) / Math.max(s.space.width, 1);
          p.ry = (p.y - s.space.top) / Math.max(s.space.height, 1);
        }
      });
      if (s.shape === 'brackets') {
        if (direction === 'h') s.flipH = !s.flipH;
        else s.flipV = !s.flipV;
      }
      if (s.brush === 'airbrush') {
        s._cacheCanvas = null;
      }
    });

    dirty = true;
    saveLocal();
    redraw();
    updateSelectionBox();
  }

  function groupSelected() {
    const groupId = generateId('grp');
    selectedIds.forEach((id) => {
      const s = strokes.find((item) => item.id === id);
      if (s) s.groupId = groupId;
    });
  }

  // --- Sticky Note Creation ---

  function createStickyNoteAt(e) {
    const space = getActiveTaskContentRect();
    const p1 = pointForEvent(e, space);
    const noteW = 180 / viewScale;
    const noteH = 140 / viewScale;
    const p2 = {
      x: p1.x + noteW,
      y: p1.y + noteH,
      rx: space ? (p1.x + noteW - space.left) / space.width : 0,
      ry: space ? (p1.y + noteH - space.top) / space.height : 0,
    };

    const newNote = {
      id: generateId('note'),
      page_id: currentPageId,
      type: 'note',
      text: '',
      colorTheme: 'yellow',
      points: [p1, p2],
      space: space ? { left: space.left, top: space.top, width: space.width, height: space.height, task_id: space.task_id } : null,
    };

    strokes.push(newNote);
    selectedIds.clear();
    selectedIds.add(newNote.id);
    setTool('select');
    dirty = true;
    saveLocal();
    redraw();
    updateSelectionBox();
    scheduleSave();
    realtimeSyncAdapter?.onStrokeCommit?.(newNote);

    setTimeout(() => {
      const ta = objectLayer.querySelector(`[data-obj-id="${newNote.id}"] textarea`);
      if (ta) ta.focus();
    }, 50);
  }

  // --- Image Compression & Insertion ---

  function compressAndInsertImage(file, clientX, clientY) {
    if (!file || !file.type.startsWith('image/')) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const img = new Image();
      img.onload = () => {
        const maxDim = 1200;
        let w = img.width;
        let h = img.height;
        if (w > maxDim || h > maxDim) {
          if (w > h) { h = Math.round((h * maxDim) / w); w = maxDim; }
          else { w = Math.round((w * maxDim) / h); h = maxDim; }
        }

        const offCanvas = document.createElement('canvas');
        offCanvas.width = w;
        offCanvas.height = h;
        const oCtx = offCanvas.getContext('2d');
        oCtx.drawImage(img, 0, 0, w, h);
        const mime = 'image/jpeg';
        const dataUrl = offCanvas.toDataURL(mime, 0.82);

        const space = (embeddedTarget || document.getElementById('canvas-window')) ? null : getActiveTaskContentRect();
        const origin = canvasOrigin();
        const posX = clientX !== undefined ? clientX : (origin.left + window.innerWidth / 3);
        const posY = clientY !== undefined ? clientY : (origin.top + window.innerHeight / 3);

        const clickEv = { pageX: posX + window.scrollX, pageY: posY + window.scrollY };
        const p1 = pointForEvent(clickEv, space);

        const targetDisplayW = Math.min(360, w);
        const targetDisplayH = Math.round((targetDisplayW * h) / w);
        const worldW = targetDisplayW / viewScale;
        const worldH = targetDisplayH / viewScale;

        const p2 = {
          x: p1.x + worldW,
          y: p1.y + worldH,
          rx: space ? (p1.x + worldW - space.left) / space.width : 0,
          ry: space ? (p1.y + worldH - space.top) / space.height : 0,
        };

        const newImgStroke = {
          id: generateId('img'),
          page_id: currentPageId,
          type: 'image',
          src: dataUrl,
          points: [p1, p2],
          space: space ? { left: space.left, top: space.top, width: space.width, height: space.height, task_id: space.task_id } : null,
        };

        strokes.push(newImgStroke);
        selectedIds.clear();
        selectedIds.add(newImgStroke.id);
        setTool('select');
        dirty = true;
        saveLocal();
        redraw();
        updateSelectionBox();
        scheduleSave();
        realtimeSyncAdapter?.onStrokeCommit?.(newImgStroke);
      };
      img.src = ev.target.result;
    };
    reader.readAsDataURL(file);
  }

  function insertPdfPlaceholder(file) {
    const space = getActiveTaskContentRect();
    const origin = canvasOrigin();
    const p1 = pointForEvent({ pageX: origin.left + 200, pageY: origin.top + 200 }, space);
    const pdfCard = {
      id: generateId('pdf'),
      page_id: currentPageId,
      type: 'widget',
      widgetType: 'pdf',
      points: [p1, { x: p1.x + 280, y: p1.y + 180 }],
      data: { name: file.name, pagesCount: 1 },
      space: space ? { left: space.left, top: space.top, width: space.width, height: space.height, task_id: space.task_id } : null,
    };
    strokes.push(pdfCard);
    setTool('select');
    redraw();
    realtimeSyncAdapter?.onStrokeCommit?.(pdfCard);
  }

  // --- Text Editor ---

  function finishTextEntry(shouldCommit) {
    const input = textEditor;
    if (!input) return;
    textEditor = null;
    const text = String(input.value || '').trim();
    const draft = input._canvasTextDraft;
    input.remove();
    if (!shouldCommit || !text || !draft) return;

    if (draft.existingId) {
      const existing = strokes.find((s) => s.id === draft.existingId);
      if (existing) {
        existing.text = text;
        dirty = true;
        saveLocal();
        redraw();
        updateSelectionBox();
        scheduleSave();
        return;
      }
    }

    const newText = {
      id: generateId('txt'),
      page_id: currentPageId,
      type: 'text',
      text,
      color: draft.color,
      fontSize: draft.fontSize,
      space: draft.space,
      points: [draft.point],
    };

    strokes.push(newText);
    selectedIds.clear();
    selectedIds.add(newText.id);
    setTool('select');
    redoStack = [];
    dirty = true;
    saveLocal();
    redraw();
    updateSelectionBox();
    scheduleSave();
    realtimeSyncAdapter?.onStrokeCommit?.(newText);
  }

  function beginTextEntry(e, space, point, existingTextObj) {
    finishTextEntry(true);
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'boo-canvas-text-editor';
    input.setAttribute('aria-label', 'Текстовый блок на доске');
    input.placeholder = 'Введите текст и нажмите Enter';
    if (existingTextObj) {
      input.value = existingTextObj.text || '';
    }
    input._canvasTextDraft = {
      point,
      color: existingTextObj?.color || penColor,
      fontSize: existingTextObj?.fontSize || Math.max(16, penSize * 5),
      space: space ? { left: space.left, top: space.top, width: space.width, height: space.height, task_id: space.task_id } : null,
      existingId: existingTextObj?.id || null,
    };
    input.style.left = `${Math.max(8, Math.min(e.clientX, window.innerWidth - 240))}px`;
    input.style.top = `${Math.max(8, Math.min(e.clientY, window.innerHeight - 48))}px`;
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        event.stopPropagation();
        finishTextEntry(true);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        finishTextEntry(false);
      }
    });
    input.addEventListener('blur', () => finishTextEntry(true), { once: true });
    document.body.appendChild(input);
    textEditor = input;
    input.focus();
    if (input.select) input.select();
  }

  // --- Operations (Duplicate, Order, Delete) ---

  function copySelected() {
    clipboardObjects = strokes
      .filter((s) => selectedIds.has(s.id))
      .map((s) => JSON.parse(JSON.stringify(s)));
  }

  function cutSelected() {
    copySelected();
    deleteSelected();
  }

  function pasteClipboardObjects() {
    if (!clipboardObjects || clipboardObjects.length === 0) return;
    const newSelected = new Set();
    const offset = 24 / viewScale;

    clipboardObjects.forEach((orig) => {
      const clone = JSON.parse(JSON.stringify(orig));
      clone.id = generateId(clone.type || 'obj');
      if (clone.points) {
        clone.points.forEach((p) => {
          p.x += offset;
          p.y += offset;
          if (clone.space) {
            p.rx = (p.x - clone.space.left) / clone.space.width;
            p.ry = (p.y - clone.space.top) / clone.space.height;
          }
        });
      }
      clone.page_id = currentPageId;
      strokes.push(clone);
      newSelected.add(clone.id);
      realtimeSyncAdapter?.onStrokeCommit?.(clone);
    });

    selectedIds = newSelected;
    setTool('select');
    dirty = true;
    saveLocal();
    redraw();
    updateSelectionBox();
    scheduleSave();
  }

  function duplicateSelected() {
    copySelected();
    pasteClipboardObjects();
  }

  function deleteSelected() {
    if (selectedIds.size === 0) return;
    const deletedIds = Array.from(selectedIds);
    strokes = strokes.filter((s) => !selectedIds.has(s.id));
    getActivePage().strokes = strokes;
    selectedIds.clear();
    dirty = true;
    saveLocal();
    redraw();
    syncDomWidgets();
    updateSelectionBox();
    scheduleSave();
    realtimeSyncAdapter?.onStrokesDelete?.(deletedIds);
  }

  function deleteSingleStroke(id) {
    strokes = strokes.filter((s) => s.id !== id);
    getActivePage().strokes = strokes;
    selectedIds.delete(id);
    dirty = true;
    saveLocal();
    redraw();
    syncDomWidgets();
    updateSelectionBox();
    scheduleSave();
    realtimeSyncAdapter?.onStrokesDelete?.([id]);
  }

  function bringForward() {
    if (selectedIds.size === 0) return;
    for (let i = strokes.length - 2; i >= 0; i--) {
      if (selectedIds.has(strokes[i].id) && !selectedIds.has(strokes[i + 1].id)) {
        const temp = strokes[i];
        strokes[i] = strokes[i + 1];
        strokes[i + 1] = temp;
      }
    }
    getActivePage().strokes = strokes;
    dirty = true;
    saveLocal();
    redraw();
    syncDomWidgets();
    updateSelectionBox();
    scheduleSave();
  }

  function sendBackward() {
    if (selectedIds.size === 0) return;
    for (let i = 1; i < strokes.length; i++) {
      if (selectedIds.has(strokes[i].id) && !selectedIds.has(strokes[i - 1].id)) {
        const temp = strokes[i];
        strokes[i] = strokes[i - 1];
        strokes[i - 1] = temp;
      }
    }
    getActivePage().strokes = strokes;
    dirty = true;
    saveLocal();
    redraw();
    syncDomWidgets();
    updateSelectionBox();
    scheduleSave();
  }

  function bringToFront() {
    if (selectedIds.size === 0) return;
    const moving = [];
    const remaining = [];
    strokes.forEach((s) => {
      if (selectedIds.has(s.id)) moving.push(s);
      else remaining.push(s);
    });
    strokes = [...remaining, ...moving];
    getActivePage().strokes = strokes;
    dirty = true;
    saveLocal();
    redraw();
    syncDomWidgets();
    updateSelectionBox();
    scheduleSave();
  }

  function sendToBack() {
    if (selectedIds.size === 0) return;
    const moving = [];
    const remaining = [];
    strokes.forEach((s) => {
      if (selectedIds.has(s.id)) moving.push(s);
      else remaining.push(s);
    });
    strokes = [...moving, ...remaining];
    getActivePage().strokes = strokes;
    dirty = true;
    saveLocal();
    redraw();
    syncDomWidgets();
    updateSelectionBox();
    scheduleSave();
  }

  function undo() {
    if (!strokes.length) return;
    const popped = strokes.pop();
    redoStack.push(popped);
    selectedIds.clear();
    dirty = true;
    redraw();
    updateSelectionBox();
    saveLocal();
    scheduleSave();
    if (popped && popped.id) {
      realtimeSyncAdapter?.onStrokesDelete?.([popped.id]);
    }
  }

  function redo() {
    if (!redoStack.length) return;
    const restored = redoStack.pop();
    strokes.push(restored);
    dirty = true;
    redraw();
    updateSelectionBox();
    saveLocal();
    scheduleSave();
    if (restored) {
      realtimeSyncAdapter?.onStrokeCommit?.(restored);
    }
  }

  function executeClearAll() {
    strokes.length = 0;
    redoStack = [];
    selectedIds.clear();
    dirty = true;
    redraw();
    updateSelectionBox();
    saveLocal();
    scheduleSave();
    updateSaveStatus('unsaved');
    realtimeSyncAdapter?.onBoardClear?.(currentPageId);
  }

  // --- Persistence Engine ---

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    updateSaveStatus('unsaved');
    saveTimer = setTimeout(() => saveToServer(), 3000);
  }

  async function saveToServer() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    if (!taskId) return false;
    if (pendingSavePromise) await waitPendingSave();
    if (!dirty && strokes.length === 0) return true;

    updateSaveStatus('saving');

    const cleanStrokesForSave = (arr) => (arr || []).map((s) => {
      const copy = { ...s };
      delete copy._cacheCanvas;
      delete copy._cacheOrigin;
      return copy;
    });

    const body = {
      task_id: taskId,
      context_type: contextType,
      context_id: contextId,
      strokes: {
        version: 2,
        pages: pages.map((p) => ({ ...p, strokes: cleanStrokesForSave(p.strokes) })),
        currentPageId,
        strokes: cleanStrokesForSave(strokes), // legacy compatibility
      },
    };

    pendingSavePromise = (async () => {
      try {
        const response = await fetch('/api/canvas/save', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error('Не удалось сохранить холст');
        dirty = false;
        updateSaveStatus('saved');
        if (strokes && strokes.length > 0 && typeof window.triggerAchievement === 'function') {
          window.triggerAchievement('canvas_save');
        }
        loadState.lastAt = 0;
        loadState.lastData = null;
        saveLocal();
        updateBadge();
        return true;
      } catch (e) {
        console.warn('Canvas save failed:', e);
        updateSaveStatus('unsaved');
        return false;
      } finally {
        pendingSavePromise = null;
      }
    })();
    return await pendingSavePromise;
  }

  async function waitPendingSave() {
    if (pendingSavePromise) {
      try { await pendingSavePromise; } catch (_) {}
    }
  }

  async function fetchCanvasState(force = false) {
    const key = contextKey();
    if (!key) return null;

    const now = Date.now();
    if (loadState.promise && loadState.key === key) return loadState.promise;
    if (!force && loadState.key === key && loadState.lastData && now - loadState.lastAt < LOAD_CACHE_TTL_MS) {
      return loadState.lastData;
    }

    const params = new URLSearchParams({ task_id: taskId, context_type: contextType });
    if (contextId) params.set('context_id', contextId);

    loadState.key = key;
    loadState.promise = fetch('/api/canvas/load?' + params.toString(), {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then((res) => res.json())
      .then((data) => {
        loadState.lastAt = Date.now();
        loadState.lastData = data;
        return data;
      })
      .finally(() => {
        loadState.promise = null;
      });

    return loadState.promise;
  }

  function scheduleExistingDrawingCheck() {
    if (checkTimer) clearTimeout(checkTimer);
    checkTimer = setTimeout(() => {
      checkTimer = null;
      checkExistingDrawing();
    }, LOAD_DEBOUNCE_MS);
  }

  async function loadFromServer() {
    const isLessonRoom = contextType === 'lesson' || contextType === 'lesson_task' || Boolean(embeddedTarget) || Boolean(document.getElementById('canvas-window'));
    if (isLessonRoom) return;

    if (!taskId) {
      pages = [{ id: 'page_1', title: 'Страница 1', background: 'dots', strokes: [] }];
      currentPageId = 'page_1';
      syncPageStrokes();
      redraw();
      updateSelectionBox();
      return;
    }

    const localData = loadLocal();
    if (localData) {
      unpackLoadedData(localData);
      redraw();
      updateSelectionBox();
      updateBadge();
    }

    await waitPendingSave();
    try {
      const data = await fetchCanvasState(false);
      if (data.success && data.strokes) {
        const parsed = typeof data.strokes === 'string' ? JSON.parse(data.strokes) : data.strokes;
        unpackLoadedData(parsed);
      }
    } catch (_) {}

    redoStack = [];
    selectedIds.clear();
    dirty = false;
    saveLocal();
    renderPageTabs();
    applyCanvasBackground(getActivePage().background || 'dots');
    redraw();
    updateSelectionBox();
    updateBadge();
  }

  function unpackLoadedData(parsed) {
    const cleanStrokes = (list) => {
      if (!Array.isArray(list)) return;
      list.forEach((s) => {
        if (s && s._cacheCanvas && !(s._cacheCanvas instanceof HTMLCanvasElement)) {
          delete s._cacheCanvas;
          delete s._cacheOrigin;
        }
      });
    };

    if (parsed && parsed.version === 2 && Array.isArray(parsed.pages)) {
      pages = parsed.pages;
      currentPageId = parsed.currentPageId || pages[0].id;
      pages.forEach((p) => cleanStrokes(p.strokes));
      syncPageStrokes();
    } else if (Array.isArray(parsed)) {
      // Legacy flat strokes array
      strokes = parsed.map((s) => ({ ...s, id: s.id || generateId(s.type) }));
      cleanStrokes(strokes);
      pages = [{ id: 'page_1', title: 'Страница 1', background: 'dots', strokes }];
      currentPageId = 'page_1';
    }
  }

  function updateBadge() {
    if (fabBadge) {
      fabBadge.style.display = strokes.length > 0 ? '' : 'none';
    }
  }

  // --- Zoom & Pan Logic ---

  function zoomBy(factor) {
    const origin = canvasOrigin();
    const w = canvas.width / Math.max(dpr, 1);
    const h = canvas.height / Math.max(dpr, 1);
    zoomAtPoint(origin.left + w / 2, origin.top + h / 2, factor);
  }

  function zoomAtPoint(clientX, clientY, factor) {
    const origin = canvasOrigin();
    const width = canvas.width / Math.max(dpr, 1);
    const height = canvas.height / Math.max(dpr, 1);
    const mouseX = clientX - origin.left;
    const mouseY = clientY - origin.top;

    const prevScale = viewScale;
    const nextScale = Math.max(0.3, Math.min(4.0, viewScale * factor));
    if (Math.abs(nextScale - prevScale) < 0.001) return;

    const worldX = (mouseX - width / 2 - viewOffsetX) / prevScale + width / 2;
    const worldY = (mouseY - height / 2 - viewOffsetY) / prevScale + height / 2;

    viewScale = nextScale;
    viewOffsetX = mouseX - width / 2 - (worldX - width / 2) * nextScale;
    viewOffsetY = mouseY - height / 2 - (worldY - height / 2) * nextScale;

    updateZoomBadge();
    redraw();
    updateSelectionBox();
    realtimeSyncAdapter?.onCameraChange?.(viewOffsetX, viewOffsetY, viewScale);
  }

  function resetZoom() {
    viewScale = 1;
    viewOffsetX = 0;
    viewOffsetY = 0;
    updateZoomBadge();
    redraw();
    updateSelectionBox();
    realtimeSyncAdapter?.onCameraChange?.(viewOffsetX, viewOffsetY, viewScale);
  }

  function updateZoomBadge() {
    const zoomLabel = document.getElementById('boo-tb-zoom-label');
    if (zoomLabel) zoomLabel.textContent = `${Math.round(viewScale * 100)}%`;
  }

  function onWheel(e) {
    if (!isOpen) return;
    if (e.shiftKey) {
      e.preventDefault();
      viewOffsetX -= e.deltaY;
      redraw();
      updateSelectionBox();
      realtimeSyncAdapter?.onCameraChange?.(viewOffsetX, viewOffsetY, viewScale);
      return;
    }
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.10 : 1 / 1.10;
    zoomAtPoint(e.clientX, e.clientY, zoomFactor);
  }

  function canvasOrigin() {
    if (!overlay) return { left: 0, top: 0 };
    const rect = overlay.getBoundingClientRect();
    return { left: rect.left + window.scrollX, top: rect.top + window.scrollY };
  }

  function resizeCanvas() {
    if (!canvas) return;
    if (embeddedTarget && !embeddedTarget.isConnected) embeddedTarget = null;
    if (embeddedTarget) {
      const width = Math.max(1, embeddedTarget.clientWidth);
      const height = Math.max(1, embeddedTarget.clientHeight);
      dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      if (laserCanvas) {
        if (laserCanvas.parentElement && laserCanvas.parentElement.id === 'lesson-os-top-laser-layer') {
          const lParent = laserCanvas.parentElement;
          laserCanvas.width = Math.floor(lParent.clientWidth * dpr);
          laserCanvas.height = Math.floor(lParent.clientHeight * dpr);
          laserCanvas.style.width = `${lParent.clientWidth}px`;
          laserCanvas.style.height = `${lParent.clientHeight}px`;
        } else {
          laserCanvas.width = canvas.width;
          laserCanvas.height = canvas.height;
          laserCanvas.style.width = canvas.style.width;
          laserCanvas.style.height = canvas.style.height;
        }
      }
      overlay.style.width = `${width}px`;
      overlay.style.height = `${height}px`;
      redraw();
      updateSelectionBox();
      drawLaserTop();
      return;
    }
    const doc = document.documentElement;
    const body = document.body;
    const width = Math.max(
      doc ? doc.scrollWidth : 0, doc ? doc.clientWidth : 0,
      body ? body.scrollWidth : 0, body ? body.clientWidth : 0,
      window.innerWidth || 0
    );
    const height = Math.max(
      doc ? doc.scrollHeight : 0, doc ? doc.clientHeight : 0,
      body ? body.scrollHeight : 0, body ? body.clientHeight : 0,
      window.innerHeight || 0
    );
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    if (laserCanvas) {
      laserCanvas.width = canvas.width;
      laserCanvas.height = canvas.height;
      laserCanvas.style.width = canvas.style.width;
      laserCanvas.style.height = canvas.style.height;
    }
    if (overlay) {
      overlay.style.width = `${width}px`;
      overlay.style.height = `${height}px`;
    }
    redraw();
    updateSelectionBox();
    drawLaserTop();
  }

  function pointForEvent(e, space) {
    const origin = canvasOrigin();
    const width = canvas.width / Math.max(dpr, 1);
    const height = canvas.height / Math.max(dpr, 1);
    const pageX = e.pageX !== undefined ? e.pageX : e.clientX + window.scrollX;
    const pageY = e.pageY !== undefined ? e.pageY : e.clientY + window.scrollY;
    const displayedX = pageX - origin.left;
    const displayedY = pageY - origin.top;
    if (!space) {
      const x = (displayedX - width / 2 - viewOffsetX) / viewScale + width / 2;
      const y = (displayedY - height / 2 - viewOffsetY) / viewScale + height / 2;
      return { x, y };
    }
    const x = origin.left + (displayedX - width / 2 - viewOffsetX) / viewScale + width / 2;
    const y = origin.top + (displayedY - height / 2 - viewOffsetY) / viewScale + height / 2;
    const rx = (x - space.left) / Math.max(space.width, 1);
    const ry = (y - space.top) / Math.max(space.height, 1);
    return { x, y, rx, ry };
  }

  function resolvePointForRender(p, stroke, activeRect) {
    if (!p) return { x: 0, y: 0 };
    const hasRelative = Number.isFinite(Number(p.rx)) && Number.isFinite(Number(p.ry));
    if (hasRelative) {
      if (activeRect && (!stroke.space || !stroke.space.task_id || Number(stroke.space.task_id) === Number(activeRect.task_id))) {
        return {
          x: activeRect.left + Number(p.rx) * activeRect.width,
          y: activeRect.top + Number(p.ry) * activeRect.height,
        };
      }
      if (stroke.space) {
        return {
          x: Number(stroke.space.left || 0) + Number(p.rx) * Number(stroke.space.width || 1),
          y: Number(stroke.space.top || 0) + Number(p.ry) * Number(stroke.space.height || 1),
        };
      }
    }
    return {
      x: Number.isFinite(Number(p.x)) ? Number(p.x) : 0,
      y: Number.isFinite(Number(p.y)) ? Number(p.y) : 0,
    };
  }

  function pointToScreen(worldPoint, stroke, activeRect) {
    const origin = canvasOrigin();
    const width = canvas.width / Math.max(dpr, 1);
    const height = canvas.height / Math.max(dpr, 1);
    const mapped = resolvePointForRender(worldPoint, stroke, activeRect);
    const localX = (stroke && stroke.space) ? (mapped.x - origin.left) : mapped.x;
    const localY = (stroke && stroke.space) ? (mapped.y - origin.top) : mapped.y;
    return {
      x: width / 2 + (localX - width / 2) * viewScale + viewOffsetX,
      y: height / 2 + (localY - height / 2) * viewScale + viewOffsetY,
    };
  }

  function getActiveTaskContentRect() {
    if (embeddedTarget) {
      const rect = embeddedTarget.getBoundingClientRect();
      return {
        left: rect.left + window.scrollX,
        top: rect.top + window.scrollY,
        width: Math.max(rect.width, 1),
        height: Math.max(rect.height, 1),
        task_id: document.querySelector('.tw-shell')?.dataset.assignmentTaskId || taskId,
      };
    }
    let el = null;
    const workspaceShell = document.querySelector('.tw-shell');
    if (workspaceShell && workspaceShell.dataset) {
      el = document.querySelector('.tw-task-panel .tw-task-content');
      if (el && el.getBoundingClientRect) {
        const rect = el.getBoundingClientRect();
        return {
          left: rect.left + window.scrollX,
          top: rect.top + window.scrollY,
          width: Math.max(rect.width, 1),
          height: Math.max(rect.height, 1),
          task_id: workspaceShell.dataset.assignmentTaskId || taskId,
        };
      }
    }
    const cardId = document.body?.dataset?.canvasTaskCardId;
    if (cardId) {
      const card = document.getElementById(cardId);
      if (card) el = card.querySelector('.exec-unlocked > .task-content, .task-content-grade');
    }
    if (!el) el = document.querySelector('.task-card.task-panel-active .exec-unlocked > .task-content');
    if (!el) el = document.querySelector('.task-card-grade.task-panel-active .task-content-grade');
    if (!el) el = document.querySelector('.task-card .task-content, .task-card-grade .task-content-grade');
    if (!el) el = document.querySelector('.tw-task-content');
    if (!el || !el.getBoundingClientRect) return null;
    const rect = el.getBoundingClientRect();
    return {
      left: rect.left + window.scrollX,
      top: rect.top + window.scrollY,
      width: Math.max(rect.width, 1),
      height: Math.max(rect.height, 1),
      task_id: taskId || null,
    };
  }

  // --- Keyboard Shortcuts & Tool Selection ---

  function setTool(t) {
    if (textEditor && t !== 'text') finishTextEntry(true);
    if (ALL_SHAPE_IDS.includes(t)) {
      tool = 'shape';
      currentShape = t;
      updateShapeIcon();
    } else {
      tool = t;
    }
    if (overlay) overlay.dataset.tool = tool;
    if (objectLayer) {
      objectLayer.style.pointerEvents = (tool === 'laser') ? 'none' : '';
    }
    const brushIds = ['pen', 'ballpoint', 'fountain_pen', 'pencil', 'brush', 'felt_tip', 'highlighter', 'neon', 'airbrush', 'dashed_pen'];
    if (brushIds.includes(t)) {
      currentBrush = t;
      updateBrushIcon();
    }
    if (tool !== 'select') {
      selectedIds.clear();
      updateSelectionBox();
    }
    if (tool !== 'laser') {
      toggleLaserMenu(false);
      lastLaserHover = null;
      laserTrail = [];
      if (laserCtx && laserCanvas) {
        laserCtx.setTransform(1, 0, 0, 1, 0, 0);
        laserCtx.clearRect(0, 0, laserCanvas.width, laserCanvas.height);
        laserCleared = true;
      }
    }
    const buttons = {
      select: 'boo-tb-select',
      pan: 'boo-tb-pan',
      pen: 'boo-tb-pen',
      shape: 'boo-tb-shape',
      eraser_stroke: 'boo-tb-eraser',
      eraser_object: 'boo-tb-eraser',
    };
    Object.entries(buttons).forEach(([name, id]) => {
      const button = document.getElementById(id);
      if (!button) return;
      const isShapeTool = (id === 'boo-tb-shape') && (tool === 'shape' || ALL_SHAPE_IDS.includes(t));
      const isEraserTool = (id === 'boo-tb-eraser') && (tool === 'eraser_stroke' || tool === 'eraser_object');
      const active = (name === tool) || (id === 'boo-tb-pen' && brushIds.includes(tool)) || isShapeTool || isEraserTool;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    if (brushMenu) {
      brushMenu.querySelectorAll('.tb-brush-opt').forEach((b) => {
        b.classList.toggle('active', b.dataset.brush === (currentBrush || tool));
      });
    }
    if (shapesMenu) {
      shapesMenu.querySelectorAll('.tb-shape-opt').forEach((b) => {
        b.classList.toggle('active', b.dataset.shape === currentShape);
      });
    }
    const moreToolIds = ['connector', 'note', 'text', 'laser', 'eyedropper'];
    const moreBtn = document.getElementById('boo-tb-more');
    if (moreBtn) {
      moreBtn.classList.toggle('active', moreToolIds.includes(tool));
    }
    updateMoreMenuUi();
    updateEraserUi();
    updateCursor();
  }

  function updateCursor() {
    if (!canvas) return;
    if (spaceKeyHeld || middlePanActive || tool === 'pan') {
      canvas.style.cursor = isPointerDown ? 'grabbing' : 'grab';
    } else if (tool === 'select') {
      canvas.style.cursor = 'default';
    } else if (tool === 'lasso') {
      canvas.style.cursor = 'crosshair';
    } else if (tool === 'eraser_stroke' || tool === 'eraser_object') {
      canvas.style.cursor = 'cell';
    } else if (tool === 'text') {
      canvas.style.cursor = 'text';
    } else if (tool === 'laser') {
      canvas.style.cursor = 'pointer';
    } else if (tool === 'eyedropper') {
      canvas.style.cursor = 'copy';
    } else {
      canvas.style.cursor = 'crosshair';
    }
  }

  function onKeyDown(e) {
    if (!isOpen) return;

    if (e.code === 'Space' && !e.repeat && !isTypingInInput(e.target)) {
      spaceKeyHeld = true;
      updateCursor();
      e.preventDefault();
      return;
    }

    if (e.key === 'Escape') {
      if (textEditor) { finishTextEntry(false); e.preventDefault(); return; }
      if (selectedIds.size > 0) { selectedIds.clear(); updateSelectionBox(); e.preventDefault(); return; }
      closeCatalogModal();
      closeExportModal();
      closeMathModal();
      toggleBrushMenu(false);
      toggleShapesMenu(false);
      toggleLaserMenu(false);
      toggleEraserMenu(false);
      toggleMoreMenu(false);
      togglePropPopover(false);
      toggleClearConfirm(false);
      toggleBgSelectorPopover(false);
      if (!embeddedTarget) close();
      return;
    }

    const isCtrl = e.ctrlKey || e.metaKey;
    const code = e.code;
    const key = (e.key || '').toLowerCase();

    // 1. Ctrl / Meta Key Combinations (support Russian and English keyboard layouts)
    if (isCtrl) {
      if (isTypingInInput(e.target)) return;

      // Ctrl+Z: Undo (excluding shift)
      if ((code === 'KeyZ' || key === 'z' || key === 'я') && !e.shiftKey) {
        undo();
        e.preventDefault();
        return;
      }

      // Ctrl+Y or Ctrl+Shift+Z: Redo
      if (code === 'KeyY' || key === 'y' || key === 'н' || ((code === 'KeyZ' || key === 'z' || key === 'я') && e.shiftKey)) {
        redo();
        e.preventDefault();
        return;
      }

      // Ctrl+C: Copy
      if (code === 'KeyC' || key === 'c' || key === 'с') {
        if (selectedIds.size > 0) {
          copySelected();
          e.preventDefault();
          return;
        }
      }

      // Ctrl+X: Cut
      if (code === 'KeyX' || key === 'x' || key === 'ч') {
        if (selectedIds.size > 0) {
          cutSelected();
          e.preventDefault();
          return;
        }
      }

      // Ctrl+V: Paste
      if (code === 'KeyV' || key === 'v' || key === 'м') {
        if (clipboardObjects && clipboardObjects.length > 0) {
          pasteClipboardObjects();
          e.preventDefault();
          return;
        }
        // If no internal canvas objects copied, allow browser paste event for external images
        return;
      }

      // Ctrl+D: Duplicate
      if (code === 'KeyD' || key === 'd' || key === 'в') {
        if (selectedIds.size > 0) {
          duplicateSelected();
          e.preventDefault();
          return;
        }
      }

      // Ctrl+A: Select All
      if (code === 'KeyA' || key === 'a' || key === 'ф') {
        if (strokes.length > 0) {
          selectedIds = new Set(strokes.map((s) => s.id));
          setTool('select');
          updateSelectionBox();
          e.preventDefault();
          return;
        }
      }

      // Do NOT fall through to single-letter tool selection while holding Ctrl!
      return;
    }

    // 2. Delete / Backspace
    if ((code === 'Delete' || code === 'Backspace' || key === 'delete' || key === 'backspace') && !isTypingInInput(e.target)) {
      if (selectedIds.size > 0) {
        deleteSelected();
        e.preventDefault();
        return;
      }
    }

    if (isTypingInInput(e.target)) return;

    // 3. Single-Key Tool Selection (support both physical code and Latin/Cyrillic characters)
    if (code === 'KeyV' || key === 'v' || key === 'м') { setTool('select'); e.preventDefault(); }
    else if (code === 'KeyH' || key === 'h' || key === 'р') { setTool('pan'); e.preventDefault(); }
    else if (code === 'KeyP' || key === 'p' || key === 'з' || code === 'KeyB' || key === 'b' || key === 'и') { setTool('pen'); e.preventDefault(); }
    else if (code === 'KeyM' || key === 'm' || key === 'ь') { setTool('highlighter'); e.preventDefault(); }
    else if (code === 'KeyR' || key === 'r' || key === 'к') { setTool(currentShape); e.preventDefault(); }
    else if (code === 'KeyS' || key === 's' || key === 'ы') { setTool('note'); e.preventDefault(); }
    else if (code === 'KeyT' || key === 't' || key === 'е') { setTool('text'); e.preventDefault(); }
    else if (code === 'KeyI' || key === 'i' || key === 'ш') { hiddenFileInput?.click(); e.preventDefault(); }
    else if (code === 'KeyE' || key === 'e' || key === 'у') {
      if (tool === 'eraser_stroke') {
        toggleEraserMenu();
      } else {
        setTool('eraser_stroke');
      }
      e.preventDefault();
    }
    else if (code === 'KeyL' || key === 'l' || key === 'д') { setTool('laser'); e.preventDefault(); }
    else if (code === 'BracketLeft' || key === '[' || key === 'х') {
      if (tool === 'eraser_stroke' || tool === 'eraser_object') {
        setEraserSize(Math.max(6, eraserSize - 4));
      } else {
        setPenSize(Math.max(1, penSize - 2));
      }
      e.preventDefault();
    }
    else if (code === 'BracketRight' || key === ']' || key === 'ъ') {
      if (tool === 'eraser_stroke' || tool === 'eraser_object') {
        setEraserSize(Math.min(100, eraserSize + 4));
      } else {
        setPenSize(Math.min(28, penSize + 2));
      }
      e.preventDefault();
    }
    else if (code === 'Digit0' || key === '0') { resetZoom(); e.preventDefault(); }
    else if (key === '+' || key === '=' || code === 'Equal') { zoomBy(1.2); e.preventDefault(); }
    else if (key === '-' || code === 'Minus') { zoomBy(1 / 1.2); e.preventDefault(); }
  }

  function onKeyUp(e) {
    if (e.code === 'Space') {
      spaceKeyHeld = false;
      updateCursor();
    }
  }

  function onGlobalPointerDown(e) {
    if (!isOpen && !embeddedTarget) return;
    if (e.target.closest('.boo-canvas-shapes-menu, .boo-canvas-brush-menu, .boo-canvas-laser-menu, .boo-canvas-eraser-menu, .boo-canvas-more-menu, .boo-canvas-props-popover, .boo-canvas-clear-confirm, .boo-canvas-toolbar, .boo-canvas-bg-selector, .boo-catalog-modal, .boo-export-modal, .boo-math-modal')) {
      return;
    }
    toggleBrushMenu(false);
    toggleShapesMenu(false);
    toggleLaserMenu(false);
    toggleEraserMenu(false);
    toggleMoreMenu(false);
    togglePropPopover(false);
    toggleClearConfirm(false);
  }

  function onPaste(e) {
    if (!isOpen || isTypingInInput(e.target)) return;

    if (e.clipboardData && e.clipboardData.items) {
      for (let i = 0; i < e.clipboardData.items.length; i++) {
        const item = e.clipboardData.items[i];
        if (item.type.indexOf('image') !== -1) {
          const file = item.getAsFile();
          if (file) {
            compressAndInsertImage(file);
            e.preventDefault();
            return;
          }
        }
      }
    }

    if (clipboardObjects && clipboardObjects.length > 0) {
      pasteClipboardObjects();
      e.preventDefault();
    }
  }

  function isTypingInInput(target) {
    if (!target) return false;
    const tag = target.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable;
  }

  // --- Toolbar Drag ---

  function onToolbarDragStart(e) {
    if (embeddedTarget) return;
    if (e.target.closest('.tb-btn, .tb-props-btn, input, button')) return;
    tbDragging = true;
    toolbar.classList.add('dragging');
    tbDragStart = { x: e.clientX, y: e.clientY, left: toolbar.offsetLeft, top: toolbar.offsetTop };
    toolbar.setPointerCapture(e.pointerId);

    const onMove = (ev) => {
      if (!tbDragging) return;
      const dx = ev.clientX - tbDragStart.x;
      const dy = ev.clientY - tbDragStart.y;
      toolbar.style.left = (tbDragStart.left + dx) + 'px';
      toolbar.style.top = (tbDragStart.top + dy) + 'px';
      toolbar.style.transform = 'none';
      if (shapesMenu) shapesMenu.style.left = `${toolbar.offsetLeft + toolbar.offsetWidth + 8}px`;
      if (propPopover) propPopover.style.left = `${toolbar.offsetLeft + toolbar.offsetWidth + 8}px`;
      if (clearConfirm) clearConfirm.style.left = `${toolbar.offsetLeft + toolbar.offsetWidth + 8}px`;
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

  // --- Open / Close Lifecycle ---

  async function open() {
    if (isOpen || !hasValidContext()) return;
    isOpen = true;
    if (typeof window.triggerAchievement === 'function') window.triggerAchievement('canvas_open');
    overlay.classList.add('active');
    resizeCanvas();
    toolbar.style.display = '';
    if (zoomIsland) zoomIsland.style.display = '';
    if (pagesBar) pagesBar.style.display = '';
    if (minimapEl) minimapEl.style.display = '';
    if (saveStatus) saveStatus.style.display = '';
    fab.style.display = 'none';
    window.dispatchEvent(new CustomEvent('boo-canvas:statechange', { detail: { open: true, embedded: Boolean(embeddedTarget) } }));
    await loadFromServer();
  }

  function close() {
    if (!isOpen) return;
    if (embeddedTarget || document.getElementById('canvas-window')) return;
    if (textEditor) finishTextEntry(true);
    if (dirty) saveToServer();
    isOpen = false;
    overlay.classList.remove('active');
    toolbar.style.display = 'none';
    if (zoomIsland) zoomIsland.style.display = 'none';
    if (pagesBar) pagesBar.style.display = 'none';
    if (minimapEl) minimapEl.style.display = 'none';
    if (saveStatus) saveStatus.style.display = 'none';
    toggleShapesMenu(false);
    togglePropPopover(false);
    toggleClearConfirm(false);
    toggleBgSelectorPopover(false);
    toggleEraserMenu(false);
    toggleMoreMenu(false);
    closeCatalogModal();
    closeExportModal();
    closeMathModal();
    fab.style.display = embeddedTarget ? 'none' : '';
    isPointerDown = false;
    currentStroke = null;
    selectedIds.clear();
    updateSelectionBox();
    syncFabVisibility();
    window.dispatchEvent(new CustomEvent('boo-canvas:statechange', { detail: { open: false, embedded: Boolean(embeddedTarget) } }));
  }

  function toggle() {
    if (!hasValidContext()) return;
    if (isOpen) close(); else open();
  }

  function openIn(target) {
    if (!target || typeof target.appendChild !== 'function' || !hasValidContext()) return false;
    init();
    if (embeddedTarget && embeddedTarget !== target) {
      embeddedTarget.classList.remove('boo-canvas-embedded-host');
    }
    embeddedTarget = target;
    embeddedTarget.classList.add('boo-canvas-embedded-host');
    embeddedTarget.appendChild(overlay);
    const topLaserLayer = document.getElementById('lesson-os-top-laser-layer');
    if (topLaserLayer && laserCanvas && laserCanvas.parentElement !== topLaserLayer) {
      topLaserLayer.appendChild(laserCanvas);
      laserCanvas.style.position = 'absolute';
      laserCanvas.style.inset = '0';
      laserCanvas.style.width = '100%';
      laserCanvas.style.height = '100%';
      laserCanvas.style.pointerEvents = 'none';
      laserCanvas.style.zIndex = '999999';
    }
    embeddedTarget.appendChild(toolbar);
    if (zoomIsland) embeddedTarget.appendChild(zoomIsland);
    if (pagesBar) embeddedTarget.appendChild(pagesBar);
    if (minimapEl) embeddedTarget.appendChild(minimapEl);
    if (saveStatus) embeddedTarget.appendChild(saveStatus);

    overlay.classList.add('is-embedded');
    toolbar.classList.add('is-embedded');
    zoomIsland?.classList.add('is-embedded');
    pagesBar?.classList.add('is-embedded');
    minimapEl?.classList.add('is-embedded');
    saveStatus?.classList.add('is-embedded');

    resizeCanvas();
    if (!isOpen) open();
    return true;
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
      if (!embeddedTarget && !document.getElementById('canvas-window')) {
        close();
        strokes = [];
        redoStack = [];
        redraw();
        updateSelectionBox();
        updateBadge();
        return;
      }
    }
    const isLessonRoom = contextType === 'lesson' || contextType === 'lesson_task' || Boolean(embeddedTarget) || Boolean(document.getElementById('canvas-window'));
    if (!isLessonRoom) {
      if (changed && isOpen) loadFromServer();
      if (changed && !isOpen) {
        scheduleExistingDrawingCheck();
      }
    }
  }

  function hasValidContext() {
    if (contextType === 'lesson' || contextType === 'lesson_task' || embeddedTarget || document.getElementById('canvas-window')) {
      return Boolean(Number.isFinite(contextId) && contextId > 0) || Boolean(Number.isFinite(taskId) && taskId > 0) || Boolean(embeddedTarget) || Boolean(document.getElementById('canvas-window'));
    }
    return Number.isFinite(taskId) && taskId > 0;
  }

  function syncFabVisibility() {
    if (!fab) return;
    fab.style.display = hasValidContext() && !embeddedTarget ? '' : 'none';
  }

  async function checkExistingDrawing() {
    if (!taskId) { updateBadge(); return; }
    await waitPendingSave();
    try {
      const data = await fetchCanvasState(false);
      if (data.success && data.exists) {
        const parsed = typeof data.strokes === 'string' ? JSON.parse(data.strokes) : data.strokes;
        unpackLoadedData(parsed);
      } else {
        const localData = loadLocal();
        if (localData) unpackLoadedData(localData);
      }
      saveLocal();
      updateBadge();
    } catch (_) {}
  }

  function setPenSize(s) {
    penSize = Math.max(1, Math.min(28, s));
    if (selectedIds.size > 0) {
      strokes.forEach((stroke) => {
        if (selectedIds.has(stroke.id)) {
          if (stroke.type === 'text' || stroke.type === 'math') {
            stroke.fontSize = Math.max(12, Math.min(96, s * 4));
          } else {
            stroke.width = s;
          }
        }
      });
      dirty = true;
      saveLocal();
      redraw();
      updateSelectionBox();
      scheduleSave();
    }
    const sizeText = document.getElementById('boo-props-size-text');
    if (sizeText) sizeText.textContent = `${penSize}px`;
    const slider = document.getElementById('boo-props-slider');
    if (slider) slider.value = String(penSize);
    if (propPopover) {
      propPopover.querySelectorAll('.boo-props-size-btn').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.size) === penSize);
      });
    }
    const badge = toolbar?.querySelector('.tb-props-size-badge');
    if (badge) badge.textContent = String(penSize);
    const brushSizeText = document.getElementById('boo-brush-size-text');
    if (brushSizeText) brushSizeText.textContent = `${penSize}px`;
    const brushSlider = document.getElementById('boo-brush-slider');
    if (brushSlider) brushSlider.value = String(penSize);
    if (brushMenu) {
      brushMenu.querySelectorAll('.boo-brush-size-btn').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.size) === penSize);
      });
    }
    const shapeSizeText = document.getElementById('boo-shape-size-text');
    if (shapeSizeText) shapeSizeText.textContent = `${penSize}px`;
    if (shapesMenu) {
      shapesMenu.querySelectorAll('.boo-brush-size-btn').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.size) === penSize);
      });
    }
  }

  function setPenColor(c) {
    penColor = c;
    highlighterColor = c;
    if (tool === 'laser') laserColor = c;
    if (selectedIds.size > 0) {
      strokes.forEach((s) => {
        if (selectedIds.has(s.id)) {
          if (s.type === 'note') s.colorTheme = c;
          else s.color = c;
        }
      });
      dirty = true;
      saveLocal();
      redraw();
      updateSelectionBox();
      scheduleSave();
    } else {
      if (['eraser_stroke', 'eraser_object', 'pan'].includes(tool)) {
        setTool('pen');
      }
    }
    const swatch = toolbar?.querySelector('.tb-props-swatch');
    if (swatch) swatch.style.backgroundColor = c;
    if (propPopover) {
      propPopover.querySelectorAll('.boo-props-color-swatch').forEach((s) => {
        s.classList.toggle('active', s.dataset.color?.toLowerCase() === c.toLowerCase());
      });
      const nativeInput = propPopover.querySelector('.boo-props-color-native-input');
      if (nativeInput) nativeInput.value = c;
    }
    if (brushMenu) {
      brushMenu.querySelectorAll('.boo-brush-color-swatch').forEach((s) => {
        s.classList.toggle('active', s.dataset.color?.toLowerCase() === c.toLowerCase());
      });
      const brushNativeInput = brushMenu.querySelector('.boo-brush-native-color');
      if (brushNativeInput) brushNativeInput.value = c;
    }
    if (shapesMenu) {
      shapesMenu.querySelectorAll('.boo-brush-color-swatch').forEach((s) => {
        s.classList.toggle('active', s.dataset.color?.toLowerCase() === c.toLowerCase());
      });
      const shapeNativeInput = shapesMenu.querySelector('.boo-brush-native-color');
      if (shapeNativeInput) shapeNativeInput.value = c;
    }
  }

  function setAirbrushDensity(d) {
    airbrushDensity = Math.max(0.15, Math.min(1.0, d));
    if (selectedIds.size > 0) {
      strokes.forEach((s) => {
        if (selectedIds.has(s.id) && s.brush === 'airbrush') {
          s.density = airbrushDensity;
        }
      });
      dirty = true;
      saveLocal();
      redraw();
      scheduleSave();
    }
    const txt = document.getElementById('boo-airbrush-density-text');
    if (txt) txt.textContent = `${Math.round(airbrushDensity * 100)}%`;
    const slider = document.getElementById('boo-airbrush-density-slider');
    if (slider) slider.value = String(Math.round(airbrushDensity * 100));
    if (brushMenu) {
      brushMenu.querySelectorAll('[data-density]').forEach((btn) => {
        btn.classList.toggle('active', Math.abs(Number(btn.dataset.density) - airbrushDensity) < 0.05);
      });
    }
  }

  function setShapeFill(f) {
    shapeFill = f;
    if (selectedIds.size > 0) {
      strokes.forEach((s) => {
        if (selectedIds.has(s.id) && s.type === 'shape') {
          s.fill = f;
          s.fillColor = s.fillColor || penColor;
        }
      });
      dirty = true;
      saveLocal();
      redraw();
      scheduleSave();
    }
    if (shapesMenu) {
      shapesMenu.querySelectorAll('.boo-shapes-fill-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.fill === f);
      });
    }
  }

  function updateShapeIcon() {
    const shapeBtn = document.getElementById('boo-tb-shape');
    if (!shapeBtn) return;
    const icons = {
      rectangle: 'ph-rectangle',
      square: 'ph-square',
      'rounded-rect': 'ph-square',
      circle: 'ph-circle',
      ellipse: 'ph-circle',
      semicircle: 'ph-circle-half',
      sector: 'ph-chart-pie-slice',
      triangle: 'ph-triangle',
      'right-triangle': 'ph-polygon',
      'equilateral-triangle': 'ph-triangle',
      rhombus: 'ph-diamond',
      parallelogram: 'ph-parallelogram',
      trapezoid: 'ph-trapezoid',
      polygon: 'ph-hexagon',
      star: 'ph-star',
      cloud: 'ph-cloud',
      callout: 'ph-chat-circle-dots',
      brackets: 'ph-brackets-curly',
      cube: 'ph-cube',
      cylinder: 'ph-cylinder',
      cone: 'ph-funnel',
      pyramid: 'ph-triangle',
      line: 'ph-line-segment',
      arrow: 'ph-arrow-up-right',
      'double-arrow': 'ph-arrows-horizontal',
      'curved-arrow': 'ph-arrow-bend-right-up',
      process: 'ph-square',
      decision: 'ph-diamond',
      io: 'ph-parallelogram',
      terminal: 'ph-pill',
    };
    const iconName = icons[currentShape] || 'ph-rectangle';
    shapeBtn.innerHTML = `<i class="ph-bold ${iconName}"></i>`;
  }

  function updateBrushIcon() {
    const penBtn = document.getElementById('boo-tb-pen');
    if (!penBtn) return;
    const icons = {
      pen: 'ph-pencil-simple-line',
      ballpoint: 'ph-pencil-simple-line',
      fountain_pen: 'ph-pen-nib',
      pencil: 'ph-pencil',
      brush: 'ph-paint-brush',
      felt_tip: 'ph-pen',
      highlighter: 'ph-highlighter',
      neon: 'ph-sparkle',
      airbrush: 'ph-spray-bottle',
      dashed_pen: 'ph-line-dashed',
    };
    const ic = icons[currentBrush] || 'ph-pencil-simple-line';
    penBtn.innerHTML = `<i class="ph-bold ${ic}"></i>`;
  }

  function positionFlyoutNextTo(flyoutEl, anchorBtn) {
    if (!flyoutEl || !toolbar) return;
    const anchor = anchorBtn || toolbar;
    const rect = anchor.getBoundingClientRect();
    const tbRect = toolbar.getBoundingClientRect();
    flyoutEl.style.position = 'fixed';

    const flyoutW = flyoutEl.offsetWidth || 290;
    let left = Math.round(tbRect.right + 8);
    if (left + flyoutW > window.innerWidth - 8) {
      left = Math.max(8, Math.round(tbRect.left - flyoutW - 8));
    }
    flyoutEl.style.left = `${left}px`;
    flyoutEl.style.display = 'flex';

    const flyoutH = flyoutEl.offsetHeight || 260;
    const screenH = window.innerHeight;
    let top = rect.top;
    if (top + flyoutH > screenH - 12) {
      top = Math.max(12, screenH - flyoutH - 12);
    }
    if (top < 12) top = 12;
    flyoutEl.style.top = `${Math.round(top)}px`;
  }

  function toggleBrushMenu(show) {
    if (!brushMenu || !toolbar) return;
    const isCurrentlyActive = brushMenu.classList.contains('active') && brushMenu.style.display !== 'none';
    const next = typeof show === 'boolean' ? show : !isCurrentlyActive;
    if (next) {
      toggleShapesMenu(false);
      toggleLaserMenu(false);
      toggleEraserMenu(false);
      toggleMoreMenu(false);
      togglePropPopover(false);
      toggleClearConfirm(false);
      const penBtn = document.getElementById('boo-tb-pen');
      brushMenu.querySelectorAll('.tb-brush-opt').forEach((opt) => {
        opt.classList.toggle('active', opt.dataset.brush === (currentBrush || 'pen'));
      });
      brushMenu.querySelectorAll('.boo-brush-color-swatch').forEach((sw) => {
        sw.classList.toggle('active', sw.dataset.color?.toLowerCase() === penColor.toLowerCase());
      });
      const brushNativeInput = brushMenu.querySelector('.boo-brush-native-color');
      if (brushNativeInput) brushNativeInput.value = penColor;
      brushMenu.querySelectorAll('.boo-brush-size-btn').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.size) === penSize);
      });
      const brushSizeText = document.getElementById('boo-brush-size-text');
      if (brushSizeText) brushSizeText.textContent = `${penSize}px`;
      const brushSlider = document.getElementById('boo-brush-slider');
      if (brushSlider) brushSlider.value = String(penSize);
      const densitySec = document.getElementById('boo-airbrush-density-section');
      if (densitySec) {
        densitySec.style.display = (currentBrush === 'airbrush' || tool === 'airbrush') ? 'flex' : 'none';
      }
      const densityText = document.getElementById('boo-airbrush-density-text');
      if (densityText) densityText.textContent = `${Math.round(airbrushDensity * 100)}%`;
      const densitySlider = document.getElementById('boo-airbrush-density-slider');
      if (densitySlider) densitySlider.value = String(Math.round(airbrushDensity * 100));
      if (brushMenu) {
        brushMenu.querySelectorAll('[data-density]').forEach((btn) => {
          btn.classList.toggle('active', Math.abs(Number(btn.dataset.density) - airbrushDensity) < 0.05);
        });
      }
      brushMenu.style.display = 'flex';
      brushMenu.classList.add('active');
      positionFlyoutNextTo(brushMenu, penBtn);
    } else {
      brushMenu.style.display = 'none';
      brushMenu.classList.remove('active');
    }
  }

  function toggleShapesMenu(show) {
    if (!shapesMenu || !toolbar) return;
    const isCurrentlyActive = shapesMenu.classList.contains('active') && shapesMenu.style.display !== 'none';
    const next = typeof show === 'boolean' ? show : !isCurrentlyActive;
    if (next) {
      toggleBrushMenu(false);
      toggleLaserMenu(false);
      toggleEraserMenu(false);
      toggleMoreMenu(false);
      togglePropPopover(false);
      toggleClearConfirm(false);
      const shapeBtn = document.getElementById('boo-tb-shape');
      shapesMenu.querySelectorAll('.tb-shape-opt').forEach((opt) => {
        opt.classList.toggle('active', opt.dataset.shape === currentShape);
      });
      shapesMenu.querySelectorAll('.boo-brush-color-swatch').forEach((sw) => {
        sw.classList.toggle('active', sw.dataset.color?.toLowerCase() === penColor.toLowerCase());
      });
      const shapeNativeInput = shapesMenu.querySelector('.boo-brush-native-color');
      if (shapeNativeInput) shapeNativeInput.value = penColor;
      shapesMenu.querySelectorAll('.boo-shapes-fill-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.fill === shapeFill);
      });
      shapesMenu.querySelectorAll('.boo-brush-size-btn').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.size) === penSize);
      });
      const shapeSizeText = document.getElementById('boo-shape-size-text');
      if (shapeSizeText) shapeSizeText.textContent = `${penSize}px`;
      shapesMenu.style.display = 'flex';
      shapesMenu.classList.add('active');
      positionFlyoutNextTo(shapesMenu, shapeBtn);
    } else {
      shapesMenu.style.display = 'none';
      shapesMenu.classList.remove('active');
    }
  }

  function toggleLaserMenu(show) {
    if (!laserMenu || !toolbar) return;
    const isCurrentlyActive = laserMenu.classList.contains('active') && laserMenu.style.display !== 'none';
    const next = typeof show === 'boolean' ? show : !isCurrentlyActive;
    if (next) {
      toggleBrushMenu(false);
      toggleShapesMenu(false);
      toggleEraserMenu(false);
      toggleMoreMenu(false);
      togglePropPopover(false);
      toggleClearConfirm(false);
      updateLaserUi();
      const laserBtn = document.getElementById('boo-tb-laser');
      laserMenu.style.display = 'flex';
      laserMenu.classList.add('active');
      positionFlyoutNextTo(laserMenu, laserBtn);
    } else {
      laserMenu.style.display = 'none';
      laserMenu.classList.remove('active');
    }
  }

  function togglePropPopover(show) {
    if (!propPopover || !toolbar) return;
    const next = typeof show === 'boolean' ? show : (propPopover.style.display === 'none' || !propPopover.classList.contains('active'));
    if (next) {
      toggleBrushMenu(false);
      toggleShapesMenu(false);
      toggleLaserMenu(false);
      toggleEraserMenu(false);
      toggleMoreMenu(false);
      toggleClearConfirm(false);
      const propsBtn = document.getElementById('boo-tb-props');
      propPopover.classList.add('active');
      positionFlyoutNextTo(propPopover, propsBtn);
    } else {
      propPopover.style.display = 'none';
      propPopover.classList.remove('active');
    }
  }

  function toggleClearConfirm(show) {
    if (!clearConfirm || !toolbar) return;
    const next = typeof show === 'boolean' ? show : (clearConfirm.style.display === 'none' || !clearConfirm.classList.contains('active'));
    if (next) {
      toggleBrushMenu(false);
      toggleShapesMenu(false);
      toggleLaserMenu(false);
      toggleEraserMenu(false);
      toggleMoreMenu(false);
      togglePropPopover(false);
      const clearBtn = document.getElementById('boo-tb-clear');
      clearConfirm.classList.add('active');
      positionFlyoutNextTo(clearConfirm, clearBtn);
    } else {
      clearConfirm.style.display = 'none';
      clearConfirm.classList.remove('active');
    }
  }

  function mkBtn(icon, title, handler) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tb-btn';
    btn.title = title;
    btn.setAttribute('aria-label', title);
    btn.innerHTML = `<i class="ph-bold ${icon}"></i>`;
    btn.addEventListener('pointerdown', (e) => e.stopPropagation());
    btn.addEventListener('mousedown', (e) => e.stopPropagation());
    btn.addEventListener('pointerup', (e) => e.stopPropagation());
    btn.addEventListener('mouseup', (e) => e.stopPropagation());
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

  function createSaveStatus() {
    saveStatus = document.createElement('div');
    saveStatus.className = 'boo-canvas-save-status';
    saveStatus.title = 'Нажмите, чтобы сохранить изменения';
    saveStatus.innerHTML = '<span class="status-dot"></span><span class="status-text">Сохранено</span>';
    saveStatus.addEventListener('pointerdown', (e) => e.stopPropagation());
    saveStatus.addEventListener('click', (e) => {
      e.stopPropagation();
      saveToServer();
    });
    document.body.appendChild(saveStatus);
  }

  function updateSaveStatus(state) {
    if (!saveStatus) return;
    const textEl = saveStatus.querySelector('.status-text');
    if (state === 'saving') {
      saveStatus.className = 'boo-canvas-save-status saving' + (embeddedTarget ? ' is-embedded' : '');
      if (textEl) textEl.textContent = 'Сохранение...';
    } else if (state === 'unsaved') {
      saveStatus.className = 'boo-canvas-save-status unsaved' + (embeddedTarget ? ' is-embedded' : '');
      if (textEl) textEl.textContent = 'Не сохранено';
    } else {
      saveStatus.className = 'boo-canvas-save-status' + (embeddedTarget ? ' is-embedded' : '');
      if (textEl) textEl.textContent = 'Сохранено';
    }
  }

  function createClearConfirm() {
    clearConfirm = document.createElement('div');
    clearConfirm.className = 'boo-canvas-clear-confirm';
    clearConfirm.innerHTML = `
      <p>Очистить страницу?</p>
      <div class="boo-confirm-actions">
        <button type="button" class="boo-confirm-btn boo-confirm-danger">Очистить</button>
        <button type="button" class="boo-confirm-btn boo-confirm-cancel">Отмена</button>
      </div>
    `;
    clearConfirm.querySelector('.boo-confirm-danger').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleClearConfirm(false);
      executeClearAll();
    });
    clearConfirm.querySelector('.boo-confirm-cancel').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleClearConfirm(false);
    });
    document.body.appendChild(clearConfirm);
  }

  // Auto-init
  function autoDetectContext() {
    const body = document.body;
    const tid = body.dataset.canvasTaskId;
    const ctype = body.dataset.canvasContextType;
    const cid = body.dataset.canvasContextId;
    if (tid) {
      setContext(Number(tid), ctype || 'submission', cid ? Number(cid) : null);
    }
  }

  window.initCanvasOverlay = function () {
    init();
    autoDetectContext();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { window.initCanvasOverlay(); });
  } else {
    window.initCanvasOverlay();
  }

  function applyRemoteStrokeLive(payload) {
    if (!payload) return;
    const strokeId = payload.stroke_id || payload.stroke?.id;
    if (!strokeId) return;
    const pageId = payload.page_id || payload.stroke?.page_id || currentPageId;
    if (payload.phase === 'cancel') {
      remoteLiveStrokes.delete(strokeId);
    } else if (payload.phase === 'end') {
      if (payload.stroke) {
        payload.stroke.page_id = pageId;
        remoteLiveStrokes.set(strokeId, payload.stroke);
      }
      setTimeout(() => {
        if (remoteLiveStrokes.has(strokeId)) {
          remoteLiveStrokes.delete(strokeId);
          redraw();
        }
      }, 1000);
    } else if (payload.stroke && Array.isArray(payload.stroke.points) && payload.stroke.points.length > 0) {
      payload.stroke.page_id = pageId;
      remoteLiveStrokes.set(strokeId, payload.stroke);
    } else {
      let existing = remoteLiveStrokes.get(strokeId);
      if (!existing) {
        existing = {
          id: strokeId,
          page_id: pageId,
          tool: payload.style?.eraser ? 'eraser' : 'pen',
          points: [],
          color: payload.style?.color || '#4f46e5',
          size: Number(payload.style?.size) || 4,
          width: Number(payload.style?.size) || 4,
          opacity: Number(payload.style?.opacity ?? 1),
        };
        remoteLiveStrokes.set(strokeId, existing);
      }
      if (Array.isArray(payload.points)) {
        if (!existing.points || existing.points.length === 0) {
          existing.points = payload.points.slice();
        } else {
          const lastPt = existing.points[existing.points.length - 1];
          payload.points.forEach((pt) => {
            if (!lastPt || Math.abs(lastPt.x - pt.x) > 0.001 || Math.abs(lastPt.y - pt.y) > 0.001) {
              existing.points.push(pt);
            }
          });
        }
      }
    }
    redraw();
  }

  function applyRemoteStrokeCommit(remoteStroke) {
    if (!remoteStroke || !remoteStroke.id) return;
    remoteLiveStrokes.delete(remoteStroke.id);
    const targetPageId = remoteStroke.page_id || currentPageId;
    let targetPage = pages.find((p) => p.id === targetPageId);
    if (!targetPage) {
      targetPage = { id: targetPageId, title: `Страница ${pages.length + 1}`, background: 'dots', strokes: [] };
      pages.push(targetPage);
      renderPageTabs();
    }
    const idx = targetPage.strokes.findIndex((s) => s.id === remoteStroke.id);
    if (idx >= 0) {
      const existingSrc = targetPage.strokes[idx].src;
      targetPage.strokes[idx] = { ...targetPage.strokes[idx], ...remoteStroke };
      if (!remoteStroke.src && existingSrc) targetPage.strokes[idx].src = existingSrc;
    } else {
      targetPage.strokes.push(remoteStroke);
    }
    if (currentPageId === targetPageId) {
      strokes = targetPage.strokes;
      redraw();
      syncDomWidgets();
    }
  }

  function applyRemoteStrokesUpdate(updatedStrokes) {
    if (!Array.isArray(updatedStrokes)) return;
    let shouldRedraw = false;
    updatedStrokes.forEach((s) => {
      if (!s || !s.id) return;
      pages.forEach((pg) => {
        const idx = pg.strokes.findIndex((item) => item.id === s.id);
        if (idx >= 0) {
          const existingSrc = pg.strokes[idx].src;
          const existingPageId = pg.strokes[idx].page_id;
          pg.strokes[idx] = { ...pg.strokes[idx], ...s };
          if (!s.src && existingSrc) pg.strokes[idx].src = existingSrc;
          if (!s.page_id && existingPageId) pg.strokes[idx].page_id = existingPageId;
          if (pg.id === currentPageId) shouldRedraw = true;
        }
      });
    });
    if (shouldRedraw) {
      strokes = getActivePage().strokes;
      redraw();
      syncDomWidgets();
    }
  }

  function applyRemoteStrokesDelete(strokeIds) {
    const idSet = new Set(Array.isArray(strokeIds) ? strokeIds : [strokeIds]);
    let shouldRedraw = false;
    pages.forEach((pg) => {
      const prevLen = pg.strokes.length;
      pg.strokes = pg.strokes.filter((s) => !idSet.has(s.id));
      if (pg.id === currentPageId && pg.strokes.length !== prevLen) {
        shouldRedraw = true;
      }
    });
    if (shouldRedraw) {
      strokes = getActivePage().strokes;
      redraw();
      syncDomWidgets();
    }
  }

  function applyRemoteBoardClear(targetPageId) {
    const pId = targetPageId || currentPageId;
    const pg = pages.find((p) => p.id === pId);
    if (pg) {
      pg.strokes = [];
    }
    if (currentPageId === pId) {
      strokes = [];
      remoteLiveStrokes.clear();
      redraw();
      syncDomWidgets();
    }
  }

  function applyRemoteLaser(worldPoint, visible = true, options = {}) {
    const opts = (typeof visible === 'object' && visible !== null) ? visible : (options || {});
    const isVisible = (typeof visible === 'boolean') ? visible : (opts.visible !== false);
    if (!isVisible || !worldPoint) {
      laserTrail.length = 0;
      drawLaserTop();
      return;
    }
    if (opts.color) remoteLaserColor = opts.color;
    if (opts.width || opts.size) remoteLaserWidth = Number(opts.width || opts.size);
    const screenX = Number(worldPoint.x) * viewScale + viewOffsetX;
    const screenY = Number(worldPoint.y) * viewScale + viewOffsetY;
    laserTrail.push({
      x: screenX,
      y: screenY,
      t: Date.now(),
      isStart: Boolean(opts.isStart),
    });
    drawLaserTop();
  }

  function setAllStrokes(strokesList) {
    remoteLiveStrokes.clear();
    const list = Array.isArray(strokesList) ? strokesList : [];
    const pageMap = new Map();
    list.forEach((s) => {
      if (!s) return;
      const pid = s.page_id || 'page_1';
      s.page_id = pid;
      if (!pageMap.has(pid)) pageMap.set(pid, []);
      pageMap.get(pid).push(s);
    });

    pageMap.forEach((pStrokes, pid) => {
      let page = pages.find((p) => p.id === pid);
      if (!page) {
        page = { id: pid, title: pid === 'page_1' ? 'Страница 1' : `Страница ${pages.length + 1}`, background: 'dots', strokes: [] };
        pages.push(page);
      }
      const strokeMap = new Map();
      (page.strokes || []).forEach((item) => {
        if (item && item.id) strokeMap.set(item.id, item);
      });
      pStrokes.forEach((s) => {
        if (!s || !s.id) return;
        const local = strokeMap.get(s.id);
        if (local) {
          strokeMap.set(s.id, { ...local, ...s, src: s.src || local.src });
        } else {
          strokeMap.set(s.id, s);
        }
      });
      page.strokes = Array.from(strokeMap.values());
    });

    syncPageStrokes();
    renderPageTabs();
    redraw();
    syncDomWidgets();
  }

  function setReadOnly(ro) {
    isReadOnly = Boolean(ro);
    if (isReadOnly && tool !== 'select' && tool !== 'pan') {
      setTool('select');
    }
  }

  function setRealtimeSync(adapter) {
    realtimeSyncAdapter = adapter;
  }

  window.BooCanvasOverlay = {
    open,
    openIn,
    close,
    toggle,
    setContext,
    setTool,
    setPenColor,
    insertInteractiveWidget,
    zoomIn: () => zoomBy(1.2),
    zoomOut: () => zoomBy(1 / 1.2),
    zoomBy,
    save: saveToServer,
    hasContent: () => strokes.length > 0,
    getStrokes: () => strokes,
    getSelectedIds: () => Array.from(selectedIds),
    init: window.initCanvasOverlay,
    openCatalog: openCatalogModal,
    openMath: openMathModal,
    exportPNG,
    exportSVG,
    exportJSON,
    addNewPage,
    switchPage,
    deletePage,
    getPages: () => pages,
    getActivePageId: () => currentPageId,
    setCamera: (offsetX, offsetY, scale, broadcast = false) => {
      if (Number.isFinite(offsetX)) viewOffsetX = offsetX;
      if (Number.isFinite(offsetY)) viewOffsetY = offsetY;
      if (Number.isFinite(scale) && scale > 0) viewScale = Math.min(5, Math.max(0.1, scale));
      redraw();
      updateZoomBadge();
      if (broadcast) {
        realtimeSyncAdapter?.onCameraChange?.(viewOffsetX, viewOffsetY, viewScale);
      }
    },
    getCamera: () => ({ offsetX: viewOffsetX, offsetY: viewOffsetY, scale: viewScale }),
    setRealtimeSync,
    setReadOnly,
    applyRemoteStrokeLive,
    applyRemoteStrokeCommit,
    applyRemoteStrokesUpdate,
    applyRemoteStrokesDelete,
    applyRemoteBoardClear,
    applyRemoteLaser,
    setAllStrokes,
  };
})();
