/**
 * ORISTERA Atlas: data-backed territory exploration and a low-cost 2.5D camera.
 * The visible filaments describe visual terrain only; topic evidence remains factual.
 */
(function () {
  'use strict';

  class AtlasController {
    constructor(root) {
      this.root = root;
      this.stage = root.querySelector('#ori-atlas-stage');
      this.viewport = root.querySelector('#ori-atlas-viewport');
      this.world = root.querySelector('#ori-atlas-world');
      this.domains = Array.from(root.querySelectorAll('.atlas-domain'));
      this.railButtons = Array.from(root.querySelectorAll('.ori-atlas-tab'));
      this.searchInput = root.querySelector('#ori-atlas-search');
      this.searchResults = root.querySelector('#ori-atlas-search-results');
      this.resetButton = root.querySelector('#ori-atlas-reset-btn');
      this.inspector = root.querySelector('#ori-atlas-inspector');
      this.overviewReadout = root.querySelector('#ori-atlas-overview-card');
      this.domainInspector = root.querySelector('#ori-cluster-inspector');
      this.topicInspector = root.querySelector('#ori-skill-inspector');
      this.reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.listeners = new AbortController();
      this.resizeObserver = null;
      this.visibilityObserver = null;
      this.layoutFrame = null;
      this.activeCid = null;
      this.activeTopic = null;
      this.focusReturnTarget = null;
      this.overviewFocusTarget = null;
      this.layoutMode = 'desktop';
      this.baseScale = 1;
      this.camera = { x: 0, y: 0, scale: 1 };
      this.cameraLimits = { min: 1, max: 1 };
      this.dragState = null;
      this.suppressClick = false;
      this.motionVisible = true;

      this.prepareTopicNodes();
      this.bindEvents();
      this.layoutScene();
      this.observeLifecycle();
      this.restoreState();
      this.syncMotionLifecycle();
    }

    prepareTopicNodes() {
      this.domains.forEach((domain) => {
        domain.querySelectorAll('.ori-star-node').forEach((topic) => {
          const kind = this.evidenceKind(this.evidenceCount(topic));
          topic.classList.add(kind);
          topic.setAttribute('aria-pressed', 'false');
        });
      });
    }

    bindEvents() {
      const signal = this.listeners.signal;
      this.root.addEventListener('click', (event) => {
        if (!(event.target instanceof Element)) return;
        const topic = event.target.closest('.ori-star-node');
        if (topic) {
          event.preventDefault();
          this.selectTopic(topic);
          return;
        }
        const domainButton = event.target.closest('.ori-atlas-tab, .atlas-domain-trigger');
        if (domainButton) {
          this.selectDomain(domainButton.dataset.cid);
          return;
        }
        const searchResult = event.target.closest('[data-search-kind]');
        if (searchResult) this.openSearchResult(searchResult);
      }, { signal });

      this.resetButton?.addEventListener('click', () => this.resetToOverview(), { signal });
      this.root.querySelector('#ori-insp-close')?.addEventListener('click', () => this.closeTopic(), { signal });
      this.root.querySelector('#ori-atlas-zoom-in')?.addEventListener('click', () => this.zoomBy(1.22), { signal });
      this.root.querySelector('#ori-atlas-zoom-out')?.addEventListener('click', () => this.zoomBy(1 / 1.22), { signal });

      this.searchInput?.addEventListener('input', () => this.renderSearchResults(), { signal });
      this.searchInput?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          const firstResult = this.searchResults?.querySelector('[role="option"]');
          if (firstResult) {
            event.preventDefault();
            firstResult.click();
          }
        } else if (event.key === 'Escape') {
          this.closeSearchResults();
        } else if (event.key === 'ArrowDown') {
          const firstResult = this.searchResults?.querySelector('button');
          if (firstResult) {
            event.preventDefault();
            firstResult.focus();
          }
        }
      }, { signal });
      document.addEventListener('pointerdown', (event) => {
        if (!(event.target instanceof Element) || !event.target.closest('.atlas-search')) this.closeSearchResults();
      }, { signal });
      document.addEventListener('keydown', (event) => this.onDocumentKeydown(event), { signal });
      document.addEventListener('visibilitychange', () => this.syncMotionLifecycle(), { signal });
      this.reduceMotion.addEventListener('change', () => this.syncMotionLifecycle(), { signal });

      this.viewport?.addEventListener('pointerdown', (event) => this.beginPan(event), { signal });
      this.viewport?.addEventListener('pointermove', (event) => this.movePan(event), { signal });
      this.viewport?.addEventListener('pointerup', (event) => this.endPan(event), { signal });
      this.viewport?.addEventListener('pointercancel', (event) => this.endPan(event), { signal });
      this.viewport?.addEventListener('click', (event) => {
        if (!this.suppressClick) return;
        event.preventDefault();
        event.stopPropagation();
        this.suppressClick = false;
      }, { capture: true, signal });
      this.viewport?.addEventListener('wheel', (event) => this.onWheel(event), { passive: false, signal });
      this.root.querySelector('.atlas-search')?.addEventListener('submit', (event) => event.preventDefault(), { signal });
    }

    observeLifecycle() {
      if ('ResizeObserver' in window && this.viewport) {
        this.resizeObserver = new ResizeObserver(() => this.scheduleLayout());
        this.resizeObserver.observe(this.viewport);
      } else {
        window.addEventListener('resize', () => this.scheduleLayout(), { signal: this.listeners.signal });
      }
      if ('IntersectionObserver' in window && this.stage) {
        this.visibilityObserver = new IntersectionObserver((entries) => {
          this.motionVisible = entries.some((entry) => entry.isIntersecting);
          this.syncMotionLifecycle();
        }, { threshold: 0.05 });
        this.visibilityObserver.observe(this.stage);
      }
    }

    scheduleLayout() {
      if (this.layoutFrame) return;
      this.layoutFrame = requestAnimationFrame(() => {
        this.layoutFrame = null;
        this.layoutScene();
      });
    }

    layoutScene() {
      if (!this.world || !this.viewport || !this.domains.length) return;
      const width = this.viewport.clientWidth || window.innerWidth;
      const mode = width <= 600 ? 'mobile' : width <= 1100 ? 'tablet' : 'desktop';
      const modeChanged = mode !== this.layoutMode;
      this.layoutMode = mode;
      this.root.dataset.layout = mode;
      this.world.dataset.layout = mode;

      if (mode !== 'desktop') {
        this.world.classList.add('is-flow-layout');
        this.world.style.width = '';
        this.world.style.height = '';
        this.world.style.transform = 'none';
        this.world.style.removeProperty('--camera-x');
        this.world.style.removeProperty('--camera-y');
        this.world.style.removeProperty('--camera-scale');
        this.domains.forEach((domain) => {
          domain.style.removeProperty('left');
          domain.style.removeProperty('top');
          domain.style.removeProperty('width');
          domain.style.removeProperty('height');
        });
        this.baseScale = 1;
        this.cameraLimits = { min: 1, max: 1 };
        this.camera = { x: 0, y: 0, scale: 1 };
        this.updateScaleReadout();
        if (modeChanged && this.activeCid) {
          this.findDomain(this.activeCid)?.scrollIntoView({
            behavior: this.reduceMotion.matches ? 'auto' : 'smooth',
            block: 'center',
          });
        }
        return;
      }

      this.world.classList.remove('is-flow-layout');
      const viewportWidth = this.viewport.clientWidth;
      const viewportHeight = this.viewport.clientHeight;
      const count = this.domains.length;
      const columns = Math.max(1, Math.ceil(Math.sqrt(count * 1.45)));
      const rows = Math.ceil(count / columns);
      const cellWidth = 535;
      const cellHeight = 372;
      const worldWidth = Math.max(1680, 110 + columns * cellWidth + 70);
      const worldHeight = Math.max(820, 70 + rows * cellHeight + 8);
      this.world.style.width = worldWidth + 'px';
      this.world.style.height = worldHeight + 'px';

      this.domains.forEach((domain, index) => {
        const row = Math.floor(index / columns);
        const rowStart = row * columns;
        const rowLength = Math.min(columns, count - rowStart);
        const column = index - rowStart;
        const rowWidth = rowLength * cellWidth + Math.max(0, rowLength - 1) * 32;
        const left = (worldWidth - rowWidth) / 2 + column * (cellWidth + 32) + (row % 2 ? 20 : 0);
        const top = 28 + row * cellHeight + (index % 2 ? 18 : 0);
        const domainWidth = 500 + (index % 3 === 1 ? 14 : 0);
        const domainHeight = 342 + (index % 4 === 2 ? 16 : 0);
        domain.style.left = left + 'px';
        domain.style.top = top + 'px';
        domain.style.width = domainWidth + 'px';
        domain.style.height = domainHeight + 'px';
        domain.dataset.centerX = String(left + domainWidth / 2);
        domain.dataset.centerY = String(top + domainHeight / 2);
      });

      this.baseScale = Math.min(viewportWidth / worldWidth, viewportHeight / worldHeight, 1);
      this.cameraLimits = {
        min: Math.max(0.42, this.baseScale * 0.88),
        max: Math.min(1.8, this.baseScale * 1.8),
      };
      const activeDomain = this.activeCid && this.findDomain(this.activeCid);
      if (activeDomain) this.focusDomain(activeDomain, { instant: true });
      else this.applyCamera(this.overviewCamera(), {
        instant: modeChanged || !this.world.classList.contains('is-layout-ready'),
      });
      this.world.classList.add('is-layout-ready');
      this.updateScaleReadout();
    }

    overviewCamera() {
      const viewportWidth = this.viewport.clientWidth;
      const viewportHeight = this.viewport.clientHeight;
      const worldWidth = this.world.offsetWidth;
      const worldHeight = this.world.offsetHeight;
      return {
        scale: this.baseScale,
        x: (viewportWidth - worldWidth * this.baseScale) / 2,
        y: (viewportHeight - worldHeight * this.baseScale) / 2,
      };
    }

    clampCamera(camera) {
      const width = this.viewport.clientWidth;
      const height = this.viewport.clientHeight;
      const scaledWidth = this.world.offsetWidth * camera.scale;
      const scaledHeight = this.world.offsetHeight * camera.scale;
      return {
        scale: camera.scale,
        x: scaledWidth <= width ? (width - scaledWidth) / 2 : Math.max(width - scaledWidth, Math.min(0, camera.x)),
        y: scaledHeight <= height ? (height - scaledHeight) / 2 : Math.max(height - scaledHeight, Math.min(0, camera.y)),
      };
    }

    applyCamera(camera, options = {}) {
      if (this.layoutMode !== 'desktop') return;
      const next = this.clampCamera(camera);
      this.camera = next;
      this.world.style.transform = 'translate3d(' + next.x + 'px, ' + next.y + 'px, 0) scale(' + next.scale + ')';
      this.world.style.setProperty('--camera-scale', String(next.scale));
      this.world.dataset.cameraMotion = options.instant || this.reduceMotion.matches ? 'instant' : 'spatial';
      this.updateScaleReadout();
    }

    focusDomain(domain, options = {}) {
      if (this.layoutMode !== 'desktop') {
        domain.scrollIntoView({ behavior: this.reduceMotion.matches ? 'auto' : 'smooth', block: 'center' });
        return;
      }
      const scale = Math.min(this.cameraLimits.max, this.baseScale * 1.43);
      const centerX = Number(domain.dataset.centerX) || this.world.offsetWidth / 2;
      const centerY = Number(domain.dataset.centerY) || this.world.offsetHeight / 2;
      this.applyCamera({
        scale,
        x: this.viewport.clientWidth * 0.41 - centerX * scale,
        y: this.viewport.clientHeight * 0.5 - centerY * scale,
      }, options);
    }

    focusTopic(topic, options = {}) {
      const domain = topic.closest('.atlas-domain');
      if (!domain) return;
      if (this.layoutMode !== 'desktop') {
        topic.scrollIntoView({ behavior: this.reduceMotion.matches ? 'auto' : 'smooth', block: 'center' });
        return;
      }
      const worldRect = this.world.getBoundingClientRect();
      const topicRect = topic.getBoundingClientRect();
      const pointX = (topicRect.left + topicRect.width / 2 - worldRect.left) / this.camera.scale;
      const pointY = (topicRect.top + topicRect.height / 2 - worldRect.top) / this.camera.scale;
      const scale = Math.min(this.cameraLimits.max, this.baseScale * 1.63);
      this.applyCamera({
        scale,
        x: this.viewport.clientWidth * 0.38 - pointX * scale,
        y: this.viewport.clientHeight * 0.5 - pointY * scale,
      }, options);
    }

    zoomBy(factor) {
      if (this.layoutMode !== 'desktop') return;
      const rect = this.viewport.getBoundingClientRect();
      this.zoomAt(this.camera.scale * factor, rect.width / 2, rect.height / 2);
    }

    zoomAt(scale, x, y) {
      if (this.layoutMode !== 'desktop') return;
      const nextScale = Math.max(this.cameraLimits.min, Math.min(this.cameraLimits.max, scale));
      const worldX = (x - this.camera.x) / this.camera.scale;
      const worldY = (y - this.camera.y) / this.camera.scale;
      this.applyCamera({
        scale: nextScale,
        x: x - worldX * nextScale,
        y: y - worldY * nextScale,
      });
    }

    beginPan(event) {
      if (this.layoutMode !== 'desktop' || event.button !== 0 || event.target.closest('button, a, input')) return;
      this.dragState = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        initialX: this.camera.x,
        initialY: this.camera.y,
        moved: false,
      };
      this.viewport.setPointerCapture?.(event.pointerId);
      this.viewport.classList.add('is-panning');
    }

    movePan(event) {
      if (!this.dragState || this.dragState.pointerId !== event.pointerId) return;
      const dx = event.clientX - this.dragState.startX;
      const dy = event.clientY - this.dragState.startY;
      if (Math.abs(dx) + Math.abs(dy) > 4) this.dragState.moved = true;
      if (!this.dragState.moved) return;
      this.applyCamera({
        scale: this.camera.scale,
        x: this.dragState.initialX + dx,
        y: this.dragState.initialY + dy,
      }, { instant: true });
    }

    endPan(event) {
      if (!this.dragState || this.dragState.pointerId !== event.pointerId) return;
      this.suppressClick = this.dragState.moved;
      this.dragState = null;
      this.viewport.classList.remove('is-panning');
      if (this.suppressClick) window.setTimeout(() => { this.suppressClick = false; }, 0);
    }

    onWheel(event) {
      if (this.layoutMode !== 'desktop' || event.target.closest('button, a, input')) return;
      event.preventDefault();
      const rect = this.viewport.getBoundingClientRect();
      const factor = Math.exp(-event.deltaY * 0.0012);
      this.zoomAt(this.camera.scale * factor, event.clientX - rect.left, event.clientY - rect.top);
    }

    onDocumentKeydown(event) {
      if (event.key === 'Escape') {
        if (this.searchResults && !this.searchResults.hidden) {
          this.closeSearchResults();
          this.searchInput?.focus();
        } else if (this.activeTopic) this.closeTopic();
        else if (this.activeCid) this.resetToOverview();
        return;
      }
      if (event.altKey || event.ctrlKey || event.metaKey || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
      if (event.key === '/') {
        event.preventDefault();
        this.searchInput?.focus();
      } else if (event.key === '+' || event.key === '=') this.zoomBy(1.18);
      else if (event.key === '-') this.zoomBy(1 / 1.18);
      else if (event.key === '0') this.resetToOverview();
      else {
        const index = Number(event.key) - 1;
        if (Number.isInteger(index) && index >= 0 && index < this.domains.length) {
          this.selectDomain(this.domains[index].dataset.cid);
        }
      }
    }

    renderSearchResults() {
      if (!this.searchInput || !this.searchResults) return;
      const query = this.searchInput.value.trim().toLocaleLowerCase('ru-RU');
      this.searchResults.replaceChildren();
      if (query.length < 2) {
        this.closeSearchResults();
        return;
      }

      const matches = [];
      this.domains.forEach((domain) => {
        const domainName = domain.dataset.title || '';
        if (domainName.toLocaleLowerCase('ru-RU').includes(query)) {
          matches.push({ kind: 'domain', domain, title: domainName, detail: domain.dataset.count + ' тем' });
        }
        domain.querySelectorAll('.ori-star-node').forEach((topic) => {
          const title = topic.dataset.name || '';
          if (title.toLocaleLowerCase('ru-RU').includes(query) || (topic.dataset.num || '') === query.replace(/^№/, '')) {
            matches.push({
              kind: 'topic',
              domain,
              topic,
              title,
              detail: '№' + topic.dataset.num + ' · ' + domainName,
            });
          }
        });
      });

      matches.slice(0, 7).forEach((match) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'atlas-search-result';
        button.setAttribute('role', 'option');
        button.setAttribute('aria-selected', 'false');
        button.dataset.searchKind = match.kind;
        button.dataset.cid = match.domain.dataset.cid;
        if (match.topic) button.dataset.topicNum = match.topic.dataset.num || '';
        const title = document.createElement('span');
        const detail = document.createElement('small');
        title.textContent = match.title;
        detail.textContent = match.detail;
        button.append(title, detail);
        this.searchResults.append(button);
      });

      if (!matches.length) {
        const empty = document.createElement('li');
        empty.className = 'atlas-search-empty';
        empty.setAttribute('role', 'option');
        empty.textContent = 'Совпадений в текущем каталоге нет';
        this.searchResults.append(empty);
      }
      this.searchResults.hidden = false;
      this.searchInput.setAttribute('aria-expanded', 'true');
    }

    openSearchResult(result) {
      const domain = this.findDomain(result.dataset.cid);
      if (!domain) return;
      this.overviewFocusTarget = result;
      this.selectDomain(domain.dataset.cid);
      this.closeSearchResults();
      if (result.dataset.searchKind === 'topic') {
        const topic = Array.from(domain.querySelectorAll('.ori-star-node'))
          .find((item) => item.dataset.num === result.dataset.topicNum);
        if (topic) this.selectTopic(topic);
      } else {
        domain.querySelector('.atlas-domain-trigger')?.focus();
      }
      this.searchInput?.blur();
    }

    selectDomain(cid, options = {}) {
      const domain = this.findDomain(cid);
      if (!domain) return;
      this.activeCid = cid;
      this.activeTopic = null;
      this.focusReturnTarget = domain.querySelector('.atlas-domain-trigger');
      if (!this.overviewFocusTarget?.isConnected) this.overviewFocusTarget = this.focusReturnTarget;
      this.root.dataset.activeDomain = cid;
      this.world.dataset.state = 'domain';
      this.world.dataset.activeDomain = cid;
      this.domains.forEach((item) => {
        const selected = item === domain;
        item.classList.toggle('is-active', selected);
        item.classList.toggle('is-muted', !selected);
        item.querySelector('.atlas-domain-trigger')?.setAttribute('aria-pressed', String(selected));
        const field = item.querySelector('.atlas-topic-field');
        if (field) field.hidden = !selected;
      });
      this.railButtons.forEach((button) => {
        const selected = button.dataset.cid === cid;
        button.classList.toggle('is-active', selected);
        button.setAttribute('aria-pressed', String(selected));
      });

      this.overviewReadout.hidden = true;
      this.domainInspector.hidden = false;
      this.topicInspector.hidden = true;
      this.inspector.hidden = false;
      this.resetButton.hidden = false;
      this.setHeading('Погружение', domain.dataset.title || 'Область знаний');
      const topics = Array.from(domain.querySelectorAll('.ori-star-node'));
      const observations = topics.reduce((sum, topic) => sum + this.evidenceCount(topic), 0);
      this.root.querySelector('#ori-cluster-title').textContent = domain.dataset.title || 'Область знаний';
      this.root.querySelector('#ori-cluster-count').textContent = topics.length + ' тем';
      this.root.querySelector('#ori-cluster-summary').textContent = observations
        ? topics.length + ' доступных тем. В каталоге есть ' + observations + ' подтверждённых учебных наблюдений.'
        : topics.length + ' доступных тем. Подтверждённая учебная активность пока не записана.';
      this.root.querySelector('#ori-cluster-evidence').textContent = String(observations);

      if (!options.skipCamera) this.focusDomain(domain, { instant: options.instant });
      if (options.writeState !== false) this.persistState();
    }

    selectTopic(topic, options = {}) {
      const domain = topic.closest('.atlas-domain');
      if (!domain) return;
      if (this.activeCid !== domain.dataset.cid) {
        this.selectDomain(domain.dataset.cid, { skipCamera: true, writeState: false });
      }
      this.activeTopic = topic;
      this.focusReturnTarget = topic;
      this.domains.forEach((item) => {
        item.querySelectorAll('.ori-star-node').forEach((node) => {
          const selected = node === topic;
          node.classList.toggle('is-selected', selected);
          node.setAttribute('aria-pressed', String(selected));
        });
      });
      this.domainInspector.hidden = true;
      this.topicInspector.hidden = false;
      this.inspector.hidden = false;
      this.world.dataset.state = 'topic';
      this.setHeading('Тема · исследование', topic.dataset.name || 'Тема');
      this.renderTopicDetails(topic);
      if (!options.skipCamera) this.focusTopic(topic, { instant: options.instant });
      if (options.writeState !== false) this.persistState();
    }

    renderTopicDetails(topic) {
      const count = this.evidenceCount(topic);
      const badge = this.root.querySelector('#ori-insp-badge');
      const domain = topic.closest('.atlas-domain');
      const practiceLink = this.root.querySelector('#ori-insp-practice-link');
      this.root.querySelector('#ori-insp-num').textContent = 'ТЕМА №' + (topic.dataset.num || '');
      this.root.querySelector('#ori-insp-title').textContent = topic.dataset.name || 'Тема';
      if (badge) {
        badge.textContent = this.evidenceLabel(count);
        badge.className = 'atlas-inspector-badge ' + this.evidenceKind(count);
      }
      this.root.querySelector('#ori-insp-desc').textContent = count === 0
        ? 'Подтверждённые учебные наблюдения пока не записаны. Это не означает, что тема не освоена.'
        : count < 3
          ? 'Для этой темы есть отдельные наблюдения. Доступные данные не позволяют делать вывод об уровне освоения.'
          : 'По теме записаны повторные наблюдения. Atlas показывает их количество, но не рассчитывает мастерство.';
      this.root.querySelector('#ori-insp-evidence-count').textContent = String(count);
      this.root.querySelector('#ori-insp-evidence').textContent = count === 0
        ? 'В доступной истории нет подтверждений по этой теме.'
        : count + ' подтверждённых наблюдений доступно для просмотра.';
      const url = new URL(practiceLink.href, window.location.href);
      url.searchParams.delete('task_no');
      url.searchParams.set('atlas_area', domain?.dataset.cid || '');
      url.searchParams.set('atlas_topic', topic.dataset.num || '');
      practiceLink.href = url.href;
      practiceLink.setAttribute('aria-label', 'Перейти к практике по теме ' + (topic.dataset.name || ''));
    }

    evidenceCount(topic) {
      const count = Number.parseInt(topic.dataset.evidenceCount || '0', 10);
      return Number.isFinite(count) && count > 0 ? count : 0;
    }

    evidenceLabel(count) {
      if (count >= 3) return 'Повторные наблюдения';
      if (count > 0) return count + ' наблюдения';
      return 'Нет подтверждений';
    }

    evidenceKind(count) {
      if (count >= 3) return 'is-repeated';
      if (count > 0) return 'is-observed';
      return 'is-unobserved';
    }

    closeTopic(restoreFocus = true, options = {}) {
      if (!this.activeTopic) return;
      const focusTarget = this.focusReturnTarget;
      this.activeTopic = null;
      this.world.dataset.state = 'domain';
      this.domains.forEach((domain) => {
        domain.querySelectorAll('.ori-star-node').forEach((topic) => {
          topic.classList.remove('is-selected');
          topic.setAttribute('aria-pressed', 'false');
        });
      });
      this.topicInspector.hidden = true;
      this.domainInspector.hidden = false;
      this.inspector.hidden = false;
      const domain = this.findDomain(this.activeCid);
      this.setHeading('Погружение', domain?.dataset.title || 'Область знаний');
      if (restoreFocus && focusTarget?.isConnected) focusTarget.focus();
      if (options.writeState !== false) this.persistState();
    }

    resetToOverview(options = {}) {
      const focusTarget = this.overviewFocusTarget?.isConnected ? this.overviewFocusTarget : this.railButtons[0];
      this.activeCid = null;
      this.activeTopic = null;
      this.root.removeAttribute('data-active-domain');
      this.world.removeAttribute('data-active-domain');
      this.world.dataset.state = 'overview';
      this.domains.forEach((domain) => {
        domain.classList.remove('is-active', 'is-muted');
        domain.querySelector('.atlas-domain-trigger')?.setAttribute('aria-pressed', 'false');
        domain.querySelectorAll('.ori-star-node').forEach((topic) => {
          topic.classList.remove('is-selected');
          topic.setAttribute('aria-pressed', 'false');
        });
        const topicField = domain.querySelector('.atlas-topic-field');
        if (topicField) topicField.hidden = true;
      });
      this.railButtons.forEach((button) => {
        button.classList.remove('is-active');
        button.setAttribute('aria-pressed', 'false');
      });
      this.inspector.hidden = true;
      this.domainInspector.hidden = true;
      this.topicInspector.hidden = true;
      this.overviewReadout.hidden = false;
      this.resetButton.hidden = true;
      this.setHeading('Общий рельеф', 'Мир знаний');
      this.applyCamera(this.overviewCamera());
      this.overviewFocusTarget = null;
      if (options.focus !== false) focusTarget?.focus?.();
      if (options.writeState !== false) this.persistState();
    }

    setHeading(level, title) {
      const levelElement = this.root.querySelector('#ori-atlas-view-level');
      const titleElement = this.root.querySelector('#ori-atlas-view-title');
      if (levelElement) {
        levelElement.textContent = title;
        levelElement.dataset.level = level;
      }
      this.root.querySelector('#ori-atlas-view-subtitle').textContent = level === 'Общий рельеф'
        ? 'Информатика · ' + this.root.dataset.topicCount + ' доступных тем'
        : level;
      if (titleElement) titleElement.textContent = title;
    }

    persistState() {
      const url = new URL(window.location.href);
      if (this.activeCid) url.searchParams.set('atlas_area', this.activeCid);
      else url.searchParams.delete('atlas_area');
      if (this.activeTopic) url.searchParams.set('atlas_topic', this.activeTopic.dataset.num || '');
      else url.searchParams.delete('atlas_topic');
      window.history.replaceState({
        ...(window.history.state || {}),
        oristeraAtlas: { area: this.activeCid, topic: this.activeTopic?.dataset.num || null },
      }, document.title, url.href);
    }

    restoreState() {
      const params = new URLSearchParams(window.location.search);
      const cid = params.get('atlas_area');
      const domain = cid && this.findDomain(cid);
      if (!domain) return;
      this.selectDomain(cid, { instant: true, writeState: false });
      const topicNum = params.get('atlas_topic');
      if (!topicNum) return;
      const topic = Array.from(domain.querySelectorAll('.ori-star-node'))
        .find((item) => item.dataset.num === topicNum);
      if (topic) this.selectTopic(topic, { instant: true, writeState: false });
    }

    findDomain(cid) {
      return this.domains.find((domain) => domain.dataset.cid === cid);
    }

    closeSearchResults() {
      if (!this.searchResults || !this.searchInput) return;
      this.searchResults.hidden = true;
      this.searchInput.setAttribute('aria-expanded', 'false');
    }

    updateScaleReadout() {
      const output = this.root.querySelector('#ori-atlas-scale');
      if (output) output.value = Math.round(this.camera.scale / (this.baseScale || 1) * 100) + '%';
    }

    syncMotionLifecycle() {
      const mainStage = document.getElementById('ori-main-stage');
      const paused = document.hidden || !this.motionVisible || mainStage?.dataset.oriMotion === 'paused' || this.reduceMotion.matches;
      this.root.dataset.motionPaused = String(Boolean(paused));
    }

    destroy() {
      this.listeners.abort();
      this.resizeObserver?.disconnect();
      this.visibilityObserver?.disconnect();
      if (this.layoutFrame) cancelAnimationFrame(this.layoutFrame);
    }
  }

  function initAtlas() {
    const root = document.getElementById('ori-atlas-universe');
    if (!root) return;
    if (window.OristeraAtlas?.root === root) return;
    window.OristeraAtlas?.destroy?.();
    window.OristeraAtlas = new AtlasController(root);
  }

  document.addEventListener('DOMContentLoaded', initAtlas, { once: true });
  window.addEventListener('ori:space-entered', (event) => {
    if (event.detail?.path?.includes('/atlas')) initAtlas();
    else if (window.OristeraAtlas?.root && !window.OristeraAtlas.root.isConnected) {
      window.OristeraAtlas.destroy();
      window.OristeraAtlas = null;
    }
  });
})();
