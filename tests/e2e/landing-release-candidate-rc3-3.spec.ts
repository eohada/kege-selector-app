import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { runGeometryAudit } from './visual/geometry-audit';

const ROUTE = '/static/landing-release-candidate-rc3-3/index.html';
const PANEL = '[data-rc3-tour-panel]';
const PACKAGE = path.resolve('output/landing-release-audit/RC3.3');
const EVIDENCE = path.join(PACKAGE, 'videos');
const SCREENSHOTS = path.join(PACKAGE, 'screenshots');
test.beforeEach(() => {
  fs.mkdirSync(path.join(PACKAGE, 'diagnostics'), { recursive: true });
  fs.mkdirSync(path.join(SCREENSHOTS, 'checkpoints'), { recursive: true });
  fs.mkdirSync(path.join(SCREENSHOTS, 'panel'), { recursive: true });
  fs.mkdirSync(SCREENSHOTS, { recursive: true });
  fs.mkdirSync(EVIDENCE, { recursive: true });
});

async function openRC33(page: Page, viewport = { width: 1920, height: 1080 }) {
  await page.setViewportSize(viewport);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const response = await page.goto(ROUTE, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  expect(response?.status()).toBe(200);
  expect(await page.title()).toBe('BooStudy — Release Candidate 3.3');
  return errors;
}

async function copyVideo(page: Page, target: string) {
  const video = page.video();
  expect(video, 'Playwright recording is enabled for the acceptance run').not.toBeNull();
  await page.close();
  fs.mkdirSync(path.dirname(target), { recursive: true });
  await fs.promises.copyFile(await video!.path(), target);
}

async function chooseMode(page: Page, mode: 'auto' | 'manual') {
  if (!(await page.locator('#rc3-welcome').isVisible())) await page.locator('[data-rc3-reopen]').click();
  await page.locator(`[data-rc3-choice="${mode}"]`).click();
}

async function waitForPhase(page: Page, expected: string, timeout = 20_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const state = await page.evaluate(() => {
      const phase = document.querySelector('[data-rc3-tour-panel]')?.getAttribute('data-phase') || '';
      const report = (window as any).BooStudyGuidedTour?.visualDiagnostics?.at(-1);
      return { phase, diagnostic: report ? { episodeId: report.episodeId, surface: report.surface, copy: report.copy } : null };
    });
    if (state.phase === expected) return;
    if (state.phase === 'visual-error') throw new Error(`Tour visibility failure: ${JSON.stringify(state.diagnostic)}`);
    await page.waitForTimeout(100);
  }
  throw new Error(`Tour did not reach ${expected} within ${timeout}ms.`);
}

async function reachFounderWithWheel(page: Page) {
  const title = page.locator('#s42-founder-title');
  for (let i = 0; i < 90; i += 1) {
    const geometry = await title.evaluate(node => {
      const rect = node.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, height: rect.height, viewportHeight: innerHeight };
    });
    if (geometry.height > 0 && geometry.top < geometry.viewportHeight * 0.82 && geometry.bottom > 0) return;
    await page.mouse.wheel(0, geometry.top > geometry.viewportHeight * 0.82 ? Math.min(1000, Math.max(500, geometry.top - geometry.viewportHeight * 0.65)) : -600);
    await page.waitForTimeout(50);
  }
  throw new Error('Founder title did not enter the viewport during manual wheel scroll.');
}

