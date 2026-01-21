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

      this._buildUI();
      this._bindUI();
    }

    _buildUI() {
      const cs = getCSRFToken(this.opts.csrfToken);
      this.csrfToken = cs;

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
                <input type="checkbox" data-act="includeInactive" checked>
                <span style="color: var(--text-muted);">Показывать неактивных</span>
              </label>
              <label style="display:flex; gap:0.6rem; align-items:center;">
                <input type="checkbox" data-act="allEnrollments">
                <span style="color: var(--text-muted);">Показывать все контракты (Enrollment)</span>
              </label>
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

      // editing dialog (optional)
      this.enableEdgeEdit = !!this.opts.enableEdgeEdit;
      this.ftUrlPrefix = (this.opts.ftUrlPrefix || '').toString();
      this.enrUrlPrefix = (this.opts.enrUrlPrefix || '').toString();
      if (this.enableEdgeEdit) {
        this._mountDialog();
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

    _bindUI() {
      const btn = (act) => this.rootEl.querySelector(`[data-act="${act}"]`);
      btn('fit')?.addEventListener('click', () => this.fitToContent());
      btn('resetView')?.addEventListener('click', () => this.resetView());
      btn('resetLayout')?.addEventListener('click', () => this.resetLayout());
      btn('refresh')?.addEventListener('click', () => this.reload());

      const includeInactive = btn('includeInactive');
      const allEnrollments = btn('allEnrollments');
      includeInactive?.addEventListener('change', () => this.render());
      allEnrollments?.addEventListener('change', () => this.reload());

      // Pan (pointer)
      this.viewportEl.addEventListener('pointerdown', (ev) => {
        const target = ev.target;
        if (target && target.closest && target.closest('.rel-node')) return;
        this.state.draggingPan = true;
        this.state.dragStart = { x: ev.clientX, y: ev.clientY, tx: this.state.tx, ty: this.state.ty };
        this.viewportEl.setPointerCapture(ev.pointerId);
      });
      this.viewportEl.addEventListener('pointermove', (ev) => {
        if (!this.state.draggingPan || !this.state.dragStart) return;
        const dx = ev.clientX - this.state.dragStart.x;
        const dy = ev.clientY - this.state.dragStart.y;
        this.state.tx = this.state.dragStart.tx + dx;
        this.state.ty = this.state.dragStart.ty + dy;
        this._applyTransform();
      });
      this.viewportEl.addEventListener('pointerup', (ev) => {
        this.state.draggingPan = false;
        this.state.dragStart = null;
        try { this.viewportEl.releasePointerCapture(ev.pointerId); } catch {}
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
      };
      this.state.dragStart = start;
      el.setPointerCapture(ev.pointerId);

      const onMove = (e) => {
        if (this.state.draggingNodeId !== nodeId || !this.state.dragStart) return;
        const dx = (e.clientX - start.x) / start.scale;
        const dy = (e.clientY - start.y) / start.scale;
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
        this._scheduleDraw();
      };
      el.addEventListener('pointermove', onMove);
      el.addEventListener('pointerup', onUp);
      el.addEventListener('pointercancel', onUp);
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
      const nodes = (this.data.nodes || []);
      const visible = new Set(nodes.filter(n => showInactive || n.is_active).map(n => n.id));

      // show/hide nodes
      for (const n of nodes) {
        const el = this.nodeEls.get(n.id);
        if (!el) continue;
        el.style.display = visible.has(n.id) ? '' : 'none';
      }

      this._drawEdges(visible);
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

    _drawEdges(visibleNodeIds) {
      // clear everything except defs
      const defs = this.svgEl.querySelector('defs');
      this.svgEl.innerHTML = '';
      if (defs) this.svgEl.appendChild(defs);

      const edges = this._allEdges().filter(e => visibleNodeIds.has(e.from_id) && visibleNodeIds.has(e.to_id));

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
          path.setAttribute('stroke', e.kind === 'family' ? 'rgba(255,200,46,0.75)' : 'rgba(46,125,255,0.75)');
          path.setAttribute('stroke-width', '2.2');
          path.setAttribute('stroke-linecap', 'round');
          path.setAttribute('marker-end', 'url(#rg-arrow)');
          path.style.pointerEvents = this.enableEdgeEdit ? 'auto' : 'none';
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

