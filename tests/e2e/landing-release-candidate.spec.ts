import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const LANDING = '/static/landing-release-candidate-rc1/index.html';
const EVIDENCE = path.resolve(process.cwd(), 'output/landing-release-audit/evidence');

async function openLanding(page: Page, viewport = { width: 1920, height: 1080 }) {
  await page.setViewportSize(viewport);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const response = await page.goto(LANDING, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  expect(response?.status()).toBe(200);
  return errors;
}

async function scrollStory(page: Page, selector: string, progress: number, settleMs = 80) {
  await page.locator(selector).evaluate((story, value) => {
    const top = story.getBoundingClientRect().top + window.scrollY;
    const calibrated = Number(story.dataset.s40ProgressRange);
    const range = Number.isFinite(calibrated) && calibrated > 0
      ? calibrated
      : Math.max(1, story.offsetHeight - window.innerHeight);
    window.scrollTo({ top: top + range * value, behavior: 'instant' });
  }, progress);
  if (settleMs) await page.waitForTimeout(settleMs);
}

const CHAPTERS = [
  { key: 's30', selector: '[data-s30-story]', file: '01-lesson-os' },
  { key: 's38homework', selector: '[data-s38-homework]', file: '02-homework-os' },
  { key: 's32', selector: '[data-s32-story]', file: '03-analytics' },
  { key: 's36', selector: '[data-s36-story]', file: '04-dashboard' },
  { key: 's37', selector: '[data-s37-story]', file: '05-schedule' },
  { key: 's39theory', selector: '[data-s39-theory]', file: '06-theory-library' },
  { key: 's39profile', selector: '[data-s39-profile]', file: '07-profile' },
  { key: 's42founder', selector: '[data-s42-founder]', file: '08-founder' },
];

test('desktop scroll-story reaches and reverses every chapter checkpoint', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop chapter matrix');
  await page.addInitScript(() => {
    (window as Window & { __storyProgress?: Record<string, number> }).__storyProgress = {};
    document.addEventListener('boostudy:story-progress', (event) => {
      Object.assign((window as Window & { __storyProgress: Record<string, number> }).__storyProgress, (event as CustomEvent).detail);
    });
  });
  const errors = await openLanding(page);

  expect(await page.title()).toBe('BooStudy — Release Candidate 1');
  expect(await page.locator('meta[name="robots"]').getAttribute('content')).toBe('noindex, nofollow');
  await expect(page.locator('main')).toHaveCount(1);
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
  for (const chapter of CHAPTERS) await expect(page.locator(chapter.selector)).toHaveCount(1);

  const sampleProgress = [0, 0.25, 0.5, 0.75, 0.98];
  fs.mkdirSync(path.join(EVIDENCE, 'desktop-states', 'chapters'), { recursive: true });
  for (const chapter of CHAPTERS) {
    let stableHeight: number | null = null;
    for (const progress of sampleProgress) {
      await scrollStory(page, chapter.selector, progress, 470);
      const state = await page.locator(chapter.selector).evaluate((story, key) => ({
        height: story.offsetHeight,
        progress: (window as Window & { __storyProgress?: Record<string, number> }).__storyProgress?.[key],
        scene: story.getAttribute('data-scene') || story.getAttribute('data-s37-scene') || story.getAttribute('data-stage') || '',
        visibleHidden: [...document.querySelectorAll('[hidden]')]
          .filter((element) => getComputedStyle(element).display !== 'none').length,
      }), chapter.key);
      expect(state.progress, `${chapter.key} at ${progress}`).toBeCloseTo(progress, 2);
      expect(state.visibleHidden, `${chapter.key} hidden content`).toBe(0);
      if (stableHeight === null) stableHeight = state.height;
      expect(Math.abs(state.height - stableHeight), `${chapter.key} changed height during scroll`).toBeLessThanOrEqual(2);
      if (progress === 0.5) {
        await page.screenshot({ path: path.join(EVIDENCE, 'desktop-states', 'chapters', `${chapter.file}-1920x1080.png`) });
      }
    }
  }

  await scrollStory(page, '[data-s30-story]', 0.74, 120);
  const forwardScene = await page.locator('[data-s30-stage]').getAttribute('data-scene');
  await scrollStory(page, '[data-s30-story]', 0.24, 120);
  const reverseScene = await page.locator('[data-s30-stage]').getAttribute('data-scene');
  await scrollStory(page, '[data-s30-story]', 0.74, 120);
  await expect(page.locator('[data-s30-stage]')).toHaveAttribute('data-scene', forwardScene || '');
  expect(reverseScene).not.toBe(forwardScene);

  await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }));
  await page.waitForTimeout(100);
  const finale = page.locator('[data-s42-finale]');
  await expect(finale).toBeVisible();
  expect(await finale.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return rect.bottom > 0 && rect.top < window.innerHeight;
  })).toBe(true);
  expect(errors).toEqual([]);
});

