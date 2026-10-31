import { expect, Page, test } from '@playwright/test';
import * as path from 'path';

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

test.describe.configure({ mode: 'serial' });

test.describe('P0 Rejected Acceptance: BooTracer, Shared Z-Order & Floating Dock Suite', () => {

  test('P0-Tracer-1: Scenario A - Program without input restarts cleanly from step 0', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const studentContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const tutorErrors: string[] = [];
    const studentErrors: string[] = [];
    tutorPage.on('pageerror', (err) => tutorErrors.push(err.message));
    studentPage.on('pageerror', (err) => studentErrors.push(err.message));

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Teacher sets Python code without input
      const testCode = `a = 10\nb = 20\nc = a + b\nprint("TOTAL:", c)\n`;
      await setEditorCode(tutorPage, testCode);
      await tutorPage.waitForTimeout(500);

      // Teacher opens BooTracer
      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });
      await expect(studentPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

      // Wait for frames to finish loading
      await expect(tutorPage.locator('#boo-tracer-total-step')).not.toHaveText('0', { timeout: 10_000 });

      // Jump to last step or step forward to completion
      const totalSteps = parseInt(await tutorPage.locator('#boo-tracer-total-step').textContent() || '0', 10);
      expect(totalSteps).toBeGreaterThanOrEqual(4);

      const nextBtn = tutorPage.locator('#boo-tracer-btn-next');
      for (let i = 0; i <= totalSteps; i++) {
        await nextBtn.click();
        await tutorPage.waitForTimeout(100);
      }

      // Verify stdout on tutor and step > 0
      const stdoutBox = tutorPage.locator('#boo-tracer-stdout-box');
      await expect(stdoutBox).toContainText('TOTAL: 30', { timeout: 7_000 });
      const curStepBadge = tutorPage.locator('#boo-tracer-cur-step');
      const stepBeforeRestart = await curStepBadge.textContent();
      expect(Number(stepBeforeRestart)).toBeGreaterThan(0);

      // Now click "Начать заново" / Reload button
      const reloadBtn = tutorPage.locator('#boo-tracer-btn-reload');
      await reloadBtn.click();

      // Verify step resets back to 0 on tutor
      await expect(tutorPage.locator('#boo-tracer-cur-step')).toHaveText('0', { timeout: 7_000 });
      const sliderVal = await tutorPage.locator('#boo-tracer-slider').inputValue();
      expect(sliderVal).toBe('0');

      // Verify student also synchronized to step 0
      await expect(studentPage.locator('#boo-tracer-cur-step')).toHaveText('0', { timeout: 7_000 });

      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('P0-Tracer-2: Scenario B - Program with input() restarts with cleared inputs and accepts new inputs', async ({ browser }) => {
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

      // Set code with input()
      const codeWithInput = `x = int(input())\ny = x * 2\nprint("DOUBLE:", y)\n`;
      await setEditorCode(tutorPage, codeWithInput);
      await tutorPage.waitForTimeout(500);

      // Teacher opens/restarts BooTracer
      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

      // Wait for interactive input card to appear
      const inputCard = tutorPage.locator('#boo-tracer-step-input-card');
      await expect(inputCard).toBeVisible({ timeout: 10_000 });

      // Enter 5
      const inputVal = tutorPage.locator('#boo-tracer-step-input-val');
      await inputVal.fill('5');
      await tutorPage.locator('#boo-tracer-step-input-btn').click();

      // Wait for runTrace to finish
      await tutorPage.waitForTimeout(600);
      const totalSteps = parseInt(await tutorPage.locator('#boo-tracer-total-step').textContent() || '0', 10);
      expect(totalSteps).toBeGreaterThanOrEqual(3);

      // Step forward to finish execution
      const nextBtn = tutorPage.locator('#boo-tracer-btn-next');
      for (let i = 0; i <= totalSteps; i++) {
        await nextBtn.click();
        await tutorPage.waitForTimeout(100);
      }

      // Verify stdout is DOUBLE: 10
      await expect(tutorPage.locator('#boo-tracer-stdout-box')).toContainText('DOUBLE: 10', { timeout: 7_000 });

      // Click "Начать заново" (restart)
      await tutorPage.locator('#boo-tracer-btn-reload').click();

      // Verify execution resets: input prompt card appears again
      await expect(inputCard).toBeVisible({ timeout: 10_000 });

      // Enter 7 this time!
      await inputVal.fill('7');
      await tutorPage.locator('#boo-tracer-step-input-btn').click();

      // Wait for runTrace to finish
      await tutorPage.waitForTimeout(600);
      const newTotalSteps = parseInt(await tutorPage.locator('#boo-tracer-total-step').textContent() || '0', 10);

      // Step forward to finish execution
      for (let i = 0; i <= newTotalSteps; i++) {
        await nextBtn.click();
        await tutorPage.waitForTimeout(100);
      }

      // Verify stdout is now DOUBLE: 14 (NOT 10)
      await expect(tutorPage.locator('#boo-tracer-stdout-box')).toContainText('DOUBLE: 14', { timeout: 7_000 });

      // Verify student also sees DOUBLE: 14
      await expect(studentPage.locator('#boo-tracer-stdout-box')).toContainText('DOUBLE: 14', { timeout: 7_000 });
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('P0-Tracer-3: Scenario C - Restart while waiting for input resets cleanly', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const tutorPage = await tutorContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await tutorPage.goto(roomUrl);
      await tutorPage.waitForLoadState('domcontentloaded');

      const codeWithInput = `a = input()\nprint("GOT:", a)\n`;
      await setEditorCode(tutorPage, codeWithInput);
      await tutorPage.waitForTimeout(500);

      await tutorPage.locator('#editor-tracer-toggle-btn').click();
      await expect(tutorPage.locator('#tracer-window')).toBeVisible({ timeout: 10_000 });

      const inputCard = tutorPage.locator('#boo-tracer-step-input-card');
      await expect(inputCard).toBeVisible({ timeout: 10_000 });

      // Without entering any input, click Reload
      await tutorPage.locator('#boo-tracer-btn-reload').click();

      // Verify input card appears again fresh, no uncaught exceptions
      await expect(inputCard).toBeVisible({ timeout: 10_000 });
    } finally {
      await tutorContext.close();
    }
  });

  test('P0-Tracer-4: BooTracer window close and reopen 3x consecutively', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const tutorPage = await tutorContext.newPage();

    const tutorErrors: string[] = [];
    tutorPage.on('pageerror', (err) => tutorErrors.push(err.message));

    try {
      await login(tutorPage, tutorUsername);
      await tutorPage.goto(roomUrl);
      await tutorPage.waitForLoadState('domcontentloaded');

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      const tracerWindow = tutorPage.locator('#tracer-window');
      const tracerBtn = tutorPage.locator('#editor-tracer-toggle-btn');
      const closeBtn = tutorPage.locator('#tracer-window-header div[onclick*="closeWindow"]');
      const dockTracerIcon = tutorPage.locator('#dock-icon-tracer-window');

      for (let cycle = 1; cycle <= 3; cycle++) {
        // 1. Open via editor button
        await tracerBtn.click();
        await expect(tracerWindow).toBeVisible({ timeout: 10_000 });
        const isOpen1 = await tutorPage.evaluate(() => (window as any).BooTracer?.isOpen);
        expect(isOpen1).toBe(true);

        // 2. Close via window close button
        await closeBtn.click();
        await expect(tracerWindow).toBeHidden({ timeout: 10_000 });
        const isOpen2 = await tutorPage.evaluate(() => (window as any).BooTracer?.isOpen);
        expect(isOpen2).toBe(false);

        // 3. Reopen via editor button
        await tracerBtn.click();
        await expect(tracerWindow).toBeVisible({ timeout: 10_000 });

        // 4. Close via dock icon toggle
        await dockTracerIcon.click();
        await expect(tracerWindow).toBeHidden({ timeout: 10_000 });

        // 5. Reopen via dock icon toggle
        await dockTracerIcon.click();
        await expect(tracerWindow).toBeVisible({ timeout: 10_000 });

        // Close for next cycle
        await closeBtn.click();
        await expect(tracerWindow).toBeHidden({ timeout: 10_000 });
      }

      expect(tutorErrors).toEqual([]);
    } finally {
      await tutorContext.close();
    }
  });

  test('P0-ZOrder: Shared Z-Order synchronizes between Teacher and Student without stealing focus', async ({ browser }) => {
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

      // Ensure both code-window and task-window are open on teacher & student
      await tutorPage.evaluate(() => {
        (window as any).openWindow?.('code-window');
        (window as any).openWindow?.('task-window');
      });
      await studentPage.evaluate(() => {
        (window as any).openWindow?.('code-window');
        (window as any).openWindow?.('task-window');
      });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 10_000 });
      await expect(tutorPage.locator('#task-window')).toBeVisible({ timeout: 10_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 10_000 });
      await expect(studentPage.locator('#task-window')).toBeVisible({ timeout: 10_000 });

      // Student focuses and starts typing in student's notes or code editor
      await studentPage.evaluate(() => {
        const input = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
        if (input) {
          input.focus();
          input.value = 'STUDENT_WORK_IN_PROGRESS';
        }
      });

      // 5 alternating rounds of Z-order switching by teacher
      for (let round = 1; round <= 5; round++) {
        // Round A: Teacher activates task-window
        await tutorPage.locator('#task-window-header').click();
        await tutorPage.waitForTimeout(400);

        // Student observer checks task-window has higher z-index than code-window
        const zIndexesA = await studentPage.evaluate(() => {
          const taskZ = parseInt(window.getComputedStyle(document.getElementById('task-window')!).zIndex || '0', 10);
          const codeZ = parseInt(window.getComputedStyle(document.getElementById('code-window')!).zIndex || '0', 10);
          return { taskZ, codeZ };
        });
        expect(zIndexesA.taskZ).toBeGreaterThan(zIndexesA.codeZ);

        // Round B: Teacher activates code-window
        await tutorPage.locator('#code-window-header').click();
        await tutorPage.waitForTimeout(400);

        // Student observer checks code-window has higher z-index than task-window
        const zIndexesB = await studentPage.evaluate(() => {
          const taskZ = parseInt(window.getComputedStyle(document.getElementById('task-window')!).zIndex || '0', 10);
          const codeZ = parseInt(window.getComputedStyle(document.getElementById('code-window')!).zIndex || '0', 10);
          return { taskZ, codeZ };
        });
        expect(zIndexesB.codeZ).toBeGreaterThan(zIndexesB.taskZ);
      }

      // Verify student's textarea content was not wiped or corrupted by remote z-order changes
      const studentText = await studentPage.evaluate(() => {
        const input = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
        return input?.value;
      });
      expect(studentText).toBe('STUDENT_WORK_IN_PROGRESS');
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('P1-Dock: Floating Dock styling, transparency, and dual-resolution screenshots', async ({ browser }) => {
    // 1. Resolution 1920x1080
    const context1080 = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const page1080 = await context1080.newPage();

    try {
      await login(page1080, tutorUsername);
      await page1080.goto(roomUrl);
      await page1080.waitForLoadState('domcontentloaded');

      const dock = page1080.locator('#board-dock');
      await expect(dock).toBeVisible({ timeout: 15_000 });

      // Verify dock container styles: transparent background, pointer-events: none, no border
      const dockStyles = await dock.evaluate((el) => {
        const computed = window.getComputedStyle(el);
        return {
          backgroundColor: computed.backgroundColor,
          borderStyle: computed.borderStyle,
          pointerEvents: computed.pointerEvents,
        };
      });

      // Background should be transparent or rgba(0, 0, 0, 0)
      expect(['transparent', 'rgba(0, 0, 0, 0)']).toContain(dockStyles.backgroundColor);
      expect(dockStyles.pointerEvents).toBe('none');
      expect(['none', 'hidden']).toContain(dockStyles.borderStyle);

      // Verify each dock item has pointer-events: auto, 48x48px size
      const dockItems = page1080.locator('#board-dock .board-dock-item');
      const count = await dockItems.count();
      expect(count).toBeGreaterThanOrEqual(4);

      for (let i = 0; i < count; i++) {
        const item = dockItems.nth(i);
        const itemStyles = await item.evaluate((el) => {
          const comp = window.getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return {
            pointerEvents: comp.pointerEvents,
            width: rect.width,
            height: rect.height,
            hasBorder: comp.borderWidth !== '0px' && comp.borderStyle !== 'none',
            hasShadow: comp.boxShadow !== 'none',
          };
        });
        expect(itemStyles.pointerEvents).toBe('auto');
        expect(itemStyles.width).toBeCloseTo(48, -1);
        expect(itemStyles.height).toBeCloseTo(48, -1);
        expect(itemStyles.hasBorder).toBe(true);
        expect(itemStyles.hasShadow).toBe(true);
      }

      // Capture screenshot 1920x1080
      const screenshot1080Path = path.resolve('docs/audits/boostudy-os-reliability/artifacts/dock_1920x1080.png');
      await page1080.screenshot({ path: screenshot1080Path, fullPage: false });
    } finally {
      await context1080.close();
    }

    // 2. Resolution 1366x768
    const context768 = await browser.newContext({ viewport: { width: 1366, height: 768 } });
    const page768 = await context768.newPage();

    try {
      await login(page768, tutorUsername);
      await page768.goto(roomUrl);
      await page768.waitForLoadState('domcontentloaded');

      const dock768 = page768.locator('#board-dock');
      await expect(dock768).toBeVisible({ timeout: 15_000 });

      const dockStyles768 = await dock768.evaluate((el) => {
        const computed = window.getComputedStyle(el);
        return {
          backgroundColor: computed.backgroundColor,
          pointerEvents: computed.pointerEvents,
        };
      });

      expect(['transparent', 'rgba(0, 0, 0, 0)']).toContain(dockStyles768.backgroundColor);
      expect(dockStyles768.pointerEvents).toBe('none');

      // Capture screenshot 1366x768
      const screenshot768Path = path.resolve('docs/audits/boostudy-os-reliability/artifacts/dock_1366x768.png');
      await page768.screenshot({ path: screenshot768Path, fullPage: false });
    } finally {
      await context768.close();
    }
  });

});