async function waitForTourComplete(page: Page, onCheckpoint?: (episodeId: string, index: string, phase: string) => Promise<void>) {
  const captured = new Set<string>();
  const startedAt = Date.now();
  while (Date.now() - startedAt < 360_000) {
    const state = await page.locator(PANEL).evaluate(panel => ({
      state: panel.getAttribute('data-state'),
      phase: panel.getAttribute('data-phase'),
      episodeId: panel.getAttribute('data-episode-id') || '',
      index: panel.getAttribute('data-index') || '',
      visual: panel.getAttribute('data-visual-status')
    }));
    if (state.state === 'visual-error') {
      const diagnostic = await page.evaluate(() => (window as any).BooStudyGuidedTour?.visualDiagnostics?.at(-1));
      throw new Error(`Auto Tour stopped at ${state.episodeId}: ${JSON.stringify(diagnostic)}`);
    }
    if ((['read', 'watch', 'understand', 'founder'].includes(state.phase)) && state.visual === 'passed') {
      const kind = await page.evaluate((id) => (window as any).BooStudyGuidedTour.manifest.find((item: any) => item.id === id)?.kind, state.episodeId);
      const expectedPhase = kind === 'watch' ? 'watch' : kind === 'understand' ? 'understand' : kind === 'founder' ? 'founder' : 'read';
      const key = state.episodeId;
      if (!captured.has(key)) {
        if (state.phase !== expectedPhase) {
          await page.waitForTimeout(80);
          continue;
        }
        captured.add(key);
        await onCheckpoint?.(state.episodeId, state.index, state.phase);
      }
    }
    if (state.state === 'auto-complete') return captured.size;
    await page.waitForTimeout(120);
  }
  throw new Error('Auto Tour did not complete within six minutes.');
}

test('RC3.3 desktop 1× semantic tour completes with readable checkpoints', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Full desktop run records at 1920×1080.');
  test.setTimeout(420_000);
  fs.mkdirSync(path.join(SCREENSHOTS, 'checkpoints'), { recursive: true });
  fs.mkdirSync(path.join(SCREENSHOTS, 'keyframes'), { recursive: true });
  await page.addInitScript(() => {
    (window as any).__rc33ScrollSamples = [];
    let sampledAt = 0;
    window.addEventListener('scroll', () => {
      if (performance.now() - sampledAt < 80) return;
      sampledAt = performance.now();
      (window as any).__rc33ScrollSamples.push({ t: Math.round(sampledAt), y: Math.round(scrollY) });
    }, { passive: true });
  });
  const errors = await openRC33(page);
  await chooseMode(page, 'auto');
  await expect(page.locator(PANEL)).toBeVisible();
  await page.locator('[data-rc3-speed-trigger]').click();
  await page.locator('[data-rc3-speed-option="1"]').click();

  const manifest = await page.evaluate(() => (window as any).BooStudyGuidedTour.manifest);
  const keyframeCount = await page.evaluate(() => (window as any).BooStudyGuidedTour.keyframeCount);
  expect(manifest).toHaveLength(26);
  expect(keyframeCount).toBe(24);
  expect(manifest.filter((item: any) => item.kind === 'pass-through')).toHaveLength(2);
  const start = Date.now();
  const capturedFrames = await waitForTourComplete(page, async (episodeId, index, phase) => {
    await page.screenshot({ path: path.join(SCREENSHOTS, 'checkpoints', `${String(Number(index) + 1).padStart(2, '0')}-${episodeId}-${phase}.png`) });
  });
  const wallDurationMs = Date.now() - start;
  const diagnostics = await page.evaluate(() => ({
    tour: (window as any).__rc33TourDiagnostics,
    reports: (window as any).BooStudyGuidedTour.visualReports,
    visualDiagnostics: (window as any).BooStudyGuidedTour.visualDiagnostics,
    scrollSamples: (window as any).__rc33ScrollSamples,
    errors: performance.getEntriesByType('resource').filter((entry: any) => entry.responseStatus >= 400).map((entry: any) => entry.name)
  }));
  expect(capturedFrames).toBe(24);
  expect(diagnostics.reports).toHaveLength(24);
  expect(diagnostics.reports.every((report: any) => report.pass)).toBeTruthy();
  expect(errors).toEqual([]);
  await page.screenshot({ path: path.join(SCREENSHOTS, 'keyframes', 'tour-complete-founder.png') });
  fs.mkdirSync(path.join(PACKAGE, 'diagnostics'), { recursive: true });
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'tour-timeline.json'), JSON.stringify({ wallDurationMs, ...diagnostics.tour }, null, 2));
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'visibility-audit.json'), JSON.stringify({ reports: diagnostics.reports, diagnostics: diagnostics.visualDiagnostics, errors, failedResources: diagnostics.errors }, null, 2));
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'performance-summary.json'), JSON.stringify({ viewport: { width: 1920, height: 1080 }, wallDurationMs, scrollSamples: diagnostics.scrollSamples.length, failedResources: diagnostics.errors }, null, 2));
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'checkpoint-manifest.json'), JSON.stringify({ keyframeCount, passThroughCount: manifest.filter((item: any) => item.kind === 'pass-through').length, items: manifest }, null, 2));
  const actualDurationMs = diagnostics.tour.durationMs || wallDurationMs;
  const preferredRangeMs = { min: 180_000, max: 270_000 };
  const withinPreferredRange = actualDurationMs >= preferredRangeMs.min && actualDurationMs <= preferredRangeMs.max;
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'pacing-timeline.json'), JSON.stringify({ actualMs: actualDurationMs, wallDurationMs, preferredRangeMs, withinPreferredRange, phases: diagnostics.tour.events.filter((event: any) => /^(segment|travel|read|watch|understand|founder|tour-complete)/.test(event.event)), passThroughCount: manifest.filter((item: any) => item.kind === 'pass-through').length, keyframeCount, temporalDeadZoneCandidates: diagnostics.tour.events.filter((event: any) => event.event === 'temporal-dead-zone-candidate') }, null, 2));
  expect(wallDurationMs, 'tour has measured reading time and should exceed 2.5 minutes').toBeGreaterThanOrEqual(150_000);
  await copyVideo(page, path.join(EVIDENCE, 'full-auto-desktop.webm'));
});