test('visible product interactions update only local preview state', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop product interactions');
  const errors = await openLanding(page);

  await scrollStory(page, '[data-s36-story]', 0.9, 500);
  const checklist = page.locator('[data-s36-story] .s35-checklist-items input[type="checkbox"]');
  await expect(checklist).toHaveCount(5);
  await checklist.first().check();
  await expect(page.locator('[data-s36-story] [data-checklist-count]')).toContainText('1 из 5');
  expect(await page.locator('[data-s36-story] .s35-checklist-card').getAttribute('data-completed')).toBe('1');

  await scrollStory(page, '[data-s32-story]', 0.7, 500);
  const analytics = async () => page.locator('[data-s32-story]').evaluate((story) => {
    const value = (name: string) => story.querySelector(`[data-s32-metric="${name}"]`)?.textContent?.trim() || '';
    return {
      works: Number(value('works')),
      attempts: Number(value('attempts')),
      correct: Number(value('correct')),
      accuracy: Number.parseFloat(value('accuracy').replace('%', '').replace(',', '.')),
      chartPaths: story.querySelectorAll('[data-s32-chart] path').length,
    };
  });
  const analyticsForward = await analytics();
  expect(analyticsForward.works).toBeGreaterThan(0);
  expect(analyticsForward.attempts).toBeGreaterThanOrEqual(analyticsForward.correct);
  expect(Math.abs(analyticsForward.accuracy - analyticsForward.correct / analyticsForward.attempts * 100)).toBeLessThan(1);
  expect(analyticsForward.chartPaths).toBeGreaterThan(0);
  await scrollStory(page, '[data-s32-story]', 0.16, 300);
  await scrollStory(page, '[data-s32-story]', 0.7, 500);
  expect(await analytics()).toEqual(analyticsForward);

  await scrollStory(page, '[data-s37-story]', 0.15, 500);
  const week = page.locator('[data-s37-week-label]');
  const originalWeek = await week.textContent();
  await page.locator('[data-s37-week-step="-1"]').click();
  await expect(week).not.toHaveText(originalWeek || '');
  await page.locator('[data-s37-week-today]').click();
  await expect(page.locator('[data-s37-day-title]')).toContainText('Понедельник');
  await page.locator('[data-s37-day="5"]').click();
  await expect(page.locator('[data-s37-day-title]')).toContainText('Суббота');
  await expect(page.locator('[data-s37-day-summary]')).toHaveText('Свободный день');
  await expect(page.locator('[data-s37-card="free"]')).toContainText('Свободный учебный день');
  await expect(page.locator('[data-s37-exiting]')).toHaveCount(0);
  await expect(page.locator('[data-s37-day="5"]')).toHaveAttribute('aria-pressed', 'true');

  await scrollStory(page, '[data-s38-homework]', 0.2, 500);
  await page.locator('[data-homework-view="answer"]').click();
  await expect(page.locator('[data-homework-app]')).toHaveAttribute('data-view', 'answer');
  await page.locator('[data-homework-view="code"]').click();
  await expect(page.locator('[data-homework-app]')).toHaveAttribute('data-view', 'code');
  await page.locator('[data-homework-run]').click();
  await expect(page.locator('.s38-terminal-window pre')).toHaveText('3840000');

  await scrollStory(page, '[data-s39-theory]', 0.05, 500);
  await page.locator('[data-s39-library-item]').first().click();
  await page.locator('[data-s39-open-reading]').first().click();
  await expect(page.locator('[data-s39-theory-app]')).toHaveAttribute('data-focus', 'reading');
  await scrollStory(page, '[data-s39-theory]', 0.35, 500);
  await page.locator('[data-s39-bookmark]').click();
  await expect(page.locator('[data-s39-bookmark]')).toHaveAttribute('aria-pressed', 'true');
  await scrollStory(page, '[data-s39-theory]', 0.65, 500);
  await page.locator('[data-s39-note-input]').fill('Проверить крайние значения');
  await page.locator('[data-s39-save-note]').click();
  await expect(page.locator('[data-s39-note-status]')).toContainText('Проверить крайние значения');
  await scrollStory(page, '[data-s39-theory]', 0.92, 500);
  await page.locator('[data-s39-check-try]').click();
  await page.locator('[data-s39-answer="retry"]').click();
  await expect(page.locator('[data-s39-check-feedback]')).toContainText('Проверь значение score');
  await page.locator('[data-s39-answer="pass"]').click();
  await expect(page.locator('[data-s39-check-feedback]')).toContainText('Верно');
  await expect(page.locator('[data-s39-theory-continue]')).toBeVisible();
  await page.locator('[data-s39-theory-continue]').click();
  await expect(page.locator('[data-s39-theory-foot]')).toHaveText('Спасибо · продолжай знакомство');

  await page.reload({ waitUntil: 'networkidle' });
  await scrollStory(page, '[data-s39-theory]', 0.92, 500);
  await page.locator('[data-s39-check-try]').click();
  await page.getByRole('button', { name: 'Продолжить без ответа' }).click();
  await expect(page.locator('[data-s39-check-feedback]')).toContainText('Проверка пропущена');
  await expect(page.locator('[data-s39-theory-continue]')).toBeVisible();

  await scrollStory(page, '[data-s39-profile]', 0.42, 500);
  await page.locator('[data-s40-award][data-award="first-step"]').click();
  await expect(page.locator('[data-s40-award][data-award="first-step"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('[data-s40-spotlight-note]')).toContainText('Первый шаг');
  await page.locator('[data-s40-award][data-award="first-step"]').click();
  await expect(page.locator('[data-s40-award][data-award="first-step"]')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('[data-s40-spotlight-note]')).toContainText('Коллекция снова собрана целиком');
  await scrollStory(page, '[data-s39-profile]', 0.7, 500);
  await page.locator('[data-s40-copy-code]').click();
  await expect(page.locator('[data-s40-copy-status]')).toContainText('BS-ANNA07K2');
  await scrollStory(page, '[data-s39-profile]', 0.79, 500);
  await page.locator('[data-s40-telegram-preview]').click();
  await expect(page.locator('[data-s40-telegram-preview]')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('[data-s40-telegram-steps]')).toBeVisible();

  const registerLinks = page.locator('a[href="/register"]');
  const telegramLinks = page.locator('a[href="https://t.me/eohada"]');
  expect(await registerLinks.count()).toBeGreaterThan(0);
  expect(await telegramLinks.count()).toBeGreaterThan(0);
  await expect(registerLinks.first()).toHaveAttribute('href', '/register');
  await expect(telegramLinks.first()).toHaveAttribute('href', 'https://t.me/eohada');
  expect(errors).toEqual([]);
});

test('responsive matrix keeps one page scroll and no horizontal overflow', async ({ page }) => {
  const errors = await openLanding(page);
  const viewports = [
    [320, 700], [360, 800], [375, 812], [390, 844], [430, 932],
    [768, 1024], [932, 430], [844, 390],
  ];
  fs.mkdirSync(path.join(EVIDENCE, 'mobile-states'), { recursive: true });
  for (const [width, height] of viewports) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await page.waitForTimeout(90);
    const geometry = await page.evaluate(() => ({
      width: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      scrollRootIsDocument: document.scrollingElement === document.documentElement,
      bodyOverflowY: getComputedStyle(document.body).overflowY,
    }));
    expect(geometry.documentWidth, `${width}x${height} document overflow`).toBeLessThanOrEqual(width + 1);
    expect(geometry.bodyWidth, `${width}x${height} body overflow`).toBeLessThanOrEqual(width + 1);
    expect(geometry.scrollRootIsDocument).toBe(true);
    expect(geometry.bodyOverflowY).not.toBe('hidden');
    await page.screenshot({ path: path.join(EVIDENCE, 'mobile-states', `${width}x${height}-hero.png`) });
  }

  await page.setViewportSize({ width: 390, height: 844 });
  fs.mkdirSync(path.join(EVIDENCE, 'mobile-states', 'chapters'), { recursive: true });
  for (const chapter of CHAPTERS) {
    await scrollStory(page, chapter.selector, 0.5, 500);
    const mobileState = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      hiddenVisible: [...document.querySelectorAll('[hidden]')]
        .filter((element) => getComputedStyle(element).display !== 'none').length,
    }));
    expect(mobileState.documentWidth, `${chapter.key} mobile overflow`).toBeLessThanOrEqual(391);
    expect(mobileState.hiddenVisible, `${chapter.key} mobile hidden content`).toBe(0);
    await page.screenshot({ path: path.join(EVIDENCE, 'mobile-states', 'chapters', `${chapter.file}-390x844.png`) });
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await scrollStory(page, '[data-s32-story]', 0.5, 100);
  const nestedScrollers = await page.evaluate(() => [...document.querySelectorAll('body *')]
    .filter((element) => element.getClientRects().length > 0)
    .filter((element) => ['auto', 'scroll'].includes(getComputedStyle(element).overflowY))
    .filter((element) => element.scrollHeight > element.clientHeight + 2)
    .map((element) => `${element.tagName.toLowerCase()}.${typeof element.className === 'string' ? element.className : ''}`));
  expect(nestedScrollers).toEqual([]);
  expect(errors).toEqual([]);
});

