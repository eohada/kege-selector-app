import { test, expect, Page } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { runGeometryAudit } from './visual/geometry-audit';

const BASE_URL = process.env.BOOSTUDY_E2E_BASE_URL || 'http://127.0.0.1:5000';
const SCREENSHOT_DIR = path.resolve('artifacts/visual/oristera');
const VIEWPORTS = [
  { width: 1920, height: 1080, label: '1920x1080' },
  { width: 1600, height: 900, label: '1600x900' },
  { width: 1366, height: 768, label: '1366x768' },
  { width: 1024, height: 768, label: '1024x768' },
  { width: 768, height: 1024, label: '768x1024' },
  { width: 390, height: 844, label: '390x844' },
];

async function signIn(page: Page, username: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', 'demo123pass');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.pathname !== '/login', undefined, { timeout: 15_000 });
}

async function capture(page: Page, name: string, fullPage = false) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  await page.evaluate(async () => {
    await document.fonts.ready;
    const finiteAnimations = document.getAnimations({ subtree: true }).filter((animation) => {
      const timing = animation.effect?.getComputedTiming();
      return animation.playState === 'running' && timing?.iterations !== Infinity;
    });
    await Promise.all(finiteAnimations.map((animation) => animation.finished.catch(() => undefined)));
  });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, name), fullPage });
}

async function measureAnimationFrames(page: Page, label: string, requestedDurationMs = 1800) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  const before = await cdp.send('Performance.getMetrics');
  const metrics = await page.evaluate(async (durationMs) => {
    const intervals: number[] = [];
    const longTasks: number[] = [];
    let observer: PerformanceObserver | undefined;
    try {
      observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) longTasks.push(entry.duration);
      });
      observer.observe({ type: 'longtask', buffered: false });
    } catch {
      observer = undefined;
    }

    const startedAt = performance.now();
    await new Promise<void>((resolve) => {
      let previousFrame = 0;
      const sample = (time: number) => {
        if (previousFrame) intervals.push(time - previousFrame);
        previousFrame = time;
        if (time - startedAt >= durationMs) resolve();
        else requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    observer?.disconnect();
    const sorted = [...intervals].sort((a, b) => a - b);
    const percentile = (p: number) => sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * p))] ?? null;
    return {
      viewport: { width: innerWidth, height: innerHeight },
      visibility: document.visibilityState,
      durationMs: Math.round(performance.now() - startedAt),
      frameCount: intervals.length,
      frameIntervalMs: { p50: percentile(0.5), p95: percentile(0.95), p99: percentile(0.99), max: sorted[sorted.length - 1] ?? null },
      animationCount: document.getAnimations({ subtree: true }).filter((animation) => animation.playState === 'running').length,
      longTaskCount: longTasks.length,
      longTaskDurationMs: Math.round(longTasks.reduce((sum, duration) => sum + duration, 0) * 10) / 10,
      longTaskObserverSupported: Boolean(observer),
    };
  }, requestedDurationMs);
  const after = await cdp.send('Performance.getMetrics');
  await cdp.detach();
  const getMetric = (snapshot: typeof before, name: string) => snapshot.metrics.find((entry) => entry.name === name)?.value ?? 0;
  const metricDelta = (name: string) => getMetric(after, name) - getMetric(before, name);
  const roundMetric = (value: number) => Math.round(value * 1000) / 1000;
  const completeMetrics = {
    ...metrics,
    chromium: {
      taskDurationMs: roundMetric(metricDelta('TaskDuration') * 1000),
      scriptDurationMs: roundMetric(metricDelta('ScriptDuration') * 1000),
      layoutDurationMs: roundMetric(metricDelta('LayoutDuration') * 1000),
      layoutCount: Math.round(metricDelta('LayoutCount')),
      styleRecalcDurationMs: roundMetric(metricDelta('RecalcStyleDuration') * 1000),
      styleRecalcCount: Math.round(metricDelta('RecalcStyleCount')),
      heapUsedMb: roundMetric(getMetric(after, 'JSHeapUsedSize') / 1_000_000),
      nodes: Math.round(getMetric(after, 'Nodes')),
      paintDurationMs: roundMetric(metricDelta('PaintDuration') * 1000),
      paintCount: Math.round(metricDelta('PaintCount')),
    },
  };
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  fs.writeFileSync(path.join(SCREENSHOT_DIR, `performance-${label}.json`), JSON.stringify(completeMetrics, null, 2));
  return completeMetrics;
}

