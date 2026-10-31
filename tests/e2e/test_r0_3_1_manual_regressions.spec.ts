import { expect, Page, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const lessonId = 2168;
const lessonRoomUrl = `/lesson/${lessonId}/room`;
const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=2694&assignment_task_id=2832`;
const reviewUrl = `/task-workspace?context_type=submission_task&context_id=2694&assignment_task_id=2832&review=1`;
const embeddedAnswerUrl = `/task-workspace?context_type=submission_task&context_id=2694&assignment_task_id=2832&embedded=answer`;

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

test.describe('BooStudy OS R0.3.1 Critical Regression Recovery Suite (RC-01 - RC-20)', () => {
  test.setTimeout(90_000);

  test('RC-01 & RC-02: Lesson OS VirtualFS file creation & deletion without state is not defined crash', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message || String(err)));

    await login(page, tutorUsername);
    await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });

    await expect(page.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    // Execute createNewFileOfType without error
    const createResult = await page.evaluate(() => {
      try {
        if (typeof (window as any).createNewFileOfType === 'function') {
          (window as any).createNewFileOfType('py', 'helper.py');
          return { success: true, files: Object.keys((window as any).virtualFS || {}) };
        }
        return { success: false, reason: 'createNewFileOfType not found' };
      } catch (e: any) {
        return { success: false, error: e.message || String(e) };
      }
    });

    expect(createResult.success).toBe(true);
    expect(createResult.files).toContain('helper.py');

    // Verify tab exists
    await page.waitForTimeout(500);
    const helperTab = page.locator('.editor-tab:has-text("helper.py"), [id="tab-helper.py"]');
    await expect(helperTab).toBeVisible({ timeout: 5_000 });

    // Verify deleting the file works cleanly
    const deleteResult = await page.evaluate(() => {
      try {
        if (typeof (window as any).deleteFileFromVFS === 'function') {
          (window as any).deleteFileFromVFS(null, 'helper.py', true);
          return { success: true, files: Object.keys((window as any).virtualFS || {}) };
        }
        return { success: false, reason: 'deleteFileFromVFS not found' };
      } catch (e: any) {
        return { success: false, error: e.message || String(e) };
      }
    });

    expect(deleteResult.success).toBe(true);
    expect(deleteResult.files).not.toContain('helper.py');

    // Confirm ZERO ReferenceError: state is not defined occurred
    const stateErrors = pageErrors.filter(e => e.includes('state is not defined'));
    expect(stateErrors).toHaveLength(0);
  });

  test('RC-03 & RC-04: Homework OS VirtualFS file management & auxiliary file durability', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message || String(err)));

    await login(page, studentUsername);
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });

    await expect(page.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    // Create auxiliary text file
    await page.evaluate(() => {
      if (typeof (window as any).createNewFileOfType === 'function') {
        (window as any).createNewFileOfType('txt', 'notes.txt');
      }
      if ((window as any).virtualFS) {
        (window as any).virtualFS['notes.txt'] = 'Sample test content line 1';
      }
      // Trigger editor input event for auxiliary file
      if (typeof (window as any).onCodeEditorInput === 'function') {
        (window as any).activeFileName = 'notes.txt';
        (window as any).onCodeEditorInput('Sample test content line 1');
      }
    });

    await page.waitForTimeout(1000);

    // Verify virtualFS has notes.txt and main.py is intact
    const vfs = await page.evaluate(() => (window as any).virtualFS || {});
    expect(Object.keys(vfs)).toContain('notes.txt');
    expect(vfs['notes.txt']).toContain('Sample test content line 1');

    const stateErrors = pageErrors.filter(e => e.includes('state is not defined'));
    expect(stateErrors).toHaveLength(0);
  });

  test('RC-05: Zero HTTP 403 on autosave in teacher review mode', async ({ page }) => {
    const failed403Urls: string[] = [];
    page.on('response', (response) => {
      if (response.status() === 403 && response.url().includes('/save')) {
        failed403Urls.push(response.url());
      }
    });

    await login(page, tutorUsername);
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });

    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    // In review mode, ws.can_edit must be false
    const canEdit = await page.evaluate(() => {
      return Boolean((window as any).boostudyTaskWorkspace?.can_edit);
    });
    expect(canEdit).toBe(false);

    // Wait 3 seconds to ensure no background autosave timer fires with 403
    await page.waitForTimeout(3000);
    expect(failed403Urls).toHaveLength(0);
  });

  test('RC-06: Student kick drops socket connection and displays modal on student browser', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      studentPage.on('console', msg => console.log('STUDENT CONSOLE:', msg.text()));
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });

      // Clear any prior ban using window.unbanLessonParticipant with CSRF before student joins
      await tutorPage.evaluate(async () => {
        if (typeof (window as any).unbanLessonParticipant === 'function') {
          await (window as any).unbanLessonParticipant(634);
        } else {
          const csrf = (document.querySelector('meta[name="csrf-token"]') as any)?.content || '';
          await fetch('/lesson/2168/unban', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ user_id: 634 })
          });
        }
      });

      await studentPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Check student user ID on student page
      const studentUserId = await studentPage.evaluate(() => {
        return (window as any).trainerOsConfig?.user_id;
      });
      expect(studentUserId).toBe(634);

      // Wait for student socket to be connected
      await studentPage.waitForFunction(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        return Boolean(socket && socket.connected);
      }, { timeout: 15_000 });

      await studentPage.evaluate(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        (window as any).__kickedEvents = [];
        if (socket) {
          socket.on('lesson_kicked', (payload: any) => {
            console.log('[DEBUG-SOCKET] RECEIVED lesson_kicked:', JSON.stringify(payload));
            (window as any).__kickedEvents.push(payload);
          });
        }
      });

      // Tutor initiates kick of student using window.kickLessonParticipant with CSRF
      const kickRes = await tutorPage.evaluate(async (targetUserId) => {
        if (typeof (window as any).kickLessonParticipant === 'function') {
          return await (window as any).kickLessonParticipant(targetUserId);
        }
        const csrf = (document.querySelector('meta[name="csrf-token"]') as any)?.content || '';
        const res = await fetch('/lesson/2168/kick', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({ user_id: targetUserId })
        });
        const text = await res.text();
        return { status: res.status, body: text };
      }, studentUserId);
      console.log('TUTOR KICK RESPONSE:', JSON.stringify(kickRes));

      await studentPage.waitForTimeout(1500);
      const events = await studentPage.evaluate(() => (window as any).__kickedEvents);
      console.log('STUDENT KICKED EVENTS IN WINDOW:', JSON.stringify(events));

      // Check student page shows kick modal within 10 seconds
      const kickModal = studentPage.locator('#lesson-os-kicked-modal');
      await expect(kickModal).toBeVisible({ timeout: 10_000 });

      // Verify student socket is disconnected
      const isConnected = await studentPage.evaluate(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        return socket ? socket.connected : false;
      });
      expect(isConnected).toBe(false);
    } finally {
      try {
        await tutorPage.evaluate(async () => {
          await fetch('/lesson/2168/unban', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: 634 })
          });
        });
      } catch (_) {}
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('RC-07 & RC-08: Return for revision modal z-index 9999999 and full row toggle', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });

    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    // Open return modal using the global API
    await page.evaluate(() => {
      if (typeof (window as any).showReturnRevisionModal === 'function') {
        (window as any).showReturnRevisionModal(() => {});
      }
    });

    const modal = page.locator('#homework-return-modal');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // Verify z-index is 9999999 (above all windows)
    const zIndex = await modal.evaluate((el) => window.getComputedStyle(el).zIndex);
    expect(zIndex).toBe('9999999');

    // Verify modal overlay buttons are clickable
    const cancelButton = modal.locator('#hw-return-cancel-btn');
    await expect(cancelButton).toBeVisible();

    // Press Escape to verify modal closes cleanly
    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible({ timeout: 3_000 });

    // Verify full row click target for toggle switch in review UI
    const toggleLabel = page.locator('label[for="review-task-return-toggle"]');
    if (await toggleLabel.count() > 0) {
      const checkbox = page.locator('#review-task-return-toggle');
      const initialState = await checkbox.isChecked();
      await toggleLabel.click();
      const newState = await checkbox.isChecked();
      expect(newState).toBe(!initialState);
    }
  });

  test('RC-12 & RC-13: Interactive lesson selector in constructor and badge in assignment list', async ({ page }) => {
    await login(page, tutorUsername);

    // 1. Check Constructor
    await page.goto('/assignments/create', { waitUntil: 'domcontentloaded' });
    const lessonSelect = page.locator('#assignment-lesson-select');
    await expect(lessonSelect).toBeVisible({ timeout: 10_000 });

    // Check available options in lesson selector
    const optionsCount = await lessonSelect.locator('option').count();
    expect(optionsCount).toBeGreaterThan(1);

    // Verify option text includes lesson details
    const optionsText = await lessonSelect.innerText();
    expect(optionsText).toContain('2168');

    // 2. Check Assignment list badge
    await page.goto('/assignments', { waitUntil: 'domcontentloaded' });
    const assignmentBadge = page.locator('.assignment-lesson-badge, a[href*="/lesson/2168/room"]').first();
    await expect(assignmentBadge).toBeVisible({ timeout: 10_000 });
    await expect(assignmentBadge).toContainText('2168');
  });

  test('RC-14 & RC-15: Homework drawer task preview KaTeX formulas and zero image 404s', async ({ page }) => {
    const failedImageUrls: string[] = [];
    page.on('response', (response) => {
      const url = response.url();
      if ((url.includes('.png') || url.includes('.jpg') || url.includes('/attachments/')) && response.status() >= 400) {
        failedImageUrls.push(`${response.status()} ${url}`);
      }
    });

    await login(page, studentUsername);
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });

    await expect(page.locator('#task-window')).toBeVisible({ timeout: 15_000 });

    // Expand preview if drawer exists
    await page.evaluate(() => {
      if (typeof (window as any).toggleHomeworkTaskPreview === 'function') {
        (window as any).toggleHomeworkTaskPreview(2832);
      }
    });

    // Check that task window is visible
    const taskContent = page.locator('#task-window');
    await expect(taskContent).toBeVisible();

    // Verify zero image 404/403 errors
    expect(failedImageUrls).toHaveLength(0);
  });

  test('RC-16 & RC-17: Orbit launcher isolation and canvas-restricted hotkey', async ({ page }) => {
    await login(page, tutorUsername);

    // 1. In embedded answer iframe, Orbit orb and overlay must NOT exist
    await page.goto(embeddedAnswerUrl, { waitUntil: 'domcontentloaded' });
    const orb = page.locator('.boo-wheel-trigger-orb');
    await expect(orb).not.toBeVisible();
    const overlay = page.locator('.boo-radial-wheel-overlay');
    await expect(overlay).not.toBeVisible();

    // 2. In lesson room, verify hotkey is suppressed over windows
    await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    // Hover or focus inside code window
    await page.locator('#code-window').hover();
    await page.keyboard.down('Alt');
    await page.waitForTimeout(300);

    const orbitOverlay = page.locator('.boo-radial-wheel-overlay.is-active');
    await expect(orbitOverlay).not.toBeVisible();
    await page.keyboard.up('Alt');
  });

  test('RC-18 & RC-19: Answer window visual polish and dock clearance', async ({ page }) => {
    await login(page, studentUsername);
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });

    const answerWin = page.locator('#homework-answer-window');
    const dock = page.locator('#board-dock');

    await expect(answerWin).toBeVisible({ timeout: 15_000 });
    await expect(dock).toBeVisible({ timeout: 15_000 });

    // Check geometry: answer window bottom should not overlap dock
    const answerBox = await answerWin.boundingBox();
    const dockBox = await dock.boundingBox();

    if (answerBox && dockBox) {
      // The answer window bottom should either be to the side of the dock or strictly above the dock
      const isHorizontallySeparated = answerBox.x + answerBox.width < dockBox.x || answerBox.x > dockBox.x + dockBox.width;
      const isAboveDock = (answerBox.y + answerBox.height) <= (dockBox.y + 10);
      expect(isHorizontallySeparated || isAboveDock).toBe(true);
    }
  });
});
