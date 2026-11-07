/**
 * Oristera Atlas: accessible focus and navigation for the topic map.
 * The page only presents evidence counts supplied by the read-only adapter.
 */
(function () {
  'use strict';

  class AtlasController {
    constructor() {
      this.svg = document.getElementById('ori-atlas-svg');
      if (!this.svg) return;

      this.clusters = Array.from(this.svg.querySelectorAll('.ori-constellation-cluster'));
      this.currentView = 'overview';
      this.activeCid = null;
      this.activeTopic = null;
      this.focusReturnTarget = null;
      this.animationFrame = null;
      this.viewBox = this.readViewBox();

      this.resetButton = document.getElementById('ori-atlas-reset-btn');
      this.level = document.getElementById('ori-atlas-view-level');
      this.title = document.getElementById('ori-atlas-view-title');
      this.subtitle = document.getElementById('ori-atlas-view-subtitle');
      this.overviewPanel = document.getElementById('ori-atlas-overview-card');
      this.clusterPanel = document.getElementById('ori-cluster-inspector');
      this.skillPanel = document.getElementById('ori-skill-inspector');

      this.bindEvents();
    }

    readViewBox() {
      const [x, y, width, height] = (this.svg.getAttribute('viewBox') || '0 0 1000 650')
        .split(/\s+/)
        .map(Number);
      return { x, y, width, height };
    }

    bindEvents() {
      this.svg.addEventListener('click', (event) => {
        const topic = event.target.closest('.ori-star-node');
        if (topic) {
          event.stopPropagation();
          this.selectTopic(topic);
          return;
        }

        const cluster = event.target.closest('.ori-constellation-cluster');
        if (cluster) this.selectCluster(cluster.dataset.cid);
      });

      this.svg.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const item = event.target.closest('.ori-star-node, .ori-constellation-cluster');
        if (!item) return;
        event.preventDefault();
        if (item.classList.contains('ori-star-node')) this.selectTopic(item);
        else this.selectCluster(item.dataset.cid);
      });

      document.querySelectorAll('.ori-atlas-tab, .ori-area-jump').forEach((button) => {
        button.addEventListener('click', () => this.selectCluster(button.dataset.cid));
      });

      this.resetButton?.addEventListener('click', () => this.resetToOverview());
      document.getElementById('ori-insp-close')?.addEventListener('click', () => this.closeTopic());

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          if (this.activeTopic) this.closeTopic();
          else if (this.currentView === 'area') this.resetToOverview();
          return;
        }

        if (event.altKey || event.ctrlKey || event.metaKey || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
        const index = Number(event.key) - 1;
        if (Number.isInteger(index) && index >= 0 && index < this.clusters.length) {
          this.selectCluster(this.clusters[index].dataset.cid);
        }
      });
    }

    findCluster(cid) {
      return this.clusters.find((cluster) => cluster.dataset.cid === cid);
    }

    selectCluster(cid) {
      const cluster = this.findCluster(cid);
      if (!cluster) return;

      this.currentView = 'area';
      this.activeCid = cid;
      this.activeTopic = null;
      this.closeTopic(false);
      this.viewToCluster(cluster);

      this.resetButton?.classList.remove('hidden');
      if (this.level) this.level.textContent = 'Выбранная область';
      if (this.title) this.title.textContent = cluster.dataset.title || 'Область знаний';
      if (this.subtitle) this.subtitle.textContent = 'Темы сгруппированы по разделам предмета. Выберите тему, чтобы увидеть только доступные подтверждения.';

      this.overviewPanel?.classList.add('hidden');
      this.skillPanel?.classList.add('hidden');
      this.clusterPanel?.classList.remove('hidden');
      const topicCount = cluster.querySelectorAll('.ori-star-node').length;
      const summary = document.getElementById('ori-cluster-summary');
      if (summary) summary.textContent = `${topicCount} тем в этой области. Показатели освоения не рассчитываются.`;
      this.renderTopics(cluster);

      this.clusters.forEach((item) => {
        const isSelected = item === cluster;
        item.classList.toggle('is-focused', isSelected);
        item.classList.toggle('is-dimmed', !isSelected);
        item.querySelector('.ori-map-region')?.setAttribute('aria-pressed', String(isSelected));
      });
      document.querySelectorAll('.ori-atlas-tab').forEach((tab) => {
        const selected = tab.dataset.cid === cid;
        tab.classList.toggle('is-active', selected);
        tab.setAttribute('aria-pressed', String(selected));
      });
    }

    viewToCluster(cluster) {
      if (!this.svg.getClientRects().length) return;
      const cx = Number(cluster.dataset.centerX) || 500;
      const cy = Number(cluster.dataset.centerY) || 325;
      const width = 390;
      const height = 290;
      const target = {
        x: Math.max(0, Math.min(1000 - width, cx - width / 2)),
        y: Math.max(0, Math.min(650 - height, cy - height / 2)),
        width,
        height,
      };
      this.animateViewBox(target);
    }

    renderTopics(cluster) {
      const list = document.getElementById('ori-cluster-topics');
      const title = document.getElementById('ori-cluster-title');
      if (!list || !title) return;

      title.textContent = cluster.dataset.title || 'Темы области';
      list.replaceChildren();
      cluster.querySelectorAll('.ori-star-node').forEach((topic) => {
        const item = document.createElement('li');
        const button = document.createElement('button');
        const number = document.createElement('span');
        const name = document.createElement('span');
        const status = document.createElement('span');
        const count = this.evidenceCount(topic);

        button.type = 'button';
        button.className = 'ori-cluster-topic';
        number.className = 'ori-topic-number';
        number.textContent = `№${topic.dataset.num || ''}`;
        name.className = 'ori-topic-name';
        name.textContent = topic.dataset.name || 'Тема';
        status.className = `ori-topic-evidence ${this.evidenceKind(count)}`;
        status.textContent = this.evidenceLabel(count);
        button.append(number, name, status);
        button.addEventListener('click', () => this.selectTopic(topic, button));
        item.append(button);
        list.append(item);
      });
    }

    selectTopic(topic, returnTarget = topic) {
      const cluster = topic.closest('.ori-constellation-cluster');
      if (!cluster) return;
      if (this.activeCid !== cluster.dataset.cid) this.selectCluster(cluster.dataset.cid);

      this.activeTopic = topic;
      this.focusReturnTarget = returnTarget;
      this.renderTopicDetails(topic);
      this.clusterPanel?.classList.add('hidden');
      this.skillPanel?.classList.remove('hidden');
      this.clusters.forEach((item) => item.classList.toggle('is-focused', item === cluster));
      this.svg.querySelectorAll('.ori-star-node').forEach((item) => item.classList.toggle('is-selected', item === topic));
    }

    renderTopicDetails(topic) {
      const count = this.evidenceCount(topic);
      const badge = document.getElementById('ori-insp-badge');
      const description = document.getElementById('ori-insp-desc');
      const countElement = document.getElementById('ori-insp-evidence-count');
      const evidence = document.getElementById('ori-insp-evidence');
      const practiceLink = document.getElementById('ori-insp-practice-link');

      document.getElementById('ori-insp-num').textContent = `№${topic.dataset.num || ''}`;
      document.getElementById('ori-insp-title').textContent = topic.dataset.name || 'Тема';
      if (badge) {
        badge.textContent = this.evidenceLabel(count);
        badge.className = `ori-inspector-tag ${this.evidenceKind(count)}`;
      }
      if (description) {
        description.textContent = count === 0
          ? 'Подтверждённые учебные наблюдения пока не записаны. Это не означает, что тема не освоена.'
          : count < 3
            ? 'Для этой темы есть отдельные наблюдения. Их недостаточно, чтобы делать вывод об освоении.'
            : 'По теме записаны повторные наблюдения. Карта показывает их количество и не рассчитывает уровень освоения.';
      }
      if (countElement) countElement.textContent = String(count);
      if (evidence) evidence.textContent = count === 0
        ? 'Подтверждений в доступных данных нет.'
        : `${count} подтверждённых наблюдений доступно для просмотра.`;
      if (practiceLink) practiceLink.href = `/oristera/practice?task_no=${encodeURIComponent(topic.dataset.num || '')}`;
    }

    evidenceCount(topic) {
      const value = Number.parseInt(topic.dataset.evidenceCount || '0', 10);
      return Number.isFinite(value) && value > 0 ? value : 0;
    }

    evidenceKind(count) {
      if (count >= 3) return 'is-repeated';
      if (count > 0) return 'is-observed';
      return 'is-unobserved';
    }

    evidenceLabel(count) {
      if (count >= 3) return 'Повторные подтверждения';
      if (count > 0) return `${count} наблюд.`;
      return 'Нет данных';
    }

    closeTopic(restoreFocus = true) {
      this.activeTopic = null;
      this.skillPanel?.classList.add('hidden');
      this.clusterPanel?.classList.toggle('hidden', this.currentView !== 'area');
      this.svg.querySelectorAll('.ori-star-node').forEach((topic) => topic.classList.remove('is-selected'));
      if (restoreFocus) this.focusReturnTarget?.focus?.();
    }

    resetToOverview() {
      this.currentView = 'overview';
      this.activeCid = null;
      this.closeTopic(false);
      this.animateViewBox({ x: 0, y: 0, width: 1000, height: 650 });
      this.resetButton?.classList.add('hidden');
      if (this.level) this.level.textContent = 'Обзор предмета';
      if (this.title) this.title.textContent = 'Связи между темами';
      if (this.subtitle) this.subtitle.textContent = 'Исследуйте карту информатики. Метки показывают только подтверждённые наблюдения; отсутствие данных не означает отсутствие знаний.';
      this.overviewPanel?.classList.remove('hidden');
      this.clusterPanel?.classList.add('hidden');
      this.skillPanel?.classList.add('hidden');
      this.clusters.forEach((cluster) => {
        cluster.classList.remove('is-focused', 'is-dimmed');
        cluster.querySelector('.ori-map-region')?.setAttribute('aria-pressed', 'false');
      });
      document.querySelectorAll('.ori-atlas-tab').forEach((tab) => {
        tab.classList.remove('is-active');
        tab.setAttribute('aria-pressed', 'false');
      });
    }

    animateViewBox(target) {
      if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
      const start = { ...this.viewBox };
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (reduceMotion) {
        this.viewBox = { ...target };
        this.applyViewBox();
        return;
      }

      const startedAt = performance.now();
      const duration = 360;
      const easeOut = (progress) => 1 - Math.pow(1 - progress, 4);
      const frame = (now) => {
        const progress = Math.min(1, (now - startedAt) / duration);
        const eased = easeOut(progress);
        this.viewBox = {
          x: start.x + (target.x - start.x) * eased,
          y: start.y + (target.y - start.y) * eased,
          width: start.width + (target.width - start.width) * eased,
          height: start.height + (target.height - start.height) * eased,
        };
        this.applyViewBox();
        if (progress < 1) this.animationFrame = requestAnimationFrame(frame);
        else this.animationFrame = null;
      };
      this.animationFrame = requestAnimationFrame(frame);
    }

    applyViewBox() {
      this.svg.setAttribute('viewBox', `${this.viewBox.x} ${this.viewBox.y} ${this.viewBox.width} ${this.viewBox.height}`);
    }
  }

  function initAtlas() {
    if (document.getElementById('ori-atlas-svg') && !window.OristeraAtlas) {
      window.OristeraAtlas = new AtlasController();
    }
  }

  document.addEventListener('DOMContentLoaded', initAtlas, { once: true });
  window.addEventListener('ori:space-entered', (event) => {
    if (event.detail?.path?.includes('atlas')) initAtlas();
  });
})();
