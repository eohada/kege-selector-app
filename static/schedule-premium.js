window.initPremiumSchedule = () => {
  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const scheduleRoot = qs('[data-schedule-root]');
  if (!scheduleRoot) return;

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
  const inspectorSubtitle = qs('#lessonInspectorSubtitle');
  const inspectorClose = qs('#lessonInspectorClose');
  const inspectorIcon = qs('#lessonInspectorIcon');

  const formatMinutes = (mins) => {
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  };
  const formatDurationLabel = (mins) => {
    const total = parseInt(mins || '0', 10);
    const hours = Math.floor(total / 60);
    const rest = total % 60;
    if (hours > 0 && rest > 0) return `${hours} ч ${String(rest).padStart(2, '0')} мин`;
    if (hours > 0) return `${hours} ч 00 мин`;
    return `${total} мин`;
  };

  const snapMinutes = (mins) => Math.round(mins / slotMinutes) * slotMinutes;

  const yToMinutes = (y) => {
    const slots = y / pxPerSlot;
    const mins = startHour * 60 + snapMinutes(slots * slotMinutes);
    return Math.max(startHour * 60, mins);
  };

  const minutesToY = (mins) => {
    // Приводим любое время к ближайшему слоту сетки,
    // чтобы уроки не «наезжали» друг на друга из‑за разницы в пару минут.
    const snapped = startHour * 60 + snapMinutes(mins - startHour * 60);
    const rel = snapped - startHour * 60;
    return (rel / slotMinutes) * pxPerSlot;
  };

  const closeInspector = () => inspector?.classList.remove('is-open');
  inspectorClose?.addEventListener('click', closeInspector);

  const animateInspectorChange = (callback) => {
    const isOpen = inspector?.classList.contains('is-open');
    if (!isOpen) {
      callback();
      return;
    }

    const headerTitle = qs('#lessonInspectorHeaderTitle');
    const icon = qs('#lessonInspectorIcon');
    const title = qs('#lessonInspectorTitle');
    const subtitle = qs('#lessonInspectorSubtitle');
    const body = qs('#lessonInspectorBody');

    const els = [headerTitle, icon, title, subtitle, body].filter(Boolean);

    els.forEach(el => {
      el.style.transition = 'opacity 0.12s ease, transform 0.12s ease';
      el.style.opacity = '0';
      el.style.transform = 'translateY(6px)';
    });

    setTimeout(() => {
      callback();
      els.forEach(el => {
        el.offsetHeight; // force repaint
        el.style.opacity = '1';
        el.style.transform = 'translateY(0)';
      });
    }, 120);
  };

  const openInspector = (lessonEl) => {
    if (!inspector || !inspectorBody || !inspectorTitle) return;

    const meta = JSON.parse(lessonEl.dataset.meta || '{}');
    const dayCol = lessonEl.closest('.day-col');
    const dayIso = dayCol?.dataset.day || '';

    const startTime = meta.start_time || '';
    const dateValue = dayIso || '';
    const timeValue = startTime || '';

    const statusMap = {
      planned: 'Запланирован',
      in_progress: 'Идёт сейчас',
      completed: 'Проведён',
      cancelled: 'Отменён',
    };
    const statusDotClass = {
      planned: 'bg-[#F59E0B]',
      in_progress: 'bg-[#F59E0B]',
      completed: 'bg-emerald-500',
      cancelled: 'bg-rose-500',
    };
    const lt = meta.lesson_type || 'regular';

    animateInspectorChange(() => {
      const headerTitle = qs('#lessonInspectorHeaderTitle');
      if (headerTitle) headerTitle.textContent = 'Инспектор урока';

      inspectorTitle.textContent = meta.student || 'Урок';
      if (inspectorIcon) {
        const iconClass = (meta.lesson_type === 'exam')
          ? 'ph-bold ph-file-text text-2xl'
          : (meta.lesson_type === 'introductory' ? 'ph-bold ph-student text-2xl' : 'ph-bold ph-calendar-check text-2xl');
        inspectorIcon.innerHTML = `<i class="${iconClass}"></i>`;
      }

      if (inspectorSubtitle) {
        const st = statusMap[meta.status_code] || meta.status_code || '';
        const dotCls = statusDotClass[meta.status_code] || 'bg-slate-400';
        inspectorSubtitle.innerHTML = `<span class="inspector-status-badge"><span class="w-2 h-2 rounded-full ${dotCls}"></span>${st}</span>`;
      }

      if (!canManage) {
        inspectorBody.innerHTML = `
          <div class="space-y-2.5">
            <div>
              <div class="inspector-label">Время</div>
              <div class="inspector-input">${meta.start_time || ''}</div>
            </div>
            <div>
              <div class="inspector-label">Статус</div>
              <div class="inspector-input">${statusMap[meta.status_code] || meta.status_code || ''}</div>
            </div>
            <div>
              <div class="inspector-label">Длительность</div>
              <div class="inspector-input">${meta.duration_minutes || 60} мин</div>
            </div>
            <div>
              <div class="inspector-label">Тип занятия</div>
              <div class="inspector-input">${lt}</div>
            </div>
            ${meta.topic ? `<div><div class="inspector-label">Тема</div><div class="inspector-input">${String(meta.topic)}</div></div>` : ''}
            <div class="flex gap-2.5 mt-2">
              ${meta.profile_url
                ? `<a class="flex-1 py-2 bg-surface-alt border border-stroke text-secondary rounded-xl font-bold hover:bg-surface hover:text-primary transition-colors shadow-sm flex justify-center items-center gap-2 text-sm no-underline" href="${meta.profile_url}">Профиль</a>`
                : `<button class="flex-1 py-2 bg-surface-alt border border-stroke text-secondary rounded-xl font-bold transition-colors shadow-sm flex justify-center items-center gap-2 text-sm btn-disabled" type="button">Профиль</button>`}
              ${meta.lesson_url
                ? `<a class="flex-1 py-2 bg-purple-50 dark:bg-purple-950/30 border border-purple-100 dark:border-purple-900/30 text-boo-primary dark:text-purple-300 rounded-xl font-bold hover:bg-purple-100 dark:hover:bg-purple-900/40 transition-colors shadow-sm flex justify-center items-center gap-2 text-sm no-underline" href="${meta.lesson_url}">Урок</a>`
                : `<button class="flex-1 py-2 bg-purple-50 dark:bg-purple-950/30 border border-purple-100 dark:border-purple-900/30 text-boo-primary dark:text-purple-300 rounded-xl font-bold transition-colors shadow-sm flex justify-center items-center gap-2 text-sm btn-disabled" type="button">Урок</button>`}
            </div>
          </div>
        `;
        return;
      }

      inspectorBody.innerHTML = `
        <div class="space-y-2.5">
          <div class="inspector-grid-two">
            <div>
              <label class="inspector-label">Дата</label>
              <input class="inspector-input" id="inspectorDate" type="date" value="${dateValue}">
            </div>
            <div>
              <label class="inspector-label">Время</label>
              <input class="inspector-input" id="inspectorTime" type="time" value="${timeValue}">
            </div>
          </div>
          <div>
            <label class="inspector-label">Статус</label>
            <select class="inspector-input" id="inspectorStatus">
              <option value="planned" ${meta.status_code === 'planned' ? 'selected' : ''}>Запланирован</option>
              <option value="in_progress" ${meta.status_code === 'in_progress' ? 'selected' : ''}>Идёт сейчас</option>
              <option value="completed" ${meta.status_code === 'completed' ? 'selected' : ''}>Проведён</option>
              <option value="cancelled" ${meta.status_code === 'cancelled' ? 'selected' : ''}>Отменён</option>
            </select>
          </div>
          <div>
            <label class="inspector-label">Длительность (мин)</label>
            <input class="inspector-input" id="inspectorDuration" type="number" min="30" max="240" step="30" value="${meta.duration_minutes || 60}">
          </div>
          <div>
            <label class="inspector-label">Ученик</label>
            <div class="inspector-input">${meta.student || ''}</div>
          </div>
          <div>
            <label class="inspector-label">Тема урока</label>
            <input class="inspector-input" id="inspectorTopic" type="text" value="${meta.topic ? String(meta.topic).replace(/"/g, '&quot;') : ''}" placeholder="Введите тему (опционально)">
          </div>
          <div>
            <label class="inspector-label">Тип занятия</label>
            <select class="inspector-input" id="inspectorLessonType">
              <option value="regular" ${lt === 'regular' ? 'selected' : ''}>Обычный</option>
              <option value="exam" ${lt === 'exam' ? 'selected' : ''}>Проверочный</option>
              <option value="introductory" ${lt === 'introductory' ? 'selected' : ''}>Вводный</option>
            </select>
          </div>
          <div class="inspector-actions-sticky space-y-2">
            <button class="w-full py-2 bg-boo-primary text-white rounded-xl font-bold hover:bg-boo-primaryHover transition-all shadow-md border-b-[3px] border-b-purple-800 flex justify-center items-center gap-2 active:translate-y-1 active:border-b-0 text-sm" type="button" id="inspectorSave">
              Сохранить изменения
            </button>
            <div class="flex gap-2.5">
              ${meta.profile_url
                ? `<a class="flex-1 py-2 bg-surface-alt border border-stroke text-secondary rounded-xl font-bold hover:bg-surface hover:text-primary transition-colors shadow-sm flex justify-center items-center gap-2 text-sm no-underline" href="${meta.profile_url}">Профиль</a>`
                : `<button class="flex-1 py-2 bg-surface-alt border border-stroke text-secondary rounded-xl font-bold transition-colors shadow-sm flex justify-center items-center gap-2 text-sm btn-disabled" type="button">Профиль</button>`}
              <button class="flex-1 py-2 bg-red-50 dark:bg-red-950/20 border border-red-100 dark:border-red-900/30 text-boo-coral hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors shadow-sm flex justify-center items-center gap-2 text-sm" type="button" id="inspectorDelete">Удалить</button>
            </div>
            <button class="w-full py-2 bg-purple-50 dark:bg-purple-950/30 border border-purple-100 dark:border-purple-900/30 text-boo-primary dark:text-purple-300 rounded-xl font-bold hover:bg-purple-100 dark:hover:bg-purple-900/40 transition-colors shadow-sm flex justify-center items-center gap-2 text-sm" type="button" id="inspectorMakeRecurring">
              Сделать еженедельным
            </button>
          </div>
        </div>
      `;

      if (typeof window.initBooSelects === 'function') {
        try {
          window.initBooSelects(inspectorBody);
        } catch (e) { /* noop */ }
      }

      const dateInput = qs('#inspectorDate', inspectorBody);
      const timeInput = qs('#inspectorTime', inspectorBody);
      const statusSel = qs('#inspectorStatus', inspectorBody);
      const durationInput = qs('#inspectorDuration', inspectorBody);
      const lessonTypeSel = qs('#inspectorLessonType', inspectorBody);
      const topicInput = qs('#inspectorTopic', inspectorBody);
      const saveBtn = qs('#inspectorSave', inspectorBody);
      const deleteBtn = qs('#inspectorDelete', inspectorBody);
      const recurringBtn = qs('#inspectorMakeRecurring', inspectorBody);

      const currentDayCol = dayCol;

      saveBtn?.addEventListener('click', async () => {
        const nextStatus = statusSel?.value || meta.status_code;
        const nextDuration = durationInput?.value ? parseInt(durationInput.value, 10) : meta.duration_minutes;
        const nextType = lessonTypeSel?.value || meta.lesson_type || 'regular';
        const nextTopic = topicInput?.value ?? '';
        const nextDate = dateInput?.value || '';
        const nextTime = timeInput?.value || '';
        const currentTz = scheduleRoot.dataset.timezone || 'moscow';

        try {
          if (nextStatus && nextStatus !== meta.status_code) {
            const url = setStatusUrlTpl.replace('0', String(meta.lesson_id));
            await postJSON(url, { status: nextStatus });
            meta.status_code = nextStatus;
            lessonEl.classList.remove('status-planned', 'status-in_progress', 'status-completed', 'status-cancelled');
            lessonEl.classList.add(`status-${nextStatus}`);
          }

          let resp = null;
          if (updateUrlTpl) {
            const url = updateUrlTpl.replace('0', String(meta.lesson_id));
            const payload = {
              duration: nextDuration,
              lesson_type: nextType,
              topic: nextTopic,
            };

            if (nextDate && nextTime) {
              payload.lesson_date = nextDate;
              payload.lesson_time = nextTime;
              payload.timezone = currentTz;
            }

            resp = await postJSON(url, payload);
            meta.duration_minutes = resp?.lesson?.duration_minutes ?? nextDuration;
            meta.lesson_type = resp?.lesson?.lesson_type ?? nextType;
            meta.topic = resp?.lesson?.topic ?? nextTopic;

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

          const height = Math.max((parseInt(meta.duration_minutes || '60', 10) / slotMinutes) * pxPerSlot - 4, pxPerSlot * 0.9);
          lessonEl.style.height = `${height}px`;

          if (nextDate && nextTime) {
            const timeEl = lessonEl.querySelector('[data-role="time"]');
            if (timeEl) timeEl.textContent = nextTime;

            const [hours, minutes] = nextTime.split(':').map(Number);
            const newStartTotal = hours * 60 + minutes;

            meta.start_total = newStartTotal;
            meta.start_time = nextTime;

            const newDayCol = qs(`.day-col[data-day="${nextDate}"]`);
            if (newDayCol && newDayCol !== currentDayCol) {
              const newTop = minutesToY(newStartTotal);
              lessonEl.style.top = `${newTop}px`;
              newDayCol.appendChild(lessonEl);
            } else if (currentDayCol) {
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

  const iconHtml = (iconValue) => {
    if (!iconValue) return '';
    const v = String(iconValue);
    if (v.includes('#')) {
      const parts = v.split('#');
      const base = parts[0] || '';
      const id = parts.slice(1).join('#');
      const href = `${base}#${id}`;
      return `<svg class="lesson-chip__icon ui-icon ui-icon--sm ui-icon--only" aria-hidden="true" focusable="false"><use href="${href}"></use></svg>`;
    }
    return `<img class="lesson-chip__icon" src="${v}" alt="">`;
  };

  const renderLessonChip = (dayCol, ev) => {
    const el = document.createElement('div');
    el.className = `lesson-chip status-${ev.status_code || 'planned'}${ev.is_conflict ? ' is-conflict' : ''}`;
    el.style.left = `calc(${ev.left_percent || 0}% + 2px)`;
    el.style.width = `calc(${ev.width_percent || 100}% - 4px)`;
    el.dataset.statusCode = ev.status_code || 'planned';

    const top = minutesToY(parseInt(ev.start_total || '0', 10));
    const durationSlots = parseInt(ev.duration_minutes || '60', 10) / slotMinutes;
    const minCardHeight = 86;
    const height = Math.max(durationSlots * pxPerSlot - 4, minCardHeight);
    const maxTop = Math.max((totalSlots * pxPerSlot) - height - 2, 0);
    el.style.top = `${Math.min(top + 2, maxTop)}px`;
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
    const durationLabel = formatDurationLabel(ev.duration_minutes || 60);

    const initial = (ev.student || '?').trim().charAt(0).toUpperCase();
    const lessonTypeLabel = lt === 'exam' ? 'Проверочный' : (lt === 'introductory' ? 'Вводный' : 'Обычный');
    const statusClass = ev.status_code || 'planned';
    const showDot = statusClass === 'in_progress';
    const iconBox = statusClass === 'planned'
      ? 'w-6 h-6 rounded-md bg-white/20 border border-white/20 flex items-center justify-center backdrop-blur-sm'
      : 'w-2 h-2 rounded-full bg-[#F59E0B] mt-1';
    el.innerHTML = `
      <div class="lesson-chip__top">
        <div class="lesson-chip__time" data-role="time">${ev.start_time || ''}<br><span class="lesson-chip__duration">${durationLabel}</span></div>
        ${showDot ? `<div class="${iconBox}"></div>` : `<div class="${iconBox}">${iconHtml(icon)}</div>`}
      </div>
      <div class="lesson-chip__meta">${topic ? topic : lessonTypeLabel}</div>
      <div class="lesson-chip__student"><span class="lesson-chip__avatar">${initial}</span>${ev.student || ''}</div>
    `;

    dayCol.querySelector('.day-col__body')?.appendChild(el);

    if (!canManage) {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        openInspector(el);
      });
    }
  };

  qsa('.day-col').forEach((dayCol) => {
    const body = dayCol.querySelector('.day-col__body');
    if (body) {
      qsa('.lesson-chip', body).forEach(chip => chip.remove());
    }
    const eventsJson = dayCol.dataset.events;
    if (!eventsJson) return;
    try {
      const events = JSON.parse(eventsJson);
      if (!Array.isArray(events)) return;
      events.forEach((ev) => renderLessonChip(dayCol, ev));
    } catch (_) {}
  });

  window.openCreateLessonInInspector = (dayIso, timeStr) => {
    if (!inspector || !inspectorBody || !inspectorTitle) return;

    animateInspectorChange(() => {
      const headerTitle = qs('#lessonInspectorHeaderTitle');
      if (headerTitle) headerTitle.textContent = 'Создание урока';

      inspectorTitle.textContent = 'Новый урок';
      if (inspectorSubtitle) {
        inspectorSubtitle.innerHTML = '<span class="text-muted font-bold text-xs">Создание нового занятия</span>';
      }
      if (inspectorIcon) {
        inspectorIcon.innerHTML = `<i class="ph-bold ph-plus text-xl"></i>`;
      }

      const template = document.getElementById('createLessonFormTemplate');
      if (!template) return;

      inspectorBody.innerHTML = '';
      inspectorBody.appendChild(template.content.cloneNode(true));

      const form = qs('#createLessonForm', inspectorBody);
      const dateInput = qs('#modalLessonDate', form);
      const timeInput = qs('#modalLessonTime', form);
      const cancelBtn = qs('#createLessonCancel', form);
      const modeSel = qs('#modalLessonMode', form);
      const repeatGroup = qs('#repeatCountGroup', form);

      const defaultDate = (window.weekDaysIso && window.weekDaysIso.length ? window.weekDaysIso[0] : '');
      if (dateInput) dateInput.value = dayIso || defaultDate;
      if (timeInput) timeInput.value = timeStr || '18:00';

      cancelBtn?.addEventListener('click', () => {
        closeInspector();
      });

      modeSel?.addEventListener('change', () => {
        if (repeatGroup) {
          repeatGroup.style.display = (modeSel.value === 'recurring') ? 'block' : 'none';
        }
      });
    });

    inspector.classList.add('is-open');
  };

  if (canManage) {
    qsa('.day-col__body').forEach((bodyEl) => {
      bodyEl.addEventListener('click', (e) => {
        if (e.target.closest('.lesson-chip')) return;
        const dayCol = e.currentTarget.closest('.day-col');
        if (!dayCol) return;
        const rect = bodyEl.getBoundingClientRect();
        const y = e.clientY - rect.top;
        const mins = yToMinutes(Math.max(0, y));
        window.openCreateLessonInInspector(dayCol.dataset.day, formatMinutes(mins));
      });
    });
  }

  if (canManage) {
    document.addEventListener('submit', async (e) => {
      const form = e.target.closest('#createLessonForm');
      if (!form) return;

      e.preventDefault();
      const fd = new FormData(form);
      const headers = { 'X-Requested-With': 'XMLHttpRequest' };
      const token = fd.get('csrf_token') || csrf();
      if (!fd.get('csrf_token') && token) fd.append('csrf_token', token);

      const btn = form.querySelector('button[type="submit"]');
      let originalText = 'Создать';
      let safetyTimeout;
      if (btn) {
        if (btn.disabled) return;
        originalText = btn.textContent || 'Создать';
        btn.disabled = true;
        btn.textContent = 'Создание...';
        safetyTimeout = setTimeout(() => {
          btn.disabled = false;
          btn.textContent = originalText;
        }, 8000);
      }

      try {
        const resp = await fetch(form.action, { method: 'POST', body: fd, headers });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || data?.success === false) throw new Error(data?.error || `HTTP ${resp.status}`);

        closeInspector();
        if (window.toast) window.toast.success(data.message || 'Урок создан');

        const mode = fd.get('lesson_mode');
        if (mode === 'recurring') {
          setTimeout(() => window.location.reload(), 250);
        } else {
          const created = Array.isArray(data.created_lessons) ? data.created_lessons : [];
          created.forEach((ev) => {
            const dayIso = fd.get('lesson_date');
            const dayCol = qs(`.day-col[data-day="${dayIso}"]`);
            if (dayCol) renderLessonChip(dayCol, ev);
          });
        }
      } catch (err) {
        if (window.toast) window.toast.error(err.message || 'Ошибка создания урока');
      } finally {
        if (btn) {
          clearTimeout(safetyTimeout);
          btn.disabled = false;
          btn.textContent = originalText;
        }
      }
    });
  }

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

    const d = drag;
    drag = null;

    const { el, dayCol } = d;
    el.classList.remove('is-dragging');
    try { el.releasePointerCapture?.(e.pointerId); } catch (_) {}

    if (!d.moved) {
      openInspector(el);
      return;
    }

    const top = parseFloat(el.style.top || '0');
    const mins = yToMinutes(top);
    const timeStr = formatMinutes(mins);
    const dayIso = dayCol.dataset.day;

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
    if (window.__onPointerDown) {
      document.removeEventListener('pointerdown', window.__onPointerDown, true);
      document.removeEventListener('pointermove', window.__onPointerMove, true);
      document.removeEventListener('pointerup', window.__onPointerUp, true);
      document.removeEventListener('pointercancel', window.__onPointerCancel, true);
    }
    window.__onPointerDown = onPointerDown;
    window.__onPointerMove = onPointerMove;
    window.__onPointerUp = onPointerUp;
    window.__onPointerCancel = onPointerCancel;

    document.addEventListener('pointerdown', window.__onPointerDown, true);
    document.addEventListener('pointermove', window.__onPointerMove, true);
    document.addEventListener('pointerup', window.__onPointerUp, true);
    document.addEventListener('pointercancel', window.__onPointerCancel, true);
  }

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
      line.innerHTML = `<div class="now-label"></div><div class="now-dot"></div>`;
      body.appendChild(line);
    }
    const label = qs('.now-label', line);
    if (label) label.textContent = formatMinutes(now.minutes);
    line.style.top = `${minutesToY(now.minutes)}px`;

    if (weekOffset === 0 && deck) {
      const targetTop = Math.max(minutesToY(now.minutes) - 220, 0);
      deck.scrollTo({ top: targetTop, behavior: 'smooth' });
    }
  };

  placeNowLine();

  if (window.__nowLineInterval) clearInterval(window.__nowLineInterval);
  window.__nowLineInterval = setInterval(placeNowLine, 30_000);
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => window.initPremiumSchedule());
} else {
  window.initPremiumSchedule();
}