async function settleAtlasCamera(page: Page) {
  await page.waitForTimeout(900);
  await page.evaluate(async () => {
    const world = document.getElementById('ori-atlas-world');
    if (!world) return;
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const transitions = world.getAnimations().filter((animation) => {
      const timing = animation.effect?.getComputedTiming();
      return animation.playState === 'running' && timing?.iterations !== Infinity;
    });
    await Promise.all(transitions.map((animation) => animation.finished.catch(() => undefined)));
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  const geometry = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    content: Math.round(document.querySelector<HTMLElement>('.ori-field-page, .ori-genesis-root')?.getBoundingClientRect().width ?? document.documentElement.clientWidth),
    overflowing: Array.from(document.querySelectorAll<HTMLElement>('.ori-field-page *'))
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        className: typeof element.className === 'string' ? element.className : element.getAttribute('class') || '',
        left: Math.round(element.getBoundingClientRect().left),
        right: Math.round(element.getBoundingClientRect().right),
        width: Math.round(element.getBoundingClientRect().width),
        scrollWidth: element.scrollWidth,
      }))
      .filter((element) => element.right > window.innerWidth + 1 || element.left < -1)
      .slice(0, 8),
  }));
  expect(geometry.document, `document overflow: ${JSON.stringify(geometry)}`).toBeLessThanOrEqual(geometry.viewport + 1);
  expect(geometry.content, `content overflow: ${JSON.stringify(geometry)}`).toBeLessThanOrEqual(geometry.viewport + 1);
}

async function expectGeometryAudit(page: Page, route: string) {
  await page.evaluate(() => window.scrollTo(0, 0));
  const report = await runGeometryAudit(page, route);
  if (route === '/oristera/atlas' && report.viewport.width === 1600 && report.viewport.height === 900) {
    const warnings = report.findings.filter((finding) => finding.severity === 'WARN');
    console.log(`ATLAS VISUAL WARNINGS — ${JSON.stringify(warnings)}`);
  }
  const failures = report.findings.filter((finding) => finding.severity === 'FAIL');
  expect(failures, JSON.stringify(failures)).toEqual([]);
}

