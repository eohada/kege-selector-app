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
  const startHour = parseInt(scheduleRoot.dataset.startHour || '7', 10);
  const pxPerSlot = parseFloat(scheduleRoot.dataset.pxPerSlot || '28');

  const tz = scheduleRoot.dataset.timezone || 'moscow';
  const rescheduleUrlTpl = scheduleRoot.dataset.rescheduleUrlTpl || '';
  const setStatusUrlTpl = scheduleRoot.dataset.setStatusUrlTpl || '';

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

    const statusMap = {
      planned: 'Запланирован',
      in_progress: 'Идёт сейчас',
      completed: 'Проведён',
      cancelled: 'Отменён',
    };

    inspectorBody.innerHTML = `
      <div style="display:grid; gap:0.6rem;">
        <div><strong>Время:</strong> ${meta.start_time || ''}</div>
        <div><strong>Статус:</strong> ${statusMap[meta.status_code] || meta.status || ''}</div>
        <div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-top:0.4rem;">
          <a class="neo-button ghost" href="${meta.profile_url || '#'}" style="text-decoration:none;">Профиль</a>
          <a class="neo-button accent" href="${meta.lesson_url || '#'}" style="text-decoration:none;">Открыть урок</a>
          <button class="neo-button ghost" type="button" data-set-status="planned">План</button>
          <button class="neo-button ghost" type="button" data-set-status="completed">Проведён</button>
          <button class="neo-button danger" type="button" data-set-status="cancelled">Отменить</button>
        </div>
        <div style="color:var(--text-muted); font-size:0.9rem; margin-top:0.4rem;">
          Перенос: просто перетащи карточку в другой слот.
        </div>
      </div>
    `;

    qsa('[data-set-status]', inspectorBody).forEach((btn) => {
      btn.addEventListener('click', async () => {
        const newStatus = btn.dataset.setStatus;
        const url = setStatusUrlTpl.replace('0', String(meta.lesson_id));
        try {
          await postJSON(url, { status: newStatus });
          meta.status_code = newStatus;
          lessonEl.dataset.meta = JSON.stringify(meta);
          lessonEl.dataset.statusCode = newStatus;
          lessonEl.classList.remove('status-planned', 'status-in_progress', 'status-completed', 'status-cancelled');
          lessonEl.classList.add(`status-${newStatus}`);
          if (window.toast) window.toast.success('Статус обновлён');
        } catch (e) {
          if (window.toast) window.toast.error(e.message || 'Ошибка обновления статуса');
        }
      });
    });

    inspector.classList.add('is-open');
  };

  const closeInspector = () => inspector?.classList.remove('is-open');
  inspectorClose?.addEventListener('click', closeInspector);

  const renderLessonChip = (dayCol, ev) => {
    const el = document.createElement('div');
    el.className = `lesson-chip status-${ev.status_code || 'planned'}`;
    el.style.left = `calc(${ev.left_percent || 0}% + 2px)`;
    el.style.width = `calc(${ev.width_percent || 100}% - 4px)`;
    el.dataset.statusCode = ev.status_code || 'planned';

    const top = minutesToY(parseInt(ev.start_total || '0', 10));
    const height = Math.max(
      (parseInt(ev.duration_minutes || '60', 10) / slotMinutes) * pxPerSlot - 4,
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
      profile_url: ev.profile_url,
      lesson_url: ev.lesson_url,
    };
    el.dataset.meta = JSON.stringify(meta);

    el.innerHTML = `
      <div class="lesson-chip__time" data-role="time">${ev.start_time || ''}</div>
      <div class="lesson-chip__student">${ev.student || ''}</div>
      <div class="lesson-chip__meta">${(ev.subject || 'Информатика')}${ev.grade ? ` · ${ev.grade}` : ''}</div>
    `;

    dayCol.querySelector('.day-col__body')?.appendChild(el);
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

  // Click on grid -> create lesson at snapped time
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
  qs('[data-modal-close="create"]')?.addEventListener('click', closeCreateModal);
  createModal?.addEventListener('click', (e) => {
    if (e.target === createModal) closeCreateModal();
  });

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

  // Create lesson without reload
  createForm?.addEventListener('submit', async (e) => {
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

  // Drag & drop reschedule
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
    const { el, dayCol } = drag;
    el.classList.remove('is-dragging');

    // If it was a click (no move) — open inspector
    if (!drag.moved) {
      openInspector(el);
      drag = null;
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
    } finally {
      drag = null;
    }
  };

  document.addEventListener('pointerdown', onPointerDown, true);
  document.addEventListener('pointermove', onPointerMove, true);
  document.addEventListener('pointerup', onPointerUp, true);
})();