test('RC3.3 mobile 1× tour completes at 390×844', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Mobile run uses the 390×844 project.');
  test.setTimeout(420_000);
  fs.mkdirSync(path.join(SCREENSHOTS, 'responsive'), { recursive: true });
  const errors = await openRC33(page, { width: 390, height: 844 });
  await chooseMode(page, 'auto');
  await page.locator('[data-rc3-speed-trigger]').click();
  await page.locator('[data-rc3-speed-option="1"]').click();
  await expect(page.locator(PANEL)).toBeVisible();
  const durationStarted = Date.now();
  const keyframes = await waitForTourComplete(page, async (episodeId, index) => {
    if (episodeId === 'founder-story' || episodeId === 'profile-complete' || episodeId === 'schedule-day') {
      await page.screenshot({ path: path.join(SCREENSHOTS, 'responsive', `${episodeId}-${index}.png`) });
    }
  });
  const durationMs = Date.now() - durationStarted;
  const diagnostics = await page.evaluate(() => ({
    reports: (window as any).BooStudyGuidedTour.visualReports,
    route: (window as any).__rc33TourDiagnostics,
    founderText: [...document.querySelectorAll('.s42-typewriter-output')].map(node => node.textContent),
    founderViewport: (() => {
      const actions = document.querySelector('[data-s42-reveal-actions]')!.getBoundingClientRect();
      const panel = document.querySelector('[data-rc3-tour-panel]')!.getBoundingClientRect();
      return { actionsTop: Math.round(actions.top), actionsBottom: Math.round(actions.bottom), panelTop: Math.round(panel.top), scrollY: Math.round(scrollY) };
    })()
  }));
  expect(keyframes).toBe(24);
  expect(diagnostics.reports).toHaveLength(24);
  expect(diagnostics.reports.every((report: any) => report.pass)).toBeTruthy();
  expect(diagnostics.founderText.at(-1)).toContain('Напиши мне напрямую');
  expect(diagnostics.founderViewport.actionsTop).toBeGreaterThanOrEqual(0);
  expect(diagnostics.founderViewport.actionsBottom).toBeLessThanOrEqual(diagnostics.founderViewport.panelTop);
  expect(errors).toEqual([]);
  await page.screenshot({ path: path.join(SCREENSHOTS, 'responsive', 'mobile-tour-complete.png') });
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'mobile-tour.json'), JSON.stringify({ viewport: { width: 390, height: 844 }, durationMs, reports: diagnostics.reports, timeline: diagnostics.route }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'full-auto-mobile.webm'));
});

