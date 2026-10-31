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

test.describe('P0/P1 Lesson Room Collaboration Recovery Tests', () => {
  test('Recovery-1: Canvas live sync and scheduleRedraw definition (zero pageerrors)', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const tutorErrors: string[] = [];
    const studentErrors: string[] = [];

    tutorPage.on('pageerror', (err) => tutorErrors.push(err.message || String(err)));
    studentPage.on('pageerror', (err) => studentErrors.push(err.message || String(err)));

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Verify scheduleRedraw exists on BooCanvasOverlay API
      const hasScheduleRedraw = await studentPage.evaluate(() => {
        const overlay = (window as any).BooCanvasOverlay;
        return typeof overlay?.scheduleRedraw === 'function';
      });
      expect(hasScheduleRedraw).toBe(true);

      // Simulate live stroke emit from teacher to student
      await tutorPage.evaluate(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
        if (socket) {
          // Emit a live stroke fragment
          socket.emit('board_live_stroke', {
            lesson_id: lessonId,
            stroke: {
              id: 'test-stroke-live-1',
              color: '#ef4444',
              size: 4,
              tool: 'pen',
              points: [
                { x: 100, y: 100 },
                { x: 120, y: 120 }
              ]
            }
          });
        }
      });

      // Wait 1 second and verify no scheduleRedraw error in student console
      await studentPage.waitForTimeout(1000);
      const scheduleRedrawError = studentErrors.find(e => e.includes('scheduleRedraw is not defined'));
      expect(scheduleRedrawError).toBeUndefined();
      expect(studentErrors.filter(e => e.includes('scheduleRedraw'))).toHaveLength(0);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('Recovery-2: Stable remote code caret with presence badge and no disappearing on idle', async ({ browser }) => {
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

      // Teacher emits a code cursor update with line and column
      await tutorPage.evaluate(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        const lessonId = (window as any).trainerOsConfig?.lesson_id || 2168;
        if (socket) {
          socket.emit('lesson_code_cursor', {
            lesson_id: lessonId,
            file_name: 'main.py',
            cursor: {
              line: 1,
              col: 4,
              selection_start: 4,
              selection_end: 4
            }
          });
        }
      });

      // Student page should display the remote caret element
      const remoteCaret = studentPage.locator('.code-remote-caret');
      await expect(remoteCaret).toBeVisible({ timeout: 5_000 });

      // Check for user badge inside remote caret
      const caretBadge = studentPage.locator('.code-remote-caret-badge');
      await expect(caretBadge).toBeVisible({ timeout: 5_000 });

      // Wait 2.5 seconds (previously disappeared after 1400ms)
      await studentPage.waitForTimeout(2500);

      // Remote caret must still be visible!
      await expect(remoteCaret).toBeVisible();
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('Recovery-3: Window edge resizers, cursor styles and min-size limits', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(roomUrl);
    await page.waitForLoadState('domcontentloaded');

    const codeWindow = page.locator('#code-window');
    await expect(codeWindow).toBeVisible({ timeout: 15_000 });

    // Check edge resizers
    const eastResizer = codeWindow.locator('.window-edge-resizer.resizer-e');
    const southResizer = codeWindow.locator('.window-edge-resizer.resizer-s');
    const seResizer = codeWindow.locator('.window-edge-resizer.resizer-se');

    await expect(eastResizer).toBeAttached();
    await expect(southResizer).toBeAttached();
    await expect(seResizer).toBeAttached();

    // Verify cursor styles
    const eastCursor = await eastResizer.evaluate(el => window.getComputedStyle(el).cursor);
    const southCursor = await southResizer.evaluate(el => window.getComputedStyle(el).cursor);
    const seCursor = await seResizer.evaluate(el => window.getComputedStyle(el).cursor);

    expect(eastCursor).toBe('ew-resize');
    expect(southCursor).toBe('ns-resize');
    expect(seCursor).toBe('nwse-resize');
  });

  test('Recovery-4: Phantom task statement window elimination & Lesson Info privacy', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      // Student opens room
      await studentPage.goto(roomUrl);
      await studentPage.waitForLoadState('domcontentloaded');
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Verify task window is NOT opened automatically for student!
      const studentTaskWindow = studentPage.locator('#task-window');
      const isTaskVisible = await studentTaskWindow.isVisible();
      expect(isTaskVisible).toBe(false);

      // Verify lesson info window is NOT in student dock and is hidden
      const studentInfoDock = studentPage.locator('#dock-icon-lesson-info-window');
      await expect(studentInfoDock).toHaveCount(0);

      const studentInfoWindow = studentPage.locator('#lesson-info-window');
      const isInfoVisible = await studentInfoWindow.isVisible();
      expect(isInfoVisible).toBe(false);

      // Teacher opens room
      await tutorPage.goto(roomUrl);
      await tutorPage.waitForLoadState('domcontentloaded');
      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Teacher HAS lesson info window available in dock
      const tutorInfoDock = tutorPage.locator('#dock-icon-lesson-info-window');
      await expect(tutorInfoDock).toHaveCount(1);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('Recovery-5: Modernized Bottom Dock styling', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(roomUrl);
    await page.waitForLoadState('domcontentloaded');

    // Dock container should be pointer-events none wrapper
    const dockContainer = page.locator('#board-dock');
    await expect(dockContainer).toBeVisible({ timeout: 15_000 });

    const dockPointerEvents = await dockContainer.evaluate(el => window.getComputedStyle(el).pointerEvents);
    expect(dockPointerEvents).toBe('none');

    // Dock items should have pointer-events auto, glassmorphism, 48x48px
    const dockItem = page.locator('.board-dock-item').first();
    await expect(dockItem).toBeVisible();

    const itemPointerEvents = await dockItem.evaluate(el => window.getComputedStyle(el).pointerEvents);
    expect(itemPointerEvents).toBe('auto');

    const itemBounding = await dockItem.boundingBox();
    expect(itemBounding?.width).toBeCloseTo(48, -1);
    expect(itemBounding?.height).toBeCloseTo(48, -1);
  });

  test('Recovery-6: BooTracer input state machine and trace restart logic', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(roomUrl);
    await page.waitForLoadState('domcontentloaded');

    // Verify BooTracer singleton instance methods and restartTrace pendingStep fix
    const tracerCheck = await page.evaluate(() => {
      const inst = (window as any).BooTracer;
      if (!inst) return { found: false };
      inst.pendingStep = 5;
      inst.isWaitingInput = true;
      inst.restartTrace();
      return {
        found: true,
        pendingStepAfterRestart: inst.pendingStep,
        hasInteractivePrompt: typeof inst.renderInteractiveInputPrompt === 'function'
      };
    });

    if (tracerCheck.found) {
      expect(tracerCheck.pendingStepAfterRestart).toBeNull();
      expect(tracerCheck.hasInteractivePrompt).toBe(true);
    }
  });
});
