import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const ROUTE = '/static/landing-release-candidate-rc3/index.html';
const FOUNDER = '[data-s42-founder]';
const PROFILE = '[data-s39-profile]';

async function openRC3(page: Page, viewport = { width: 1920, height: 1080 }, reducedMotion = false) {
  for (const folder of ['welcome', 'reduced-motion', 'founder', 'profile-after']) fs.mkdirSync(path.resolve('output/landing-release-audit/evidence/rc3', folder), { recursive: true });
  await page.setViewportSize(viewport);
  if (reducedMotion) await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const response = await page.goto(ROUTE, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  expect(response?.status()).toBe(200);
  expect(await page.title()).toBe('BooStudy — Release Candidate 3');
  return errors;
}

async function progressStory(page: Page, selector: string, progress: number) {
  await page.locator(selector).evaluate((story, value) => {
    document.documentElement.style.scrollBehavior = 'auto';
    const top = story.getBoundingClientRect().top + window.scrollY;
    const range = Math.max(1, story.offsetHeight - window.innerHeight);
    window.scrollTo({ top: top + range * value, behavior: 'instant' });
  }, progress);
  await page.waitForTimeout(760);
}

test('welcome offers keyboard-accessible manual and guided entry; manual scroll remains normal', async ({ page }) => {
  const errors = await openRC3(page);
  const welcome = page.locator('#rc3-welcome');
  const manual = page.locator('[data-rc3-choice="manual"]');
  const automatic = page.locator('[data-rc3-choice="auto"]');
  await expect(welcome).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Добро пожаловать в BooStudy!' })).toBeVisible();
  await expect(automatic).toContainText('РЕКОМЕНДУЕМ');
  await expect(automatic).toContainText(/\d+ мин/);
  await expect(automatic).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(manual).toBeFocused();
  await page.screenshot({ path: 'output/landing-release-audit/evidence/rc3/welcome/welcome-desktop-1920x1080.jpg', type: 'jpeg', quality: 90 });

  await manual.click();
  await expect(welcome).toBeHidden();
  await expect(page.locator('[data-rc3-tour-panel]')).toBeHidden();
  await expect(page.locator('[data-rc3-reopen]')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('manual');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowY)).not.toBe('hidden');
  await page.mouse.wheel(0, 520);
  await page.waitForTimeout(180);
  const manualScrollY = await page.evaluate(() => scrollY);
  expect(manualScrollY).toBeGreaterThan(0);

  await page.keyboard.press('Home');
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);
  await page.locator('[data-rc3-reopen]').click();
  await expect(welcome).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(welcome).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('manual');
  expect(await page.evaluate(() => scrollY)).toBe(0);
  expect(errors).toEqual([]);
});

test('guided controls keep a single scroll owner, support seek and restore manual mode', async ({ page }) => {
  const errors = await openRC3(page);
  await page.locator('[data-rc3-choice="auto"]').click();
  const panel = page.locator('[data-rc3-tour-panel]');
  await expect(panel).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-playing');
  await expect.poll(() => page.evaluate(() => scrollY), { timeout: 5000 }).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.phase)).toBe('read');

  await page.locator('[data-rc3-play]').click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-paused');
  const pausedY = await page.evaluate(() => scrollY);
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowY)).toBe('hidden');
  expect(await page.evaluate(() => getComputedStyle(document.body).overflowY)).toBe('hidden');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollbarWidth)).toBe('none');
  await page.mouse.wheel(0, 800);
  await page.keyboard.press('PageDown');
  await page.keyboard.press('ArrowDown');
  await page.mouse.move(1918, 190);
  await page.mouse.down();
  await page.mouse.move(1918, 720, { steps: 4 });
  await page.mouse.up();
  await page.waitForTimeout(240);
  expect(await page.evaluate(() => scrollY)).toBe(pausedY);

  await page.locator('[data-rc3-next]').click();
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.currentIndex)).toBe(1);
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-paused');
  const soughtY = await page.evaluate(() => scrollY);
  expect(soughtY).not.toBe(pausedY);
  await page.locator('[data-rc3-speed]').selectOption('1.25');
  expect(await page.evaluate(() => window.BooStudyGuidedTour?.currentIndex)).toBe(1);
  expect(await page.evaluate(() => scrollY)).toBe(soughtY);

  await page.locator('[data-rc3-restart]').click();
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.currentIndex)).toBe(0);
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-playing');
  await page.locator('[data-rc3-exit]').click();
  await expect(panel).toBeHidden();
  await expect(page.locator('[data-rc3-reopen]')).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('manual');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowY)).not.toBe('hidden');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollbarWidth)).not.toBe('none');
  const exitY = await page.evaluate(() => scrollY);
  await page.mouse.wheel(0, 420);
  await page.waitForTimeout(180);
  expect(await page.evaluate(() => scrollY)).toBeGreaterThan(exitY);
  expect(errors).toEqual([]);
});