test('Founder manual typewriter records each stage and keeps text accessible', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Founder typewriter evidence records at 1920×1080.');
  test.setTimeout(120_000);
  fs.mkdirSync(path.join(SCREENSHOTS, 'keyframes'), { recursive: true });
  const errors = await openRC33(page);
  await chooseMode(page, 'manual');
  const startedAt = Date.now();
  await reachFounderWithWheel(page);
  await expect(page.locator('[data-s42-founder]')).toHaveAttribute('data-reveal-state', 'revealing', { timeout: 7000 });
  const typewriterStartedAt = Date.now();
  const samples: Array<Record<string, unknown>> = [];
  const capture = async (name: string) => {
    const state = await page.evaluate(() => ({
      phase: document.querySelector('[data-s42-founder]')?.getAttribute('data-phase'),
      state: document.querySelector('[data-s42-founder]')?.getAttribute('data-reveal-state'),
      outputs: [...document.querySelectorAll('.s42-typewriter-output')].map(node => node.textContent || ''),
      accessible: [...document.querySelectorAll('.s42-typewriter-accessible')].map(node => node.textContent || ''),
      cursors: [...document.querySelectorAll('.s42-typewriter-cursor')].map(node => !node.hasAttribute('hidden')),
      ctaVisible: [...document.querySelectorAll('[data-s42-founder] .s42-founder-actions a')].every(node => getComputedStyle(node).opacity === '1')
    }));
    samples.push({ name, ...state });
    await page.screenshot({ path: path.join(SCREENSHOTS, 'keyframes', `founder-${name}.png`) });
  };
  await expect.poll(() => page.locator('.s42-typewriter-output').first().textContent()).not.toBe('');
  await page.waitForTimeout(1100);
  await capture('typing-start');
  await expect.poll(async () => (await page.locator('.s42-typewriter-output').first().textContent() || '').length).toBeGreaterThan(60);
  await capture('typing-first-paragraph');
  await expect(page.locator('[data-typewriter-state="complete"]')).toHaveCount(2, { timeout: 25_000 });
  await capture('story-complete');
  await expect.poll(() => page.locator('#s42-invitation-title').locator('.s42-typewriter-output').textContent()).not.toBe('');
  await capture('invitation-start');
  await expect(page.locator('[data-s42-founder]')).toHaveAttribute('data-reveal-state', 'complete', { timeout: 35_000 });
  await expect(page.locator('[data-s42-founder] a[href="https://t.me/eohada"]')).toBeVisible();
  await capture('invitation-and-cta');
  const result = await page.evaluate(() => ({
    totalText: document.querySelector('[data-s42-founder]')?.textContent,
    completeBlocks: document.querySelectorAll('[data-typewriter-state="complete"]').length,
    fullAccessibleBlocks: document.querySelectorAll('.s42-typewriter-accessible').length,
    fullOutputBlocks: [...document.querySelectorAll('.s42-typewriter-output')].every((node, index) => node.textContent === document.querySelectorAll('.s42-typewriter-accessible')[index].textContent),
    reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches
  }));
  expect(result.completeBlocks).toBe(4);
  expect(result.fullAccessibleBlocks).toBe(4);
  expect(result.fullOutputBlocks).toBeTruthy();
  expect(result.totalText).toContain('Давай обсудим твоё обучение.');
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'founder-typewriter.json'), JSON.stringify({ samples, result, durationMs: Date.now() - typewriterStartedAt, errors }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'founder-clean-reveal.webm'));
});

test('Founder typewriter Pause and Resume keeps the exact character position', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Pause evidence records at 1920×1080.');
  test.setTimeout(110_000);
  fs.mkdirSync(path.join(SCREENSHOTS, 'keyframes'), { recursive: true });
  const errors = await openRC33(page);
  await chooseMode(page, 'auto');
  await page.locator('[data-rc3-speed-trigger]').click();
  await page.locator('[data-rc3-speed-option="2"]').click();
  await page.locator('[data-rc3-progress]').fill('990');
  await expect(page.locator(PANEL)).toHaveAttribute('data-episode-id', 'founder-story', { timeout: 10_000 });
  await expect(page.locator(PANEL)).toHaveAttribute('data-phase', 'founder', { timeout: 55_000 });
  await expect.poll(async () => (await page.locator('.s42-typewriter-output').first().textContent() || '').length).toBeGreaterThan(24);
  const pauseButton = page.locator('[data-rc3-play]');
  await pauseButton.click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-paused');
  const before = await page.locator('.s42-typewriter-output').first().textContent();
  await page.screenshot({ path: path.join(SCREENSHOTS, 'keyframes', 'founder-paused-mid-sentence.png') });
  await page.waitForTimeout(650);
  const whilePaused = await page.locator('.s42-typewriter-output').first().textContent();
  expect(whilePaused).toBe(before);
  await pauseButton.click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-playing');
  await expect.poll(() => page.locator('.s42-typewriter-output').first().textContent()).not.toBe(before);
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-complete', { timeout: 40_000 });
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'pause-resume.json'), JSON.stringify({ before, whilePaused, resumed: await page.locator('.s42-typewriter-output').first().textContent(), passed: before === whilePaused && errors.length === 0 }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'pause-resume.webm'));
});

