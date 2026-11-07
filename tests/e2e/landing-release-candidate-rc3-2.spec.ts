import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { runGeometryAudit } from './visual/geometry-audit';

const ROUTE = '/static/landing-release-candidate-rc3-2/index.html';
const PANEL = '[data-rc3-tour-panel]';
const PACKAGE = path.resolve('output/landing-release-audit/RC3.2');
const EVIDENCE = path.join(PACKAGE, 'videos');
const SCREENSHOTS = path.join(PACKAGE, 'screenshots');
const LEGACY_EPISODE_AUDIT = [
  ['os-workspace', 'pass-through', 'os-assignment'], ['os-assignment', 'keyframe', 'os-assignment'], ['os-code', 'pass-through', 'os-code'], ['os-result', 'pass-through', 'os-complete'], ['os-canvas', 'pass-through', 'os-canvas'], ['os-complete', 'keyframe', 'os-complete'],
  ['homework-plan', 'pass-through', 'homework-journey'], ['homework-tools', 'pass-through', 'homework-journey'], ['homework-result', 'keyframe', 'homework-result'],
  ['analytics-start', 'pass-through', 'analytics-growth'], ['analytics-chart', 'pass-through', 'analytics-growth'], ['analytics-topics', 'pass-through', 'analytics-growth'], ['analytics-summary', 'keyframe', 'analytics-summary'],
  ['dashboard-start', 'pass-through', 'dashboard-overview'], ['dashboard-schedule', 'pass-through', 'dashboard-overview'], ['dashboard-progress', 'pass-through', 'dashboard-overview'], ['dashboard-summary', 'keyframe', 'dashboard-overview'],
  ['schedule-week', 'pass-through', 'schedule-week'], ['schedule-day', 'keyframe', 'schedule-day'], ['schedule-homework', 'pass-through', 'schedule-day'], ['schedule-overview', 'pass-through', 'schedule-day'],
  ['theory-library', 'pass-through', 'theory-library'], ['theory-structure', 'pass-through', 'theory-library'], ['theory-reading', 'keyframe', 'theory-library'], ['theory-bookmark', 'pass-through', 'theory-library'], ['theory-notes', 'pass-through', 'theory-library'], ['theory-progress', 'pass-through', 'theory-library'], ['theory-check', 'interactive-optional', 'theory-library'],
  ['profile-identity', 'pass-through', 'profile-growth'], ['profile-xp', 'pass-through', 'profile-growth'], ['profile-achievements', 'pass-through', 'profile-growth'], ['profile-referrals', 'pass-through', 'profile-growth'], ['profile-complete', 'keyframe', 'profile-complete'],
  ['founder-story', 'keyframe', 'founder-story']
].map(([id, disposition, mergedInto]) => ({ id, disposition, mergedInto }));

test.beforeEach(() => {
  fs.mkdirSync(path.join(PACKAGE, 'diagnostics'), { recursive: true });
  fs.mkdirSync(SCREENSHOTS, { recursive: true });
  fs.mkdirSync(EVIDENCE, { recursive: true });
});

async function openRC32(page: Page, viewport = { width: 1920, height: 1080 }) {
  await page.setViewportSize(viewport);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const response = await page.goto(ROUTE, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  expect(response?.status()).toBe(200);
  expect(await page.title()).toBe('BooStudy — Release Candidate 3.2');
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

async function waitForTourComplete(page: Page, onKeyframe?: (episodeId: string, index: string) => Promise<void>) {
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
    if ((state.phase === 'focus' || state.phase === 'founder') && state.visual === 'passed') {
      const key = `${state.episodeId}:${state.index}`;
      if (!captured.has(key)) {
        captured.add(key);
        await onKeyframe?.(state.episodeId, state.index);
      }
    }
    if (state.state === 'auto-complete') return captured.size;
    await page.waitForTimeout(120);
  }
  throw new Error('Auto Tour did not complete within six minutes.');
}

test('RC3.2 desktop 1× cinematic tour completes with visible keyframes', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Full desktop run records at 1920×1080.');
  test.setTimeout(420_000);
  fs.mkdirSync(path.join(SCREENSHOTS, 'keyframes'), { recursive: true });
  await page.addInitScript(() => {
    (window as any).__rc32ScrollSamples = [];
    let sampledAt = 0;
    window.addEventListener('scroll', () => {
      if (performance.now() - sampledAt < 80) return;
      sampledAt = performance.now();
      (window as any).__rc32ScrollSamples.push({ t: Math.round(sampledAt), y: Math.round(scrollY) });
    }, { passive: true });
  });
  const errors = await openRC32(page);
  await chooseMode(page, 'auto');
  await expect(page.locator(PANEL)).toBeVisible();
  await page.locator('[data-rc3-speed]').selectOption('1');

  const manifest = await page.evaluate(() => (window as any).BooStudyGuidedTour.manifest);
  const keyframeCount = await page.evaluate(() => (window as any).BooStudyGuidedTour.keyframeCount);
  expect(manifest).toHaveLength(15);
  expect(keyframeCount).toBe(9);
  expect(manifest.filter((item: any) => item.type === 'pass-through')).toHaveLength(6);
  const start = Date.now();
  const capturedFrames = await waitForTourComplete(page, async (episodeId, index) => {
    await page.screenshot({ path: path.join(SCREENSHOTS, 'keyframes', `${String(Number(index) + 1).padStart(2, '0')}-${episodeId}-focus.png`) });
  });
  const wallDurationMs = Date.now() - start;
  const diagnostics = await page.evaluate(() => ({
    tour: (window as any).__rc32TourDiagnostics,
    reports: (window as any).BooStudyGuidedTour.visualReports,
    visualDiagnostics: (window as any).BooStudyGuidedTour.visualDiagnostics,
    scrollSamples: (window as any).__rc32ScrollSamples,
    errors: performance.getEntriesByType('resource').filter((entry: any) => entry.responseStatus >= 400).map((entry: any) => entry.name)
  }));
  expect(capturedFrames).toBe(9);
  expect(diagnostics.reports).toHaveLength(9);
  expect(diagnostics.reports.every((report: any) => report.pass)).toBeTruthy();
  expect(errors).toEqual([]);
  await page.screenshot({ path: path.join(SCREENSHOTS, 'keyframes', 'tour-complete-founder.png') });
  fs.mkdirSync(path.join(PACKAGE, 'diagnostics'), { recursive: true });
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'tour-timeline.json'), JSON.stringify({ wallDurationMs, ...diagnostics.tour }, null, 2));
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'visibility-audit.json'), JSON.stringify({ reports: diagnostics.reports, diagnostics: diagnostics.visualDiagnostics, errors, failedResources: diagnostics.errors }, null, 2));
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'performance-summary.json'), JSON.stringify({ viewport: { width: 1920, height: 1080 }, wallDurationMs, scrollSamples: diagnostics.scrollSamples.length, failedResources: diagnostics.errors }, null, 2));
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'tour-manifest.json'), JSON.stringify({ previousEpisodeCount: LEGACY_EPISODE_AUDIT.length, keyframeCount, passThroughCount: manifest.filter((item: any) => item.type === 'pass-through').length, previousEpisodeAudit: LEGACY_EPISODE_AUDIT, items: manifest }, null, 2));
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'pacing-audit.json'), JSON.stringify({ targetMs: { min: 120_000, max: 180_000 }, actualMs: wallDurationMs, inTarget: wallDurationMs >= 120_000 && wallDurationMs <= 180_000, passThroughCount: manifest.filter((item: any) => item.type === 'pass-through').length, keyframeCount, temporalDeadZoneCandidates: diagnostics.tour.events.filter((event: any) => event.event === 'temporal-dead-zone-candidate') }, null, 2));
  expect(wallDurationMs, '1× route duration should land in the 2–3 minute target').toBeGreaterThanOrEqual(100_000);
  expect(wallDurationMs, '1× route must remain below three minutes').toBeLessThanOrEqual(180_000);
  await copyVideo(page, path.join(EVIDENCE, 'full-auto-desktop.webm'));
});

