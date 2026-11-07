import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const LANDING = '/static/landing-release-candidate-rc2/index.html';
const EVIDENCE = path.resolve(process.cwd(), 'output/landing-release-audit/evidence/rc2');
const SCHEDULE = '[data-s37-story]';

async function openLanding(page: Page, viewport = { width: 1920, height: 1080 }) {
  await page.setViewportSize(viewport);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  const response = await page.goto(LANDING, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  expect(response?.status()).toBe(200);
  expect(await page.title()).toBe('BooStudy — Release Candidate 2');
  expect(await page.locator('meta[name="robots"]').getAttribute('content')).toBe('noindex, nofollow');
  return errors;
}

async function scrollStory(page: Page, selector: string, progress: number, settleMs = 450) {
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

async function scheduleState(page: Page, progress: number, settleMs = 450) {
  await scrollStory(page, SCHEDULE, progress, settleMs);
  return page.locator(SCHEDULE).evaluate((story) => {
    const events = story.querySelector('[data-s37-events]');
    const activeCopies = [...story.querySelectorAll<HTMLElement>('[data-s37-copy-block]')]
      .filter((copy) => !copy.hidden);
    const selected = [...story.querySelectorAll<HTMLElement>('[data-s37-day].is-active')];
    const liveCards = [...story.querySelectorAll<HTMLElement>('[data-s37-card]:not([data-s37-exiting])')];
    const exitingCards = [...story.querySelectorAll<HTMLElement>('[data-s37-card][data-s37-exiting]')];
    const focusedCards = [...story.querySelectorAll<HTMLElement>('[data-s37-card].is-focused')];
    return {
      scene: story.dataset.s37Scene,
      side: story.dataset.s37Side,
      phase: story.dataset.s37Phase,
      manual: story.dataset.s37Manual === 'true',
      moving: story.hasAttribute('data-s37-moving'),
      copy: activeCopies.map((copy) => copy.dataset.s37CopyBlock),
      selectedDay: selected[0]?.dataset.s37Day,
      dayTitle: story.querySelector('[data-s37-day-title]')?.textContent?.trim(),
      week: story.querySelector('[data-s37-week-label]')?.textContent?.trim(),
      cards: liveCards.map((card) => card.dataset.s37Card),
      exiting: exitingCards.map((card) => card.dataset.s37Card),
      focused: focusedCards.map((card) => card.dataset.s37Card),
      eventsFocus: events?.getAttribute('data-focus') || '',
      contextVisible: story.querySelector('[data-s37-context]')?.classList.contains('is-visible') || false,
    };
  });
}

test('RC2 schedule keeps day, cards, copy and spotlight in one causal story', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop schedule state matrix');
  const errors = await openLanding(page);
  const samples = [
    { p: 0, scene: 'week', day: '2', title: 'Среда, 4 ноября', cards: ['lesson-wed-a', 'lesson-wed-b'], copy: 'week', focused: [] },
    { p: 0.15, scene: 'day', day: '2', title: 'Среда, 4 ноября', cards: ['lesson-wed-a', 'lesson-wed-b'], copy: 'day', focused: [] },
    { p: 0.165, scene: 'day', day: '3', title: 'Четверг, 5 ноября', cards: ['lesson-thu'], copy: 'day', focused: [] },
    { p: 0.32, scene: 'lesson', day: '3', title: 'Четверг, 5 ноября', cards: ['lesson-thu'], copy: 'lesson', focused: ['lesson-thu'] },
    { p: 0.45, scene: 'context', day: '3', title: 'Четверг, 5 ноября', cards: ['lesson-thu'], copy: 'context', focused: ['lesson-thu'], contextVisible: true },
    { p: 0.56, scene: 'homework', day: '4', title: 'Пятница, 6 ноября', cards: ['homework-fri'], copy: 'homework', focused: [] },
    { p: 0.64, scene: 'homework', day: '4', title: 'Пятница, 6 ноября', cards: ['homework-fri'], copy: 'homework', focused: ['homework-fri'] },
    { p: 0.72, scene: 'free', day: '6', title: 'Воскресенье, 8 ноября', cards: ['free'], copy: 'free', focused: [] },
    { p: 0.8, scene: 'free', day: '6', title: 'Воскресенье, 8 ноября', cards: ['free'], copy: 'free', focused: ['free'] },
    { p: 0.9, scene: 'overview', day: '2', title: 'Среда, 4 ноября', cards: ['lesson-wed-a', 'lesson-wed-b'], copy: 'overview', focused: [] },
  ];

  const atlasDir = path.join(EVIDENCE, 'schedule-state-matrix');
  fs.mkdirSync(atlasDir, { recursive: true });
  for (const sample of samples) {
    const state = await scheduleState(page, sample.p);
    expect(state.scene, `scene at ${sample.p}`).toBe(sample.scene);
    expect(state.side, `stable text/product composition at ${sample.p}`).toBe('right');
    expect(state.copy, `one active narrative at ${sample.p}`).toEqual([sample.copy]);
    expect(state.selectedDay, `selected date at ${sample.p}`).toBe(sample.day);
    expect(state.dayTitle, `date label at ${sample.p}`).toBe(sample.title);
    expect(state.cards, `events for selected date at ${sample.p}`).toEqual(sample.cards);
    expect(state.focused, `spotlight target at ${sample.p}`).toEqual(sample.focused);
    expect(state.exiting, `settled event transition at ${sample.p}`).toEqual([]);
    expect(state.moving, `no delayed side transition at ${sample.p}`).toBe(false);
    if (sample.contextVisible !== undefined) expect(state.contextVisible).toBe(sample.contextVisible);
    if ([0, 0.165, 0.32, 0.45, 0.56, 0.64, 0.72, 0.8, 0.9].includes(sample.p)) {
      await page.screenshot({ path: path.join(atlasDir, `schedule-${String(Math.round(sample.p * 1000)).padStart(3, '0')}.jpg`), type: 'jpeg', quality: 82 });
    }
  }
  expect(errors).toEqual([]);
});

test('manual date and week controls hold within an episode and return at the next boundary', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop manual control regression');
  const errors = await openLanding(page);
  await scheduleState(page, 0.32);
  await page.locator('[data-s37-day="0"]').click();
  await page.waitForTimeout(350);
  let state = await page.locator(SCHEDULE).evaluate((story) => ({
    day: story.querySelector('[data-s37-day].is-active')?.getAttribute('data-s37-day'),
    title: story.querySelector('[data-s37-day-title]')?.textContent?.trim(),
    copy: story.querySelector('[data-s37-copy-block]:not([hidden])')?.getAttribute('data-s37-copy-block'),
    manual: story.dataset.s37Manual,
    focused: story.querySelectorAll('[data-s37-card].is-focused').length,
  }));
  expect(state).toMatchObject({ day: '0', title: 'Понедельник, 2 ноября', copy: 'day', manual: 'true', focused: 0 });

  await page.locator('[data-s37-week-step="1"]').click();
  await page.waitForTimeout(350);
  state = await page.locator(SCHEDULE).evaluate((story) => ({
    day: story.querySelector('[data-s37-day].is-active')?.getAttribute('data-s37-day'),
    title: story.querySelector('[data-s37-day-title]')?.textContent?.trim(),
    week: story.querySelector('[data-s37-week-label]')?.textContent?.trim(),
    manual: story.dataset.s37Manual,
  }));
  expect(state).toMatchObject({ day: '0', title: 'Понедельник, 9 ноября', week: '9 — 15 ноября 2026', manual: 'true' });
  await scrollStory(page, SCHEDULE, 0.36, 80);
  await expect(page.locator('[data-s37-day-title]')).toHaveText('Понедельник, 9 ноября');

  await scrollStory(page, SCHEDULE, 0.405, 500);
  await expect(page.locator('[data-s37-copy-block="context"]')).toBeVisible();
  await expect(page.locator('[data-s37-day-title]')).toHaveText('Четверг, 12 ноября');
  await expect(page.locator('[data-s37-card="lesson-thu"]')).toHaveClass(/is-focused/);
  await expect(page.locator(SCHEDULE)).not.toHaveAttribute('data-s37-manual', 'true');

  await page.locator('[data-s37-week-today]').click();
  await page.waitForTimeout(350);
  await expect(page.locator('[data-s37-day-title]')).toHaveText('Понедельник, 2 ноября');
  await expect(page.locator('[data-s37-copy-block="day"]')).toBeVisible();
  await scrollStory(page, SCHEDULE, 0.45, 80);
  await expect(page.locator('[data-s37-day-title]')).toHaveText('Понедельник, 2 ноября');
  await scrollStory(page, SCHEDULE, 0.56, 500);
  await expect(page.locator('[data-s37-day-title]')).toHaveText('Пятница, 6 ноября');
  await expect(page.locator('[data-s37-card="homework-fri"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test('reverse and fast scrolling restore a stable schedule state', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop reverse and fast scroll regression');
  const errors = await openLanding(page);
  let state = await scheduleState(page, 0.64);
  expect(state.cards).toEqual(['homework-fri']);
  expect(state.focused).toEqual(['homework-fri']);
  state = await scheduleState(page, 0.53);
  expect(state.scene).toBe('context');
  expect(state.dayTitle).toBe('Четверг, 5 ноября');
  expect(state.cards).toEqual(['lesson-thu']);
  expect(state.focused).toEqual([]);
  state = await scheduleState(page, 0.56);
  expect(state.dayTitle).toBe('Пятница, 6 ноября');
  expect(state.cards).toEqual(['homework-fri']);
  state = await scheduleState(page, 0.53);
  expect(state.dayTitle).toBe('Четверг, 5 ноября');

  await scheduleState(page, 0.95, 40);
  state = await scheduleState(page, 0.05, 500);
  expect(state).toMatchObject({ scene: 'week', selectedDay: '2', cards: ['lesson-wed-a', 'lesson-wed-b'], focused: [], exiting: [], moving: false });
  expect(errors).toEqual([]);
});

test('profile completion keeps its copy and product geometry on screen', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Desktop profile continuity regression');
  const errors = await openLanding(page);
  const profile = '[data-s39-profile]';
  const capture = async (progress: number, name: string) => {
    await scrollStory(page, profile, progress, 520);
    await page.screenshot({ path: path.join(EVIDENCE, 'profile-continuity', `${name}-1920x1080.png`) });
    return page.locator(profile).evaluate((story) => {
      const layout = story.querySelector('.s39-layout')!;
      const frame = story.querySelector('.s39-profile-frame')!;
      const copy = story.querySelector<HTMLElement>('[data-s39-profile-copy-step]:not([hidden])');
      const box = (node: Element) => {
        const r = node.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      };
      return {
        stage: (story as HTMLElement).dataset.stage,
        layout: box(layout),
        frame: box(frame),
        copy: copy ? { key: copy.getAttribute('data-s39-profile-copy-step'), display: getComputedStyle(copy).display, box: box(copy) } : null,
        focus: story.querySelector('[data-s39-profile-app]')?.getAttribute('data-focus'),
      };
    });
  };
  fs.mkdirSync(path.join(EVIDENCE, 'profile-continuity'), { recursive: true });
  const before = await capture(0.83, 'before-complete');
  const after = await capture(0.85, 'complete');
  expect(before.stage).toBe('telegram');
  expect(after.stage).toBe('complete');
  expect(after.copy).toMatchObject({ key: 'complete', display: 'block' });
  expect(after.focus).toBe('complete');
  expect(Math.abs(after.layout.x - before.layout.x)).toBeLessThan(3);
  expect(Math.abs(after.layout.width - before.layout.width)).toBeLessThan(3);
  expect(Math.abs(after.frame.x - before.frame.x)).toBeLessThan(3);
  expect(Math.abs(after.frame.width - before.frame.width)).toBeLessThan(3);
  expect(after.copy!.box.x + after.copy!.box.width).toBeLessThan(after.frame.x);
  expect(errors).toEqual([]);
});

