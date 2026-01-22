(() => {
  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const csrf = () =>
    document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
    document.body?.dataset?.csrfToken ||
    '';

  const postJSON = async (url, payload) => {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
      },
      body: JSON.stringify(payload || {}),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data?.success === false) {
      throw new Error(data?.error || `HTTP ${resp.status}`);
    }
    return data;
  };

  const scheduleRoot = qs('[data-schedule-root]');
  if (!scheduleRoot) return;

  const slotMinutes = parseInt(scheduleRoot.dataset.slotMinutes || '30', 10);
  const startHour = parseInt(scheduleRoot.dataset.startHour || '0', 10);
  const endHour = parseInt(scheduleRoot.dataset.endHour || '23', 10);
  const totalSlots = parseInt(scheduleRoot.dataset.totalSlots || '48', 10);
  const pxPerSlot = parseFloat(scheduleRoot.dataset.pxPerSlot || '28');

  const tz = scheduleRoot.dataset.timezone || 'moscow';
  const rescheduleUrlTpl = scheduleRoot.dataset.rescheduleUrlTpl || '';
  const setStatusUrlTpl = scheduleRoot.dataset.setStatusUrlTpl || '';
  const updateUrlTpl = scheduleRoot.dataset.updateUrlTpl || '';
  const deleteUrlTpl = scheduleRoot.dataset.deleteUrlTpl || '';
  const weekOffset = parseInt(scheduleRoot.dataset.weekOffset || '0', 10);
  const canManage = (scheduleRoot.dataset.canManage || '0') === '1';

  const iconRegular = scheduleRoot.dataset.iconRegular || '';
  const iconExam = scheduleRoot.dataset.iconExam || '';
  const iconIntro = scheduleRoot.dataset.iconIntro || '';

  const deck = qs('#scheduleGrid');
  const inspector = qs('#lessonInspector');
  const inspectorBody = qs('#lessonInspectorBody');
  const inspectorTitle = qs('#lessonInspectorTitle');
  const inspectorClose = qs('#lessonInspectorClose');

  const formatMinutes = (mins) => {
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  };

  const snapMinutes = (mins) => Math.round(mins / slotMinutes) * slotMinutes;

  const yToMinutes = (y) => {
    const slots = y / pxPerSlot;
    const mins = startHour * 60 + snapMinutes(slots * slotMinutes);
    return Math.max(startHour * 60, mins);
  };

  const minutesToY = (mins) => {
    const rel = mins - startHour * 60;
    return (rel / slotMinutes) * pxPerSlot;
  };

  const openInspector = (lessonEl) => {
    if (!inspector || !inspectorBody || !inspectorTitle) return;

    const meta = JSON.parse(lessonEl.dataset.meta || '{}');
    inspectorTitle.textContent = meta.student || 'Урок';
    
    // Извлекаем дату из родительской колонки дня
    const dayCol = lessonEl.closest('.day-col');
    const dayIso = dayCol?.dataset.day || '';
    
    // Парсим дату и время из meta или используем значения по умолчанию
    const startTime = meta.start_time || '';
    const dateValue = dayIso || '';
    const timeValue = startTime || '';

    const statusMap = {
      planned: 'Запланирован',
      in_progress: 'Идёт сейчас',
      completed: 'Проведён',
      cancelled: 'Отменён',
    };

    const lt = meta.lesson_type || 'regular';
    if (!canManage) {
      const lt = meta.lesson_type || 'regular';
      inspectorBody.innerHTML = `
        <div style="display:grid; gap:0.85rem;">
          <div style="display:grid; gap:0.4rem;">
            <div style="color:var(--text-muted); font-size:0.9rem;">Время</div>
            <div style="font-weight:900; font-size:1.1rem; color:var(--text-primary);">${meta.start_time || ''}</div>
          </div>
          <div style="display:grid; gap:0.4rem;">
            <div style="color:var(--text-muted); font-size:0.9rem;">Статус</div>
            <div style="font-weight:800;">${statusMap[meta.status_code] || meta.status_code || ''}</div>
          </div>
          <div style="display:grid; gap:0.4rem;">
            <div style="color:var(--text-muted); font-size:0.9rem;">Длительность</div>
            <div style="font-weight:800;">${meta.duration_minutes || 60} мин</div>
          </div>
          <div style="display:grid; gap:0.4rem;">
            <div style="color:var(--text-muted); font-size:0.9rem;">Тип</div>
            <div style="font-weight:800;">${lt}</div>
          </div>
          ${meta.topic ? `<div style="display:grid; gap:0.4rem;"><div style="color:var(--text-muted); font-size:0.9rem;">Тема</div><div style="font-weight:800;">${String(meta.topic)}</div></div>` : ''}
          <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
            ${meta.profile_url ? `<a class="neo-button ghost" href="${meta.profile_url}" style="text-decoration:none;">Профиль</a>` : ''}
            ${meta.lesson_url ? `<a class="neo-button accent" href="${meta.lesson_url}" style="text-decoration:none;">Открыть урок</a>` : ''}
          </div>
        </div>
      `;
      inspector.classList.add('is-open');
      return;
    }

    inspectorBody.innerHTML = `
      <div style="display:grid; gap:0.85rem;">
        <div class="neo-field">
          <label class="neo-label">Дата</label>
          <input class="neo-input" id="inspectorDate" type="date" value="${dateValue}">
        </div>

        <div class="neo-field">
          <label class="neo-label">Время</label>
          <input class="neo-input" id="inspectorTime" type="time" value="${timeValue}">
        </div>

        <div class="neo-field">
          <label class="neo-label">Статус</label>
          <select class="neo-select" id="inspectorStatus">
            <option value="planned" ${meta.status_code === 'planned' ? 'selected' : ''}>Запланирован</option>
            <option value="in_progress" ${meta.status_code === 'in_progress' ? 'selected' : ''}>Идёт сейчас</option>
            <option value="completed" ${meta.status_code === 'completed' ? 'selected' : ''}>Проведён</option>
            <option value="cancelled" ${meta.status_code === 'cancelled' ? 'selected' : ''}>Отменён</option>
          </select>
        </div>

        <div class="neo-field">
          <label class="neo-label">Длительность (мин)</label>
          <input class="neo-input" id="inspectorDuration" type="number" min="30" max="240" step="30" value="${meta.duration_minutes || 60}">
        </div>

        <div class="neo-field">
          <label class="neo-label">Тип урока</label>
          <select class="neo-select" id="inspectorLessonType">
            <option value="regular" ${lt === 'regular' ? 'selected' : ''}>Обычный</option>
            <option value="exam" ${lt === 'exam' ? 'selected' : ''}>Проверочный</option>
            <option value="introductory" ${lt === 'introductory' ? 'selected' : ''}>Вводный</option>
          </select>
        </div>

        <div class="neo-field">
          <label class="neo-label">Тема</label>
          <input class="neo-input" id="inspectorTopic" type="text" value="${meta.topic ? String(meta.topic).replace(/"/g, '&quot;') : ''}" placeholder="Опционально">
        </div>

        <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
          <a class="neo-button ghost" href="${meta.profile_url || '#'}" style="text-decoration:none;">Профиль</a>
          <a class="neo-button accent" href="${meta.lesson_url || '#'}" style="text-decoration:none;">Открыть урок</a>
          <button class="neo-button ghost" type="button" id="inspectorSave">Сохранить</button>
          <button class="neo-button danger" type="button" id="inspectorDelete">Удалить</button>
          <button class="neo-button outline" type="button" id="inspectorMakeRecurring">Сделать еженедельным</button>
        </div>

        <div style="color:var(--text-muted); font-size:0.9rem;">
          Перенос: перетащи карточку. Линия “сейчас” показывает текущее время.
        </div>
      </div>
    `;

    const dateInput = qs('#inspectorDate', inspectorBody);
    const timeInput = qs('#inspectorTime', inspectorBody);
    const statusSel = qs('#inspectorStatus', inspectorBody);
    const durationInput = qs('#inspectorDuration', inspectorBody);
    const lessonTypeSel = qs('#inspectorLessonType', inspectorBody);
    const topicInput = qs('#inspectorTopic', inspectorBody);
    const saveBtn = qs('#inspectorSave', inspectorBody);
    const deleteBtn = qs('#inspectorDelete', inspectorBody);
    const recurringBtn = qs('#inspectorMakeRecurring', inspectorBody);
    
    // Сохраняем ссылку на dayCol для использования в обработчике сохранения
    const currentDayCol = dayCol;

    saveBtn?.addEventListener('click', async () => {
      const nextStatus = statusSel?.value || meta.status_code;
      const nextDuration = durationInput?.value ? parseInt(durationInput.value, 10) : meta.duration_minutes;
      const nextType = lessonTypeSel?.value || meta.lesson_type || 'regular';
      const nextTopic = topicInput?.value ?? '';
      const nextDate = dateInput?.value || '';
      const nextTime = timeInput?.value || '';
      const currentTz = document.querySelector('[data-timezone-toggle]')?.dataset.timezone || 'moscow';

      try {
        // status
        if (nextStatus && nextStatus !== meta.status_code) {
          const url = setStatusUrlTpl.replace('0', String(meta.lesson_id));
          await postJSON(url, { status: nextStatus });
          meta.status_code = nextStatus;
          lessonEl.classList.remove('status-planned', 'status-in_progress', 'status-completed', 'status-cancelled');
          lessonEl.classList.add(`status-${nextStatus}`);
        }

        // other fields
        let resp = null;
        if (updateUrlTpl) {
          const url = updateUrlTpl.replace('0', String(meta.lesson_id));
          const payload = {
            duration: nextDuration,
            lesson_type: nextType,
            topic: nextTopic,
          };
          
          // Добавляем время, если оно изменилось
          if (nextDate && nextTime) {
            payload.lesson_date = nextDate;
            payload.lesson_time = nextTime;
            payload.timezone = currentTz;
          }
          
          resp = await postJSON(url, payload);
          meta.duration_minutes = resp?.lesson?.duration_minutes ?? nextDuration;
          meta.lesson_type = resp?.lesson?.lesson_type ?? nextType;
          meta.topic = resp?.lesson?.topic ?? nextTopic;
          
          // Обновляем время в meta, если оно изменилось
          if (nextDate && nextTime) {
            meta.start_date = nextDate;
            meta.start_time = nextTime;
          }
        } else {
          meta.duration_minutes = nextDuration;
          meta.lesson_type = nextType;
          meta.topic = nextTopic;
          if (nextDate && nextTime) {
            meta.start_date = nextDate;
            meta.start_time = nextTime;
          }
        }

        // resize card
        const height = Math.max((parseInt(meta.duration_minutes || '60', 10) / slotMinutes) * pxPerSlot - 4, pxPerSlot * 0.9);
        lessonEl.style.height = `${height}px`;

        // Обновляем время на карточке, если оно изменилось
        if (nextDate && nextTime) {
          const timeEl = lessonEl.querySelector('[data-role="time"]');
          if (timeEl) timeEl.textContent = nextTime;
          
          // Если изменилось время, нужно перерисовать карточку в новом месте
          const [hours, minutes] = nextTime.split(':').map(Number);
          const newStartTotal = hours * 60 + minutes;
          
          meta.start_total = newStartTotal;
          meta.start_time = nextTime;
          
          // Находим новую колонку дня
          const newDayCol = qs(`.day-col[data-day="${nextDate}"]`);
          if (newDayCol && newDayCol !== currentDayCol) {
            // Перемещаем карточку в новую колонку
            const newTop = minutesToY(newStartTotal);
            lessonEl.style.top = `${newTop}px`;
            newDayCol.appendChild(lessonEl);
          } else if (currentDayCol) {
            // Обновляем позицию в той же колонке
            const newTop = minutesToY(newStartTotal);
            lessonEl.style.top = `${newTop}px`;
          }
        }

        if (window.toast) window.toast.success('Сохранено');
      } catch (e) {
        if (window.toast) window.toast.error(e.message || 'Ошибка сохранения');
      }
    });

    deleteBtn?.addEventListener('click', async () => {
      if (!confirm('Удалить урок? Это действие нельзя отменить.')) return;
      try {
        if (!deleteUrlTpl) throw new Error('delete url not configured');
        const url = deleteUrlTpl.replace('0', String(meta.lesson_id));
        await postJSON(url, {});
        // remove chip
        lessonEl.remove();
        closeInspector();
        if (window.toast) window.toast.success('Урок удалён');
      } catch (e) {
        if (window.toast) window.toast.error(e.message || 'Ошибка удаления');
      }
    });

    recurringBtn?.addEventListener('click', async () => {
      try {
        const url = `/schedule/templates/api/from-lesson/${meta.lesson_id}`;
        await postJSON(url, { timezone: tz });
        if (window.toast) window.toast.success('Добавлено в автоплан');
      } catch (e) {
        if (window.toast) window.toast.error(e.message || 'Ошибка');
      }
    });

    inspector.classList.add('is-open');
  };

  const closeInspector = () => inspector?.classList.remove('is-open');
  inspectorClose?.addEventListener('click', closeInspector);

  const iconForLessonType = (lt) => {
    if (lt === 'exam') return iconExam;
    if (lt === 'introductory') return iconIntro;
    return iconRegular;
  };

  const renderLessonChip = (dayCol, ev) => {
    const el = document.createElement('div');
    el.className = `lesson-chip status-${ev.status_code || 'planned'}${ev.is_conflict ? ' is-conflict' : ''}`;
    el.style.left = `calc(${ev.left_percent || 0}% + 2px)`;
    el.style.width = `calc(${ev.width_percent || 100}% - 4px)`;
    el.dataset.statusCode = ev.status_code || 'planned';

    const top = minutesToY(parseInt(ev.start_total || '0', 10));
    const durationSlots = parseInt(ev.duration_minutes || '60', 10) / slotMinutes;
    const height = Math.max(
      durationSlots * pxPerSlot - 4,
      pxPerSlot * 0.9
    );
    el.style.top = `${top + 2}px`;
    el.style.height = `${height}px`;

    const meta = {
      lesson_id: ev.lesson_id,
      student: ev.student,
      student_id: ev.student_id,
      status: ev.status,
      status_code: ev.status_code,
      start_time: ev.start_time,
      duration_minutes: ev.duration_minutes,
      lesson_type: ev.lesson_type,
      topic: ev.topic,
      profile_url: ev.profile_url,
      lesson_url: ev.lesson_url,
    };
    el.dataset.meta = JSON.stringify(meta);

    const lt = ev.lesson_type || 'regular';
    const icon = iconForLessonType(lt);
    const topic = ev.topic ? String(ev.topic) : '';

    el.innerHTML = `
      <div class="lesson-chip__top">
        <div class="lesson-chip__time" data-role="time">${ev.start_time || ''}</div>
        ${icon ? `<img class="lesson-chip__icon" src="${icon}" alt="">` : ''}
      </div>
      <div class="lesson-chip__student">${ev.student || ''}</div>
      <div class="lesson-chip__meta">${topic ? topic : `${(ev.subject || 'Информатика')}${ev.grade ? ` · ${ev.grade}` : ''}`}</div>
    `;

    dayCol.querySelector('.day-col__body')?.appendChild(el);

    // View-only: click to open inspector (no drag)
    if (!canManage) {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        openInspector(el);
      });
    }
  };

  qsa('.day-col').forEach((dayCol) => {
    const eventsJson = dayCol.dataset.events;
    if (!eventsJson) return;
    try {
      const events = JSON.parse(eventsJson);
      if (!Array.isArray(events)) return;
      events.forEach((ev) => renderLessonChip(dayCol, ev));
    } catch (_) {}
  });

  // Click on grid -> create lesson at snapped time (only for managers)
  const createModal = qs('#createLessonModal');
  const createForm = qs('#createLessonForm');
  const modalDate = qs('#modalLessonDate');
  const modalTime = qs('#modalLessonTime');

  const openCreateModal = (dayIso, timeStr) => {
    if (modalDate) modalDate.value = dayIso;
    if (modalTime) modalTime.value = timeStr;
    createModal?.classList.add('active');
  };

  const closeCreateModal = () => createModal?.classList.remove('active');
  qsa('[data-modal-close="create"]').forEach((b) => b.addEventListener('click', closeCreateModal));
  createModal?.addEventListener('click', (e) => {
    if (e.target === createModal) closeCreateModal();
  });

  if (canManage) {
    qsa('.day-col__body').forEach((bodyEl) => {
      bodyEl.addEventListener('click', (e) => {
        if (e.target.closest('.lesson-chip')) return;
        const dayCol = e.currentTarget.closest('.day-col');
        if (!dayCol) return;
        const rect = bodyEl.getBoundingClientRect();
        const y = e.clientY - rect.top;
        const mins = yToMinutes(Math.max(0, y));
        openCreateModal(dayCol.dataset.day, formatMinutes(mins));
      });
    });
  }

  // Create lesson without reload
  if (canManage) createForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(createForm);
    const headers = { 'X-Requested-With': 'XMLHttpRequest' };
    const token = fd.get('csrf_token') || csrf();
    if (!fd.get('csrf_token') && token) fd.append('csrf_token', token);
    if (token) headers['X-CSRFToken'] = token;

    const btn = createForm.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const resp = await fetch(createForm.action, { method: 'POST', body: fd, headers });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data?.success === false) throw new Error(data?.error || `HTTP ${resp.status}`);

      closeCreateModal();
      if (window.toast) window.toast.success(data.message || 'Урок создан');

      const created = Array.isArray(data.created_lessons) ? data.created_lessons : [];
      created.forEach((ev) => {
        const dayIso = fd.get('lesson_date');
        const dayCol = qs(`.day-col[data-day="${dayIso}"]`);
        if (dayCol) renderLessonChip(dayCol, ev);
      });

      createForm.reset();
    } catch (err) {
      if (window.toast) window.toast.error(err.message || 'Ошибка создания урока');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // Drag & drop reschedule (only for managers)
  let drag = null;

  const onPointerDown = (e) => {
    const target = e.target.closest?.('.lesson-chip');
    if (!target) return;
    if (e.button !== 0) return;

    const dayCol = target.closest('.day-col');
    if (!dayCol) return;

    target.setPointerCapture?.(e.pointerId);

    const rect = dayCol.getBoundingClientRect();
    const offsetY = e.clientY - rect.top - parseFloat(target.style.top || '0');
    drag = {
      el: target,
      dayCol,
      dayIndex: parseInt(dayCol.dataset.dayIndex || '0', 10),
      offsetY,
      startX: e.clientX,
      startY: e.clientY,
      moved: false,
    };

    target.classList.add('is-dragging');
  };

  const onPointerMove = (e) => {
    if (!drag) return;
    const rect = drag.dayCol.getBoundingClientRect();
    const y = e.clientY - rect.top - drag.offsetY;
    const mins = yToMinutes(Math.max(0, y));

    drag.moved = true;
    drag.el.style.top = `${minutesToY(mins)}px`;
  };

  const onPointerUp = async (e) => {
    if (!drag) return;

    // Важно: сразу обрываем drag-состояние, чтобы карточка НЕ ехала за мышью во время await.
    const d = drag;
    drag = null;

    const { el, dayCol } = d;
    el.classList.remove('is-dragging');
    try { el.releasePointerCapture?.(e.pointerId); } catch (_) {}

    // If it was a click (no move) — open inspector
    if (!d.moved) {
      openInspector(el);
      return;
    }

    // Snap and persist
    const top = parseFloat(el.style.top || '0');
    const mins = yToMinutes(top);
    const timeStr = formatMinutes(mins);
    const dayIso = dayCol.dataset.day; // YYYY-MM-DD

    const meta = JSON.parse(el.dataset.meta || '{}');
    const url = rescheduleUrlTpl.replace('0', String(meta.lesson_id));

    try {
      await postJSON(url, { lesson_date: dayIso, lesson_time: timeStr, timezone: tz });
      meta.start_time = timeStr;
      el.dataset.meta = JSON.stringify(meta);
      el.querySelector('[data-role="time"]').textContent = timeStr;
      if (window.toast) window.toast.success('Перенесено');
    } catch (err) {
      if (window.toast) window.toast.error(err.message || 'Ошибка переноса');
      // rollback by reloading is safer for now
      setTimeout(() => window.location.reload(), 600);
    }
  };

  const onPointerCancel = (e) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    const { el } = d;
    el.classList.remove('is-dragging');
    try { el.releasePointerCapture?.(e.pointerId); } catch (_) {}
  };

  if (canManage) {
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('pointermove', onPointerMove, true);
    document.addEventListener('pointerup', onPointerUp, true);
    document.addEventListener('pointercancel', onPointerCancel, true);
  }

  // Линия текущего времени + автоскролл
  const tzName = tz === 'tomsk' ? 'Asia/Tomsk' : 'Europe/Moscow';

  const getNowInTz = () => {
    try {
      const parts = new Intl.DateTimeFormat('ru-RU', {
        timeZone: tzName,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).formatToParts(new Date());

      const map = {};
      parts.forEach((p) => { map[p.type] = p.value; });
      const y = map.year;
      const m = map.month;
      const d = map.day;
      const hh = parseInt(map.hour || '0', 10);
      const mm = parseInt(map.minute || '0', 10);
      return {
        iso: `${y}-${m}-${d}`,
        minutes: hh * 60 + mm,
      };
    } catch (_) {
      const now = new Date();
      return { iso: '', minutes: now.getHours() * 60 + now.getMinutes() };
    }
  };

  const placeNowLine = () => {
    const now = getNowInTz();
    if (!now.iso) return;
    const dayCol = qs(`.day-col[data-day="${now.iso}"]`);
    if (!dayCol) return;
    const body = qs('.day-col__body', dayCol);
    if (!body) return;

    let line = qs('.now-line', body);
    if (!line) {
      line = document.createElement('div');
      line.className = 'now-line';
      line.innerHTML = `<div class="now-dot"></div>`;
      body.appendChild(line);
    }
    line.style.top = `${minutesToY(now.minutes)}px`;

    // автоскролл к "сейчас" только на текущей неделе
    if (weekOffset === 0 && deck) {
      const targetTop = Math.max(minutesToY(now.minutes) - 220, 0);
      deck.scrollTo({ top: targetTop, behavior: 'smooth' });
    }
  };

  placeNowLine();
  setInterval(placeNowLine, 30_000);
})();


