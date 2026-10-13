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

test.describe('BooStudy demo v5 — finale controls', () => {
  test('opens one accessible intro-request form and returns safely to the finale', async ({ page }) => {
    await page.goto('/demo', { waitUntil: 'domcontentloaded' });
    const ready = await page.evaluate(async () => {
      await fetch('/demo/api/init', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_name: 'Марина', grade: '10', goal: 'choosing', start_at_dashboard: true }),
      });
      const response = await fetch('/demo/api/director', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter: 'chapter_10' }),
      });
      return response.ok;
    });
    expect(ready).toBe(true);

    await page.goto('/workspace/profile', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#boo-finale-mode')).toBeVisible();
    await expect(page.getByText('Теперь ты видел не обещание, а путь', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Оставить заявку на вводный урок' }).click();
    const form = page.locator('#boo-intro-request');
    await expect(form).toBeVisible();
    await expect(form.locator('[name="name"]')).toHaveValue('Марина');
    await expect(form.locator('[name="grade"]')).toHaveValue('10');
    await expect(form.locator('[name="goal"]')).toHaveValue('пока выбираю');

    await page.getByRole('button', { name: 'Назад к вариантам' }).click();
    await expect(form).toBeHidden();

    await page.getByRole('button', { name: 'Оставить заявку на вводный урок' }).click();
    await form.locator('[name="contact"]').fill('@marina');
    await form.locator('[name="consent"]').check();
    await page.route('**/demo/api/request', async (route) => {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: true, existing: false, request_id: 42 }) });
    });
    await form.getByRole('button', { name: 'Отправить заявку' }).click();
    await expect(page.locator('#boo-request-followup')).toBeVisible();
    await expect(form.getByText('Заявка у меня. Отвечу в Telegram.')).toBeVisible();

    await page.getByRole('button', { name: 'К финалу' }).click();
    await expect(form).toBeHidden();
    await expect(page.locator('#boo-finale-mode')).toBeVisible();
  });

  test('restores the active finale after a refresh instead of replaying earlier scenes', async ({ page }) => {
    await page.goto('/demo', { waitUntil: 'domcontentloaded' });
    const ready = await page.evaluate(async () => {
      await fetch('/demo/api/init', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_name: 'Илья', grade: '11', goal: 'ege_90', start_at_dashboard: true }),
      });
      const response = await fetch('/demo/api/director', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter: 'chapter_10' }),
      });
      return response.ok;
    });
    expect(ready).toBe(true);

    await page.goto('/workspace/profile', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#boo-finale-mode')).toBeVisible();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#boo-finale-mode')).toBeVisible();
    await expect(page.getByText('Теперь ты видел не обещание, а путь', { exact: true })).toBeVisible();
  });
});
