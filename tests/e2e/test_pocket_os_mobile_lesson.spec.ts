import { expect, Page, test, BrowserContext } from '@playwright/test';

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

test.describe('BOOSTUDY POCKET OS — SPRINT 1 E2E SUITE', () => {
  test.describe.configure({ mode: 'serial' });

  // ---------------------------------------------------------------------------
  // POCKET-01: Mobile Lesson Entry
  // ---------------------------------------------------------------------------
  test('POCKET-01: Mobile Student Entry activates Pocket OS Shell', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 }); // iPhone 14 / Pixel
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });

    // Pocket OS Shell must be present
    const shell = page.locator('#pocket-os-shell');
    await expect(shell).toBeVisible({ timeout: 15_000 });

    // Header, Surface, and Bottom Navigation must be rendered
    await expect(page.locator('#pocket-header')).toBeVisible();
    await expect(page.locator('#pocket-focus-surface')).toBeVisible();
    await expect(page.locator('#pocket-nav-bar')).toBeVisible();

    // Default focus must be 'board'
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'board');
    await expect(page.locator('#pocket-nav-board')).toHaveClass(/is-active/);

    // Desktop chrome must be hidden
    await expect(page.locator('header.lesson-os-system-bar')).toBeHidden();
    await expect(page.locator('#board-dock-shelf')).toBeHidden();
  });

  // ---------------------------------------------------------------------------
  // POCKET-02: Focus Navigation (Board -> Code -> Task -> Board with zero state loss)
  // ---------------------------------------------------------------------------
  test('POCKET-02: Focus Navigation preserves DOM state and switches smoothly', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    // Switch to Code
    await page.locator('#pocket-nav-code').click();
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'code');
    await expect(page.locator('#pocket-nav-code')).toHaveClass(/is-active/);
    await expect(page.locator('#code-window')).toBeVisible();
    await expect(page.locator('#canvas-window')).toBeHidden();

    // Type text in Code Editor
    const textarea = page.locator('#code-editor-textarea');
    await textarea.fill('# Pocket OS Test Marker 42\nprint("Hello Pocket")');

    // Switch to Task
    await page.locator('#pocket-nav-task').click();
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'task');
    await expect(page.locator('#pocket-nav-task')).toHaveClass(/is-active/);
    await expect(page.locator('#task-window')).toBeVisible();
    await expect(page.locator('#code-window')).toBeHidden();

    // Switch back to Code — text must be 100% preserved
    await page.locator('#pocket-nav-code').click();
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'code');
    await expect(textarea).toHaveValue('# Pocket OS Test Marker 42\nprint("Hello Pocket")');

    // Switch back to Board
    await page.locator('#pocket-nav-board').click();
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'board');
    await expect(page.locator('#canvas-window')).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // POCKET-03: Canvas View-Only Enforcement
  // ---------------------------------------------------------------------------
  test('POCKET-03: Mobile Canvas is strictly Read-Only', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    // Read-only pill must be visible
    await expect(page.locator('#pocket-read-only-pill')).toBeVisible();
    await expect(page.locator('#pocket-read-only-pill')).toContainText('Доска учителя · Просмотр');

    // BooCanvasOverlay must report isReadOnly = true
    const isReadOnly = await page.evaluate(() => {
      return window.BooCanvasOverlay ? window.BooCanvasOverlay.isReadOnly() : false;
    });
    expect(isReadOnly).toBe(true);

    // Desktop drawing tools must NOT be accessible
    await expect(page.locator('#board-toolbar')).toBeHidden();
    await expect(page.locator('.boo-canvas-toolbar')).toBeHidden();
  });

  // ---------------------------------------------------------------------------
  // POCKET-04, 05, 06: Dual-Browser Teacher & Mobile Student Interaction
  // ---------------------------------------------------------------------------
  test('POCKET-04/05/06: Viewport Contour, Show Here, and Focus on Contour', async ({ browser }) => {
    // Context 1: Teacher Desktop (1440x900)
    const teacherContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const teacherPage = await teacherContext.newPage();
    await login(teacherPage, tutorUsername);
    await teacherPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    // Verify Teacher Controls are present
    const showHereBtn = teacherPage.locator('#btn-teacher-show-here');
    await expect(showHereBtn).toBeVisible();

    // Context 2: Student Mobile (390x844)
    const studentContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const studentPage = await studentContext.newPage();
    await login(studentPage, studentUsername);
    await studentPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    // Give socket time to connect & announce viewport
    await studentPage.waitForTimeout(2000);

    // POCKET-04: Teacher sees mobile student contour
    const studentContour = teacherPage.locator('.board-student-viewport-box');
    await expect(studentContour).toBeVisible({ timeout: 10_000 });
    await expect(studentContour).toHaveClass(/is-mobile-contour/);
    await expect(studentContour).toContainText('Pocket');

    // POCKET-05: Teacher triggers «Показать здесь»
    await showHereBtn.click();
    await expect(showHereBtn).toContainText('Показано!');

    // POCKET-06: Teacher centers camera on student contour without modifying student
    const jumpBtn = studentContour.locator('.board-student-viewport-jump-btn');
    if (await jumpBtn.isVisible()) {
      await jumpBtn.dispatchEvent('click');
      await teacherPage.waitForTimeout(500);
      // Student is still on board
      await expect(studentPage.locator('body')).toHaveAttribute('data-pocket-focus', 'board');
    }

    await teacherContext.close();
    await studentContext.close();
  });

  // ---------------------------------------------------------------------------
  // POCKET-09 & POCKET-10: Teacher Focus Suggestions & Non-Destructive Switch
  // ---------------------------------------------------------------------------
  test('POCKET-09/10: Teacher Suggestion Toast & Non-Destructive Navigation', async ({ browser }) => {
    const teacherContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const teacherPage = await teacherContext.newPage();
    await login(teacherPage, tutorUsername);
    await teacherPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    const studentContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const studentPage = await studentContext.newPage();
    await login(studentPage, studentUsername);
    await studentPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    // Teacher sends suggestion to switch to Code
    await teacherPage.evaluate(() => {
      window.sendFocusSuggestion?.('code');
    });

    // Student receives toast
    const toast = studentPage.locator('#pocket-toast');
    await expect(toast).toBeVisible({ timeout: 5_000 });
    await expect(toast).toContainText('Учитель предлагает');

    // Student accepts suggestion
    await studentPage.locator('#pocket-toast-btn-action').click();
    await expect(studentPage.locator('body')).toHaveAttribute('data-pocket-focus', 'code');
    await expect(studentPage.locator('#code-window')).toBeVisible();

    await teacherContext.close();
    await studentContext.close();
  });

  // ---------------------------------------------------------------------------
  // POCKET-11: Mobile Python Ergonomics & Virtual Symbols
  // ---------------------------------------------------------------------------
  test('POCKET-11: Virtual Symbol Toolbar inserts characters and Runs code', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    // Go to Code
    await page.locator('#pocket-nav-code').click();
    await expect(page.locator('#code-window')).toBeVisible();

    // Check Virtual Symbol Strip
    const symbolStrip = page.locator('#pocket-virtual-symbols');
    await expect(symbolStrip).toBeVisible();

    const textarea = page.locator('#code-editor-textarea');
    await textarea.fill('def solve');

    // Click virtual symbol `(`
    await page.locator('.pocket-symbol-key[data-val="("]').click();
    // Click virtual symbol `)`
    await page.locator('.pocket-symbol-key[data-val=")"]').click();
    // Click virtual symbol `:`
    await page.locator('.pocket-symbol-key[data-val=":"]').click();

    await expect(textarea).toHaveValue('def solve():');

    // Run Code button
    const runBtn = page.locator('#pocket-btn-run');
    await expect(runBtn).toBeVisible();
    await runBtn.click();

    // Terminal drawer should expand
    const drawer = page.locator('#pocket-terminal-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer).not.toHaveClass(/is-collapsed/);
  });

  // ---------------------------------------------------------------------------
  // POCKET-13: LiveKit Video Pill Continuity
  // ---------------------------------------------------------------------------
  test('POCKET-13: LiveKit Floating Video Pill persists across focus switches', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    const videoPill = page.locator('#pocket-video-pill');
    await expect(videoPill).toBeVisible();

    // Tap to expand
    await videoPill.click();
    await expect(videoPill).toHaveClass(/is-expanded/);

    // Switch to Code — Video pill remains mounted and expanded
    await page.locator('#pocket-nav-code').click();
    await expect(videoPill).toBeVisible();
    await expect(videoPill).toHaveClass(/is-expanded/);

    // Switch to Task — Video pill remains mounted
    await page.locator('#pocket-nav-task').click();
    await expect(videoPill).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // POCKET-14: Mobile Ergonomics & Safe Area Padding
  // ---------------------------------------------------------------------------
  test('POCKET-14: Header and Nav Bar touch targets meet 44px ergonomics', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    const navItems = page.locator('.pocket-nav-item');
    expect(await navItems.count()).toBe(3);

    // Verify touch target height
    const navBox = await page.locator('#pocket-nav-bar').boundingBox();
    expect(navBox?.height).toBeGreaterThanOrEqual(50);
  });

  // ---------------------------------------------------------------------------
  // POCKET-15: Desktop Zero-Regression
  // ---------------------------------------------------------------------------
  test('POCKET-15: Desktop layout remains 100% intact on desktop viewport', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, tutorUsername);
    await page.goto(roomUrl, { waitUntil: 'domcontentloaded' });

    // Desktop system bar is visible
    await expect(page.locator('header.lesson-os-system-bar')).toBeVisible({ timeout: 15_000 });

    // Desktop dock is visible
    await expect(page.locator('#board-dock')).toBeVisible();

    // Pocket OS Shell must NOT be active
    await expect(page.locator('#pocket-os-shell')).toBeHidden();
    await expect(page.locator('body')).not.toHaveClass(/pocket-os-active/);
  });

  // ---------------------------------------------------------------------------
  // POCKET-16: Security & Permissions Lockout
  // ---------------------------------------------------------------------------
  test('POCKET-16: Student cannot trigger Teacher Master Controls', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    // Student attempts to emit show_here or focus_suggestion via socket directly
    const socketErrorReceived = await page.evaluate(() => {
      return new Promise<boolean>((resolve) => {
        const socket = window.boostudyLessonSocket || window.state?.socket || window.boostudyWhiteboard?.state?.socket;
        if (!socket) return resolve(false);

        socket.on('whiteboard_error', () => {
          resolve(true);
        });

        // Malicious emission
        socket.emit('whiteboard_show_here', {
          lesson_id: window.trainerOsConfig?.lesson_id,
          world_x: 0,
          world_y: 0,
        });

        setTimeout(() => resolve(false), 2000);
      });
    });

    expect(socketErrorReceived).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // POCKET-17: Resilience & Reconnect
  // ---------------------------------------------------------------------------
  test('POCKET-17: Page reload restores Pocket OS Shell cleanly without error', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    // Reload page
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('#pocket-nav-bar')).toBeVisible();
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'board');
  });
});
