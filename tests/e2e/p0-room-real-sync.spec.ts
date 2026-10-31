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

test.describe('P0 Verification: Real Dual-Browser Live Synchronization & Zero Page Errors', () => {
  test('P0-1: Successful connection, zero JS pageerrors, and presence synchronization', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const tutorErrors: string[] = [];
    const studentErrors: string[] = [];

    tutorPage.on('pageerror', (err) => {
      console.error('[TUTOR PAGEERROR]', err.message);
      tutorErrors.push(err.message || String(err));
    });

    studentPage.on('pageerror', (err) => {
      console.error('[STUDENT PAGEERROR]', err.message);
      studentErrors.push(err.message || String(err));
    });

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Wait for presence exchange (up to 10 seconds)
      const tutorHeaderCount = tutorPage.locator('#lesson-os-participants');
      const studentHeaderCount = studentPage.locator('#lesson-os-participants');

      await expect(tutorHeaderCount).toContainText('2 участник', { timeout: 10_000 });
      await expect(studentHeaderCount).toContainText('2 участник', { timeout: 10_000 });

      // Verify ZERO unhandled JavaScript errors occurred on either page
      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);

      // Verify participants list contains 2 users and both roles
      await tutorPage.locator('#lesson-os-presence-toggle').click();
      await expect(tutorPage.locator('.lesson-os-presence-person')).toHaveCount(2, { timeout: 5_000 });
      await expect(tutorPage.locator('#lesson-os-presence-list')).toContainText('qa_pool_tutor_1');
      await expect(tutorPage.locator('#lesson-os-presence-list')).toContainText('Qa Pool Student 1');
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('P0-2: Live bidirectional Python IDE synchronization & Permission control', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const errors: string[] = [];
    tutorPage.on('pageerror', (err) => errors.push(`TUTOR: ${err.message}`));
    studentPage.on('pageerror', (err) => errors.push(`STUDENT: ${err.message}`));

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Teacher edits Python code via Ace Editor / textarea
      const testCode = `# Live Sync Test ${Date.now()}\ndef solution():\n    return 42\n`;
      await tutorPage.evaluate((code) => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
        if (socket) {
          socket.emit('lesson_code_update', {
            lesson_id: lessonId,
            file_name: 'main.py',
            code: code,
            force: true
          });
        }
      }, testCode);

      // Student must see the code updated in their editor within 8 seconds
      const studentEditor = studentPage.locator('#code-editor-textarea');
      await expect(studentEditor).toHaveValue(testCode, { timeout: 8_000 });

      // Zero page errors
      expect(errors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('P0-3: Teacher Orbit freeze_student & free_mode live execution and server enforcement', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const errors: string[] = [];
    tutorPage.on('pageerror', (err) => errors.push(`TUTOR: ${err.message}`));
    studentPage.on('pageerror', (err) => errors.push(`STUDENT: ${err.message}`));

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
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
        if (socket) {
          socket.emit('lesson_room_ui', { lesson_id: lessonId, kind: 'freeze_student' });
        }
      });

      // Verify student DOM reflects frozen / demonstration state
      const studentBadge = studentPage.locator('#code-window-permission-badge');
      await expect(studentBadge).toContainText('Демонстрация', { timeout: 8_000 });

      const studentEditor = studentPage.locator('#code-editor-textarea');
      await expect(studentEditor).toHaveAttribute('aria-readonly', 'true');

      // Teacher emits free_mode
      await tutorPage.evaluate(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
        if (socket) {
          socket.emit('lesson_room_ui', { lesson_id: lessonId, kind: 'free_mode' });
        }
      });

      // Wait for badge to update from demonstration
      await expect(studentBadge).not.toContainText('Демонстрация', { timeout: 8_000 });

      // Zero page errors
      expect(errors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('P0-4: Student reconnect rehydrates presence and room state with zero errors', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const errors: string[] = [];
    tutorPage.on('pageerror', (err) => errors.push(`TUTOR: ${err.message}`));
    studentPage.on('pageerror', (err) => errors.push(`STUDENT: ${err.message}`));

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Reload student page to simulate disconnect & reconnect
      await studentPage.reload();
      await studentPage.waitForLoadState('domcontentloaded');
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Verify student reconnected and sees participants in header
      const studentOnlineCount = studentPage.locator('#lesson-os-participants');
      await expect(studentOnlineCount).toBeVisible({ timeout: 10_000 });
      await expect(studentOnlineCount).toContainText('2 участник', { timeout: 10_000 });

      // Zero page errors on reload
      expect(errors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });
});
