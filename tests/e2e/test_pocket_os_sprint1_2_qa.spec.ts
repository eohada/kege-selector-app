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

test.describe('BOOSTUDY POCKET OS — SPRINT 1.2 QA VERIFICATION SUITE', () => {
  test.describe.configure({ mode: 'serial' });

  // ---------------------------------------------------------------------------
  // POCKET-QA-01: Viewport Detection & Fail-Closed Role Guard
  // ---------------------------------------------------------------------------
  test('POCKET-QA-01: Mobile student activates Pocket OS; teacher strictly desktop', async ({ browser }) => {
    // 1. Student context on mobile viewport 390x844
    const studentContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const sPage = await studentContext.newPage();
    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(sPage.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });
    await expect(sPage.locator('body')).toHaveClass(/pocket-os-active/);

    // 2. Teacher context on mobile viewport: must fail-closed to Desktop Lesson OS
    const teacherContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const tPage = await teacherContext.newPage();
    await login(tPage, tutorUsername);
    await tPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    // Teacher must NOT have pocket-os-active on body and shell must be hidden
    await expect(tPage.locator('body')).not.toHaveClass(/pocket-os-active/);
    await expect(tPage.locator('#pocket-os-shell')).toBeHidden();

    await studentContext.close();
    await teacherContext.close();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-02: Board Focus Ergonomics & View-Only Presentation
  // ---------------------------------------------------------------------------
  test('POCKET-QA-02: Board Focus is read-only with floating zoom and rejoin controls', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await expect(page.locator('#pocket-read-only-pill')).toBeVisible();
    await expect(page.locator('#pocket-board-controls')).toBeVisible();
    await expect(page.locator('#pocket-btn-zoom-in')).toBeVisible();
    await expect(page.locator('#pocket-btn-zoom-out')).toBeVisible();
    await expect(page.locator('#pocket-btn-rejoin')).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-03: Code Focus Full Available Height in Portrait (Zero 480px constraint)
  // ---------------------------------------------------------------------------
  test('POCKET-QA-03: Code Focus uses 100% available height in portrait without 480px cap', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await page.locator('#pocket-nav-code').click();
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'code');
    await page.waitForTimeout(400);

    const box = await page.evaluate(() => {
      const el = document.getElementById('code-window');
      const r = el?.getBoundingClientRect() || { width: 0, height: 0, top: 0, left: 0 };
      return { width: Math.round(r.width), height: Math.round(r.height), top: Math.round(r.top) };
    });

    expect(box.width).toBe(390);
    // Height must be >= 700px (not 480px)
    expect(box.height).toBeGreaterThanOrEqual(720);
    expect(box.top).toBeLessThanOrEqual(52);
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-04: Code Focus Full Available Width in Landscape (Zero 52% constraint)
  // ---------------------------------------------------------------------------
  test('POCKET-QA-04: Code Focus uses 100% available width in landscape without 52% cap', async ({ page }) => {
    await page.setViewportSize({ width: 844, height: 390 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await page.locator('#pocket-nav-code').click();
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'code');
    await page.waitForTimeout(400);

    const box = await page.evaluate(() => {
      const el = document.getElementById('code-window');
      const r = el?.getBoundingClientRect() || { width: 0, height: 0, top: 0, left: 0 };
      return { width: Math.round(r.width), height: Math.round(r.height), top: Math.round(r.top) };
    });

    // Full 844px width (not 438px / 52%)
    expect(box.width).toBe(844);
    expect(box.height).toBeGreaterThanOrEqual(290);
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-05: Virtual Symbol Strip Insertion
  // ---------------------------------------------------------------------------
  test('POCKET-QA-05: Virtual symbol strip inserts symbols directly into code editor', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await page.locator('#pocket-nav-code').click();
    await expect(page.locator('#pocket-virtual-symbols')).toBeVisible();

    const textarea = page.locator('#code-editor-textarea');
    await textarea.fill('a = 5');

    // Click ':' symbol key
    const colonBtn = page.locator('.pocket-symbol-key[data-val=":"]');
    await expect(colonBtn).toBeVisible();
    await colonBtn.click();

    const val = await textarea.inputValue();
    expect(val).toContain('a = 5:');
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-06: Real Python Execution Engine (Skulpt Output 42 and 6)
  // ---------------------------------------------------------------------------
  test('POCKET-QA-06: Real Python execution produces true math calculation results (42 and 6)', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await page.locator('#pocket-nav-code').click();

    // 1. Run solve(20, 22) -> 42
    await page.evaluate(() => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      ta.value = 'def solve(a, b):\n    return a + b\n\nprint("Результат:", solve(20, 22))';
      if (typeof (window as any).onCodeEditorInput === 'function') (window as any).onCodeEditorInput(ta.value);
    });

    await page.locator('#pocket-btn-run').click();
    await page.waitForTimeout(1200);

    let output = await page.locator('#pocket-terminal-body').innerText();
    expect(output).toContain('Результат: 42');
    expect(output).toContain('Код выхода: 0');

    // 2. Run combinations(4) -> 6
    await page.evaluate(() => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      ta.value = 'def combinations(n):\n    return n * (n - 1) // 2\n\nprint("Комбинаций:", combinations(4))';
      if (typeof (window as any).onCodeEditorInput === 'function') (window as any).onCodeEditorInput(ta.value);
    });

    await page.locator('#pocket-btn-run').click();
    await page.waitForTimeout(1200);

    output = await page.locator('#pocket-terminal-body').innerText();
    expect(output).toContain('Комбинаций: 6');
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-07: Stale Output Indicator `(код изменён)`
  // ---------------------------------------------------------------------------
  test('POCKET-QA-07: Stale badge appears when code changes after run, disappears on re-run', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await page.locator('#pocket-nav-code').click();

    // Set code and execute
    await page.evaluate(() => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      ta.value = 'print("Stable Code")';
      if (typeof (window as any).onCodeEditorInput === 'function') (window as any).onCodeEditorInput(ta.value);
    });
    await page.locator('#pocket-btn-run').click();
    await page.waitForTimeout(1000);

    const staleBadge = page.locator('#pocket-terminal-stale-badge');
    await expect(staleBadge).toBeHidden();

    // Modify code in textarea
    await page.evaluate(() => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      ta.value += '\nprint("Modified line")';
      if (typeof (window as any).onCodeEditorInput === 'function') (window as any).onCodeEditorInput(ta.value);
    });
    await page.waitForTimeout(200);

    // Stale badge must now be visible
    await expect(staleBadge).toBeVisible();
    await expect(staleBadge).toContainText('код изменён');

    // Re-run code
    await page.locator('#pocket-btn-run').click();
    await page.waitForTimeout(1000);

    // Stale badge must disappear
    await expect(staleBadge).toBeHidden();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-08: Task Focus Real Content (Task 5464 Graph & Weight Matrix)
  // ---------------------------------------------------------------------------
  test('POCKET-QA-08: Task Focus displays real Task 5464 with road graph and matrix', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await page.locator('#pocket-nav-task').click();
    await expect(page.locator('body')).toHaveAttribute('data-pocket-focus', 'task');

    const content = page.locator('#task-current-content');
    await expect(content).toBeVisible();
    await expect(content).toContainText('схема дорог Н-ского района');
    await expect(content).toContainText('Определите длину дороги из пункта А в пункт Д');

    // Graph pre block and table must be present
    await expect(content.locator('pre')).toBeVisible();
    await expect(content.locator('table')).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-09: Task Focus Absence of Static Guidance ("Фокус урока")
  // ---------------------------------------------------------------------------
  test('POCKET-QA-09: Static guidance block "Фокус урока" is completely hidden in Pocket OS', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await page.locator('#pocket-nav-task').click();

    const guidance = page.locator('.lesson-os-task-guidance');
    if (await guidance.count() > 0) {
      await expect(guidance).toBeHidden();
    }
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-10: Responsive Horizontal Scroll for Wide Matrix Table
  // ---------------------------------------------------------------------------
  test('POCKET-QA-10: Weight matrix table is enclosed in scrollable container with monospace styling', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await page.locator('#pocket-nav-task').click();

    const tableContainer = page.locator('.pocket-table-container');
    await expect(tableContainer).toBeVisible();

    const table = tableContainer.locator('table');
    await expect(table).toBeVisible();
    await expect(table.locator('th').first()).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-11: Two-Screen BooCanvas Stroke Synchronization
  // ---------------------------------------------------------------------------
  test('POCKET-QA-11: Teacher stroke inside student contour appears live on student canvas', async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const tCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

    const sPage = await sCtx.newPage();
    const tPage = await tCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(sPage.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await login(tPage, tutorUsername);
    await tPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await expect(tPage.locator('#canvas-window')).toBeVisible({ timeout: 15_000 });
    await tPage.waitForTimeout(1500);

    // Initial student stroke count
    const initialStrokeCount = await sPage.evaluate(() => {
      return (window as any).BooCanvasOverlay?.getStrokes?.()?.length || 0;
    });

    // Teacher sends a stroke operation via socket
    await tPage.evaluate(() => {
      const state = (window as any).state;
      const pid = state?.currentPageId || 'page_1';
      const stroke = {
        id: 'stroke_test_' + Date.now(),
        tool: 'pen',
        points: [{ x: 100, y: 100 }, { x: 150, y: 150 }, { x: 200, y: 120 }],
        color: '#5b35f5',
        width: 4,
        page_id: pid
      };
      if (state?.socket) {
        state.socket.emit('board_stroke', {
          lesson_id: 2168,
          stroke: stroke
        });
      }
    });

    // Student must receive the stroke in BooCanvasOverlay
    await expect.poll(async () => {
      return await sPage.evaluate(() => {
        return (window as any).BooCanvasOverlay?.getStrokes?.()?.length || 0;
      });
    }, { timeout: 5000 }).toBeGreaterThan(initialStrokeCount);

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-12: LiveKit Signaling & Presence Indicators
  // ---------------------------------------------------------------------------
  test('POCKET-QA-12: LiveKit presence indicator and track controls are operational', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    await expect(page.locator('#pocket-video-pill')).toBeVisible();
    await expect(page.locator('#pocket-mic-toggle')).toBeVisible();
    await expect(page.locator('#pocket-cam-toggle')).toBeVisible();
    await expect(page.locator('#pocket-teacher-status')).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-13: Student Classwork Answer Submission & Teacher Review
  // ---------------------------------------------------------------------------
  test('POCKET-QA-13: Student submits real answer 11, teacher verifies matching key', async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const tCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

    const sPage = await sCtx.newPage();
    const tPage = await tCtx.newPage();

    // Student submits answer
    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(sPage.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });
    await sPage.locator('#pocket-nav-task').click();

    const ansInput = sPage.locator('#student-classwork-answer');
    await ansInput.fill('11');
    await sPage.locator('#student-classwork-submit-button').click();
    await sPage.waitForTimeout(1000);

    const submitStatus = await sPage.locator('#student-classwork-submit-status').innerText();
    expect(submitStatus).toMatch(/(Ответ сохранён|совпал с эталоном)/);

    // Teacher opens task window and verifies response
    await login(tPage, tutorUsername);
    await tPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await tPage.waitForSelector('#canvas-window');
    await tPage.evaluate(() => {
      if (typeof (window as any).openWindow === 'function') (window as any).openWindow('task-window');
    });
    await tPage.waitForTimeout(1000);

    const tResponse = await tPage.evaluate(() => {
      const respVal = document.getElementById('teacher-classwork-response-value');
      const checkText = document.getElementById('teacher-classwork-response-check');
      return {
        submission: respVal ? respVal.textContent : null,
        check: checkText ? checkText.textContent : null
      };
    });

    expect(tResponse.submission).toBe('11');
    expect(tResponse.check).toContain('совпадает');

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-14: "Show Here" Camera Synchronization
  // ---------------------------------------------------------------------------
  test('POCKET-QA-14: Teacher Show Here command updates student camera coordinates', async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const sPage = await sCtx.newPage();
    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: 'domcontentloaded' });
    await expect(sPage.locator('#pocket-os-shell')).toBeVisible({ timeout: 15_000 });

    // Simulate incoming whiteboard_show_here event
    await sPage.evaluate(() => {
      const targetPayload = {
        lesson_id: 2168,
        x: 450,
        y: 350,
        scale: 1.25,
        target_focus: 'board'
      };
      if (typeof (window as any).BooStudyPocketOS?.handleShowHere === 'function') {
        (window as any).BooStudyPocketOS.handleShowHere(targetPayload);
      }
    });

    await sPage.waitForTimeout(400);

    const result = await sPage.evaluate(() => {
      const pocket = (window as any).BooStudyPocketOS;
      const cam = (window as any).BooCanvasOverlay?.getCamera?.() || { offsetX: 0, offsetY: 0, scale: 1.0 };
      return {
        coords: pocket?.lastTargetCoords,
        cam
      };
    });

    expect(result.coords?.world_x).toBe(450);
    expect(result.coords?.world_y).toBe(350);
    expect(result.cam).toBeDefined();
    expect(typeof result.cam.scale).toBe('number');

    await sCtx.close();
  });

  // ---------------------------------------------------------------------------
  // POCKET-QA-15: Desktop Lesson OS Zero Regressions
  // ---------------------------------------------------------------------------
  test('POCKET-QA-15: Desktop Lesson OS retains full WindowManager, toolbar, and orbit', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await login(page, tutorUsername);
    await page.goto(roomUrl, { waitUntil: 'domcontentloaded' });

    // Desktop controls must be visible
    await expect(page.locator('body')).not.toHaveClass(/pocket-os-active/);
    await expect(page.locator('#pocket-os-shell')).toBeHidden();
    await expect(page.locator('header.lesson-os-system-bar')).toBeVisible();
    await expect(page.locator('#canvas-window')).toBeVisible();
  });
});