test('Compact controller changes speed, pauses, seeks and genuinely collapses', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Controls evidence records at 1920×1080.');
  test.setTimeout(60_000);
  const errors = await openRC33(page);
  await chooseMode(page, 'auto');
  await expect(page.locator(PANEL)).toBeVisible();
  const speed = page.locator('[data-rc3-speed-trigger]');
  await speed.click();
  await page.locator('[data-rc3-speed-option="1.5"]').click();
  await expect(speed).toHaveText('1,5×');
  await page.locator('[data-rc3-play]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-paused');
  await page.locator('[data-rc3-play]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-playing');
  await page.locator('[data-rc3-next]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-index', '1');
  await page.locator('[data-rc3-prev]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-index', '0');
  const expanded = await page.locator(PANEL).evaluate(node => {
    const { width, height } = node.getBoundingClientRect();
    return { width, height, area: width * height };
  });
  await page.locator('[data-rc3-collapse]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-collapsed', 'true');
  await expect(page.locator(PANEL)).toHaveCSS('height', '54px');
  await page.waitForTimeout(320);
  const collapsed = await page.locator(PANEL).evaluate(node => {
    const { width, height } = node.getBoundingClientRect();
    return { width, height, area: width * height };
  });
  expect(collapsed.area / expanded.area).toBeLessThan(0.35);
  expect(collapsed.width).toBeLessThanOrEqual(180);
  await page.screenshot({ path: path.join(SCREENSHOTS, 'panel', 'controller-collapsed.png') });
  await page.locator('[data-rc3-collapse]').click();
  await page.locator('[data-rc3-more-toggle]').click();
  await page.locator('[data-rc3-restart]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-index', '0');
  await page.screenshot({ path: path.join(SCREENSHOTS, 'panel', 'controller-expanded.png') });
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'panel-geometry.json'), JSON.stringify({ expanded, collapsed, areaRatio: collapsed.area / expanded.area, speed: await speed.textContent(), state: await page.locator(PANEL).getAttribute('data-state'), index: await page.locator(PANEL).getAttribute('data-index'), passed: true }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'panel-collapse.webm'));
});

test('Semantic checkpoints expose copy and product phases across five chapters', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Checkpoint pacing evidence records at 1920×1080.');
  test.setTimeout(260_000);
  const errors = await openRC33(page);
  await chooseMode(page, 'auto');
  const targetIds = ['os-code-watch', 'dashboard-spotlight', 'schedule-day-watch', 'theory-notes-watch', 'profile-achievements-watch'];
  const samples: Array<Record<string, unknown>> = [];
  for (const id of targetIds) {
    const index = await page.evaluate((checkpointId) => (window as any).BooStudyGuidedTour.manifest.findIndex((item: any) => item.id === checkpointId), id);
    const total = await page.evaluate(() => (window as any).BooStudyGuidedTour.manifest.length);
    const slider = page.locator('[data-rc3-progress]');
    const box = await slider.boundingBox();
    if (!box) throw new Error('Tour progress slider is not visible.');
    const rangeRatio = (index + 0.5) / total;
    const thumbInset = Math.min(8, box.width * 0.04);
    await page.mouse.click(box.x + thumbInset + (box.width - thumbInset * 2) * rangeRatio, box.y + box.height / 2);
    await expect(page.locator(PANEL)).toHaveAttribute('data-episode-id', id, { timeout: 45_000 });
    await waitForPhase(page, 'read', 50_000);
    const readEvent = await page.evaluate((checkpointId) => (window as any).__rc33TourDiagnostics.events.find((item: any) => item.event === 'read-start' && item.episodeId === checkpointId), id);
    expect(readEvent?.words).toBeGreaterThan(0);
    expect(readEvent?.durationMs).toBeGreaterThanOrEqual(1500);
    await page.screenshot({ path: path.join(SCREENSHOTS, 'checkpoints', `${id}-read.png`) });
    await waitForPhase(page, 'watch', 20_000);
    const watchEvent = await page.evaluate((checkpointId) => (window as any).__rc33TourDiagnostics.events.find((item: any) => item.event === 'watch-start' && item.episodeId === checkpointId), id);
    expect(watchEvent?.durationMs).toBeGreaterThanOrEqual(1500);
    await page.screenshot({ path: path.join(SCREENSHOTS, 'checkpoints', `${id}-watch.png`) });
    samples.push({ id, read: readEvent, watch: watchEvent, visual: await page.locator(PANEL).getAttribute('data-visual-status') });
  }
  expect(samples).toHaveLength(5);
  expect(samples.every(sample => sample.visual === 'passed')).toBeTruthy();
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'pacing-audit.json'), JSON.stringify({ viewport: { width: 1920, height: 1080 }, samples, passed: true, errors }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'checkpoint-pacing.webm'));
});

