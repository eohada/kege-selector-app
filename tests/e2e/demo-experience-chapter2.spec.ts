import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
      const headers = new Headers(init.headers || {});
      const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
      if (token) headers.set('X-CSRFToken', token);
      return originalFetch(input, { ...init, headers });
    };
  });
});

async function startDemo(page: import('@playwright/test').Page) {
  await page.goto('/demo', { waitUntil: 'domcontentloaded' });
  await page.locator('.choice').first().click();
  await page.locator('#continue').click();
  await page.locator('#name').fill('Саша');
  await page.locator('#grade').selectOption('10');
  await page.locator('#to-goal').click();
  await page.getByLabel('ЕГЭ 90+').check();
  await page.locator('#start').click();
  await expect(page).toHaveURL(/\/dashboard/);
}

test.describe('BooStudy demo v5 — welcome and cabinet tour', () => {
  test('keeps the welcome scene responsive without an unexplained mission plaque', async ({ page }) => {
    await page.goto('/demo', { waitUntil: 'domcontentloaded' });
    await page.evaluate(async () => {
      localStorage.removeItem('boostudy_demo_state_v1');
      await fetch('/demo/api/exit', { method: 'POST' });
    });
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await page.goto('/demo', { waitUntil: 'domcontentloaded' });
      await expect(page.getByRole('heading', { name: 'О! Кажется, у нас гость!' })).toBeVisible();
      await expect(page.getByText('Что ты хочешь узнать о BooStudy прямо сейчас?')).toBeVisible();
      const dimensions = await page.evaluate(() => ({
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }));
      expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.width + 1);
    }
  });

  test('keeps the welcome screen on the single guided route', async ({ page }) => {
    await page.goto('/demo', { waitUntil: 'domcontentloaded' });
    await page.locator('.choice').first().click();
    await page.locator('#continue').click();
    await page.locator('#name').fill('Свободный просмотр');
    await page.locator('#grade').selectOption('10');
    await page.locator('#to-goal').click();
    await page.getByLabel('ЕГЭ 90+').check();
    await expect(page.locator('#explore')).toHaveCount(0);
    await expect(page.locator('#start')).toBeVisible();
  });

  test('uses the director to open the actual page for every later chapter', async ({ page }) => {
    await page.goto('/demo?director=1', { waitUntil: 'domcontentloaded' });
    const destinations = await page.evaluate(async () => {
      const post = (url: string, body: unknown) => fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      await post('/demo/api/init', { student_name: 'Режиссёр', start_at_dashboard: true });
      const chapters = ['chapter_4', 'chapter_5', 'chapter_6', 'chapter_7', 'chapter_8', 'chapter_9', 'chapter_10'];
      const entries: Record<string, string> = {};
      for (const chapter of chapters) {
        const response = await post('/demo/api/director', { chapter });
        entries[chapter] = (await response.json()).url;
      }
      return entries;
    });
    expect(destinations.chapter_4).toContain('/theory/topic/');
    expect(destinations.chapter_5).toBe('/submissions');
    expect(destinations.chapter_6).toContain('/student/');
    expect(destinations.chapter_7).toContain('/student/');
    expect(destinations.chapter_8).toContain('/schedule');
    expect(destinations.chapter_9).toBe('/workspace/profile');
    expect(destinations.chapter_10).toBe('/workspace/profile');
  });

  test('walks one precise path through program, a completed lesson, and works', async ({ page }) => {
    await startDemo(page);
    await expect(page.locator('#boo-novel-dialogue')).toBeVisible();
    await page.locator('#boo-novel-close').click();
    await expect(page.locator('[data-demo-target="learning-program"]')).toHaveClass(/boo-target-pulse/);
    await expect(page.locator('#boo-focus-hole')).toBeVisible();
    await expect(page.locator('html')).toHaveClass(/boo-objective-lock/);
    expect(await page.locator('.boo-target-pulse').evaluate((node) => getComputedStyle(node, '::after').display)).toBe('none');
    await page.locator('[data-demo-target="learning-program"]').click();
    await expect(page).toHaveURL(/\/courses/);
    await page.getByRole('button', { name: 'Открыть мой курс' }).click();
    await page.locator('[data-demo-program-course]').click();
    await expect(page).toHaveURL(/\/courses\/\d+/);
    await page.getByRole('button', { name: 'Показать модуль' }).click();
    await page.locator('[data-demo-target="program-module"]').first().click();
    await expect(page.locator('#boo-novel-close')).toBeHidden();
    await page.getByRole('button', { name: 'Вернуться в кабинет' }).click();
    await expect(page).toHaveURL(/\/dashboard/);

    await page.locator('#boo-novel-close').click();
    const pastLesson = page.locator('[data-demo-target="past-lesson"]');
    await expect(pastLesson).toHaveClass(/boo-target-pulse/);
    await pastLesson.click();
    await expect(page).toHaveURL(/\/lesson\/\d+\/room/, { timeout: 15000 });
    await expect(page.getByText('Комната ожидания урока')).toHaveCount(0);
    await page.locator('#boo-novel-close').click();
    await page.locator('[data-demo-target="lesson-room-tour"]').click();
    await expect(page.locator('#boo-novel-close')).toBeHidden();
    await page.getByRole('button', { name: 'Вернуться в кабинет' }).click();
    await expect(page).toHaveURL(/\/dashboard/);

    await page.locator('#boo-novel-close').click();
    await expect(page.locator('[data-demo-target="recent-assignments"]')).toHaveClass(/boo-target-pulse/);
    await page.locator('[data-demo-target="recent-assignments"]').click();
    await expect(page.locator('#boo-cinema-mode')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Открыть первое испытание' })).toBeVisible();
  });
});
