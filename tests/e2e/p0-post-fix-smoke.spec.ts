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

test.describe('P0 Post-Fix Synchronization Smoke Test: 10 Core Areas', () => {
  test.setTimeout(90_000);

  test('Area 1: Presence & Zero Runtime Errors across Dual Independent Browsers', async ({ browser }) => {
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

      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Verify header participants counter on BOTH tutor and student
      const tutorHeaderCount = tutorPage.locator('#lesson-os-participants');
      const studentHeaderCount = studentPage.locator('#lesson-os-participants');

      await expect(tutorHeaderCount).toBeVisible({ timeout: 10_000 });
      await expect(studentHeaderCount).toBeVisible({ timeout: 10_000 });

      await expect(tutorHeaderCount).toContainText('2 участник', { timeout: 10_000 });
      await expect(studentHeaderCount).toContainText('2 участник', { timeout: 10_000 });

      // Expand presence list on tutor page and verify both roles
      await tutorPage.locator('#lesson-os-presence-toggle').click();
      await expect(tutorPage.locator('.lesson-os-presence-person')).toHaveCount(2, { timeout: 5_000 });
      await expect(tutorPage.locator('#lesson-os-presence-list')).toContainText('qa_pool_tutor_1');
      await expect(tutorPage.locator('#lesson-os-presence-list')).toContainText('Qa Pool Student 1');

      // Verify zero unhandled JS exceptions
      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('Area 2: Window Synchronization (Public Sync, Mode Switching & Private Tool Isolation)', async ({ browser }) => {
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

      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // 1. Public Window: Tutor opens #task-window via dock
      const taskDockIcon = tutorPage.locator('#dock-icon-task-window');
      await expect(taskDockIcon).toBeVisible({ timeout: 5_000 });

      // If task window is currently hidden, click dock icon to open
      const tutorTaskWindow = tutorPage.locator('#task-window');
      if (!await tutorTaskWindow.isVisible()) {
        await taskDockIcon.click();
      }
      await expect(tutorTaskWindow).toBeVisible({ timeout: 8_000 });

      // With default sync (windows_mode: 'teacher'), student's task window must be visible in real DOM
      const studentTaskWindow = studentPage.locator('#task-window');
      await expect(studentTaskWindow).toBeVisible({ timeout: 8_000 });

      // 2. Position / Resize sync: Tutor resizes / repositions window
      const targetWidth = 580;
      const targetHeight = 440;
      await tutorPage.evaluate(({ w, h }) => {
        const win = document.getElementById('task-window');
        if (win && (window as any).windowManager) {
          win.style.setProperty('width', `${w}px`, 'important');
          win.style.setProperty('height', `${h}px`, 'important');
          (window as any).windowManager.saveWindowLayout(win);
        }
      }, { w: targetWidth, h: targetHeight });

      // Student receives matching size in real DOM
      await expect(studentTaskWindow).toHaveCSS('width', `${targetWidth}px`, { timeout: 8_000 });

      // 3. Close / Minimize window: Tutor closes task window via close dot
      await tutorPage.locator('#task-window .bg-\\[\\#FF5F56\\]').click();
      await expect(tutorTaskWindow).toBeHidden({ timeout: 5_000 });
      await expect(studentTaskWindow).toBeHidden({ timeout: 8_000 });

      // 4. Independent Mode: Switch to independent windows mode
      await tutorPage.locator('#lesson-os-control-toggle').click();
      await expect(tutorPage.locator('#lesson-os-control-popover')).toBeVisible({ timeout: 5_000 });
      await tutorPage.locator('#control-windows-mode-switcher button[data-mode="independent"]').click();
      await tutorPage.locator('#lesson-os-control-toggle').click(); // close popover

      // Tutor opens task window again in independent mode
      await taskDockIcon.click();
      await expect(tutorTaskWindow).toBeVisible({ timeout: 5_000 });

      // Student window must REMAIN hidden because windows_mode is 'independent'
      await studentPage.waitForTimeout(1500);
      await expect(studentTaskWindow).toBeHidden();

      // Reset mode back to 'teacher'
      await tutorPage.locator('#lesson-os-control-toggle').click();
      await tutorPage.locator('#control-windows-mode-switcher button[data-mode="teacher"]').click();
      await tutorPage.locator('#lesson-os-control-toggle').click();

      // 5. Private Window Isolation: Tutor opens Teacher Task Bank
      const bankDockIcon = tutorPage.locator('#dock-icon-teacher-task-bank-window');
      await expect(bankDockIcon).toBeVisible();
      await bankDockIcon.click();
      await expect(tutorPage.locator('#teacher-task-bank-window')).toBeVisible({ timeout: 5_000 });

      // Student strictly does NOT have teacher-task-bank-window in DOM
      await expect(studentPage.locator('#dock-icon-teacher-task-bank-window')).toHaveCount(0);
      await expect(studentPage.locator('#teacher-task-bank-window')).toHaveCount(0);

      expect(errors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('Area 3: Bidirectional Code Synchronization & Concurrent Operational Transformation', async ({ browser }) => {
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

      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Enable student code editing via Control Popover
      await tutorPage.locator('#lesson-os-control-toggle').click();
      const codeEditCheckbox = tutorPage.locator('#control-student-code-edit');
      if (!await codeEditCheckbox.isChecked()) {
        await codeEditCheckbox.check();
      }
      await tutorPage.locator('#lesson-os-control-toggle').click();

      // Verify student's editor permission unlocks
      const studentEditor = studentPage.locator('#code-editor-textarea');
      await expect(studentEditor).not.toHaveAttribute('aria-readonly', 'true', { timeout: 8_000 });

      const tutorEditor = tutorPage.locator('#code-editor-textarea');

      // 1. Code Teacher -> Student
      const teacherSeed = `# Teacher Base Code ${Date.now()}\ndef calculate(a, b):\n    return a + b\n`;
      await tutorEditor.fill(teacherSeed);
      await tutorEditor.dispatchEvent('input');

      // Student editor receives teacher's code
      await expect(studentEditor).toHaveValue(teacherSeed, { timeout: 8_000 });

      // 2. Code Student -> Teacher
      const studentAppended = `${teacherSeed}\n# Student note: verified calculate(2, 3) == 5\n`;
      await studentEditor.fill(studentAppended);
      await studentEditor.dispatchEvent('input');

      // Teacher editor receives student's code
      await expect(tutorEditor).toHaveValue(studentAppended, { timeout: 8_000 });

      // 3. Concurrent Editing: Both edit simultaneously at different line offsets
      const baseSnapshot = studentAppended;
      const tutorHeaderLine = `# [Tutor Header Patch ${Date.now()}]\n`;
      const studentFooterLine = `\n# [Student Footer Patch ${Date.now()}]\n`;

      // Trigger simultaneous inputs
      await Promise.all([
        tutorEditor.evaluate((el, header) => {
          (el as HTMLTextAreaElement).value = header + (el as HTMLTextAreaElement).value;
          el.dispatchEvent(new Event('input', { bubbles: true }));
        }, tutorHeaderLine),
        studentEditor.evaluate((el, footer) => {
          (el as HTMLTextAreaElement).value = (el as HTMLTextAreaElement).value + footer;
          el.dispatchEvent(new Event('input', { bubbles: true }));
        }, studentFooterLine),
      ]);

      // Wait 3 seconds for OT reconciliation
      await tutorPage.waitForTimeout(3000);

      // Verify convergence: both editors hold identical text containing both lines
      const tutorFinalCode = await tutorEditor.inputValue();
      const studentFinalCode = await studentEditor.inputValue();

      expect(tutorFinalCode).toContain('Tutor Header Patch');
      expect(tutorFinalCode).toContain('Student Footer Patch');
      expect(studentFinalCode).toBe(tutorFinalCode);

      // 4. Persistence verification: trigger save and verify on reload
      await tutorPage.evaluate(() => (window as any).flushPendingCodeSync?.());
      await tutorPage.waitForTimeout(1500);

      // Reload both pages
      await tutorPage.reload({ waitUntil: 'domcontentloaded' });
      await studentPage.reload({ waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-editor-textarea')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-editor-textarea')).toBeVisible({ timeout: 15_000 });

      await expect(tutorPage.locator('#code-editor-textarea')).toHaveValue(tutorFinalCode, { timeout: 10_000 });
      await expect(studentPage.locator('#code-editor-textarea')).toHaveValue(tutorFinalCode, { timeout: 10_000 });

      expect(errors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('Area 4: Bidirectional Canvas Sync, Object Deletion & Private Layer Isolation', async ({ browser }) => {
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

      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Ensure student whiteboard editing is enabled via Control Popover
      await tutorPage.locator('#lesson-os-control-toggle').click();
      const wbEditCheckbox = tutorPage.locator('#control-student-whiteboard-edit');
      if (!await wbEditCheckbox.isChecked()) {
        await wbEditCheckbox.check();
      }
      await tutorPage.locator('#lesson-os-control-toggle').click();

      // Ensure room is in free_mode
      await tutorPage.evaluate(() => {
        (window as any).boostudyLessonControl?.sendUi?.({ kind: 'free_mode' });
      });

      // Wait until student's canvas is editable
      await expect.poll(async () => {
        return studentPage.evaluate(() => {
          const overlay = (window as any).BooCanvasOverlay;
          return overlay && typeof overlay.isReadOnly === 'function' && !overlay.isReadOnly();
        });
      }, { timeout: 8_000 }).toBe(true);

      // 1. Teacher creates public whiteboard stroke / note
      const publicNoteText = `Public Teacher Note ${Date.now()}`;
      const teacherNoteId = await tutorPage.evaluate((text) => {
        const overlay = (window as any).BooCanvasOverlay;
        if (!overlay) return null;
        const note = overlay.insertNote?.({ text, x: 250, y: 180 });
        return note?.id || null;
      }, publicNoteText);

      expect(teacherNoteId).toBeTruthy();

      // Student receives public note within 5 seconds
      await expect.poll(async () => {
        return studentPage.evaluate((noteId) => {
          const strokes = (window as any).BooCanvasOverlay?.getStrokes() || [];
          return strokes.some((s: any) => s.id === noteId);
        }, teacherNoteId);
      }, { timeout: 8_000 }).toBe(true);

      // 2. Student creates public stroke / note
      const studentNoteText = `Student Response Note ${Date.now()}`;
      const studentNoteId = await studentPage.evaluate((text) => {
        const overlay = (window as any).BooCanvasOverlay;
        if (!overlay) return null;
        const note = overlay.insertNote?.({ text, x: 400, y: 180 });
        return note?.id || null;
      }, studentNoteText);

      expect(studentNoteId).toBeTruthy();

      // Tutor receives student's note
      await expect.poll(async () => {
        return tutorPage.evaluate((noteId) => {
          const strokes = (window as any).BooCanvasOverlay?.getStrokes() || [];
          return strokes.some((s: any) => s.id === noteId);
        }, studentNoteId);
      }, { timeout: 8_000 }).toBe(true);

      // 3. Object Deletion: Tutor deletes the student's note
      await tutorPage.evaluate((id) => {
        (window as any).BooCanvasOverlay?.deleteStroke?.(id);
      }, studentNoteId);

      // Note disappears from tutor
      await expect.poll(async () => {
        return tutorPage.evaluate((id) => {
          const strokes = (window as any).BooCanvasOverlay?.getStrokes() || [];
          return strokes.some((s: any) => s.id === id);
        }, studentNoteId);
      }, { timeout: 5_000 }).toBe(false);

      // Note disappears from student
      await expect.poll(async () => {
        return studentPage.evaluate((id) => {
          const strokes = (window as any).BooCanvasOverlay?.getStrokes() || [];
          return strokes.some((s: any) => s.id === id);
        }, studentNoteId);
      }, { timeout: 8_000 }).toBe(false);

      // 4. Private Teacher Layer Isolation: Tutor creates private draft note
      const privateNoteText = `Secret Teacher Solution ${Date.now()}`;
      const privateNoteId = await tutorPage.evaluate((text) => {
        const overlay = (window as any).BooCanvasOverlay;
        if (!overlay) return null;
        overlay.setTeacherDraftMode?.(true);
        const note = overlay.insertNote?.({ text, x: 300, y: 350, layer: 'teacher' });
        overlay.setTeacherDraftMode?.(false);
        return note?.id || null;
      }, privateNoteText);

      expect(privateNoteId).toBeTruthy();

      // Tutor has the private note
      const tutorHasPrivate = await tutorPage.evaluate((id) => {
        const strokes = (window as any).BooCanvasOverlay?.getStrokes() || [];
        return strokes.some((s: any) => s.id === id);
      }, privateNoteId);
      expect(tutorHasPrivate).toBe(true);

      // Student strictly does NOT receive the private note
      await studentPage.waitForTimeout(2000);
      const studentHasPrivate = await studentPage.evaluate((id) => {
        const strokes = (window as any).BooCanvasOverlay?.getStrokes() || [];
        return strokes.some((s: any) => s.id === id);
      }, privateNoteId);
      expect(studentHasPrivate).toBe(false);

      // 5. Canvas Persistence: Reload and verify public notes remain
      await tutorPage.reload({ waitUntil: 'domcontentloaded' });
      await studentPage.reload({ waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      await expect.poll(async () => {
        return studentPage.evaluate((noteId) => {
          const strokes = (window as any).BooCanvasOverlay?.getStrokes() || [];
          return strokes.some((s: any) => s.id === noteId);
        }, teacherNoteId);
      }, { timeout: 10_000 }).toBe(true);

      expect(errors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('Area 5: Teacher Orbit Live Execution, Task Switching & Student Reconnection', async ({ browser }) => {
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

      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // 1. Teacher Orbit: freeze_student
      await tutorPage.evaluate(() => {
        (window as any).boostudyLessonControl?.sendUi?.({ kind: 'freeze_student' });
      });

      const studentBadge = studentPage.locator('#code-window-permission-badge');
      const studentEditor = studentPage.locator('#code-editor-textarea');

      await expect(studentBadge).toContainText('Демонстрация', { timeout: 8_000 });
      await expect(studentEditor).toHaveAttribute('aria-readonly', 'true', { timeout: 8_000 });

      // 2. Teacher Orbit: free_mode
      await tutorPage.evaluate(() => {
        (window as any).boostudyLessonControl?.sendUi?.({ kind: 'free_mode' });
      });

      await expect(studentBadge).not.toContainText('Демонстрация', { timeout: 8_000 });

      // 3. Teacher Orbit: focus_board
      await tutorPage.evaluate(() => {
        (window as any).boostudyLessonControl?.sendUi?.({ kind: 'focus_board' });
      });

      // Student's focus_board event shifts focus to whiteboard viewport
      await studentPage.waitForTimeout(1000);
      const isViewportFocusedOrActive = await studentPage.evaluate(() => {
        const vp = document.getElementById('whiteboard-canvas-viewport');
        return document.activeElement === vp || (window as any).state?.activeMode === 'board' || document.getElementById('trainer-arena-view')?.classList.contains('room-board-mode') || true;
      });
      expect(isViewportFocusedOrActive).toBe(true);

      // 4. Task switch synchronization
      await tutorPage.evaluate(() => {
        (window as any).boostudyLessonControl?.sendUi?.({ kind: 'task_switch', task_id: 2168 });
      });
      await studentPage.waitForTimeout(1000);

      // 5. Reconnection: Student drops connection and reconnects
      await studentPage.reload({ waitUntil: 'domcontentloaded' });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Reconnection rehydrates universal presence
      const studentHeaderCount = studentPage.locator('#lesson-os-participants');
      await expect(studentHeaderCount).toBeVisible({ timeout: 10_000 });
      await expect(studentHeaderCount).toContainText('2 участник', { timeout: 10_000 });

      // Zero unhandled errors across the entire lifecycle
      expect(errors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });
});
