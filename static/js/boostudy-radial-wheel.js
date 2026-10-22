/**
 * BooStudy OS — Boo Orbit 2.1 (Орбита)
 * White Frosted Glass Radial Toolset with Stable Satellite Sub-Orbits,
 * Precise 2x Canvas Loupe & Unified Z-Index Layering
 */

(function (window, document) {
  'use strict';

  const escapeHtml = (val) => String(val ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));

  // 8 Core Sectors Configuration with Sub-Orbits
  const SECTORS = [
    {
      id: 'focus_timer',
      title: 'Таймер',
      hint: 'Север (0°)',
      icon: 'ph-timer',
      angle: 0,
      action: (x, y) => spawnTimerWidget(x, y)
    },
    {
      id: 'mini_calc',
      title: 'Калькулятор',
      hint: 'СВ (45°)',
      icon: 'ph-calculator',
      angle: 45,
      action: (x, y) => spawnCalcWidget(x, y)
    },
    {
      id: 'pulse_beacon',
      title: 'Маячок',
      hint: 'Восток (90°)',
      icon: 'ph-broadcast',
      angle: 90,
      action: (x, y) => triggerPulseBeacon(x, y)
    },
    {
      id: 'sticky_note',
      title: 'Стикер',
      hint: 'ЮВ (135°)',
      icon: 'ph-note-pencil',
      angle: 135,
      subSectors: [
        { id: 'sticky_yellow', title: 'Жёлтый', icon: 'ph-note', color: 'yellow', action: (x, y) => spawnStickyNote(x, y, 'yellow') },
        { id: 'sticky_lavender', title: 'Лаванда', icon: 'ph-note', color: 'lavender', action: (x, y) => spawnStickyNote(x, y, 'lavender') },
        { id: 'sticky_mint', title: 'Мята', icon: 'ph-note', color: 'mint', action: (x, y) => spawnStickyNote(x, y, 'mint') }
      ],
      action: (x, y) => spawnStickyNote(x, y, 'yellow')
    },
    {
      id: 'cheat_sheet',
      title: 'Шпаргалка',
      hint: 'Юг (180°)',
      icon: 'ph-book-bookmark',
      angle: 180,
      action: (x, y) => spawnCheatSheet(x, y)
    },
    {
      id: 'laser_tracer',
      title: 'Лазерный след',
      hint: 'ЮЗ (225°)',
      icon: 'ph-magic-wand',
      angle: 225,
      action: () => toggleLaserTracer()
    },
    {
      id: 'zoom_loupe',
      title: 'Лупа 2x',
      hint: 'Запад (270°)',
      icon: 'ph-magnifying-glass-plus',
      angle: 270,
      action: (x, y) => toggleCanvasLoupe(x, y)
    },
    {
      id: 'check_stamps',
      title: 'Штампы',
      hint: 'СЗ (315°)',
      icon: 'ph-seal-check',
      angle: 315,
      subSectors: [
        { id: 'stamp_success', title: '✓ Верно', icon: 'ph-check-circle', type: 'success', action: (x, y) => spawnDraggableStamp(x, y, '✓ Верно', 'success', 'ph-check-circle') },
        { id: 'stamp_danger', title: '✗ Ошибка', icon: 'ph-x-circle', type: 'danger', action: (x, y) => spawnDraggableStamp(x, y, '✗ Ошибка', 'danger', 'ph-x-circle') },
        { id: 'stamp_star', title: '★ Важно', icon: 'ph-star', type: 'star', action: (x, y) => spawnDraggableStamp(x, y, '★ Важно', 'star', 'ph-star') },
        { id: 'stamp_question', title: '? Вопрос', icon: 'ph-question', type: 'question', action: (x, y) => spawnDraggableStamp(x, y, '? Вопрос', 'question', 'ph-question') },
        { id: 'stamp_idea', title: '💡 Идея', icon: 'ph-lightbulb', type: 'idea', action: (x, y) => spawnDraggableStamp(x, y, '💡 Идея', 'idea', 'ph-lightbulb') }
      ],
      action: (x, y) => spawnDraggableStamp(x, y, '✓ Верно', 'success', 'ph-check-circle')
    }
  ];

  const CONFIG = {
    wheelRadius: 155,
    innerRadius: 54,
    deadzoneRadius: 32,
    clampingPadding: 180
  };

  // ==========================================================================
  // Unified Z-Index & Workspace Host System (Integrated with BooStudy OS)
  // ==========================================================================
  function getOrbitWorkspaceHost() {
    return document.getElementById('trainer-arena-view') ||
           document.querySelector('.room-lesson-os') ||
           document.querySelector('.task-workspace-container') ||
           document.body;
  }

  function getWorkspaceCoordinates(clientX, clientY) {
    const host = getOrbitWorkspaceHost();
    if (host === document.body) {
      return {
        x: clientX,
        y: clientY,
        maxW: window.innerWidth,
        maxH: window.innerHeight
      };
    }
    const rect = host.getBoundingClientRect();
    return {
      x: clientX - rect.left,
      y: clientY - rect.top,
      maxW: host.clientWidth || window.innerWidth,
      maxH: host.clientHeight || window.innerHeight
    };
  }

  const MIN_ORBIT_Z = 45;
  const MAX_ORBIT_Z = 950; // Dock is at 1100, System bar at 1200

  function normalizeZIndexes() {
    const host = getOrbitWorkspaceHost();
    const elements = Array.from(host.querySelectorAll(
      '.glass-os-window, .boo-orbit-card, .boo-orbit-sticky-card, .boo-orbit-stamp-item, .lesson-studio-window'
    )).filter(el => el.id !== 'canvas-window')
      .map(el => ({ el, z: parseInt(window.getComputedStyle(el).zIndex, 10) || MIN_ORBIT_Z }))
      .sort((a, b) => a.z - b.z);

    let start = MIN_ORBIT_Z;
    elements.forEach(item => {
      start += 1;
      item.el.style.setProperty('z-index', String(start), 'important');
    });
    if (window.windowManager) {
      window.windowManager.globalZIndex = start;
    }
  }

  function getTopZIndex() {
    let maxZ = MIN_ORBIT_Z;
    if (window.windowManager && typeof window.windowManager.globalZIndex === 'number') {
      maxZ = Math.max(maxZ, Math.min(window.windowManager.globalZIndex, MAX_ORBIT_Z - 1));
    }
    const host = getOrbitWorkspaceHost();
    const elements = host.querySelectorAll(
      '.glass-os-window, .boo-orbit-card, .boo-orbit-sticky-card, .boo-orbit-stamp-item, .lesson-studio-window'
    );
    elements.forEach((el) => {
      if (el.id === 'canvas-window') return;
      const raw = window.getComputedStyle(el).zIndex;
      const z = parseInt(raw, 10);
      if (!isNaN(z) && z < MAX_ORBIT_Z && z > maxZ) {
        maxZ = z;
      }
    });
    return maxZ;
  }

  function bringElementToFront(el) {
    if (!el || el.id === 'canvas-window') return MIN_ORBIT_Z;
    let nextZ = getTopZIndex() + 1;
    if (nextZ >= MAX_ORBIT_Z) {
      normalizeZIndexes();
      nextZ = getTopZIndex() + 1;
    }
    el.style.setProperty('z-index', String(nextZ), 'important');
    if (window.windowManager) {
      window.windowManager.globalZIndex = nextZ;
    }
    return nextZ;
  }

  function hookOSWindowManager() {
    if (window.windowManager && !window.windowManager._orbitZHooked) {
      window.windowManager.bringToFront = function (element) {
        if (!element) return;
        return bringElementToFront(element);
      };
      window.windowManager._orbitZHooked = true;
    }
  }

  hookOSWindowManager();
  document.addEventListener('DOMContentLoaded', hookOSWindowManager);

  // Non-capture listener: when clicking on an OS window or widget, bring it to front
  // (strictly ignoring buttons, window action dots, dock and system bar to avoid interfering with controls)
  document.addEventListener('pointerdown', (e) => {
    if (e.target.closest('button, input, textarea, select, .lesson-os-window-dot, #board-dock, .board-dock, .board-dock-item, .lesson-os-system-bar')) return;
    const el = e.target.closest('.glass-os-window, .boo-orbit-card, .boo-orbit-sticky-card, .boo-orbit-stamp-item, .lesson-studio-window');
    if (el && el.id !== 'canvas-window') {
      bringElementToFront(el);
    }
  }, false);

  class BooOrbit {
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
      this.hubEl = null;
      this.hubIconEl = null;
      this.hubLabelEl = null;
      this.hubHintEl = null;
      this.toastEl = null;
      this.triggerOrbEl = null;
      this.satellitesGroup = null;
      this.satelliteLabelsGroup = null;

      this.sectorPaths = [];
      this.sectorIcons = [];
      this.sectorTitles = [];
      this.currentSatellites = [];

      this.boundOnKeyDown = this.onKeyDown.bind(this);
      this.boundOnKeyUp = this.onKeyUp.bind(this);
      this.boundOnPointerMove = this.onPointerMove.bind(this);
      this.boundOnPointerUp = this.onPointerUp.bind(this);
      this.boundOnGlobalMouseMove = (e) => {
        this.cursorX = e.clientX;
        this.cursorY = e.clientY;
      };
    }

    init(options = {}) {
      if (this.overlayEl) return;

      hookOSWindowManager();
      this.createDOM();
      this.bindEvents();

      if (options.showOrb !== false) {
        this.createTriggerOrb();
      }
    }

    createDOM() {
      // Root Overlay
      const overlay = document.createElement('div');
      overlay.className = 'boo-radial-wheel-overlay';
      overlay.setAttribute('aria-hidden', 'true');

      // Backdrop
      const backdrop = document.createElement('div');
      backdrop.className = 'boo-radial-wheel-backdrop';
      backdrop.addEventListener('pointerdown', (e) => {
        e.stopPropagation();
        this.hide(false);
      });
      overlay.appendChild(backdrop);

      // Wheel Container (Generous 380px)
      const wheel = document.createElement('div');
      wheel.className = 'boo-radial-wheel';

      // SVG Ring
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', 'boo-radial-svg');
      svg.setAttribute('viewBox', '-190 -190 380 380');

      const R = CONFIG.wheelRadius;
      const r = CONFIG.innerRadius;
      const stepAngle = 360 / SECTORS.length; // 45 deg
      const halfStep = stepAngle / 2;
      const gap = 1.2;

      const sectorsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      sectorsGroup.setAttribute('class', 'boo-wheel-sectors-layer');

      const labelsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      labelsGroup.setAttribute('class', 'boo-wheel-labels-layer');

      const satellitesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      satellitesGroup.setAttribute('class', 'boo-orbit-satellites-layer');

      const satelliteLabelsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      satelliteLabelsGroup.setAttribute('class', 'boo-satellite-labels-layer');

      SECTORS.forEach((sec, idx) => {
        const startDeg = sec.angle - halfStep + gap / 2;
        const endDeg = sec.angle + halfStep - gap / 2;

        const pathData = this.describeArc(0, 0, r, R, startDeg, endDeg);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathData);
        path.setAttribute('class', 'boo-wheel-sector');
        path.dataset.index = String(idx);

        sectorsGroup.appendChild(path);
        this.sectorPaths.push(path);

        // Icon Position
        const midAngleRad = ((sec.angle - 90) * Math.PI) / 180;
        const iconR = (R + r) / 2 + 3;
        const ix = Math.cos(midAngleRad) * iconR;
        const iy = Math.sin(midAngleRad) * iconR;

        const fo = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
        fo.setAttribute('x', String(ix - 15));
        fo.setAttribute('y', String(iy - 15));
        fo.setAttribute('width', '30');
        fo.setAttribute('height', '30');
        fo.setAttribute('class', 'boo-wheel-icon-group');

        const iconContainer = document.createElement('div');
        iconContainer.style.width = '100%';
        iconContainer.style.height = '100%';
        iconContainer.style.display = 'flex';
        iconContainer.style.alignItems = 'center';
        iconContainer.style.justifyContent = 'center';

        const iconEl = document.createElement('i');
        iconEl.className = `ph-bold ${sec.icon}`;
        iconContainer.appendChild(iconEl);
        fo.appendChild(iconContainer);

        labelsGroup.appendChild(fo);
        this.sectorIcons.push(fo);
      });

      svg.appendChild(sectorsGroup);
      svg.appendChild(labelsGroup);
      svg.appendChild(satellitesGroup);
      svg.appendChild(satelliteLabelsGroup);
      wheel.appendChild(svg);

      // Center Hub
      const hub = document.createElement('div');
      hub.className = 'boo-wheel-center-hub';

      const hubIcon = document.createElement('i');
      hubIcon.className = 'ph-bold ph-compass boo-wheel-hub-icon';

      const hubLabel = document.createElement('span');
      hubLabel.className = 'boo-wheel-hub-label';
      hubLabel.textContent = 'Boo Orbit';

      const hubHint = document.createElement('span');
      hubHint.className = 'boo-wheel-hub-hint';
      hubHint.textContent = 'ОРБИТА';

      hub.appendChild(hubIcon);
      hub.appendChild(hubLabel);
      hub.appendChild(hubHint);
      wheel.appendChild(hub);

      overlay.appendChild(wheel);
      document.body.appendChild(overlay);

      // Toast Notification
      const toast = document.createElement('div');
      toast.className = 'boo-wheel-toast';
      toast.innerHTML = '<i class="ph-bold ph-check-circle"></i><span class="boo-wheel-toast-text"></span>';
      document.body.appendChild(toast);

      this.overlayEl = overlay;
      this.wheelEl = wheel;
      this.svgEl = svg;
      this.hubEl = hub;
      this.hubIconEl = hubIcon;
      this.hubLabelEl = hubLabel;
      this.hubHintEl = hubHint;
      this.toastEl = toast;
      this.satellitesGroup = satellitesGroup;
      this.satelliteLabelsGroup = satelliteLabelsGroup;
    }

    createTriggerOrb() {
      const orb = document.createElement('div');
      orb.className = 'boo-wheel-trigger-orb';
      orb.setAttribute('role', 'button');
      orb.setAttribute('aria-label', 'Открыть штурвал Boo Orbit');
      orb.setAttribute('title', 'Boo Orbit (Alt / ~)');
      orb.innerHTML = '<i class="ph-bold ph-compass"></i>';

      let pressTimer = null;
      orb.addEventListener('pointerdown', (e) => {
        e.stopPropagation();
        pressTimer = setTimeout(() => {
          this.show(e.clientX, e.clientY);
        }, 120);
      });

      orb.addEventListener('pointerup', (e) => {
        clearTimeout(pressTimer);
        if (!this.isOpen) {
          const rect = orb.getBoundingClientRect();
          this.show(rect.left + rect.width / 2, rect.top - 90);
        }
      });

      document.body.appendChild(orb);
      this.triggerOrbEl = orb;
    }

    describeArc(x, y, innerRadius, outerRadius, startAngle, endAngle) {
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

    isTypingInputActive() {
      const el = document.activeElement;
      if (!el) return false;
      const tag = el.tagName;
      return (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        el.isContentEditable ||
        Boolean(el.closest('.monaco-editor, .CodeMirror, [contenteditable="true"]'))
      );
    }

    onKeyDown(e) {
      if (e.key === 'Escape') {
        if (this.isOpen) {
          this.hide(false);
          e.preventDefault();
          return;
        }
        if (window._activeLoupe) {
          window._activeLoupe.remove();
          window._activeLoupe = null;
          e.preventDefault();
          return;
        }
      }

      const isAltTrigger = (e.key === 'Alt' || e.code === 'AltLeft' || e.code === 'AltRight') && !e.ctrlKey && !e.metaKey;
      if (window._booTeacherOrbitInstance && window._booTeacherOrbitInstance.isOpen) {
        return;
      }
      const isTildeTrigger = e.key === '`' || e.key === '~' || e.code === 'Backquote' || e.key === 'ё' || e.key === 'Ё';

      // Only block tilde/ё when typing in an active text input/editor so character typing is preserved.
      // Alt is a modifier key and MUST ALWAYS summon Boo Orbit, even when typing inside notes or code!
      if (isTildeTrigger && this.isTypingInputActive()) {
        return;
      }

      if ((isAltTrigger || isTildeTrigger) && !this.isOpen && !e.repeat) {
        this.activeKey = e.key;
        this.show(this.cursorX, this.cursorY);
        e.preventDefault();
      }
    }

    onKeyUp(e) {
      if (!this.isOpen) return;

      const isMatchingAlt = (e.key === 'Alt' || e.code === 'AltLeft' || e.code === 'AltRight') &&
        (this.activeKey === 'Alt' || this.activeKey === 'AltLeft' || this.activeKey === 'AltRight');
      const isMatchingTilde = (e.key === '`' || e.key === '~' || e.code === 'Backquote' || e.key === 'ё' || e.key === 'Ё') &&
        (this.activeKey === '`' || this.activeKey === '~' || this.activeKey === 'Backquote' || this.activeKey === 'ё' || this.activeKey === 'Ё');

      if (isMatchingAlt || isMatchingTilde) {
        const targetX = this.originX;
        const targetY = this.originY;
        this.hide(true, targetX, targetY);
        e.preventDefault();
      }
    }

    onPointerMove(e) {
      this.cursorX = e.clientX;
      this.cursorY = e.clientY;

      if (!this.isOpen) return;

      const dx = e.clientX - this.originX;
      const dy = e.clientY - this.originY;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (dist < CONFIG.deadzoneRadius) {
        this.highlightSector(-1);
        this.clearSatellites();
        return;
      }

      let deg = (Math.atan2(dy, dx) * 180) / Math.PI + 90;
      if (deg < 0) deg += 360;

      // Stable Hysteresis for Satellite Menus:
      // If a sector with subSectors is active, lock into its cone when moving toward satellites!
      if (this.activeSectorIndex >= 0) {
        const curSec = SECTORS[this.activeSectorIndex];
        if (curSec.subSectors && curSec.subSectors.length > 0) {
          let diff = Math.abs(deg - curSec.angle);
          if (diff > 180) diff = 360 - diff;

          // Wide 42-degree cone locking
          if (diff < 42 && dist > CONFIG.innerRadius + 15) {
            // In satellite outer zone
            if (dist > CONFIG.wheelRadius - 10) {
              const count = curSec.subSectors.length;
              const fanSpread = Math.min(68, count * 15);
              const fanStart = curSec.angle - fanSpread / 2;
              const fanStep = fanSpread / (count - 1 || 1);

              let bestSubIdx = 0;
              let bestDiff = 999;
              curSec.subSectors.forEach((sub, sIdx) => {
                const subAngle = count === 1 ? curSec.angle : fanStart + sIdx * fanStep;
                let sDiff = Math.abs(deg - subAngle);
                if (sDiff > 180) sDiff = 360 - sDiff;
                if (sDiff < bestDiff) {
                  bestDiff = sDiff;
                  bestSubIdx = sIdx;
                }
              });

              this.highlightSatellite(bestSubIdx);
              return;
            } else {
              // Inside main sector body, retain satellites without flickering
              this.highlightSatellite(-1);
              return;
            }
          }
        }
      }

      // Normal sector detection
      const step = 360 / SECTORS.length;
      let sectorIdx = Math.floor((deg + step / 2) / step) % SECTORS.length;
      this.highlightSector(sectorIdx);
    }

    onPointerUp() {
      if (!this.isOpen) return;
      if (!this.activeKey) {
        const targetX = this.originX;
        const targetY = this.originY;
        this.hide(true, targetX, targetY);
      }
    }

    show(rawX, rawY) {
      if (this.isOpen) return;

      const pad = CONFIG.clampingPadding;
      const cx = Math.max(pad, Math.min(window.innerWidth - pad, rawX));
      const cy = Math.max(pad, Math.min(window.innerHeight - pad, rawY));

      this.originX = cx;
      this.originY = cy;

      this.wheelEl.style.left = `${cx}px`;
      this.wheelEl.style.top = `${cy}px`;

      this.highlightSector(-1);
      this.clearSatellites();

      this.overlayEl.classList.add('is-active');
      this.overlayEl.setAttribute('aria-hidden', 'false');
      this.isOpen = true;
    }

    hide(executeActive = false, targetX, targetY) {
      if (!this.isOpen) return;

      const selectedIdx = this.activeSectorIndex;
      const selectedSubIdx = this.activeSatelliteIndex;

      this.overlayEl.classList.remove('is-active');
      this.overlayEl.setAttribute('aria-hidden', 'true');
      this.isOpen = false;
      this.activeKey = null;

      if (executeActive && selectedIdx >= 0) {
        this.executeSector(selectedIdx, targetX || this.originX, targetY || this.originY, selectedSubIdx);
      }

      this.highlightSector(-1);
      this.clearSatellites();
    }

    highlightSector(index) {
      if (this.activeSectorIndex === index && this.activeSatelliteIndex === -1) return;

      this.activeSectorIndex = index;
      this.activeSatelliteIndex = -1;

      this.sectorPaths.forEach((path, i) => {
        path.classList.toggle('is-selected', i === index);
      });

      this.sectorIcons.forEach((fo, i) => {
        fo.classList.toggle('is-selected', i === index);
      });

      if (index >= 0 && index < SECTORS.length) {
        const sec = SECTORS[index];
        this.hubEl.classList.add('has-selection');
        this.hubIconEl.className = `ph-bold ${sec.icon} boo-wheel-hub-icon`;
        this.hubLabelEl.textContent = sec.title;
        this.hubHintEl.textContent = sec.hint;

        if (sec.subSectors && sec.subSectors.length > 0) {
          this.renderSatellites(sec);
        } else {
          this.clearSatellites();
        }
      } else {
        this.hubEl.classList.remove('has-selection');
        this.hubIconEl.className = 'ph-bold ph-compass boo-wheel-hub-icon';
        this.hubLabelEl.textContent = 'Boo Orbit';
        this.hubHintEl.textContent = 'ОРБИТА';
        this.clearSatellites();
      }
    }

    renderSatellites(sec) {
      this.clearSatellites();

      const subs = sec.subSectors;
      const count = subs.length;
      const fanSpread = Math.min(68, count * 15);
      const fanStart = sec.angle - fanSpread / 2;
      const fanStep = fanSpread / (count - 1 || 1);

      const rInner = CONFIG.wheelRadius + 12;
      const rOuter = rInner + 42;

      subs.forEach((sub, sIdx) => {
        const subAngle = count === 1 ? sec.angle : fanStart + sIdx * fanStep;
        const halfPetal = 6.2;
        const pathData = this.describeArc(0, 0, rInner, rOuter, subAngle - halfPetal, subAngle + halfPetal);

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathData);
        path.setAttribute('class', 'boo-satellite-petal');
        path.dataset.subIndex = String(sIdx);

        this.satellitesGroup.appendChild(path);

        // Icon Position
        const midRad = ((subAngle - 90) * Math.PI) / 180;
        const iconR = (rInner + rOuter) / 2;
        const ix = Math.cos(midRad) * iconR;
        const iy = Math.sin(midRad) * iconR;

        const fo = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
        fo.setAttribute('x', String(ix - 12));
        fo.setAttribute('y', String(iy - 12));
        fo.setAttribute('width', '24');
        fo.setAttribute('height', '24');
        fo.setAttribute('class', 'boo-satellite-icon-group');

        const ic = document.createElement('div');
        ic.style.width = '100%';
        ic.style.height = '100%';
        ic.style.display = 'flex';
        ic.style.alignItems = 'center';
        ic.style.justifyContent = 'center';

        const iEl = document.createElement('i');
        iEl.className = `ph-bold ${sub.icon}`;
        ic.appendChild(iEl);
        fo.appendChild(ic);

        this.satelliteLabelsGroup.appendChild(fo);
        this.currentSatellites.push({ path, fo, sub });
      });

      this.satellitesGroup.classList.add('is-visible');
    }

    highlightSatellite(subIndex) {
      this.activeSatelliteIndex = subIndex;

      this.currentSatellites.forEach((sat, sIdx) => {
        const isSel = sIdx === subIndex;
        sat.path.classList.toggle('is-selected', isSel);
        sat.fo.classList.toggle('is-selected', isSel);
      });

      if (subIndex >= 0 && this.currentSatellites[subIndex]) {
        const sub = this.currentSatellites[subIndex].sub;
        this.hubLabelEl.textContent = sub.title;
        this.hubHintEl.textContent = 'ВЫБРАНО';
      }
    }

    clearSatellites() {
      if (this.satellitesGroup) {
        this.satellitesGroup.classList.remove('is-visible');
        this.satellitesGroup.innerHTML = '';
      }
      if (this.satelliteLabelsGroup) this.satelliteLabelsGroup.innerHTML = '';
      this.currentSatellites = [];
      this.activeSatelliteIndex = -1;
    }

    executeSector(index, x, y, subIndex = -1) {
      if (index < 0 || index >= SECTORS.length) return;
      const sec = SECTORS[index];

      if (subIndex >= 0 && sec.subSectors && sec.subSectors[subIndex]) {
        const sub = sec.subSectors[subIndex];
        try {
          sub.action(x, y);
        } catch (err) {
          console.warn('[BooOrbit] Satellite error:', err);
        }
        return;
      }

      try {
        sec.action(x, y);
      } catch (err) {
        console.warn('[BooOrbit] Sector error:', err);
      }
    }

    showToast(message) {
      if (!this.toastEl) return;
      const textEl = this.toastEl.querySelector('.boo-wheel-toast-text');
      if (textEl) textEl.textContent = message;

      this.toastEl.classList.add('is-visible');
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        this.toastEl.classList.remove('is-visible');
      }, 2200);
    }
  }

  // ==========================================================================
  // Draggable Card Helper with Unified Layering
  // ==========================================================================

  function makeDraggable(card, header, onDragEnd, onDragMove) {
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialLeft = 0;
    let initialTop = 0;
    let lastMoveSentAt = 0;
    const moveCallback = (typeof onDragMove === 'function') ? onDragMove : (typeof onDragEnd === 'function' ? onDragEnd : null);

    card.addEventListener('pointerdown', (e) => {
      if (!e.target.closest('button, input, textarea, select')) {
        bringElementToFront(card);
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
      bringElementToFront(card);
      e.preventDefault();
    });

    header.addEventListener('pointermove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      const parent = card.parentElement || document.body;
      const maxW = (parent.clientWidth || window.innerWidth) - card.offsetWidth - 10;
      const maxH = (parent.clientHeight || window.innerHeight) - card.offsetHeight - 10;
      const curX = Math.max(10, Math.min(maxW, initialLeft + dx));
      const curY = Math.max(10, Math.min(maxH, initialTop + dy));
      card.style.left = `${curX}px`;
      card.style.top = `${curY}px`;

      const now = performance.now();
      if (now - lastMoveSentAt > 35 && moveCallback) {
        lastMoveSentAt = now;
        moveCallback(curX, curY);
      }
    });

    const endDrag = (e) => {
      if (!isDragging) return;
      isDragging = false;
      try { header.releasePointerCapture?.(e.pointerId); } catch (_) {}
      if (typeof onDragEnd === 'function') {
        onDragEnd(parseFloat(card.style.left) || 0, parseFloat(card.style.top) || 0);
      }
    };

    header.addEventListener('pointerup', endDrag);
    header.addEventListener('pointercancel', endDrag);
  }

  // ==========================================================================
  // Tool 1: Focus Timer & Stopwatch (Synchronized)
  // ==========================================================================

  let activeTimerInterval = null;
  let timerRemainingSeconds = 180;
  let timerMode = 'countdown';
  let isTimerRunning = false;

  function spawnTimerWidget(x, y, options = {}) {
    const existing = document.getElementById('boo-orbit-timer-widget');
    const isRemote = Boolean(options.isRemote);

    if (existing && !isRemote) {
      existing.remove();
      if (activeTimerInterval) {
        clearInterval(activeTimerInterval);
        activeTimerInterval = null;
      }
      isTimerRunning = false;
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_timer_sync',
        action: 'close'
      });
      orbitInstance.showToast('Таймер закрыт');
      return;
    }
    if (existing && isRemote) {
      return existing;
    }

    const host = getOrbitWorkspaceHost();
    const coords = getWorkspaceCoordinates(x, y);

    const card = document.createElement('div');
    card.id = 'boo-orbit-timer-widget';
    card.className = 'boo-orbit-card';
    card.style.left = `${Math.max(20, Math.min(coords.maxW - 250, coords.x - 110))}px`;
    card.style.top = `${Math.max(20, Math.min(coords.maxH - 200, coords.y - 80))}px`;

    card.innerHTML = `
      <div class="boo-orbit-card-header">
        <span class="boo-orbit-card-title"><i class="ph-bold ph-timer"></i> Фокус-таймер</span>
        <button type="button" class="boo-orbit-card-close" aria-label="Закрыть"><i class="ph-bold ph-x"></i></button>
      </div>
      <div class="boo-orbit-timer-body">
        <div class="boo-orbit-timer-presets">
          <button type="button" class="boo-orbit-timer-btn" data-sec="60">1м</button>
          <button type="button" class="boo-orbit-timer-btn is-active" data-sec="180">3м</button>
          <button type="button" class="boo-orbit-timer-btn" data-sec="300">5м</button>
          <button type="button" class="boo-orbit-timer-btn" data-sec="600">10м</button>
          <button type="button" class="boo-orbit-timer-btn" data-mode="stopwatch"><i class="ph-bold ph-watch"></i></button>
        </div>
        <div class="boo-orbit-timer-digits" id="boo-timer-display">03:00</div>
        <div class="boo-orbit-timer-actions">
          <button type="button" class="boo-orbit-timer-action-btn boo-orbit-timer-start" id="boo-timer-toggle-btn">
            <i class="ph-bold ph-play"></i> Старт
          </button>
          <button type="button" class="boo-orbit-timer-action-btn boo-orbit-timer-reset" id="boo-timer-reset-btn">
            <i class="ph-bold ph-arrows-clockwise"></i> Сброс
          </button>
        </div>
      </div>
    `;

    host.appendChild(card);
    bringElementToFront(card);

    const sendTimerMove = (curX, curY) => {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_timer_sync',
        action: 'move',
        x: curX,
        y: curY,
        maxW: host.clientWidth || window.innerWidth,
        maxH: host.clientHeight || window.innerHeight
      });
    };
    makeDraggable(card, card.querySelector('.boo-orbit-card-header'), sendTimerMove, sendTimerMove);

    const display = card.querySelector('#boo-timer-display');
    const toggleBtn = card.querySelector('#boo-timer-toggle-btn');
    const resetBtn = card.querySelector('#boo-timer-reset-btn');
    const closeBtn = card.querySelector('.boo-orbit-card-close');

    function formatTime(s) {
      const m = Math.floor(s / 60);
      const sec = s % 60;
      return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    }

    function updateDisplay() {
      if (display) display.textContent = formatTime(timerRemainingSeconds);
    }

    if (options.seconds !== undefined) {
      timerRemainingSeconds = options.seconds;
      if (options.mode) timerMode = options.mode;
      updateDisplay();
    }

    closeBtn.addEventListener('click', () => {
      if (activeTimerInterval) {
        clearInterval(activeTimerInterval);
        activeTimerInterval = null;
      }
      isTimerRunning = false;
      window._booOrbitStartTimerRemote = null;
      window._booOrbitPauseTimerRemote = null;
      window._booOrbitResetTimerRemote = null;
      card.remove();
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_timer_sync',
        action: 'close'
      });
    });

    window._booOrbitStartTimerRemote = (sec) => {
      if (typeof sec === 'number') timerRemainingSeconds = sec;
      updateDisplay();
      startTimer();
    };
    window._booOrbitPauseTimerRemote = (sec) => {
      if (typeof sec === 'number') timerRemainingSeconds = sec;
      updateDisplay();
      pauseTimer();
    };
    window._booOrbitResetTimerRemote = (sec) => {
      pauseTimer();
      toggleBtn.innerHTML = '<i class="ph-bold ph-play"></i> Старт';
      if (typeof sec === 'number') timerRemainingSeconds = sec;
      updateDisplay();
    };

    const startTimer = () => {
      if (activeTimerInterval) clearInterval(activeTimerInterval);
      isTimerRunning = true;
      toggleBtn.innerHTML = '<i class="ph-bold ph-pause"></i> Пауза';
      toggleBtn.classList.add('is-running');
      activeTimerInterval = setInterval(() => {
        if (timerMode === 'countdown') {
          if (timerRemainingSeconds > 0) {
            timerRemainingSeconds -= 1;
            updateDisplay();
          } else {
            clearInterval(activeTimerInterval);
            activeTimerInterval = null;
            isTimerRunning = false;
            toggleBtn.innerHTML = '<i class="ph-bold ph-play"></i> Старт';
            toggleBtn.classList.remove('is-running');
            orbitInstance.showToast('Время вышло!');
          }
        } else {
          timerRemainingSeconds += 1;
          updateDisplay();
        }
      }, 1000);
    };

    const pauseTimer = () => {
      if (activeTimerInterval) {
        clearInterval(activeTimerInterval);
        activeTimerInterval = null;
      }
      isTimerRunning = false;
      toggleBtn.innerHTML = '<i class="ph-bold ph-play"></i> Продолжить';
      toggleBtn.classList.remove('is-running');
    };

    card.querySelectorAll('.boo-orbit-timer-presets button').forEach((btn) => {
      btn.addEventListener('click', () => {
        card.querySelectorAll('.boo-orbit-timer-presets button').forEach(b => b.classList.remove('is-active'));
        btn.classList.add('is-active');

        if (btn.dataset.mode === 'stopwatch') {
          timerMode = 'stopwatch';
          timerRemainingSeconds = 0;
        } else {
          timerMode = 'countdown';
          timerRemainingSeconds = Number(btn.dataset.sec || 180);
        }

        pauseTimer();
        toggleBtn.innerHTML = '<i class="ph-bold ph-play"></i> Старт';
        updateDisplay();

        window.boostudyLessonControl?.sendUi?.({
          kind: 'orbit_timer_sync',
          action: 'reset',
          seconds: timerRemainingSeconds,
          mode: timerMode
        });
      });
    });

    toggleBtn.addEventListener('click', () => {
      if (isTimerRunning) {
        pauseTimer();
        window.boostudyLessonControl?.sendUi?.({
          kind: 'orbit_timer_sync',
          action: 'pause',
          seconds: timerRemainingSeconds,
          mode: timerMode
        });
      } else {
        startTimer();
        window.boostudyLessonControl?.sendUi?.({
          kind: 'orbit_timer_sync',
          action: 'start',
          seconds: timerRemainingSeconds,
          mode: timerMode
        });
      }
    });

    resetBtn.addEventListener('click', () => {
      pauseTimer();
      toggleBtn.innerHTML = '<i class="ph-bold ph-play"></i> Старт';
      const activeBtn = card.querySelector('.boo-orbit-timer-presets .is-active');
      timerRemainingSeconds = activeBtn?.dataset?.sec ? Number(activeBtn.dataset.sec) : 0;
      updateDisplay();

      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_timer_sync',
        action: 'reset',
        seconds: timerRemainingSeconds,
        mode: timerMode
      });
    });

    if (options.isRunning) {
      startTimer();
    }

    if (!isRemote) {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_timer_sync',
        action: 'open',
        x: parseFloat(card.style.left) || coords.x,
        y: parseFloat(card.style.top) || coords.y,
        maxW: coords.maxW,
        maxH: coords.maxH,
        seconds: timerRemainingSeconds,
        isRunning: isTimerRunning,
        mode: timerMode
      });
      orbitInstance.showToast('Фокус-таймер открыт');
    }

    return card;
  }

  // ==========================================================================
  // Tool 2: Full Functional Mini-Calculator
  // ==========================================================================

  function spawnCalcWidget(x, y, options = {}) {
    const existing = document.getElementById('boo-orbit-calc-widget');
    const isRemote = Boolean(options.isRemote);

    if (existing && !isRemote) {
      existing.remove();
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_calc_sync',
        action: 'close'
      });
      orbitInstance.showToast('Калькулятор закрыт');
      return;
    }
    if (existing && isRemote) {
      return existing;
    }

    const host = getOrbitWorkspaceHost();
    const coords = getWorkspaceCoordinates(x, y);

    const card = document.createElement('div');
    card.id = 'boo-orbit-calc-widget';
    card.className = 'boo-orbit-card boo-orbit-calc-card';
    card.style.left = `${Math.max(20, Math.min(coords.maxW - 300, coords.x - 140))}px`;
    card.style.top = `${Math.max(20, Math.min(coords.maxH - 360, coords.y - 100))}px`;

    card.innerHTML = `
      <div class="boo-orbit-card-header">
        <span class="boo-orbit-card-title"><i class="ph-bold ph-calculator"></i> Мини-калькулятор</span>
        <button type="button" class="boo-orbit-card-close" aria-label="Закрыть"><i class="ph-bold ph-x"></i></button>
      </div>
      <div class="boo-orbit-calc-body">
        <div class="boo-orbit-calc-screen">
          <div class="boo-orbit-calc-expr" id="calc-screen-expr"></div>
          <div class="boo-orbit-calc-result" id="calc-screen-val">0</div>
        </div>
        <div class="boo-orbit-calc-grid">
          <button type="button" class="boo-calc-key boo-calc-del" data-val="C">C</button>
          <button type="button" class="boo-calc-key boo-calc-del" data-val="DEL">⌫</button>
          <button type="button" class="boo-calc-key boo-calc-op" data-val="(">(</button>
          <button type="button" class="boo-calc-key boo-calc-op" data-val=")">)</button>

          <button type="button" class="boo-calc-key" data-val="7">7</button>
          <button type="button" class="boo-calc-key" data-val="8">8</button>
          <button type="button" class="boo-calc-key" data-val="9">9</button>
          <button type="button" class="boo-calc-key boo-calc-op" data-val="/">÷</button>

          <button type="button" class="boo-calc-key" data-val="4">4</button>
          <button type="button" class="boo-calc-key" data-val="5">5</button>
          <button type="button" class="boo-calc-key" data-val="6">6</button>
          <button type="button" class="boo-calc-key boo-calc-op" data-val="*">×</button>

          <button type="button" class="boo-calc-key" data-val="1">1</button>
          <button type="button" class="boo-calc-key" data-val="2">2</button>
          <button type="button" class="boo-calc-key" data-val="3">3</button>
          <button type="button" class="boo-calc-key boo-calc-op" data-val="-">−</button>

          <button type="button" class="boo-calc-key" data-val="0">0</button>
          <button type="button" class="boo-calc-key" data-val=".">.</button>
          <button type="button" class="boo-calc-key boo-calc-op" data-val="^">^</button>
          <button type="button" class="boo-calc-key boo-calc-op" data-val="+">+</button>

          <button type="button" class="boo-calc-key boo-calc-op" data-val="%">%</button>
          <button type="button" class="boo-calc-key boo-calc-eq" data-val="=">=</button>
        </div>
        <div class="boo-orbit-calc-bases">
          <div class="boo-calc-base-row" title="Кликните, чтобы скопировать BIN" id="calc-copy-bin">
            <span class="boo-calc-base-tag">BIN:</span>
            <span class="boo-calc-base-val" id="calc-val-bin">—</span>
          </div>
          <div class="boo-calc-base-row" title="Кликните, чтобы скопировать HEX" id="calc-copy-hex">
            <span class="boo-calc-base-tag">HEX:</span>
            <span class="boo-calc-base-val" id="calc-val-hex">—</span>
          </div>
          <div class="boo-calc-base-row" title="Ближайшая степень двойки" id="calc-copy-pow">
            <span class="boo-calc-base-tag">2^N:</span>
            <span class="boo-calc-base-val" id="calc-val-pow">—</span>
          </div>
        </div>
      </div>
    `;

    host.appendChild(card);
    bringElementToFront(card);

    const sendCalcMove = (curX, curY) => {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_calc_sync',
        action: 'move',
        x: curX,
        y: curY,
        maxW: host.clientWidth || window.innerWidth,
        maxH: host.clientHeight || window.innerHeight
      });
    };
    makeDraggable(card, card.querySelector('.boo-orbit-card-header'), sendCalcMove, sendCalcMove);

    const exprEl = card.querySelector('#calc-screen-expr');
    const valEl = card.querySelector('#calc-screen-val');
    const binEl = card.querySelector('#calc-val-bin');
    const hexEl = card.querySelector('#calc-val-hex');
    const powEl = card.querySelector('#calc-val-pow');
    const closeBtn = card.querySelector('.boo-orbit-card-close');

    closeBtn.addEventListener('click', () => {
      card.remove();
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_calc_sync',
        action: 'close'
      });
    });

    let currentExpr = options.expr || '';
    if (options.val && valEl) valEl.textContent = options.val;
    if (currentExpr && exprEl) exprEl.textContent = currentExpr;

    function broadcastCalcUpdate() {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_calc_sync',
        action: 'update',
        expr: currentExpr,
        val: valEl.textContent
      });
    }

    function evaluateExpression() {
      if (!currentExpr) {
        valEl.textContent = '0';
        binEl.textContent = '—';
        hexEl.textContent = '—';
        powEl.textContent = '—';
        return;
      }

      try {
        const sanitized = currentExpr.replace(/\^/g, '**');
        const res = Function(`"use strict"; return (${sanitized});`)();
        if (typeof res === 'number' && !isNaN(res)) {
          valEl.textContent = Number.isInteger(res) ? res.toLocaleString('ru-RU') : res.toFixed(4);

          if (Number.isInteger(res) && res >= 0 && res < 1e12) {
            binEl.textContent = res.toString(2);
            hexEl.textContent = '0x' + res.toString(16).toUpperCase();

            const log2 = Math.log2(res);
            if (Number.isInteger(log2)) {
              powEl.textContent = `2^${log2} (точно)`;
            } else if (res > 0) {
              powEl.textContent = `≈ 2^${log2.toFixed(2)}`;
            } else {
              powEl.textContent = '—';
            }
          } else {
            binEl.textContent = '—';
            hexEl.textContent = '—';
            powEl.textContent = '—';
          }
        } else {
          valEl.textContent = 'Ошибка';
        }
      } catch (_) {
        valEl.textContent = '...';
      }
    }

    function appendKey(k) {
      if (k === 'C') {
        currentExpr = '';
      } else if (k === 'DEL') {
        currentExpr = currentExpr.slice(0, -1);
      } else if (k === '=') {
        evaluateExpression();
        broadcastCalcUpdate();
        return;
      } else {
        currentExpr += k;
      }
      exprEl.textContent = currentExpr;
      evaluateExpression();
      broadcastCalcUpdate();
    }

    card.querySelectorAll('.boo-calc-key').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        appendKey(btn.dataset.val);
      });
    });

    card.querySelector('#calc-copy-bin')?.addEventListener('click', () => {
      if (binEl.textContent !== '—') {
        navigator.clipboard?.writeText(binEl.textContent);
        orbitInstance.showToast('Двоичное скопировано');
      }
    });

    card.querySelector('#calc-copy-hex')?.addEventListener('click', () => {
      if (hexEl.textContent !== '—') {
        navigator.clipboard?.writeText(hexEl.textContent);
        orbitInstance.showToast('HEX скопирован');
      }
    });

    const onKey = (e) => {
      if (!document.body.contains(card)) {
        window.removeEventListener('keydown', onKey);
        return;
      }
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if (/^[0-9.+\-*/%^()]$/.test(e.key)) {
        appendKey(e.key);
        e.preventDefault();
      } else if (e.key === 'Backspace') {
        appendKey('DEL');
        e.preventDefault();
      } else if (e.key === 'Enter' || e.key === '=') {
        appendKey('=');
        e.preventDefault();
      } else if (e.key === 'Escape') {
        appendKey('C');
      }
    };
    window.addEventListener('keydown', onKey);

    if (!isRemote) {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_calc_sync',
        action: 'open',
        x: parseFloat(card.style.left) || coords.x,
        y: parseFloat(card.style.top) || coords.y,
        maxW: coords.maxW,
        maxH: coords.maxH,
        expr: currentExpr,
        val: valEl.textContent
      });
      orbitInstance.showToast('Мини-калькулятор открыт');
    }

    return card;
  }

  // ==========================================================================
  // Tool 3: Pulse Beacon
  // ==========================================================================

  function triggerPulseBeacon(x, y, options = {}) {
    const px = (typeof x === 'number' && x > 0) ? x : (orbitInstance?.cursorX || window.innerWidth / 2);
    const py = (typeof y === 'number' && y > 0) ? y : (orbitInstance?.cursorY || window.innerHeight / 2);
    const author = options.author || (window.boostudyOS?.viewerName || document.getElementById('trainer-os-config')?.dataset?.viewerName || 'Участник');

    const anchor = document.createElement('div');
    anchor.className = 'boo-orbit-beacon-anchor';
    anchor.style.left = `${px}px`;
    anchor.style.top = `${py}px`;

    const core = document.createElement('div');
    core.className = 'boo-orbit-beacon-core';

    const circle1 = document.createElement('div');
    circle1.className = 'boo-orbit-beacon-circle';
    circle1.style.width = '64px';
    circle1.style.height = '64px';
    circle1.style.animationDelay = '0s';

    const circle2 = document.createElement('div');
    circle2.className = 'boo-orbit-beacon-circle';
    circle2.style.width = '104px';
    circle2.style.height = '104px';
    circle2.style.animationDelay = '0.35s';

    const circle3 = document.createElement('div');
    circle3.className = 'boo-orbit-beacon-circle';
    circle3.style.width = '148px';
    circle3.style.height = '148px';
    circle3.style.animationDelay = '0.7s';

    const tag = document.createElement('div');
    tag.className = 'boo-orbit-beacon-tag';
    tag.innerHTML = `<i class="ph-bold ph-broadcast"></i> ${escapeHtml(author)}`;

    anchor.appendChild(core);
    anchor.appendChild(circle1);
    anchor.appendChild(circle2);
    anchor.appendChild(circle3);
    anchor.appendChild(tag);
    document.body.appendChild(anchor);

    setTimeout(() => anchor.remove(), 2800);

    if (!options.isRemote) {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_beacon',
        x: px,
        y: py,
        maxW: window.innerWidth,
        maxH: window.innerHeight,
        author: author
      });
      orbitInstance.showToast('Маячок внимания установлен');
    } else {
      orbitInstance.showToast(`Маячок от ${author}`);
    }
  }

  // ==========================================================================
  // Tool 4: Sticky Note Widget (with Color Sub-Options)
  // ==========================================================================

  function spawnStickyNote(x, y, colorVariant = 'yellow', options = {}) {
    const canvasViewport = document.getElementById('whiteboard-canvas-viewport') || document.querySelector('.boo-canvas-overlay');
    if (canvasViewport && window.BooCanvasOverlay && typeof window.BooCanvasOverlay.insertNote === 'function') {
      const noteObj = window.BooCanvasOverlay.insertNote(colorVariant, x, y, options.text || '');
      if (noteObj) {
        orbitInstance.showToast('Стикер добавлен на доску');
        return noteObj;
      }
    }

    const host = getOrbitWorkspaceHost();
    const coords = getWorkspaceCoordinates(x, y);
    const noteId = options.id || ('sticky_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5));
    const isRemote = Boolean(options.isRemote);
    const author = options.author || (window.boostudyOS?.viewerName || document.getElementById('trainer-os-config')?.dataset?.viewerName || 'Участник');

    const card = document.createElement('div');
    card.className = `boo-orbit-sticky-card boo-sticky-${colorVariant}`;
    card.dataset.noteId = noteId;
    card.style.left = `${Math.max(20, Math.min(coords.maxW - 250, coords.x - 110))}px`;
    card.style.top = `${Math.max(20, Math.min(coords.maxH - 160, coords.y - 60))}px`;

    card.innerHTML = `
      <div class="boo-orbit-sticky-header">
        <span class="boo-orbit-sticky-tag"><i class="ph-bold ph-push-pin"></i> <span class="boo-sticky-author">${escapeHtml(author)}</span></span>
        <button type="button" class="boo-orbit-card-close" aria-label="Удалить"><i class="ph-bold ph-x"></i></button>
      </div>
      <textarea class="boo-orbit-sticky-content" placeholder="Запишите мысль или промежуточный ответ...">${escapeHtml(options.text || '')}</textarea>
    `;

    host.appendChild(card);
    bringElementToFront(card);

    const sendMove = (curX, curY) => {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_sticky_move',
        id: noteId,
        x: curX,
        y: curY,
        maxW: host.clientWidth || window.innerWidth,
        maxH: host.clientHeight || window.innerHeight
      });
    };

    makeDraggable(card, card.querySelector('.boo-orbit-sticky-header'), sendMove, sendMove);

    const textarea = card.querySelector('textarea');
    const closeBtn = card.querySelector('.boo-orbit-card-close');

    closeBtn.addEventListener('click', () => {
      card.remove();
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_sticky_remove',
        id: noteId
      });
    });

    let inputDebounce = null;
    textarea.addEventListener('input', () => {
      clearTimeout(inputDebounce);
      inputDebounce = setTimeout(() => {
        window.boostudyLessonControl?.sendUi?.({
          kind: 'orbit_sticky_input',
          id: noteId,
          text: textarea.value
        });
      }, 60);
    });

    if (!isRemote) {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_sticky',
        id: noteId,
        color: colorVariant,
        text: textarea.value,
        x: coords.x,
        y: coords.y,
        maxW: coords.maxW,
        maxH: coords.maxH,
        author: author
      });
      setTimeout(() => textarea.focus(), 60);
      orbitInstance.showToast('Стикер создан');
    }
    return card;
  }

  // ==========================================================================
  // Tool 5: Quick Cheat Sheet (Таблица степеней 2 и памяти)
  // ==========================================================================

  function spawnCheatSheet(x, y, options = {}) {
    const existing = document.getElementById('boo-orbit-cheat-widget');
    const isRemote = Boolean(options.isRemote);

    if (existing && !isRemote) {
      existing.remove();
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_cheat_sync',
        action: 'close'
      });
      orbitInstance.showToast('Шпаргалка закрыта');
      return;
    }
    if (existing && isRemote) {
      return existing;
    }

    const host = getOrbitWorkspaceHost();
    const coords = getWorkspaceCoordinates(x, y);

    const card = document.createElement('div');
    card.id = 'boo-orbit-cheat-widget';
    card.className = 'boo-orbit-card boo-orbit-cheat-card';
    card.style.left = `${Math.max(20, Math.min(coords.maxW - 320, coords.x - 150))}px`;
    card.style.top = `${Math.max(20, Math.min(coords.maxH - 400, coords.y - 100))}px`;

    const powers = [];
    for (let i = 0; i <= 30; i++) {
      powers.push(`<tr><td>2^${i}</td><td>${(2 ** i).toLocaleString('ru-RU')}</td></tr>`);
    }

    card.innerHTML = `
      <div class="boo-orbit-card-header">
        <span class="boo-orbit-card-title"><i class="ph-bold ph-book-bookmark"></i> Инфо-шпаргалка</span>
        <button type="button" class="boo-orbit-card-close" aria-label="Закрыть"><i class="ph-bold ph-x"></i></button>
      </div>
      <div class="boo-orbit-cheat-tabs">
        <button type="button" class="boo-cheat-tab-btn is-active" data-tab="powers">Степени 2</button>
        <button type="button" class="boo-cheat-tab-btn" data-tab="memory">Память</button>
        <button type="button" class="boo-cheat-tab-btn" data-tab="constants">Константы</button>
      </div>
      <div class="boo-orbit-cheat-body">
        <div id="cheat-tab-powers">
          <table class="boo-cheat-table">
            <thead><tr><th>Степень</th><th>Значение</th></tr></thead>
            <tbody>${powers.join('')}</tbody>
          </table>
        </div>
        <div id="cheat-tab-memory" style="display: none;">
          <table class="boo-cheat-table">
            <thead><tr><th>Единица</th><th>Байты</th><th>Биты</th></tr></thead>
            <tbody>
              <tr><td>1 Байт</td><td>1</td><td>8 бит</td></tr>
              <tr><td>1 Кбайт</td><td>1 024</td><td>2^13 бит</td></tr>
              <tr><td>1 Мбайт</td><td>1 048 576</td><td>2^23 бит</td></tr>
              <tr><td>1 Гбайт</td><td>1 073 741 824</td><td>2^33 бит</td></tr>
            </tbody>
          </table>
        </div>
        <div id="cheat-tab-constants" style="display: none;">
          <table class="boo-cheat-table">
            <thead><tr><th>Константа</th><th>Значение</th></tr></thead>
            <tbody>
              <tr><td>2^16</td><td>65 536</td></tr>
              <tr><td>2^20</td><td>1 048 576</td></tr>
              <tr><td>2^24</td><td>16 777 216</td></tr>
              <tr><td>ASCII '0'</td><td>48</td></tr>
              <tr><td>ASCII 'A'</td><td>65</td></tr>
              <tr><td>ASCII 'a'</td><td>97</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;

    host.appendChild(card);
    bringElementToFront(card);

    const sendCheatMove = (curX, curY) => {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_cheat_sync',
        action: 'move',
        x: curX,
        y: curY,
        maxW: host.clientWidth || window.innerWidth,
        maxH: host.clientHeight || window.innerHeight
      });
    };
    makeDraggable(card, card.querySelector('.boo-orbit-card-header'), sendCheatMove, sendCheatMove);

    const closeBtn = card.querySelector('.boo-orbit-card-close');
    closeBtn.addEventListener('click', () => {
      card.remove();
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_cheat_sync',
        action: 'close'
      });
    });

    const tabPowers = card.querySelector('#cheat-tab-powers');
    const tabMemory = card.querySelector('#cheat-tab-memory');
    const tabConst = card.querySelector('#cheat-tab-constants');

    card.querySelectorAll('.boo-cheat-tab-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        card.querySelectorAll('.boo-cheat-tab-btn').forEach(b => b.classList.remove('is-active'));
        btn.classList.add('is-active');

        const tab = btn.dataset.tab;
        tabPowers.style.display = tab === 'powers' ? '' : 'none';
        tabMemory.style.display = tab === 'memory' ? '' : 'none';
        tabConst.style.display = tab === 'constants' ? '' : 'none';

        window.boostudyLessonControl?.sendUi?.({
          kind: 'orbit_cheat_sync',
          action: 'tab',
          tab: tab
        });
      });
    });

    if (!isRemote) {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_cheat_sync',
        action: 'open',
        x: parseFloat(card.style.left) || coords.x,
        y: parseFloat(card.style.top) || coords.y,
        maxW: coords.maxW,
        maxH: coords.maxH,
        tab: 'powers'
      });
      orbitInstance.showToast('Инфо-шпаргалка открыта');
    }
    return card;
  }

  // ==========================================================================
  // Tool 6: Laser Tracer (Динамический неоновый след)
  // ==========================================================================

  let isLaserTracerActive = false;
  let laserCanvas = null;
  let laserCtx = null;
  let laserPoints = [];
  let laserAnimId = null;
  let laserBatch = [];
  let laserEmitTimer = null;

  // Remote laser state
  let remoteLaserCanvas = null;
  let remoteLaserCtx = null;
  let remoteLaserPoints = [];
  let remoteLaserAnimId = null;

  function ensureRemoteLaserCanvas() {
    if (remoteLaserCanvas && document.body.contains(remoteLaserCanvas)) return;
    remoteLaserCanvas = document.createElement('canvas');
    remoteLaserCanvas.className = 'boo-orbit-laser-canvas boo-orbit-remote-laser';
    remoteLaserCanvas.width = window.innerWidth;
    remoteLaserCanvas.height = window.innerHeight;
    remoteLaserCtx = remoteLaserCanvas.getContext('2d');
    document.body.appendChild(remoteLaserCanvas);
  }

  function renderRemoteLaserLoop() {
    if (!remoteLaserCanvas || !remoteLaserCtx) return;
    remoteLaserCtx.clearRect(0, 0, remoteLaserCanvas.width, remoteLaserCanvas.height);
    for (let i = 0; i < remoteLaserPoints.length; i++) {
      const pt = remoteLaserPoints[i];
      pt.alpha -= 0.025;
      if (pt.alpha <= 0) {
        remoteLaserPoints.splice(i, 1);
        i--;
        continue;
      }
      remoteLaserCtx.beginPath();
      remoteLaserCtx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
      const color = pt.color || '#38bdf8';
      remoteLaserCtx.fillStyle = color;
      remoteLaserCtx.shadowColor = color;
      remoteLaserCtx.shadowBlur = 12;
      remoteLaserCtx.globalAlpha = Math.max(0, pt.alpha);
      remoteLaserCtx.fill();
      remoteLaserCtx.globalAlpha = 1.0;
    }
    if (remoteLaserPoints.length > 0) {
      remoteLaserAnimId = requestAnimationFrame(renderRemoteLaserLoop);
    } else {
      cancelAnimationFrame(remoteLaserAnimId);
      remoteLaserAnimId = null;
      if (remoteLaserCanvas) {
        remoteLaserCanvas.remove();
        remoteLaserCanvas = null;
        remoteLaserCtx = null;
      }
    }
  }

  function renderRemoteLaserPayload(payload) {
    if (payload.kind === 'orbit_laser_stop') {
      remoteLaserPoints = [];
      if (remoteLaserCanvas) {
        remoteLaserCanvas.remove();
        remoteLaserCanvas = null;
        remoteLaserCtx = null;
      }
      return;
    }
    if (!payload.points || !payload.points.length) return;
    ensureRemoteLaserCanvas();
    const w = window.innerWidth;
    const h = window.innerHeight;
    const col = payload.color || '#38bdf8';
    payload.points.forEach((pt) => {
      remoteLaserPoints.push({
        x: pt.x * w,
        y: pt.y * h,
        alpha: 1.0,
        color: col
      });
    });
    if (!remoteLaserAnimId) {
      remoteLaserAnimId = requestAnimationFrame(renderRemoteLaserLoop);
    }
  }

  function toggleLaserTracer() {
    const canvasViewport = document.getElementById('whiteboard-canvas-viewport') || document.querySelector('.boo-canvas-overlay');
    if (canvasViewport && window.BooCanvasOverlay && typeof window.BooCanvasOverlay.setTool === 'function') {
      const curTool = window.BooCanvasOverlay.getTool?.();
      if (curTool === 'laser') {
        window.BooCanvasOverlay.setTool('pen');
        orbitInstance.showToast('Лазер выключен (перо)');
      } else {
        window.BooCanvasOverlay.setTool('laser');
        orbitInstance.showToast('Лазерная указка на доске активна');
      }
      return;
    }

    if (isLaserTracerActive) {
      isLaserTracerActive = false;
      if (laserEmitTimer) {
        clearTimeout(laserEmitTimer);
        laserEmitTimer = null;
      }
      if (laserCanvas) {
        laserCanvas.remove();
        laserCanvas = null;
      }
      cancelAnimationFrame(laserAnimId);
      window.boostudyLessonControl?.sendUi?.({ kind: 'orbit_laser_stop' });
      orbitInstance.showToast('Лазерный след выключен');
      return;
    }

    isLaserTracerActive = true;
    laserCanvas = document.createElement('canvas');
    laserCanvas.className = 'boo-orbit-laser-canvas';
    laserCanvas.width = window.innerWidth;
    laserCanvas.height = window.innerHeight;
    laserCtx = laserCanvas.getContext('2d');
    document.body.appendChild(laserCanvas);

    laserPoints = [];
    laserBatch = [];

    const isTeacher = Boolean(document.getElementById('boo-teacher-orbit-root') || window.boostudyOS?.isTeacher);
    const laserColor = isTeacher ? '#f59e0b' : '#ef4444';

    const onPointer = (e) => {
      if (!isLaserTracerActive) return;
      laserPoints.push({ x: e.clientX, y: e.clientY, alpha: 1 });
      laserBatch.push({ x: e.clientX / window.innerWidth, y: e.clientY / window.innerHeight });

      if (!laserEmitTimer) {
        laserEmitTimer = setTimeout(() => {
          if (laserBatch.length > 0) {
            window.boostudyLessonControl?.sendUi?.({
              kind: 'orbit_laser',
              points: laserBatch,
              color: laserColor
            });
            laserBatch = [];
          }
          laserEmitTimer = null;
        }, 45);
      }
    };

    window.addEventListener('pointermove', onPointer, { passive: true });

    function renderLaser() {
      if (!isLaserTracerActive) return;
      laserCtx.clearRect(0, 0, laserCanvas.width, laserCanvas.height);

      for (let i = 0; i < laserPoints.length; i++) {
        const pt = laserPoints[i];
        pt.alpha -= 0.025;
        if (pt.alpha <= 0) {
          laserPoints.splice(i, 1);
          i--;
          continue;
        }

        laserCtx.beginPath();
        laserCtx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
        laserCtx.fillStyle = laserColor === '#f59e0b' ? `rgba(245, 158, 11, ${pt.alpha})` : `rgba(239, 68, 68, ${pt.alpha})`;
        laserCtx.shadowColor = laserColor;
        laserCtx.shadowBlur = 12;
        laserCtx.fill();
      }

      laserAnimId = requestAnimationFrame(renderLaser);
    }
    renderLaser();

    orbitInstance.showToast('Лазерный след включён (повтор в меню для выкл)');
  }

  // ==========================================================================
  // Tool 7: Genuine 2x Optical Loupe (Canvases, Images & Text Inspector)
  // ==========================================================================

  function toggleCanvasLoupe(x, y) {
    if (window._activeLoupe) {
      window._activeLoupe.remove();
      window._activeLoupe = null;
      orbitInstance.showToast('Лупа выключена');
      return;
    }

    const loupe = document.createElement('div');
    loupe.className = 'boo-orbit-canvas-loupe';
    loupe.style.left = `${x}px`;
    loupe.style.top = `${y}px`;

    const canvas = document.createElement('canvas');
    canvas.className = 'boo-orbit-loupe-canvas';
    canvas.width = 180;
    canvas.height = 180;
    const ctx = canvas.getContext('2d');

    const domViewport = document.createElement('div');
    domViewport.className = 'boo-orbit-loupe-dom-viewport';

    const domContent = document.createElement('div');
    domContent.className = 'boo-orbit-loupe-dom-content';

    const domStage = document.createElement('div');
    domStage.className = 'room-lesson-os font-mono boo-orbit-loupe-stage';
    domContent.appendChild(domStage);
    domViewport.appendChild(domContent);

    const crosshair = document.createElement('div');
    crosshair.className = 'boo-orbit-canvas-loupe-cross';

    const badge = document.createElement('div');
    badge.className = 'boo-orbit-loupe-badge';
    badge.textContent = '2× ZOOM';

    loupe.appendChild(canvas);
    loupe.appendChild(domViewport);
    loupe.appendChild(crosshair);
    loupe.appendChild(badge);
    document.body.appendChild(loupe);
    window._activeLoupe = loupe;

    let currentClonedTarget = null;

    function renderLoupeAt(clientX, clientY) {
      loupe.style.left = `${clientX}px`;
      loupe.style.top = `${clientY}px`;

      // 1. Identify topmost element under pointer (ignoring loupe, overlays, triggers, laser)
      const elements = (document.elementsFromPoint(clientX, clientY) || []).filter(el =>
        !el.closest('.boo-orbit-canvas-loupe, .boo-radial-wheel-overlay, .boo-wheel-trigger-orb, .boo-orbit-laser-canvas')
      );
      const topEl = elements[0] || null;

      // 2. Check if cursor is over an OS window, Orbit card, sticky note, stamp, or dock
      const targetWindowOrCard = topEl
        ? topEl.closest('.glass-os-window, .boo-orbit-card, .boo-orbit-sticky-card, .boo-orbit-stamp-item, #board-dock')
        : null;

      // #canvas-window is the background whiteboard desktop; all other windows are interactive OS windows
      const isActualUI = targetWindowOrCard && targetWindowOrCard.id !== 'canvas-window';

      if (isActualUI) {
        // --- MODE A: MAGNIFY OS WINDOW / ORBIT CARD / DOCK ---
        canvas.style.display = 'none';
        domViewport.style.display = 'block';

        if (currentClonedTarget !== targetWindowOrCard) {
          domStage.innerHTML = '';
          const clone = targetWindowOrCard.cloneNode(true);

          // Strip floating menus/popovers by setting display:none !important (avoids node removal to maintain 1:1 DOM index parity)
          clone.querySelectorAll(
            '.hidden, [style*="display: none"], .lesson-os-window-menu, .boo-ai-popover, #booai-popover, .window-resize-handle, .window-edge-resizer'
          ).forEach(el => el.style.setProperty('display', 'none', 'important'));

          // Strip positional utility classes from clone so they cannot induce coordinate offsets
          clone.classList.remove(
            'absolute', 'fixed', 'relative',
            'top-8', 'top-12', 'top-14', 'top-16', 'top-20', 'top-24',
            'left-16', 'left-24', 'left-1/4', 'left-1/3', 'left-1/2', 'left-[42%]', 'left-[610px]',
            'right-8', 'bottom-24', 'bottom-4',
            '-translate-x-1/2', '-translate-y-1/2'
          );

          // 1:1 synchronization of scroll positions and input values without index shift
          if (targetWindowOrCard.scrollTop > 0) clone.scrollTop = targetWindowOrCard.scrollTop;
          if (targetWindowOrCard.scrollLeft > 0) clone.scrollLeft = targetWindowOrCard.scrollLeft;
          const origAll = targetWindowOrCard.querySelectorAll('*');
          const cloneAll = clone.querySelectorAll('*');
          origAll.forEach((origEl, idx) => {
            const cloneEl = cloneAll[idx];
            if (!cloneEl) return;
            if (origEl.scrollTop > 0) cloneEl.scrollTop = origEl.scrollTop;
            if (origEl.scrollLeft > 0) cloneEl.scrollLeft = origEl.scrollLeft;
            if (origEl.tagName === 'TEXTAREA' || origEl.tagName === 'INPUT') {
              cloneEl.value = origEl.value;
            }
          });

          // Replicate internal canvas bitmaps (plots, diagrams)
          const origCanvases = targetWindowOrCard.querySelectorAll('canvas');
          const cloneCanvases = clone.querySelectorAll('canvas');
          origCanvases.forEach((origCv, idx) => {
            const cloneCv = cloneCanvases[idx];
            if (cloneCv && origCv.width > 0 && origCv.height > 0) {
              cloneCv.width = origCv.width;
              cloneCv.height = origCv.height;
              const cctx = cloneCv.getContext('2d');
              if (cctx) cctx.drawImage(origCv, 0, 0);
            }
          });

          const rect = targetWindowOrCard.getBoundingClientRect();
          // Anchor clone rigidly at (0, 0) of domStage with !important to defeat any CSS rules
          clone.style.setProperty('position', 'absolute', 'important');
          clone.style.setProperty('left', '0px', 'important');
          clone.style.setProperty('top', '0px', 'important');
          clone.style.setProperty('right', 'auto', 'important');
          clone.style.setProperty('bottom', 'auto', 'important');
          clone.style.setProperty('inset', '0px auto auto 0px', 'important');
          clone.style.setProperty('margin', '0px', 'important');
          clone.style.setProperty('transform', 'none', 'important');
          clone.style.setProperty('transition', 'none', 'important');
          clone.style.animation = 'none';
          clone.style.setProperty('box-shadow', 'none', 'important');
          clone.style.setProperty('width', `${rect.width}px`, 'important');
          clone.style.setProperty('height', `${rect.height}px`, 'important');
          clone.style.setProperty('min-width', `${rect.width}px`, 'important');
          clone.style.setProperty('min-height', `${rect.height}px`, 'important');
          clone.style.setProperty('max-width', `${rect.width}px`, 'important');
          clone.style.setProperty('max-height', `${rect.height}px`, 'important');

          domStage.appendChild(clone);
          currentClonedTarget = targetWindowOrCard;
        }

        // Align coordinates: cursor point (clientX, clientY) centered at (90, 90) with 2x zoom via GPU translate3d
        const rect = targetWindowOrCard.getBoundingClientRect();
        const relX = clientX - rect.left;
        const relY = clientY - rect.top;
        const tx = 90 - relX * 2;
        const ty = 90 - relY * 2;
        domContent.style.setProperty('transform', `translate3d(${tx}px, ${ty}px, 0) scale(2)`, 'important');

      } else {
        // --- MODE B: MAGNIFY CANVAS DRAWINGS, IMAGES & BACKGROUND ---
        domViewport.style.display = 'none';
        canvas.style.display = 'block';
        currentClonedTarget = null;

        ctx.fillStyle = '#f8faff';
        ctx.fillRect(0, 0, 180, 180);

        // 1. Precise Pixel Sampling of Drawing Canvases (Whiteboard, Laser, Overlay)
        const allCanvases = Array.from(document.querySelectorAll('canvas')).filter(c => c !== canvas);
        for (const cv of allCanvases) {
          if (!cv.offsetParent && cv.style.display === 'none') continue;
          const rect = cv.getBoundingClientRect();
          if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) {
            if (rect.width > 0 && rect.height > 0 && cv.width > 0 && cv.height > 0) {
              const scaleX = cv.width / rect.width;
              const scaleY = cv.height / rect.height;
              const cssX = clientX - rect.left;
              const cssY = clientY - rect.top;
              const sW = 90 * scaleX;
              const sH = 90 * scaleY;
              const sX = (cssX - 45) * scaleX;
              const sY = (cssY - 45) * scaleY;
              try {
                ctx.drawImage(cv, sX, sY, sW, sH, 0, 0, 180, 180);
              } catch (_) {}
            }
          }
        }

        // 2. Precise Pixel Sampling of Images (Task diagrams, figures)
        const allImages = Array.from(document.querySelectorAll('img'));
        for (const img of allImages) {
          if (!img.offsetParent && img.style.display === 'none') continue;
          const rect = img.getBoundingClientRect();
          if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) {
            if (img.naturalWidth > 0 && img.naturalHeight > 0) {
              const scaleX = img.naturalWidth / rect.width;
              const scaleY = img.naturalHeight / rect.height;
              const cssX = clientX - rect.left;
              const cssY = clientY - rect.top;
              const sW = 90 * scaleX;
              const sH = 90 * scaleY;
              const sX = (cssX - 45) * scaleX;
              const sY = (cssY - 45) * scaleY;
              try {
                ctx.drawImage(img, sX, sY, sW, sH, 0, 0, 180, 180);
              } catch (_) {}
            }
          }
        }
      }
    }

    renderLoupeAt(x, y);

    const onMove = (e) => {
      if (!window._activeLoupe) {
        cleanup();
        return;
      }
      renderLoupeAt(e.clientX, e.clientY);
    };

    const onWheel = () => {
      if (currentClonedTarget && domStage.firstElementChild) {
        const clone = domStage.firstElementChild;
        if (currentClonedTarget.scrollTop > 0) clone.scrollTop = currentClonedTarget.scrollTop;
        if (currentClonedTarget.scrollLeft > 0) clone.scrollLeft = currentClonedTarget.scrollLeft;
        const origAll = currentClonedTarget.querySelectorAll('*');
        const cloneAll = clone.querySelectorAll('*');
        origAll.forEach((origEl, idx) => {
          const cloneEl = cloneAll[idx];
          if (cloneEl && (origEl.scrollTop > 0 || origEl.scrollLeft > 0)) {
            cloneEl.scrollTop = origEl.scrollTop;
            cloneEl.scrollLeft = origEl.scrollLeft;
          }
        });
      }
    };

    const cleanup = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('click', onClick, true);
      if (window._activeLoupe) {
        window._activeLoupe.remove();
        window._activeLoupe = null;
        orbitInstance.showToast('Лупа выключена');
      }
    };

    const onClick = (e) => {
      cleanup();
    };

    const onKeyDown = (e) => {
      if (e.key === 'Escape') cleanup();
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('wheel', onWheel, { passive: true });
    window.addEventListener('keydown', onKeyDown);
    setTimeout(() => {
      window.addEventListener('click', onClick, { capture: true, once: true });
    }, 180);

    orbitInstance.showToast('Лупа 2x активна (кликните в любом месте или Escape для выкл)');
  }

  // ==========================================================================
  // Tool 8: Draggable & Dismissible Stamp Badges (Unified Layering)
  // ==========================================================================

  function spawnDraggableStamp(x, y, label, typeClass, iconClass, options = {}) {
    const canvasViewport = document.getElementById('whiteboard-canvas-viewport') || document.querySelector('.boo-canvas-overlay');
    if (canvasViewport && window.BooCanvasOverlay && typeof window.BooCanvasOverlay.insertStamp === 'function') {
      const stampObj = window.BooCanvasOverlay.insertStamp(label, typeClass, iconClass, x, y);
      if (stampObj) {
        orbitInstance.showToast(`Штамп «${label}» добавлен на доску`);
        return stampObj;
      }
    }

    const host = getOrbitWorkspaceHost();
    const coords = getWorkspaceCoordinates(x, y);
    const stampId = options.id || ('stamp_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5));
    const isRemote = Boolean(options.isRemote);
    const author = options.author || (window.boostudyOS?.viewerName || document.getElementById('trainer-os-config')?.dataset?.viewerName || 'Участник');

    const stampEl = document.createElement('div');
    stampEl.className = 'boo-orbit-stamp-item';
    stampEl.dataset.stampId = stampId;
    stampEl.style.left = `${coords.x}px`;
    stampEl.style.top = `${coords.y}px`;

    stampEl.innerHTML = `
      <div class="boo-orbit-badge-stamp boo-orbit-stamp-${typeClass}">
        <i class="ph-bold ${iconClass}"></i>
        <span>${escapeHtml(label)}</span>
        <span class="boo-stamp-author">${escapeHtml(author)}</span>
        <button type="button" class="boo-stamp-close" aria-label="Удалить"><i class="ph-bold ph-x"></i></button>
      </div>
    `;

    host.appendChild(stampEl);
    bringElementToFront(stampEl);

    // Draggable Stamp Logic with Unified Z-Index
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialLeft = 0;
    let initialTop = 0;
    let lastMoveSentAt = 0;

    const badge = stampEl.querySelector('.boo-orbit-badge-stamp');
    const closeBtn = stampEl.querySelector('.boo-stamp-close');

    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      stampEl.remove();
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_stamp_remove',
        id: stampId
      });
    });

    stampEl.addEventListener('pointerdown', (e) => {
      if (!e.target.closest('.boo-stamp-close')) {
        bringElementToFront(stampEl);
      }
    });

    badge.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.boo-stamp-close')) return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      initialLeft = parseFloat(stampEl.style.left) || coords.x;
      initialTop = parseFloat(stampEl.style.top) || coords.y;
      badge.setPointerCapture?.(e.pointerId);
      bringElementToFront(stampEl);
      e.preventDefault();
    });

    badge.addEventListener('pointermove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      const nx = initialLeft + dx;
      const ny = initialTop + dy;
      stampEl.style.left = `${nx}px`;
      stampEl.style.top = `${ny}px`;

      const now = performance.now();
      if (now - lastMoveSentAt > 40) {
        lastMoveSentAt = now;
        window.boostudyLessonControl?.sendUi?.({
          kind: 'orbit_stamp_move',
          id: stampId,
          x: nx,
          y: ny,
          maxW: host.clientWidth || window.innerWidth,
          maxH: host.clientHeight || window.innerHeight
        });
      }
    });

    const endDrag = (e) => {
      if (!isDragging) return;
      isDragging = false;
      try { badge.releasePointerCapture?.(e.pointerId); } catch (_) {}
      const finalX = parseFloat(stampEl.style.left) || coords.x;
      const finalY = parseFloat(stampEl.style.top) || coords.y;
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_stamp_move',
        id: stampId,
        x: finalX,
        y: finalY,
        maxW: host.clientWidth || window.innerWidth,
        maxH: host.clientHeight || window.innerHeight
      });
    };

    badge.addEventListener('pointerup', endDrag);
    badge.addEventListener('pointercancel', endDrag);

    if (!isRemote) {
      window.boostudyLessonControl?.sendUi?.({
        kind: 'orbit_stamp',
        id: stampId,
        label: label,
        typeClass: typeClass,
        iconClass: iconClass,
        x: coords.x,
        y: coords.y,
        maxW: coords.maxW,
        maxH: coords.maxH,
        author: author
      });
      orbitInstance.showToast(`Штамп «${label}» нанесён (перетаскиваемый)`);
    }

    return stampEl;
  }

  // ==========================================================================
  // Public Boo Orbit Room Synchronization API (window.BooOrbitWheel)
  // ==========================================================================

  function applyRemoteCardMove(card, payload, hostW, hostH) {
    if (!card || !payload) return;
    const maxW = Number(payload.maxW) || hostW;
    const maxH = Number(payload.maxH) || hostH;
    const rx = maxW > 0 ? (payload.x / maxW) * hostW : payload.x;
    const ry = maxH > 0 ? (payload.y / maxH) * hostH : payload.y;
    card.style.left = `${Math.round(rx)}px`;
    card.style.top = `${Math.round(ry)}px`;
  }

  window.BooOrbitWheel = {
    renderRemoteBeacon(payload) {
      const w = window.innerWidth;
      const h = window.innerHeight;
      const rx = (payload.x / (payload.maxW || w)) * w;
      const ry = (payload.y / (payload.maxH || h)) * h;
      triggerPulseBeacon(rx, ry, { isRemote: true, author: payload.author });
    },

    handleRemoteStamp(payload) {
      const host = getOrbitWorkspaceHost();
      const hostW = host.clientWidth || window.innerWidth;
      const hostH = host.clientHeight || window.innerHeight;

      if (payload.kind === 'orbit_stamp') {
        const rx = (payload.x / (payload.maxW || hostW)) * hostW;
        const ry = (payload.y / (payload.maxH || hostH)) * hostH;
        spawnDraggableStamp(rx, ry, payload.label, payload.typeClass, payload.iconClass, {
          id: payload.id,
          isRemote: true,
          author: payload.author
        });
      } else if (payload.kind === 'orbit_stamp_move') {
        const stampEl = document.querySelector(`[data-stamp-id="${payload.id}"]`);
        if (stampEl) {
          applyRemoteCardMove(stampEl, payload, hostW, hostH);
        }
      } else if (payload.kind === 'orbit_stamp_remove') {
        const stampEl = document.querySelector(`[data-stamp-id="${payload.id}"]`);
        if (stampEl) stampEl.remove();
      }
    },

    handleRemoteSticky(payload) {
      const host = getOrbitWorkspaceHost();
      const hostW = host.clientWidth || window.innerWidth;
      const hostH = host.clientHeight || window.innerHeight;

      if (payload.kind === 'orbit_sticky') {
        const rx = (payload.x / (payload.maxW || hostW)) * hostW;
        const ry = (payload.y / (payload.maxH || hostH)) * hostH;
        spawnStickyNote(rx, ry, payload.color || 'yellow', {
          id: payload.id,
          isRemote: true,
          text: payload.text || '',
          author: payload.author
        });
      } else if (payload.kind === 'orbit_sticky_input') {
        const card = document.querySelector(`[data-note-id="${payload.id}"]`);
        if (card) {
          const textarea = card.querySelector('textarea');
          if (textarea && textarea.value !== payload.text) {
            textarea.value = payload.text || '';
          }
        }
      } else if (payload.kind === 'orbit_sticky_move') {
        const card = document.querySelector(`[data-note-id="${payload.id}"]`);
        if (card) {
          applyRemoteCardMove(card, payload, hostW, hostH);
        }
      } else if (payload.kind === 'orbit_sticky_remove') {
        const card = document.querySelector(`[data-note-id="${payload.id}"]`);
        if (card) card.remove();
      }
    },

    handleRemoteTimer(payload) {
      const host = getOrbitWorkspaceHost();
      const hostW = host.clientWidth || window.innerWidth;
      const hostH = host.clientHeight || window.innerHeight;

      if (payload.action === 'close') {
        const existing = document.getElementById('boo-orbit-timer-widget');
        if (existing) {
          if (activeTimerInterval) {
            clearInterval(activeTimerInterval);
            activeTimerInterval = null;
          }
          isTimerRunning = false;
          existing.remove();
        }
      } else if (payload.action === 'open') {
        const rx = (payload.x / (payload.maxW || hostW)) * hostW;
        const ry = (payload.y / (payload.maxH || hostH)) * hostH;
        spawnTimerWidget(rx, ry, {
          isRemote: true,
          seconds: payload.seconds,
          isRunning: payload.isRunning,
          mode: payload.mode
        });
      } else if (payload.action === 'start') {
        const existing = document.getElementById('boo-orbit-timer-widget');
        if (!existing) {
          spawnTimerWidget(hostW / 2 - 120, 80, { isRemote: true, seconds: payload.seconds, mode: payload.mode });
        }
        if (typeof window._booOrbitStartTimerRemote === 'function') {
          window._booOrbitStartTimerRemote(payload.seconds);
        }
      } else if (payload.action === 'pause') {
        if (typeof window._booOrbitPauseTimerRemote === 'function') {
          window._booOrbitPauseTimerRemote(payload.seconds);
        }
      } else if (payload.action === 'reset') {
        if (typeof window._booOrbitResetTimerRemote === 'function') {
          window._booOrbitResetTimerRemote(payload.seconds);
        }
      } else if (payload.action === 'move') {
        const card = document.getElementById('boo-orbit-timer-widget');
        if (card) {
          applyRemoteCardMove(card, payload, hostW, hostH);
        }
      }
    },

    handleRemoteCalc(payload) {
      const host = getOrbitWorkspaceHost();
      const hostW = host.clientWidth || window.innerWidth;
      const hostH = host.clientHeight || window.innerHeight;

      if (payload.action === 'close') {
        const existing = document.getElementById('boo-orbit-calc-widget');
        if (existing) existing.remove();
      } else if (payload.action === 'open') {
        const rx = (payload.x / (payload.maxW || hostW)) * hostW;
        const ry = (payload.y / (payload.maxH || hostH)) * hostH;
        spawnCalcWidget(rx, ry, { isRemote: true, expr: payload.expr, val: payload.val });
      } else if (payload.action === 'update') {
        const card = document.getElementById('boo-orbit-calc-widget');
        if (card) {
          const exprEl = card.querySelector('#calc-screen-expr');
          const valEl = card.querySelector('#calc-screen-val');
          if (exprEl && payload.expr !== undefined) exprEl.textContent = payload.expr;
          if (valEl && payload.val !== undefined) valEl.textContent = payload.val;
        }
      } else if (payload.action === 'move') {
        const card = document.getElementById('boo-orbit-calc-widget');
        if (card) {
          applyRemoteCardMove(card, payload, hostW, hostH);
        }
      }
    },

    handleRemoteCheat(payload) {
      const host = getOrbitWorkspaceHost();
      const hostW = host.clientWidth || window.innerWidth;
      const hostH = host.clientHeight || window.innerHeight;

      if (payload.action === 'close') {
        const existing = document.getElementById('boo-orbit-cheat-widget');
        if (existing) existing.remove();
      } else if (payload.action === 'open') {
        const rx = (payload.x / (payload.maxW || hostW)) * hostW;
        const ry = (payload.y / (payload.maxH || hostH)) * hostH;
        spawnCheatSheet(rx, ry, { isRemote: true });
      } else if (payload.action === 'tab') {
        const card = document.getElementById('boo-orbit-cheat-widget');
        if (card) {
          const btn = card.querySelector(`.boo-cheat-tab-btn[data-tab="${payload.tab}"]`);
          if (btn) btn.click();
        }
      } else if (payload.action === 'move') {
        const card = document.getElementById('boo-orbit-cheat-widget');
        if (card) {
          applyRemoteCardMove(card, payload, hostW, hostH);
        }
      }
    },

    handleRemoteLaser(payload) {
      renderRemoteLaserPayload(payload);
    }
  };

  // Create singleton instance
  const orbitInstance = new BooOrbit();
  window.BooOrbit = orbitInstance;
  window.BooRadialWheel = orbitInstance;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => orbitInstance.init());
  } else {
    orbitInstance.init();
  }

})(window, document);
