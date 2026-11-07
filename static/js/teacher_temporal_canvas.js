/**
 * BooStudy — Teacher Control Center: Sprint 2.7 TEMPORAL CANVAS
 * Living Temporal Workspace for Educators (Isolated Preview Engine)
 */

(function() {
  'use strict';

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    if (window.CSRF_TOKEN) return window.CSRF_TOKEN;
    const input = document.querySelector('input[name="csrf_token"]');
    if (input && input.value) return input.value;
    return '';
  }

  // Seed demo data if needed for the rich 16-lesson flagship scenario
  const FLAGSHIP_DEMO_LESSONS = [
    {
      lesson_id: 901,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-02',
      start_time: '10:30',
      end_time: '12:00',
      duration_minutes: 90,
      subject: 'Информатика',
      topic: 'Разбор графов и поиск путей • КЕГЭ №13',
      notes: 'Подробный анализ графовых моделей и динамическое программирование на графах.',
      status: 'planned',
      is_test: false,
      is_recurring: true,
      has_hw: true,
      hw_status: 'accepted',
      room_url: '/lessons/room/901'
    },
    {
      lesson_id: 902,
      student_name: 'demo_student_2',
      student_id: 102,
      start_date: '2026-11-02',
      start_time: '14:00',
      end_time: '15:00',
      duration_minutes: 60,
      subject: 'Программирование',
      topic: 'Python для ЕГЭ №24 (обработка строк)',
      notes: 'Регулярные выражения и методы поиска максимальной подстроки.',
      status: 'in_progress',
      is_test: false,
      is_recurring: false,
      has_hw: true,
      hw_status: 'review',
      room_url: '/lessons/room/902'
    },
    {
      lesson_id: 903,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-02',
      start_time: '16:30',
      end_time: '17:15',
      duration_minutes: 45,
      subject: 'Информатика',
      topic: 'Экспресс-разбор домашнего задания',
      notes: 'Точечные вопросы по домашней работе №4.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: false,
      room_url: '/lessons/room/903'
    },
    {
      lesson_id: 904,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-03',
      start_time: '07:00',
      end_time: '08:00',
      duration_minutes: 60,
      subject: 'Информатика',
      topic: 'Утренний интенсив: Базовые алгоритмы',
      notes: 'Сложность алгоритмов, асимптотика O(N).',
      status: 'planned',
      is_test: false,
      is_recurring: true,
      has_hw: true,
      hw_status: 'accepted',
      room_url: '/lessons/room/904'
    },
    {
      lesson_id: 905,
      student_name: 'demo_student_2',
      student_id: 102,
      start_date: '2026-11-03',
      start_time: '14:00',
      end_time: '15:00',
      duration_minutes: 60,
      subject: 'Математика',
      topic: 'Теория вероятностей: сложные задачи',
      notes: 'Условная вероятность, теорема Байеса.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: false,
      room_url: '/lessons/room/905'
    },
    {
      lesson_id: 906,
      student_name: 'demo_student_2',
      student_id: 102,
      start_date: '2026-11-03',
      start_time: '18:00',
      end_time: '19:30',
      duration_minutes: 90,
      subject: 'Математика',
      topic: 'Параметры: аналитический метод',
      notes: 'Квадратичные уравнения с параметром.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: true,
      hw_status: 'accepted',
      room_url: '/lessons/room/906'
    },
    {
      lesson_id: 907,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-04',
      start_time: '11:00',
      end_time: '12:00',
      duration_minutes: 60,
      subject: 'Информатика',
      topic: 'Динамика в таблицах • КЕГЭ №18',
      notes: 'Поиск максимальной и минимальной суммы в сетке.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: true,
      hw_status: 'accepted',
      room_url: '/lessons/room/907'
    },
    {
      lesson_id: 908,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-04',
      start_time: '18:00',
      end_time: '19:30',
      duration_minutes: 90,
      subject: 'Информатика',
      topic: 'Динамическое программирование: теория',
      notes: 'Задача о рюкзаке и наибольшая возрастающая подпоследовательность.',
      status: 'planned',
      is_test: false,
      is_recurring: true,
      has_hw: false,
      room_url: '/lessons/room/908'
    },
    {
      lesson_id: 909,
      student_name: 'demo_student_2',
      student_id: 102,
      start_date: '2026-11-04',
      start_time: '18:00',
      end_time: '19:30',
      duration_minutes: 90,
      subject: 'Программирование',
      topic: 'Параллельная группа: структуры данных',
      notes: 'Стеки, очереди, приоритетные очереди в Python.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: true,
      hw_status: 'accepted',
      room_url: '/lessons/room/909'
    },
    {
      lesson_id: 910,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-05',
      start_time: '15:00',
      end_time: '16:00',
      duration_minutes: 60,
      subject: 'Информатика',
      topic: 'Комбинаторика и логика • КЕГЭ №8',
      notes: 'Слова по алфавиту, перестановки с ограничениями.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: true,
      hw_status: 'review',
      room_url: '/lessons/room/910'
    },
    {
      lesson_id: 911,
      student_name: 'demo_student_2',
      student_id: 102,
      start_date: '2026-11-05',
      start_time: '17:00',
      end_time: '19:00',
      duration_minutes: 120,
      subject: 'Математика',
      topic: 'Параметры в профильной математике',
      notes: 'Геометрический подход к решению задач с параметрами.',
      status: 'planned',
      is_test: false,
      is_recurring: true,
      has_hw: false,
      room_url: '/lessons/room/911'
    },
    {
      lesson_id: 912,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-06',
      start_time: '10:00',
      end_time: '11:30',
      duration_minutes: 90,
      subject: 'Информатика',
      topic: 'Теория игр: две кучи • КЕГЭ №19–21',
      notes: 'Выигрышные и проигрышные позиции, таблицы состояний.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: true,
      hw_status: 'accepted',
      room_url: '/lessons/room/912'
    },
    {
      lesson_id: 913,
      student_name: 'demo_student_2',
      student_id: 102,
      start_date: '2026-11-06',
      start_time: '14:00',
      end_time: '14:45',
      duration_minutes: 45,
      subject: 'Физика',
      topic: 'Промежуточный срез: Электродинамика',
      notes: 'Закон Ома, правила Кирхгофа, расчет цепей.',
      status: 'planned',
      is_test: true,
      is_recurring: false,
      has_hw: false,
      room_url: '/lessons/room/913'
    },
    {
      lesson_id: 914,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-06',
      start_time: '16:00',
      end_time: '17:00',
      duration_minutes: 60,
      subject: 'Информатика',
      topic: 'Рекурсивные алгоритмы • КЕГЭ №16',
      notes: 'Мемоизация и глубина стека вызовов.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: true,
      hw_status: 'accepted',
      room_url: '/lessons/room/914'
    },
    {
      lesson_id: 915,
      student_name: 'demo_student_2',
      student_id: 102,
      start_date: '2026-11-06',
      start_time: '18:00',
      end_time: '19:00',
      duration_minutes: 60,
      subject: 'Программирование',
      topic: 'Практикум: решение задач повышенной сложности',
      notes: 'Разбор авторских задач сайта Полякова.',
      status: 'planned',
      is_test: false,
      is_recurring: false,
      has_hw: false,
      room_url: '/lessons/room/915'
    },
    {
      lesson_id: 916,
      student_name: 'demo_student_1',
      student_id: 101,
      start_date: '2026-11-07',
      start_time: '12:00',
      end_time: '13:30',
      duration_minutes: 90,
      subject: 'Информатика',
      topic: 'Субботний пробник: разбор первой части',
      notes: 'Анализ типичных ошибок первой части.',
      status: 'planned',
      is_test: true,
      is_recurring: false,
      has_hw: true,
      hw_status: 'review',
      room_url: '/lessons/room/916'
    }
  ];

  class TemporalCanvasEngine {
    constructor() {
      const pageData = window.SCHEDULE_PAGE_DATA || {};
      this.state = {
        view: 'week', // 'week', 'day', 'focus', 'month', 'stream'
        focusedDate: pageData.today_iso || '2026-11-02',
        selectedLessonId: null,
        hourHeight: 64, // 64 or 48 (compact)
        layers: {
          homework: true,
          freeSlots: true,
          nonWorking: true
        },
        filters: {
          studentId: null,
          subject: null,
          status: null,
          searchQuery: ''
        },
        lessons: [],
        days: [],
        accessibleStudents: pageData.accessible_students || [],
        timezone: pageData.timezone || 'Europe/Moscow',
        canManage: pageData.can_manage !== false,
        activePopover: null,
        drag: {
          active: false,
          lesson: null,
          startX: 0,
          startY: 0,
          offsetX: 0,
          offsetY: 0,
          ghostEl: null,
          targetCol: null,
          targetTime: null,
          isCollision: false
        },
        resize: {
          active: false,
          lesson: null,
          startY: 0,
          startHeight: 0,
          newDuration: 60
        }
      };

      this.init();
    }

    calcEndTime(startTime, durationMinutes) {
      if (!startTime) return '15:00';
      const [h, m] = startTime.split(':').map(Number);
      const total = h * 60 + m + parseInt(durationMinutes || 60, 10);
      const eh = Math.floor(total / 60) % 24;
      const em = total % 60;
      return `${String(eh).padStart(2, '0')}:${String(em).padStart(2, '0')}`;
    }

    init() {
      const pageData = window.SCHEDULE_PAGE_DATA || {};

      // 1. Initialize days from server weekdays payload if present
      const serverDays = pageData.weekdays || [];
      if (Array.isArray(serverDays) && serverDays.length === 7) {
        this.state.days = serverDays.map(w => ({
          date: w.iso,
          name: w.short_name || w.name,
          num: String(w.date),
          isToday: Boolean(w.is_today),
          full: w.full_name || w.day_name,
          eventsCount: w.events_count || 0
        }));
      } else {
        this.state.days = [
          { date: '2026-11-02', name: 'ПН', num: '2', isToday: true, full: 'Понедельник' },
          { date: '2026-11-03', name: 'ВТ', num: '3', isToday: false, full: 'Вторник' },
          { date: '2026-11-04', name: 'СР', num: '4', isToday: false, full: 'Среда' },
          { date: '2026-11-05', name: 'ЧТ', num: '5', isToday: false, full: 'Четверг' },
          { date: '2026-11-06', name: 'ПТ', num: '6', isToday: false, full: 'Пятница' },
          { date: '2026-11-07', name: 'СБ', num: '7', isToday: false, full: 'Суббота' },
          { date: '2026-11-08', name: 'ВС', num: '8', isToday: false, full: 'Воскресенье' }
        ];
      }

      // 2. Focused date: use today or first day
      const todayDay = this.state.days.find(d => d.isToday);
      this.state.focusedDate = todayDay ? todayDay.date : this.state.days[0].date;

      // 3. Load initial lessons from server page data if provided, or use flagship demo if standalone demo
      const rawPayload = pageData.lessons;
      if (Array.isArray(rawPayload) && rawPayload.length > 0) {
        this.state.lessons = rawPayload.map(l => {
          const startTime = l.start_time || (l.time_str || '14:00');
          const dur = parseInt(l.duration_minutes || l.duration || 60, 10);
          return {
            lesson_id: l.lesson_id || l.id,
            student_name: l.student_name || (l.student ? (l.student.name || l.student) : 'Ученик'),
            student_id: l.student_id,
            start_date: l.start_date || (l.date ? l.date : (l.lesson_date ? l.lesson_date.slice(0, 10) : '2026-11-02')),
            start_time: startTime,
            end_time: l.end_time || this.calcEndTime(startTime, dur),
            duration_minutes: dur,
            subject: l.subject || 'Информатика',
            topic: (!l.topic || l.topic.trim() === '-' || l.topic.trim() === '') ? 'Разбор типовых заданий КЕГЭ' : l.topic,
            notes: l.notes || '',
            status: l.status || 'planned',
            is_test: Boolean(l.is_test),
            is_recurring: Boolean(l.is_recurring),
            has_hw: Boolean(l.homework || l.has_hw),
            hw_status: l.hw_status || (l.status === 'in_progress' ? 'review' : 'accepted'),
            room_url: l.room_url || `/lessons/room/${l.lesson_id || l.id}`
          };
        });
      } else if (rawPayload && rawPayload.length === 0 && !pageData.is_temporal_canvas_preview) {
        // Real empty schedule for this teacher
        this.state.lessons = [];
      } else {
        // Flagship rich scenario fallback
        this.state.lessons = [...FLAGSHIP_DEMO_LESSONS];
      }

      // 4. Render initial layout
      this.render();
      this.bindGlobalEvents();
      this.scrollToActiveHours();
    }

    render() {
      this.renderCommandBar();
      const filtered = this.getFilteredLessons();

      if (filtered.length === 0 && this.state.lessons.length > 0) {
        const container = document.getElementById('tc-canvas-main');
        if (container) {
          container.className = 'tc-canvas-card p-8 flex items-center justify-center';
          container.innerHTML = this.renderEmptyState('По выбранным фильтрам уроки не найдены');
        }
      } else {
        if (this.state.view === 'week') {
          this.renderWeekView();
        } else if (this.state.view === 'day') {
          this.renderDayView();
        } else if (this.state.view === 'focus') {
          this.renderFocusView();
        } else if (this.state.view === 'month') {
          this.renderMonthView();
        } else if (this.state.view === 'stream') {
          this.renderStreamView();
        }
      }

      this.renderContextDock();
    }

    renderCommandBar() {
      // Update date title
      const titleEl = document.getElementById('tc-date-range');
      if (titleEl) {
        const dStart = this.state.days[0] || { num: '2' };
        const dEnd = this.state.days[6] || { num: '8' };

        if (this.state.view === 'day') {
          const d = this.state.days.find(x => x.date === this.state.focusedDate) || this.state.days[0];
          titleEl.textContent = `${d.full}, ${d.num} ноября 2026`;
        } else if (this.state.view === 'focus') {
          const d = this.state.days.find(x => x.date === this.state.focusedDate) || this.state.days[4];
          titleEl.textContent = `Фокус: ${d.full}, ${d.num} ноября 2026`;
        } else if (this.state.view === 'month') {
          titleEl.textContent = 'Ноябрь 2026';
        } else if (this.state.view === 'stream') {
          titleEl.textContent = `Список занятий • ${dStart.num} — ${dEnd.num} ноября 2026`;
        } else {
          titleEl.textContent = `${dStart.num} — ${dEnd.num} ноября 2026`;
        }
      }

      // Update active view pills
      document.querySelectorAll('.tc-view-btn').forEach(btn => {
        const viewMode = btn.dataset.view;
        btn.classList.toggle('is-active', viewMode === this.state.view);
      });

      // Update filter badge
      const filterBadge = document.getElementById('tc-filter-badge');
      if (filterBadge) {
        let count = 0;
        if (this.state.filters.studentId) count++;
        if (this.state.filters.subject) count++;
        if (this.state.filters.status) count++;
        if (this.state.filters.searchQuery) count++;
        if (count > 0) {
          filterBadge.textContent = count;
          filterBadge.classList.remove('hidden', 'is-hidden');
          filterBadge.style.display = 'inline-flex';
        } else {
          filterBadge.classList.add('hidden', 'is-hidden');
          filterBadge.style.display = 'none';
        }
      }
    }

    renderWeekView() {
      const container = document.getElementById('tc-canvas-main');
      if (!container) return;

      container.className = 'tc-canvas-card';
      container.innerHTML = `
        <div class="tc-days-header-strip">
          <div class="tc-gutter-header">
            <span class="tc-tz-label">МСК</span>
          </div>
          <div class="tc-day-header-cols">
            ${this.state.days.map((d, idx) => {
              const dayLessons = this.state.lessons.filter(l => l.start_date === d.date);
              const totalHours = (dayLessons.reduce((acc, l) => acc + (l.duration_minutes || 60), 0) / 60).toFixed(1);
              return `
                <div class="tc-day-header-cell ${d.isToday ? 'is-today' : ''}" onclick="window.TC.zoomToDay('${d.date}')" title="Нажмите для перехода в Spatial Focus">
                  <span class="tc-day-name">${d.name}</span>
                  <div class="tc-day-number">${d.num}</div>
                  <span class="tc-day-load-badge">${dayLessons.length} ур • ${totalHours}ч</span>
                </div>
              `;
            }).join('')}
          </div>
        </div>

        <div class="tc-canvas-body" id="tc-canvas-body" style="--tc-hour-height: ${this.state.hourHeight}px;">
          <!-- Time Gutter -->
          <div class="tc-time-gutter">
            ${Array.from({ length: 17 }, (_, i) => {
              const h = i + 7;
              return `<div class="tc-time-cell">${String(h).padStart(2, '0')}:00</div>`;
            }).join('')}
          </div>

          <!-- Day Columns -->
          <div class="tc-columns-grid">
            ${this.state.days.map((d, dayIndex) => {
              const dayLessons = this.getFilteredLessons().filter(l => l.start_date === d.date);
              return `
                <div class="tc-day-column ${d.isToday ? 'is-today' : ''}" data-date="${d.date}" data-col="${dayIndex}">
                  <!-- 17 Background Hour Slot Cells -->
                  ${Array.from({ length: 17 }, (_, i) => {
                    const h = i + 7;
                    const isNonWorking = this.state.layers.nonWorking && (h < 9 || h >= 21);
                    const isFree = this.state.layers.freeSlots && (h === 13 || (dayIndex === 5 && h === 10));
                    return `
                      <div class="tc-slot-cell ${isNonWorking ? 'is-non-working' : ''} ${isFree ? 'is-free-window' : ''}"
                           data-hour="${h}" onclick="window.TC.handleSlotClick('${d.date}', ${h})"></div>
                    `;
                  }).join('')}

                  <!-- Live Current Time Line for Today -->
                  ${d.isToday ? `
                    <div class="tc-now-marker" style="top: ${(14 - 7 + 15 / 60) * this.state.hourHeight}px;"></div>
                  ` : ''}

                  <!-- Lesson Cards -->
                  ${this.renderDayLessonCards(dayLessons)}
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    renderDayView() {
      const container = document.getElementById('tc-canvas-main');
      if (!container) return;

      const currentDay = this.state.days.find(d => d.date === this.state.focusedDate) || this.state.days[0];
      const dayLessons = this.getFilteredLessons().filter(l => l.start_date === currentDay.date);
      const totalHours = (dayLessons.reduce((acc, l) => acc + (l.duration_minutes || 60), 0) / 60).toFixed(1);

      container.className = 'tc-canvas-card tc-day-view';
      container.innerHTML = `
        <div class="tc-days-header-strip">
          <div class="tc-gutter-header">
            <span class="tc-tz-label">МСК</span>
          </div>
          <div class="flex-1 flex items-center justify-between px-4 py-2 bg-slate-50 border-b border-slate-200">
            <div class="flex items-center gap-3">
              <button type="button" class="tc-btn-nav px-2.5 py-1 text-xs" onclick="window.TC.switchView('week')">
                <i class="ph-bold ph-arrow-left"></i>
                <span>Вся неделя</span>
              </button>
              <div class="flex items-baseline gap-2">
                <span class="text-sm font-black text-slate-900 font-display">${currentDay.full}, ${currentDay.num} ноября</span>
                ${currentDay.isToday ? '<span class="px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-black uppercase">Сегодня</span>' : ''}
              </div>
            </div>
            <div class="text-xs font-bold text-slate-500">
              ${dayLessons.length} занятий • ${totalHours} ч
            </div>
          </div>
        </div>

        <div class="tc-canvas-body" id="tc-canvas-body" style="--tc-hour-height: ${this.state.hourHeight}px;">
          <div class="tc-time-gutter">
            ${Array.from({ length: 17 }, (_, i) => {
              const h = i + 7;
              return `<div class="tc-time-cell">${String(h).padStart(2, '0')}:00</div>`;
            }).join('')}
          </div>

          <div class="tc-columns-grid" style="grid-template-columns: 1fr;">
            <div class="tc-day-column ${currentDay.isToday ? 'is-today' : ''}" data-date="${currentDay.date}" data-col="0">
              ${Array.from({ length: 17 }, (_, i) => {
                const h = i + 7;
                const isNonWorking = this.state.layers.nonWorking && (h < 9 || h >= 21);
                return `
                  <div class="tc-slot-cell ${isNonWorking ? 'is-non-working' : ''}"
                       data-hour="${h}" onclick="window.TC.handleSlotClick('${currentDay.date}', ${h})"></div>
                `;
              }).join('')}

              ${currentDay.isToday ? `
                <div class="tc-now-marker" style="top: ${(14 - 7 + 15 / 60) * this.state.hourHeight}px;"></div>
              ` : ''}

              ${this.renderDayLessonCards(dayLessons)}
            </div>
          </div>
        </div>
      `;
    }

    renderStreamView() {
      const container = document.getElementById('tc-canvas-main');
      if (!container) return;

      const filtered = this.getFilteredLessons();
      container.className = 'tc-canvas-card p-6 overflow-y-auto';

      if (!filtered.length) {
        container.innerHTML = this.renderEmptyState('Нет занятий, подходящих под критерии фильтрации');
        return;
      }

      // Group by date
      const grouped = {};
      filtered.forEach(l => {
        grouped[l.start_date] = grouped[l.start_date] || [];
        grouped[l.start_date].push(l);
      });

      const sortedDates = Object.keys(grouped).sort();

      container.innerHTML = `
        <div class="tc-stream-list">
          <div class="flex items-center justify-between pb-4 mb-4 border-b border-slate-200">
            <div>
              <h2 class="text-base font-black text-slate-900 font-display">Хронологический список занятий</h2>
              <p class="text-xs text-slate-500 font-medium">Всего запланировано: ${filtered.length} занятий</p>
            </div>
            <button type="button" class="tc-btn-primary" onclick="window.TC.openCreateLessonModal()">
              <i class="ph-bold ph-plus-circle"></i>
              <span>Новый урок</span>
            </button>
          </div>

          ${sortedDates.map(dateStr => {
            const dayInfo = this.state.days.find(d => d.date === dateStr) || { full: dateStr, num: '' };
            const dayLessons = grouped[dateStr].sort((a, b) => a.start_time.localeCompare(b.start_time));

            return `
              <div class="tc-stream-day-group">
                <div class="tc-stream-day-header">
                  <span class="tc-stream-day-title">${dayInfo.full || dateStr}, ${dayInfo.num || ''} ноября</span>
                  <span class="tc-stream-day-badge">${dayLessons.length} ур</span>
                </div>

                <div class="space-y-2.5">
                  ${dayLessons.map(l => {
                    const isSelected = this.state.selectedLessonId === l.lesson_id;
                    let statusBadge = '';
                    if (l.status === 'in_progress') statusBadge = '<span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-black uppercase">Идёт сейчас</span>';
                    else if (l.status === 'completed') statusBadge = '<span class="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-black uppercase">Проведён</span>';
                    else if (l.status === 'cancelled') statusBadge = '<span class="px-2 py-0.5 rounded-full bg-rose-100 text-rose-800 text-[10px] font-black uppercase">Отменён</span>';

                    return `
                      <div class="tc-stream-card ${isSelected ? 'is-selected' : ''}"
                           onclick="window.TC.selectLesson(event, ${l.lesson_id})">
                        <div class="flex items-start justify-between gap-4">
                          <div class="flex items-start gap-3">
                            <div class="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-200/80 text-indigo-700 flex items-center justify-center font-black text-sm shrink-0">
                              ${(l.student_name && l.student_name[0] ? l.student_name[0] : 'У').toUpperCase()}
                            </div>
                            <div>
                              <div class="flex items-center gap-2 mb-1 flex-wrap">
                                <span class="font-mono text-xs font-black text-slate-800 bg-slate-100 px-2 py-0.5 rounded-md">
                                  ${l.start_time} — ${l.end_time} (${l.duration_minutes}м)
                                </span>
                                <span class="text-xs font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-md border border-indigo-100">
                                  ${l.subject}
                                </span>
                                ${statusBadge}
                                ${l.is_test ? '<span class="px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 text-[10px] font-bold border border-amber-200">Тест</span>' : ''}
                                ${l.is_recurring ? '<i class="ph-bold ph-repeat text-indigo-600 text-xs" title="Серия"></i>' : ''}
                              </div>
                              <div class="text-sm font-black text-slate-900 font-display">${l.student_name}</div>
                              <div class="text-xs text-slate-600 font-medium mt-0.5">${l.topic}</div>
                              ${l.notes ? `<div class="text-[11px] text-slate-400 font-medium italic mt-1">«${l.notes}»</div>` : ''}
                            </div>
                          </div>

                          <div class="flex items-center gap-2 shrink-0">
                            <a href="${l.room_url}" target="_blank" class="tc-btn-primary py-2 px-3 text-xs" onclick="event.stopPropagation()">
                              <i class="ph-bold ph-broadcast"></i>
                              <span>Войти</span>
                            </a>
                            <button type="button" class="tc-btn-nav py-2 px-3 text-xs" onclick="window.TC.selectLesson(event, ${l.lesson_id})">
                              Инспектор
                            </button>
                          </div>
                        </div>
                      </div>
                    `;
                  }).join('')}
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    renderEmptyState(message) {
      return `
        <div class="tc-empty-state">
          <div class="tc-empty-icon">
            <i class="ph-bold ph-calendar-x"></i>
          </div>
          <h3 class="tc-empty-title">Занятия не найдены</h3>
          <p class="tc-empty-desc">${message || 'По вашему запросу не найдено ни одного урока в текущем периоде'}</p>
          <div class="flex items-center gap-3">
            <button type="button" class="tc-btn-nav" onclick="window.TC.resetFilters()">
              <i class="ph-bold ph-arrow-counter-clockwise"></i>
              <span>Сбросить все фильтры</span>
            </button>
            <button type="button" class="tc-btn-primary" onclick="window.TC.openCreateLessonModal()">
              <i class="ph-bold ph-plus"></i>
              <span>Создать занятие</span>
            </button>
          </div>
        </div>
      `;
    }

    handleSlotClick(dateStr, hour) {
      const timeStr = `${String(hour).padStart(2, '0')}:00`;
      this.openCreateLessonModal(dateStr, timeStr);
    }

    renderDayLessonCards(dayLessons) {
      if (!dayLessons || !dayLessons.length) return '';

      // Check overlapping lessons
      const sorted = [...dayLessons].sort((a, b) => a.start_time.localeCompare(b.start_time));
      const overlapMap = new Map();

      for (let i = 0; i < sorted.length; i++) {
        for (let j = i + 1; j < sorted.length; j++) {
          const l1 = sorted[i];
          const l2 = sorted[j];
          if (l1.start_time < l2.end_time && l2.start_time < l1.end_time) {
            overlapMap.set(l1.lesson_id, 0);
            overlapMap.set(l2.lesson_id, 1);
          }
        }
      }

      return sorted.map(l => {
        const [sh, sm] = l.start_time.split(':').map(Number);
        const top = (sh - 7 + sm / 60) * this.state.hourHeight;
        const height = (l.duration_minutes / 60) * this.state.hourHeight - 3;
        const subcol = overlapMap.has(l.lesson_id) ? `subcol-${overlapMap.get(l.lesson_id)}` : '';
        const isSelected = this.state.selectedLessonId === l.lesson_id;

        let subjClass = 'subj-indigo';
        if (l.subject.includes('Мат')) subjClass = 'subj-sky';
        else if (l.subject.includes('Физ')) subjClass = 'subj-emerald';
        else if (l.subject.includes('Прог')) subjClass = 'subj-amber';

        return `
          <div class="tc-lesson-card ${subjClass} ${subcol} ${l.status === 'in_progress' ? 'status-in_progress' : ''} ${isSelected ? 'is-selected' : ''}"
               id="tc-card-${l.lesson_id}"
               data-id="${l.lesson_id}"
               style="top: ${top}px; height: ${height}px;"
               onpointerdown="window.TC.handleCardPointerDown(event, ${l.lesson_id})"
               onclick="window.TC.selectLesson(event, ${l.lesson_id})">
            
            <div class="tc-card-top">
              <span class="tc-card-time">${l.start_time} — ${l.end_time}</span>
              <span class="tc-card-duration">${l.duration_minutes}м</span>
              ${l.status === 'in_progress' ? '<span class="tc-card-live-dot" title="Урок идёт прямо сейчас"></span>' : ''}
            </div>

            <div class="tc-card-student">${l.student_name}</div>
            ${l.duration_minutes >= 60 ? `<div class="tc-card-topic">${l.topic}</div>` : ''}

            ${l.duration_minutes >= 75 ? `
              <div class="tc-card-badges">
                ${this.state.layers.homework && l.has_hw ? `
                  <span class="tc-badge-hw">${l.hw_status === 'review' ? 'ДЗ: проверка' : 'ДЗ: принято'}</span>
                ` : ''}
                ${l.is_recurring ? '<i class="ph-bold ph-repeat tc-badge-series" title="Регулярная серия"></i>' : ''}
                ${l.is_test ? '<i class="ph-bold ph-exam text-amber-600 text-xs" title="Тестовое занятие"></i>' : ''}
              </div>
            ` : ''}

            <div class="tc-resize-handle" onpointerdown="window.TC.handleResizeDown(event, ${l.lesson_id})"></div>
          </div>
        `;
      }).join('');
    }

    renderFocusView() {
      const container = document.getElementById('tc-canvas-main');
      if (!container) return;

      const focusedDay = this.state.days.find(d => d.date === this.state.focusedDate) || this.state.days[4];
      const dayLessons = this.getFilteredLessons().filter(l => l.start_date === focusedDay.date);

      container.className = 'tc-canvas-card tc-focus-container';
      container.innerHTML = `
        <!-- Top Week Ribbon for Spatial Continuity -->
        <div class="tc-focus-week-ribbon">
          <button type="button" class="tc-focus-back-btn" onclick="window.TC.switchView('week')">
            <i class="ph-bold ph-arrow-left"></i>
            <span>Вся неделя</span>
          </button>

          <div class="tc-focus-ribbon-days">
            ${this.state.days.map(d => {
              const count = this.state.lessons.filter(l => l.start_date === d.date).length;
              return `
                <div class="tc-focus-day-chip ${d.date === focusedDay.date ? 'is-active' : ''}"
                     onclick="window.TC.zoomToDay('${d.date}')">
                  <span>${d.name} ${d.num}</span>
                  <span class="text-[10px] opacity-75">(${count})</span>
                </div>
              `;
            }).join('')}
          </div>

          <div class="text-xs font-black text-slate-700 font-display">
            ${focusedDay.full}, ${focusedDay.num} ноября
          </div>
        </div>

        <!-- Focused Day Expanded Timeline (80px / hour) -->
        <div class="tc-focus-timeline" id="tc-focus-timeline">
          <div class="tc-time-gutter" style="--tc-hour-height: var(--tc-hour-height-focus);">
            ${Array.from({ length: 17 }, (_, i) => {
              const h = i + 7;
              return `<div class="tc-time-cell" style="height: 80px;">${String(h).padStart(2, '0')}:00</div>`;
            }).join('')}
          </div>

          <div class="tc-focus-column">
            <!-- Background Hour Slot Cells -->
            ${Array.from({ length: 17 }, (_, i) => {
              const h = i + 7;
              return `
                <div class="tc-focus-slot-cell" data-hour="${h}" onclick="window.TC.handleSlotClick('${focusedDay.date}', ${h})"></div>
              `;
            }).join('')}

            <!-- Focus Lesson Cards -->
            ${dayLessons.map(l => {
              const [sh, sm] = l.start_time.split(':').map(Number);
              const top = (sh - 7 + sm / 60) * 80;
              const height = (l.duration_minutes / 60) * 80 - 6;
              const isSelected = this.state.selectedLessonId === l.lesson_id;

              return `
                <div class="tc-focus-lesson-card ${isSelected ? 'is-selected' : ''}"
                     style="top: ${top}px; height: ${height}px;"
                     onclick="window.TC.selectLesson(event, ${l.lesson_id})">
                  
                  <div class="flex items-center gap-4">
                    <div class="w-10 h-10 rounded-xl bg-indigo-100 text-indigo-700 flex items-center justify-center font-black text-sm border border-indigo-200">
                      ${l.student_name[0].toUpperCase()}
                    </div>
                    <div>
                      <div class="flex items-center gap-2 mb-0.5">
                        <span class="text-xs font-mono font-black text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-md border border-indigo-100">
                          ${l.start_time} — ${l.end_time} (${l.duration_minutes} мин)
                        </span>
                        <span class="text-xs font-bold text-slate-500">• ${l.subject}</span>
                        ${l.status === 'in_progress' ? '<span class="px-2 py-0.5 rounded-md bg-amber-100 text-amber-800 text-[10px] font-black uppercase">Идёт сейчас</span>' : ''}
                      </div>
                      <div class="text-sm font-black text-slate-900 font-display">${l.student_name}</div>
                      <div class="text-xs text-slate-600 font-medium">${l.topic}</div>
                    </div>
                  </div>

                  <div class="flex items-center gap-3">
                    <a href="${l.room_url}" target="_blank" class="tc-btn-primary" onclick="event.stopPropagation()">
                      <i class="ph-bold ph-broadcast"></i>
                      <span>Войти в комнату</span>
                    </a>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    renderMonthView() {
      const container = document.getElementById('tc-canvas-main');
      if (!container) return;

      container.className = 'tc-canvas-card p-6';
      container.innerHTML = `
        <div class="flex items-center justify-between mb-4 pb-3 border-b border-slate-200">
          <div class="text-base font-black text-slate-900 font-display">Ноябрь 2026 • Месячный обзор нагрузки</div>
          <button type="button" class="tc-btn-nav" onclick="window.TC.switchView('week')">
            ← Вернуться к неделе
          </button>
        </div>

        <div class="grid grid-cols-7 gap-2 mb-2">
          ${['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'].map(d => `
            <div class="text-center text-xs font-black text-slate-400 py-1 uppercase tracking-wider">${d}</div>
          `).join('')}
        </div>

        <div class="grid grid-cols-7 gap-2">
          ${Array.from({ length: 35 }, (_, idx) => {
            const dayNum = idx - 1; // 2nd of Nov starts at index 0
            if (dayNum < 1 || dayNum > 30) {
              return `<div class="h-28 rounded-xl bg-slate-50/50 border border-dashed border-slate-200/60 p-2"></div>`;
            }
            const dateStr = `2026-11-${String(dayNum).padStart(2, '0')}`;
            const lessons = this.state.lessons.filter(l => l.start_date === dateStr);
            const isToday = dayNum === 2;

            return `
              <div class="h-28 rounded-xl border ${isToday ? 'border-indigo-400 bg-indigo-50/20' : 'border-slate-200/80 bg-white'} p-2.5 flex flex-col justify-between hover:border-slate-300 transition cursor-pointer"
                   onclick="window.TC.zoomToDay('${dateStr}')">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-black ${isToday ? 'text-indigo-600' : 'text-slate-800'}">${dayNum}</span>
                  ${lessons.length ? `<span class="text-[10px] font-bold text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded-full">${lessons.length} ур</span>` : ''}
                </div>
                <div class="flex flex-col gap-1 overflow-hidden">
                  ${lessons.slice(0, 2).map(l => `
                    <div class="text-[10px] font-bold text-slate-700 bg-slate-50 border border-slate-200/60 rounded px-1.5 py-0.5 truncate">
                      ${l.start_time} ${l.student_name}
                    </div>
                  `).join('')}
                  ${lessons.length > 2 ? `<span class="text-[9px] font-black text-indigo-600">+${lessons.length - 2} ещё</span>` : ''}
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    renderContextDock() {
      const dock = document.getElementById('tc-context-dock');
      if (!dock) return;

      const selectedLesson = this.state.selectedLessonId 
        ? this.state.lessons.find(l => l.lesson_id === this.state.selectedLessonId)
        : null;

      if (selectedLesson) {
        // Mode 2: Detailed Lesson Inspector
        dock.innerHTML = `
          <div class="tc-dock-header">
            <div class="tc-dock-title">
              <i class="ph-bold ph-identification-card text-indigo-600 text-lg"></i>
              <span>Карточка урока</span>
            </div>
            <button type="button" class="tc-dock-close-btn" onclick="window.TC.selectLesson(null, null)">✕</button>
          </div>

          <div class="tc-dock-body">
            <!-- Lesson Identity & Time -->
            <div class="p-3.5 rounded-xl bg-slate-50 border border-slate-200/80 flex flex-col gap-2">
              <div class="flex items-center justify-between">
                <span class="text-xs font-bold text-indigo-700 bg-indigo-100/70 border border-indigo-200 px-2 py-0.5 rounded-md">
                  ${selectedLesson.subject}
                </span>
                <span class="text-xs font-mono font-bold text-slate-600">
                  ${selectedLesson.start_date} • ${selectedLesson.start_time}
                </span>
              </div>
              <div class="text-base font-black text-slate-900 font-display">${selectedLesson.student_name}</div>
              <div class="text-xs text-slate-600 font-medium leading-relaxed">${selectedLesson.topic}</div>
            </div>

            <!-- Primary 1-Click Action -->
            <a href="${selectedLesson.room_url}" target="_blank" class="tc-btn-primary w-full justify-center py-3 text-center">
              <i class="ph-bold ph-broadcast text-base"></i>
              <span>Войти в интерактивную комнату</span>
            </a>

            <!-- Status Tabs -->
            <div>
              <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Статус урока</div>
              <div class="grid grid-cols-2 gap-1.5">
                <button type="button" class="p-2 rounded-lg text-xs font-bold border border-slate-200 ${selectedLesson.status === 'planned' ? 'bg-indigo-50 border-indigo-300 text-indigo-700' : 'bg-white text-slate-600'}" onclick="window.TC.updateLessonStatus(${selectedLesson.lesson_id}, 'planned')">
                  Запланирован
                </button>
                <button type="button" class="p-2 rounded-lg text-xs font-bold border border-slate-200 ${selectedLesson.status === 'in_progress' ? 'bg-amber-50 border-amber-300 text-amber-700' : 'bg-white text-slate-600'}" onclick="window.TC.updateLessonStatus(${selectedLesson.lesson_id}, 'in_progress')">
                  Идёт
                </button>
                <button type="button" class="p-2 rounded-lg text-xs font-bold border border-slate-200 ${selectedLesson.status === 'completed' ? 'bg-emerald-50 border-emerald-300 text-emerald-700' : 'bg-white text-slate-600'}" onclick="window.TC.updateLessonStatus(${selectedLesson.lesson_id}, 'completed')">
                  Проведён
                </button>
                <button type="button" class="p-2 rounded-lg text-xs font-bold border border-slate-200 ${selectedLesson.status === 'cancelled' ? 'bg-rose-50 border-rose-300 text-rose-700' : 'bg-white text-slate-600'}" onclick="window.TC.updateLessonStatus(${selectedLesson.lesson_id}, 'cancelled')">
                  Отменён
                </button>
              </div>
            </div>

            <!-- Notes Section -->
            <div>
              <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Заметки к уроку</div>
              <textarea id="tc-lesson-notes-input" class="w-full h-20 p-2.5 rounded-xl border border-slate-200 text-xs font-medium text-slate-800 focus:outline-indigo-500 focus:border-indigo-500" placeholder="Заметки для подготовки или разбора...">${selectedLesson.notes || ''}</textarea>
              <button type="button" class="tc-btn-nav w-full justify-center mt-2" onclick="window.TC.saveLessonNotes(${selectedLesson.lesson_id})">
                Сохранить заметку
              </button>
            </div>

            <!-- Footer Reschedule Actions -->
            <div class="pt-3 border-t border-slate-200 flex items-center justify-between text-xs font-bold">
              <button type="button" class="text-indigo-600 hover:text-indigo-800 cursor-pointer" onclick="window.TC.openReschedulePrompt(${selectedLesson.lesson_id})">Перенести...</button>
              <button type="button" class="text-rose-600 hover:text-rose-800 cursor-pointer" onclick="window.TC.openCancelConfirm(${selectedLesson.lesson_id})">Отменить урок</button>
            </div>
          </div>
        `;
      } else {
        // Mode 1: Overview Mode (Next lesson hero + attention feed)
        const nextLesson = this.state.lessons.find(l => l.status === 'in_progress') || this.state.lessons[0];
        dock.innerHTML = `
          <div class="tc-dock-header">
            <div class="tc-dock-title">
              <i class="ph-bold ph-compass text-indigo-600 text-lg"></i>
              <span>Центр управления</span>
            </div>
            <span class="text-xs font-bold text-slate-400">Сегодня</span>
          </div>

          <div class="tc-dock-body">
            <!-- Hero Card: Next/Live Lesson -->
            ${nextLesson ? `
              <div class="tc-hero-card">
                <div class="tc-hero-badge">
                  <i class="ph-bold ${nextLesson.status === 'in_progress' ? 'ph-broadcast text-amber-600' : 'ph-clock text-indigo-600'}"></i>
                  <span>${nextLesson.status === 'in_progress' ? 'Идёт сейчас' : 'Ближайший урок'}</span>
                </div>
                <div class="tc-hero-student">${nextLesson.student_name}</div>
                <div class="tc-hero-topic">${nextLesson.start_time} — ${nextLesson.end_time} • ${nextLesson.topic}</div>
                <a href="${nextLesson.room_url}" target="_blank" class="tc-btn-primary w-full justify-center py-2.5">
                  <i class="ph-bold ph-door-open"></i>
                  <span>Войти в комнату</span>
                </a>
              </div>
            ` : ''}

            <!-- Attention Feed -->
            <div>
              <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Требует внимания</div>
              <div class="flex flex-col gap-2">
                <div class="p-3 rounded-xl bg-amber-50/60 border border-amber-200/80 flex items-center justify-between">
                  <div class="flex items-center gap-2.5">
                    <i class="ph-bold ph-pencil-simple text-amber-600 text-base"></i>
                    <div>
                      <div class="text-xs font-bold text-slate-900">Проверить ДЗ: demo_student_1</div>
                      <div class="text-[11px] text-slate-500">Домашняя работа — 12 заданий</div>
                    </div>
                  </div>
                  <span class="text-[10px] font-black text-amber-800 bg-amber-100 px-2 py-0.5 rounded-md">На проверке</span>
                </div>

                <div class="p-3 rounded-xl bg-indigo-50/60 border border-indigo-200/80 flex items-center justify-between">
                  <div class="flex items-center gap-2.5">
                    <i class="ph-bold ph-calendar-plus text-indigo-600 text-base"></i>
                    <div>
                      <div class="text-xs font-bold text-slate-900">Запрос слота: demo_student_2</div>
                      <div class="text-[11px] text-slate-500">Пятница 18:00 (Математика)</div>
                    </div>
                  </div>
                  <span class="text-[10px] font-black text-indigo-800 bg-indigo-100 px-2 py-0.5 rounded-md">Новый</span>
                </div>
              </div>
            </div>

            <!-- Quick Actions -->
            <div>
              <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Быстрые действия</div>
              <div class="grid grid-cols-2 gap-2">
                <button type="button" class="p-3 rounded-xl border border-slate-200 hover:border-slate-300 bg-white text-left transition cursor-pointer" onclick="window.TC.openFindTimeModal()">
                  <i class="ph-bold ph-sparkle text-indigo-600 text-lg mb-1 block"></i>
                  <div class="text-xs font-black text-slate-800">Найти окно</div>
                  <div class="text-[10px] text-slate-400">Свободные часы</div>
                </button>
                <button type="button" class="p-3 rounded-xl border border-slate-200 hover:border-slate-300 bg-white text-left transition cursor-pointer" onclick="window.openTeacherAvailabilityModal ? window.openTeacherAvailabilityModal() : null">
                  <i class="ph-bold ph-clock text-indigo-600 text-lg mb-1 block"></i>
                  <div class="text-xs font-black text-slate-800">График</div>
                  <div class="text-[10px] text-slate-400">Часы приёма</div>
                </button>
              </div>
            </div>
          </div>
        `;
      }
    }

    // Direct Manipulation (Drag & Drop with safe optimistic update in preview)
    handleCardPointerDown(e, lessonId) {
      if (e.button !== 0) return; // Left click only
      const cardEl = document.getElementById(`tc-card-${lessonId}`);
      if (!cardEl) return;

      const rect = cardEl.getBoundingClientRect();
      const lesson = this.state.lessons.find(l => l.lesson_id === lessonId);
      if (!lesson) return;

      this.state.drag = {
        active: false,
        lesson: lesson,
        startX: e.clientX,
        startY: e.clientY,
        offsetX: e.clientX - rect.left,
        offsetY: e.clientY - rect.top,
        width: rect.width,
        height: rect.height,
        ghostEl: null,
        targetCol: null,
        targetTime: null,
        isCollision: false
      };

      const moveHandler = (moveEvent) => {
        const dx = moveEvent.clientX - this.state.drag.startX;
        const dy = moveEvent.clientY - this.state.drag.startY;

        // 5px threshold to activate drag
        if (!this.state.drag.active && (Math.hypot(dx, dy) > 5)) {
          this.state.drag.active = true;
          this.createDragGhost();
        }

        if (this.state.drag.active) {
          this.updateDragGhost(moveEvent.clientX, moveEvent.clientY);
        }
      };

      const upHandler = () => {
        document.removeEventListener('pointermove', moveHandler);
        document.removeEventListener('pointerup', upHandler);

        if (this.state.drag.active) {
          this.commitDrag();
        }
      };

      document.addEventListener('pointermove', moveHandler);
      document.addEventListener('pointerup', upHandler);
    }

    createDragGhost() {
      const ghost = document.createElement('div');
      ghost.className = 'tc-drag-ghost';
      ghost.id = 'tc-drag-ghost';
      ghost.style.width = `${this.state.drag.width}px`;
      ghost.style.height = `${this.state.drag.height}px`;
      ghost.innerHTML = `
        <span class="tc-drag-pill" id="tc-drag-pill">${this.state.drag.lesson.start_time}</span>
        <div class="p-2.5">
          <div class="text-xs font-black text-slate-900">${this.state.drag.lesson.student_name}</div>
          <div class="text-[10px] text-slate-500 truncate">${this.state.drag.lesson.topic}</div>
        </div>
      `;
      document.body.appendChild(ghost);
      this.state.drag.ghostEl = ghost;
    }

    updateDragGhost(clientX, clientY) {
      const ghost = this.state.drag.ghostEl;
      if (!ghost) return;

      ghost.style.left = `${clientX - this.state.drag.offsetX}px`;
      ghost.style.top = `${clientY - this.state.drag.offsetY}px`;

      // Find day column under cursor
      const cols = document.querySelectorAll('.tc-day-column');
      let foundCol = null;
      cols.forEach(col => {
        const rect = col.getBoundingClientRect();
        if (clientX >= rect.left && clientX <= rect.right) {
          foundCol = col;
        }
      });

      if (foundCol) {
        const colRect = foundCol.getBoundingClientRect();
        const bodyEl = document.getElementById('tc-canvas-body');
        const scrollY = bodyEl ? bodyEl.scrollTop : 0;
        const relY = (clientY - this.state.drag.offsetY) - colRect.top + scrollY;

        // Calculate snapped 15-minute slot
        const rawHours = 7 + (relY / this.state.hourHeight);
        const snappedQuarter = Math.max(0, Math.min(68, Math.round((rawHours - 7) * 4)));
        const targetH = Math.floor(7 + snappedQuarter / 4);
        const targetM = (snappedQuarter % 4) * 15;
        const timeStr = `${String(targetH).padStart(2, '0')}:${String(targetM).padStart(2, '0')}`;

        this.state.drag.targetCol = foundCol.dataset.date;
        this.state.drag.targetTime = timeStr;

        const pill = document.getElementById('tc-drag-pill');
        if (pill) pill.textContent = timeStr;

        // Collision check
        const targetDur = this.state.drag.lesson.duration_minutes || 60;
        const targetEndMin = targetH * 60 + targetM + targetDur;

        const hasCollision = this.state.lessons.some(l => {
          if (l.lesson_id === this.state.drag.lesson.lesson_id) return false;
          if (l.start_date !== this.state.drag.targetCol) return false;
          const [sh, sm] = l.start_time.split(':').map(Number);
          const [eh, em] = l.end_time.split(':').map(Number);
          const lStart = sh * 60 + sm;
          const lEnd = eh * 60 + em;
          const targetStart = targetH * 60 + targetM;
          return (targetStart < lEnd && targetEndMin > lStart);
        });

        this.state.drag.isCollision = hasCollision;
        ghost.classList.toggle('is-collision', hasCollision);
        ghost.classList.toggle('is-valid', !hasCollision);
      }
    }

    async commitDrag() {
      const { ghostEl, lesson, targetCol, targetTime, isCollision } = this.state.drag;
      if (ghostEl) ghostEl.remove();

      if (targetCol && targetTime) {
        if (isCollision) {
          this.showToast('Невозможно перенести: обнаружен конфликт расписания', 'error');
          this.state.drag.active = false;
          return;
        }

        const oldDate = lesson.start_date;
        const oldTime = lesson.start_time;
        const oldEndTime = lesson.end_time;

        // Optimistic update
        lesson.start_date = targetCol;
        lesson.start_time = targetTime;
        lesson.end_time = this.calcEndTime(targetTime, lesson.duration_minutes);
        this.render();

        try {
          const res = await fetch(`/schedule/api/lesson/${lesson.lesson_id}/reschedule`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
              date: targetCol,
              time: targetTime,
              timezone: this.state.timezone
            })
          });

          const data = await res.json();
          if (res.ok && data.success) {
            this.showToast(`Урок перенесён на ${targetCol} ${targetTime}`, 'success');
          } else {
            // Rollback on conflict or failure
            lesson.start_date = oldDate;
            lesson.start_time = oldTime;
            lesson.end_time = oldEndTime;
            this.render();
            this.showToast(`Ошибка переноса: ${data.error || 'Конфликт времени'}`, 'error');
          }
        } catch (err) {
          lesson.start_date = oldDate;
          lesson.start_time = oldTime;
          lesson.end_time = oldEndTime;
          this.render();
          this.showToast('Ошибка сети при переносе урока', 'error');
        }
      }

      this.state.drag.active = false;
    }

    cancelDrag() {
      if (this.state.drag.ghostEl) {
        this.state.drag.ghostEl.remove();
      }
      this.state.drag.active = false;
      this.closeAllPopovers();
    }

    handleResizeDown(e, lessonId) {
      e.stopPropagation();
      e.preventDefault();
      const lesson = this.state.lessons.find(l => l.lesson_id === lessonId);
      if (!lesson) return;

      const cardEl = document.getElementById(`tc-card-${lessonId}`);
      if (!cardEl) return;

      const startY = e.clientY;
      const startDur = lesson.duration_minutes || 60;
      let newDur = startDur;

      const onMove = (moveEvent) => {
        const dy = moveEvent.clientY - startY;
        const dQuarters = Math.round(dy / (this.state.hourHeight / 4));
        newDur = Math.max(15, Math.min(240, startDur + dQuarters * 15));

        const newH = (newDur / 60) * this.state.hourHeight - 3;
        cardEl.style.height = `${newH}px`;
        const durLabel = cardEl.querySelector('.tc-card-duration');
        if (durLabel) durLabel.textContent = `${newDur}м`;
      };

      const onUp = async () => {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);

        if (newDur !== startDur) {
          const oldDur = lesson.duration_minutes;
          const oldEndTime = lesson.end_time;
          lesson.duration_minutes = newDur;
          lesson.end_time = this.calcEndTime(lesson.start_time, newDur);
          this.render();

          try {
            const res = await fetch(`/schedule/api/lesson/${lessonId}/update`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
              },
              body: JSON.stringify({ duration: newDur })
            });
            const data = await res.json();
            if (res.ok && data.success) {
              this.showToast(`Длительность урока изменена на ${newDur} мин`, 'success');
            } else {
              lesson.duration_minutes = oldDur;
              lesson.end_time = oldEndTime;
              this.render();
              this.showToast(`Ошибка изменения длительности: ${data.error || 'Сбой'}`, 'error');
            }
          } catch (err) {
            lesson.duration_minutes = oldDur;
            lesson.end_time = oldEndTime;
            this.render();
            this.showToast('Ошибка сети при изменении длительности', 'error');
          }
        }
      };

      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
    }

    // Navigation and View Switches
    navigateToday() {
      this.navigatePeriod(0);
    }

    navigatePeriod(dir) {
      if (dir === 0) {
        const currentParams = new URLSearchParams(window.location.search);
        if (currentParams.has('week_offset') && currentParams.get('week_offset') !== '0') {
          currentParams.delete('week_offset');
          window.location.search = currentParams.toString();
          return;
        }
        const todayDay = this.state.days.find(d => d.isToday);
        if (todayDay) {
          this.state.focusedDate = todayDay.date;
          this.render();
          this.scrollToActiveHours();
        }
        return;
      }

      if (this.state.view === 'day') {
        const curIdx = this.state.days.findIndex(d => d.date === this.state.focusedDate);
        if (curIdx !== -1) {
          const nextIdx = curIdx + dir;
          if (nextIdx >= 0 && nextIdx < this.state.days.length) {
            this.state.focusedDate = this.state.days[nextIdx].date;
            this.render();
            this.scrollToActiveHours();
            return;
          }
        }
      }

      const params = new URLSearchParams(window.location.search);
      const currentOffset = parseInt(params.get('week_offset') || '0', 10);
      params.set('week_offset', currentOffset + dir);
      window.location.search = params.toString();
    }

    switchView(viewName) {
      this.state.view = viewName;
      this.render();
      this.scrollToActiveHours();
    }

    zoomToDay(dateStr) {
      this.state.focusedDate = dateStr;
      this.state.view = 'focus';
      if (this.state.selectedLessonId) {
        const sel = this.state.lessons.find(l => l.lesson_id === this.state.selectedLessonId);
        if (sel && sel.start_date !== dateStr) {
          const dayFirst = this.state.lessons.find(l => l.start_date === dateStr);
          this.state.selectedLessonId = dayFirst ? dayFirst.lesson_id : null;
        }
      }
      this.render();
    }

    selectLesson(e, lessonId) {
      if (e) e.stopPropagation();
      this.state.selectedLessonId = lessonId;
      this.renderContextDock();

      document.querySelectorAll('.tc-lesson-card').forEach(el => {
        el.classList.toggle('is-selected', Number(el.dataset.id) === lessonId);
      });

      if (window.innerWidth <= 1440 && lessonId) {
        const dock = document.getElementById('tc-context-dock');
        const backdrop = document.getElementById('tc-dock-backdrop');
        if (dock) dock.classList.add('is-open');
        if (backdrop) backdrop.classList.add('is-open');
      }
    }

    toggleInspector(forceState) {
      const dock = document.getElementById('tc-context-dock');
      const backdrop = document.getElementById('tc-dock-backdrop');
      if (!dock) return;
      const isOpen = forceState !== undefined ? forceState : !dock.classList.contains('is-open');
      dock.classList.toggle('is-open', isOpen);
      if (backdrop) backdrop.classList.toggle('is-open', isOpen);
    }

    togglePopover(popoverId, triggerBtn) {
      const popover = document.getElementById(popoverId);
      if (!popover) return;

      const isCurrentlyOpen = !popover.classList.contains('is-hidden');
      this.closeAllPopovers();

      if (!isCurrentlyOpen) {
        popover.classList.remove('is-hidden');
        if (triggerBtn) triggerBtn.classList.add('is-active');
      }
    }

    closeAllPopovers() {
      document.querySelectorAll('.tc-popover').forEach(p => p.classList.add('is-hidden'));
      document.querySelectorAll('.tc-tool-btn').forEach(b => b.classList.remove('is-active'));
    }

    toggleLayer(layerKey, isEnabled) {
      this.state.layers[layerKey] = isEnabled;
      this.render();
    }

    toggleDensity() {
      this.state.hourHeight = this.state.hourHeight === 64 ? 48 : 64;
      this.render();
      this.showToast(`Плотность переключена: ${this.state.hourHeight === 64 ? 'Стандартная (64px)' : 'Компактная (48px)'}`);
    }

    openModal(modalId) {
      const el = document.getElementById(modalId);
      if (el) el.classList.remove('is-hidden');
    }

    closeModal(modalId) {
      const el = document.getElementById(modalId);
      if (el) el.classList.add('is-hidden');
    }

    openCreateLessonModal(dateStr, timeStr, duration) {
      const modal = document.getElementById('tc-modal-new-lesson');
      if (!modal) return;

      const dateInput = document.getElementById('tc-input-date');
      const timeInput = document.getElementById('tc-input-time');
      const durInput = document.getElementById('tc-input-duration');
      const errorBanner = document.getElementById('tc-create-error');

      if (dateInput) dateInput.value = dateStr || this.state.focusedDate || '2026-11-02';
      if (timeInput) timeInput.value = timeStr || '14:00';
      if (durInput && duration) durInput.value = String(duration);
      if (errorBanner) errorBanner.classList.add('hidden');

      this.openModal('tc-modal-new-lesson');
    }

    async handleCreateLessonSubmit(e) {
      e.preventDefault();
      const form = document.getElementById('tc-form-new-lesson');
      if (!form) return;

      const errorBanner = document.getElementById('tc-create-error');
      const errorMsg = document.getElementById('tc-create-error-msg');
      const submitBtn = document.getElementById('tc-btn-submit-lesson');

      const studentSelect = document.getElementById('tc-input-student');
      const studentId = studentSelect ? studentSelect.value : '';
      const studentName = studentSelect && studentSelect.selectedOptions[0] ? studentSelect.selectedOptions[0].text : 'Ученик';
      const subject = document.getElementById('tc-input-subject').value;
      const lessonDate = document.getElementById('tc-input-date').value;
      const lessonTime = document.getElementById('tc-input-time').value;
      const duration = parseInt(document.getElementById('tc-input-duration').value || '60', 10);
      const topic = document.getElementById('tc-input-topic').value;
      const notes = document.getElementById('tc-input-notes').value;

      if (!studentId || !lessonDate || !lessonTime) {
        if (errorBanner) {
          errorMsg.textContent = 'Заполните обязательные поля';
          errorBanner.classList.remove('hidden');
        }
        return;
      }

      const payload = {
        student_id: parseInt(studentId, 10),
        subject: subject,
        lesson_date: lessonDate,
        time: lessonTime,
        duration: duration,
        topic: topic,
        notes: notes,
        timezone: this.state.timezone
      };

      if (submitBtn) submitBtn.disabled = true;

      try {
        const res = await fetch('/api/schedule/create_lesson', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
          },
          body: JSON.stringify(payload)
        });

        const data = await res.json();

        if (res.ok && (data.status === 'success' || data.success)) {
          const newLessonId = data.lesson_id || Date.now();
          const newLesson = {
            lesson_id: newLessonId,
            student_id: parseInt(studentId, 10),
            student_name: studentName,
            start_date: lessonDate,
            start_time: lessonTime,
            end_time: this.calcEndTime(lessonTime, duration),
            duration_minutes: duration,
            subject: subject,
            topic: topic,
            notes: notes,
            status: 'planned',
            is_test: false,
            is_recurring: false,
            has_hw: false,
            hw_status: 'accepted',
            room_url: `/lessons/room/${newLessonId}`
          };

          this.state.lessons.push(newLesson);
          this.closeModal('tc-modal-new-lesson');
          form.reset();
          this.selectLesson(null, newLessonId);
          this.render();
          this.showToast('Урок успешно запланирован в расписании!', 'success');
        } else {
          const msg = data.message || data.error || 'Ошибка при создании урока';
          if (errorBanner) {
            errorMsg.textContent = msg;
            errorBanner.classList.remove('hidden');
          }
          this.showToast(`Ошибка: ${msg}`, 'error');
        }
      } catch (err) {
        if (errorBanner) {
          errorMsg.textContent = 'Ошибка сети при обращении к серверу';
          errorBanner.classList.remove('hidden');
        }
        this.showToast('Ошибка сети при сохранении урока', 'error');
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    }

    openReschedulePrompt(lessonId) {
      const lesson = this.state.lessons.find(l => l.lesson_id === lessonId);
      if (!lesson) return;

      const idInput = document.getElementById('tc-reschedule-lesson-id');
      const studentLabel = document.getElementById('tc-reschedule-student-label');
      const currentLabel = document.getElementById('tc-reschedule-current-label');
      const dateInput = document.getElementById('tc-reschedule-date');
      const timeInput = document.getElementById('tc-reschedule-time');
      const errorDiv = document.getElementById('tc-reschedule-error');

      if (idInput) idInput.value = lesson.lesson_id;
      if (studentLabel) studentLabel.textContent = `Ученик: ${lesson.student_name} (${lesson.subject})`;
      if (currentLabel) currentLabel.textContent = `Текущее время: ${lesson.start_date} ${lesson.start_time} (${lesson.duration_minutes} мин)`;
      if (dateInput) dateInput.value = lesson.start_date;
      if (timeInput) timeInput.value = lesson.start_time;
      if (errorDiv) errorDiv.classList.add('hidden');

      this.openModal('tc-modal-reschedule');
    }

    async handleRescheduleSubmit(e) {
      e.preventDefault();
      const idInput = document.getElementById('tc-reschedule-lesson-id');
      const dateInput = document.getElementById('tc-reschedule-date');
      const timeInput = document.getElementById('tc-reschedule-time');
      const errorDiv = document.getElementById('tc-reschedule-error');
      const submitBtn = document.getElementById('tc-btn-submit-reschedule');

      const lessonId = parseInt(idInput.value, 10);
      const newDate = dateInput.value;
      const newTime = timeInput.value;
      const lesson = this.state.lessons.find(l => l.lesson_id === lessonId);
      if (!lesson) return;

      if (submitBtn) submitBtn.disabled = true;

      try {
        const res = await fetch(`/schedule/api/lesson/${lessonId}/reschedule`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
          },
          body: JSON.stringify({
            date: newDate,
            time: newTime,
            timezone: this.state.timezone
          })
        });

        const data = await res.json();
        if (res.ok && data.success) {
          lesson.start_date = newDate;
          lesson.start_time = newTime;
          lesson.end_time = this.calcEndTime(newTime, lesson.duration_minutes);

          this.closeModal('tc-modal-reschedule');
          this.render();
          this.showToast(`Урок перенесён на ${newDate} ${newTime}`, 'success');
        } else {
          const msg = data.error || data.message || 'Ошибка переноса занятия';
          if (errorDiv) {
            errorDiv.textContent = msg;
            errorDiv.classList.remove('hidden');
          }
          this.showToast(`Конфликт: ${msg}`, 'error');
        }
      } catch (err) {
        if (errorDiv) {
          errorDiv.textContent = 'Сетевая ошибка при переносе урока';
          errorDiv.classList.remove('hidden');
        }
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    }

    openCancelConfirm(lessonId) {
      const lesson = this.state.lessons.find(l => l.lesson_id === lessonId);
      if (!lesson) return;

      const idInput = document.getElementById('tc-delete-lesson-id');
      const studentLabel = document.getElementById('tc-delete-student-label');
      if (idInput) idInput.value = lesson.lesson_id;
      if (studentLabel) studentLabel.textContent = `Ученик: ${lesson.student_name} (${lesson.start_date} ${lesson.start_time})`;

      this.openModal('tc-modal-confirm-delete');
    }

    async executeCancelLesson() {
      const idInput = document.getElementById('tc-delete-lesson-id');
      if (!idInput) return;
      const lessonId = parseInt(idInput.value, 10);
      const deleteBtn = document.getElementById('tc-btn-confirm-delete');

      if (deleteBtn) deleteBtn.disabled = true;

      try {
        const res = await fetch(`/schedule/api/lesson/${lessonId}/delete`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
          }
        });

        const data = await res.json();
        if (res.ok && (data.success || data.status === 'success')) {
          this.state.lessons = this.state.lessons.filter(l => l.lesson_id !== lessonId);
          this.state.selectedLessonId = null;
          this.closeModal('tc-modal-confirm-delete');
          this.render();
          this.showToast('Занятие успешно отменено и удалено из расписания', 'success');
        } else {
          this.showToast(`Ошибка отмены: ${data.error || 'Не удалось отменить'}`, 'error');
        }
      } catch (err) {
        this.showToast('Сетевая ошибка при отмене урока', 'error');
      } finally {
        if (deleteBtn) deleteBtn.disabled = false;
      }
    }

    async updateLessonStatus(lessonId, newStatus) {
      const lesson = this.state.lessons.find(l => l.lesson_id === lessonId);
      if (!lesson) return;

      try {
        const res = await fetch(`/schedule/api/lesson/${lessonId}/set-status`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
          },
          body: JSON.stringify({ status: newStatus })
        });

        const data = await res.json();
        if (res.ok && data.success) {
          lesson.status = newStatus;
          this.render();
          const statusLabels = { planned: 'Запланирован', in_progress: 'Идёт сейчас', completed: 'Проведён', cancelled: 'Отменён' };
          this.showToast(`Статус урока обновлен на «${statusLabels[newStatus] || newStatus}»`, 'success');
        } else {
          this.showToast(`Ошибка: ${data.error || 'Не удалось сменить статус'}`, 'error');
        }
      } catch (err) {
        this.showToast('Ошибка сети при обновлении статуса', 'error');
      }
    }

    async saveLessonNotes(lessonId) {
      const input = document.getElementById('tc-lesson-notes-input');
      const lesson = this.state.lessons.find(l => l.lesson_id === lessonId);
      if (!lesson || !input) return;

      const newNotes = input.value;

      try {
        const res = await fetch(`/api/schedule/update/${lessonId}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
          },
          body: JSON.stringify({ notes: newNotes })
        });

        const data = await res.json();
        if (res.ok && (data.success || data.status === 'success')) {
          lesson.notes = newNotes;
          this.showToast('Заметка успешно сохранена на сервере!', 'success');
        } else {
          this.showToast('Не удалось сохранить заметку', 'error');
        }
      } catch (err) {
        this.showToast('Ошибка сети при сохранении заметки', 'error');
      }
    }

    openFindTimeModal() {
      this.openModal('tc-modal-find-time');
      this.searchFreeSlots();
    }

    async searchFreeSlots() {
      const container = document.getElementById('tc-find-slots-list');
      const durSelect = document.getElementById('tc-find-duration');
      if (!container) return;

      const duration = durSelect ? durSelect.value : '60';
      container.innerHTML = `
        <div class="py-6 text-center text-xs font-bold text-slate-400 flex items-center justify-center gap-2">
          <i class="ph-bold ph-spinner animate-spin text-base"></i>
          <span>Поиск свободных окон...</span>
        </div>
      `;

      try {
        const res = await fetch(`/api/schedule/find-free-slots?duration=${duration}`);
        const data = await res.json();

        if (res.ok && data.success && Array.isArray(data.slots) && data.slots.length > 0) {
          container.innerHTML = data.slots.map(slot => `
            <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80 hover:border-indigo-300 flex items-center justify-between transition">
              <div>
                <div class="text-xs font-black text-slate-800 font-display">${slot.date_label || slot.date}</div>
                <div class="text-[11px] font-mono font-bold text-indigo-600">${slot.start_time} — ${slot.end_time} (${slot.duration} мин)</div>
              </div>
              <button type="button" class="tc-btn-primary py-1.5 px-3 text-xs"
                      onclick="window.TC.closeModal('tc-modal-find-time'); window.TC.openCreateLessonModal('${slot.date}', '${slot.start_time}', ${slot.duration})">
                <span>Выбрать</span>
              </button>
            </div>
          `).join('');
        } else {
          container.innerHTML = `
            <div class="py-6 text-center text-xs text-slate-400">
              Свободных окон в рабочие часы не найдено. Попробуйте выбрать меньшую длительность.
            </div>
          `;
        }
      } catch (err) {
        container.innerHTML = `
          <div class="py-6 text-center text-xs text-rose-500">
            Ошибка при поиске окон.
          </div>
        `;
      }
    }

    openCommandPalette() {
      this.openModal('tc-modal-cmd');
      const input = document.getElementById('tc-cmd-input');
      if (input) {
        input.value = '';
        input.focus();
        this.handleCommandInput('');
      }
    }

    handleCommandInput(query) {
      const listEl = document.getElementById('tc-cmd-list');
      if (!listEl) return;

      const q = (query || '').toLowerCase().trim();
      const commands = [
        { label: 'Вид: Неделя (7 дней)', action: () => this.switchView('week'), icon: 'ph-calendar' },
        { label: 'Вид: День (подробный)', action: () => this.switchView('day'), icon: 'ph-calendar-blank' },
        { label: 'Вид: Пространственный фокус', action: () => this.switchView('focus'), icon: 'ph-target' },
        { label: 'Вид: Месяц (обзор нагрузки)', action: () => this.switchView('month'), icon: 'ph-squares-four' },
        { label: 'Вид: Список (стрим)', action: () => this.switchView('stream'), icon: 'ph-list-dashes' },
        { label: 'Создать новое занятие', action: () => this.openCreateLessonModal(), icon: 'ph-plus-circle' },
        { label: 'Найти свободное окно (Smart Finder)', action: () => this.openFindTimeModal(), icon: 'ph-sparkle' },
        { label: 'Переключить плотность сетки', action: () => this.toggleDensity(), icon: 'ph-rows' },
        { label: 'Сбросить все фильтры', action: () => this.resetFilters(), icon: 'ph-arrow-counter-clockwise' }
      ];

      const students = this.state.accessibleStudents || [];
      students.forEach(s => {
        commands.push({
          label: `Фильтр по ученику: ${s.name}`,
          action: () => this.setFilter('student', s.student_id || s.id),
          icon: 'ph-user'
        });
      });

      const filtered = q ? commands.filter(c => c.label.toLowerCase().includes(q)) : commands;

      if (!filtered.length) {
        listEl.innerHTML = `<div class="p-4 text-center text-xs text-slate-400">Команды не найдены</div>`;
        return;
      }

      listEl.innerHTML = filtered.map((c, idx) => `
        <div class="tc-cmd-item ${idx === 0 ? 'is-selected' : ''}" onclick="window.TC.executeCommand(${idx})">
          <i class="ph-bold ${c.icon} text-slate-500 text-base"></i>
          <span>${c.label}</span>
        </div>
      `).join('');

      this._currentCommands = filtered;
    }

    executeCommand(idx) {
      if (this._currentCommands && this._currentCommands[idx]) {
        this.closeModal('tc-modal-cmd');
        this._currentCommands[idx].action();
      }
    }

    setFilter(type, value) {
      if (type === 'student' || type === 'studentId') {
        this.state.filters.studentId = value || null;
      } else if (type === 'subject') {
        this.state.filters.subject = value || null;
      } else if (type === 'status') {
        this.state.filters.status = value || null;
      } else if (type === 'search' || type === 'searchQuery') {
        this.state.filters.searchQuery = value || '';
      }
      this.render();
    }

    resetFilters() {
      this.state.filters.studentId = null;
      this.state.filters.subject = null;
      this.state.filters.status = null;
      this.state.filters.searchQuery = '';

      const studentSel = document.getElementById('tc-filter-student');
      const subjSel = document.getElementById('tc-filter-subject');
      const statusSel = document.getElementById('tc-filter-status');
      const searchInp = document.getElementById('tc-filter-search') || document.getElementById('tc-search-input');

      if (studentSel) studentSel.value = '';
      if (subjSel) subjSel.value = '';
      if (statusSel) statusSel.value = '';
      if (searchInp) searchInp.value = '';

      this.render();
      this.showToast('Фильтры сброшены', 'info');
    }

    getFilteredLessons() {
      let result = [...this.state.lessons];
      if (this.state.filters.studentId) {
        const sid = String(this.state.filters.studentId);
        result = result.filter(l => String(l.student_id) === sid);
      }
      if (this.state.filters.subject) {
        result = result.filter(l => l.subject === this.state.filters.subject);
      }
      if (this.state.filters.status) {
        result = result.filter(l => l.status === this.state.filters.status);
      }
      if (this.state.filters.searchQuery) {
        const q = this.state.filters.searchQuery.toLowerCase().trim();
        result = result.filter(l => 
          (l.student_name && l.student_name.toLowerCase().includes(q)) ||
          (l.topic && l.topic.toLowerCase().includes(q)) ||
          (l.subject && l.subject.toLowerCase().includes(q))
        );
      }
      return result;
    }

    scrollToActiveHours() {
      requestAnimationFrame(() => {
        const body = document.getElementById('tc-canvas-body') || document.getElementById('tc-focus-timeline');
        if (body) {
          body.scrollTop = 1.5 * this.state.hourHeight;
        }
      });
    }

    showToast(message, type = 'info') {
      const container = document.getElementById('tc-toast-container');
      if (!container) return;

      const toast = document.createElement('div');
      const bg = type === 'error' ? 'bg-rose-900 border-rose-700' : (type === 'success' ? 'bg-emerald-900 border-emerald-700' : 'bg-slate-900 border-slate-700');
      const icon = type === 'error' ? 'ph-warning-circle text-rose-300' : (type === 'success' ? 'ph-check-circle text-emerald-300' : 'ph-info text-indigo-300');

      toast.className = `px-4 py-2.5 rounded-xl ${bg} border text-white font-bold text-xs shadow-xl flex items-center gap-2 pointer-events-auto transition-all duration-200 transform translate-y-2 opacity-0`;
      toast.innerHTML = `<i class="ph-bold ${icon} text-base"></i><span>${message}</span>`;
      container.appendChild(toast);

      requestAnimationFrame(() => {
        toast.classList.remove('translate-y-2', 'opacity-0');
      });

      setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-2');
        setTimeout(() => toast.remove(), 250);
      }, 3500);
    }

    bindGlobalEvents() {
      document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          this.openCommandPalette();
          return;
        }

        if (e.key === 'Escape') {
          this.cancelDrag();
          this.closeAllPopovers();
          this.toggleInspector(false);
          document.querySelectorAll('.tc-modal-backdrop').forEach(m => m.classList.add('is-hidden'));
        }
      });

      document.addEventListener('click', (e) => {
        if (!e.target.closest('.tc-popover') && !e.target.closest('.tc-tool-btn')) {
          this.closeAllPopovers();
        }
      });
    }
  }

  // Mount to window
  window.addEventListener('DOMContentLoaded', () => {
    window.TC = new TemporalCanvasEngine();
  });
})();