test.describe('ORISTERA learning studio and knowledge map', () => {
  test('Nexus and Atlas remain usable at desktop, laptop and mobile widths', async ({ page }) => {
    test.setTimeout(120_000);
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));

    await signIn(page, 'demo_student_1');
    await page.goto(`${BASE_URL}/oristera/nexus`);
    await expect(page.locator('.ori-genesis-root')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('#ori-genesis-stage')).toBeVisible();
    await expect(page.locator('.ori-genesis-quick')).toBeVisible();
    await expect(page.locator('#ori-genesis-assignments-title')).toHaveText('Активные задания');
    await expect(page.locator('#ori-genesis-path-title')).toHaveText('Путь развития');

    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await expectNoHorizontalOverflow(page);
      await expectGeometryAudit(page, '/oristera/nexus');
      await capture(page, `nexus-${viewport.label}.png`, viewport.width === 390);
    }

    await page.setViewportSize({ width: 1600, height: 900 });
    const idleFrames = await measureAnimationFrames(page, 'idle-1600x900');
    expect(idleFrames.animationCount).toBe(1);
    expect(idleFrames.frameIntervalMs.p50).toBeLessThanOrEqual(33.4);

    const backgroundMotion = await page.evaluate(() => {
      const originalHidden = Object.getOwnPropertyDescriptor(document, 'hidden');
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      document.dispatchEvent(new Event('visibilitychange'));
      const stage = document.getElementById('ori-main-stage');
      const paused = stage?.getAttribute('data-ori-motion') === 'paused';
      const runningAnimations = document.getAnimations({ subtree: true }).filter((animation) => animation.playState === 'running').length;
      if (originalHidden) Object.defineProperty(document, 'hidden', originalHidden);
      else delete (document as Document & { hidden?: boolean }).hidden;
      document.dispatchEvent(new Event('visibilitychange'));
      return { paused, runningAnimations, resumed: stage?.getAttribute('data-ori-motion') !== 'paused' };
    });
    expect(backgroundMotion.paused).toBe(true);
    expect(backgroundMotion.runningAnimations).toBe(0);
    expect(backgroundMotion.resumed).toBe(true);

    const atlasOrb = await page.evaluate(() => {
      const rect = document.querySelector('.ori-genesis-orb.orb-atlas')!.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });
    await page.mouse.move(atlasOrb.x, atlasOrb.y);
    const hoverFrames = await measureAnimationFrames(page, 'nexus-atlas-hover-1600x900');
    console.log(`NEXUS FRAME QA — idle p50/p95/p99 ${idleFrames.frameIntervalMs.p50}/${idleFrames.frameIntervalMs.p95}/${idleFrames.frameIntervalMs.p99} ms; Atlas hover ${hoverFrames.frameIntervalMs.p50}/${hoverFrames.frameIntervalMs.p95}/${hoverFrames.frameIntervalMs.p99} ms`);

    await page.emulateMedia({ reducedMotion: 'reduce' });
    const reducedMotion = await page.evaluate(() => ({
      matches: matchMedia('(prefers-reduced-motion: reduce)').matches,
      ambientAnimationDurationMs: (() => {
        const value = getComputedStyle(document.querySelector('.ori-genesis-core-globe')!, '::before').animationDuration;
        const amount = Number.parseFloat(value);
        return value.endsWith('ms') ? amount : amount * 1000;
      })(),
      ambientAnimationIterations: getComputedStyle(document.querySelector('.ori-genesis-core-globe')!, '::before').animationIterationCount,
    }));
    expect(reducedMotion.matches).toBe(true);
    expect(reducedMotion.ambientAnimationDurationMs).toBeLessThanOrEqual(0.02);
    expect(reducedMotion.ambientAnimationIterations).toBe('1');
    const reducedFrames = await measureAnimationFrames(page, 'reduced-motion-1600x900');
    console.log(`NEXUS FRAME QA — reduced motion p50/p95/p99 ${reducedFrames.frameIntervalMs.p50}/${reducedFrames.frameIntervalMs.p95}/${reducedFrames.frameIntervalMs.p99} ms`);
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.mouse.move(5, 5);

    const longOpenFrames = await measureAnimationFrames(page, 'long-open-32000-1600x900', 32_000);
    expect(longOpenFrames.animationCount).toBe(1);
    expect(longOpenFrames.frameIntervalMs.p50).toBeLessThanOrEqual(33.4);
    console.log(`NEXUS LONG OPEN — ${longOpenFrames.durationMs} ms; p50/p95/p99 ${longOpenFrames.frameIntervalMs.p50}/${longOpenFrames.frameIntervalMs.p95}/${longOpenFrames.frameIntervalMs.p99} ms; long tasks ${longOpenFrames.longTaskCount}`);

    const navigationProbe = await page.evaluate(() => {
      const docToken = `${Date.now()}-${Math.random()}`;
      const probe = { docToken, portalEntered: false };
      (window as Window & { __oristeraNavigationProbe?: typeof probe }).__oristeraNavigationProbe = probe;
      window.addEventListener('ori:space-entered', () => { probe.portalEntered = true; });
      return { docToken, controllerAvailable: Boolean((window as Window & { OristeraMotion?: unknown }).OristeraMotion) };
    });
    const navigationStartedAt = Date.now();
    await page.locator('.ori-genesis-orb.orb-atlas').click();
    await expect(page.locator('.ori-atlas-tabs')).toBeVisible();
    await expect(page.locator('#ori-atlas-world')).toBeVisible();
    await expect(page.locator('#ori-atlas-svg')).toBeVisible();
    await page.waitForFunction(() => {
      const controller = (window as Window & {
        OristeraMotion?: { getMetrics: () => { transitionCount: number } };
      }).OristeraMotion;
      return (controller?.getMetrics().transitionCount ?? 0) > 0;
    });
    const navigationMetrics = await page.evaluate(({ startedAt, docToken }) => {
      const metrics = (window as Window & {
        OristeraMotion?: {
          getMetrics: () => {
            transitionCount: number;
            lastDurationMs: number;
            lastFetchDurationMs: number;
            lastTransitionDurationMs: number;
          };
        };
      }).OristeraMotion?.getMetrics();
      const probe = (window as Window & {
        __oristeraNavigationProbe?: { docToken: string; portalEntered: boolean };
      }).__oristeraNavigationProbe;
      return {
        pathname: window.location.pathname,
        browserWallDurationMs: Date.now() - startedAt,
        sameDocument: probe?.docToken === docToken,
        probeAvailable: Boolean(probe),
        portalEntered: probe?.portalEntered ?? false,
        controllerAvailable: Boolean((window as Window & { OristeraMotion?: unknown }).OristeraMotion),
        transitionCount: metrics?.transitionCount ?? 0,
        lastDurationMs: metrics?.lastDurationMs ?? 0,
        lastFetchDurationMs: metrics?.lastFetchDurationMs ?? 0,
        lastTransitionDurationMs: metrics?.lastTransitionDurationMs ?? 0,
      };
    }, { startedAt: navigationStartedAt, docToken: navigationProbe.docToken });
    expect(navigationMetrics.pathname).toBe('/oristera/atlas');
    expect(navigationMetrics.sameDocument).toBe(true);
    expect(navigationMetrics.portalEntered).toBe(true);
    expect(navigationMetrics.transitionCount).toBeGreaterThan(0);
    console.log(`NEXUS → ATLAS — ${navigationMetrics.lastDurationMs} ms total (${navigationMetrics.lastFetchDurationMs} ms fetch, ${navigationMetrics.lastTransitionDurationMs} ms view transition; ${navigationMetrics.browserWallDurationMs} ms browser wall time)`);
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    fs.writeFileSync(
      path.join(SCREENSHOT_DIR, 'navigation-nexus-to-atlas-1600x900.json'),
      JSON.stringify(navigationMetrics, null, 2),
    );
    const atlasBackgroundMotion = await page.evaluate(() => {
      const originalHidden = Object.getOwnPropertyDescriptor(document, 'hidden');
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      document.dispatchEvent(new Event('visibilitychange'));
      const root = document.getElementById('ori-atlas-universe');
      const paused = root?.dataset.motionPaused === 'true';
      const animationState = getComputedStyle(document.querySelector('.atlas-domain-plate')!).animationPlayState;
      if (originalHidden) Object.defineProperty(document, 'hidden', originalHidden);
      else delete (document as Document & { hidden?: boolean }).hidden;
      document.dispatchEvent(new Event('visibilitychange'));
      return { paused, animationState, resumed: root?.dataset.motionPaused !== 'true' };
    });
    expect(atlasBackgroundMotion.paused).toBe(true);
    expect(atlasBackgroundMotion.animationState).toBe('paused');
    expect(atlasBackgroundMotion.resumed).toBe(true);
    const atlasIdleFrames = await measureAnimationFrames(page, 'atlas-idle-1600x900');
    await page.locator('.atlas-domain-trigger').first().hover();
    const atlasHoverFrames = await measureAnimationFrames(page, 'atlas-hover-1600x900');
    console.log(`ATLAS FRAME QA — idle p50/p95/p99 ${atlasIdleFrames.frameIntervalMs.p50}/${atlasIdleFrames.frameIntervalMs.p95}/${atlasIdleFrames.frameIntervalMs.p99} ms; hover ${atlasHoverFrames.frameIntervalMs.p50}/${atlasHoverFrames.frameIntervalMs.p95}/${atlasHoverFrames.frameIntervalMs.p99} ms; long tasks ${atlasIdleFrames.longTaskCount}/${atlasHoverFrames.longTaskCount}`);
    await page.mouse.move(5, 5);
    const areaCount = await page.locator('.ori-constellation-cluster').count();
    const tabCount = await page.locator('.ori-atlas-tab').count();
    expect(areaCount).toBeGreaterThan(0);
    expect(tabCount).toBe(areaCount);
    await expect(page.locator('#ori-atlas-scale')).toHaveText('100%');
    await expect(page.locator('.ori-atlas-field')).not.toContainText(/Verified Mastery/i);

    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await settleAtlasCamera(page);
      await expectNoHorizontalOverflow(page);
      await expectGeometryAudit(page, '/oristera/atlas');
      await capture(page, `atlas-${viewport.label}.png`, viewport.width <= 768);
    }

    await page.setViewportSize({ width: 1600, height: 900 });
    await settleAtlasCamera(page);
    const firstArea = page.locator('.ori-atlas-tab').first();
    await firstArea.click();
    await settleAtlasCamera(page);
    await expect(page.locator('#ori-cluster-inspector')).toBeVisible();
    await expect(page.locator('#ori-atlas-reset-btn')).toBeVisible();
    await expect(page.locator('.atlas-domain.is-active')).toBeVisible();
    const immersionFrames = await measureAnimationFrames(page, 'atlas-immersion-1600x900');
    console.log(`ATLAS IMMERSION CAMERA — p50/p95/p99 ${immersionFrames.frameIntervalMs.p50}/${immersionFrames.frameIntervalMs.p95}/${immersionFrames.frameIntervalMs.p99} ms; long tasks ${immersionFrames.longTaskCount}`);
    await capture(page, 'atlas-domain-immersion-1600x900.png');
    const firstTopic = page.locator('.atlas-domain.is-active .ori-star-node').first();
    await firstTopic.click();
    await expect(page.locator('#ori-skill-inspector')).toBeVisible();
    await expect(page.locator('#ori-insp-title')).not.toBeEmpty();
    await expect(page.locator('#ori-insp-evidence-count')).toHaveText(/^\d+$/);
    await expect(page.locator('#ori-skill-inspector')).not.toContainText(/\b\d+%|Verified Mastery/i);
    await capture(page, 'atlas-topic-detail-1600x900.png');

    const restoredTopic = await page.locator('#ori-insp-title').innerText();
    await expect(page).toHaveURL(/atlas_area=.*atlas_topic=/);
    await page.reload();
    await expect(page.locator('#ori-skill-inspector')).toBeVisible();
    await expect(page.locator('#ori-insp-title')).toHaveText(restoredTopic);
    await page.locator('#ori-insp-practice-link').click();
    await page.waitForURL(/\/oristera\/practice\?/);
    await page.goBack();
    await page.waitForURL(/\/oristera\/atlas\?atlas_area=.*atlas_topic=/);
    await expect(page.locator('#ori-skill-inspector')).toBeVisible();
    await expect(page.locator('#ori-insp-title')).toHaveText(restoredTopic);

    await page.keyboard.press('Escape');
    await expect(page.locator('#ori-cluster-inspector')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#ori-atlas-overview-card')).toBeVisible();
    await expect(page.locator('#ori-atlas-reset-btn')).toBeHidden();

    await page.keyboard.press('/');
    await expect(page.locator('#ori-atlas-search')).toBeFocused();
    await page.locator('#ori-atlas-search').fill('Рекурсивные функции');
    const searchResult = page.locator('.atlas-search-result').first();
    await expect(searchResult).toBeVisible();
    await searchResult.click();
    await expect(page.locator('#ori-skill-inspector')).toBeVisible();
    await expect(page.locator('#ori-insp-title')).toHaveText('Рекурсивные функции');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');

    await page.keyboard.press('=');
    await expect(page.locator('#ori-atlas-scale')).not.toHaveText('100%');
    await page.keyboard.press('-');
    await expect(page.locator('#ori-atlas-scale')).toHaveText('100%');
    await page.keyboard.press('5');
    await expect(page.locator('.atlas-domain.is-active')).toHaveAttribute('data-cid', 'c-olympiad');
    await page.keyboard.press('Escape');
    await expect(page.locator('#ori-atlas-overview-card')).toBeVisible();

    const panStart = await page.locator('#ori-atlas-viewport').evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return { x: rect.left + rect.width * 0.05, y: rect.top + rect.height * 0.08 };
    });
    const transformBeforePan = await page.locator('#ori-atlas-world').evaluate((element) => getComputedStyle(element).transform);
    await page.mouse.move(panStart.x, panStart.y);
    await page.mouse.down();
    await page.mouse.move(panStart.x + 70, panStart.y + 24, { steps: 5 });
    await page.mouse.up();
    await settleAtlasCamera(page);
    const transformAfterPan = await page.locator('#ori-atlas-world').evaluate((element) => getComputedStyle(element).transform);
    expect(transformAfterPan).not.toBe(transformBeforePan);
    await page.keyboard.press('0');
    await expect(page.locator('#ori-atlas-scale')).toHaveText('100%');

    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.ori-atlas-tab').nth(1).click();
    expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
    await expect(page.locator('#ori-cluster-inspector')).toBeVisible();
    await expect(page.locator('#ori-atlas-svg')).toBeVisible();
    await capture(page, 'atlas-reduced-motion-390x844.png', true);
    await page.locator('.atlas-domain.is-active .ori-star-node').first().click();
    await expect(page.locator('#ori-skill-inspector')).toBeVisible();
    await expect(page.locator('#ori-insp-title')).toBeVisible();
    await expect(page.locator('#ori-insp-evidence-count')).toHaveText(/^\d+$/);
    await page.locator('#ori-skill-inspector').scrollIntoViewIfNeeded();
    await capture(page, 'atlas-mobile-topic-390x844.png');
    await page.emulateMedia({ reducedMotion: 'no-preference' });

    expect(pageErrors).toEqual([]);
  });

