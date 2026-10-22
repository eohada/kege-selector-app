/**
 * BooStudy OS — Boo Master Orbit (Преподская Орбита) 1.0
 * Specialized Pedagogical Command HUD for Teachers
 * Strictly Isolated to `trainerOsConfig.is_studio_teacher`
 */

(function () {
  'use strict';

  // Guard: Initialize strictly if role is teacher
  function isTeacherRole() {
    return Boolean(
      window.trainerOsConfig?.is_studio_teacher ||
      window.trainerOsConfig?.room_role === 'teacher' ||
      window.boostudyLessonControl?.getControl?.()?.role === 'teacher'
    );
  }

  const escapeHtml = (val) => String(val ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));

  // Workspace Host & Z-Index Integration
  function getMasterWorkspaceHost() {
    return document.getElementById('trainer-arena-view') ||
           document.querySelector('.room-lesson-os') ||
           document.querySelector('.task-workspace-container') ||
           document.body;
  }

  function bringMasterElementToFront(el) {
    if (!el) return 55;
    if (typeof window.bringElementToFront === 'function') {
      return window.bringElementToFront(el);
    }
    const host = getMasterWorkspaceHost();
    let maxZ = 55;
    const items = host.querySelectorAll('.glass-os-window, .boo-master-card, .boo-orbit-card, .boo-orbit-stamp-item');
    items.forEach(item => {
      const z = parseInt(window.getComputedStyle(item).zIndex, 10);
      if (!isNaN(z) && z < 950 && z > maxZ) maxZ = z;
    });
    const nextZ = Math.min(950, maxZ + 1);
    el.style.setProperty('z-index', String(nextZ), 'important');
    if (window.windowManager) window.windowManager.globalZIndex = nextZ;
    return nextZ;
  }

  function getWorkspaceCoordinates(clientX, clientY) {
    const host = getMasterWorkspaceHost();
    if (host === document.body) {
      return { x: clientX, y: clientY, maxW: window.innerWidth, maxH: window.innerHeight };
    }
    const rect = host.getBoundingClientRect();
    return {
      x: clientX - rect.left,
      y: clientY - rect.top,
      maxW: host.clientWidth || window.innerWidth,
      maxH: host.clientHeight || window.innerHeight
    };
  }

  // Master Tools Configuration (5 Focused Pedagogical Sectors + Satellites)
  const MASTER_SECTORS = [
    {
      id: 'teacher_draft',
      title: 'Скрытый черновик',
      icon: 'ph-eye-slash',
      color: '#b45309',
      action: () => actionToggleMarks(),
      satellites: [
        {
          id: 'toggle_draft',
          title: 'Вкл/выкл черновик',
          icon: 'ph-pencil-slash',
          action: () => actionToggleMarks()
        },
        {
          id: 'teacher_notes',
          title: 'Личные заметки',
          icon: 'ph-notebook',
          action: () => actionOpenTeacherNotes()
        },
        {
          id: 'toggle_student_viewport',
          title: 'Контур ученика',
          icon: 'ph-bounding-box',
          action: () => window.toggleStudentViewportOutline?.()
        }
      ]
    },
    {
      id: 'official_answer',
      title: 'Эталон ответа',
      icon: 'ph-check-circle',
      color: '#059669',
      action: (x, y) => spawnAnswerCard(x, y),
      satellites: [
        {
          id: 'show_card',
          title: 'Карточка ответа',
          icon: 'ph-article',
          action: (x, y) => spawnAnswerCard(x, y)
        },
        {
          id: 'toggle_student_vis',
          title: 'Открыть ученику',
          icon: 'ph-broadcast',
          action: () => toggleStudentAnswerVisibility()
        }
      ]
    },
    {
      id: 'task_manager',
      title: 'Задания урока',
      icon: 'ph-books',
      color: '#d97706',
      action: () => actionNextTask(),
      satellites: [
        {
          id: 'prev_task',
          title: 'Предыдущая',
          icon: 'ph-arrow-circle-left',
          action: () => actionPrevTask()
        },
        {
          id: 'next_task',
          title: 'Следующая',
          icon: 'ph-arrow-circle-right',
          action: () => actionNextTask()
        },
        {
          id: 'task_bank',
          title: 'Банк задач',
          icon: 'ph-magnifying-glass-plus',
          action: () => actionOpenTaskBank()
        },
        {
          id: 'ai_analog',
          title: 'AI аналог',
          icon: 'ph-sparkle',
          action: () => actionGenerateAnalog()
        }
      ]
    },
    {
      id: 'pedagogy_stamps',
      title: 'Пед-штампы',
      icon: 'ph-seal-check',
      color: '#4f46e5',
      satellites: [
        {
          id: 'stamp_excellent',
          title: 'Отлично! 100%',
          icon: 'ph-star',
          action: (x, y) => spawnMasterStamp(x, y, 'Отлично! 100%', 'excellent', 'ph-star')
        },
        {
          id: 'stamp_warning',
          title: 'Перепроверь!',
          icon: 'ph-warning',
          action: (x, y) => spawnMasterStamp(x, y, 'Перепроверь условия', 'warning', 'ph-warning')
        },
        {
          id: 'stamp_error',
          title: 'Ошибка',
          icon: 'ph-x-circle',
          action: (x, y) => spawnMasterStamp(x, y, 'Ошибка в решении', 'error', 'ph-x-circle')
        },
        {
          id: 'stamp_hint',
          title: 'Хорошая мысль!',
          icon: 'ph-lightbulb',
          action: (x, y) => spawnMasterStamp(x, y, 'Хорошая мысль!', 'hint', 'ph-lightbulb')
        }
      ]
    },
    {
      id: 'scaffolding_hint',
      title: 'Подсказка',
      icon: 'ph-lightbulb',
      color: '#d97706',
      action: (x, y) => spawnMasterHintCard(x, y),
      satellites: [
        {
          id: 'hint_tier1',
          title: 'Намёк (Уровень 1)',
          icon: 'ph-sparkle',
          action: () => actionSendQuickHint(1)
        },
        {
          id: 'hint_tier2',
          title: 'Шаг плана (Ур. 2)',
          icon: 'ph-list-numbers',
          action: () => actionSendQuickHint(2)
        },
        {
          id: 'hint_custom',
          title: 'Написать свою',
          icon: 'ph-pencil-line',
          action: (x, y) => spawnMasterHintCard(x, y)
        }
      ]
    }
  ];

  // ==========================================================================
  // Core Class: BooTeacherOrbit
  // ==========================================================================

  class BooTeacherOrbit {
    constructor() {
      this.isOpen = false;
      this.originX = 0;
      this.originY = 0;
      this.cursorX = window.innerWidth / 2;
      this.cursorY = window.innerHeight / 2;
      this.activeSectorIndex = -1;
      this.activeSatelliteIndex = -1;
      this.activeKey = null;

      this.overlayEl = null;
      this.wheelEl = null;
      this.svgEl = null;
      this.sectorsGroup = null;
      this.labelsGroup = null;
      this.satellitesGroup = null;
      this.satelliteLabelsGroup = null;
      this.hubEl = null;
      this.hubIconEl = null;
      this.hubLabelEl = null;
      this.hubHintEl = null;
      this.toastEl = null;
      this.triggerOrbEl = null;

      this.sectorPaths = [];
      this.sectorIcons = [];
      this.currentSatellites = [];

      this.boundOnKeyDown = this.onKeyDown.bind(this);
      this.boundOnKeyUp = this.onKeyUp.bind(this);
      this.boundOnPointerMove = this.onPointerMove.bind(this);
      this.boundOnPointerUp = this.onPointerUp.bind(this);
      this.boundOnGlobalMouseMove = (e) => {
        this.cursorX = e.clientX;
        this.cursorY = e.clientY;
      };

      this.init();
    }

    init() {
      this.buildDOM();
      this.bindEvents();
    }

    buildDOM() {
      const overlay = document.createElement('div');
      overlay.className = 'boo-master-overlay';
      overlay.id = 'boo-master-orbit-overlay';

      const backdrop = document.createElement('div');
      backdrop.className = 'boo-master-backdrop';
      overlay.appendChild(backdrop);

      const wheel = document.createElement('div');
      wheel.className = 'boo-master-wheel';
      wheel.id = 'boo-master-wheel';

      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', 'boo-master-svg');
      svg.setAttribute('viewBox', '0 0 380 380');

      const sectorsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      sectorsGroup.setAttribute('class', 'boo-master-sectors-layer');

      const labelsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      labelsGroup.setAttribute('class', 'boo-master-labels-layer');

      const satellitesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      satellitesGroup.setAttribute('class', 'boo-master-satellites-layer');

      const satelliteLabelsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      satelliteLabelsGroup.setAttribute('class', 'boo-master-satellite-labels-layer');

      const numSectors = MASTER_SECTORS.length;
      const anglePerSector = 360 / numSectors;

      MASTER_SECTORS.forEach((sec, idx) => {
        const startAngle = idx * anglePerSector;
        const endAngle = (idx + 1) * anglePerSector;
        const midAngle = (startAngle + endAngle) / 2;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('class', 'boo-master-sector');
        path.setAttribute('d', this.createSectorPath(190, 190, 54, 155, startAngle, endAngle));
        path.dataset.sectorIndex = idx;
        sectorsGroup.appendChild(path);
        this.sectorPaths.push(path);

        const iconRadius = 104;
        const toRad = Math.PI / 180;
        const midRad = (midAngle - 90) * toRad;
        const iconX = 190 + iconRadius * Math.cos(midRad);
        const iconY = 190 + iconRadius * Math.sin(midRad);

        const fo = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
        fo.setAttribute('x', iconX - 32);
        fo.setAttribute('y', iconY - 32);
        fo.setAttribute('width', '64');
        fo.setAttribute('height', '64');
        fo.setAttribute('class', 'boo-master-icon-group');

        const iconContainer = document.createElement('div');
        iconContainer.style.cssText = 'width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 3px;';

        const iconEl = document.createElement('i');
        iconEl.className = `ph-bold ${sec.icon}`;

        const titleEl = document.createElement('span');
        titleEl.textContent = sec.title;
        titleEl.style.cssText = 'font-size: 10.5px; font-weight: 850; color: #78350f; max-width: 60px; line-height: 1.1; letter-spacing: -0.01em;';

        iconContainer.appendChild(iconEl);
        iconContainer.appendChild(titleEl);
        fo.appendChild(iconContainer);
        labelsGroup.appendChild(fo);
        this.sectorIcons.push(fo);
      });

      svg.appendChild(sectorsGroup);
      svg.appendChild(labelsGroup);
      svg.appendChild(satellitesGroup);
      svg.appendChild(satelliteLabelsGroup);
      wheel.appendChild(svg);

      // Center Gold Master Hub
      const hub = document.createElement('div');
      hub.className = 'boo-master-center-hub';
      hub.id = 'boo-master-center-hub';

      const hubCrown = document.createElement('i');
      hubCrown.className = 'ph-bold ph-crown boo-master-hub-crown';

      const hubLabel = document.createElement('div');
      hubLabel.className = 'boo-master-hub-label';
      hubLabel.textContent = 'BOO MASTER';

      const hubHint = document.createElement('div');
      hubHint.className = 'boo-master-hub-hint';
      hubHint.textContent = 'Препод-ОС';

      hub.appendChild(hubCrown);
      hub.appendChild(hubLabel);
      hub.appendChild(hubHint);
      wheel.appendChild(hub);

      overlay.appendChild(wheel);
      document.body.appendChild(overlay);

      // Toast Notification
      const toast = document.createElement('div');
      toast.className = 'boo-master-toast';
      toast.id = 'boo-master-toast';
      document.body.appendChild(toast);

      // Floating Amber Trigger Orb (Visible exclusively for teachers)
      const orb = document.createElement('div');
      orb.className = 'boo-master-trigger-orb';
      orb.id = 'boo-master-trigger-orb';
      orb.title = 'Boo Master Orbit (Ctrl + Alt)';
      orb.innerHTML = '<i class="ph-bold ph-crown"></i>';
      orb.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggle(window.innerWidth / 2, window.innerHeight / 2);
      });
      document.body.appendChild(orb);
      this.triggerOrbEl = orb;

      this.overlayEl = overlay;
      this.wheelEl = wheel;
      this.svgEl = svg;
      this.sectorsGroup = sectorsGroup;
      this.labelsGroup = labelsGroup;
      this.satellitesGroup = satellitesGroup;
      this.satelliteLabelsGroup = satelliteLabelsGroup;
      this.hubEl = hub;
      this.hubIconEl = hubCrown;
      this.hubLabelEl = hubLabel;
      this.hubHintEl = hubHint;
      this.toastEl = toast;
    }

    createSectorPath(x, y, innerRadius, outerRadius, startAngle, endAngle) {
      const toRad = Math.PI / 180;
      const startAngleRad = (startAngle - 90) * toRad;
      const endAngleRad = (endAngle - 90) * toRad;

      const p1x = x + outerRadius * Math.cos(startAngleRad);
      const p1y = y + outerRadius * Math.sin(startAngleRad);
      const p2x = x + outerRadius * Math.cos(endAngleRad);
      const p2y = y + outerRadius * Math.sin(endAngleRad);

      const p3x = x + innerRadius * Math.cos(endAngleRad);
      const p3y = y + innerRadius * Math.sin(endAngleRad);
      const p4x = x + innerRadius * Math.cos(startAngleRad);
      const p4y = y + innerRadius * Math.sin(startAngleRad);

      const largeArc = endAngle - startAngle <= 180 ? '0' : '1';

      return [
        `M ${p1x} ${p1y}`,
        `A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${p2x} ${p2y}`,
        `L ${p3x} ${p3y}`,
        `A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${p4x} ${p4y}`,
        'Z'
      ].join(' ');
    }

    bindEvents() {
      window.addEventListener('keydown', this.boundOnKeyDown, { capture: true });
      window.addEventListener('keyup', this.boundOnKeyUp, { capture: true });
      window.addEventListener('mousemove', this.boundOnGlobalMouseMove, { passive: true });
      window.addEventListener('pointermove', this.boundOnPointerMove, { passive: true });
      window.addEventListener('pointerup', this.boundOnPointerUp);
    }

    onKeyDown(e) {
      if (e.key === 'Escape') {
        if (this.isOpen) {
          this.hide(false);
          e.preventDefault();
          return;
        }
      }

      // Hotkey: Ctrl + Alt (or Cmd + Alt on macOS)
      const isCtrlAlt = (e.ctrlKey || e.metaKey) && e.altKey;
      if (isCtrlAlt && !this.isOpen && !e.repeat) {
        this.activeKey = 'CtrlAlt';
        this.show(this.cursorX, this.cursorY);
        e.preventDefault();
      }
    }

    onKeyUp(e) {
      if (!this.isOpen) return;
      if (this.activeKey === 'CtrlAlt') {
        // If either Ctrl or Alt is released, execute selection
        if (!e.ctrlKey && !e.metaKey || !e.altKey) {
          this.hide(true);
        }
      }
    }

    onPointerMove(e) {
      if (!this.isOpen) return;

      const dx = e.clientX - this.originX;
      const dy = e.clientY - this.originY;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (dist < 46) {
        this.clearSelection();
        return;
      }

      let angle = Math.atan2(dy, dx) * (180 / Math.PI) + 90;
      if (angle < 0) angle += 360;

      // 1. Check Sub-Orbit Satellites (outer radius 160..220)
      if (dist >= 160 && this.currentSatellites.length > 0) {
        let bestSatIdx = -1;
        let minDiff = 999;
        this.currentSatellites.forEach((sat, sIdx) => {
          let diff = Math.abs(angle - sat.midAngle);
          if (diff > 180) diff = 360 - diff;
          if (diff < minDiff && diff < 22) {
            minDiff = diff;
            bestSatIdx = sIdx;
          }
        });

        if (bestSatIdx !== -1) {
          this.selectSatellite(bestSatIdx);
          return;
        }
      }

      // 2. Select Main Sector (radius 48..165)
      const numSectors = MASTER_SECTORS.length;
      const anglePerSector = 360 / numSectors;
      const sectorIdx = Math.floor(angle / anglePerSector);

      if (sectorIdx >= 0 && sectorIdx < numSectors) {
        this.selectSector(sectorIdx);
      }
    }

    onPointerUp(e) {
      if (!this.isOpen) return;
      this.hide(true);
    }

    show(x, y) {
      const padding = 205;
      const clampedX = Math.max(padding, Math.min(window.innerWidth - padding, x));
      const clampedY = Math.max(padding, Math.min(window.innerHeight - padding, y));

      this.originX = clampedX;
      this.originY = clampedY;
      this.wheelEl.style.left = `${clampedX}px`;
      this.wheelEl.style.top = `${clampedY}px`;

      this.isOpen = true;
      this.overlayEl.classList.add('is-active');
      this.clearSelection();
    }

    hide(executeAction = true) {
      if (!this.isOpen) return;
      this.isOpen = false;
      this.overlayEl.classList.remove('is-active');

      const secIdx = this.activeSectorIndex;
      const satIdx = this.activeSatelliteIndex;
      const targetX = this.originX;
      const targetY = this.originY;

      this.clearSelection();

      if (executeAction && secIdx >= 0 && secIdx < MASTER_SECTORS.length) {
        const sector = MASTER_SECTORS[secIdx];
        if (satIdx >= 0 && sector.satellites && sector.satellites[satIdx]) {
          const sat = sector.satellites[satIdx];
          if (typeof sat.action === 'function') {
            sat.action(targetX, targetY);
          }
        } else if (typeof sector.action === 'function') {
          sector.action(targetX, targetY);
        }
      }
    }

    toggle(x, y) {
      if (this.isOpen) this.hide(false);
      else this.show(x, y);
    }

    selectSector(idx) {
      if (this.activeSectorIndex === idx && this.activeSatelliteIndex === -1) return;

      this.activeSectorIndex = idx;
      this.activeSatelliteIndex = -1;

      this.sectorPaths.forEach((p, i) => {
        p.classList.toggle('is-selected', i === idx);
      });
      this.sectorIcons.forEach((fo, i) => {
        fo.classList.toggle('is-selected', i === idx);
      });

      const sector = MASTER_SECTORS[idx];
      this.hubEl.classList.add('has-selection');
      this.hubIconEl.className = `ph-bold ${sector.icon} boo-master-hub-crown`;
      this.hubLabelEl.textContent = sector.title;
      this.hubHintEl.textContent = sector.satellites ? 'Выберите вариант' : 'Отпустите';

      this.renderSatellites(idx);
    }

    renderSatellites(sectorIdx) {
      this.satellitesGroup.innerHTML = '';
      this.satelliteLabelsGroup.innerHTML = '';
      this.currentSatellites = [];

      const sector = MASTER_SECTORS[sectorIdx];
      if (!sector || !sector.satellites || sector.satellites.length === 0) {
        this.satellitesGroup.classList.remove('is-visible');
        return;
      }

      const numSats = sector.satellites.length;
      const anglePerSector = 360 / MASTER_SECTORS.length;
      const sectorMidAngle = sectorIdx * anglePerSector + anglePerSector / 2;
      const arcSpread = Math.min(84, numSats * 24);
      const startArc = sectorMidAngle - arcSpread / 2;
      const stepArc = arcSpread / numSats;

      sector.satellites.forEach((sub, sIdx) => {
        const subStart = startArc + sIdx * stepArc;
        const subEnd = subStart + stepArc - 2;
        const subMid = (subStart + subEnd) / 2;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('class', 'boo-master-satellite-petal');
        path.setAttribute('d', this.createSectorPath(190, 190, 160, 218, subStart, subEnd));
        this.satellitesGroup.appendChild(path);

        const toRad = Math.PI / 180;
        const midRad = (subMid - 90) * toRad;
        const iconX = 190 + 189 * Math.cos(midRad);
        const iconY = 190 + 189 * Math.sin(midRad);

        const fo = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
        fo.setAttribute('x', iconX - 25);
        fo.setAttribute('y', iconY - 25);
        fo.setAttribute('width', '50');
        fo.setAttribute('height', '50');
        fo.setAttribute('class', 'boo-master-satellite-icon-group');

        const ic = document.createElement('div');
        ic.style.cssText = 'width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; text-align: center;';

        const iEl = document.createElement('i');
        iEl.className = `ph-bold ${sub.icon}`;

        const txt = document.createElement('span');
        txt.textContent = sub.title;
        txt.style.cssText = 'font-size: 8.5px; font-weight: 800; color: #78350f; max-width: 46px; line-height: 1; letter-spacing: -0.02em;';

        ic.appendChild(iEl);
        ic.appendChild(txt);
        fo.appendChild(ic);
        this.satelliteLabelsGroup.appendChild(fo);

        this.currentSatellites.push({ path, fo, sub, midAngle: subMid });
      });

      this.satellitesGroup.classList.add('is-visible');
    }

    selectSatellite(sIdx) {
      if (this.activeSatelliteIndex === sIdx) return;
      this.activeSatelliteIndex = sIdx;

      this.currentSatellites.forEach((sat, i) => {
        sat.path.classList.toggle('is-selected', i === sIdx);
        sat.fo.classList.toggle('is-selected', i === sIdx);
      });

      if (sIdx >= 0 && sIdx < this.currentSatellites.length) {
        const item = this.currentSatellites[sIdx].sub;
        this.hubIconEl.className = `ph-bold ${item.icon} boo-master-hub-crown`;
        this.hubLabelEl.textContent = item.title;
        this.hubHintEl.textContent = 'Применить';
      }
    }

    clearSelection() {
      this.activeSectorIndex = -1;
      this.activeSatelliteIndex = -1;
      this.sectorPaths.forEach((p) => p.classList.remove('is-selected'));
      this.sectorIcons.forEach((fo) => fo.classList.remove('is-selected'));
      this.satellitesGroup.innerHTML = '';
      this.satelliteLabelsGroup.innerHTML = '';
      this.satellitesGroup.classList.remove('is-visible');
      this.currentSatellites = [];

      this.hubEl.classList.remove('has-selection');
      this.hubIconEl.className = 'ph-bold ph-crown boo-master-hub-crown';
      this.hubLabelEl.textContent = 'BOO MASTER';
      this.hubHintEl.textContent = 'Препод-ОС';
    }

    showToast(message, iconClass = 'ph-crown') {
      if (!this.toastEl) return;
      this.toastEl.innerHTML = `<i class="ph-bold ${iconClass}"></i><span>${message}</span>`;
      this.toastEl.classList.add('is-visible');

      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        this.toastEl.classList.remove('is-visible');
      }, 2600);
    }
  }

  // ==========================================================================
  // Specialized Master Actions (Pedagogical Handlers)
  // ==========================================================================

  let masterInstance = null;

  // 1. Focus Control Actions
  function actionFocusBoard() {
    ['notes-window', 'files-window', 'theory-window', 'terminal-window'].forEach((id) => {
      window.minimizeToDock?.(id);
    });
    window.boostudyLessonControl?.commitControl?.({
      mode: 'present',
      teacher_controls_mode: true
    });
    window.boostudyLessonControl?.sendUi?.({ kind: 'focus_board' });
    if (typeof window.switchRoomWorkMode === 'function') {
      window.switchRoomWorkMode('board');
    }
    document.getElementById('whiteboard-canvas-viewport')?.focus();
    masterInstance?.showToast('Внимание ученика направлено на доску', 'ph-chalkboard-simple');
  }

  function actionFreezeStudent() {
    window.boostudyLessonControl?.commitControl?.({
      student_code_editing: false,
      board_locked: true
    });
    window.boostudyLessonControl?.sendUi?.({ kind: 'freeze_student' });
    masterInstance?.showToast('Ввод ученика заблокирован (Режим демонстрации)', 'ph-lock-simple');
  }

  function actionFreeMode() {
    window.boostudyLessonControl?.commitControl?.({
      student_code_editing: true,
      board_locked: false
    });
    window.boostudyLessonControl?.sendUi?.({ kind: 'free_mode' });
    masterInstance?.showToast('Свободный режим включён: ученик может взаимодействовать', 'ph-lock-simple-open');
  }

  // 2. Teacher Layer Actions
  function actionToggleMarks() {
    if (window.BooCanvasOverlay && typeof window.BooCanvasOverlay.toggleTeacherDraftMode === 'function') {
      const active = window.BooCanvasOverlay.toggleTeacherDraftMode();
      masterInstance?.showToast(active ? 'Скрытый черновик активен (ученик не видит пометки)' : 'Скрытый черновик выключен', active ? 'ph-eye-slash' : 'ph-eye');
      return;
    }
    const canvasWin = document.getElementById('canvas-window') || document.getElementById('whiteboard-canvas-viewport');
    if (canvasWin) {
      const active = canvasWin.classList.toggle('boo-teacher-layer-active');
      masterInstance?.showToast(active ? 'Скрытый слой пометок включён' : 'Скрытый слой пометок выключен', 'ph-highlighter');
    } else {
      masterInstance?.showToast('Откройте доску для режима черновика', 'ph-info');
    }
  }

  function toggleStudentAnswerVisibility() {
    window.lessonTasksController?.toggleAnswerVisibility?.();
    const updatedTask = window.lessonTasksController?.getActiveTask?.();
    const isVis = updatedTask?.answer_visible_to_student === true;
    window.boostudyLessonControl?.sendUi?.({
      kind: 'teacher_answer_vis',
      visible: isVis,
      answer: updatedTask?.answer || '',
      task_id: updatedTask?.lesson_task_id || updatedTask?.task_id
    });
    masterInstance?.showToast(isVis ? 'Ответ открыт ученику' : 'Ответ скрыт от ученика', isVis ? 'ph-eye' : 'ph-eye-slash');
  }

  function actionOpenTeacherNotes() {
    if (typeof window.openWindow === 'function') {
      window.openWindow('teacher-notes-window');
      masterInstance?.showToast('Личные заметки учителя открыты', 'ph-notebook');
    }
  }

  // Floating Official Answer Card (Real Task Integration)
  function spawnAnswerCard(x, y) {
    const existing = document.getElementById('boo-master-answer-card');
    if (existing) {
      existing.remove();
      masterInstance?.showToast('Карточка ответа закрыта', 'ph-check-circle');
      return;
    }

    const host = getMasterWorkspaceHost();
    const coords = getWorkspaceCoordinates(x, y);

    const card = document.createElement('div');
    card.id = 'boo-master-answer-card';
    card.className = 'boo-master-card';
    card.style.left = `${Math.max(20, Math.min(coords.maxW - 380, coords.x - 180))}px`;
    card.style.top = `${Math.max(20, Math.min(coords.maxH - 320, coords.y - 120))}px`;

    const activeTask = window.lessonTasksController?.getActiveTask?.();
    const taskTitle = activeTask?.title || (activeTask?.task_number ? `Задание №${activeTask.task_number}` : 'Текущее задание');
    const answer = String(activeTask?.answer || '').trim();
    const answerVisible = activeTask?.answer_visible_to_student === true;
    const criteriaOrSolution = activeTask?.criteria || activeTask?.solution || activeTask?.explanation || (Array.isArray(activeTask?.subtasks) ? activeTask.subtasks.map((s) => s.text).join('\n') : '');

    card.innerHTML = `
      <div class="boo-master-card-header">
        <div class="boo-master-card-title">
          <i class="ph-bold ph-check-circle text-emerald-500"></i>
          <span>${escapeHtml(taskTitle)}</span>
        </div>
        <button type="button" class="boo-master-card-close" aria-label="Закрыть"><i class="ph-bold ph-x"></i></button>
      </div>
      <div class="boo-master-answer-body">
        <div class="flex items-center justify-between gap-2">
          <span class="boo-master-answer-badge">Эталонный ответ</span>
          <span id="boo-answer-vis-status" class="text-[10px] font-bold ${answerVisible ? 'text-emerald-600' : 'text-amber-600'}">
            <i class="ph-bold ${answerVisible ? 'ph-eye' : 'ph-eye-slash'}"></i> ${answerVisible ? 'Виден ученику' : 'Скрыт от ученика'}
          </span>
        </div>
        <div class="boo-master-answer-val">${escapeHtml(answer || 'Не задан в условии')}</div>
        ${criteriaOrSolution ? `
          <div class="text-xs text-slate-600 space-y-1">
            <div class="text-[11px] text-amber-900 bg-amber-50/80 p-2.5 rounded-xl border border-amber-200 mt-1 max-h-32 overflow-y-auto leading-relaxed">
              <strong>Решение / Критерии:</strong>
              <div class="mt-1 whitespace-pre-wrap">${escapeHtml(criteriaOrSolution)}</div>
            </div>
          </div>
        ` : ''}
        <div class="flex items-center gap-1.5 pt-1">
          <button type="button" class="boo-inspector-btn flex-1 py-1.5 text-[11px]" id="boo-toggle-student-answer">
            <i class="ph-bold ${answerVisible ? 'ph-eye-slash' : 'ph-eye'}"></i>
            <span>${answerVisible ? 'Скрыть от ученика' : 'Показать ученику'}</span>
          </button>
          ${answer ? `
            <button type="button" class="boo-inspector-btn py-1.5 px-3 text-[11px]" id="boo-copy-answer" title="Скопировать ответ">
              <i class="ph-bold ph-copy"></i>
            </button>
          ` : ''}
        </div>
      </div>
    `;

    host.appendChild(card);
    bringMasterElementToFront(card);
    makeMasterDraggable(card, card.querySelector('.boo-master-card-header'));
    card.querySelector('.boo-master-card-close').addEventListener('click', () => card.remove());

    const toggleBtn = card.querySelector('#boo-toggle-student-answer');
    toggleBtn?.addEventListener('click', () => {
      window.lessonTasksController?.toggleAnswerVisibility?.();
      const updatedTask = window.lessonTasksController?.getActiveTask?.();
      const isVis = updatedTask?.answer_visible_to_student === true;
      const statusEl = card.querySelector('#boo-answer-vis-status');
      if (statusEl) {
        statusEl.className = `text-[10px] font-bold ${isVis ? 'text-emerald-600' : 'text-amber-600'}`;
        statusEl.innerHTML = `<i class="ph-bold ${isVis ? 'ph-eye' : 'ph-eye-slash'}"></i> ${isVis ? 'Виден ученику' : 'Скрыт от ученика'}`;
      }
      toggleBtn.innerHTML = `<i class="ph-bold ${isVis ? 'ph-eye-slash' : 'ph-eye'}"></i> <span>${isVis ? 'Скрыть от ученика' : 'Показать ученику'}</span>`;
      window.boostudyLessonControl?.sendUi?.({
        kind: 'teacher_answer_vis',
        visible: isVis,
        answer: updatedTask?.answer || '',
        task_id: updatedTask?.lesson_task_id || updatedTask?.task_id
      });
      masterInstance?.showToast(isVis ? 'Ответ открыт ученику' : 'Ответ скрыт от ученика', isVis ? 'ph-eye' : 'ph-eye-slash');
    });

    const copyBtn = card.querySelector('#boo-copy-answer');
    copyBtn?.addEventListener('click', () => {
      if (answer && navigator.clipboard) {
        navigator.clipboard.writeText(answer).then(() => {
          masterInstance?.showToast('Ответ скопирован в буфер', 'ph-copy');
        });
      }
    });

    masterInstance?.showToast('Карточка эталонного ответа открыта', 'ph-check-circle');
  }

  // 3. Task Management Actions
  function actionPrevTask() {
    if (window.lessonTasksController?.prevTask) {
      const task = window.lessonTasksController.prevTask();
      if (task) {
        const taskId = task.lesson_task_id || task.task_id;
        window.boostudyLessonControl?.sendUi?.({
          kind: 'task_switch',
          task_id: taskId
        });
        masterInstance?.showToast(`Переход: ${task.title || ('Задание №' + task.task_number)}`, 'ph-arrow-circle-left');
        return;
      }
    }
    const list = document.getElementById('task-attached-list');
    const currentActive = list?.querySelector('[aria-current="true"]');
    const prevBtn = currentActive?.previousElementSibling || list?.lastElementChild;
    if (prevBtn) {
      prevBtn.click();
      masterInstance?.showToast('Переход к предыдущей задаче', 'ph-arrow-circle-left');
    } else {
      masterInstance?.showToast('В уроке пока нет прикрепленных задач', 'ph-info');
    }
  }

  function actionNextTask() {
    if (window.lessonTasksController?.nextTask) {
      const task = window.lessonTasksController.nextTask();
      if (task) {
        const taskId = task.lesson_task_id || task.task_id;
        window.boostudyLessonControl?.sendUi?.({
          kind: 'task_switch',
          task_id: taskId
        });
        masterInstance?.showToast(`Переход: ${task.title || ('Задание №' + task.task_number)}`, 'ph-arrow-circle-right');
        return;
      }
    }
    const list = document.getElementById('task-attached-list');
    const currentActive = list?.querySelector('[aria-current="true"]');
    const nextBtn = currentActive?.nextElementSibling || list?.firstElementChild;
    if (nextBtn) {
      nextBtn.click();
      masterInstance?.showToast('Переход к следующей задаче', 'ph-arrow-circle-right');
    } else {
      masterInstance?.showToast('В уроке пока нет прикрепленных задач', 'ph-info');
    }
  }

  function actionOpenTaskBank() {
    if (window.lessonTasksController?.openBank) {
      window.lessonTasksController.openBank();
      masterInstance?.showToast('Банк задач открыт', 'ph-magnifying-glass-plus');
    } else if (typeof window.openWindow === 'function') {
      window.openWindow('task-window');
      masterInstance?.showToast('Окно заданий открыто', 'ph-books');
    }
  }

  function actionGenerateAnalog() {
    const activeTask = window.lessonTasksController?.getActiveTask?.();
    const taskTitle = activeTask?.title || (activeTask?.task_number ? `Задание №${activeTask.task_number}` : '');
    if (window.lessonTasksController?.openCompose) {
      window.lessonTasksController.openCompose();
    }
    if (typeof window.toggleBooAICopilot === 'function') {
      window.toggleBooAICopilot();
      const popover = document.getElementById('booai-popover');
      const input = popover?.querySelector('input');
      if (input) {
        input.value = taskTitle ? `Сгенерируй аналог для задачи: ${taskTitle}` : 'Сгенерируй аналогичную задачу по текущей теме';
        input.focus();
      }
    }
    masterInstance?.showToast('AI Lab: генерация аналога подготовлена', 'ph-sparkle');
  }

  // 4. Pedagogical Stamps (Synchronized with student & canvas-space aware)
  function spawnMasterStamp(x, y, label, type, icon) {
    const canvasViewport = document.getElementById('whiteboard-canvas-viewport') || document.querySelector('.boo-canvas-overlay');
    if (canvasViewport && window.BooCanvasOverlay && typeof window.BooCanvasOverlay.insertStamp === 'function') {
      const stampObj = window.BooCanvasOverlay.insertStamp(label, type, icon, x, y);
      if (stampObj) {
        masterInstance?.showToast(`Штамп «${label}» нанесён на доску`, icon);
        return;
      }
    }

    const host = getMasterWorkspaceHost();
    const coords = getWorkspaceCoordinates(x, y);
    const stampId = 'teacher_stamp_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);

    const stamp = document.createElement('div');
    stamp.className = 'boo-orbit-stamp-item';
    stamp.dataset.stampId = stampId;
    stamp.style.left = `${coords.x}px`;
    stamp.style.top = `${coords.y}px`;

    stamp.innerHTML = `
      <div class="boo-orbit-badge-stamp boo-master-stamp-${type}">
        <i class="ph-bold ${icon}"></i>
        <span>${escapeHtml(label)}</span>
        <button type="button" class="boo-stamp-close" aria-label="Удалить"><i class="ph-bold ph-x"></i></button>
      </div>
    `;

    host.appendChild(stamp);
    bringMasterElementToFront(stamp);

    const badge = stamp.querySelector('.boo-orbit-badge-stamp');
    const closeBtn = stamp.querySelector('.boo-stamp-close');
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      stamp.remove();
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_stamp_remove',
        id: stampId
      });
    });

    stamp.addEventListener('pointerdown', (e) => {
      if (!e.target.closest('.boo-stamp-close')) bringMasterElementToFront(stamp);
    });

    const sendMove = (curX, curY) => {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_stamp_move',
        id: stampId,
        x: curX,
        y: curY,
        maxW: host.clientWidth || window.innerWidth,
        maxH: host.clientHeight || window.innerHeight
      });
    };

    makeMasterDraggable(stamp, badge, sendMove, sendMove);

    // Broadcast stamp to student screen in real time
    window.boostudyLessonControl?.sendUi?.({
      kind: 'teacher_stamp',
      id: stampId,
      label: label,
      type: type,
      icon: icon,
      x: coords.x,
      y: coords.y,
      maxW: coords.maxW,
      maxH: coords.maxH,
    });

    masterInstance?.showToast(`Штамп «${label}» выставлен и отправлен`, icon);
  }

  // Pedagogical Scaffolding Hint Card
  function spawnMasterHintCard(x, y) {
    const host = getMasterWorkspaceHost();
    const coords = getWorkspaceCoordinates(x, y);

    const activeTask = window.lessonTasksController?.getActiveTask?.();
    const taskTitle = activeTask?.title || (activeTask?.task_number ? `№${activeTask.task_number}` : 'Задание');

    const card = document.createElement('div');
    card.id = 'boo-master-hint-dialog';
    card.className = 'boo-master-card';
    card.style.left = `${Math.max(20, Math.min(coords.maxW - 360, coords.x - 180))}px`;
    card.style.top = `${Math.max(20, Math.min(coords.maxH - 320, coords.y - 120))}px`;

    // Tier presets for pedagogical scaffolding
    const tiers = [
      {
        tier: 1,
        title: 'Уровень 1 · Наводящий вопрос',
        hint: `Подумай над граничным условием задачи «${taskTitle}». Какие крайние случаи могут повлиять на результат?`
      },
      {
        tier: 2,
        title: 'Уровень 2 · Алгоритм и структуры',
        hint: 'Разбей решение на два этапа: эффективное чтение данных и потоковая обработка без полного сохранения в память.'
      },
      {
        tier: 3,
        title: 'Уровень 3 · Языковая реализация Python',
        hint: 'Используй срезы, словари или генераторы для лаконичной фильтрации значений.'
      }
    ];

    card.innerHTML = `
      <div class="boo-master-card-header">
        <div class="boo-master-card-title">
          <i class="ph-bold ph-lightbulb text-amber-500"></i>
          <span>Ступенчатая подсказка ученику</span>
        </div>
        <button type="button" class="boo-master-card-close" aria-label="Закрыть"><i class="ph-bold ph-x"></i></button>
      </div>
      <div class="p-3.5 space-y-2.5 text-xs text-slate-800">
        <div class="flex gap-1.5 p-1 bg-amber-50/80 rounded-xl border border-amber-200">
          <button type="button" class="boo-hint-tier-tab flex-1 py-1 rounded-lg font-bold text-[10px] bg-white text-amber-900 shadow-xs border border-amber-200" data-tier="0">Ур. 1</button>
          <button type="button" class="boo-hint-tier-tab flex-1 py-1 rounded-lg font-bold text-[10px] text-amber-800 hover:bg-white/60" data-tier="1">Ур. 2</button>
          <button type="button" class="boo-hint-tier-tab flex-1 py-1 rounded-lg font-bold text-[10px] text-amber-800 hover:bg-white/60" data-tier="2">Ур. 3</button>
        </div>
        <div>
          <label class="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1" id="boo-hint-title">${escapeHtml(tiers[0].title)}</label>
          <textarea id="boo-master-hint-text" class="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 focus:bg-white focus:outline-none focus:border-amber-400 transition-colors resize-none h-20 leading-relaxed font-sans">${escapeHtml(tiers[0].hint)}</textarea>
        </div>
        <button type="button" class="boo-inspector-btn w-full py-2" id="boo-send-hint-btn" style="background: #4f46e5;">
          <i class="ph-bold ph-paper-plane-tilt"></i>
          <span>Отправить ученику на экран</span>
        </button>
      </div>
    `;

    host.appendChild(card);
    bringMasterElementToFront(card);
    makeMasterDraggable(card, card.querySelector('.boo-master-card-header'));
    card.querySelector('.boo-master-card-close').addEventListener('click', () => card.remove());

    let currentTierIdx = 0;
    const titleEl = card.querySelector('#boo-hint-title');
    const textEl = card.querySelector('#boo-master-hint-text');

    card.querySelectorAll('.boo-hint-tier-tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        card.querySelectorAll('.boo-hint-tier-tab').forEach((t) => {
          t.className = 'boo-hint-tier-tab flex-1 py-1 rounded-lg font-bold text-[10px] text-amber-800 hover:bg-white/60';
        });
        tab.className = 'boo-hint-tier-tab flex-1 py-1 rounded-lg font-bold text-[10px] bg-white text-amber-900 shadow-xs border border-amber-200';
        currentTierIdx = Number(tab.dataset.tier);
        titleEl.textContent = tiers[currentTierIdx].title;
        textEl.value = tiers[currentTierIdx].hint;
      });
    });

    card.querySelector('#boo-send-hint-btn').addEventListener('click', () => {
      const text = textEl.value.trim();
      if (!text) return;
      window.boostudyLessonControl?.sendUi?.({
        kind: 'teacher_hint',
        hint: text,
        tier: currentTierIdx + 1
      });
      masterInstance?.showToast('Подсказка отправлена на экран ученика', 'ph-paper-plane-tilt');
      card.remove();
    });
  }

  function actionSendQuickHint(tierNum) {
    const activeTask = window.lessonTasksController?.getActiveTask?.();
    const taskTitle = activeTask?.title || (activeTask?.task_number ? `№${activeTask.task_number}` : 'Задание');
    const hintText = tierNum === 1
      ? `Подумай над граничным условием задачи «${taskTitle}». Какие крайние случаи могут повлиять на результат?`
      : 'Разбей решение на два этапа: аккуратная фильтрация входных данных и последовательная проверка условий.';
    window.boostudyLessonControl?.sendUi?.({
      kind: 'teacher_hint',
      hint: hintText,
      tier: tierNum
    });
    masterInstance?.showToast(`Подсказка (Ур. ${tierNum}) отправлена ученику`, 'ph-paper-plane-tilt');
  }

  // Draggable Card Helper with live remote move streaming
  function makeMasterDraggable(card, header, onDragEnd, onDragMove) {
    let isDragging = false;
    let startX = 0, startY = 0;
    let initialLeft = 0, initialTop = 0;
    let lastMoveSentAt = 0;
    const moveCallback = (typeof onDragMove === 'function') ? onDragMove : (typeof onDragEnd === 'function' ? onDragEnd : null);

    card.addEventListener('pointerdown', (e) => {
      if (!e.target.closest('button, input, textarea, select')) {
        bringMasterElementToFront(card);
      }
    });

    header.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button, input, textarea')) return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      initialLeft = parseFloat(card.style.left) || 0;
      initialTop = parseFloat(card.style.top) || 0;
      header.setPointerCapture?.(e.pointerId);
      bringMasterElementToFront(card);
      e.preventDefault();
    });

    header.addEventListener('pointermove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      const nx = initialLeft + dx;
      const ny = initialTop + dy;
      card.style.left = `${nx}px`;
      card.style.top = `${ny}px`;

      const now = performance.now();
      if (now - lastMoveSentAt > 35 && moveCallback) {
        lastMoveSentAt = now;
        moveCallback(nx, ny);
      }
    });

    const stopDrag = () => {
      if (isDragging) {
        isDragging = false;
        const finalX = parseFloat(card.style.left) || 0;
        const finalY = parseFloat(card.style.top) || 0;
        if (typeof onDragEnd === 'function') {
          onDragEnd(finalX, finalY);
        }
      }
    };
    header.addEventListener('pointerup', stopDrag);
    header.addEventListener('pointercancel', stopDrag);
  }

  // Initialize strictly on DOM ready if teacher role is verified
  function bootstrapBooTeacherOrbit() {
    if (!isTeacherRole()) return;
    if (window._booTeacherOrbitInstance) return;

    masterInstance = new BooTeacherOrbit();
    window._booTeacherOrbitInstance = masterInstance;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapBooTeacherOrbit);
  } else {
    bootstrapBooTeacherOrbit();
  }
})();