test('Styled speed menu supports keyboard selection, Escape and outside close', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Menu keyboard and visual evidence records at 1920×1080.');
  test.setTimeout(60_000);
  const errors = await openRC33(page);
  await chooseMode(page, 'auto');
  const trigger = page.locator('[data-rc3-speed-trigger]');
  await trigger.focus();
  await trigger.press('ArrowDown');
  await expect(page.locator('[data-rc3-speed-menu]')).toBeVisible();
  await expect(page.locator('[data-rc3-speed-option="1"]')).toBeFocused();
  await page.keyboard.press('Home');
  await expect(page.locator('[data-rc3-speed-option="0.75"]')).toBeFocused();
  await page.keyboard.press('End');
  await expect(page.locator('[data-rc3-speed-option="2"]')).toBeFocused();
  await page.screenshot({ path: path.join(SCREENSHOTS, 'panel', 'speed-menu-open.png') });
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-rc3-speed-menu]')).toBeHidden();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.locator('[data-rc3-speed-option="1.5"]').click();
  await expect(trigger).toHaveText('1,5×');
  await trigger.click();
  await page.mouse.click(500, 500);
  await expect(page.locator('[data-rc3-speed-menu]')).toBeHidden();
  await expect(trigger).toHaveText('1,5×');
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'interaction-tests.json'), JSON.stringify({ keyboardOpen: true, arrowHomeEnd: true, escapeRestoresFocus: true, outsideClickCloses: true, selectedSpeed: await trigger.textContent(), errors }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'speed-dropdown.webm'));
});

test('Speed comparison keeps the same reading checkpoint and measures its duration', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Speed comparison evidence records at 1920×1080.');
  test.setTimeout(75_000);
  const errors = await openRC33(page);
  await chooseMode(page, 'auto');
  const trigger = page.locator('[data-rc3-speed-trigger]');
  const chooseSpeed = async (speed: string) => {
    await trigger.click();
    await page.locator(`[data-rc3-speed-option="${speed}"]`).click();
  };
  const restart = async () => {
    await page.locator('[data-rc3-more-toggle]').click();
    await page.locator('[data-rc3-restart]').click();
    await expect(page.locator(PANEL)).toHaveAttribute('data-episode-id', 'os-orientation');
  };
  const measurements: Array<Record<string, unknown>> = [];
  for (const speed of ['0.75', '1', '1.5']) {
    await chooseSpeed(speed);
    await restart();
    await expect(page.locator(PANEL)).toHaveAttribute('data-phase', 'read', { timeout: 20_000 });
    const start = await page.evaluate(() => (window as any).__rc33TourDiagnostics.events.find((item: any) => item.event === 'read-start' && item.episodeId === 'os-orientation'));
    await page.waitForTimeout(650);
    await page.screenshot({ path: path.join(SCREENSHOTS, 'panel', `speed-${speed.replace('.', '-')}.png`) });
    await expect.poll(() => page.evaluate(() => (window as any).__rc33TourDiagnostics.events.some((item: any) => item.event === 'read-end' && item.episodeId === 'os-orientation')), { timeout: 12_000 }).toBeTruthy();
    const end = await page.evaluate(() => (window as any).__rc33TourDiagnostics.events.find((item: any) => item.event === 'read-end' && item.episodeId === 'os-orientation'));
    measurements.push({ speed, durationMs: start.durationMs, startedAtMs: start.atMs, endedAtMs: end.atMs });
  }
  expect(measurements[0].durationMs).toBeGreaterThan(measurements[1].durationMs as number);
  expect(measurements[2].durationMs).toBeLessThan(measurements[1].durationMs as number);
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'speed-comparison.json'), JSON.stringify({ sameCheckpoint: 'os-orientation', effectiveReadSpeedCeiling: 1.25, measurements, errors }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'speed-comparison.webm'));
});

