import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { runGeometryAudit } from './visual/geometry-audit';

const ROUTE = '/static/landing-release-candidate-rc3-1/index.html';
const RC3_ROUTE = '/static/landing-release-candidate-rc3/index.html';
const PANEL = '[data-rc3-tour-panel]';
const EVIDENCE = path.resolve('output/landing-release-audit/evidence/rc3-1');
const VIEWPORTS = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1366x768', width: 1366, height: 768 },
  { name: '1024x768', width: 1024, height: 768 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
  { name: '375x812', width: 375, height: 812 },
  { name: '320x700', width: 320, height: 700 },
];

async function openRC31(page: Page, viewport = { width: 1920, height: 1080 }) {
  await page.setViewportSize(viewport);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const response = await page.goto(ROUTE, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  expect(response?.status()).toBe(200);
  expect(await page.title()).toBe('BooStudy — Release Candidate 3');
  return errors;
}

async function copyPageVideo(page: Page, targetPath: string) {
  if (process.env.PLAYWRIGHT_VIDEO !== 'on') return;
  const video = page.video();
  expect(video, 'video recording is enabled for this evidence run').not.toBeNull();
  await page.close();
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  await fs.promises.copyFile(await video!.path(), targetPath);
}

async function chooseMode(page: Page, mode: 'auto' | 'manual') {
  if (!(await page.locator('#rc3-welcome').isVisible())) {
    await page.locator('[data-rc3-reopen]').click();
  }
  await page.locator(`[data-rc3-choice="${mode}"]`).click();
}

async function startAuto(page: Page, speed = '1.5') {
  await chooseMode(page, 'auto');
  await expect(page.locator(PANEL)).toBeVisible();
  await page.locator('[data-rc3-speed]').selectOption(speed);
}

async function waitForVisualStop(page: Page, index: number) {
  await expect.poll(() => page.locator(PANEL).getAttribute('data-index'), { timeout: 10_000 }).toBe(String(index));
  await expect.poll(() => page.locator(PANEL).getAttribute('data-visual-status'), { timeout: 10_000 }).not.toBe('pending');
  const status = await page.locator(PANEL).getAttribute('data-visual-status');
  if (status !== 'passed') {
    const diagnostic = await page.evaluate(() => {
      const tour = (window as Window & { BooStudyGuidedTour?: { visualDiagnostics?: unknown[] } }).BooStudyGuidedTour;
      return tour?.visualDiagnostics?.at(-1) || null;
    });
    throw new Error(`Visual contract failed at stop ${index + 1}: ${JSON.stringify(diagnostic)}`);
  }
}

async function readVisualReport(page: Page) {
  return page.evaluate(() => {
    const tour = (window as Window & { BooStudyGuidedTour?: { visualReports?: unknown[] } }).BooStudyGuidedTour;
    return tour?.visualReports?.at(-1) || null;
  });
}

test('Auto keeps the sticky surface visible, pauses input, and restores manual scrolling', async ({ page }) => {
  const errors = await openRC31(page);
  await startAuto(page);
  await waitForVisualStop(page, 0);

  const scene = await page.evaluate(() => {
    const stage = document.querySelector('[data-s30-stage]')!.getBoundingClientRect();
    const surface = document.querySelector('[data-s30-workspace]')!.getBoundingClientRect();
    const copy = document.querySelector('[data-s30-copy="enter"]')!;
    const text = copy.getBoundingClientRect();
    return {
      y: scrollY,
      rootOverflow: getComputedStyle(document.documentElement).overflowY,
      bodyOverflow: getComputedStyle(document.body).overflowY,
      stage: { top: stage.top, bottom: stage.bottom },
      surface: { top: surface.top, bottom: surface.bottom, width: surface.width },
      copy: { top: text.top, bottom: text.bottom, opacity: Number.parseFloat(getComputedStyle(copy).opacity), ariaHidden: copy.getAttribute('aria-hidden') },
    };
  });
  expect(scene.y).toBeGreaterThan(0);
  expect(scene.rootOverflow).not.toBe('hidden');
  expect(scene.bodyOverflow).not.toBe('hidden');
  expect(scene.stage.top).toBeLessThanOrEqual(1);
  expect(scene.stage.bottom).toBeGreaterThan(800);
  expect(scene.surface.top).toBeGreaterThanOrEqual(0);
  expect(scene.surface.bottom).toBeLessThanOrEqual(1081);
  expect(scene.copy.opacity).toBeGreaterThan(0);
  expect(scene.copy.ariaHidden).toBe('false');
  await page.screenshot({ path: path.join(EVIDENCE, 'manual-auto', 'rc31-first-auto-1920x1080.jpg'), type: 'jpeg', quality: 90 });

  await page.locator('[data-rc3-play]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-paused');
  const pausedY = await page.evaluate(() => scrollY);
  await page.mouse.wheel(0, 900);
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(120);
  expect(await page.evaluate(() => scrollY)).toBe(pausedY);
  await page.locator('[data-rc3-play]').click();
  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-playing');
  await page.locator('[data-rc3-exit]').click();
  await expect(page.locator(PANEL)).toBeHidden();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowY)).not.toBe('hidden');
  const manualAfter = await page.evaluate(() => {
    const stage = document.querySelector('[data-s30-stage]')!.getBoundingClientRect();
    const surface = document.querySelector('[data-s30-workspace]')!.getBoundingClientRect();
    return { y: scrollY, stageTop: stage.top, surface: { top: surface.top, bottom: surface.bottom } };
  });
  expect(manualAfter.y).toBe(scene.y);
  expect(manualAfter.stageTop).toBeLessThanOrEqual(1);
  await page.screenshot({ path: path.join(EVIDENCE, 'manual-auto', 'rc31-first-manual-1920x1080.jpg'), type: 'jpeg', quality: 90 });
  fs.writeFileSync(path.join(EVIDENCE, 'manual-auto', 'rc31-manual-auto-geometry.json'), JSON.stringify({ auto: scene, manual: manualAfter }, null, 2));
  const manualBefore = await page.evaluate(() => scrollY);
  await page.mouse.wheel(0, 480);
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(manualBefore);
  expect(errors).toEqual([]);
});