test('Teacher Studio keeps the shared navigation', async ({ page }) => {
    test.setTimeout(90_000);
    await signIn(page, 'qa_pool_teacher_1');
    await page.goto(`${BASE_URL}/oristera/nexus`);
    await expect(page.locator('.ori-field-title')).toBeVisible();
    await expect(page.locator('.ori-compass-label', { hasText: 'Обзор' })).toBeVisible();
    await expect(page.locator('.ori-teacher-work-grid')).toBeVisible();
    await expect(page.locator('.ori-teacher-student-list')).toBeVisible();
    await expectGeometryAudit(page, '/oristera/teacher');
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await expectNoHorizontalOverflow(page);
      await expectGeometryAudit(page, '/oristera/teacher');
      await capture(page, `teacher-studio-${viewport.label}.png`, viewport.width === 390);
    }
  });

  test('Parent center keeps the shared navigation and Classic return', async ({ page }) => {
    test.setTimeout(90_000);
    await signIn(page, 'demo_parent_1');
    await page.goto(`${BASE_URL}/oristera/nexus`);
    await expect(page.locator('.ori-field-title')).toBeVisible();
    await expect(page.locator('.ori-compass-label', { hasText: 'Родитель' })).toBeVisible();
    await expect(page.locator('.ori-parent-children')).toBeVisible();
    await expect(page.locator('.ori-parent-children')).not.toContainText(/80\s*б\.|65\s*б\.|цель на год/i);
    await expectGeometryAudit(page, '/oristera/parent');
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await expectNoHorizontalOverflow(page);
      await expectGeometryAudit(page, '/oristera/parent');
      await capture(page, `parent-center-${viewport.label}.png`, viewport.width === 390);
    }

    await page.locator('#ori-mode-toggle-btn').click({ noWaitAfter: true });
    await page.waitForFunction(() => location.pathname === '/dashboard', undefined, { timeout: 15_000 });
    expect(page.url()).toContain('/dashboard');
  });

  test('Practice runs code and lessons link to real preparation details', async ({ page }) => {
    test.setTimeout(120_000);
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));

    await signIn(page, 'demo_student_1');
    await page.goto(`${BASE_URL}/oristera/practice`);
    await expect(page.locator('.ori-practice-code-panel')).toBeVisible();
    await expect(page.locator('#ori-code-editor')).toBeVisible();
    await page.locator('#ori-code-editor').fill('print("ORISTERA QA")');
    await page.locator('#ori-run-code-btn').click();
    await expect(page.locator('#ori-console-output')).toContainText('ORISTERA QA', { timeout: 20_000 });
    await expectGeometryAudit(page, '/oristera/practice');
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await expectNoHorizontalOverflow(page);
      await expectGeometryAudit(page, '/oristera/practice');
      await capture(page, `practice-${viewport.label}.png`, viewport.width === 390);
    }

    await page.setViewportSize({ width: 1600, height: 900 });
    await page.getByRole('link', { name: 'Уроки', exact: true }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { level: 1, name: 'Время для занятий' })).toBeVisible();
    await expect(page.locator('.ori-schedule-list, .ori-field-empty').first()).toBeVisible();
    await expectGeometryAudit(page, '/oristera/lessons');
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await expectNoHorizontalOverflow(page);
      await expectGeometryAudit(page, '/oristera/lessons');
      await capture(page, `lessons-${viewport.label}.png`, viewport.width === 390);
    }
    await page.setViewportSize({ width: 1600, height: 900 });
    const prepLink = page.locator('a[href*="lesson_prep"], a[href*="/oristera/lesson/"]').first();
    if (await prepLink.count()) {
      await prepLink.click();
      await expect(page.locator('#ori-prep-portal')).toBeVisible();
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await expect(page.locator('#ori-enter-room-btn')).toHaveAttribute('href', /from=oristera/);
      await expectGeometryAudit(page, '/oristera/lesson-prep');
      for (const viewport of VIEWPORTS) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await expectNoHorizontalOverflow(page);
        await expectGeometryAudit(page, '/oristera/lesson-prep');
        await capture(page, `lesson-preparation-${viewport.label}.png`, viewport.width === 390);
      }
    }

    expect(pageErrors).toEqual([]);
  });
});