test('Manual scrolling works and Founder reduced motion exposes all copy immediately', async ({ page, browserName }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Responsive geometry and reduced motion are captured once.');
  test.setTimeout(90_000);
  const errors = await openRC33(page);
  await chooseMode(page, 'manual');
  const before = await page.evaluate(() => scrollY);
  await page.mouse.wheel(0, 1200);
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(before);
  await reachFounderWithWheel(page);
  await expect(page.locator('[data-s42-founder]')).toHaveAttribute('data-reveal-state', 'complete', { timeout: 35_000 });
  await expect(page.locator('[data-s42-founder] a[href="https://t.me/eohada"]')).toBeVisible();
  const desktopReport = await runGeometryAudit(page, ROUTE);
  const failures = desktopReport.findings.filter(item => item.severity === 'FAIL' && !/^\.s(32|36|37|38|39)-skip$/.test(item.selector));
  fs.mkdirSync(path.join(SCREENSHOTS, 'responsive'), { recursive: true });
  await page.screenshot({ path: path.join(SCREENSHOTS, 'responsive', 'manual-founder-desktop.png') });
  expect(failures).toEqual([]);
  expect(errors).toEqual([]);
  const reduceContext = await page.context().browser()!.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
  const reducePage = await reduceContext.newPage();
  const reducedErrors = await openRC33(reducePage, { width: 390, height: 844 });
  await chooseMode(reducePage, 'manual');
  await reachFounderWithWheel(reducePage);
  const reduced = await reducePage.evaluate(() => ({
    complete: document.querySelector('[data-s42-founder]')?.getAttribute('data-reveal-state'),
    blocks: [...document.querySelectorAll('[data-typewriter]')].map(node => ({ full: node.querySelector('.s42-typewriter-output')?.textContent, accessible: node.querySelector('.s42-typewriter-accessible')?.textContent })),
    cta: [...document.querySelectorAll('[data-s42-founder] .s42-founder-actions a')].every(node => getComputedStyle(node).opacity === '1')
  }));
  expect(reduced.complete).toBe('complete');
  expect(reduced.blocks.every(block => block.full === block.accessible && block.full)).toBeTruthy();
  expect(reduced.cta).toBeTruthy();
  expect(reducedErrors).toEqual([]);
  await reducePage.screenshot({ path: path.join(SCREENSHOTS, 'responsive', 'founder-reduced-motion-mobile.png') });
  const mobileReport = await runGeometryAudit(reducePage, ROUTE);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'geometry-audit.json'), JSON.stringify({ desktop: desktopReport, mobileReducedMotion: mobileReport, desktopFailures: failures }, null, 2));
  await reduceContext.close();
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'test-results.json'), JSON.stringify({ manualScroll: { from: before, to: await page.evaluate(() => scrollY) }, reducedMotion: reduced, desktopFailures: failures, errors: [...errors, ...reducedErrors], browserName }, null, 2));
});