test('responsive schedule fits required viewport sizes', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Responsive viewport matrix');
  const errors = await openLanding(page);
  const sizes = [
    { width: 320, height: 700 },
    { width: 375, height: 812 },
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1366, height: 768 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ];
  const dir = path.join(EVIDENCE, 'responsive');
  fs.mkdirSync(dir, { recursive: true });
  for (const size of sizes) {
    await page.setViewportSize(size);
    await scrollStory(page, SCHEDULE, 0.45, 350);
    const geometry = await page.evaluate(() => ({
      viewport: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      cards: [...document.querySelectorAll('[data-s37-card]:not([data-s37-exiting])')].map((card) => {
        const r = card.getBoundingClientRect();
        return { left: r.left, right: r.right };
      }),
    }));
    expect(geometry.documentWidth, `document overflow at ${size.width}x${size.height}`).toBeLessThanOrEqual(size.width);
    expect(geometry.bodyWidth, `body overflow at ${size.width}x${size.height}`).toBeLessThanOrEqual(size.width);
    expect(geometry.cards.every((card) => card.left >= -1 && card.right <= size.width + 1), `schedule card outside viewport at ${size.width}x${size.height}`).toBe(true);
    await page.screenshot({ path: path.join(dir, `schedule-${size.width}x${size.height}.jpg`), type: 'jpeg', quality: 80 });
  }
  expect(errors).toEqual([]);
});