test('RC3 baseline reproduces the empty Auto frame at the same y as Manual', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Baseline comparison is captured once at 1920×1080.');
  const viewport = { width: 1920, height: 1080 };
  await page.setViewportSize(viewport);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.goto(RC3_ROUTE, { waitUntil: 'networkidle' });
  expect(response?.status()).toBe(200);
  const baselineDir = path.join(EVIDENCE, 'root-cause');
  fs.mkdirSync(baselineDir, { recursive: true });
  await chooseMode(page, 'auto');
  await expect.poll(() => page.locator('[data-rc3-phase-label]').innerText()).toContain('READ');
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
  const auto = await page.evaluate(() => {
    const rect = (selector: string) => {
      const r = document.querySelector(selector)!.getBoundingClientRect();
      return { top: Math.round(r.top), bottom: Math.round(r.bottom), width: Math.round(r.width), height: Math.round(r.height) };
    };
    return {
      y: Math.round(scrollY),
      rootOverflow: getComputedStyle(document.documentElement).overflowY,
      bodyOverflow: getComputedStyle(document.body).overflowY,
      stage: rect('[data-s30-stage]'),
      workspace: rect('[data-s30-workspace]'),
    };
  });
  await page.screenshot({ path: path.join(baselineDir, 'rc3-auto-empty-1920x1080.jpg'), type: 'jpeg', quality: 90 });
  await page.locator('[data-rc3-exit]').click();
  await expect(page.locator('[data-rc3-tour-panel]')).toBeHidden();
  const manual = await page.evaluate(() => {
    const stage = document.querySelector('[data-s30-stage]')!.getBoundingClientRect();
    const workspace = document.querySelector('[data-s30-workspace]')!.getBoundingClientRect();
    return {
      y: Math.round(scrollY),
      rootOverflow: getComputedStyle(document.documentElement).overflowY,
      bodyOverflow: getComputedStyle(document.body).overflowY,
      stageTop: Math.round(stage.top),
      workspace: { top: Math.round(workspace.top), bottom: Math.round(workspace.bottom) },
    };
  });
  await page.screenshot({ path: path.join(baselineDir, 'rc3-manual-visible-1920x1080.jpg'), type: 'jpeg', quality: 90 });
  fs.writeFileSync(path.join(baselineDir, 'rc3-root-cause-geometry.json'), JSON.stringify({ auto, manual, errors }, null, 2));
  expect(auto.rootOverflow).toBe('hidden');
  expect(auto.bodyOverflow).toBe('hidden');
  expect(auto.stage.top).toBeLessThan(-viewport.height / 2);
  expect(manual.y).toBe(auto.y);
  expect(manual.rootOverflow).not.toBe('hidden');
  expect(manual.stageTop).toBeLessThanOrEqual(1);
  expect(manual.workspace.top).toBeGreaterThanOrEqual(0);
  expect(errors).toEqual([]);
});

