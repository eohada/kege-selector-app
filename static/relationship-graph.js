(function () {
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  function safeJsonParse(s, fallback) {
    try { return JSON.parse(s); } catch { return fallback; }
  }

  function nowMs() { return Date.now ? Date.now() : +new Date(); }

  function getCSRFToken(explicit) {
    if (explicit) return explicit;
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? (meta.getAttribute('content') || '') : '';
  }

  function createSvgEl(name) {
    return document.createElementNS('http://www.w3.org/2000/svg', name);
  }

  function edgeKey(e) {
    const id = e.kind === 'family' ? e.tie_id : e.enrollment_id;
    return `${e.kind}:${e.from_id}->${e.to_id}:${id}`;
  }

  function pairKey(e) {
    return `${e.kind}:${e.from_id}->${e.to_id}`;
  }

  function defaultRoleLabel(role) {
    if (role === 'tutor') return 'Преподаватель';
    if (role === 'student') return 'Ученик';
    if (role === 'parent') return 'Родитель';
    return role || '—';
  }

  class RelationshipGraph {
    constructor(rootEl, opts) {
      this.rootEl = rootEl;
      this.opts = opts || {};

      this.state = {
        tx: 60,
        ty: 60,
        scale: 1,
        draggingPan: false,
        draggingNodeId: null,
        dragStart: null,
        lastDrawAt: 0,
      };

      this.data = null;
      this.nodeEls = new Map();
      this.edgeIndexByPair = new Map();
      this.currentEdge = null; // {kind, id}
      this.selectedNodeId = null;

      this._buildUI();
      this._bindUI();
    }

    _buildUI() {
      const cs = getCSRFToken(this.opts.csrfToken);
      this.csrfToken = cs;
      this.userEditUrlPrefix = (this.opts.userEditUrlPrefix || '').toString();

      this.rootEl.innerHTML = `
        <div class="rel-graph-shell">
          <div class="rel-graph-toolbar">
            <div class="rel-graph-actions">
              <button type="button" class="neo-button outline" data-act="fit">Вписать</button>
              <button type="button" class="neo-button ghost" data-act="resetView">Сброс вида</button>
              <button type="button" class="neo-button ghost" data-act="resetLayout">Сброс раскладки</button>
              <button type="button" class="neo-button outline" data-act="refresh">Обновить</button>
            </div>
            <div class="rel-graph-filters">
              <label style="display:flex; gap:0.6rem; align-items:center;">
                <input type="checkbox" data-act="focusSelected" checked>
                <span style="color: var(--text-muted);">Фокус на выбранном</span>
              </label>
              <label style="display:flex; gap:0.6rem; align-items:center;">
                <input type="checkbox" data-act="includeInactive" checked>
                <span style="color: var(--text-muted);">Показывать неактивных</span>
              </label>
              <label style="display:flex; gap:0.6rem; align-items:center;">
                <input type="checkbox" data-act="allEnrollments">
                <span style="color: var(--text-muted);">Показывать все контракты (Enrollment)</span>
              </label>
            </div>
            <div class="rel-graph-selection">
              <span class="sel-pill">Выбран: <small data-act="selText">—</small></span>
              <button type="button" class="neo-button ghost small" data-act="selClear">Сбросить</button>
              <button type="button" class="neo-button outline small" data-act="selCreateLink" style="display:none;">Создать связь</button>
              <button type="button" class="neo-button ghost small" data-act="selOpen" style="display:none;">Открыть</button>
            </div>
            <div class="rel-legend">
              <span><span class="rel-dot enr"></span> Enrollment</span>
              <span><span class="rel-dot ft"></span> FamilyTie</span>
              <span style="opacity:0.85;">Перетаскивай карточки. Пустое место — двигать плоскость. Колесо — зум.</span>
            </div>
          </div>
          <div class="rel-graph-viewport" data-act="viewport">
            <div class="rel-graph-world" data-act="world">
              <svg class="rel-graph-edges" data-act="svg" width="3200" height="2000" viewBox="0 0 3200 2000" preserveAspectRatio="none"></svg>
              <div data-act="nodes"></div>
            </div>
          </div>
        </div>
      `;

      this.viewportEl = this.rootEl.querySelector('[data-act="viewport"]');
      this.worldEl = this.rootEl.querySelector('[data-act="world"]');
      this.svgEl = this.rootEl.querySelector('[data-act="svg"]');
      this.nodesWrapEl = this.rootEl.querySelector('[data-act="nodes"]');
      this.selTextEl = this.rootEl.querySelector('[data-act="selText"]');
      this.selClearBtn = this.rootEl.querySelector('[data-act="selClear"]');
      this.selCreateLinkBtn = this.rootEl.querySelector('[data-act="selCreateLink"]');
      this.selOpenBtn = this.rootEl.querySelector('[data-act="selOpen"]');

      // editing dialog (optional)
      this.enableEdgeEdit = !!this.opts.enableEdgeEdit;
      this.ftUrlPrefix = (this.opts.ftUrlPrefix || '').toString();
      this.enrUrlPrefix = (this.opts.enrUrlPrefix || '').toString();
      this.ftCreateUrl = (this.opts.ftCreateUrl || '').toString();
      this.enrCreateUrl = (this.opts.enrCreateUrl || '').toString();
      if (this.enableEdgeEdit) {
        this._mountDialog();
        this._mountCreateDialog();
      }

      // svg defs: arrowhead
      const defs = createSvgEl('defs');
      const marker = createSvgEl('marker');
      marker.setAttribute('id', 'rg-arrow');
      marker.setAttribute('markerWidth', '10');
      marker.setAttribute('markerHeight', '10');
      marker.setAttribute('refX', '9');
      marker.setAttribute('refY', '3');
      marker.setAttribute('orient', 'auto');
      marker.setAttribute('markerUnits', 'strokeWidth');
      const path = createSvgEl('path');
      path.setAttribute('d', 'M 0 0 L 10 3 L 0 6 z');
      path.setAttribute('fill', 'rgba(255,255,255,0.55)');
      marker.appendChild(path);
      defs.appendChild(marker);
      this.svgEl.appendChild(defs);
    }

    _mountDialog() {
      const dlg = document.createElement('dialog');
      dlg.className = 'rel-graph-dialog';
      dlg.innerHTML = `
        <div class="rel-graph-dlg-head">
          <div style="font-weight:800;" data-act="dlgTitle">Связь</div>
          <button type="button" class="neo-button ghost small" data-act="dlgClose">Закрыть</button>
        </div>
        <div class="rel-graph-dlg-body">
          <div class="neo-field" data-act="dlgFamily" style="display:none;">
            <label class="neo-label" for="rg-dlg-access-level">Уровень доступа (FamilyTie)</label>
            <select id="rg-dlg-access-level" class="neo-input" data-act="dlgAccess">
              <option value="full">Полный</option>
              <option value="financial_only">Только финансы</option>
              <option value="schedule_only">Только расписание</option>
            </select>
            <label style="display:flex; gap:0.6rem; align-items:center; margin-top:0.5rem;">
              <input type="checkbox" data-act="dlgConfirmed">
              <span style="color: var(--text-muted);">Подтверждено</span>
            </label>
          </div>
          <div class="neo-field" data-act="dlgEnrollment" style="display:none;">
            <label class="neo-label" for="rg-dlg-enr-subject">Предмет/тэг (Enrollment)</label>
            <input id="rg-dlg-enr-subject" class="neo-input" data-act="dlgSubject" placeholder="например: GENERAL или INFORMATICS_EGE_2026">
            <label class="neo-label" for="rg-dlg-enr-status" style="margin-top:0.5rem;">Статус</label>
            <select id="rg-dlg-enr-status" class="neo-input" data-act="dlgStatus">
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="archived">archived</option>
            </select>
          </div>
          <div style="color: var(--text-muted); font-size:0.9rem;" data-act="dlgHint"></div>
        </div>
        <div class="rel-graph-dlg-actions">
          <button type="button" class="neo-button danger" data-act="dlgDelete" style="display:none;">Удалить связь</button>
          <button type="button" class="neo-button outline" data-act="dlgSave">Сохранить</button>
        </div>
      `;
      this.rootEl.appendChild(dlg);
      this.dialogEl = dlg;

      this.dlgTitle = dlg.querySelector('[data-act="dlgTitle"]');
      this.dlgClose = dlg.querySelector('[data-act="dlgClose"]');
      this.dlgSave = dlg.querySelector('[data-act="dlgSave"]');
      this.dlgDelete = dlg.querySelector('[data-act="dlgDelete"]');
      this.dlgHint = dlg.querySelector('[data-act="dlgHint"]');
      this.dlgFamily = dlg.querySelector('[data-act="dlgFamily"]');
      this.dlgEnrollment = dlg.querySelector('[data-act="dlgEnrollment"]');
      this.dlgAccess = dlg.querySelector('[data-act="dlgAccess"]');
      this.dlgConfirmed = dlg.querySelector('[data-act="dlgConfirmed"]');
      this.dlgSubject = dlg.querySelector('[data-act="dlgSubject"]');
      this.dlgStatus = dlg.querySelector('[data-act="dlgStatus"]');

      this.dlgClose.addEventListener('click', () => this.dialogEl.close());
      this.dlgSave.addEventListener('click', () => this._saveEdge());
      this.dlgDelete.addEventListener('click', () => this._deleteEdge());
    }

    _mountCreateDialog() {
      const dlg = document.createElement('dialog');
      dlg.className = 'rel-graph-dialog';
      dlg.innerHTML = `
        <div class="rel-graph-dlg-head">
          <div style="font-weight:800;" data-act="createDlgTitle">Создать связь</div>
          <button type="button" class="neo-button ghost small" data-act="createDlgClose">Закрыть</button>
        </div>
        <div class="rel-graph-dlg-body">
          <div class="neo-field" data-act="createDlgType" style="display:none;">
            <label class="neo-label" for="rg-create-type">Тип связи</label>
            <select id="rg-create-type" class="neo-input" data-act="createDlgTypeSelect">
              <option value="family">FamilyTie (родитель → ученик)</option>
              <option value="enrollment">Enrollment (преподаватель → ученик)</option>
            </select>
          </div>
          <div class="neo-field" data-act="createDlgTarget">
            <label class="neo-label" for="rg-create-target">Выберите пользователя</label>
            <select id="rg-create-target" class="neo-input" data-act="createDlgTargetSelect">
              <option value="">— выберите —</option>
            </select>
          </div>
          <div class="neo-field" data-act="createDlgFamily" style="display:none;">
            <label class="neo-label" for="rg-create-access-level">Уровень доступа (FamilyTie)</label>
            <select id="rg-create-access-level" class="neo-input" data-act="createDlgAccess">
              <option value="full">Полный</option>
              <option value="financial_only">Только финансы</option>
              <option value="schedule_only">Только расписание</option>
            </select>
            <label style="display:flex; gap:0.6rem; align-items:center; margin-top:0.5rem;">
              <input type="checkbox" data-act="createDlgConfirmed" checked>
              <span style="color: var(--text-muted);">Подтверждено</span>
            </label>
          </div>
          <div class="neo-field" data-act="createDlgEnrollment" style="display:none;">
            <label class="neo-label" for="rg-create-enr-subject">Предмет/тэг (Enrollment)</label>
            <input id="rg-create-enr-subject" class="neo-input" data-act="createDlgSubject" placeholder="например: GENERAL или INFORMATICS_EGE_2026" value="GENERAL">
            <label class="neo-label" for="rg-create-enr-status" style="margin-top:0.5rem;">Статус</label>
            <select id="rg-create-enr-status" class="neo-input" data-act="createDlgStatus">
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="archived">archived</option>
            </select>
          </div>
          <div style="color: var(--text-muted); font-size:0.9rem;" data-act="createDlgHint"></div>
        </div>
        <div class="rel-graph-dlg-actions">
          <button type="button" class="neo-button outline" data-act="createDlgSave">Создать</button>
        </div>
      `;
      this.rootEl.appendChild(dlg);
      this.createDialogEl = dlg;

      this.createDlgTitle = dlg.querySelector('[data-act="createDlgTitle"]');
      this.createDlgClose = dlg.querySelector('[data-act="createDlgClose"]');
      this.createDlgSave = dlg.querySelector('[data-act="createDlgSave"]');
      this.createDlgHint = dlg.querySelector('[data-act="createDlgHint"]');
      this.createDlgType = dlg.querySelector('[data-act="createDlgType"]');
      this.createDlgTypeSelect = dlg.querySelector('[data-act="createDlgTypeSelect"]');
      this.createDlgTarget = dlg.querySelector('[data-act="createDlgTarget"]');
      this.createDlgTargetSelect = dlg.querySelector('[data-act="createDlgTargetSelect"]');
      this.createDlgFamily = dlg.querySelector('[data-act="createDlgFamily"]');
      this.createDlgEnrollment = dlg.querySelector('[data-act="createDlgEnrollment"]');
      this.createDlgAccess = dlg.querySelector('[data-act="createDlgAccess"]');
      this.createDlgConfirmed = dlg.querySelector('[data-act="createDlgConfirmed"]');
      this.createDlgSubject = dlg.querySelector('[data-act="createDlgSubject"]');
      this.createDlgStatus = dlg.querySelector('[data-act="createDlgStatus"]');

      this.createDlgClose.addEventListener('click', () => {
        this.createDialogEl.close();
        this._resetCreateDialog();
      });
      this.createDlgTypeSelect?.addEventListener('change', () => this._updateCreateDialog());
      this.createDlgSave.addEventListener('click', () => this._createLink());
      // Сбрасываем диалог при закрытии через ESC или клик вне диалога
      this.createDialogEl.addEventListener('close', () => this._resetCreateDialog());
    }

    _updateCreateDialog() {
      if (!this.createDialogEl || !this.data) return;
      const kind = this.createDlgTypeSelect?.value || '';
      if (kind === 'family') {
        this.createDlgFamily.style.display = '';
        this.createDlgEnrollment.style.display = 'none';
      } else if (kind === 'enrollment') {
        this.createDlgFamily.style.display = 'none';
        this.createDlgEnrollment.style.display = '';
      }
    }

    _resetCreateDialog() {
      if (!this.createDialogEl) return;
      this.createDlgTargetSelect.innerHTML = '<option value="">— выберите —</option>';
      this.createDlgTypeSelect.value = 'family';
      this.createDlgAccess.value = 'full';
      this.createDlgConfirmed.checked = true;
      this.createDlgSubject.value = 'GENERAL';
      this.createDlgStatus.value = 'active';
      this.createDlgHint.textContent = '';
      this.createDlgType.style.display = 'none';
      this.createDlgFamily.style.display = 'none';
      this.createDlgEnrollment.style.display = 'none';
      this.createDlgTypeSelect.onchange = null;
    }

    _openCreateLinkDialog() {
      if (!this.selectedNodeId || !this.data || !this.createDialogEl) return;
      const selected = (this.data.nodes || []).find(n => n.id === this.selectedNodeId);
      if (!selected) return;

      this.createDlgHint.textContent = '';
      const role = selected.role;
      const nodes = (this.data.nodes || []).filter(n => n.id !== this.selectedNodeId);

      // Заполняем список доступных пользователей
      this.createDlgTargetSelect.innerHTML = '<option value="">— выберите —</option>';
      if (role === 'parent') {
        this.createDlgTitle.textContent = 'Создать FamilyTie: родитель → ученик';
        this.createDlgType.style.display = 'none';
        this.createDlgFamily.style.display = '';
        this.createDlgEnrollment.style.display = 'none';
        this.createDlgHint.textContent = `Родитель: ${selected.username}. Выберите ученика.`;
        for (const n of nodes.filter(n => n.role === 'student')) {
          const opt = document.createElement('option');
          opt.value = String(n.id);
          opt.textContent = `${n.username}${n.email ? ' · ' + n.email : ''}`;
          this.createDlgTargetSelect.appendChild(opt);
        }
      } else if (role === 'student') {
        this.createDlgTitle.textContent = 'Создать связь для ученика';
        this.createDlgType.style.display = '';
        this.createDlgFamily.style.display = '';
        this.createDlgEnrollment.style.display = '';
        this.createDlgHint.textContent = `Ученик: ${selected.username}. Выберите тип связи и пользователя.`;
        this.createDlgTypeSelect.value = 'family';
        this._updateCreateDialog();
        // Показываем и родителей, и преподавателей
        const parents = nodes.filter(n => n.role === 'parent');
        const tutors = nodes.filter(n => n.role === 'tutor');
        const updateTargetList = () => {
          this.createDlgTargetSelect.innerHTML = '<option value="">— выберите —</option>';
          const kind = this.createDlgTypeSelect.value;
          const list = kind === 'family' ? parents : tutors;
          for (const n of list) {
            const opt = document.createElement('option');
            opt.value = String(n.id);
            opt.textContent = `${n.username}${n.email ? ' · ' + n.email : ''}`;
            this.createDlgTargetSelect.appendChild(opt);
          }
          this._updateCreateDialog();
        };
        // Используем onchange вместо addEventListener, чтобы избежать дублирования
        this.createDlgTypeSelect.onchange = updateTargetList;
        // Инициализируем список для начального значения
        updateTargetList();
      } else if (role === 'tutor') {
        this.createDlgTitle.textContent = 'Создать Enrollment: преподаватель → ученик';
        this.createDlgType.style.display = 'none';
        this.createDlgFamily.style.display = 'none';
        this.createDlgEnrollment.style.display = '';
        this.createDlgHint.textContent = `Преподаватель: ${selected.username}. Выберите ученика.`;
        for (const n of nodes.filter(n => n.role === 'student')) {
          const opt = document.createElement('option');
          opt.value = String(n.id);
          opt.textContent = `${n.username}${n.email ? ' · ' + n.email : ''}`;
          this.createDlgTargetSelect.appendChild(opt);
        }
      } else {
        return;
      }

      this.createDialogEl.showModal();
    }

    async _createLink() {
      if (!this.selectedNodeId || !this.data) return;
      const selected = (this.data.nodes || []).find(n => n.id === this.selectedNodeId);
      if (!selected) return;

      try {
        this.createDlgSave.disabled = true;
        const role = selected.role;
        let url, payload, kind;

        // Получаем выбранного пользователя из диалога
        const targetUserId = this.createDlgTargetSelect?.value;
        if (!targetUserId) {
          (window.toast || toast)?.error?.('Выберите пользователя');
          this.createDlgSave.disabled = false;
          return;
        }
        const targetUser = (this.data.nodes || []).find(n => String(n.id) === String(targetUserId));
        if (!targetUser) {
          (window.toast || toast)?.error?.('Пользователь не найден');
          this.createDlgSave.disabled = false;
          return;
        }

        if (role === 'parent') {
          // FamilyTie: parent -> student
          if (targetUser.role !== 'student') {
            (window.toast || toast)?.error?.('Выберите ученика');
            this.createDlgSave.disabled = false;
            return;
          }
          url = this.ftCreateUrl;
          payload = {
            parent_id: this.selectedNodeId,
            student_id: targetUser.id,
            access_level: this.createDlgAccess.value,
            is_confirmed: this.createDlgConfirmed.checked,
          };
          kind = 'family';
        } else if (role === 'tutor') {
          // Enrollment: tutor -> student
          if (targetUser.role !== 'student') {
            (window.toast || toast)?.error?.('Выберите ученика');
            this.createDlgSave.disabled = false;
            return;
          }
          url = this.enrCreateUrl;
          payload = {
            tutor_id: this.selectedNodeId,
            student_id: targetUser.id,
            subject: this.createDlgSubject.value || 'GENERAL',
            status: this.createDlgStatus.value || 'active',
          };
          kind = 'enrollment';
        } else if (role === 'student') {
          // Можем создать либо FamilyTie (нужен parent), либо Enrollment (нужен tutor)
          const linkType = this.createDlgTypeSelect?.value || 'family';
          if (linkType === 'family') {
            if (targetUser.role !== 'parent') {
              (window.toast || toast)?.error?.('Выберите родителя');
              this.createDlgSave.disabled = false;
              return;
            }
            url = this.ftCreateUrl;
            payload = {
              parent_id: targetUser.id,
              student_id: this.selectedNodeId,
              access_level: this.createDlgAccess.value,
              is_confirmed: this.createDlgConfirmed.checked,
            };
            kind = 'family';
          } else if (linkType === 'enrollment') {
            if (targetUser.role !== 'tutor') {
              (window.toast || toast)?.error?.('Выберите преподавателя');
              this.createDlgSave.disabled = false;
              return;
            }
            url = this.enrCreateUrl;
            payload = {
              tutor_id: targetUser.id,
              student_id: this.selectedNodeId,
              subject: this.createDlgSubject.value || 'GENERAL',
              status: this.createDlgStatus.value || 'active',
            };
            kind = 'enrollment';
          } else {
            (window.toast || toast)?.error?.('Неверный тип связи');
            this.createDlgSave.disabled = false;
            return;
          }
        } else {
          (window.toast || toast)?.error?.('Невозможно создать связь для этой роли');
          this.createDlgSave.disabled = false;
          return;
        }

        const resp = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRFToken': this.csrfToken,
          },
          body: JSON.stringify(payload),
        });
        
        // Проверяем content-type перед парсингом JSON
        const contentType = resp.headers.get('content-type') || '';
        let data;
        if (contentType.includes('application/json')) {
          try {
            data = await resp.json();
          } catch (e) {
            throw new Error('Invalid JSON response');
          }
        } else {
          const text = await resp.text();
          throw new Error(`Invalid response format: ${text.substring(0, 100)}`);
        }
        
        if (!resp.ok || !data || data.success === false) {
          throw new Error((data && (data.error || data.message)) || `HTTP ${resp.status}`);
        }
        (window.toast || toast)?.success?.('Связь создана');
        this.createDialogEl.close();
        this._resetCreateDialog();
        await this.reload();
      } catch (e) {
        console.error(e);
        (window.toast || toast)?.error?.('Не удалось создать связь: ' + (e.message || String(e)));
      } finally {
        this.createDlgSave.disabled = false;
      }
    }

    _bindUI() {
      const btn = (act) => this.rootEl.querySelector(`[data-act="${act}"]`);
      btn('fit')?.addEventListener('click', () => this.fitToContent());
      btn('resetView')?.addEventListener('click', () => this.resetView());
      btn('resetLayout')?.addEventListener('click', () => this.resetLayout());
      btn('refresh')?.addEventListener('click', () => this.reload());

      const includeInactive = btn('includeInactive');
      const focusSelected = btn('focusSelected');
      const allEnrollments = btn('allEnrollments');
      includeInactive?.addEventListener('change', () => this.render());
      focusSelected?.addEventListener('change', () => this.render());
      allEnrollments?.addEventListener('change', () => this.reload());
      this.selClearBtn?.addEventListener('click', () => this._setSelected(null));
      this.selCreateLinkBtn?.addEventListener('click', () => this._openCreateLinkDialog());
        this.selOpenBtn?.addEventListener('click', () => {
          if (!this.selectedNodeId || !this.userEditUrlPrefix) return;
          const baseUrl = this.userEditUrlPrefix.replace(/\/$/, '');
          const url = baseUrl + '/' + this.selectedNodeId + '/edit';
          if (!url || url === '/' || url === baseUrl) {
            (window.toast || toast)?.error?.('Неверный URL для открытия профиля');
            return;
          }
          window.open(url, '_blank');
        });

      // Pan (pointer)
      this.viewportEl.addEventListener('pointerdown', (ev) => {
        const target = ev.target;
        if (target && target.closest && target.closest('.rel-node')) return;
        this.state.draggingPan = true;
        this.state.dragStart = { x: ev.clientX, y: ev.clientY, tx: this.state.tx, ty: this.state.ty, moved: false };
        this.viewportEl.setPointerCapture(ev.pointerId);
      });
      this.viewportEl.addEventListener('pointermove', (ev) => {
        if (!this.state.draggingPan || !this.state.dragStart) return;
        const dx = ev.clientX - this.state.dragStart.x;
        const dy = ev.clientY - this.state.dragStart.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) this.state.dragStart.moved = true;
        this.state.tx = this.state.dragStart.tx + dx;
        this.state.ty = this.state.dragStart.ty + dy;
        this._applyTransform();
      });
      this.viewportEl.addEventListener('pointerup', (ev) => {
        const wasClick = this.state.dragStart && !this.state.dragStart.moved;
        this.state.draggingPan = false;
        this.state.dragStart = null;
        try { this.viewportEl.releasePointerCapture(ev.pointerId); } catch {}
        if (wasClick) this._setSelected(null);
      });

      // Zoom (wheel)
      this.viewportEl.addEventListener('wheel', (ev) => {
        ev.preventDefault();
        const rect = this.viewportEl.getBoundingClientRect();
        const mx = ev.clientX - rect.left;
        const my = ev.clientY - rect.top;
        const old = this.state.scale;
        const delta = -ev.deltaY;
        const factor = delta > 0 ? 1.08 : 1 / 1.08;
        const next = clamp(old * factor, 0.35, 2.2);
        if (Math.abs(next - old) < 0.0001) return;

        // keep cursor point stable:
        // worldPoint = (mouse - translate) / scale
        const wx = (mx - this.state.tx) / old;
        const wy = (my - this.state.ty) / old;
        this.state.scale = next;
        this.state.tx = mx - wx * next;
        this.state.ty = my - wy * next;
        this._applyTransform();
      }, { passive: false });

      window.addEventListener('resize', () => this._scheduleDraw());
    }

    async reload() {
      const url = this._buildDataUrl();
      const resp = await fetch(url, { headers: { 'Accept': 'application/json' } });
      const data = await resp.json();
      if (!resp.ok || !data || data.success === false) {
        throw new Error((data && (data.error || data.message)) || `HTTP ${resp.status}`);
      }
      this.data = data;
      this._mountNodes();
      this._applyStoredPositionsOrLayout();
      this.render();
      this.fitToContent({ padding: 120, maxScale: 1.35 });
    }

    _buildDataUrl() {
      const base = this.opts.graphUrl;
      const allEnroll = !!this.rootEl.querySelector('[data-act="allEnrollments"]')?.checked;
      const qs = new URLSearchParams();
      qs.set('roles', 'tutor,student,parent');
      qs.set('include_inactive', 'true');
      if (allEnroll) qs.set('all_enrollments', 'true');
      return base + (base.includes('?') ? '&' : '?') + qs.toString();
    }

    _mountNodes() {
      this.nodeEls.clear();
      this.nodesWrapEl.innerHTML = '';
      const nodes = (this.data && this.data.nodes) || [];
      for (const n of nodes) {
        const el = document.createElement('div');
        el.className = 'rel-node' + ((!n.is_active) ? ' dim' : '');
        el.dataset.nodeId = String(n.id);
        el.dataset.role = n.role || '';
        el.innerHTML = `
          <div class="rel-node-title">
            <span class="role-badge role-${n.role}">${defaultRoleLabel(n.role)}</span>
            <span>${escapeHtml(n.username || '')}</span>
          </div>
          <div class="rel-node-sub">${escapeHtml([n.display_name, n.email, n.timezone].filter(Boolean).join(' · ') || '—')}</div>
        `;
        el.style.left = '0px';
        el.style.top = '0px';
        el.addEventListener('pointerdown', (ev) => this._startDragNode(ev, n.id));
        el.addEventListener('dblclick', (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (this.userEditUrlPrefix) {
            const baseUrl = this.userEditUrlPrefix.replace(/\/$/, '');
            const url = baseUrl + '/' + n.id + '/edit';
            if (!url || url === '/' || url === baseUrl) {
              (window.toast || toast)?.error?.('Неверный URL для открытия профиля');
              return;
            }
            window.open(url, '_blank');
          }
        });
        this.nodesWrapEl.appendChild(el);
        this.nodeEls.set(n.id, el);
      }
    }

    _storageKey() {
      const k = (this.opts.storageKey || 'relationshipGraph').toString();
      return k;
    }

    _applyStoredPositionsOrLayout() {
      const nodes = (this.data && this.data.nodes) || [];
      const stored = safeJsonParse(localStorage.getItem(this._storageKey()) || '', null);
      if (stored && stored.nodes && typeof stored.nodes === 'object') {
        for (const n of nodes) {
          const pos = stored.nodes[String(n.id)];
          if (!pos) continue;
          const el = this.nodeEls.get(n.id);
          if (!el) continue;
          el.style.left = `${pos.x}px`;
          el.style.top = `${pos.y}px`;
        }
        // also restore view if matches
        if (stored.view) {
          this.state.tx = stored.view.tx ?? this.state.tx;
          this.state.ty = stored.view.ty ?? this.state.ty;
          this.state.scale = stored.view.scale ?? this.state.scale;
          this._applyTransform();
        }
        return;
      }
      this._layoutDefault();
    }

    _layoutDefault() {
      const nodes = (this.data && this.data.nodes) || [];
      const byRole = {
        tutor: nodes.filter(n => n.role === 'tutor'),
        student: nodes.filter(n => n.role === 'student'),
        parent: nodes.filter(n => n.role === 'parent'),
      };

      // Order students by number of edges to reduce crossings a bit
      const edgeCounts = new Map();
      const addCnt = (id) => edgeCounts.set(id, (edgeCounts.get(id) || 0) + 1);
      for (const e of this._allEdges()) {
        addCnt(e.from_id); addCnt(e.to_id);
      }
      for (const k of Object.keys(byRole)) {
        byRole[k].sort((a, b) => (edgeCounts.get(b.id) || 0) - (edgeCounts.get(a.id) || 0) || (a.username || '').localeCompare((b.username || ''), 'ru'));
      }

      const colX = { tutor: 120, student: 720, parent: 1320 };
      const startY = 120;
      const gapY = 170;

      for (const role of ['tutor', 'student', 'parent']) {
        const list = byRole[role] || [];
        for (let i = 0; i < list.length; i++) {
          const n = list[i];
          const el = this.nodeEls.get(n.id);
          if (!el) continue;
          el.style.left = `${colX[role]}px`;
          el.style.top = `${startY + i * gapY}px`;
        }
      }

      this._saveState();
    }

    _startDragNode(ev, nodeId) {
      ev.preventDefault();
      ev.stopPropagation();
      const el = this.nodeEls.get(nodeId);
      if (!el) return;
      this.state.draggingNodeId = nodeId;
      const start = {
        x: ev.clientX,
        y: ev.clientY,
        left: parseFloat(el.style.left || '0') || 0,
        top: parseFloat(el.style.top || '0') || 0,
        scale: this.state.scale,
        moved: false,
      };
      this.state.dragStart = start;
      el.setPointerCapture(ev.pointerId);

      const onMove = (e) => {
        if (this.state.draggingNodeId !== nodeId || !this.state.dragStart) return;
        const dx = (e.clientX - start.x) / start.scale;
        const dy = (e.clientY - start.y) / start.scale;
        if (Math.abs(dx) + Math.abs(dy) > 2) start.moved = true;
        el.style.left = `${start.left + dx}px`;
        el.style.top = `${start.top + dy}px`;
        this._scheduleDraw();
      };
      const onUp = (e) => {
        try { el.releasePointerCapture(e.pointerId); } catch {}
        this.state.draggingNodeId = null;
        this.state.dragStart = null;
        el.removeEventListener('pointermove', onMove);
        el.removeEventListener('pointerup', onUp);
        el.removeEventListener('pointercancel', onUp);
        this._saveState();
        if (!start.moved) {
          this._setSelected(nodeId);
        }
        this._scheduleDraw();
      };
      el.addEventListener('pointermove', onMove);
      el.addEventListener('pointerup', onUp);
      el.addEventListener('pointercancel', onUp);
    }

    _setSelected(nodeId) {
      const next = (nodeId && nodeId === this.selectedNodeId) ? null : nodeId;
      this.selectedNodeId = next;
      this._updateSelectionUI();
      this.render();
    }

    _updateSelectionUI() {
      if (!this.selTextEl) return;
      if (!this.data || !this.selectedNodeId) {
        this.selTextEl.textContent = '—';
        if (this.selOpenBtn) this.selOpenBtn.style.display = 'none';
        if (this.selCreateLinkBtn) this.selCreateLinkBtn.style.display = 'none';
        for (const el of this.nodeEls.values()) el.classList.remove('selected');
        return;
      }
      const node = (this.data.nodes || []).find(n => n.id === this.selectedNodeId);
      const label = node ? `${node.username}${node.role ? ' · ' + defaultRoleLabel(node.role) : ''}` : String(this.selectedNodeId);
      this.selTextEl.textContent = label;
      if (this.selOpenBtn) this.selOpenBtn.style.display = this.userEditUrlPrefix ? '' : 'none';
      if (this.selCreateLinkBtn) {
        const canCreate = node && (node.role === 'parent' || node.role === 'tutor' || node.role === 'student');
        this.selCreateLinkBtn.style.display = (canCreate && this.enableEdgeEdit) ? '' : 'none';
      }
      for (const [id, el] of this.nodeEls.entries()) {
        el.classList.toggle('selected', id === this.selectedNodeId);
      }
    }

    _isNodeRelatedToSelected(nodeId) {
      if (!this.selectedNodeId) return false;
      for (const e of this._allEdges()) {
        if ((e.from_id === this.selectedNodeId && e.to_id === nodeId) || (e.to_id === this.selectedNodeId && e.from_id === nodeId)) {
          return true;
        }
      }
      return false;
    }

    _saveState() {
      const nodes = {};
      for (const [id, el] of this.nodeEls.entries()) {
        nodes[String(id)] = {
          x: parseFloat(el.style.left || '0') || 0,
          y: parseFloat(el.style.top || '0') || 0,
        };
      }
      const payload = {
        nodes,
        view: { tx: this.state.tx, ty: this.state.ty, scale: this.state.scale },
        saved_at: nowMs(),
      };
      try { localStorage.setItem(this._storageKey(), JSON.stringify(payload)); } catch {}
    }

    resetLayout() {
      try { localStorage.removeItem(this._storageKey()); } catch {}
      this._layoutDefault();
      this.render();
      this.fitToContent({ padding: 120, maxScale: 1.35 });
    }

    resetView() {
      this.state.tx = 60;
      this.state.ty = 60;
      this.state.scale = 1;
      this._applyTransform();
      this._saveState();
    }

    _applyTransform() {
      this.worldEl.style.transform = `translate(${this.state.tx}px, ${this.state.ty}px) scale(${this.state.scale})`;
    }

    _allEdges() {
      const edges = [];
      const enrollments = (this.data && this.data.enrollments) || [];
      const ties = (this.data && this.data.family_ties) || [];
      for (const e of enrollments) edges.push({ kind: 'enrollment', ...e });
      for (const t of ties) edges.push({ kind: 'family', ...t });
      return edges;
    }

    render() {
      if (!this.data) return;
      const showInactive = !!this.rootEl.querySelector('[data-act="includeInactive"]')?.checked;
      const focusSelected = !!this.rootEl.querySelector('[data-act="focusSelected"]')?.checked;
      const nodes = (this.data.nodes || []);
      this._updateSelectionUI();
      let visible = new Set(nodes.filter(n => showInactive || n.is_active).map(n => n.id));

      if (this.selectedNodeId && focusSelected) {
        const keep = new Set([this.selectedNodeId]);
        for (const e of this._allEdges()) {
          if (e.from_id === this.selectedNodeId || e.to_id === this.selectedNodeId) {
            keep.add(e.from_id);
            keep.add(e.to_id);
          }
        }
        visible = new Set([...visible].filter(id => keep.has(id)));
      }

      // show/hide nodes
      for (const n of nodes) {
        const el = this.nodeEls.get(n.id);
        if (!el) continue;
        el.style.display = visible.has(n.id) ? '' : 'none';
        if (this.selectedNodeId && !focusSelected) {
          const related = (n.id === this.selectedNodeId) || this._isNodeRelatedToSelected(n.id);
          el.classList.toggle('dim', !related);
        } else {
          el.classList.toggle('dim', !n.is_active);
        }
      }

      this._drawEdges(visible, { focusSelected });
      this._applyTransform();
      this._saveState();
    }

    _scheduleDraw() {
      // throttle redraw
      const t = nowMs();
      if (t - this.state.lastDrawAt < 16) return;
      this.state.lastDrawAt = t;
      this.render();
    }

    _nodeCenter(id) {
      const el = this.nodeEls.get(id);
      if (!el || el.style.display === 'none') return null;
      const x = (parseFloat(el.style.left || '0') || 0);
      const y = (parseFloat(el.style.top || '0') || 0);
      const w = el.offsetWidth || 300;
      const h = el.offsetHeight || 90;
      return { x, y, w, h, cx: x + w / 2, cy: y + h / 2 };
    }

    _drawEdges(visibleNodeIds, options) {
      options = options || {};
      // clear everything except defs
      const defs = this.svgEl.querySelector('defs');
      this.svgEl.innerHTML = '';
      if (defs) this.svgEl.appendChild(defs);

      let edges = this._allEdges().filter(e => visibleNodeIds.has(e.from_id) && visibleNodeIds.has(e.to_id));
      if (this.selectedNodeId && options.focusSelected) {
        edges = edges.filter(e => e.from_id === this.selectedNodeId || e.to_id === this.selectedNodeId);
      }

      // group by pair to de-overlap via control offset
      const grouped = new Map();
      for (const e of edges) {
        const pk = pairKey(e);
        if (!grouped.has(pk)) grouped.set(pk, []);
        grouped.get(pk).push(e);
      }

      for (const [pk, list] of grouped.entries()) {
        // stable sort by id to make offsets stable
        list.sort((a, b) => edgeKey(a).localeCompare(edgeKey(b)));
        for (let i = 0; i < list.length; i++) {
          const e = list[i];
          const from = this._nodeCenter(e.from_id);
          const to = this._nodeCenter(e.to_id);
          if (!from || !to) continue;

          // route: pick sides based on relative x
          const leftToRight = from.cx <= to.cx;
          const ax = leftToRight ? (from.x + from.w) : from.x;
          const ay = from.cy;
          const bx = leftToRight ? to.x : (to.x + to.w);
          const by = to.cy;

          const dx = Math.abs(bx - ax);
          const base = Math.max(120, dx * 0.45);
          const offset = (i - (list.length - 1) / 2) * 18; // spreads parallel edges

          const c1x = ax + (leftToRight ? base : -base);
          const c2x = bx - (leftToRight ? base : -base);
          const c1y = ay + offset;
          const c2y = by + offset;

          const path = createSvgEl('path');
          path.setAttribute('d', `M ${ax} ${ay} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${bx} ${by}`);
          path.setAttribute('fill', 'none');
          const isRelated = !this.selectedNodeId || (e.from_id === this.selectedNodeId || e.to_id === this.selectedNodeId);
          const baseStroke = (e.kind === 'family' ? 'rgba(255,200,46,0.75)' : 'rgba(46,125,255,0.75)');
          path.setAttribute('stroke', baseStroke);
          path.setAttribute('stroke-width', '2.2');
          path.setAttribute('stroke-linecap', 'round');
          path.setAttribute('marker-end', 'url(#rg-arrow)');
          path.style.pointerEvents = this.enableEdgeEdit ? 'auto' : 'none';
          if (this.selectedNodeId && !options.focusSelected) {
            path.setAttribute('opacity', isRelated ? '1' : '0.18');
          }
          if (this.enableEdgeEdit) {
            path.addEventListener('click', () => this._openEdgeEditor(e));
          }
          this.svgEl.appendChild(path);

          // label
          const label = createSvgEl('text');
          label.setAttribute('class', 'edge-label');
          label.setAttribute('text-anchor', 'middle');
          const mx = (ax + bx) / 2;
          const my = (ay + by) / 2 + offset - 8;
          label.setAttribute('x', String(mx));
          label.setAttribute('y', String(my));
          const text = (e.kind === 'family')
            ? `${e.access_level || ''}${e.is_confirmed ? ' · ok' : ' · pending'}`
            : `${e.subject || ''} · ${e.status || ''}`;
          label.textContent = (text || '—').trim();
          if (this.selectedNodeId && !options.focusSelected) {
            label.setAttribute('opacity', isRelated ? '1' : '0.18');
          }
          this.svgEl.appendChild(label);
        }
      }
    }

    _openEdgeEditor(e) {
      if (!this.enableEdgeEdit || !this.dialogEl) return;
      this.currentEdge = { kind: e.kind, id: (e.kind === 'family' ? e.tie_id : e.enrollment_id) };
      this.dlgDelete.style.display = '';
      if (e.kind === 'family') {
        this.dlgTitle.textContent = 'FamilyTie: родитель → ученик';
        this.dlgFamily.style.display = '';
        this.dlgEnrollment.style.display = 'none';
        this.dlgAccess.value = e.access_level || 'full';
        this.dlgConfirmed.checked = !!e.is_confirmed;
        this.dlgHint.textContent = 'Настройка: уровень доступа и подтверждение связи.';
      } else {
        this.dlgTitle.textContent = 'Enrollment: преподаватель → ученик';
        this.dlgFamily.style.display = 'none';
        this.dlgEnrollment.style.display = '';
        this.dlgSubject.value = e.subject || '';
        this.dlgStatus.value = e.status || 'active';
        this.dlgHint.textContent = 'Настройка: subject/тэг и статус контракта.';
      }
      this.dialogEl.showModal();
    }

    async _saveEdge() {
      if (!this.currentEdge) return;
      try {
        this.dlgSave.disabled = true;
        const isFamily = this.currentEdge.kind === 'family';
        const prefix = isFamily ? this.ftUrlPrefix : this.enrUrlPrefix;
        const url = `${prefix}${this.currentEdge.id}`;
        const payload = isFamily
          ? { access_level: this.dlgAccess.value, is_confirmed: this.dlgConfirmed.checked }
          : { subject: this.dlgSubject.value, status: this.dlgStatus.value };
        const resp = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRFToken': this.csrfToken,
          },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok || !data || data.success === false) {
          throw new Error((data && (data.error || data.message)) || `HTTP ${resp.status}`);
        }
        (window.toast || toast)?.success?.('Связь обновлена');
        this.dialogEl.close();
        await this.reload();
      } catch (e) {
        console.error(e);
        (window.toast || toast)?.error?.('Не удалось сохранить связь');
      } finally {
        this.dlgSave.disabled = false;
      }
    }

    async _deleteEdge() {
      if (!this.currentEdge) return;
      if (!confirm('Удалить эту связь?')) return;
      try {
        this.dlgDelete.disabled = true;
        const isFamily = this.currentEdge.kind === 'family';
        const prefix = isFamily ? this.ftUrlPrefix : this.enrUrlPrefix;
        const url = `${prefix}${this.currentEdge.id}`;
        const resp = await fetch(url, {
          method: 'DELETE',
          headers: {
            'Accept': 'application/json',
            'X-CSRFToken': this.csrfToken,
          },
        });
        const data = await resp.json();
        if (!resp.ok || !data || data.success === false) {
          throw new Error((data && (data.error || data.message)) || `HTTP ${resp.status}`);
        }
        (window.toast || toast)?.success?.('Связь удалена');
        this.dialogEl.close();
        await this.reload();
      } catch (e) {
        console.error(e);
        (window.toast || toast)?.error?.('Не удалось удалить связь');
      } finally {
        this.dlgDelete.disabled = false;
      }
    }

    fitToContent(opts) {
      opts = opts || {};
      const padding = opts.padding ?? 100;
      const maxScale = opts.maxScale ?? 1.6;
      const minScale = opts.minScale ?? 0.5;

      const nodes = Array.from(this.nodeEls.values()).filter(el => el.style.display !== 'none');
      if (!nodes.length) return;

      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const el of nodes) {
        const x = (parseFloat(el.style.left || '0') || 0);
        const y = (parseFloat(el.style.top || '0') || 0);
        const w = el.offsetWidth || 300;
        const h = el.offsetHeight || 90;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x + w);
        maxY = Math.max(maxY, y + h);
      }

      const contentW = (maxX - minX) + padding * 2;
      const contentH = (maxY - minY) + padding * 2;

      const vr = this.viewportEl.getBoundingClientRect();
      const vw = vr.width || 800;
      const vh = vr.height || 600;

      const s = clamp(Math.min(vw / contentW, vh / contentH), minScale, maxScale);

      // center content
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      this.state.scale = s;
      this.state.tx = (vw / 2) - cx * s;
      this.state.ty = (vh / 2) - cy * s;
      this._applyTransform();
      this._saveState();
    }
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  window.RelationshipGraph = RelationshipGraph;
})();

