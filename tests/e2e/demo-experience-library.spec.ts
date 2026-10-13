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

test.describe('BooStudy Experience — Chapter 4', () => {
  test('opens the live algorithm-tracing article and saves a checkpoint answer', async ({ page }, testInfo) => {
    await page.goto('/demo');
    const state = await page.evaluate(async () => {
      const response = await fetch('/demo/api/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_name: 'Саша', exam: 'ege', goal: 'ege' }),
      });
      return (await response.json()).state;
    });

    await page.goto(state.theory_url);
    await expect(page.locator('#theory-article')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Трассировка алгоритма: как читать программу по шагам' }).first()).toBeVisible();

    const checkpoint = page.locator('[data-checkpoint-key="algorithm-branch"]');
    await checkpoint.getByRole('button', { name: 'Прибавить 1' }).click();
    await expect(checkpoint.getByText('Верно.')).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('demo-chapter4-library.png'), fullPage: true });
  });
});