test('scroll stress, resize, pause and lifecycle return stay deterministic', async ({ page, context }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop motion stress');
  const errors = await openLanding(page);

  await scrollStory(page, '[data-s30-story]', 0.42, 100);
  const beforeWheel = await page.evaluate(() => window.scrollY);
  await page.mouse.move(960, 540);
  await page.mouse.wheel(0, 360);
  await page.waitForTimeout(120);
  const afterSlowWheel = await page.evaluate(() => window.scrollY);
  expect(afterSlowWheel).toBeGreaterThan(beforeWheel);
  await page.mouse.wheel(0, 5200);
  await page.waitForTimeout(120);
  const afterFastWheel = await page.evaluate(() => window.scrollY);
  expect(afterFastWheel).toBeGreaterThan(afterSlowWheel + 1000);
  await page.mouse.wheel(0, -4400);
  await page.waitForTimeout(120);
  expect(await page.evaluate(() => window.scrollY)).toBeLessThan(afterFastWheel);

  await scrollStory(page, '[data-s30-story]', 0.55, 100);
  const beforeResize = await page.locator('[data-s30-story]').evaluate((story) => {
    const top = story.getBoundingClientRect().top + window.scrollY;
    return (window.scrollY - top) / Math.max(1, story.offsetHeight - window.innerHeight);
  });
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.waitForTimeout(120);
  const afterResize = await page.locator('[data-s30-story]').evaluate((story) => {
    const top = story.getBoundingClientRect().top + window.scrollY;
    return (window.scrollY - top) / Math.max(1, story.offsetHeight - window.innerHeight);
  });
  expect(afterResize).toBeCloseTo(beforeResize, 1);

  await scrollStory(page, '[data-s30-story]', 0.5, 100);
  const stoppedAt = await page.evaluate(() => window.scrollY);
  const stoppedScene = await page.locator('[data-s30-stage]').getAttribute('data-scene');
  await page.waitForTimeout(650);
  expect(await page.evaluate(() => window.scrollY)).toBe(stoppedAt);
  await expect(page.locator('[data-s30-stage]')).toHaveAttribute('data-scene', stoppedScene || '');

  const lifecycle = await context.newCDPSession(page);
  await lifecycle.send('Page.setWebLifecycleState', { state: 'frozen' });
  await lifecycle.send('Page.setWebLifecycleState', { state: 'active' });
  await page.waitForTimeout(120);
  await scrollStory(page, '[data-s30-story]', 0.74, 20);
  await expect(page.locator('[data-s30-stage]')).toHaveAttribute('data-scene', 'math-tree');

  await scrollStory(page, '[data-s37-story]', 0.52, 500);
  await scrollStory(page, '[data-s37-story]', 0.63, 70);
  await scrollStory(page, '[data-s37-story]', 0.76, 70);
  await scrollStory(page, '[data-s37-story]', 0.63, 70);
  await scrollStory(page, '[data-s37-story]', 0.76, 300);
  const earlyReveal = await page.locator('[data-s37-copy-block="free"]').evaluate((copy) => ({
    hidden: (copy as HTMLElement).hidden,
    moving: copy.closest('[data-s37-story]')?.hasAttribute('data-s37-moving'),
  }));
  expect(earlyReveal.hidden).toBe(true);
  expect(earlyReveal.moving).toBe(true);
  await page.waitForTimeout(180);
  await expect(page.locator('[data-s37-copy-block="free"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test('reduced motion and keyboard access remain usable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openLanding(page, { width: 390, height: 844 });
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
  await page.keyboard.press('Tab');
  await expect(page.locator(':focus')).toHaveClass(/s30-skip/);
  expect(await page.locator(':focus').evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe('none');
  expect(await page.locator('textarea[aria-label], textarea[aria-labelledby], label[for="s39-note-input"]').count()).toBeGreaterThan(0);

  const unnamedButtons = await page.locator('button').evaluateAll((buttons) => buttons
    .filter((button) => !button.innerText.trim() && !button.getAttribute('aria-label') && !button.getAttribute('aria-labelledby') && !button.title)
    .map((button) => button.outerHTML.slice(0, 120)));
  expect(unnamedButtons).toEqual([]);
  const unlabeledImages = await page.locator('img').evaluateAll((images) => images
    .filter((image) => !image.hasAttribute('alt'))
    .map((image) => image.currentSrc));
  expect(unlabeledImages).toEqual([]);
  expect(await page.evaluate(() => document.getAnimations({ subtree: true }).filter((animation) => animation.playState === 'running').length)).toBe(0);

  await scrollStory(page, '[data-s30-story]', 0.75, 40);
  const motion = await page.evaluate(() => ({
    rootOverflow: getComputedStyle(document.body).overflowY,
    activeScene: document.querySelector('[data-s30-stage]')?.getAttribute('data-scene'),
    runningAnimations: document.getAnimations({ subtree: true }).filter((animation) => animation.playState === 'running').length,
  }));
  expect(motion.rootOverflow).not.toBe('hidden');
  expect(motion.activeScene).toBeTruthy();
  expect(motion.runningAnimations).toBe(0);
  expect(errors).toEqual([]);
});

test('mobile schedule accepts a real emulated touch tap', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Touch input check');
  const errors = await openLanding(page, { width: 390, height: 844 });
  await scrollStory(page, '[data-s37-story]', 0.18, 500);
  const day = page.locator('[data-s37-day="5"]');
  await day.scrollIntoViewIfNeeded();
  const box = await day.boundingBox();
  expect(box).not.toBeNull();
  await page.touchscreen.tap(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await expect(page.locator('[data-s37-day-title]')).toContainText('Суббота');
  await expect(page.locator('[data-s37-day-summary]')).toHaveText('Свободный день');
  expect(errors).toEqual([]);
});

test('continuous desktop release walkthrough 1920x1080', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop recording');
  test.setTimeout(90_000);
  await openLanding(page);
  const maxY = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  await page.evaluate(async ({ maxY, duration }) => new Promise<void>((resolve) => {
    let start: number | undefined;
    const step = (now: number) => {
      if (start === undefined) start = now;
      const progress = Math.min(1, (now - start) / duration);
      window.scrollTo({ top: maxY * progress, behavior: 'instant' });
      if (progress < 1) requestAnimationFrame(step);
      else window.setTimeout(resolve, 250);
    };
    requestAnimationFrame(step);
  }), { maxY, duration: 42_000 });
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThanOrEqual(maxY - 2);
});

test('continuous touch-emulated mobile release walkthrough 390x844', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Mobile recording');
  test.setTimeout(90_000);
  await openLanding(page, { width: 390, height: 844 });
  const maxY = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  const touch = await page.context().newCDPSession(page);
  await touch.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  let swipes = 0;
  while ((await page.evaluate(() => window.scrollY)) < maxY - 2 && swipes < 65) {
    await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ id: 1, x: 195, y: 700 }] });
    for (let step = 1; step <= 19; step += 1) {
      await touch.send('Input.dispatchTouchEvent', {
        type: 'touchMove',
        touchPoints: [{ id: 1, x: 195, y: 700 - step * 30 }],
      });
      await page.waitForTimeout(16);
    }
    await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await page.waitForTimeout(180);
    swipes += 1;
  }
  expect(swipes).toBeLessThan(65);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThanOrEqual(maxY - 2);
});
