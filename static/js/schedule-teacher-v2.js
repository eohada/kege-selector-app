(() => {
  const boot = () => {
    const source = document.getElementById('schedule-data');
    if (!source) return;

    const raw = JSON.parse(source.textContent || '{}');
    const state = {
      week: Number(raw.week_offset || 0),
      weekdays: Array.isArray(raw.weekdays) ? raw.weekdays : [],
      lessons: Array.isArray(raw.lessons) ? raw.lessons : [],
      view: 'week',
    };
    const pad = (value) => String(value).padStart(2, '0');
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[char]));
    const toast = (message, kind = 'error') => {
      if (typeof window.showBentoToast === 'function') return window.showBentoToast(message, kind);
      let notice = document.getElementById('schedule-v2-notice');
      if (!notice) {
        notice = document.createElement('div');
        notice.id = 'schedule-v2-notice';
        notice.className = 'fixed right-6 bottom-6 z-[100] max-w-sm rounded-2xl border-2 border-rose-200 bg-white px-4 py-3 text-sm font-bold text-slate-700 shadow-[0_4px_0_#DAE1E9]';
        document.body.appendChild(notice);
      }
      notice.textContent = message;
      notice.classList.remove('hidden');
      window.setTimeout(() => notice.classList.add('hidden'), 4000);
    };

    const decorate = (lesson) => {
      const fallback = new Date(lesson.start_iso || lesson.lesson_date);
      const fallbackValid = !Number.isNaN(fallback.getTime());
      lesson.start_date = lesson.start_date || (fallbackValid ? fallback.toLocaleDateString('en-CA') : '');
      lesson.start_time = lesson.start_time || (fallbackValid
        ? fallback.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '');
      lesson.end_time = lesson.end_time || (fallbackValid
        ? new Date(fallback.getTime() + Number(lesson.duration_minutes || 60) * 60000)
          .toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '');
      lesson.top = Number.isFinite(Number(lesson.grid_top))
        ? Number(lesson.grid_top)
        : (fallbackValid ? fallback.getHours() * 60 + fallback.getMinutes() : 0);
      lesson.height = Math.max(28, Number(lesson.duration_minutes || 60));
      lesson.day = state.weekdays.findIndex((day) => day.iso === lesson.start_date);
      return lesson;
    };
    state.lessons = state.lessons.map(decorate);

    const visibleLessons = () => {
      const type = document.getElementById('filter-type')?.value || 'all';
      const student = document.getElementById('filter-student')?.value || 'all';
      return state.lessons.filter((lesson) => (
        (type === 'all' || lesson.lesson_type === type)
        && (student === 'all' || String(lesson.student_id) === student)
      ));
    };

    const updateCounters = (lessons) => {
      const total = document.getElementById('stat-total');
      const done = document.getElementById('stat-done');
      if (total) total.textContent = String(lessons.length);
      if (done) done.textContent = String(lessons.filter((lesson) => lesson.status === 'completed').length);
    };

    const renderWeek = () => {
      const head = document.getElementById('days-header');
      const rows = document.getElementById('hour-rows');
      const columns = document.getElementById('lessons-cols');
      if (!head || !rows || !columns) return;

      head.innerHTML = '<div class="flex items-center justify-center border-r border-slate-200 bg-slate-50 py-3"><span class="text-[10px] font-black text-slate-400 uppercase">Время</span></div>'
        + state.weekdays.map((day, index) => `<div class="p-3 text-center border-r border-slate-200 ${day.is_today ? 'bg-indigo-50/60 border-t-4 border-t-indigo-600' : 'bg-white'}"><div class="text-xs font-bold ${day.is_today ? 'text-indigo-600' : index > 4 ? 'text-rose-400' : 'text-slate-500'}">${escapeHtml(day.name)}</div><div class="text-base font-black text-slate-800">${escapeHtml(day.date)}</div></div>`).join('');
      rows.innerHTML = Array.from({ length: 24 }, (_, hour) => `<div class="hour-row-slot group"><div class="hour-label border-r border-slate-200"><span>${pad(hour)}:00</span></div>${state.weekdays.map((day) => `<div class="border-r border-slate-200 relative cursor-pointer" onclick="openNewLessonModal(${hour}, '${escapeHtml(day.iso)}')"></div>`).join('')}</div>`).join('');

      const byDay = state.weekdays.map(() => []);
      const lessons = visibleLessons();
      lessons.forEach((lesson) => { if (lesson.day >= 0) byDay[lesson.day].push(lesson); });
      columns.innerHTML = byDay.map((items) => `<div class="lessons-col">${items.map((lesson) => `<button type="button" class="lesson-card color-indigo text-left" style="top:${lesson.top}px;height:${lesson.height}px" onclick="openLessonView(${Number(lesson.lesson_id)})"><div class="font-extrabold truncate">${escapeHtml(lesson.topic)}</div><div class="text-[10px] opacity-70">${escapeHtml(lesson.start_time)} – ${escapeHtml(lesson.end_time)}</div></button>`).join('')}</div>`).join('');
      updateCounters(lessons);
    };

    const localDate = (iso) => new Date(`${iso}T12:00:00`);
    const renderMonth = () => {
      const grid = document.getElementById('month-grid');
      if (!grid) return;
      const anchor = localDate(state.weekdays[0]?.iso || new Date().toLocaleDateString('en-CA'));
      const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
      const daysInMonth = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0).getDate();
      const before = (first.getDay() + 6) % 7;
      const cells = Array(before).fill(null).concat(Array.from({ length: daysInMonth }, (_, index) => new Date(anchor.getFullYear(), anchor.getMonth(), index + 1)));
      while (cells.length % 7) cells.push(null);
      const lessons = visibleLessons();
      grid.innerHTML = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((name) => `<div class="p-2 text-center text-[10px] font-black text-slate-400 border-b border-slate-200">${name}</div>`).join('')
        + cells.map((day) => {
          if (!day) return '<div class="min-h-[100px] bg-slate-50 border-r border-b border-slate-200"></div>';
          const iso = `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
          return `<div class="min-h-[100px] p-2 border-r border-b border-slate-200"><div class="text-xs font-black">${day.getDate()}</div>${lessons.filter((lesson) => lesson.start_date === iso).map((lesson) => `<button type="button" class="block w-full truncate text-left text-[10px] text-indigo-700 font-bold" onclick="openLessonView(${Number(lesson.lesson_id)})">${escapeHtml(lesson.start_time)} ${escapeHtml(lesson.topic)}</button>`).join('')}</div>`;
        }).join('');
      updateCounters(lessons);
    };

    window.switchView = (view) => {
      state.view = view === 'month' ? 'month' : 'week';
      const week = document.getElementById('view-week');
      const month = document.getElementById('view-month');
      if (week) week.style.display = state.view === 'week' ? '' : 'none';
      if (month) month.style.display = state.view === 'month' ? '' : 'none';
      if (state.view === 'week') renderWeek(); else renderMonth();
    };
    window.navigateWeek = (delta) => {
      const params = new URLSearchParams(window.location.search);
      params.set('week', String(state.week + Number(delta || 0)));
      window.location.assign(`${raw.base_url || '/schedule'}?${params.toString()}`);
    };
    window.applyFilters = () => window.switchView(state.view);
    window.changeTimezone = (value) => {
      const params = new URLSearchParams(window.location.search);
      params.set('timezone', String(value).toLowerCase().includes('novosibirsk') ? 'tomsk' : 'moscow');
      window.location.assign(`${raw.base_url || '/schedule'}?${params.toString()}`);
    };
    window.openNewLessonModal = (hour, date) => {
      const time = document.getElementById('input-start-time');
      const inputDate = document.getElementById('input-lesson-date');
      if (time) time.value = `${pad(hour ?? 16)}:00`;
      if (inputDate) inputDate.value = date || state.weekdays[0]?.iso || '';
      document.getElementById('modal-new-lesson')?.classList.remove('hidden');
    };
    window.closeNewLessonModal = () => document.getElementById('modal-new-lesson')?.classList.add('hidden');
    window.openLessonView = (id) => {
      const lesson = state.lessons.find((item) => Number(item.lesson_id) === Number(id));
      if (!lesson) return;
      document.getElementById('view-lesson-topic').textContent = lesson.topic || 'Урок';
      document.getElementById('view-lesson-time').textContent = `${lesson.start_time} – ${lesson.end_time}`;
      document.getElementById('view-lesson-duration').textContent = `${lesson.duration_minutes} мин`;
      const status = document.getElementById('view-lesson-status');
      if (status) status.value = lesson.status || 'planned';
      document.getElementById('join-room-link').href = lesson.room_url || `/lesson/${lesson.lesson_id}/room`;
      document.getElementById('modal-lesson-view').dataset.lessonId = String(lesson.lesson_id);
      document.getElementById('modal-lesson-view')?.classList.remove('hidden');
    };
    window.saveLessonStatus = async () => {
      const modal = document.getElementById('modal-lesson-view');
      const lessonId = modal?.dataset.lessonId;
      const status = document.getElementById('view-lesson-status')?.value;
      if (!lessonId || !status) return;
      try {
        const response = await fetch(`/schedule/api/lesson/${lessonId}/set-status`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' },
          body: JSON.stringify({ status }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) throw new Error(data.error || 'Не удалось сохранить статус');
        window.location.reload();
      } catch (error) {
        toast(error.message || 'Не удалось сохранить статус');
      }
    };
    window.handleCreateLesson = async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const submit = form.querySelector('button[type="submit"]');
      const studentId = document.getElementById('input-student-id')?.value;
      const lessonDate = document.getElementById('input-lesson-date')?.value;
      const startTime = document.getElementById('input-start-time')?.value;
      const topic = document.getElementById('input-topic')?.value.trim();
      if (!studentId) return toast('Выберите ученика для урока');
      if (!lessonDate || !startTime || !topic) return toast('Заполните тему, дату и время урока');
      if (submit) submit.disabled = true;
      try {
        const response = await fetch('/api/schedule/create_lesson', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' },
          body: JSON.stringify({
            student_id: Number(studentId), lesson_date: lessonDate, time: startTime,
            duration: Number(document.getElementById('input-duration')?.value || 60),
            lesson_type: document.getElementById('input-lesson-type')?.value || 'individual',
            topic, timezone: raw.timezone || 'moscow',
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !(data.success || data.status === 'success')) throw new Error(data.message || data.error || 'Не удалось создать урок');
        window.location.reload();
      } catch (error) {
        toast(error.message || 'Не удалось создать урок');
      } finally {
        if (submit) submit.disabled = false;
      }
    };
    window.switchView('week');
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