test('reduced motion keeps all schedule copy and controls available', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', 'Reduced motion regression');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openLanding(page);
  const state = await page.locator(SCHEDULE).evaluate((story) => ({
    copies: [...story.querySelectorAll<HTMLElement>('[data-s37-copy-block]')].filter((copy) => !copy.hidden).length,
    days: story.querySelectorAll('[data-s37-day]').length,
    activeDay: story.querySelector('[data-s37-day].is-active')?.getAttribute('data-s37-day'),
    focus: story.querySelector('[data-s37-events]')?.getAttribute('data-focus') || '',
    runningAnimations: document.getAnimations({ subtree: true }).filter((animation) => animation.playState === 'running').length,
  }));
  expect(state.copies).toBe(8);
  expect(state.days).toBe(7);
  expect(state.activeDay).toBe('2');
  expect(state.focus).toBe('');
  expect(state.runningAnimations).toBe(0);
  expect(errors).toEqual([]);
});

test('mobile date selection remains a touch interaction', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Touch input regression');
  const errors = await openLanding(page, { width: 390, height: 844 });
  await scrollStory(page, SCHEDULE, 0.18, 350);
  const day = page.locator('[data-s37-day="5"]');
  await day.scrollIntoViewIfNeeded();
  const box = await day.boundingBox();
  expect(box).not.toBeNull();
  await page.touchscreen.tap(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await expect(page.locator('[data-s37-day-title]')).toHaveText('Суббота, 7 ноября');
  await expect(page.locator('[data-s37-day-summary]')).toHaveText('Свободный день');
  await expect(page.locator('[data-s37-copy-block="day"]')).toBeVisible();
  await expect(page.locator(SCHEDULE)).toHaveAttribute('data-s37-manual', 'true');
  expect(errors).toEqual([]);
});
