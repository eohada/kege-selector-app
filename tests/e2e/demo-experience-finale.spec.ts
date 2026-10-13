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

async function moveDirector(page: import('@playwright/test').Page, chapter: string) {
  await page.goto('/demo', { waitUntil: 'domcontentloaded' });
  const destination = await page.evaluate(async (chapterId) => {
    await fetch('/demo/api/init', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_name: 'Саша', grade: '10', goal: 'ege_90', start_at_dashboard: true }),
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

test.describe('BooStudy demo v5 — final product scenes', () => {
  test('explains analytics as an information screen and keeps the next action singular', async ({ page }) => {
    await moveDirector(page, 'chapter_7');
    await expect(page.locator('#boo-novel-dialogue')).toBeVisible();
    await expect(page.locator('#boo-novel-text')).toContainText('Это не задание');
    await page.getByRole('button', { name: 'Показать прогресс' }).click();
    await expect(page.locator('[data-demo-target="analytics-progress"]')).toHaveClass(/boo-target-pulse/);
    await page.locator('[data-demo-target="analytics-progress"]').click();
    await expect(page.locator('#boo-novel-dialogue')).toBeVisible();
    await page.getByRole('button', { name: 'Открыть расписание' }).click();
    await expect(page).toHaveURL(/\/schedule/);
  });

  test('shows a locked demo week, profile achievements, and then the final choice', async ({ page }) => {
    await moveDirector(page, 'chapter_8');
    await expect(page.locator('#boo-novel-dialogue')).toBeVisible();
    await page.getByRole('button', { name: 'Показать неделю' }).click();
    await expect(page.locator('[data-demo-target="schedule-week"]')).toHaveClass(/boo-target-pulse/);
    await page.locator('[data-demo-target="schedule-week"]').click();
    await page.getByRole('button', { name: 'Посмотреть профиль' }).click();
    await expect(page).toHaveURL(/\/workspace\/profile/);

    await expect(page.locator('#boo-novel-dialogue')).toBeVisible();
    await page.getByRole('button', { name: 'Показать достижения' }).click();
    const achievements = page.locator('[data-demo-target="profile-achievements-action"]');
    await expect(achievements).toBeVisible();
    await expect(achievements).toHaveClass(/boo-target-pulse/);
    await achievements.click();
    await page.getByRole('button', { name: 'К финалу' }).click();
    await expect(page.locator('#boo-finale-mode')).toBeVisible();
    await expect(page.locator('#boo-story-guide')).toBeHidden();
  });
});
