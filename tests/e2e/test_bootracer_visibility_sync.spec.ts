import { expect, Page, test } from '@playwright/test';
import * as path from 'path';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || '/lesson/2168/room';
const videoDir = path.join(process.cwd(), 'docs/audits/boostudy-os-reliability/artifacts/videos');

async function login(page: Page, username: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  const usernameInput = page.locator('input[name="username"]');
  await expect(usernameInput).toBeVisible({ timeout: 10_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
}

async function setEditorCode(page: Page, code: string) {
  await page.evaluate((c) => {
    const textarea = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
    if (textarea) {
      textarea.value = c;
      (window as any).onCodeEditorInput?.(c);
    }
    if ((window as any).virtualFS) {
      (window as any).virtualFS['main.py'] = c;
    }
    const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
    const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
    if (socket) {
      socket.emit('lesson_code_update', {
        lesson_id: lessonId,
        file_name: 'main.py',
        code: c,
        force: true
      });
    }
  }, code);
}

async function isWindowVisibleInDom(page: Page, selector: string = '#tracer-window'): Promise<boolean> {
  return await page.evaluate((sel) => {
    const el = document.querySelector(sel) as HTMLElement;
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const isHiddenClass = el.classList.contains('hidden');
    const isMinimizedData = el.dataset.isMinimized === 'true';
    const isDisplayNone = style.display === 'none';
    const isZeroOpacity = style.opacity === '0';
    return !isHiddenClass && !isMinimizedData && !isDisplayNone && !isZeroOpacity;
  }, selector);
}

async function closeTracerWindow(page: Page) {
  await page.locator('#tracer-window [onclick*="closeWindow"], #tracer-window [title="Закрыть"]').first().click();
}

test.describe.configure({ mode: 'serial' });

test.describe('BooTracer Window Visibility Synchronization Suite (P0)', () => {

  test('BT-SYNC-1: 3 Cycles of Open -> Remote Visible -> Close -> Remote Hidden -> Reopen via Editor Button', async ({ browser }) => {
    const tutorContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } }
    });
    const studentContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } }
    });

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

      const testCode = `x = 5\ny = 15\nres = x + y\nprint("RES:", res)\n`;
      await setEditorCode(tutorPage, testCode);
      await tutorPage.waitForTimeout(600);

      // Run 3 cycles of Open -> Close -> Reopen
      for (let cycle = 1; cycle <= 3; cycle++) {
        console.log(`[Cycle ${cycle}] Teacher opening via #editor-tracer-toggle-btn`);
        await tutorPage.locator('#editor-tracer-toggle-btn').click();

        await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
        await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

        expect(await isWindowVisibleInDom(tutorPage, '#tracer-window')).toBe(true);
        expect(await isWindowVisibleInDom(studentPage, '#tracer-window')).toBe(true);

        const tutorIsOpen = await tutorPage.evaluate(() => (window as any).BooTracer?.isOpen);
        const studentIsOpen = await studentPage.evaluate(() => (window as any).BooTracer?.isOpen);
        expect(tutorIsOpen).toBe(true);
        expect(studentIsOpen).toBe(true);

        console.log(`[Cycle ${cycle}] Teacher closing via close button (cross)`);
        await tutorPage.locator('#tracer-window .window-control-close, #tracer-window [onclick*="closeWindow"]').first().click();

        await expect(tutorPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });
        await expect(studentPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });

        expect(await isWindowVisibleInDom(tutorPage, '#tracer-window')).toBe(false);
        expect(await isWindowVisibleInDom(studentPage, '#tracer-window')).toBe(false);

        const tutorClosedIsOpen = await tutorPage.evaluate(() => (window as any).BooTracer?.isOpen);
        const studentClosedIsOpen = await studentPage.evaluate(() => (window as any).BooTracer?.isOpen);
        expect(tutorClosedIsOpen).toBe(false);
        expect(studentClosedIsOpen).toBe(false);

        await tutorPage.waitForTimeout(400);
      }
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('BT-SYNC-2: 3 Cycles of Open and Close via Dock Icon (#dock-icon-tracer-window)', async ({ browser }) => {
    const tutorContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } }
    });
    const studentContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } }
    });

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

      // Run 3 cycles of Dock Open -> Close
      for (let cycle = 1; cycle <= 3; cycle++) {
        console.log(`[Dock Cycle ${cycle}] Teacher clicking dock icon`);
        await tutorPage.locator('#dock-icon-tracer-window').click();

        await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
        await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

        expect(await isWindowVisibleInDom(tutorPage, '#tracer-window')).toBe(true);
        expect(await isWindowVisibleInDom(studentPage, '#tracer-window')).toBe(true);

        console.log(`[Dock Cycle ${cycle}] Teacher clicking close button`);
        await tutorPage.locator('#tracer-window .window-control-close, #tracer-window [onclick*="closeWindow"]').first().click();

        await expect(tutorPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });
        await expect(studentPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });

        expect(await isWindowVisibleInDom(tutorPage, '#tracer-window')).toBe(false);
        expect(await isWindowVisibleInDom(studentPage, '#tracer-window')).toBe(false);

        await tutorPage.waitForTimeout(400);
      }
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('BT-SYNC-3: Execution State Preservation - stepping to step 2, minimize, reopen preserves step and frames', async ({ browser }) => {
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

      const testCode = `a = 100\nb = 200\nc = 300\nprint("SUM:", a + b + c)\n`;
      await setEditorCode(tutorPage, testCode);
      await tutorPage.waitForTimeout(600);

      // Open BooTracer
      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
      await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

      // Wait for frames to load
      await expect(tutorPage.locator('#boo-tracer-total-step')).not.toHaveText('0', { timeout: 10_000 });

      // Step to step 2
      await tutorPage.locator('#boo-tracer-btn-next').click();
      await tutorPage.waitForTimeout(200);
      await tutorPage.locator('#boo-tracer-btn-next').click();
      await tutorPage.waitForTimeout(400);

      const stepOnTutor = await tutorPage.locator('#boo-tracer-cur-step').textContent();
      expect(Number(stepOnTutor)).toBe(2);

      // Verify student is also at step 2
      await expect(studentPage.locator('#boo-tracer-cur-step')).toHaveText('2', { timeout: 5_000 });

      // Close tracer window
      console.log('Closing window on Tutor...');
      await closeTracerWindow(tutorPage);
      await expect(tutorPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });
      await expect(studentPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });

      // Reopen tracer window
      console.log('Reopening window on Tutor via editor button...');
      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
      await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

      // VERIFY: Step is STILL 2 and frames are preserved!
      const stepAfterRestoreTutor = await tutorPage.locator('#boo-tracer-cur-step').textContent();
      expect(Number(stepAfterRestoreTutor)).toBe(2);

      await expect(studentPage.locator('#boo-tracer-cur-step')).toHaveText('2', { timeout: 5_000 });

      // Step to end and verify output
      const totalSteps = parseInt(await tutorPage.locator('#boo-tracer-total-step').textContent() || '0', 10);
      for (let i = 2; i <= totalSteps; i++) {
        await tutorPage.locator('#boo-tracer-btn-next').click();
        await tutorPage.waitForTimeout(200);
      }

      console.log('DEBUG Tutor step:', await tutorPage.locator('#boo-tracer-cur-step').textContent());
      console.log('DEBUG Student step:', await studentPage.locator('#boo-tracer-cur-step').textContent());
      console.log('DEBUG Student frames:', await studentPage.evaluate(() => (window as any).BooTracer?.frames?.length));
      console.log('DEBUG Student stdout:', await studentPage.locator('#boo-tracer-stdout-box').textContent());

      await expect(tutorPage.locator('#boo-tracer-stdout-box')).toContainText('SUM: 600', { timeout: 5_000 });
      await expect(studentPage.locator('#boo-tracer-stdout-box')).toContainText('SUM: 600', { timeout: 5_000 });
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('BT-SYNC-4: Clicking Editor Button when BooTracer already open brings to front without restarting trace', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const tutorPage = await tutorContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await tutorPage.goto(roomUrl);
      await tutorPage.waitForLoadState('domcontentloaded');

      const testCode = `k = 42\nprint("VAL:", k)\n`;
      await setEditorCode(tutorPage, testCode);
      await tutorPage.waitForTimeout(500);

      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
      await expect(tutorPage.locator('#boo-tracer-total-step')).not.toHaveText('0', { timeout: 10_000 });

      // Step forward to step 1
      await tutorPage.locator('#boo-tracer-btn-next').click();
      await expect(tutorPage.locator('#boo-tracer-cur-step')).toHaveText('1');

      // Make another window active (e.g. bring code-window to front)
      await tutorPage.evaluate(() => {
        const codeWin = document.getElementById('code-window');
        if (codeWin && (window as any).windowManager) {
          (window as any).windowManager.bringToFront(codeWin);
        }
      });
      await tutorPage.waitForTimeout(300);

      // Verify BooTracer is no longer the active window
      const wasActiveBefore = await tutorPage.evaluate(() => {
        return document.getElementById('tracer-window')?.classList.contains('is-window-active');
      });
      expect(wasActiveBefore).toBe(false);

      // Now click editor tracer button again
      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await tutorPage.waitForTimeout(300);

      // BooTracer must still be open, active, and step must NOT have been reset to 0
      const step = await tutorPage.locator('#boo-tracer-cur-step').textContent();
      expect(Number(step)).toBe(1);

      const isActive = await tutorPage.evaluate(() => {
        return document.getElementById('tracer-window')?.classList.contains('is-window-active');
      });
      expect(isActive).toBe(true);
    } finally {
      await tutorContext.close();
    }
  });

  test('BT-SYNC-5: Student editor focus preservation during remote BooTracer open', async ({ browser }) => {
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

      // Student focuses editor textarea
      const studentTextarea = studentPage.locator('#code-editor-textarea');
      await studentTextarea.focus();
      const isFocusedBefore = await studentPage.evaluate(() => {
        return document.activeElement === document.getElementById('code-editor-textarea');
      });
      expect(isFocusedBefore).toBe(true);

      // Teacher opens BooTracer
      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
      await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

      // Verify student's focus was not stolen
      const isFocusedAfter = await studentPage.evaluate(() => {
        return document.activeElement === document.getElementById('code-editor-textarea');
      });
      expect(isFocusedAfter).toBe(true);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('BT-SYNC-6: Student reload rehydrates visible BooTracer window when open', async ({ browser }) => {
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

      // Teacher opens BooTracer
      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
      await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

      // Student reloads the page
      console.log('Reloading student page...');
      await studentPage.reload();
      await studentPage.waitForLoadState('domcontentloaded');

      // Verify BooTracer window is visible on student after reload
      await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 15_000 });
      expect(await isWindowVisibleInDom(studentPage, '#tracer-window')).toBe(true);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('BT-SYNC-7: Student in windows_mode: both open/close syncs to Teacher', async ({ browser }) => {
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

      // First ensure tracer is closed on both
      const isTracerOpen = await tutorPage.evaluate(() => (window as any).BooTracer?.isOpen);
      if (isTracerOpen) {
        await closeTracerWindow(tutorPage);
        await expect(tutorPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });
      }

      // Teacher switches room to windows_mode: 'both'
      await tutorPage.evaluate(() => {
        const btn = document.querySelector('.win-mode-btn[data-mode="both"]') as HTMLElement;
        if (btn) btn.click();
      });
      await tutorPage.waitForTimeout(600);

      // Student opens BooTracer via editor toggle button
      console.log('Student opening BooTracer in windows_mode: both...');
      await studentPage.locator('#editor-tracer-toggle-btn').click();

      // Must be visible on BOTH student and teacher!
      await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
      expect(await isWindowVisibleInDom(tutorPage, '#tracer-window')).toBe(true);

      // Student closes BooTracer
      console.log('Student closing BooTracer in windows_mode: both...');
      await closeTracerWindow(studentPage);

      // Must be hidden on BOTH student and teacher!
      await expect(studentPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });
      await expect(tutorPage.locator('#tracer-window')).toBeHidden({ timeout: 10_000 });
      expect(await isWindowVisibleInDom(tutorPage, '#tracer-window')).toBe(false);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

});
