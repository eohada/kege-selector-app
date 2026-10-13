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

async function openChapter(page: import('@playwright/test').Page, chapter: string) {
  await page.goto('/demo', { waitUntil: 'domcontentloaded' });
  const destination = await page.evaluate(async (chapterId) => {
    await fetch('/demo/api/init', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_name: 'Проверка', grade: '10', goal: 'ege_90', start_at_dashboard: true }),
    });
    const response = await fetch('/demo/api/director', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: chapterId }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'director failed');
    return data.url;
  }, chapter);
  await page.goto(destination, { waitUntil: 'domcontentloaded' });
}

async function expectFixedObjective(page: import('@playwright/test').Page, target: string) {
  const objective = page.locator(`${target}.boo-target-pulse`);
  await expect(objective).toHaveCount(1);
  await expect(page.locator('#boo-focus-hole')).toBeVisible();
  await expect(page.locator('html')).toHaveClass(/boo-objective-lock/);
  expect(await page.locator('#boo-focus-hole').evaluate((node) => getComputedStyle(node).position)).toBe('fixed');
  expect(await objective.evaluate((node) => getComputedStyle(node, '::after').display)).toBe('none');
  const fit = await page.evaluate((selector) => {
    const target = (document.querySelector(selector + '.boo-target-pulse') || document.querySelector(selector))!.getBoundingClientRect();
    const frame = document.querySelector('#boo-focus-hole')!.getBoundingClientRect();
    return {
      left: Math.abs(target.left - frame.left), top: Math.abs(target.top - frame.top),
      right: Math.abs(target.right - frame.right), bottom: Math.abs(target.bottom - frame.bottom),
    };
  }, target);
  expect(Math.max(fit.left, fit.top, fit.right, fit.bottom)).toBeLessThanOrEqual(6);
}

test.describe('BooStudy demo — guided controls across later chapters', () => {
  test('keeps theory and mistakes as a single guided chain without overlapping scenes', async ({ page }) => {
    await openChapter(page, 'chapter_4');
    await page.getByRole('button', { name: 'Показать разбор' }).click();
    await expectFixedObjective(page, '[data-demo-target="theory-material"]');
    await page.locator('[data-demo-target="theory-material"]').click();
    await expect(page.locator('#boo-cinema-mode')).toBeVisible();
    await expect(page.locator('#boo-novel-dialogue')).toBeHidden();
    await page.getByRole('button', { name: 'К работе над ошибками' }).click();
    await expect(page).toHaveURL(/\/submissions/);
    await expect(page.getByRole('button', { name: 'Показать разбор ошибки' })).toBeVisible();
    await page.getByRole('button', { name: 'Показать разбор ошибки' }).click();
    await expectFixedObjective(page, '[data-demo-target="mistake-review"]');
    await page.locator('[data-demo-target="mistake-review"]').click();
    await expect(page.locator('#boo-cinema-mode')).toBeVisible();
    await expect(page.locator('#boo-novel-dialogue')).toBeHidden();
    await expect(page.getByRole('button', { name: 'Исправить ответ' })).toBeVisible();
  });

  test('keeps the route, analytics, schedule and profile controls available', async ({ page }) => {
    await openChapter(page, 'chapter_6');
    await page.getByRole('button', { name: 'Открыть курс' }).click();
    await expectFixedObjective(page, '[data-demo-program-course]');
    await page.locator('[data-demo-program-course]').click();
    await expect(page).toHaveURL(/\/courses\/\d+/);
    await page.getByRole('button', { name: 'Показать модуль' }).click();
    await expectFixedObjective(page, '[data-demo-target="program-module"]');
    await page.locator('[data-demo-target="program-module"]').first().click();
    await expect(page.getByRole('button', { name: 'Вернуться в кабинет' })).toBeVisible();
    await expect(page.locator('#boo-novel-close')).toBeHidden();
    await page.getByRole('button', { name: 'Вернуться в кабинет' }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole('button', { name: 'Открыть аналитику' })).toBeVisible();
  });
});