test('all 34 visual contracts pass at each required viewport', async ({ browser }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'One responsive sweep covers all viewport sizes.');
  test.setTimeout(600_000);
  fs.mkdirSync(path.join(EVIDENCE, 'responsive'), { recursive: true });
  const selectedViewports = process.env.RC31_VIEWPORTS
    ? VIEWPORTS.filter(({ name }) => process.env.RC31_VIEWPORTS?.split(',').includes(name))
    : VIEWPORTS;
  expect(selectedViewports.length).toBeGreaterThan(0);
  const allViewportReports: Record<string, unknown> = {};
  const allErrors: Record<string, string[]> = {};

  for (const viewport of selectedViewports) {
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
    const page = await context.newPage();
    const errors = await openRC31(page, viewport);
    await startAuto(page);
    const manifest = await page.evaluate(() => {
      const tour = (window as Window & { BooStudyGuidedTour?: { manifest?: Array<{ id: string; chapter: string; visualContract: { surface: string; copy: string } }> } }).BooStudyGuidedTour;
      return tour?.manifest?.map(({ id, chapter, visualContract }) => ({ id, chapter, visualContract })) || [];
    });
    expect(manifest, `Tour manifest is available at ${viewport.name}`).toHaveLength(34);
    const stopReports: unknown[] = [];

    for (let index = 0; index < manifest.length; index += 1) {
      if (index > 0) await page.locator('[data-rc3-next]').click();
      await waitForVisualStop(page, index);
      const report = await readVisualReport(page);
      expect(report, `Stop ${index + 1} has visibility evidence at ${viewport.name}`).not.toBeNull();
      stopReports.push({ episode: manifest[index], report, panelPhase: await page.locator(PANEL).getAttribute('data-phase') });
    }

    const geometry = viewport.name === '1920x1080' || viewport.name === '390x844'
      ? await runGeometryAudit(page, ROUTE)
      : null;
    allViewportReports[viewport.name] = { stops: stopReports, geometry };
    allErrors[viewport.name] = errors;
    fs.writeFileSync(path.join(EVIDENCE, 'responsive', 'all-viewports-34-stops.json'), JSON.stringify({ viewports: allViewportReports, errors: allErrors }, null, 2));
    await context.close();
  }

  fs.writeFileSync(path.join(EVIDENCE, 'responsive', 'all-viewports-34-stops.json'), JSON.stringify({ viewports: allViewportReports, errors: allErrors }, null, 2));
  expect(allErrors).toEqual(Object.fromEntries(selectedViewports.map(({ name }) => [name, []])));
  expect(Object.keys(allViewportReports)).toHaveLength(selectedViewports.length);
});

