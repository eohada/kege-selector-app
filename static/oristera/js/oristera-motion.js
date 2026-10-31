/**
 * ORISTERA spatial navigation and on-demand motion diagnostics.
 * Navigation remains server rendered; this controller swaps only the shared
 * Oristera stage and keeps normal browser navigation semantics intact.
 */
(function() {
  'use strict';

  class OristeraMotionEngine {
    constructor() {
      this.motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.prefersReducedMotion = this.motionPreference.matches;
      this.navigationId = 0;
      this.pendingController = null;
      this.activeTransition = null;
      this.motionObserver = null;
      this.motionScopeInView = true;
      this.metrics = {
        transitionCount: 0,
        lastDurationMs: 0,
        lastFetchDurationMs: 0,
        lastTransitionDurationMs: 0,
        lastFrameMeasurement: null
      };

      this.initConceptSwitcher();
      this.initParallax();
      this.initMotionLifecycle();
      this.initSeamlessNavigation();
      this.motionPreference.addEventListener?.('change', event => {
        this.prefersReducedMotion = event.matches;
        this.syncMotionLifecycle();
      });
    }

    initMotionLifecycle() {
      const scope = document.getElementById('ori-main-stage');
      if (!scope) return;

      if ('IntersectionObserver' in window) {
        this.motionObserver = new IntersectionObserver(entries => {
          this.motionScopeInView = entries.some(entry => entry.isIntersecting);
          this.syncMotionLifecycle();
        }, { threshold: 0 });
        this.motionObserver.observe(scope);
      }

      document.addEventListener('visibilitychange', () => this.syncMotionLifecycle());
      this.syncMotionLifecycle();
    }

    syncMotionLifecycle() {
      const scope = document.getElementById('ori-main-stage');
      if (!scope) return;

      const shouldPause = document.hidden || this.prefersReducedMotion || (this.motionObserver && !this.motionScopeInView);
      if (shouldPause) scope.setAttribute('data-ori-motion', 'paused');
      else scope.removeAttribute('data-ori-motion');
    }

    initConceptSwitcher() {
      const savedConcept = localStorage.getItem('ori_concept') || 'observatory';
      document.documentElement.setAttribute('data-ori-concept', savedConcept);

      document.addEventListener('click', event => {
        const button = event.target.closest('.ori-concept-btn');
        if (!button) return;
        const concept = button.getAttribute('data-concept');
        if (!concept) return;

        document.documentElement.setAttribute('data-ori-concept', concept);
        localStorage.setItem('ori_concept', concept);
        document.querySelectorAll('.ori-concept-btn').forEach(item => {
          item.classList.toggle('active', item.getAttribute('data-concept') === concept);
        });
      });

      document.querySelectorAll('.ori-concept-btn').forEach(button => {
        button.classList.toggle('active', button.getAttribute('data-concept') === savedConcept);
      });
    }

    initParallax() {
      const stage = document.querySelector('.ori-genesis-universe');
      if (!stage || this.prefersReducedMotion || !window.matchMedia('(pointer: fine)').matches) return;

      let frameId = 0;
      let pointer = null;
      const paint = () => {
        frameId = 0;
        if (!pointer || !stage.isConnected || document.hidden) return;
        const bounds = stage.getBoundingClientRect();
        const x = ((pointer.x - bounds.left) / bounds.width - 0.5) * 2;
        const y = ((pointer.y - bounds.top) / bounds.height - 0.5) * 2;
        stage.style.setProperty('--ori-pointer-x', `${Math.max(-1, Math.min(1, x)) * 5}px`);
        stage.style.setProperty('--ori-pointer-y', `${Math.max(-1, Math.min(1, y)) * 5}px`);
      };

      const onPointerMove = event => {
        pointer = { x: event.clientX, y: event.clientY };
        if (!frameId) frameId = requestAnimationFrame(paint);
      };
      const reset = () => {
        pointer = null;
        if (frameId) cancelAnimationFrame(frameId);
        frameId = 0;
        if (stage.isConnected) {
          stage.style.removeProperty('--ori-pointer-x');
          stage.style.removeProperty('--ori-pointer-y');
        }
      };

      stage.addEventListener('pointermove', onPointerMove, { passive: true });
      stage.addEventListener('pointerleave', reset, { passive: true });
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) reset();
      });
    }

    initSeamlessNavigation() {
      document.addEventListener('click', event => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const link = event.target.closest('a[href]');
        if (!link || link.target && link.target !== '_self' || link.hasAttribute('download')) return;
        if (link.id === 'ori-mode-toggle-btn' || link.id === 'ori-genesis-classic-toggle') return;

        let target;
        try {
          target = new URL(link.href, window.location.href);
        } catch (_) {
          return;
        }
        if (target.origin !== window.location.origin || !target.pathname.startsWith('/oristera/')) return;
        if (target.pathname === '/oristera/toggle' || target.pathname.endsWith('/toggle-mode')) return;
        if (target.href === window.location.href) return;

        event.preventDefault();
        this.teleportTo(target.href, { source: link });
      });

      window.addEventListener('popstate', () => {
        this.teleportTo(window.location.href, { pushState: false, historyState: window.history.state });
      });
    }

    async teleportTo(targetUrl, options = {}) {
      const target = new URL(targetUrl, window.location.href);
      if (target.origin !== window.location.origin) {
        window.location.assign(target.href);
        return;
      }

      const pushState = options.pushState !== false;
      const sourceLink = options.source || null;
      const historyState = options.historyState || window.history.state || {};
      let currentStage = document.getElementById('ori-main-stage');
      if (!currentStage) {
        window.location.assign(target.href);
        return;
      }

      const requestId = ++this.navigationId;
      if (this.pendingController) this.pendingController.abort();
      const controller = new AbortController();
      this.pendingController = controller;
      if (sourceLink) {
        sourceLink.setAttribute('aria-busy', 'true');
        sourceLink.dataset.oriNavigationId = String(requestId);
      }
      const navigationStart = performance.now();
      const fetchStart = navigationStart;

      try {
        const response = await fetch(target.href, {
          signal: controller.signal,
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (requestId !== this.navigationId) return;
        if (!response.ok) {
          window.location.assign(target.href);
          return;
        }

        const html = await response.text();
        if (requestId !== this.navigationId) return;
        const parsed = new DOMParser().parseFromString(html, 'text/html');
        const newStage = parsed.getElementById('ori-main-stage');
        if (!newStage) {
          window.location.assign(target.href);
          return;
        }
        if (requestId !== this.navigationId) return;
        if (this.activeTransition) await this.activeTransition;
        if (requestId !== this.navigationId) return;
        currentStage = document.getElementById('ori-main-stage');
        if (!currentStage) {
          window.location.assign(target.href);
          return;
        }

        const fetchDuration = performance.now() - fetchStart;
        const isGenesisSource = !!currentStage.querySelector('.ori-genesis-root');
        const isGenesisTarget = !!newStage.querySelector('.ori-genesis-root');
        const portal = this.getPortalName(sourceLink);
        const returningPortal = historyState.oriPortalExit || historyState.oriPortalFrom || portal;
        const sourceShared = this.findSharedSource(currentStage, sourceLink, isGenesisSource, isGenesisTarget, portal || historyState.oriPortalFrom);
        const targetShared = this.findSharedTarget(newStage, isGenesisTarget, isGenesisSource, returningPortal);
        const canTransition = document.startViewTransition && !this.prefersReducedMotion;

        if (sourceShared && targetShared && canTransition) {
          sourceShared.style.viewTransitionName = 'ori-nexus-portal';
          targetShared.style.viewTransitionName = 'ori-nexus-portal';
        }

        const transitionStart = performance.now();
        let domSwapped = false;
        const swap = () => {
          this.swapPage(parsed, newStage, currentStage);
          domSwapped = true;

          if (pushState) {
            if (portal) {
              window.history.replaceState({ ...(window.history.state || {}), oriPortalExit: portal }, document.title, window.location.href);
            }
            window.history.pushState({ oriPortalFrom: portal || null }, parsed.title, target.href);
          }

          currentStage.setAttribute('tabindex', '-1');
          currentStage.focus({ preventScroll: true });
          window.dispatchEvent(new CustomEvent('ori:space-entered', { detail: { path: target.pathname } }));
        };

        if (canTransition) {
          const transition = document.startViewTransition(swap);
          const finished = transition.finished;
          this.activeTransition = finished.then(() => undefined, () => undefined);
          try {
            await finished.catch(error => {
              if (!domSwapped) throw error;
            });
          } finally {
            if (this.activeTransition) await this.activeTransition;
            this.activeTransition = null;
          }
        } else {
          swap();
        }

        if (sourceShared) sourceShared.style.removeProperty('view-transition-name');
        const activeStage = document.getElementById('ori-main-stage');
        const activePortal = activeStage?.querySelector('[style*="view-transition-name"]');
        if (activePortal) activePortal.style.removeProperty('view-transition-name');

        if (requestId !== this.navigationId) return;
        const duration = performance.now() - navigationStart;
        this.metrics.transitionCount++;
        this.metrics.lastDurationMs = Math.round(duration);
        this.metrics.lastFetchDurationMs = Math.round(fetchDuration);
        this.metrics.lastTransitionDurationMs = Math.round(performance.now() - transitionStart);
      } catch (error) {
        if (error.name === 'AbortError' || requestId !== this.navigationId) return;
        console.warn('Oristera navigation fell back to a full page load:', error);
        window.location.assign(target.href);
      } finally {
        if (requestId === this.navigationId) this.pendingController = null;
        if (sourceLink?.isConnected && sourceLink.dataset.oriNavigationId === String(requestId)) {
          sourceLink.removeAttribute('aria-busy');
          delete sourceLink.dataset.oriNavigationId;
        }
      }
    }

    getPortalName(link) {
      const name = link?.getAttribute('data-ori-portal');
      return name && /^[a-z-]+$/.test(name) ? name : null;
    }

    findSharedSource(currentStage, sourceLink, isGenesisSource, isGenesisTarget, portal) {
      if (isGenesisSource && !isGenesisTarget && portal) {
        return currentStage.querySelector(`.ori-genesis-orb[data-ori-portal="${portal}"]`);
      }
      if (!isGenesisSource && isGenesisTarget) {
        return currentStage.querySelector('.ori-field-page');
      }
      return sourceLink?.closest('.ori-genesis-orb, .ori-field-page') || null;
    }

    findSharedTarget(newStage, isGenesisTarget, isGenesisSource, portal) {
      if (!isGenesisTarget && isGenesisSource) return newStage.querySelector('.ori-field-page');
      if (isGenesisTarget && !isGenesisSource && portal) {
        return newStage.querySelector(`.ori-genesis-orb[data-ori-portal="${portal}"]`);
      }
      return null;
    }

    swapPage(parsed, newStage, currentStage) {
      currentStage.innerHTML = newStage.innerHTML;
      currentStage.className = newStage.className;
      currentStage.classList.remove('ori-space-enter');
      for (const attribute of [...currentStage.attributes]) {
        if (attribute.name !== 'id' && attribute.name !== 'class') currentStage.removeAttribute(attribute.name);
      }
      for (const attribute of [...newStage.attributes]) {
        if (attribute.name !== 'id' && attribute.name !== 'class') currentStage.setAttribute(attribute.name, attribute.value);
      }

      document.body.className = parsed.body.className;
      document.title = parsed.title;
      this.syncMotionLifecycle();

      const newCoordinates = parsed.getElementById('ori-spatial-coords')?.textContent;
      const coordinates = document.getElementById('ori-spatial-coords');
      if (coordinates && newCoordinates !== undefined) coordinates.textContent = newCoordinates;

      const activeSpaces = new Set([...parsed.querySelectorAll('.ori-compass-node.active')].map(node => node.dataset.space));
      document.querySelectorAll('.ori-compass-node').forEach(node => {
        node.classList.toggle('active', activeSpaces.has(node.dataset.space));
      });
    }

    async measureFrames(durationMs = 2000) {
      const requestedDuration = Math.max(500, Math.min(10000, Number(durationMs) || 2000));
      if (document.hidden) throw new Error('Frame measurement requires a visible tab.');

      const intervals = [];
      let previous = null;
      let start = null;
      return new Promise((resolve, reject) => {
        let frameId = 0;
        const sample = timestamp => {
          if (document.hidden) {
            cancelAnimationFrame(frameId);
            reject(new Error('Frame measurement stopped because the tab became hidden.'));
            return;
          }
          if (start === null) start = timestamp;
          if (previous !== null) intervals.push(timestamp - previous);
          previous = timestamp;
          if (timestamp - start >= requestedDuration) {
            const sorted = intervals.slice().sort((a, b) => a - b);
            const percentile = p => sorted.length ? Number(sorted[Math.min(sorted.length - 1, Math.ceil(p * sorted.length) - 1)].toFixed(2)) : null;
            const result = {
              durationMs: Math.round(timestamp - start),
              frameCount: intervals.length,
              p50FrameMs: percentile(0.50),
              p95FrameMs: percentile(0.95),
              p99FrameMs: percentile(0.99),
              framesOver25ms: intervals.filter(value => value > 25).length,
              framesOver50ms: intervals.filter(value => value > 50).length,
              maxFrameMs: sorted.length ? Number(sorted[sorted.length - 1].toFixed(2)) : null
            };
            this.metrics.lastFrameMeasurement = result;
            resolve(result);
            return;
          }
          frameId = requestAnimationFrame(sample);
        };
        frameId = requestAnimationFrame(sample);
      });
    }

    getMetrics() {
      return { ...this.metrics, lastFrameMeasurement: this.metrics.lastFrameMeasurement && { ...this.metrics.lastFrameMeasurement } };
    }
  }

  window.OristeraMotion = new OristeraMotionEngine();
})();
