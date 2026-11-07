/**
 * BooStudy Teacher Control Center — Sprint 2.6
 * The Ultimate Teaching Workspace: 3-Zone Adaptive Architecture
 * State machine, Direct Manipulations, Smart Inspector, Attention System
 */

(function () {
  'use strict';

  // State object
  const state = {
    data: {},
    lessons: [],
    weekdays: [],
    accessibleStudents: [],
    activeUser: {},
    currentView: 'week', // 'week' | 'day' | 'month' | 'stream' | 'focus'
    weekOffset: 0,
    selectedDate: null,
    selectedLesson: null,
    selectedStudent: null,
    inspectorMode: 'overview', // 'overview' | 'lesson' | 'student' | 'find_time' | 'composer'
    isInspectorOpen: true,
    isRailExpanded: false,
    activeRailTab: 'students', // 'students' | 'subjects' | 'layers' | 'series'
    filters: {
      studentId: null,
      subject: null,
      status: null,
      searchQuery: '',
    },
    layers: {
      homework: true,
      workingHours: true,
      grid15m: false,
    },
    density: 'comfortable', // 'comfortable' | 'compact'
    pendingDrag: null,
    dragState: null,
    resizeState: null,
    selectState: null,
    hasScrolledToActiveHours: false,
  };

  const RU_WD_NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  const RU_WD_NAMES_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];
  const RU_MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

  // Initialize
  function init() {
    const rawDataEl = document.getElementById('schedule-data');
    if (!rawDataEl) return;

    try {
      state.data = JSON.parse(rawDataEl.textContent || '{}');
    } catch (e) {
      console.error('Error parsing schedule data:', e);
      state.data = {};
    }

    state.lessons = state.data.lessons || [];
    state.weekdays = state.data.weekdays || [];
    state.accessibleStudents = state.data.accessible_students || [];
    state.activeUser = state.data.active_user || {};
    state.weekOffset = state.data.week_offset || 0;
    state.selectedDate = state.data.today_iso || new Date().toISOString().split('T')[0];

    // Read stored preferences
    try {
      const savedDensity = localStorage.getItem('tcc_density');
      if (savedDensity) state.density = savedDensity;
      const savedView = localStorage.getItem('tcc_view');
      if (savedView && ['week', 'day', 'month', 'stream', 'focus'].includes(savedView)) {
        state.currentView = savedView;
      }
    } catch (e) {}

    setupDOM();
    setupEventListeners();
    setupKeyboardShortcuts();
    renderAll();

    // Start live countdown & current time line timer
    setInterval(updateLiveIndicators, 30000);
    updateLiveIndicators();
  }

  // Setup main layout container classes and references
  function setupDOM() {
    const ws = document.getElementById('tcc-workspace');
    if (!ws) return;

    if (state.density === 'compact') {
      ws.classList.add('is-density-compact');
    } else {
      ws.classList.remove('is-density-compact');
    }
  }

  // Event Listeners
  function setupEventListeners() {
    // Tool rail tabs
    document.querySelectorAll('[data-rail-tab]').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-rail-tab');
        toggleRail(tab);
      });
    });

    // Rail drawer close
    const railClose = document.getElementById('tcc-rail-close');
    if (railClose) {
      railClose.addEventListener('click', () => {
        toggleRail(null, false);
      });
    }

    // View switcher pills
    document.querySelectorAll('[data-view-target]').forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.getAttribute('data-view-target');
        switchView(view);
      });
    });

    // Navigation buttons
    const btnPrev = document.getElementById('tcc-nav-prev');
    if (btnPrev) btnPrev.addEventListener('click', () => navigatePeriod(-1));
    const btnNext = document.getElementById('tcc-nav-next');
    if (btnNext) btnNext.addEventListener('click', () => navigatePeriod(1));
    const btnToday = document.getElementById('tcc-nav-today');
    if (btnToday) btnToday.addEventListener('click', () => navigatePeriod(0, true));

    // "Find a Time" launcher
    const btnFind = document.getElementById('tcc-btn-find-time');
    if (btnFind) {
      btnFind.addEventListener('click', () => {
        openInspector('find_time');
      });
    }

    // "+ Новый урок" launcher
    const btnNew = document.getElementById('tcc-btn-new-lesson');
    if (btnNew) {
      btnNew.addEventListener('click', () => {
        openInspector('composer');
      });
    }

    // Inspector toggle & close
    const inspToggle = document.getElementById('tcc-inspector-toggle');
    if (inspToggle) {
      inspToggle.addEventListener('click', () => {
        toggleInspector();
      });
    }

    const inspClose = document.getElementById('tcc-inspector-close');
    if (inspClose) {
      inspClose.addEventListener('click', () => {
        toggleInspector(false);
      });
    }

    // Density toggle
    const densityBtn = document.getElementById('tcc-toggle-density');
    if (densityBtn) {
      densityBtn.addEventListener('click', () => {
        state.density = state.density === 'comfortable' ? 'compact' : 'comfortable';
        try { localStorage.setItem('tcc_density', state.density); } catch (e) {}
        setupDOM();
        renderAll();
      });
    }

    // Global click listener to close context menus & command palette
    document.addEventListener('click', (e) => {
      const ctxMenu = document.getElementById('tcc-context-menu');
      if (ctxMenu && !ctxMenu.contains(e.target)) {
        ctxMenu.classList.add('is-hidden');
      }

      const cmdModal = document.getElementById('tcc-cmd-modal');
      if (cmdModal && e.target === cmdModal) {
        cmdModal.classList.add('is-hidden');
      }
    });

    // Mouse drag-and-drop & resize listeners on window
    window.addEventListener('mousemove', handlePointerMove);
    window.addEventListener('mouseup', handlePointerUp);
    window.addEventListener('touchmove', handlePointerMove, { passive: false });
    window.addEventListener('touchend', handlePointerUp);
  }

  // Keyboard shortcuts (Cmd+K, /, Esc, etc.)
  function setupKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      // Toggle Command Palette
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        toggleCommandPalette();
        return;
      }

      // Quick search on '/' when not in input
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
        e.preventDefault();
        toggleCommandPalette();
        return;
      }

      // Close modal on Escape
      if (e.key === 'Escape') {
        if (state.dragState) {
          if (state.dragState.ghostEl) state.dragState.ghostEl.remove();
          if (state.dragState.cardEl) state.dragState.cardEl.style.opacity = '1';
          state.dragState = null;
          state.pendingDrag = null;
          showToast('Перенос отменён', 'info');
          return;
        }
        state.pendingDrag = null;

        if (state.isRailExpanded) {
          toggleRail(null, false);
          return;
        }

        if (state.isInspectorOpen && window.innerWidth <= 1440) {
          toggleInspector(false);
          return;
        }

        const cmdModal = document.getElementById('tcc-cmd-modal');
        if (cmdModal && !cmdModal.classList.contains('is-hidden')) {
          cmdModal.classList.add('is-hidden');
          return;
        }
        const scopeModal = document.getElementById('tcc-scope-modal');
        if (scopeModal && !scopeModal.classList.contains('is-hidden')) {
          scopeModal.classList.add('is-hidden');
          return;
        }
        const ctxMenu = document.getElementById('tcc-context-menu');
        if (ctxMenu && !ctxMenu.classList.contains('is-hidden')) {
          ctxMenu.classList.add('is-hidden');
          return;
        }
      }
    });
  }

  // Tool Rail Drawer toggle
  function toggleRail(tab = null, forceState = null) {
    const rail = document.getElementById('tcc-tool-rail');
    const backdrop = document.getElementById('tcc-drawer-backdrop');
    if (!rail) return;

    if (forceState !== null) {
      state.isRailExpanded = forceState;
    } else if (tab && state.activeRailTab === tab && state.isRailExpanded) {
      state.isRailExpanded = false;
    } else {
      state.isRailExpanded = true;
    }

    if (tab) state.activeRailTab = tab;

    if (state.isRailExpanded) {
      rail.classList.add('is-expanded');
      if (backdrop) backdrop.classList.remove('is-hidden');
      renderRailDrawer();
    } else {
      rail.classList.remove('is-expanded');
      if (backdrop) backdrop.classList.add('is-hidden');
    }

    // Update active tab buttons (header tools)
    const btnFilters = document.getElementById('tcc-btn-filters');
    const btnLayers = document.getElementById('tcc-btn-layers');
    const btnSeries = document.getElementById('tcc-btn-series');
    if (btnFilters) btnFilters.classList.toggle('is-active', state.isRailExpanded && state.activeRailTab === 'students');
    if (btnLayers) btnLayers.classList.toggle('is-active', state.isRailExpanded && state.activeRailTab === 'layers');
    if (btnSeries) btnSeries.classList.toggle('is-active', state.isRailExpanded && state.activeRailTab === 'series');

    document.querySelectorAll('[data-rail-tab]').forEach(b => {
      const bTab = b.getAttribute('data-rail-tab');
      if (state.isRailExpanded && bTab === state.activeRailTab) {
        b.classList.add('is-active');
      } else {
        b.classList.remove('is-active');
      }
    });

    updateFilterBadge();
  }

  function updateFilterBadge() {
    const badge = document.getElementById('tcc-filter-badge');
    if (!badge) return;
    let count = 0;
    if (state.filters.studentId !== null) count++;
    if (state.filters.subject !== null) count++;
    if (count > 0) {
      badge.textContent = count;
      badge.classList.remove('is-hidden');
    } else {
      badge.classList.add('is-hidden');
    }
  }

  // Render contents of the Tool Rail Drawer
  function renderRailDrawer() {
    const titleEl = document.getElementById('tcc-rail-title');
    const contentEl = document.getElementById('tcc-rail-content');
    if (!titleEl || !contentEl) return;

    if (state.activeRailTab === 'students') {
      titleEl.innerHTML = '<i class="ph-bold ph-users text-indigo-600"></i> <span>Ученики</span>';
      let html = `
        <div class="mb-3">
          <input type="text" id="tcc-student-search-input" placeholder="Поиск ученика..." value="${state.filters.searchQuery}" class="w-full bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500">
        </div>
        <div class="flex flex-col gap-1.5 max-h-[60vh] overflow-y-auto">
          <div onclick="window.TCC.filterByStudent(null)" class="flex items-center justify-between p-2 rounded-xl border border-slate-100 hover:bg-slate-50 cursor-pointer ${state.filters.studentId === null ? 'bg-indigo-50 border-indigo-200 text-indigo-700 font-extrabold' : 'text-slate-700 font-bold text-xs'}">
            <span>Все ученики</span>
            <span class="text-[10px] bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded-full font-extrabold">${state.accessibleStudents.length}</span>
          </div>
      `;
      state.accessibleStudents.forEach(st => {
        const isSel = state.filters.studentId === st.student_id;
        html += `
          <div onclick="window.TCC.filterByStudent(${st.student_id})" class="flex items-center justify-between p-2 rounded-xl border border-slate-100 hover:bg-slate-50 cursor-pointer ${isSel ? 'bg-indigo-50 border-indigo-200 text-indigo-700 font-extrabold' : 'text-slate-700 font-bold text-xs'}">
            <div class="flex items-center gap-2 truncate">
              <div class="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-[10px] font-black shrink-0">
                ${st.name ? st.name.charAt(0) : 'У'}
              </div>
              <span class="truncate">${escapeHtml(st.name || 'Ученик')}</span>
            </div>
            ${st.grade ? `<span class="text-[10px] text-slate-400 shrink-0">${st.grade} кл</span>` : ''}
          </div>
        `;
      });
      html += `</div>`;
      contentEl.innerHTML = html;

      const searchInput = document.getElementById('tcc-student-search-input');
      if (searchInput) {
        searchInput.addEventListener('input', (e) => {
          state.filters.searchQuery = e.target.value.toLowerCase();
          document.querySelectorAll('#tcc-rail-content [data-student-name]').forEach(el => {
            const name = el.getAttribute('data-student-name') || '';
            el.style.display = name.includes(state.filters.searchQuery) ? 'flex' : 'none';
          });
        });
      }
    } else if (state.activeRailTab === 'subjects') {
      titleEl.innerHTML = '<i class="ph-bold ph-books text-indigo-600"></i> <span>Предметы</span>';
      const subjects = ['Все предметы', 'Информатика', 'Математика', 'Физика', 'Программирование'];
      let html = '<div class="flex flex-col gap-1.5">';
      subjects.forEach(sub => {
        const val = sub === 'Все предметы' ? null : sub;
        const isSel = state.filters.subject === val;
        html += `
          <div onclick="window.TCC.filterBySubject(${val ? `'${val}'` : 'null'})" class="flex items-center justify-between p-2 rounded-xl border border-slate-100 hover:bg-slate-50 cursor-pointer ${isSel ? 'bg-indigo-50 border-indigo-200 text-indigo-700 font-extrabold' : 'text-slate-700 font-bold text-xs'}">
            <span>${sub}</span>
            ${isSel ? '<i class="ph-bold ph-check text-indigo-600"></i>' : ''}
          </div>
        `;
      });
      html += '</div>';
      contentEl.innerHTML = html;
    } else if (state.activeRailTab === 'layers') {
      titleEl.innerHTML = '<i class="ph-bold ph-stack text-indigo-600"></i> <span>Слои расписания</span>';
      contentEl.innerHTML = `
        <div class="flex flex-col gap-3">
          <div class="flex items-center justify-between p-2.5 rounded-xl border border-slate-200 bg-white shadow-xs">
            <div>
              <div class="text-xs font-black text-slate-800">Домашние задания</div>
              <div class="text-[10px] text-slate-500 font-medium">Показывать дедлайны учеников</div>
            </div>
            <input type="checkbox" id="tcc-layer-hw" ${state.layers.homework ? 'checked' : ''} onchange="window.TCC.toggleLayer('homework', this.checked)" class="w-4 h-4 text-indigo-600 rounded cursor-pointer">
          </div>

          <div class="flex items-center justify-between p-2.5 rounded-xl border border-slate-200 bg-white shadow-xs">
            <div>
              <div class="text-xs font-black text-slate-800">Рабочие часы</div>
              <div class="text-[10px] text-slate-500 font-medium">Подсветка доступного времени</div>
            </div>
            <input type="checkbox" id="tcc-layer-wh" ${state.layers.workingHours ? 'checked' : ''} onchange="window.TCC.toggleLayer('workingHours', this.checked)" class="w-4 h-4 text-indigo-600 rounded cursor-pointer">
          </div>

          <div class="flex items-center justify-between p-2.5 rounded-xl border border-slate-200 bg-white shadow-xs">
            <div>
              <div class="text-xs font-black text-slate-800">Сетка 15 минут</div>
              <div class="text-[10px] text-slate-500 font-medium">Высокая детализация слотов</div>
            </div>
            <input type="checkbox" id="tcc-layer-15m" ${state.layers.grid15m ? 'checked' : ''} onchange="window.TCC.toggleLayer('grid15m', this.checked)" class="w-4 h-4 text-indigo-600 rounded cursor-pointer">
          </div>
        </div>
      `;
    } else if (state.activeRailTab === 'series') {
      titleEl.innerHTML = '<i class="ph-bold ph-arrows-clockwise text-indigo-600"></i> <span>Серии уроков</span>';
      const seriesList = state.data.recurring_series || [];
      if (seriesList.length === 0) {
        contentEl.innerHTML = `
          <div class="text-center py-6">
            <i class="ph-duotone ph-repeat text-3xl text-slate-300 block mb-2"></i>
            <div class="text-xs font-bold text-slate-600">Нет активных серий</div>
            <div class="text-[11px] text-slate-400 mt-1">Регулярные занятия будут отображаться здесь</div>
            <button onclick="window.openRecurringSeriesModal()" class="mt-4 px-3 py-1.5 bg-indigo-50 border border-indigo-200 text-indigo-600 text-xs font-black rounded-xl hover:bg-indigo-100 transition cursor-pointer">+ Создать серию</button>
          </div>
        `;
      } else {
        let html = `
          <div class="flex items-center justify-between mb-2">
            <span class="text-[11px] font-black text-slate-400 uppercase">Всего серий: ${seriesList.length}</span>
            <button onclick="window.openRecurringSeriesModal()" class="text-xs text-indigo-600 font-black hover:underline cursor-pointer">+ Новая</button>
          </div>
          <div class="flex flex-col gap-2 max-h-[60vh] overflow-y-auto">
        `;
        seriesList.forEach(s => {
          html += `
            <div class="p-2.5 rounded-xl border border-slate-200 bg-white shadow-xs flex flex-col gap-1">
              <div class="flex items-center justify-between">
                <span class="text-xs font-black text-slate-800 truncate">${escapeHtml(s.student_name)}</span>
                <span class="text-[10px] font-black px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700">${RU_WD_NAMES[s.weekday]} ${s.time_hhmm}</span>
              </div>
              <div class="text-[11px] text-slate-500 font-medium">${escapeHtml(s.subject || 'Информатика')} • ${s.duration} мин</div>
              <div class="flex items-center justify-end gap-2 mt-1 pt-1 border-t border-slate-100">
                <button onclick="window.pauseRecurringSeries(${s.slot_id})" class="text-[10px] font-bold text-slate-500 hover:text-slate-800 cursor-pointer">Приостановить</button>
                <button onclick="window.cancelRecurringSeries(${s.slot_id})" class="text-[10px] font-bold text-rose-500 hover:text-rose-700 cursor-pointer">Отменить</button>
              </div>
            </div>
          `;
        });
        html += '</div>';
        contentEl.innerHTML = html;
      }
    }
  }

  // Switch Calendar View
  function switchView(view) {
    if (!['week', 'day', 'month', 'stream', 'focus'].includes(view)) return;
    state.currentView = view;
    try { localStorage.setItem('tcc_view', view); } catch (e) {}

    // Update pill tabs
    document.querySelectorAll('[data-view-target]').forEach(btn => {
      if (btn.getAttribute('data-view-target') === view) {
        btn.classList.add('is-active');
      } else {
        btn.classList.remove('is-active');
      }
    });

    renderAll();
  }

  // Switch Inspector Mode & Toggle
  function openInspector(mode = 'overview', payload = null) {
    state.inspectorMode = mode;
    state.isInspectorOpen = true;

    if (mode === 'lesson' && payload) {
      state.selectedLesson = payload;
    } else if (mode === 'student' && payload) {
      state.selectedStudent = payload;
    }

    const insp = document.getElementById('tcc-inspector');
    const backdrop = document.getElementById('tcc-inspector-backdrop');
    if (insp) {
      insp.classList.remove('is-collapsed');
      insp.classList.add('is-mobile-open', 'is-drawer-open');
    }
    if (backdrop && window.innerWidth <= 1440) {
      backdrop.classList.remove('is-hidden');
    }

    renderInspector();
  }

  function toggleInspector(force = null) {
    const insp = document.getElementById('tcc-inspector');
    const backdrop = document.getElementById('tcc-inspector-backdrop');
    if (!insp) return;

    if (force !== null) {
      state.isInspectorOpen = force;
    } else {
      state.isInspectorOpen = !state.isInspectorOpen;
    }

    if (state.isInspectorOpen) {
      insp.classList.remove('is-collapsed');
      insp.classList.add('is-mobile-open', 'is-drawer-open');
      if (backdrop && window.innerWidth <= 1440) backdrop.classList.remove('is-hidden');
      renderInspector();
    } else {
      insp.classList.add('is-collapsed');
      insp.classList.remove('is-mobile-open', 'is-drawer-open');
      if (backdrop) backdrop.classList.add('is-hidden');
    }
  }

  // Filter handlers
  function filterByStudent(studentId) {
    state.filters.studentId = studentId;
    updateFilterBadge();
    renderAll();
    toggleRail(null, false);
  }

  function filterBySubject(subject) {
    state.filters.subject = subject;
    updateFilterBadge();
    renderAll();
    toggleRail(null, false);
  }

  function toggleLayer(layerName, enabled) {
    if (layerName in state.layers) {
      state.layers[layerName] = enabled;
      renderAll();
    }
  }

  // Master render router
  function renderAll() {
    renderTopHeader();
    renderSubBar();

    const weekWrap = document.getElementById('tcc-week-view');
    const dayWrap = document.getElementById('tcc-day-view');
    const monthWrap = document.getElementById('tcc-month-view');
    const streamWrap = document.getElementById('tcc-stream-view');
    const focusWrap = document.getElementById('tcc-focus-view');

    // Hide all
    if (weekWrap) weekWrap.style.display = 'none';
    if (dayWrap) dayWrap.style.display = 'none';
    if (monthWrap) monthWrap.style.display = 'none';
    if (streamWrap) streamWrap.style.display = 'none';
    if (focusWrap) focusWrap.style.display = 'none';

    if (state.currentView === 'week') {
      if (weekWrap) {
        weekWrap.style.display = 'flex';
        renderWeekGrid();
      }
    } else if (state.currentView === 'day') {
      if (dayWrap) {
        dayWrap.style.display = 'flex';
        renderDayView();
      }
    } else if (state.currentView === 'month') {
      if (monthWrap) {
        monthWrap.style.display = 'grid';
        renderMonthView();
      }
    } else if (state.currentView === 'stream') {
      if (streamWrap) {
        streamWrap.style.display = 'flex';
        renderStreamView();
      }
    } else if (state.currentView === 'focus') {
      if (focusWrap) {
        focusWrap.style.display = 'flex';
        renderFocusView();
      }
    }

    renderInspector();
  }

  // Render Top Header
  function renderTopHeader() {
    const titleEl = document.getElementById('tcc-period-title');
    if (titleEl) {
      if (state.currentView === 'day' || state.currentView === 'focus') {
        const d = new Date(state.selectedDate);
        titleEl.textContent = `${d.getDate()} ${RU_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
      } else {
        titleEl.textContent = state.data.week_label || 'Расписание';
      }
    }

    const tzDisplay = document.getElementById('tcc-tz-label');
    if (tzDisplay) {
      const tz = state.data.timezone || 'Europe/Moscow';
      tzDisplay.textContent = tz.includes('Yekaterinburg') ? 'YEKT (+5)' : tz.includes('Novosibirsk') ? 'NOVT (+7)' : 'MSK (+3)';
    }
  }

  // Render Sub Bar (Filters + Metrics)
  function renderSubBar() {
    const bar = document.getElementById('tcc-sub-bar');
    if (!bar) return;

    const filteredLessons = getFilteredLessons();
    const plannedCount = filteredLessons.filter(l => l.status === 'planned').length;
    const liveCount = filteredLessons.filter(l => l.status === 'in_progress').length;
    const hwItems = state.data.teacher_homework_items || [];
    const hwReviewCount = hwItems.filter(h => h.status === 'SUBMITTED' || h.status === 'NEEDS_MANUAL_REVIEW').length;

    let filterTag = '';
    if (state.filters.studentId) {
      const st = state.accessibleStudents.find(s => s.student_id === state.filters.studentId);
      filterTag = `
        <span class="tcc-filter-tag">
          <span>Ученик: ${escapeHtml(st ? st.name : '#' + state.filters.studentId)}</span>
          <button onclick="window.TCC.filterByStudent(null)" class="hover:text-red-600 font-black cursor-pointer">×</button>
        </span>
      `;
    }
    if (state.filters.subject) {
      filterTag += `
        <span class="tcc-filter-tag">
          <span>Предмет: ${escapeHtml(state.filters.subject)}</span>
          <button onclick="window.TCC.filterBySubject(null)" class="hover:text-red-600 font-black cursor-pointer">×</button>
        </span>
      `;
    }

    bar.innerHTML = `
      <div class="flex items-center gap-2">
        ${filterTag || '<span class="text-slate-400 font-bold">Фильтры не применены</span>'}
      </div>
      <div class="tcc-metrics-items">
        <span class="tcc-metric-badge"><span class="tcc-metric-dot bg-indigo-500"></span> Запланировано: ${plannedCount}</span>
        ${liveCount > 0 ? `<span class="tcc-metric-badge text-amber-600 font-black"><span class="tcc-metric-dot bg-amber-500 animate-pulse"></span> Идёт: ${liveCount}</span>` : ''}
        <span class="tcc-metric-badge"><span class="tcc-metric-dot bg-emerald-500"></span> ДЗ на проверке: ${hwReviewCount}</span>
      </div>
    `;
  }

  // Filter lessons according to current filters
  function getFilteredLessons() {
    return state.lessons.filter(l => {
      if (state.filters.studentId && l.student_id !== state.filters.studentId) return false;
      if (state.filters.subject && l.subject !== state.filters.subject) return false;
      if (state.filters.status && l.status !== state.filters.status) return false;
      return true;
    });
  }

  // ==========================================================================
  // VIEW 1: WEEK VIEW
  // ==========================================================================
  function renderWeekGrid() {
    if (window.innerWidth <= 768) {
      renderMobileWeekRibbon();
      return;
    }
    const daysHeaderRow = document.getElementById('tcc-days-header-row');
    if (daysHeaderRow) daysHeaderRow.style.display = 'grid';
    renderWeekHeaders();
    renderWeekBody();
  }

  function selectMobileDay(iso) {
    state.selectedMobileDayIso = iso;
    renderWeekGrid();
  }

  function renderMobileWeekRibbon() {
    const daysHeaderRow = document.getElementById('tcc-days-header-row');
    if (daysHeaderRow) daysHeaderRow.style.display = 'none';

    const gridBody = document.getElementById('tcc-grid-body');
    if (!gridBody) return;

    if (!state.selectedMobileDayIso) {
      const todayObj = state.weekdays.find(d => d.is_today);
      state.selectedMobileDayIso = todayObj ? todayObj.iso : state.weekdays[0].iso;
    }

    const activeDay = state.weekdays.find(d => d.iso === state.selectedMobileDayIso) || state.weekdays[0];
    const filtered = getFilteredLessons();
    const dayLessons = filtered.filter(l => l.start_date === activeDay.iso);

    let ribbonHtml = `
      <div class="tcc-mobile-week-strip mb-3">
        ${state.weekdays.map(d => {
          const isSel = d.iso === state.selectedMobileDayIso;
          const count = filtered.filter(l => l.start_date === d.iso).length;
          return `
            <div class="tcc-mobile-day-pill ${isSel ? 'is-active' : ''}" onclick="window.TCC.selectMobileDay('${d.iso}')">
              <span class="text-[11px] font-bold text-slate-500 uppercase">${d.short_name}</span>
              <span class="text-sm font-black">${d.date}</span>
              ${count > 0 ? `<span class="w-1.5 h-1.5 rounded-full bg-indigo-500 mt-1"></span>` : '<span class="w-1.5 h-1.5 mt-1"></span>'}
            </div>
          `;
        }).join('')}
      </div>
    `;

    let agendaHtml = '';
    if (dayLessons.length === 0) {
      agendaHtml = `
        <div class="bg-white rounded-2xl border-1.5 border-slate-200 p-6 text-center shadow-sm my-4">
          <i class="ph-duotone ph-calendar-blank text-4xl text-slate-400 mb-2"></i>
          <h4 class="font-black text-slate-800 text-base">Нет занятий на этот день</h4>
          <p class="text-xs text-slate-500 mt-1 mb-4">Нажмите кнопку «+» ниже, чтобы запланировать новый урок или подобрать свободное окно.</p>
          <button onclick="window.TCC.openInspector('composer', { date: '${activeDay.iso}' })" class="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 text-white font-black text-xs shadow-md">
            <i class="ph-bold ph-plus"></i> Создать урок
          </button>
        </div>
      `;
    } else {
      agendaHtml = `
        <div class="flex flex-col gap-3 pb-24 px-2">
          ${dayLessons.map(l => {
            const isLive = l.status === 'in_progress';
            const subject = l.subject || 'Занятие';
            const colorClass = subject.includes('Информ') ? 'stripe-indigo' : subject.includes('Мат') ? 'stripe-sky' : 'stripe-emerald';
            return `
              <div class="tcc-mobile-agenda-card is-visible ${colorClass} ${isLive ? 'is-live' : ''} cursor-pointer" onclick="window.TCC.openInspector('lesson', ${JSON.stringify(l).replace(/"/g, '&quot;')})">
                <div class="flex items-center justify-between gap-2 mb-1.5">
                  <div class="flex items-center gap-2">
                    <span class="tcc-card-time font-black text-xs text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-md">${l.start_time} - ${l.end_time}</span>
                    <span class="text-xs font-bold text-slate-500">${l.duration_minutes || 60} мин</span>
                  </div>
                  <span class="text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${isLive ? 'bg-amber-100 text-amber-700 animate-pulse' : 'bg-slate-100 text-slate-600'}">
                    ${isLive ? 'Идёт сейчас' : l.status === 'completed' ? 'Проведён' : 'Запланирован'}
                  </span>
                </div>
                <div class="font-black text-slate-900 text-sm mb-1">${escapeHtml(l.student_name || 'Ученик')}</div>
                <div class="text-xs text-slate-600 line-clamp-2 mb-3">${escapeHtml(l.topic || subject)}</div>
                <div class="flex items-center justify-between pt-2 border-t border-slate-100">
                  <span class="text-xs font-bold text-indigo-600">${escapeHtml(subject)}</span>
                  <button class="px-3 py-1.5 rounded-xl bg-indigo-600 text-white font-bold text-xs flex items-center gap-1 shadow-sm" onclick="event.stopPropagation(); window.open('${l.room_url || '/room/' + l.id}', '_blank')">
                    <i class="ph-bold ph-broadcast"></i> Войти
                  </button>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    gridBody.innerHTML = ribbonHtml + agendaHtml;
  }

  function renderWeekHeaders() {
    const container = document.getElementById('tcc-days-header-row');
    if (!container) return;

    const hwItems = state.data.teacher_homework_items || [];
    let html = `<div class="tcc-tz-header-cell">Время</div>`;

    state.weekdays.forEach((day, index) => {
      const isToday = day.is_today;
      const dayLessons = getFilteredLessons().filter(l => l.start_date === day.iso);
      const totalHours = (dayLessons.reduce((acc, l) => acc + (l.duration_minutes || 60), 0) / 60).toFixed(1).replace('.0', '');

      // Hybrid Homework Layer pills
      let hwHtml = '';
      if (state.layers.homework) {
        const dayHw = hwItems.filter(h => h.deadline_date === day.iso);
        dayHw.slice(0, 2).forEach(h => {
          const isReview = h.status === 'SUBMITTED' || h.status === 'NEEDS_MANUAL_REVIEW';
          const isDone = h.status === 'GRADED' || h.status === 'ACCEPTED';
          const cls = isReview ? 'status-review' : isDone ? 'status-accepted' : 'status-assigned';
          const label = isReview ? 'ДЗ: сдали' : isDone ? 'ДЗ: принято' : 'ДЗ: срок';
          hwHtml += `
            <div class="tcc-hw-pill ${cls}" title="${escapeHtml(h.title)} (${escapeHtml(h.student_name)})" onclick="window.TCC.openHomework('${h.url}')">
              <i class="ph-bold ph-file-text text-[10px]"></i>
              <span class="truncate">${label}</span>
            </div>
          `;
        });
      }

      html += `
        <div class="tcc-day-header-cell ${isToday ? 'is-today' : ''}" data-day-iso="${day.iso}">
          <div class="tcc-day-meta">
            <span class="tcc-day-name">${day.short_name || day.name}</span>
            <span class="tcc-day-number">${day.date}</span>
          </div>
          <div class="tcc-day-stats-pill">${dayLessons.length} ур • ${totalHours}ч</div>
          ${state.layers.homework ? `<div class="tcc-hw-track">${hwHtml}</div>` : ''}
        </div>
      `;
    });

    container.innerHTML = html;
  }

  function renderWeekBody() {
    const gridBody = document.getElementById('tcc-grid-body');
    if (!gridBody) return;

    const startHour = 7;
    const endHour = 23;
    const hourHeight = state.density === 'compact' ? 48 : 64;

    // 1. Time gutter
    let gutterHtml = '<div class="tcc-time-gutter" id="tcc-time-gutter">';
    for (let h = startHour; h <= endHour; h++) {
      const timeStr = `${h < 10 ? '0' + h : h}:00`;
      gutterHtml += `<div class="tcc-time-cell">${timeStr}</div>`;
    }
    gutterHtml += '</div>';

    // 2. Day columns with background slot cells
    let columnsHtml = '';
    for (let dayIdx = 0; dayIdx < 7; dayIdx++) {
      const day = state.weekdays[dayIdx];
      const dayIso = day ? day.iso : '';
      const isToday = day ? day.is_today : false;

      columnsHtml += `
        <div class="tcc-day-column ${isToday ? 'is-today-col' : ''}" 
             data-day-index="${dayIdx}" 
             data-day-iso="${dayIso}" 
             id="tcc-day-col-${dayIdx}">
      `;

      for (let h = startHour; h <= endHour; h++) {
        columnsHtml += `
          <div class="tcc-slot-cell ${isToday ? 'is-today-col' : ''}" 
               data-day-index="${dayIdx}" 
               data-day-iso="${dayIso}" 
               data-hour="${h}"
               onmousedown="window.TCC.startSlotSelection(event, ${dayIdx}, '${dayIso}', ${h})">
          </div>
        `;
      }

      columnsHtml += '</div>';
    }

    gridBody.innerHTML = gutterHtml + columnsHtml;

    // 3. Render lesson cards inside columns
    renderWeekLessons(startHour, hourHeight);

    // 4. Auto-scroll on initial load
    if (!state.hasScrolledToActiveHours) {
      const scrollEl = document.getElementById('tcc-grid-scroll');
      if (scrollEl) {
        let scrollTargetY = 96;
        const filtered = getFilteredLessons();
        if (filtered.length > 0) {
          const earliestHour = Math.min(...filtered.map(l => parseInt(l.start_time.split(':')[0], 10)));
          if (earliestHour >= startHour) {
            scrollTargetY = Math.max(0, (earliestHour - startHour) * hourHeight - 20);
          }
        }
        scrollEl.scrollTop = scrollTargetY;
        state.hasScrolledToActiveHours = true;
      }
    }
  }

  function renderWeekLessons(startHour, hourHeight) {
    const filtered = getFilteredLessons();

    state.weekdays.forEach((day, dayIdx) => {
      const colEl = document.getElementById(`tcc-day-col-${dayIdx}`);
      if (!colEl) return;

      // Remove previous cards from this column
      colEl.querySelectorAll('.tcc-lesson-card').forEach(c => c.remove());

      const dayLessons = filtered.filter(l => l.start_date === day.iso);
      dayLessons.sort((a, b) => a.start_time.localeCompare(b.start_time));

      dayLessons.forEach((l, idx) => {
        const [lh, lm] = l.start_time.split(':').map(Number);
        const startMins = lh * 60 + lm;
        const dur = l.duration_minutes || 60;
        const endMins = startMins + dur;

        // Check if overlaps with any other lesson on this day
        const overlapping = dayLessons.filter((other, oIdx) => {
          if (oIdx === idx) return false;
          const [oh, om] = other.start_time.split(':').map(Number);
          const oStart = oh * 60 + om;
          const oEnd = oStart + (other.duration_minutes || 60);
          return (startMins < oEnd && endMins > oStart);
        });

        const topPx = (lh - startHour) * hourHeight + (lm / 60) * hourHeight;
        const heightPx = Math.max(28, (dur / 60) * hourHeight - 2);

        // Subject styling
        const sub = (l.subject || '').toLowerCase();
        let colorClass = 'tcc-card-indigo';
        if (sub.includes('мат')) colorClass = 'tcc-card-sky';
        else if (sub.includes('физ')) colorClass = 'tcc-card-emerald';
        else if (sub.includes('прог') || sub.includes('level')) colorClass = 'tcc-card-amber';

        const isLive = l.status === 'in_progress';
        const isCancelled = l.status === 'cancelled' || l.status === 'canceled';
        const isRecurring = l.is_recurring || Boolean(l.recurring_slot_id);

        const card = document.createElement('div');
        card.className = `tcc-lesson-card ${colorClass} ${isLive ? 'status-in_progress' : ''} ${isCancelled ? 'status-cancelled' : ''} ${state.selectedLesson && state.selectedLesson.lesson_id === l.lesson_id ? 'is-selected' : ''}`;
        card.id = `lesson-card-${l.lesson_id}`;
        card.style.top = `${topPx}px`;
        card.style.height = `${heightPx}px`;

        if (overlapping.length > 0) {
          const isSecond = idx > dayLessons.indexOf(overlapping[0]);
          card.style.width = 'calc(50% - 4px)';
          card.style.left = isSecond ? 'calc(50% + 2px)' : '2px';
        } else {
          card.style.width = 'calc(100% - 6px)';
          card.style.left = '3px';
        }

        // Calculate end time
        const endH = Math.floor(endMins / 60);
        const endM = endMins % 60;
        const endTimeStr = `${endH < 10 ? '0' + endH : endH}:${endM < 10 ? '0' + endM : endM}`;

        card.innerHTML = `
          <div class="tcc-card-time-row">
            <span class="tcc-card-time-badge">${l.start_time}${heightPx >= 44 ? ' — ' + endTimeStr : ''}</span>
            <span class="tcc-card-duration">${dur}м</span>
          </div>
          <div class="tcc-card-student">${escapeHtml(l.student_name)}</div>
          ${heightPx >= 52 ? `<div class="tcc-card-topic">${escapeHtml(l.topic || l.subject || 'Занятие')}</div>` : ''}
          <div class="tcc-card-badges">
            ${isRecurring ? '<i class="ph-bold ph-repeat text-indigo-600 text-[10px]" title="Регулярный урок"></i>' : ''}
            ${l.is_test ? '<span class="tcc-card-tag text-amber-700 bg-amber-50">Тест</span>' : ''}
            ${isLive ? '<span class="tcc-card-tag text-rose-700 bg-rose-50 animate-pulse">Идёт</span>' : ''}
          </div>
          <div class="tcc-resize-handle" title="Потяните для изменения длительности" onmousedown="window.TCC.startResize(event, ${l.lesson_id})"></div>
        `;

        // Click to inspect
        card.addEventListener('click', (e) => {
          if (e.target.classList.contains('tcc-resize-handle')) return;
          openInspector('lesson', l);
        });

        // Right click context menu
        card.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          showContextMenu(e, l);
        });

        // Drag to reschedule
        card.addEventListener('mousedown', (e) => {
          if (e.target.classList.contains('tcc-resize-handle')) return;
          if (e.button === 0) startDrag(e, l);
        });

        colEl.appendChild(card);
      });
    });
  }

  // ==========================================================================
  // VIEW 2: DAY VIEW
  // ==========================================================================
  function renderDayView() {
    const dayWrap = document.getElementById('tcc-day-view');
    if (!dayWrap) return;

    const lessons = getFilteredLessons().filter(l => l.start_date === state.selectedDate);
    lessons.sort((a, b) => a.start_time.localeCompare(b.start_time));

    let html = `
      <div class="max-w-4xl mx-auto w-full">
        <div class="flex items-center justify-between mb-6">
          <div>
            <h2 class="text-2xl font-black text-slate-900 font-display">Расписание дня</h2>
            <div class="text-xs font-bold text-slate-500 mt-1">${lessons.length} занятий запланировано</div>
          </div>
          <button onclick="window.TCC.openInspector('composer')" class="tcc-btn-primary">+ Запланировать урок</button>
        </div>
    `;

    if (lessons.length === 0) {
      html += `
        <div class="p-12 text-center bg-slate-50 rounded-3xl border-2 border-dashed border-slate-200">
          <i class="ph-duotone ph-calendar-blank text-5xl text-slate-300 block mb-3"></i>
          <h3 class="text-base font-black text-slate-700">На этот день уроков нет</h3>
          <p class="text-xs text-slate-500 mt-1 max-w-sm mx-auto">Отличный момент, чтобы назначить новое занятие или отдохнуть!</p>
          <button onclick="window.TCC.openInspector('composer')" class="mt-4 px-4 py-2 bg-indigo-600 text-white font-extrabold text-xs rounded-xl shadow-xs hover:bg-indigo-500 transition cursor-pointer">Создать урок</button>
        </div>
      `;
    } else {
      html += '<div class="flex flex-col gap-4">';
      lessons.forEach(l => {
        const isLive = l.status === 'in_progress';
        html += `
          <div class="tcc-day-timeline-card ${isLive ? 'border-amber-400 bg-amber-50/20' : ''}">
            <div class="flex flex-col items-center justify-center pr-4 border-r-2 border-slate-100 min-w-[90px]">
              <span class="text-xl font-black text-slate-900">${l.start_time}</span>
              <span class="text-[11px] font-bold text-slate-400">${l.duration_minutes || 60} мин</span>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xs font-black px-2 py-0.5 rounded-lg bg-indigo-50 text-indigo-700">${escapeHtml(l.subject || 'Информатика')}</span>
                ${isLive ? '<span class="text-xs font-black px-2 py-0.5 rounded-lg bg-rose-50 text-rose-700 animate-pulse">Идёт урок</span>' : ''}
                ${l.is_recurring ? '<span class="text-xs font-bold text-slate-400 flex items-center gap-1"><i class="ph-bold ph-repeat"></i> Серия</span>' : ''}
              </div>
              <h4 class="text-base font-black text-slate-900 truncate">${escapeHtml(l.student_name)}</h4>
              <p class="text-xs text-slate-600 mt-1">${escapeHtml(l.topic || 'Разбор типовых задач')}</p>
            </div>
            <div class="flex items-center gap-2">
              <a href="${l.room_url}" target="_blank" class="tcc-btn-primary">
                <i class="ph-bold ph-broadcast"></i>
                <span>Войти в урок</span>
              </a>
              <button onclick="window.TCC.openInspector('lesson', ${JSON.stringify(l).replace(/"/g, '&quot;')})" class="w-9 h-9 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 flex items-center justify-center text-slate-600 transition cursor-pointer">
                <i class="ph-bold ph-sliders-horizontal"></i>
              </button>
            </div>
          </div>
        `;
      });
      html += '</div>';
    }

    html += `</div>`;
    dayWrap.innerHTML = html;
  }

  // ==========================================================================
  // VIEW 3: MONTH VIEW
  // ==========================================================================
  function renderMonthView() {
    const monthWrap = document.getElementById('tcc-month-view');
    if (!monthWrap) return;

    let html = `
      <div class="tcc-month-days-header">
        <div>ПОНЕДЕЛЬНИК</div>
        <div>ВТОРНИК</div>
        <div>СРЕДА</div>
        <div>ЧЕТВЕРГ</div>
        <div>ПЯТНИЦА</div>
        <div>СУББОТА</div>
        <div>ВОСКРЕСЕНЬЕ</div>
      </div>
      <div class="tcc-month-grid">
    `;

    // Render cells from state.weekdays as representative days
    state.weekdays.forEach(day => {
      const dayLessons = getFilteredLessons().filter(l => l.start_date === day.iso);
      html += `
        <div class="tcc-month-cell ${day.is_today ? 'is-today' : ''}" onclick="window.TCC.selectDateAndDrill('${day.iso}')">
          <div class="flex items-center justify-between">
            <span class="text-xs font-black ${day.is_today ? 'text-indigo-600' : 'text-slate-800'}">${day.date}</span>
            ${dayLessons.length > 0 ? `<span class="text-[10px] font-bold text-slate-400">${dayLessons.length} ур</span>` : ''}
          </div>
          <div class="flex flex-col gap-1 mt-1">
      `;
      dayLessons.slice(0, 3).forEach(l => {
        html += `
          <div class="tcc-month-chip bg-indigo-50 text-indigo-700 border border-indigo-200">
            ${l.start_time} ${escapeHtml(l.student_name)}
          </div>
        `;
      });
      if (dayLessons.length > 3) {
        html += `<span class="text-[9px] font-bold text-slate-400">+ ещё ${dayLessons.length - 3}</span>`;
      }
      html += `</div></div>`;
    });

    html += `</div>`;
    monthWrap.innerHTML = html;
  }

  // ==========================================================================
  // VIEW 4: STREAM VIEW (AGENDA)
  // ==========================================================================
  function renderStreamView() {
    const streamWrap = document.getElementById('tcc-stream-view');
    if (!streamWrap) return;

    const lessons = getFilteredLessons();
    // Group lessons by date
    const groups = {};
    lessons.forEach(l => {
      if (!groups[l.start_date]) groups[l.start_date] = [];
      groups[l.start_date].push(l);
    });

    const dates = Object.keys(groups).sort();

    let html = '<div class="max-w-4xl mx-auto w-full flex flex-col gap-6">';
    if (dates.length === 0) {
      html += `
        <div class="p-12 text-center bg-slate-50 rounded-3xl border-2 border-dashed border-slate-200">
          <i class="ph-duotone ph-list-bullets text-5xl text-slate-300 block mb-3"></i>
          <h3 class="text-base font-black text-slate-700">Лента занятий пуста</h3>
          <p class="text-xs text-slate-500 mt-1">В выбранном периоде нет уроков.</p>
        </div>
      `;
    } else {
      dates.forEach(dateStr => {
        const dayLessons = groups[dateStr];
        dayLessons.sort((a, b) => a.start_time.localeCompare(b.start_time));
        const dObj = new Date(dateStr);
        const dayName = RU_WD_NAMES_FULL[dObj.getDay() === 0 ? 6 : dObj.getDay() - 1];

        html += `
          <div class="tcc-stream-day-group">
            <h3 class="tcc-stream-day-title">
              <span class="w-2.5 h-2.5 rounded-full bg-indigo-500"></span>
              <span>${dayName}, ${dObj.getDate()} ${RU_MONTHS[dObj.getMonth()]}</span>
            </h3>
            <div class="flex flex-col gap-2">
        `;

        dayLessons.forEach(l => {
          html += `
            <div class="tcc-stream-card">
              <div class="flex items-center gap-3">
                <div class="text-center min-w-[54px] py-1 px-2 rounded-xl bg-slate-50 border border-slate-200">
                  <div class="text-xs font-black text-slate-800">${l.start_time}</div>
                  <div class="text-[9px] font-bold text-slate-400">${l.duration_minutes || 60}м</div>
                </div>
                <div>
                  <div class="text-sm font-black text-slate-900">${escapeHtml(l.student_name)}</div>
                  <div class="text-xs text-slate-500 font-medium">${escapeHtml(l.subject || 'Информатика')} • ${escapeHtml(l.topic || 'Занятие')}</div>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <a href="${l.room_url}" target="_blank" class="tcc-btn-primary">
                  <i class="ph-bold ph-broadcast"></i>
                  <span>Войти</span>
                </a>
              </div>
            </div>
          `;
        });

        html += `</div></div>`;
      });
    }

    html += '</div>';
    streamWrap.innerHTML = html;
  }

  // ==========================================================================
  // VIEW 5: DAY FOCUS MODE
  // ==========================================================================
  function renderFocusView() {
    const focusWrap = document.getElementById('tcc-focus-view');
    if (!focusWrap) return;

    const todayLessons = getFilteredLessons().filter(l => l.start_date === state.data.today_iso);
    todayLessons.sort((a, b) => a.start_time.localeCompare(b.start_time));

    const nextLesson = todayLessons.find(l => l.status === 'in_progress' || l.status === 'planned');

    let html = `
      <div class="max-w-4xl mx-auto w-full flex flex-col gap-6">
        <div class="tcc-focus-hero-card">
          <div>
            <div class="text-xs font-black uppercase tracking-widest text-indigo-200 mb-1">ФОКУС-РЕЖИМ ПРЕПОДАВАТЕЛЯ</div>
            <h2 class="text-3xl font-black font-display tracking-tight">
              ${nextLesson ? (nextLesson.status === 'in_progress' ? 'Урок идёт прямо сейчас!' : 'Следующее занятие:') : 'Все уроки на сегодня завершены!'}
            </h2>
            ${nextLesson ? `
              <p class="text-sm text-indigo-100 mt-2 font-medium">
                ${escapeHtml(nextLesson.student_name)} • ${escapeHtml(nextLesson.subject)} • Начало в ${nextLesson.start_time}
              </p>
            ` : ''}
          </div>
          ${nextLesson ? `
            <a href="${nextLesson.room_url}" target="_blank" class="px-6 py-3 rounded-2xl bg-white text-indigo-700 font-black text-sm shadow-xl hover:bg-indigo-50 transition active:scale-95 flex items-center gap-2">
              <i class="ph-bold ph-broadcast text-lg"></i>
              <span>Открыть интерактивную комнату</span>
            </a>
          ` : ''}
        </div>

        <div>
          <h3 class="text-lg font-black text-slate-900 mb-3 font-display">Таймлайн сегодняшнего дня</h3>
          <div class="flex flex-col gap-3">
    `;

    if (todayLessons.length === 0) {
      html += `<div class="p-8 text-center bg-white rounded-2xl border border-slate-200 text-slate-500 font-bold text-xs">Сегодня нет запланированных уроков</div>`;
    } else {
      todayLessons.forEach(l => {
        html += `
          <div class="p-4 rounded-2xl border-2 border-slate-200 bg-white shadow-xs flex items-center justify-between">
            <div class="flex items-center gap-4">
              <div class="text-lg font-black text-slate-800">${l.start_time}</div>
              <div>
                <div class="text-sm font-black text-slate-900">${escapeHtml(l.student_name)}</div>
                <div class="text-xs text-slate-500 font-medium">${escapeHtml(l.topic || l.subject)}</div>
              </div>
            </div>
            <a href="${l.room_url}" target="_blank" class="tcc-btn-primary">
              <i class="ph-bold ph-broadcast"></i>
              <span>В урок</span>
            </a>
          </div>
        `;
      });
    }

    html += `</div></div></div>`;
    focusWrap.innerHTML = html;
  }

  // ==========================================================================
  // ZONE C: SMART CONTEXT INSPECTOR
  // ==========================================================================
  function renderInspector() {
    const titleEl = document.getElementById('tcc-inspector-title');
    const bodyEl = document.getElementById('tcc-inspector-body');
    if (!titleEl || !bodyEl) return;

    if (state.inspectorMode === 'overview') {
      titleEl.innerHTML = '<i class="ph-bold ph-compass text-indigo-600"></i> <span>Центр управления</span>';
      renderInspectorOverview(bodyEl);
    } else if (state.inspectorMode === 'lesson') {
      titleEl.innerHTML = '<i class="ph-bold ph-chalkboard-teacher text-indigo-600"></i> <span>Карточка урока</span>';
      renderInspectorLesson(bodyEl);
    } else if (state.inspectorMode === 'student') {
      titleEl.innerHTML = '<i class="ph-bold ph-user text-indigo-600"></i> <span>Контекст ученика</span>';
      renderInspectorStudent(bodyEl);
    } else if (state.inspectorMode === 'find_time') {
      titleEl.innerHTML = '<i class="ph-bold ph-sparkle text-indigo-600"></i> <span>Подбор свободного времени</span>';
      renderInspectorFindTime(bodyEl);
    } else if (state.inspectorMode === 'composer') {
      titleEl.innerHTML = '<i class="ph-bold ph-plus-circle text-indigo-600"></i> <span>Новый урок</span>';
      renderInspectorComposer(bodyEl);
    }
  }

  function renderInspectorOverview(el) {
    const attentionItems = state.data.attention_items || [];

    // Deduplicate attention signals
    const seen = new Set();
    const dedupedAttention = attentionItems.filter(item => {
      const key = `${item.title}_${item.subtitle || ''}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    // Find next upcoming lesson
    const now = new Date();
    const todayStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    const plannedLessons = (state.lessons || []).filter(l => l.status !== 'cancelled');
    plannedLessons.sort((a, b) => (a.start_date + a.start_time).localeCompare(b.start_date + b.start_time));
    const nextLesson = plannedLessons.find(l => l.start_date >= todayStr) || plannedLessons[0];

    let html = '';

    // Hero Widget: Next Upcoming Lesson
    if (nextLesson) {
      const isLive = nextLesson.status === 'in_progress';
      html += `
        <div class="tcc-widget-card border-indigo-100 bg-gradient-to-br from-indigo-50/60 to-white shadow-xs">
          <div class="flex items-center justify-between mb-2">
            <span class="text-[10px] font-black uppercase tracking-wider ${isLive ? 'bg-rose-600 animate-pulse text-white' : 'bg-indigo-600 text-white'} px-2 py-0.5 rounded-full">
              ${isLive ? 'Урок идёт прямо сейчас' : 'Ближайший урок'}
            </span>
            <span class="text-xs font-bold text-slate-500">${nextLesson.start_date.split('-').slice(1).reverse().join('.')} • ${nextLesson.start_time}</span>
          </div>
          <div class="text-sm font-black text-slate-900 truncate">${escapeHtml(nextLesson.student_name)}</div>
          <div class="text-xs text-slate-600 font-medium truncate mb-3">${escapeHtml(nextLesson.topic || nextLesson.subject || 'Занятие')}</div>
          <div class="flex items-center gap-2">
            <a href="${nextLesson.room_url}" target="_blank" class="flex-1 py-1.5 px-3 bg-indigo-600 hover:bg-indigo-700 text-white font-extrabold text-xs rounded-xl flex items-center justify-center gap-1.5 shadow-xs transition">
              <i class="ph-bold ph-broadcast"></i>
              <span>Войти в комнату</span>
            </a>
            <button onclick="window.TCC.openInspector('lesson', ${JSON.stringify(nextLesson).replace(/"/g, '&quot;')})" class="py-1.5 px-3 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl transition cursor-pointer">
              Детали
            </button>
          </div>
        </div>
      `;
    }

    // Attention System (Grouped & Deduplicated)
    html += `
      <div class="tcc-widget-card">
        <div class="tcc-widget-title">
          <span>Требует внимания</span>
          <span class="text-[10px] font-black bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full">${dedupedAttention.length}</span>
        </div>
        <div class="flex flex-col gap-2">
    `;

    if (dedupedAttention.length === 0) {
      html += `<div class="text-xs text-slate-400 py-2 italic text-center">Все задания проверены, уроки готовы!</div>`;
    } else {
      dedupedAttention.slice(0, 4).forEach(item => {
        html += `
          <div class="tcc-attention-item urgency-${item.severity || 'info'}" onclick="window.open('${item.url}', '_blank')">
            <i class="ph-bold ${item.icon || 'ph-bell'} text-base text-amber-600 shrink-0"></i>
            <div class="flex-1 min-w-0">
              <div class="text-xs font-black text-slate-800 truncate">${escapeHtml(item.title)}</div>
              <div class="text-[11px] text-slate-500 truncate">${escapeHtml(item.subtitle || '')}</div>
            </div>
            <span class="text-[9px] font-black px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 shrink-0">${item.badge}</span>
          </div>
        `;
      });
    }

    html += `
        </div>
      </div>

      <!-- Quick Actions -->
      <div class="tcc-widget-card">
        <div class="tcc-widget-title">Быстрые действия</div>
        <div class="grid grid-cols-2 gap-2">
          <button onclick="window.TCC.openInspector('find_time')" class="p-3 rounded-xl border border-indigo-200 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 font-extrabold text-xs flex flex-col items-center gap-1.5 transition cursor-pointer">
            <i class="ph-bold ph-sparkle text-lg"></i>
            <span>Найти окно</span>
          </button>
          <button onclick="window.TCC.openInspector('composer')" class="p-3 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-extrabold text-xs flex flex-col items-center gap-1.5 transition cursor-pointer">
            <i class="ph-bold ph-plus text-lg"></i>
            <span>Создать урок</span>
          </button>
        </div>
      </div>

      <!-- Working Hours & Exceptions Shortcut -->
      <div class="tcc-widget-card">
        <div class="tcc-widget-title">Рабочий график</div>
        <p class="text-xs text-slate-600">Настройте постоянные рабочие часы по дням недели и праздничные исключения.</p>
        <button onclick="window.openTeacherAvailabilityModal()" class="w-full py-2 bg-white border border-slate-200 hover:border-slate-300 rounded-xl text-xs font-black text-slate-700 shadow-xs transition cursor-pointer">
          <i class="ph-bold ph-calendar-check mr-1"></i> Настроить доступность
        </button>
      </div>
    `;

    el.innerHTML = html;
  }

  function renderInspectorLesson(el) {
    const l = state.selectedLesson;
    if (!l) {
      el.innerHTML = '<div class="text-xs text-slate-400 py-6 text-center">Выберите урок в календаре для просмотра деталей</div>';
      return;
    }

    const isRecurring = l.is_recurring || Boolean(l.recurring_slot_id);
    const isLive = l.status === 'in_progress';

    el.innerHTML = `
      <div class="tcc-widget-card">
        <div class="flex items-center justify-between">
          <span class="text-xs font-black px-2 py-0.5 rounded-lg bg-indigo-50 text-indigo-700">${escapeHtml(l.subject || 'Информатика')}</span>
          <span class="text-xs font-bold text-slate-500">${l.start_date} • ${l.start_time} (${l.duration_minutes || 60} мин)</span>
        </div>
        <h3 class="text-lg font-black text-slate-900 mt-1">${escapeHtml(l.student_name)}</h3>
        <p class="text-xs text-slate-600">${escapeHtml(l.topic || 'Занятие по расписанию')}</p>
        ${isRecurring ? '<div class="text-[11px] font-bold text-indigo-600 flex items-center gap-1 mt-1"><i class="ph-bold ph-repeat"></i> Регулярное занятие</div>' : ''}
      </div>

      <!-- Action buttons -->
      <div class="flex flex-col gap-2">
        <a href="${l.room_url}" target="_blank" class="tcc-btn-primary justify-center h-10 text-sm">
          <i class="ph-bold ph-broadcast text-lg"></i>
          <span>Войти в интерактивную комнату</span>
        </a>
        <button onclick="navigator.clipboard.writeText(window.location.origin + '${l.room_url}').then(() => alert('Ссылка скопирована!'))" class="py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 font-extrabold text-xs rounded-xl transition cursor-pointer">
          <i class="ph-bold ph-copy mr-1"></i> Скопировать ссылку на комнату
        </button>
      </div>

      <!-- Status selector -->
      <div class="tcc-widget-card">
        <div class="tcc-widget-title">Статус урока</div>
        <div class="grid grid-cols-2 gap-2">
          <button onclick="window.TCC.changeLessonStatus(${l.lesson_id}, 'planned')" class="py-1.5 px-2 rounded-xl text-xs font-bold border ${l.status === 'planned' ? 'bg-indigo-50 border-indigo-300 text-indigo-700' : 'bg-white border-slate-200 text-slate-600'} cursor-pointer">Запланирован</button>
          <button onclick="window.TCC.changeLessonStatus(${l.lesson_id}, 'in_progress')" class="py-1.5 px-2 rounded-xl text-xs font-bold border ${l.status === 'in_progress' ? 'bg-amber-50 border-amber-300 text-amber-700' : 'bg-white border-slate-200 text-slate-600'} cursor-pointer">Идёт</button>
          <button onclick="window.TCC.changeLessonStatus(${l.lesson_id}, 'completed')" class="py-1.5 px-2 rounded-xl text-xs font-bold border ${l.status === 'completed' ? 'bg-emerald-50 border-emerald-300 text-emerald-700' : 'bg-white border-slate-200 text-slate-600'} cursor-pointer">Проведён</button>
          <button onclick="window.TCC.changeLessonStatus(${l.lesson_id}, 'cancelled')" class="py-1.5 px-2 rounded-xl text-xs font-bold border ${l.status === 'cancelled' ? 'bg-rose-50 border-rose-300 text-rose-700' : 'bg-white border-slate-200 text-slate-600'} cursor-pointer">Отменён</button>
        </div>
      </div>

      <!-- Notes -->
      <div class="tcc-widget-card">
        <div class="tcc-widget-title">Заметки к уроку</div>
        <textarea id="tcc-lesson-notes-input" rows="3" class="w-full bg-white border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-indigo-500 font-medium">${escapeHtml(l.notes || '')}</textarea>
        <button onclick="window.TCC.saveLessonNotes(${l.lesson_id})" class="py-1.5 px-3 bg-slate-800 text-white rounded-xl text-xs font-extrabold hover:bg-slate-700 transition cursor-pointer self-end">Сохранить заметку</button>
      </div>

      <!-- Danger Zone -->
      <div class="flex items-center justify-between pt-2">
        <button onclick="window.TCC.promptRescheduleLesson(${l.lesson_id})" class="text-xs font-bold text-indigo-600 hover:underline cursor-pointer">Перенести...</button>
        <button onclick="window.TCC.cancelLesson(${l.lesson_id})" class="text-xs font-bold text-rose-600 hover:underline cursor-pointer">Отменить урок</button>
      </div>
    `;
  }

  function renderInspectorFindTime(el) {
    el.innerHTML = `
      <div class="tcc-widget-card">
        <div class="tcc-widget-title">Параметры подбора</div>
        <div class="flex flex-col gap-2">
          <label class="text-xs font-bold text-slate-600">Ученик:</label>
          <select id="tcc-finder-student-select" class="bg-white border border-slate-200 rounded-xl p-2 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500 cursor-pointer">
            <option value="">Любой ученик (общее окно)</option>
            ${state.accessibleStudents.map(s => `<option value="${s.student_id}">${escapeHtml(s.name)}</option>`).join('')}
          </select>

          <label class="text-xs font-bold text-slate-600 mt-2">Длительность:</label>
          <div class="grid grid-cols-3 gap-2">
            <button type="button" data-dur="45" onclick="window.TCC.selectFinderDuration(45)" class="finder-dur-btn py-1.5 rounded-xl border border-slate-200 bg-white text-xs font-black text-slate-700 cursor-pointer">45 мин</button>
            <button type="button" data-dur="60" onclick="window.TCC.selectFinderDuration(60)" class="finder-dur-btn py-1.5 rounded-xl border-2 border-indigo-500 bg-indigo-50 text-xs font-black text-indigo-700 cursor-pointer">60 мин</button>
            <button type="button" data-dur="90" onclick="window.TCC.selectFinderDuration(90)" class="finder-dur-btn py-1.5 rounded-xl border border-slate-200 bg-white text-xs font-black text-slate-700 cursor-pointer">90 мин</button>
          </div>
        </div>
        <button onclick="window.TCC.executeFindTime()" class="mt-3 py-2 bg-indigo-600 text-white rounded-xl text-xs font-black hover:bg-indigo-500 transition cursor-pointer">
          <i class="ph-bold ph-sparkle mr-1"></i> Найти свободные слоты
        </button>
      </div>

      <div id="tcc-finder-results" class="flex flex-col gap-2">
        <div class="text-xs text-slate-400 py-4 text-center italic">Нажмите «Найти», чтобы рассчитать свободные окна</div>
      </div>
    `;
  }

  function renderInspectorComposer(el, prefill = {}) {
    const defaultDate = prefill.date || state.selectedDate || new Date().toISOString().split('T')[0];
    const defaultTime = prefill.time || '14:00';
    const defaultDuration = prefill.duration || 60;

    el.innerHTML = `
      <form id="tcc-inline-composer-form" onsubmit="window.TCC.submitComposer(event)" class="flex flex-col gap-3">
        <div class="tcc-widget-card">
          <div class="tcc-widget-title">Создание урока</div>
          
          <div class="flex flex-col gap-2">
            <label class="text-xs font-bold text-slate-600">Ученик *</label>
            <select name="student_id" required class="bg-white border border-slate-200 rounded-xl p-2 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500 cursor-pointer">
              <option value="">Выберите ученика...</option>
              ${state.accessibleStudents.map(s => `<option value="${s.student_id}">${escapeHtml(s.name)}</option>`).join('')}
            </select>

            <label class="text-xs font-bold text-slate-600 mt-1">Предмет</label>
            <select name="subject" class="bg-white border border-slate-200 rounded-xl p-2 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500 cursor-pointer">
              <option value="Информатика">Информатика</option>
              <option value="Математика">Математика</option>
              <option value="Физика">Физика</option>
              <option value="Программирование">Программирование</option>
            </select>

            <div class="grid grid-cols-2 gap-2 mt-1">
              <div>
                <label class="text-xs font-bold text-slate-600">Дата *</label>
                <input type="date" name="lesson_date" value="${defaultDate}" required class="w-full bg-white border border-slate-200 rounded-xl p-2 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500">
              </div>
              <div>
                <label class="text-xs font-bold text-slate-600">Время *</label>
                <input type="time" name="lesson_time" value="${defaultTime}" required class="w-full bg-white border border-slate-200 rounded-xl p-2 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500">
              </div>
            </div>

            <div class="grid grid-cols-2 gap-2 mt-1">
              <div>
                <label class="text-xs font-bold text-slate-600">Длительность</label>
                <select name="duration" class="w-full bg-white border border-slate-200 rounded-xl p-2 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500">
                  <option value="45" ${defaultDuration === 45 ? 'selected' : ''}>45 минут</option>
                  <option value="60" ${defaultDuration === 60 ? 'selected' : ''}>60 минут</option>
                  <option value="90" ${defaultDuration === 90 ? 'selected' : ''}>90 минут</option>
                  <option value="120" ${defaultDuration === 120 ? 'selected' : ''}>120 минут</option>
                </select>
              </div>
              <div>
                <label class="text-xs font-bold text-slate-600">Тип урока</label>
                <select name="lesson_type" class="w-full bg-white border border-slate-200 rounded-xl p-2 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500">
                  <option value="regular">Индивидуальный</option>
                  <option value="test">Контрольная / Тест</option>
                  <option value="webinar">Вебинар</option>
                </select>
              </div>
            </div>

            <label class="text-xs font-bold text-slate-600 mt-1">Тема занятия</label>
            <input type="text" name="topic" placeholder="Например: Разбор задания №14" class="bg-white border border-slate-200 rounded-xl p-2 text-xs font-bold text-slate-800 outline-none focus:border-indigo-500">
          </div>
        </div>

        <button type="submit" class="tcc-btn-primary justify-center h-10 text-sm">
          <i class="ph-bold ph-plus text-base"></i>
          <span>Создать занятие</span>
        </button>
      </form>
    `;
  }

  // ==========================================================================
  // DIRECT MANIPULATION: DRAG-AND-DROP RESCHEDULE
  // ==========================================================================
  // DIRECT MANIPULATION: DRAG-AND-DROP RESCHEDULE & RESIZE
  // ==========================================================================
  function startDrag(e, lesson) {
    if (state.dragState || state.resizeState || state.pendingDrag) return;
    const card = document.getElementById(`lesson-card-${lesson.lesson_id}`);
    if (!card) return;
    const rect = card.getBoundingClientRect();
    state.pendingDrag = {
      lesson: lesson,
      startX: e.clientX,
      startY: e.clientY,
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
      cardRect: rect,
      cardEl: card,
    };
  }

  function handlePointerMove(e) {
    // 1. Dragging threshold check (5px)
    if (state.pendingDrag && !state.dragState) {
      const dist = Math.hypot(e.clientX - state.pendingDrag.startX, e.clientY - state.pendingDrag.startY);
      if (dist >= 5) {
        state.dragState = state.pendingDrag;
        state.pendingDrag = null;

        const sub = (state.dragState.lesson.subject || '').toLowerCase();
        let colorClass = 'tcc-card-indigo';
        if (sub.includes('мат')) colorClass = 'tcc-card-sky';
        else if (sub.includes('физ')) colorClass = 'tcc-card-emerald';
        else if (sub.includes('прог') || sub.includes('level')) colorClass = 'tcc-card-amber';

        const ghost = document.createElement('div');
        ghost.className = `tcc-drag-ghost ${colorClass}`;
        ghost.style.width = `${state.dragState.cardRect.width}px`;
        ghost.style.minHeight = `${state.dragState.cardRect.height}px`;
        ghost.innerHTML = `
          <div class="tcc-ghost-badge" id="tcc-ghost-badge">
            <i class="ph-bold ph-calendar"></i>
            <span id="tcc-ghost-text">Перенос урока...</span>
          </div>
          <div class="tcc-card-student font-black text-xs text-slate-900">${escapeHtml(state.dragState.lesson.student_name)}</div>
          <div class="tcc-card-topic text-[11px] truncate text-slate-600">${escapeHtml(state.dragState.lesson.topic || state.dragState.lesson.subject)}</div>
        `;
        document.body.appendChild(ghost);
        state.dragState.ghostEl = ghost;
        state.dragState.cardEl.style.opacity = '0.35';
      }
    }

    if (state.dragState && state.dragState.ghostEl) {
      const ghost = state.dragState.ghostEl;
      ghost.style.left = `${e.clientX - state.dragState.offsetX}px`;
      ghost.style.top = `${e.clientY - state.dragState.offsetY}px`;

      // Auto-scroll grid container when dragging near top/bottom edges
      const scrollEl = document.getElementById('tcc-grid-scroll');
      if (scrollEl) {
        const sRect = scrollEl.getBoundingClientRect();
        if (e.clientY < sRect.top + 60 && scrollEl.scrollTop > 0) {
          scrollEl.scrollTop -= 14;
        } else if (e.clientY > sRect.bottom - 60) {
          scrollEl.scrollTop += 14;
        }
      }

      // Slot detection
      ghost.style.pointerEvents = 'none';
      const elUnder = document.elementFromPoint(e.clientX, e.clientY);
      const slotCell = elUnder ? elUnder.closest('.tcc-slot-cell') : null;
      const dayCol = elUnder ? elUnder.closest('.tcc-day-column') : null;

      const badgeText = document.getElementById('tcc-ghost-text');
      if (slotCell || dayCol) {
        const targetDayIso = slotCell ? slotCell.getAttribute('data-day-iso') : dayCol.getAttribute('data-day-iso');
        let targetHour = slotCell ? parseInt(slotCell.getAttribute('data-hour'), 10) : 12;
        let targetMinute = 0;

        if (slotCell) {
          const slotRect = slotCell.getBoundingClientRect();
          if (e.clientY - slotRect.top >= slotRect.height / 2) {
            targetMinute = 30;
          }
        }

        const dur = state.dragState.lesson.duration_minutes || 60;
        const timeStr = `${targetHour < 10 ? '0' + targetHour : targetHour}:${targetMinute < 10 ? '0' + targetMinute : targetMinute}`;

        // Collision check
        const targetStartMins = targetHour * 60 + targetMinute;
        const targetEndMins = targetStartMins + dur;
        const collision = state.lessons.find(other => {
          if (other.lesson_id === state.dragState.lesson.lesson_id) return false;
          if (other.start_date !== targetDayIso) return false;
          if (other.status === 'cancelled') return false;
          const [oh, om] = other.start_time.split(':').map(Number);
          const oStart = oh * 60 + om;
          const oEnd = oStart + (other.duration_minutes || 60);
          return (targetStartMins < oEnd && targetEndMins > oStart);
        });

        state.dragState.dropTarget = {
          dayIso: targetDayIso,
          time: timeStr,
          hasCollision: Boolean(collision)
        };

        if (collision) {
          ghost.classList.remove('is-valid');
          ghost.classList.add('is-collision');
          if (badgeText) badgeText.textContent = `⚠ Конфликт: ${collision.student_name} (${collision.start_time})`;
        } else {
          ghost.classList.remove('is-collision');
          ghost.classList.add('is-valid');
          if (badgeText) badgeText.textContent = `${targetDayIso.split('-').slice(1).reverse().join('.')} • ${timeStr} (${dur}м)`;
        }
      } else {
        state.dragState.dropTarget = null;
        ghost.classList.remove('is-valid', 'is-collision');
        if (badgeText) badgeText.textContent = 'Перенесите на сетку календаря';
      }
    }

    // 2. Resizing card
    if (state.resizeState) {
      const dy = e.clientY - state.resizeState.startY;
      const hourHeight = state.density === 'compact' ? 48 : 64;
      const deltaMinutes = Math.round((dy / hourHeight) * 60 / 15) * 15;
      const newDur = Math.max(30, Math.min(180, state.resizeState.origDuration + deltaMinutes));
      state.resizeState.currentDuration = newDur;

      const card = document.getElementById(`lesson-card-${state.resizeState.lessonId}`);
      if (card) {
        card.style.height = `${Math.max(28, (newDur / 60) * hourHeight - 2)}px`;
        const durEl = card.querySelector('.tcc-card-duration');
        if (durEl) durEl.textContent = `${newDur}м`;
      }
    }
  }

  function handlePointerUp(e) {
    // 1. End Drag
    if (state.dragState) {
      const dropTarget = state.dragState.dropTarget;
      const lesson = state.dragState.lesson;
      const cardEl = state.dragState.cardEl;
      if (state.dragState.ghostEl) state.dragState.ghostEl.remove();
      if (cardEl) cardEl.style.opacity = '1';

      if (dropTarget && !dropTarget.hasCollision) {
        confirmAndReschedule(lesson, dropTarget.dayIso, dropTarget.time);
      } else if (dropTarget && dropTarget.hasCollision) {
        showToast('Выбранный интервал уже занят другим уроком', 'error');
      }
      state.dragState = null;
    }
    state.pendingDrag = null;

    // 2. End Resize
    if (state.resizeState) {
      const newDur = state.resizeState.currentDuration;
      const lessonId = state.resizeState.lessonId;
      state.resizeState = null;
      applyResize(lessonId, newDur);
    }
  }

  function startResize(e, lessonId) {
    e.stopPropagation();
    const lesson = state.lessons.find(l => l.lesson_id === lessonId);
    if (!lesson) return;

    state.resizeState = {
      lessonId: lessonId,
      startY: e.clientY,
      origDuration: lesson.duration_minutes || 60,
      currentDuration: lesson.duration_minutes || 60,
    };
  }

  async function applyResize(lessonId, newDuration) {
    try {
      const resp = await fetch(`/api/schedule/update_lesson/${lessonId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({ duration: newDuration })
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && (data.status === 'success' || data.success)) {
        const l = state.lessons.find(x => x.lesson_id === lessonId);
        if (l) l.duration_minutes = newDuration;
        showToast('Длительность урока обновлена', 'success');
      } else {
        showToast(data.error || 'Не удалось обновить длительность', 'error');
      }
    } catch (err) {
      showToast('Ошибка сети при изменении длительности', 'error');
    }
    renderAll();
  }

  async function confirmAndReschedule(lesson, targetDate, targetTime) {
    const isRecurring = lesson.is_recurring || Boolean(lesson.recurring_slot_id);

    if (isRecurring) {
      // Prompt modal for scope
      openScopeModal(lesson, targetDate, targetTime);
    } else {
      executeReschedule(lesson.lesson_id, targetDate, targetTime, 'single');
    }
  }

  function openScopeModal(lesson, targetDate, targetTime) {
    const modal = document.getElementById('tcc-scope-modal');
    if (!modal) {
      executeReschedule(lesson.lesson_id, targetDate, targetTime, 'single');
      return;
    }

    modal.classList.remove('is-hidden');
    document.getElementById('tcc-scope-btn-single').onclick = () => {
      modal.classList.add('is-hidden');
      executeReschedule(lesson.lesson_id, targetDate, targetTime, 'single');
    };
    document.getElementById('tcc-scope-btn-future').onclick = () => {
      modal.classList.add('is-hidden');
      executeReschedule(lesson.lesson_id, targetDate, targetTime, 'future');
    };
    document.getElementById('tcc-scope-btn-series').onclick = () => {
      modal.classList.add('is-hidden');
      executeReschedule(lesson.lesson_id, targetDate, targetTime, 'series');
    };
  }

  async function executeReschedule(lessonId, targetDate, targetTime, scope = 'single') {
    try {
      let endpoint = `/api/schedule/lesson/${lessonId}/reschedule`;
      let payload = {
        lesson_date: targetDate,
        lesson_time: targetTime,
        timezone: state.data.timezone || 'Europe/Moscow',
      };

      if (scope === 'series') {
        endpoint = `/api/schedule/recurring/update-series`;
        const l = state.lessons.find(x => x.lesson_id === lessonId);
        payload = {
          slot_id: l.recurring_slot_id,
          time_hhmm: targetTime,
        };
      }

      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(payload)
      });
      const data = await resp.json().catch(() => ({}));

      if (resp.ok && (data.status === 'success' || data.success)) {
        showToast('Урок успешно перенесён!', 'success');
        // Update local lesson state
        const l = state.lessons.find(x => x.lesson_id === lessonId);
        if (l) {
          l.start_date = targetDate;
          l.start_time = targetTime;
        }
        renderAll();
      } else {
        showToast(data.error || 'Ошибка при переносе урока', 'error');
        renderAll();
      }
    } catch (err) {
      showToast('Сетевая ошибка при переносе урока', 'error');
      renderAll();
    }
  }

  // ==========================================================================
  // COMMAND PALETTE
  // ==========================================================================
  function toggleCommandPalette() {
    const modal = document.getElementById('tcc-cmd-modal');
    if (!modal) return;

    if (modal.classList.contains('is-hidden')) {
      modal.classList.remove('is-hidden');
      const input = document.getElementById('tcc-cmd-input');
      if (input) {
        input.value = '';
        input.focus();
        renderCommandResults('');
      }
    } else {
      modal.classList.add('is-hidden');
    }
  }

  function renderCommandResults(query) {
    const container = document.getElementById('tcc-cmd-results');
    if (!container) return;

    const q = (query || '').toLowerCase().trim();

    const staticCommands = [
      { label: 'Вид: Неделя', icon: 'ph-calendar', action: () => switchView('week') },
      { label: 'Вид: День', icon: 'ph-calendar-check', action: () => switchView('day') },
      { label: 'Вид: Месяц', icon: 'ph-calendar-blank', action: () => switchView('month') },
      { label: 'Вид: Лента (Agenda)', icon: 'ph-list-bullets', action: () => switchView('stream') },
      { label: 'Вид: Фокус дня', icon: 'ph-lightning', action: () => switchView('focus') },
      { label: 'Создать новый урок', icon: 'ph-plus-circle', action: () => openInspector('composer') },
      { label: 'Найти свободное окно (Smart Finder)', icon: 'ph-sparkle', action: () => openInspector('find_time') },
      { label: 'Настроить рабочие часы и график', icon: 'ph-clock', action: () => window.openTeacherAvailabilityModal() },
      { label: 'Управление сериями уроков', icon: 'ph-repeat', action: () => toggleRail('series', true) },
      { label: 'Перейти к текущей неделе (Сегодня)', icon: 'ph-arrow-u-up-left', action: () => navigatePeriod(0, true) },
    ];

    let items = staticCommands.filter(c => c.label.toLowerCase().includes(q));

    // Also match accessible students
    state.accessibleStudents.forEach(st => {
      if (st.name && st.name.toLowerCase().includes(q)) {
        items.push({
          label: `Ученик: ${st.name}`,
          icon: 'ph-user',
          action: () => filterByStudent(st.student_id)
        });
      }
    });

    let html = '';
    items.slice(0, 8).forEach((item, idx) => {
      html += `
        <div class="tcc-cmd-item ${idx === 0 ? 'is-active' : ''}" onclick="window.TCC.runCommand(${idx})">
          <i class="ph-bold ${item.icon} text-indigo-600"></i>
          <span>${escapeHtml(item.label)}</span>
        </div>
      `;
    });

    if (items.length === 0) {
      html = '<div class="text-xs text-slate-400 p-4 text-center">Ничего не найдено</div>';
    }

    container.innerHTML = html;
    window.__tcc_cmd_items = items;
  }

  // ==========================================================================
  // SMART TIME FINDER
  // ==========================================================================
  async function executeFindTime() {
    const studentSelect = document.getElementById('tcc-finder-student-select');
    const studentId = studentSelect ? studentSelect.value : null;
    const durBtn = document.querySelector('.finder-dur-btn.border-indigo-500');
    const dur = durBtn ? parseInt(durBtn.getAttribute('data-dur'), 10) : 60;

    const resEl = document.getElementById('tcc-finder-results');
    if (resEl) resEl.innerHTML = '<div class="text-xs text-slate-400 py-4 text-center">Анализируем рабочие часы и уроки...</div>';

    try {
      const resp = await fetch(`/api/schedule/find-free-slots?duration=${dur}${studentId ? '&student_id=' + studentId : ''}`);
      const data = await resp.json().catch(() => ({}));

      if (resp.ok && data.slots && data.slots.length > 0) {
        let html = '<div class="text-[11px] font-black text-slate-400 uppercase mt-2 mb-1">Рекомендуемые слоты:</div>';
        data.slots.slice(0, 6).forEach(slot => {
          html += `
            <div class="flex items-center justify-between p-2.5 rounded-xl border border-slate-200 bg-white hover:border-indigo-400 transition cursor-pointer shadow-xs" 
                 onclick="window.TCC.pickRecommendedSlot('${slot.date}', '${slot.start_time}', ${slot.duration})">
              <div>
                <div class="text-xs font-black text-slate-800">${slot.date_label}</div>
                <div class="text-[11px] text-slate-500 font-medium">${slot.duration} мин</div>
              </div>
              <span class="text-xs font-black px-2 py-1 rounded-lg bg-indigo-50 text-indigo-700">${slot.start_time}</span>
            </div>
          `;
        });
        if (resEl) resEl.innerHTML = html;
      } else {
        if (resEl) resEl.innerHTML = '<div class="text-xs text-amber-600 font-bold py-4 text-center">Свободных слотов в рамках рабочих часов не найдено</div>';
      }
    } catch (e) {
      if (resEl) resEl.innerHTML = '<div class="text-xs text-rose-600 font-bold py-4 text-center">Не удалось подобрать время</div>';
    }
  }

  function pickRecommendedSlot(date, time, duration) {
    openInspector('composer');
    setTimeout(() => {
      const f = document.getElementById('tcc-inline-composer-form');
      if (f) {
        if (f.elements['lesson_date']) f.elements['lesson_date'].value = date;
        if (f.elements['lesson_time']) f.elements['lesson_time'].value = time;
        if (f.elements['duration']) f.elements['duration'].value = duration;
      }
    }, 50);
  }

  // ==========================================================================
  // HELPERS
  // ==========================================================================
  function showContextMenu(e, lesson) {
    const menu = document.getElementById('tcc-context-menu');
    if (!menu) return;

    menu.style.left = `${Math.min(window.innerWidth - 200, e.clientX)}px`;
    menu.style.top = `${Math.min(window.innerHeight - 200, e.clientY)}px`;
    menu.classList.remove('is-hidden');

    menu.innerHTML = `
      <div class="tcc-menu-item" onclick="window.open('${lesson.room_url}', '_blank')">
        <i class="ph-bold ph-broadcast text-indigo-600"></i>
        <span>Войти в урок</span>
      </div>
      <div class="tcc-menu-item" onclick="window.TCC.openInspector('lesson', ${JSON.stringify(lesson).replace(/"/g, '&quot;')})">
        <i class="ph-bold ph-sliders-horizontal text-slate-600"></i>
        <span>Подробнее</span>
      </div>
      <div class="tcc-menu-item" onclick="window.TCC.promptRescheduleLesson(${lesson.lesson_id})">
        <i class="ph-bold ph-calendar text-slate-600"></i>
        <span>Перенести</span>
      </div>
      <div class="tcc-menu-item danger" onclick="window.TCC.cancelLesson(${lesson.lesson_id})">
        <i class="ph-bold ph-trash text-rose-600"></i>
        <span>Отменить урок</span>
      </div>
    `;
  }

  function navigatePeriod(delta, isToday = false) {
    if (isToday) {
      window.location.href = '/schedule?week=0';
    } else {
      window.location.href = `/schedule?week=${state.weekOffset + delta}`;
    }
  }

  function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
  }

  function showToast(msg, type = 'info') {
    if (typeof window.showBentoToast === 'function') {
      window.showBentoToast(msg, type);
    } else {
      alert(msg);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function updateLiveIndicators() {
    const line = document.getElementById('tcc-current-time-line');
    if (!line) return;

    const now = new Date();
    const startHour = 7;
    const endHour = 23;
    const curHour = now.getHours();
    const curMin = now.getMinutes();

    if (curHour >= startHour && curHour <= endHour) {
      const hourHeight = state.density === 'compact' ? 44 : 60;
      const topPx = (curHour - startHour) * hourHeight + (curMin / 60) * hourHeight;
      line.style.top = `${topPx}px`;
      line.style.display = 'flex';
    } else {
      line.style.display = 'none';
    }
  }

  // Submit inline composer
  async function submitComposer(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);

    try {
      const resp = await fetch('/api/schedule/create_lesson', {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCsrfToken()
        },
        body: formData
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && (data.status === 'success' || data.success)) {
        showToast('Урок успешно создан!', 'success');
        setTimeout(() => window.location.reload(), 400);
      } else {
        showToast(data.error || 'Не удалось создать урок', 'error');
      }
    } catch (err) {
      showToast('Сетевая ошибка при создании урока', 'error');
    }
  }

  // Public API
  window.TCC = {
    state,
    filterByStudent,
    filterBySubject,
    toggleLayer,
    switchView,
    openInspector,
    toggleInspector,
    toggleRail,
    selectMobileDay,
    toggleDensity: function(forced) {
      state.density = forced || (state.density === 'comfortable' ? 'compact' : 'comfortable');
      const ws = document.getElementById('tcc-workspace');
      if (ws) {
        if (state.density === 'compact') ws.classList.add('is-density-compact');
        else ws.classList.remove('is-density-compact');
      }
      renderAll();
    },
    openScopeModal,
    closeScopeModal: function() {
      const m = document.getElementById('tcc-scope-modal');
      if (m) m.classList.add('is-hidden');
    },
    toggleCommandPalette,
    openCmd: function() {
      const m = document.getElementById('tcc-cmd-modal');
      if (m && m.classList.contains('is-hidden')) toggleCommandPalette();
    },
    closeCmd: function() {
      const m = document.getElementById('tcc-cmd-modal');
      if (m && !m.classList.contains('is-hidden')) toggleCommandPalette();
    },
    selectLesson: function(lessonId) {
      const l = state.lessons.find(x => x.id === lessonId || x.lesson_id === lessonId);
      if (l) openInspector('lesson', l);
    },
    openFindTime: function() {
      openInspector('find_time');
    },
    openSlotComposer: function(payload) {
      openInspector('composer', payload || {});
    },
    startResize,
    startSlotSelection: function(e, dayIdx, dayIso, hour) {
      // Slot composer shortcut on cell click
      openInspector('composer', { date: dayIso, time: `${hour < 10 ? '0' + hour : hour}:00` });
    },
    runCommand: function(idx) {
      const items = window.__tcc_cmd_items || [];
      if (items[idx] && typeof items[idx].action === 'function') {
        toggleCommandPalette();
        items[idx].action();
      }
    },
    executeFindTime,
    pickRecommendedSlot,
    selectFinderDuration: function(dur) {
      document.querySelectorAll('.finder-dur-btn').forEach(b => {
        if (parseInt(b.getAttribute('data-dur'), 10) === dur) {
          b.className = 'finder-dur-btn py-1.5 rounded-xl border-2 border-indigo-500 bg-indigo-50 text-xs font-black text-indigo-700 cursor-pointer';
        } else {
          b.className = 'finder-dur-btn py-1.5 rounded-xl border border-slate-200 bg-white text-xs font-black text-slate-700 cursor-pointer';
        }
      });
    },
    openHomework: function(url) {
      if (url) window.open(url, '_blank');
    },
    changeLessonStatus: async function(lessonId, newStatus) {
      try {
        const resp = await fetch(`/schedule/api/lesson/${lessonId}/set-status`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
          },
          body: JSON.stringify({ status: newStatus })
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok && (data.status === 'success' || data.success)) {
          showToast('Статус урока обновлен!', 'success');
          const l = state.lessons.find(x => x.lesson_id === lessonId);
          if (l) l.status = newStatus;
          renderAll();
        } else {
          showToast(data.error || 'Не удалось обновить статус', 'error');
        }
      } catch (err) {
        showToast('Сетевая ошибка', 'error');
      }
    },
    cancelLesson: async function(lessonId) {
      if (!confirm('Вы уверены, что хотите отменить этот урок?')) return;
      try {
        const resp = await fetch(`/schedule/api/lesson/${lessonId}/delete`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
          }
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok && (data.status === 'success' || data.success)) {
          showToast('Урок отменён', 'success');
          state.lessons = state.lessons.filter(x => x.lesson_id !== lessonId);
          renderAll();
          openInspector('overview');
        } else {
          showToast(data.error || 'Не удалось отменить урок', 'error');
        }
      } catch (err) {
        showToast('Сетевая ошибка', 'error');
      }
    },
    submitComposer,
  };

  // Launch on DOMContentLoaded
  document.addEventListener('DOMContentLoaded', init);
})();