async function runNaturalAutoTour(page: Page, viewport: { width: number; height: number }, captureAtlas: boolean) {
  test.setTimeout(600_000);
  const errors = await openRC31(page, viewport);
  const evidenceDir = path.join(EVIDENCE, captureAtlas ? 'desktop-atlas' : 'mobile');
  const stopDir = path.join(evidenceDir, 'stops');
  fs.mkdirSync(stopDir, { recursive: true });
  const manifest = await page.evaluate(() => {
    const tour = (window as Window & { BooStudyGuidedTour?: { manifest?: Array<{ id: string; chapterTitle: string; label: string; watchMs: number }> } }).BooStudyGuidedTour;
    return tour?.manifest || [];
  });
  expect(manifest).toHaveLength(34);
  await page.screenshot({ path: path.join(evidenceDir, 'welcome-before-auto.jpg'), type: 'jpeg', quality: 82 });
  await startAuto(page, '0.75');
  await page.screenshot({ path: path.join(stopDir, 'before-00.jpg'), type: 'jpeg', quality: 78 });

  const reports: unknown[] = [];
  const founderSamples: unknown[] = [];
  const timing = [0, 250, 500, 750, 1000, 1500, 2000, 3000, 4000];
  for (let index = 0; index < manifest.length; index += 1) {
    await waitForVisualStop(page, index);
    const report = await readVisualReport(page);
    expect(report, `stop ${index + 1} visual report`).not.toBeNull();
    reports.push({ manifest: manifest[index], report });
    if (captureAtlas) {
      await page.screenshot({ path: path.join(stopDir, `${String(index + 1).padStart(2, '0')}-${manifest[index].id}-after-move.jpg`), type: 'jpeg', quality: 78 });
    }

    if (manifest[index].id === 'founder-story') {
      const firstFrameAt = Date.now();
      for (const elapsedMs of timing) {
        await page.waitForTimeout(Math.max(0, elapsedMs - (Date.now() - firstFrameAt)));
        const sample = await page.evaluate(() => {
          const founder = document.querySelector('[data-s42-founder]')!;
          const title = founder.querySelector('#s42-founder-title')!;
          const revealItems = [...founder.querySelectorAll('[data-s42-reveal]')];
          const actions = founder.querySelector('[data-s42-reveal-actions]')!;
          const rect = title.getBoundingClientRect();
          return {
            revealState: founder.getAttribute('data-reveal-state'),
            revealedCount: revealItems.filter(item => item.classList.contains('is-revealed')).length,
            titleOpacity: Number.parseFloat(getComputedStyle(title).opacity),
            titleTransform: getComputedStyle(title).transform,
            titleRect: { top: Math.round(rect.top), bottom: Math.round(rect.bottom) },
            actionsOpacity: Number.parseFloat(getComputedStyle(actions).opacity),
          };
        });
        founderSamples.push({ elapsedMs, sample });
        if (captureAtlas) await page.screenshot({ path: path.join(evidenceDir, `founder-${String(elapsedMs).padStart(4, '0')}ms.jpg`), type: 'jpeg', quality: 88 });
      }
      await expect(page.locator('[data-s42-founder]')).toHaveAttribute('data-reveal-state', 'complete', { timeout: 7000 });
      if (captureAtlas) await page.screenshot({ path: path.join(evidenceDir, 'founder-complete.jpg'), type: 'jpeg', quality: 88 });
    } else if (manifest[index].watchMs > 0) {
      await expect(page.locator(PANEL)).toHaveAttribute('data-phase', 'watch', { timeout: 12_000 });
      if (captureAtlas) await page.screenshot({ path: path.join(stopDir, `${String(index + 1).padStart(2, '0')}-${manifest[index].id}-watch.jpg`), type: 'jpeg', quality: 78 });
    }

    await expect(page.locator(PANEL)).toHaveAttribute('data-phase', 'hold', { timeout: 12_000 });
    if (captureAtlas) {
      const name = `${String(index + 1).padStart(2, '0')}-${manifest[index].id}-hold.jpg`;
      await page.screenshot({ path: path.join(stopDir, name), type: 'jpeg', quality: 78 });
      if (index + 1 < manifest.length) {
        await fs.promises.copyFile(path.join(stopDir, name), path.join(stopDir, `before-${String(index + 1).padStart(2, '0')}.jpg`));
      }
    }
  }

  await expect(page.locator(PANEL)).toHaveAttribute('data-state', 'auto-complete', { timeout: 10_000 });
  expect(errors).toEqual([]);
  const finalState = await page.locator(PANEL).evaluate((panel) => ({
    state: panel.getAttribute('data-state'),
    episode: panel.getAttribute('data-episode-id'),
    index: panel.getAttribute('data-index'),
    visualStatus: panel.getAttribute('data-visual-status'),
  }));
  fs.writeFileSync(path.join(evidenceDir, 'natural-tour-visual-reports.json'), JSON.stringify({ viewport, finalState, reports, founderSamples, errors }, null, 2));

  if (captureAtlas) {
    const image = (file: string, alt: string) => `<figure><img src="stops/${file}" alt="${alt}" loading="lazy"><figcaption>${alt}</figcaption></figure>`;
    const rows = manifest.map((episode, index) => {
      const n = String(index + 1).padStart(2, '0');
      const id = episode.id;
      const before = index === 0 ? 'before-00.jpg' : `before-${n}.jpg`;
      const watch = episode.watchMs > 0 ? `${n}-${id}-watch.jpg` : 'founder-0000ms.jpg';
      return `<article><h2>${n} · ${id} · ${episode.chapterTitle}</h2><p>${episode.label}</p><div class="frames">${image(before, 'До остановки')}${image(`${n}-${id}-after-move.jpg`, 'После MOVE, сцена видима')}${image(watch, 'WATCH / раскрытие')}${image(`${n}-${id}-hold.jpg`, 'После HOLD')}</div></article>`;
    }).join('');
    fs.writeFileSync(path.join(evidenceDir, 'visual-atlas.html'), `<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>RC3.1 · Atlas 34 stops</title><style>body{margin:0;padding:24px;background:#f3f1f8;color:#29243e;font:15px/1.45 system-ui}h1{font-size:32px}.intro{max-width:900px;color:#645d79}article{margin:28px 0;padding:20px;background:white;border:1px solid #e1dced;border-radius:18px;box-shadow:0 8px 26px #30205012}h2{margin:0 0 4px;font-size:20px}.frames{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}figure{margin:0}img{display:block;width:100%;height:auto;border:1px solid #ebe8f2;border-radius:10px}figcaption{padding-top:5px;color:#766f87;font-size:12px}@media(max-width:900px){.frames{grid-template-columns:repeat(2,minmax(0,1fr))}}</style><h1>RC3.1 · Визуальная проверка 34 остановок</h1><p class="intro">Каждая строка содержит кадр до остановки, после MOVE, во время WATCH и после HOLD. Кадры связаны с отчётом видимости и фактической фазой экскурсии.</p>${rows}</html>`);
  }
  const recordingName = captureAtlas ? 'desktop-auto-1920x1080.webm' : 'mobile-auto-390x844.webm';
  await copyPageVideo(page, path.join(EVIDENCE, 'videos', recordingName));
}