test('Manual scrolling walkthrough video', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Manual walkthrough records at 1920×1080.');
  test.setTimeout(150_000);
  const errors = await openRC33(page);
  await chooseMode(page, 'manual');
  const startedAt = Date.now();
  const landmarks = [
    { id: 'lesson-os', selector: '#s31-hero' },
    { id: 'homework', selector: '#s38-homework' },
    { id: 'analytics', selector: '#s32-analytics' },
    { id: 'dashboard', selector: '#s36-dashboard' },
    { id: 'schedule', selector: '#s37-schedule' },
    { id: 'theory', selector: '#s39-theory' },
    { id: 'profile', selector: '#s39-profile' },
    { id: 'founder', selector: '#s42-founder' },
  ];
  const frames: Array<{ chapter: string; y: number; heading: string }> = [];
  for (const landmark of landmarks) {
    const targetY = await page.locator(landmark.selector).evaluate(node => Math.max(0, Math.round(node.getBoundingClientRect().top + scrollY - 80)));
    let attempts = 0;
    while ((await page.evaluate(() => scrollY)) < targetY - 4 && attempts < 180) {
      const currentY = await page.evaluate(() => scrollY);
      await page.mouse.wheel(0, Math.min(480, targetY - currentY));
      await page.waitForTimeout(300);
      attempts += 1;
    }
    const frame = await page.locator(landmark.selector).evaluate(node => {
      const rect = node.getBoundingClientRect();
      return {
        y: Math.round(scrollY),
        top: Math.round(rect.top),
        bottom: Math.round(rect.bottom),
        heading: node.querySelector('h1,h2,h3')?.textContent?.trim().replace(/\s+/g, ' ') || '',
      };
    });
    expect(frame.bottom).toBeGreaterThan(0);
    expect(frame.top).toBeLessThan(1080);
    frames.push({ chapter: landmark.id, y: frame.y, heading: frame.heading });
    await page.waitForTimeout(900);
  }
  await expect(page.locator('[data-s42-founder]')).toHaveAttribute('data-reveal-state', 'complete', { timeout: 35_000 });
  await expect(page.locator('[data-s42-founder] a[href="https://t.me/eohada"]')).toBeVisible();
  frames.push({ chapter: 'founder-complete', y: await page.evaluate(() => Math.round(scrollY)), heading: await page.locator('#s42-invitation-title').textContent() || '' });
  expect(frames).toHaveLength(9);
  expect(new Set(frames.map(frame => frame.y)).size).toBeGreaterThan(7);
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'manual-regression.json'), JSON.stringify({ viewport: { width: 1920, height: 1080 }, mode: 'manual', action: 'mouse-wheel across all chapter landmarks', frames, founderComplete: true, durationMs: Date.now() - startedAt, errors }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'manual-regression.webm'));
});

test('Visual geometry QA at BooStudy canonical viewport sizes', async ({ browser }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'One viewport sweep covers the canonical sizes.');
  test.setTimeout(90_000);
  const viewports = [
    { name: '1920x1080', width: 1920, height: 1080, mobile: false },
    { name: '1440x900', width: 1440, height: 900, mobile: false },
    { name: '1366x768', width: 1366, height: 768, mobile: false },
    { name: '1024x768', width: 1024, height: 768, mobile: false },
    { name: '390x844', width: 390, height: 844, mobile: true },
  ];
  const reports: Record<string, unknown> = {};
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, isMobile: viewport.mobile, hasTouch: viewport.mobile });
    const page = await context.newPage();
    const errors = await openRC33(page, viewport);
    await chooseMode(page, 'manual');
    const screenshotPath = path.join(SCREENSHOTS, 'responsive', `geometry-${viewport.name}.png`);
    await page.screenshot({ path: screenshotPath });
    const report = await runGeometryAudit(page, ROUTE);
    const ignoredKeyboardSkipLinks = report.findings.filter(item => item.severity === 'FAIL' && /^\.s(32|36|37|38|39)-skip$/.test(item.selector));
    const failures = report.findings.filter(item => item.severity === 'FAIL' && !ignoredKeyboardSkipLinks.includes(item));
    reports[viewport.name] = { report, failures, ignoredKeyboardSkipLinks, screenshot: path.relative(PACKAGE, screenshotPath), errors };
    expect(failures, `No material geometry failures at ${viewport.name}`).toEqual([]);
    expect(errors, `No browser errors at ${viewport.name}`).toEqual([]);
    await context.close();
  }
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'responsive-geometry-audit.json'), JSON.stringify(reports, null, 2));
});