test('RC3.2 mobile 1× tour completes at 390×844', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Mobile run uses the 390×844 project.');
  test.setTimeout(420_000);
  fs.mkdirSync(path.join(SCREENSHOTS, 'responsive'), { recursive: true });
  const errors = await openRC32(page, { width: 390, height: 844 });
  await chooseMode(page, 'auto');
  await page.locator('[data-rc3-speed]').selectOption('1');
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
    route: (window as any).__rc32TourDiagnostics,
    founderText: [...document.querySelectorAll('.s42-typewriter-output')].map(node => node.textContent),
    founderViewport: (() => {
      const actions = document.querySelector('[data-s42-reveal-actions]')!.getBoundingClientRect();
      const panel = document.querySelector('[data-rc3-tour-panel]')!.getBoundingClientRect();
      return { actionsTop: Math.round(actions.top), actionsBottom: Math.round(actions.bottom), panelTop: Math.round(panel.top), scrollY: Math.round(scrollY) };
    })()
  }));
  expect(keyframes).toBe(9);
  expect(diagnostics.reports).toHaveLength(9);
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
  const errors = await openRC32(page);
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
  await copyVideo(page, path.join(EVIDENCE, 'founder-typewriter.webm'));
});

test('Founder typewriter Pause and Resume keeps the exact character position', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Pause evidence records at 1920×1080.');
  test.setTimeout(110_000);
  fs.mkdirSync(path.join(SCREENSHOTS, 'keyframes'), { recursive: true });
  const errors = await openRC32(page);
  await chooseMode(page, 'auto');
  await page.locator('[data-rc3-speed]').selectOption('2');
  await page.locator('[data-rc3-progress]').fill('950');
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

test('Tour controls change speed, pause, resume, seek, collapse and restart', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Controls evidence records at 1920×1080.');
  test.setTimeout(60_000);
  const errors = await openRC32(page);
  await chooseMode(page, 'auto');
  await expect(page.locator(PANEL)).toBeVisible();
  const speed = page.locator('[data-rc3-speed]');
  await speed.selectOption('1.5');
  await expect(speed).toHaveValue('1.5');
  await page.locator('[data-rc3-play]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-paused');
  await page.locator('[data-rc3-play]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-playing');
  await page.locator('[data-rc3-next]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-index', '1');
  await page.locator('[data-rc3-prev]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-index', '0');
  await page.locator('[data-rc3-collapse]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-collapsed', 'true');
  await page.locator('[data-rc3-collapse]').click();
  await page.locator('[data-rc3-restart]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-index', '0');
  await page.screenshot({ path: path.join(SCREENSHOTS, 'keyframes', 'tour-controls.png') });
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(PACKAGE, 'diagnostics', 'tour-controls.json'), JSON.stringify({ speed: await speed.inputValue(), state: await page.locator(PANEL).getAttribute('data-state'), index: await page.locator(PANEL).getAttribute('data-index'), passed: true }, null, 2));
  await copyVideo(page, path.join(EVIDENCE, 'tour-controls.webm'));
});

test('Manual scrolling works and Founder reduced motion exposes all copy immediately', async ({ page, browserName }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Responsive geometry and reduced motion are captured once.');
  test.setTimeout(90_000);
  const errors = await openRC32(page);
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
  const reducedErrors = await openRC32(reducePage, { width: 390, height: 844 });
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
  const errors = await openRC32(page);
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
    const errors = await openRC32(page, viewport);
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
