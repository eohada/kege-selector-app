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

async function openTrial(page: import('@playwright/test').Page) {
  await page.goto('/demo');
  await page.evaluate(async () => {
    await fetch('/demo/api/init', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_name: 'Саша', grade: '10', goal: 'ege_90', start_at_dashboard: true }),
    });
    await fetch('/demo/api/director', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: 'chapter_3' }),
    });
  });
  await page.goto('/dashboard', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Открыть первое испытание' }).click();
  await page.getByRole('button', { name: 'Выбрать способ решения' }).click();
}

test.describe('BooStudy demo v5 — first trial', () => {
  test('guards a detour and returns focus to the selected answer task', async ({ page }) => {
    await openTrial(page);
    await page.getByRole('button', { name: 'Режим «Ответ»' }).click();
    await page.getByRole('button', { name: 'Показать поле ответа' }).click();
    await page.locator('a[href="/theory"]:visible').click();
    await expect(page.locator('#boo-novel-dialogue')).toBeVisible();
    await page.locator('#boo-novel-close').click();
    await expect(page.locator('#tw-answer')).toBeFocused();
  });

  test('guides the code mode through its own runnable mini-task', async ({ page }) => {
    await openTrial(page);
    await page.getByRole('button', { name: 'Режим «Код»' }).click();
    await expect(page.locator('#boo-novel-dialogue')).toBeVisible();
    await expect(page.locator('#boo-novel-text')).toContainText('отдельная мини-задача');
    await page.getByRole('button', { name: 'Показать редактор' }).click();
    await expect(page.locator('#tw-code')).toBeFocused();
    await expect(page.locator('#tw-task-panel')).toContainText('marks = [3, 1, 4, 1, 5]');
    await expect(page.locator('#tw-run')).toHaveClass(/boo-target-pulse/);
  });

  test('supports one hint, a retry, and then a standalone solution scene', async ({ page }) => {
    await openTrial(page);
    await page.getByRole('button', { name: 'Режим «Ответ»' }).click();
    await page.getByRole('button', { name: 'Показать поле ответа' }).click();

    const answer = page.locator('#tw-answer');
    await answer.fill('4');
    await page.locator('#tw-submit-work').click();
    await expect(page.locator('#boo-novel-text')).toContainText('На четвёртой команде DOWN');
    await page.getByRole('button', { name: 'Попробовать ещё раз' }).click();
    await expect(answer).toBeFocused();

    await answer.fill('5');
    await page.locator('#tw-submit-work').click();
    await expect(page.locator('#boo-cinema-mode')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Первое испытание пройдено!' })).toBeVisible();
    await expect(page.locator('#boo-novel-dialogue')).toBeHidden();

    await page.getByRole('button', { name: 'Посмотреть решение' }).click();
    await expect(page.locator('#boo-novel-dialogue')).toBeVisible();
    await expect(page.locator('#boo-novel-text')).toContainText('Смотри на ход по строкам');
    await expect(page.getByRole('button', { name: 'Перейти к работе над ошибками' })).toBeVisible();
  });
});
