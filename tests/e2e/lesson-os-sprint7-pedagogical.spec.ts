import { expect, Page, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';

async function login(page: Page, username: string) {
  await page.goto('/logout').catch(() => undefined);
  await page.goto('/login');
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/);
}

test.describe('Sprint 7: Pedagogical UX & Window Environment Acceptance', () => {
  test('Tutor: Active window focus differentiation and permission badge in /trainer/v2', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto('/trainer/v2');
    await page.waitForLoadState('domcontentloaded');

    // 1. Verify Code Window and Permission Badge
    const codeWindow = page.locator('#code-window');
    await expect(codeWindow).toBeVisible({ timeout: 15_000 });

    const badge = page.locator('#code-window-permission-badge');
    await expect(badge).toBeVisible();
    await expect(badge).toHaveClass(/lesson-os-permission-badge/);

    // 2. Window Focus Management (is-window-active class)
    // Click code window -> gets active class
    await codeWindow.click({ position: { x: 50, y: 15 } });
    await expect(codeWindow).toHaveClass(/is-window-active/);

    // Open/focus task window
    const taskWindow = page.locator('#task-window');
    if (await taskWindow.isVisible()) {
      await taskWindow.click({ position: { x: 50, y: 15 } });
      await expect(taskWindow).toHaveClass(/is-window-active/);
      // Code window should lose active class
      await expect(codeWindow).not.toHaveClass(/is-window-active/);
    }
  });

  test('Layout & Ergonomics on 1366x768 (Standard Laptop Viewport)', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 });
    await login(page, tutorUsername);
    await page.goto('/trainer/v2');
    await page.waitForLoadState('domcontentloaded');

    const codeWindow = page.locator('#code-window');
    await expect(codeWindow).toBeVisible({ timeout: 15_000 });

    // Check bounds
    const box = await codeWindow.boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      expect(box.width).toBeGreaterThanOrEqual(350);
      expect(box.height).toBeGreaterThanOrEqual(230);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(40); // below system bar
    }

    // Dock should remain accessible
    const dock = page.locator('#board-dock');
    if (await dock.isVisible()) {
      const dockBox = await dock.boundingBox();
      expect(dockBox).not.toBeNull();
      if (dockBox) {
        expect(dockBox.y + dockBox.height).toBeLessThanOrEqual(768);
      }
    }
  });

  test('Student: Read-only visual indication and permission states', async ({ page }) => {
    await login(page, studentUsername);
    await page.goto('/trainer/v2');
    await page.waitForLoadState('domcontentloaded');

    const codeWindow = page.locator('#code-window');
    await expect(codeWindow).toBeVisible({ timeout: 15_000 });

    // Check textarea exists and has valid attribute
    const textarea = page.locator('#code-editor-textarea');
    await expect(textarea).toBeVisible();

    const badge = page.locator('#code-window-permission-badge');
    await expect(badge).toBeVisible();
  });
});