test('guided tour preserves its scene across every speed, resize, hidden tab and step controls', async ({ page }) => {
  const errors = await openRC3(page);
  await page.locator('[data-rc3-choice="auto"]').click();
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.phase)).toBe('read');

  for (const speed of ['0.75', '1', '1.25', '1.5']) {
    await page.locator('[data-rc3-speed]').selectOption(speed);
    await expect(page.locator('[data-rc3-speed]')).toHaveValue(speed);
    expect(await page.evaluate(() => window.BooStudyGuidedTour?.currentIndex)).toBe(0);
    expect(await page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-playing');
  }

  await page.locator('[data-rc3-speed]').selectOption('1.5');
  await page.evaluate(() => window.BooStudyGuidedTour?.seek(1));
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.currentIndex)).toBe(1);
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.phase)).toBe('move');
  await page.setViewportSize({ width: 1366, height: 768 });
  await expect.poll(() => page.evaluate(() => innerWidth)).toBe(1366);
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-playing');

  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-paused');
  const hiddenY = await page.evaluate(() => scrollY);
  await page.waitForTimeout(200);
  expect(await page.evaluate(() => scrollY)).toBe(hiddenY);
  await page.evaluate(() => {
    delete (document as Document & { hidden?: boolean }).hidden;
    document.dispatchEvent(new Event('visibilitychange'));
  });
  expect(await page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-paused');

  await page.locator('[data-rc3-play]').click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-playing');
  await page.locator('[data-rc3-play]').click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-paused');
  await page.locator('[data-rc3-prev]').click();
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.currentIndex)).toBe(0);
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-paused');
  await page.locator('[data-rc3-next]').click();
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.currentIndex)).toBe(1);
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-paused');

  await page.locator('[data-rc3-restart]').click();
  await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.currentIndex)).toBe(0);
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-playing');
  await page.locator('[data-rc3-exit]').click();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowY)).not.toBe('hidden');
  expect(errors).toEqual([]);
});

test('reduced-motion preference requires explicit opt-in and uses immediate scene changes', async ({ page }) => {
  const errors = await openRC3(page, { width: 390, height: 844 }, true);
  await expect(page.locator('[data-rc3-choice="manual"]')).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('idle');
  expect(await page.evaluate(() => scrollY)).toBe(0);
  await page.locator('[data-rc3-choice="auto"]').click();
  await expect(page.locator('[data-rc3-tour-panel]')).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('reduced-motion');
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowY)).toBe('hidden');
  await page.screenshot({ path: 'output/landing-release-audit/evidence/rc3/reduced-motion/welcome-reduced-390x844.jpg', type: 'jpeg', quality: 88 });
  await page.locator('[data-rc3-exit]').click();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowY)).not.toBe('hidden');
  expect(errors).toEqual([]);
});

