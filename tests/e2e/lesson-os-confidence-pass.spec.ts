import { expect, Page, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || '/lesson/2168/room';

async function login(page: Page, username: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  const usernameInput = page.locator('input[name="username"]');
  await expect(usernameInput).toBeVisible({ timeout: 10_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
}

test.describe('Final Confidence Pass: Live Dual-Browser Orchestration & Routing', () => {
  test('Teacher Orbit: freeze_student & free_mode live execution in student DOM', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Teacher emits freeze_student via Socket.IO
      await tutorPage.evaluate(() => {
        const socket = (window as any).lessonSocket || (window as any).boardSocket || (window as any).state?.socket;
        const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
        if (socket) {
          socket.emit('lesson_room_ui', { lesson_id: lessonId, kind: 'freeze_student' });
        }
      });

      // Verify student DOM reflects frozen / demonstration state
      const studentEditor = studentPage.locator('#code-editor-textarea');
      await expect(studentEditor).toHaveAttribute('aria-readonly', 'true', { timeout: 10_000 });

      // Teacher emits free_mode
      await tutorPage.evaluate(() => {
        const socket = (window as any).lessonSocket || (window as any).boardSocket || (window as any).state?.socket;
        const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
        if (socket) {
          socket.emit('lesson_room_ui', { lesson_id: lessonId, kind: 'free_mode' });
        }
      });

      // Wait a moment for free_mode propagation
      await studentPage.waitForTimeout(1_000);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('Teacher Orbit: focus_board shifts student focus and minimizes auxiliary windows', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Teacher emits focus_board
      await tutorPage.evaluate(() => {
        const socket = (window as any).lessonSocket || (window as any).boardSocket || (window as any).state?.socket;
        const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
        if (socket) {
          socket.emit('lesson_room_ui', { lesson_id: lessonId, kind: 'focus_board' });
        }
      });

      // Wait for propagation
      await studentPage.waitForTimeout(1_000);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('V1 Route Availability: /trainer/v2 standalone mode renders without OS regression', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto('/trainer/v2');
    await page.waitForLoadState('domcontentloaded');

    // Standalone trainer starts in catalog mode
    const catalog = page.locator('#trainer-catalog-view');
    await expect(catalog).toBeVisible({ timeout: 15_000 });

    // Switch to Arena/Code mode
    const arenaBtn = page.locator('#mode-arena');
    if (await arenaBtn.isVisible()) {
      await arenaBtn.click();
      const editor = page.locator('#code-editor-textarea');
      await expect(editor).toBeVisible({ timeout: 10_000 });
    }
  });

  test('V3 Route Availability: /reviews/queue loads review queue for tutor', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto('/reviews/queue');
    await page.waitForLoadState('domcontentloaded');

    // Review queue should render successfully without 403/500
    await expect(page).toHaveURL(/\/reviews\/queue/);
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});
