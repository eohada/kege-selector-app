import { expect, Page, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || '/lesson/2168/room';
const lessonId = 2168;

async function login(page: Page, username: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  const usernameInput = page.locator('input[name="username"]');
  await expect(usernameInput).toBeVisible({ timeout: 10_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
}

test.describe.configure({ mode: 'serial' });

test.describe('Educational Workflow Integration: Dual-Browser Suite', () => {

  test('EWI-1: Authoritative Kick, Multi-Tab Exclusion & Re-admission', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const studentContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });

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

      // Retrieve student user ID from student page config
      const studentUserId = await studentPage.evaluate(() => {
        const cfg = JSON.parse(document.getElementById('trainer-os-config')?.textContent || '{}');
        return cfg.viewer_id;
      });
      expect(studentUserId).toBeTruthy();

      // Teacher kicks student via POST /lesson/2168/kick
      const kickResult = await tutorPage.evaluate(async ({ id, targetId }) => {
        const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        const res = await fetch(`/lesson/${id}/kick`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({ user_id: targetId, csrf_token: csrf }),
        });
        const status = res.status;
        const text = await res.text();
        return { status, text };
      }, { id: lessonId, targetId: studentUserId });
      console.log('KICK RESULT:', JSON.stringify(kickResult));
      expect(kickResult.status).toBe(200);
      const kickData = JSON.parse(kickResult.text);
      expect(kickData.success).toBe(true);

      // Student page receives kick and is locked or redirected
      await studentPage.waitForTimeout(1000);

      // Multi-tab exclusion: student opens a second tab trying to join lesson
      const studentSecondPage = await studentContext.newPage();
      await studentSecondPage.goto(roomUrl);
      await studentSecondPage.waitForLoadState('domcontentloaded');

      // Second tab must be redirected to /schedule due to active ban
      await expect(studentSecondPage).toHaveURL(/\/schedule/);

      // LiveKit token gate: student tries to request LiveKit token directly
      const tokenResStatus = await studentSecondPage.evaluate(async (id) => {
        try {
          const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
          const res = await fetch(`/lesson/${id}/livekit/token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          });
          return res.status;
        } catch (_) {
          return 500;
        }
      }, lessonId);
      expect(tokenResStatus).toBe(403);

      // Teacher unbans student via REST endpoint
      const unbanResult = await tutorPage.evaluate(async ({ id, targetId }) => {
        const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        const res = await fetch(`/lesson/${id}/unban`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({ user_id: targetId, csrf_token: csrf }),
        });
        const status = res.status;
        const text = await res.text();
        return { status, text };
      }, { id: lessonId, targetId: studentUserId });
      console.log('UNBAN RESULT:', JSON.stringify(unbanResult));
      expect(unbanResult.status).toBe(200);
      const unbanData = JSON.parse(unbanResult.text);
      expect(unbanData.success).toBe(true);

      // Student re-joins lesson room successfully after unban
      await studentSecondPage.goto(roomUrl);
      await studentSecondPage.waitForLoadState('domcontentloaded');
      await expect(studentSecondPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      await studentSecondPage.close();
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('EWI-2: Private Teacher Homework Window (Zero Student Leakage)', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const studentContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      // 1. Teacher Dock has #dock-icon-homework-window
      const teacherHwIcon = tutorPage.locator('#dock-icon-homework-window');
      await expect(teacherHwIcon).toBeVisible({ timeout: 10_000 });

      // 2. Student Dock MUST NOT have #dock-icon-homework-window
      const studentHwIcon = studentPage.locator('#dock-icon-homework-window');
      await expect(studentHwIcon).toHaveCount(0);

      // 3. Student DOM MUST NOT have #homework-window
      const studentHwWindow = studentPage.locator('#homework-window');
      await expect(studentHwWindow).toHaveCount(0);

      // 4. Teacher opens #homework-window
      await teacherHwIcon.click();
      const teacherHwWindow = tutorPage.locator('#homework-window');
      await expect(teacherHwWindow).toBeVisible({ timeout: 5_000 });

      // 5. Verify Homework window shows private badge and traffic lights
      await expect(teacherHwWindow.locator('#homework-window-header')).toContainText('Домашние задания и работы');
      await expect(teacherHwWindow.locator('#homework-window-header')).toContainText('Приватно');

      // 6. Student page should remain unaffected and unpolluted
      await expect(studentPage.locator('#homework-window')).toHaveCount(0);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('EWI-3: Teacher Orbit Suppression over OS Windows & Alt+I Restriction', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const studentContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      // Verify floating dev badge does not exist in student DOM
      await expect(studentPage.locator('#dev-switcher-trigger-badge')).toHaveCount(0);

      // Verify Alt+I does NOT open modal on student page
      await studentPage.keyboard.press('Alt+I');
      await studentPage.waitForTimeout(400);
      await expect(studentPage.locator('#dev-role-switcher-modal')).toHaveCount(0);

      // Orbit hit-test suppression check:
      // Over #code-window, Orbit should NOT activate
      const isOrbitSuppressedOverWindow = await tutorPage.evaluate(() => {
        const codeWin = document.getElementById('code-window');
        if (!codeWin) return false;
        const rect = codeWin.getBoundingClientRect();
        const el = document.elementFromPoint(rect.left + 50, rect.top + 20);
        return Boolean(el?.closest('.glass-os-window') || el?.closest('[id$="-window"]'));
      });
      expect(isOrbitSuppressedOverWindow).toBe(true);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

});