test('Founder motion is visible, autonomous, pause-safe, and remains complete on re-entry', async ({ page }) => {
  const errors = await openRC3(page);
  await page.locator('[data-rc3-choice="manual"]').click();
  await page.locator(FOUNDER).evaluate((founder) => {
    document.documentElement.style.scrollBehavior = 'auto';
    window.scrollTo({ top: founder.getBoundingClientRect().top + window.scrollY, behavior: 'instant' });
  });
  await expect(page.locator(FOUNDER)).toHaveAttribute('data-reveal-state', 'revealing');
  await page.waitForTimeout(560);
  const mid = await page.evaluate(() => ({
    y: scrollY,
    revealed: document.querySelectorAll('[data-s42-founder] [data-s42-reveal].is-revealed').length,
    transform: getComputedStyle(document.querySelector('[data-s42-founder] [data-s42-reveal]')).transform,
    opacity: Number.parseFloat(getComputedStyle(document.querySelector('[data-s42-founder] [data-s42-reveal]')).opacity),
    activeAnimations: document.getAnimations().filter((animation) => animation.playState === 'running' && animation.effect?.target instanceof Element && animation.effect.target.closest('[data-s42-founder]')).length
  }));
  expect(mid.transform).not.toBe('none');
  expect(mid.opacity).toBeGreaterThan(0);
  expect(mid.activeAnimations).toBeGreaterThan(0);
  await page.screenshot({ path: 'output/landing-release-audit/evidence/rc3/founder/founder-early-1920x1080.jpg', type: 'jpeg', quality: 90 });
  await expect(page.locator(FOUNDER)).toHaveAttribute('data-reveal-state', 'complete', { timeout: 7000 });
  expect(await page.locator(`${FOUNDER} [data-s42-reveal].is-revealed`).count()).toBe(8);
  await expect(page.locator(`${FOUNDER} a[href="https://t.me/eohada"]`)).toBeVisible();
  await expect(page.locator(`${FOUNDER} a[href="/register"]`)).toBeVisible();
  await page.screenshot({ path: 'output/landing-release-audit/evidence/rc3/founder/founder-complete-1920x1080.jpg', type: 'jpeg', quality: 90 });
  await page.mouse.wheel(0, 220);
  await page.mouse.wheel(0, -220);
  expect(await page.locator(FOUNDER).getAttribute('data-reveal-state')).toBe('complete');
  expect(await page.locator(`${FOUNDER} [data-s42-reveal].is-revealed`).count()).toBe(8);
  expect(errors).toEqual([]);
});

test('profile final state retains readable copy and card text at desktop and mobile widths', async ({ page }) => {
  const errors = await openRC3(page);
  const evidence = path.resolve('output/landing-release-audit/evidence/rc3/profile-after');
  fs.mkdirSync(evidence, { recursive: true });
  for (const viewport of [
    { name: '1920x1080', width: 1920, height: 1080 },
    { name: '1366x768', width: 1366, height: 768 },
    { name: '390x844', width: 390, height: 844 },
    { name: '320x700', width: 320, height: 700 }
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(ROUTE, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    if (await page.locator('#rc3-welcome').isVisible()) await page.locator('[data-rc3-choice="manual"]').click();
    await progressStory(page, PROFILE, 1);
    const state = await page.locator(PROFILE).evaluate((profile) => {
      const visibleCards = [...profile.querySelectorAll('.s40-profile-card[data-profile-region]')].filter((card) => getComputedStyle(card).display !== 'none');
      return {
        focus: profile.querySelector('.s40-profile-app')?.getAttribute('data-focus'),
        widths: [document.documentElement.scrollWidth, innerWidth],
        regions: visibleCards.map((card) => ({
          name: card.getAttribute('data-profile-region'),
          rect: (() => { const r = card.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, width: r.width }; })(),
          scrollHeight: card.scrollHeight,
          clientHeight: card.clientHeight,
          overflow: getComputedStyle(card).overflow,
          text: card.innerText
        })),
        clippedCopy: visibleCards.flatMap((card) => [...card.querySelectorAll('p, .s40-award-copy small')]
          .filter((copy) => copy.scrollHeight > copy.clientHeight + 2)
          .map((copy) => ({ region: card.getAttribute('data-profile-region'), text: copy.innerText }))),
        xp: profile.querySelector('[data-profile-region="xp"]')?.innerText,
        xpFont: getComputedStyle(profile.querySelector('.s40-xp-ledger span')).fontSize,
        awardFont: getComputedStyle(profile.querySelector('.s40-award-copy small')).fontSize,
        lineClamp: getComputedStyle(profile.querySelector('.s40-award-copy small')).webkitLineClamp,
        frameRect: (() => { const r = profile.querySelector('.s39-frame').getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; })()
      };
    });
    expect(state.focus).toBe('complete');
    expect(state.widths[0]).toBeLessThanOrEqual(state.widths[1]);
    expect(state.regions.map((card) => card.name)).toEqual(['identity', 'xp', 'achievements', 'streak', 'time', 'referral', 'telegram']);
    expect(state.clippedCopy).toEqual([]);
    expect(state.xp).toContain('765');
    expect(state.xp).toContain('810 XP');
    expect(state.xp).toContain('45 XP');
    for (const source of ['170 XP', '280 XP', '60 XP', '155 XP', '100 XP']) expect(state.xp).toContain(source);
    expect(Number.parseFloat(state.xpFont)).toBeGreaterThanOrEqual(9);
    expect(Number.parseFloat(state.awardFont)).toBeGreaterThanOrEqual(7);
    expect(state.lineClamp).not.toBe('2');
    await page.screenshot({ path: path.join(evidence, `profile-complete-${viewport.name}.jpg`), type: 'jpeg', quality: 90 });
  }
  expect(errors).toEqual([]);
});

test('tour manifest covers all eight product chapters and founder is its final stop', async ({ page }) => {
  await openRC3(page);
  const result = await page.evaluate(() => {
    const manifest = window.BooStudyGuidedTour?.manifest || [];
    const theory = manifest.filter((item) => item.chapter === 'theory');
    return { count: manifest.length, chapters: [...new Set(manifest.map((item) => item.chapter))], last: manifest.at(-1)?.id, uniqueIds: new Set(manifest.map((item) => item.id)).size, theory: theory.map((item) => ({ id: item.id, root: item.root })) };
  });
  expect(result.chapters).toEqual(['hero', 'homework', 'analytics', 'dashboard', 'schedule', 'theory', 'profile', 'founder']);
  expect(result.last).toBe('founder-story');
  expect(result.uniqueIds).toBe(result.count);
  expect(result.count).toBe(34);
  expect(result.theory).toEqual(['library', 'structure', 'reading', 'bookmark', 'notes', 'progress', 'check'].map((stage) => ({ id: `theory-${stage}`, root: '[data-s39-theory]' })));
});

test('guided tour visits every live Theory OS state without submitting a microcheck answer', async ({ page }) => {
  const errors = await openRC3(page);
  await page.locator('[data-rc3-choice="auto"]').click();
  const stages = await page.evaluate(() => window.BooStudyGuidedTour.manifest
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.chapter === 'theory')
    .map(({ item, index }) => ({ stage: item.id.slice('theory-'.length), index })));
  for (const episode of stages) {
    await page.evaluate((index) => window.BooStudyGuidedTour.seek(index), episode.index);
    await expect.poll(() => page.locator('[data-s39-theory]').getAttribute('data-stage'), { timeout: 7000 }).toBe(episode.stage);
  }
  await expect(page.locator('[data-s39-check-invite]')).toBeVisible();
  await expect(page.locator('[data-s39-check-question]')).toBeHidden();
  await expect(page.locator('[data-s39-check-feedback]')).toHaveText('Ответ по желанию. Попробуй предсказать результат или пропусти.');
  await page.locator('[data-rc3-exit]').click();
  expect(errors).toEqual([]);
});