test('natural desktop Auto tour shows all 34 stops and produces the visual atlas', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop recording uses the 1920×1080 project.');
  await runNaturalAutoTour(page, { width: 1920, height: 1080 }, true);
});

test('natural mobile Auto tour completes at 390×844 without blank stops', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Mobile recording uses the 390×844 project.');
  await runNaturalAutoTour(page, { width: 390, height: 844 }, false);
});

test('Founder reveals only in a safe viewport, stays visible on return, and captures the full sequence', async ({ page }, testInfo) => {
  const viewport = testInfo.project.name === 'mobile-chromium' ? { width: 390, height: 844 } : { width: 1920, height: 1080 };
  const errors = await openRC31(page, viewport);
  const evidenceDir = path.join(EVIDENCE, 'founder-manual', `${viewport.width}x${viewport.height}`);
  fs.mkdirSync(evidenceDir, { recursive: true });
  await chooseMode(page, 'manual');

  const title = page.locator('#s42-founder-title');
  let safe = false;
  for (let attempt = 0; attempt < 120 && !safe; attempt += 1) {
    const geometry = await title.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, safeTop: innerHeight * 0.12, safeBottom: innerHeight * 0.82 };
    });
    safe = geometry.top >= geometry.safeTop && geometry.bottom <= geometry.safeBottom;
    if (!safe) {
      await page.mouse.wheel(0, geometry.top > geometry.safeBottom ? 900 : -600);
      await page.waitForTimeout(24);
    }
  }
  expect(safe, 'Founder heading reached its safe reading area via mouse wheel').toBeTruthy();
  await expect(page.locator('[data-s42-founder]')).toHaveAttribute('data-reveal-state', 'revealing', { timeout: 5000 });
  const timing = [0, 250, 500, 750, 1000, 1500, 2000, 3000, 4000];
  const samples: unknown[] = [];
  const revealStarted = Date.now();
  for (const elapsedMs of timing) {
    await page.waitForTimeout(Math.max(0, elapsedMs - (Date.now() - revealStarted)));
    const sample = await page.evaluate(() => {
      const founder = document.querySelector('[data-s42-founder]')!;
      const heading = founder.querySelector('#s42-founder-title')!;
      const items = [...founder.querySelectorAll('[data-s42-reveal]')];
      const actions = founder.querySelector('[data-s42-reveal-actions]')!;
      const r = heading.getBoundingClientRect();
      return {
        state: founder.getAttribute('data-reveal-state'),
        revealedCount: items.filter(item => item.classList.contains('is-revealed')).length,
        headingOpacity: Number.parseFloat(getComputedStyle(heading).opacity),
        headingTransform: getComputedStyle(heading).transform,
        headingRect: { top: Math.round(r.top), bottom: Math.round(r.bottom) },
        actionsOpacity: Number.parseFloat(getComputedStyle(actions).opacity),
        scrollY,
      };
    });
    samples.push({ elapsedMs, sample });
    await page.screenshot({ path: path.join(evidenceDir, `founder-${String(elapsedMs).padStart(4, '0')}ms.jpg`), type: 'jpeg', quality: 88 });
  }
  await expect(page.locator('[data-s42-founder]')).toHaveAttribute('data-reveal-state', 'complete', { timeout: 8000 });
  await expect(page.locator('[data-s42-founder] a[href="https://t.me/eohada"]')).toBeVisible();
  await expect(page.locator('[data-s42-founder] a[href="/register"]')).toBeVisible();
  await page.screenshot({ path: path.join(evidenceDir, 'founder-complete.jpg'), type: 'jpeg', quality: 88 });
  await page.mouse.wheel(0, -800);
  await page.mouse.wheel(0, 800);
  expect(await page.locator('[data-s42-founder]').getAttribute('data-reveal-state')).toBe('complete');
  expect(await page.locator('[data-s42-founder] [data-s42-reveal].is-revealed').count()).toBe(8);
  fs.writeFileSync(path.join(evidenceDir, 'founder-timeline.json'), JSON.stringify({ viewport, samples, errors }, null, 2));
  expect(errors).toEqual([]);
  await copyPageVideo(page, path.join(EVIDENCE, 'videos', `founder-reveal-${viewport.width}x${viewport.height}.webm`));
});

test('visual geometry audit covers the landing shell at desktop and mobile entry', async ({ page }, testInfo) => {
  const viewport = testInfo.project.name === 'mobile-chromium' ? { width: 390, height: 844 } : { width: 1920, height: 1080 };
  await openRC31(page, viewport);
  await chooseMode(page, 'manual');
  const report = await runGeometryAudit(page, ROUTE);
  fs.mkdirSync(path.join(EVIDENCE, 'geometry'), { recursive: true });
  const intentionalKeyboardSkipLinkFindings = report.findings.filter(item => item.severity === 'FAIL' && /^\.s(32|36|37|38|39)-skip$/.test(item.selector));
  const materialFailures = report.findings.filter(item => item.severity === 'FAIL' && !intentionalKeyboardSkipLinkFindings.includes(item));
  fs.writeFileSync(path.join(EVIDENCE, 'geometry', `${viewport.width}x${viewport.height}.json`), JSON.stringify({ report, intentionalKeyboardSkipLinkFindings, materialFailures }, null, 2));
  expect(materialFailures).toEqual([]);
});