test('landing remains available in manual mode when JavaScript is disabled', async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 }, javaScriptEnabled: false });
  const response = await page.goto(ROUTE, { waitUntil: 'networkidle' });
  expect(response?.status()).toBe(200);
  await expect(page.locator('#s30-hero-title')).toBeVisible();
  await expect(page.locator('#rc3-welcome')).toBeHidden();
  await expect(page.locator('#s30-hero-title').locator('xpath=ancestor::section').getByRole('link', { name: /Создать аккаунт/ })).toHaveAttribute('href', '/register');
  await page.close();
});

test('mobile touch and page keys stay locked while the guided controller keeps moving', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  try {
    const errors = await openRC3(page, { width: 390, height: 844 });
    await page.locator('[data-rc3-choice="auto"]').click();
    await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.phase)).toBe('read');
    const heldY = await page.evaluate(() => scrollY);
    await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
    for (const key of ['PageDown', 'ArrowDown', ' ', 'Home', 'End']) await page.keyboard.press(key);
    const session = await context.newCDPSession(page);
    await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 200, y: 560 }] });
    await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 200, y: 170 }] });
    await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await page.waitForTimeout(180);
    expect(await page.evaluate(() => scrollY)).toBe(heldY);
    expect(await page.evaluate(() => document.documentElement.dataset.rc3TourState)).toBe('auto-playing');
    await expect.poll(() => page.evaluate(() => window.BooStudyGuidedTour?.currentIndex), { timeout: 16000 }).toBeGreaterThan(0);
    expect(await page.evaluate(() => scrollY)).not.toBe(heldY);
    expect(errors).toEqual([]);
    await session.detach();
  } finally {
    await context.close();
  }
});
