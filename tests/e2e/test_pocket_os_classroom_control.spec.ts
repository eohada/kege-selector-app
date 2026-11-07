import { expect, Page, test } from "@playwright/test";

const password = process.env.BOOSTUDY_E2E_PASSWORD || "123456";
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || "qa_pool_tutor_1";
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || "qa_pool_student_1";
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || "/lesson/2168/room";

async function login(page: Page, username: string) {
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    const usernameInput = page.locator('input[name="username"]');
    await expect(usernameInput).toBeVisible({ timeout: 10_000 });
    await usernameInput.fill(username);
    await page.locator('input[name="password"]').fill(password);
    await page.locator('button[type="submit"]').click();
    try {
      await expect(page).not.toHaveURL(/\/login/, { timeout: 8_000 });
      return;
    } catch (e) {
      if (attempt === 2) throw e;
      await page.waitForTimeout(1200);
    }
  }
}

test.describe("BOOSTUDY POCKET OS — SPRINT 1.2.2 CLASSROOM CONTROL & RUNTIME RECOVERY", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async () => {
    test.setTimeout(90_000);
  });

  test.afterEach(async () => {
    await new Promise((r) => setTimeout(r, 1500));
  });

  // ---------------------------------------------------------------------------
  // CLASSROOM-01..04: Mobile Student Python Run Button Accessibility & Execution
  // ---------------------------------------------------------------------------
  test("CLASSROOM-01..04: Student Run button is visible, >=44x38px, accessible on 360px, and triggers execution", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const sPage = await sCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    // Switch to Code Focus
    await sPage.locator("#pocket-nav-code").click();
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "code");

    // CLASSROOM-01: Run button must be visible, min 44x38
    const runBtn = sPage.locator("#pocket-btn-run");
    await expect(runBtn).toBeVisible({ timeout: 5_000 });
    const box = await runBtn.boundingBox();
    expect(box).toBeTruthy();
    expect(box!.width).toBeGreaterThanOrEqual(44);
    expect(box!.height).toBeGreaterThanOrEqual(38);

    // CLASSROOM-02: Check on narrow 360px viewport (Galaxy S / iPhone SE width)
    await sPage.setViewportSize({ width: 360, height: 740 });
    await sPage.waitForTimeout(300);
    await expect(runBtn).toBeVisible();
    await expect(runBtn).toBeInViewport();
    const boxNarrow = await runBtn.boundingBox();
    expect(boxNarrow).toBeTruthy();
    expect(boxNarrow!.width).toBeGreaterThanOrEqual(44);
    expect(boxNarrow!.height).toBeGreaterThanOrEqual(38);

    // CLASSROOM-03 & 04: Student triggers execution and sees terminal drawer output
    await sPage.evaluate(() => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      if (ta) {
        ta.value = 'print("Pocket OS Student Run Test")';
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });

    await runBtn.click();
    const drawer = sPage.locator("#pocket-terminal-drawer");
    await expect(drawer).toBeVisible({ timeout: 5_000 });
    await expect(drawer).not.toHaveClass(/is-collapsed/);

    const pocketConsole = sPage.locator("#pocket-terminal-body");
    await expect(pocketConsole).toContainText("Код выхода: 0", { timeout: 8_000 });

    await sCtx.close();
  });

  // ---------------------------------------------------------------------------
  // CLASSROOM-08..11: Presence Reporting (Terminal Open/Closed, Board, Task)
  // ---------------------------------------------------------------------------
  test("CLASSROOM-08..11: Student terminal open/closed and focus states reflect in teacher viewport badge", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const tCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

    const sPage = await sCtx.newPage();
    const tPage = await tCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    await login(tPage, tutorUsername);
    await tPage.goto(roomUrl, { waitUntil: "domcontentloaded" });
    await expect(tPage.locator("#canvas-window")).toBeVisible({ timeout: 15_000 });

    // Step 1: Student switches to Code focus (terminal closed initially)
    await sPage.locator("#pocket-nav-code").click();
    await sPage.waitForTimeout(1000);

    const teacherStatusTag = tPage.locator(".board-student-viewport-status-tag");
    await expect(teacherStatusTag).toBeVisible({ timeout: 8_000 });
    await expect(teacherStatusTag).toContainText("Код · Консоль закрыта");

    // Step 2: Student opens terminal drawer (CLASSROOM-08 & CLASSROOM-10)
    await sPage.locator("#pocket-btn-console-toggle").click();
    await expect(sPage.locator("#pocket-terminal-drawer")).not.toHaveClass(/is-collapsed/);
    await sPage.waitForTimeout(800);

    await expect(teacherStatusTag).toContainText("Код · Консоль открыта", { timeout: 8_000 });

    // Step 3: Student closes terminal drawer (CLASSROOM-09 & CLASSROOM-10)
    await sPage.locator("#pocket-terminal-close-btn").click();
    await expect(sPage.locator("#pocket-terminal-drawer")).toHaveClass(/is-collapsed/);
    await sPage.waitForTimeout(800);

    await expect(teacherStatusTag).toContainText("Код · Консоль закрыта", { timeout: 8_000 });

    // Step 4: Student switches to Task focus (CLASSROOM-11)
    await sPage.locator("#pocket-nav-task").click();
    await sPage.waitForTimeout(800);
    await expect(teacherStatusTag).toContainText("В задании", { timeout: 8_000 });

    // Step 5: Student switches to Board focus (CLASSROOM-11)
    await sPage.locator("#pocket-nav-board").click();
    await sPage.waitForTimeout(800);
    await expect(teacherStatusTag).toContainText("На доске", { timeout: 8_000 });

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // CLASSROOM-05..07: Shared Python Runtime (Teacher Execution Broadcast)
  // ---------------------------------------------------------------------------
  test("CLASSROOM-05..07: Teacher executes Python code; student terminal receives shared output and notification", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const tCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

    const sPage = await sCtx.newPage();
    const tPage = await tCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    await login(tPage, tutorUsername);
    await tPage.goto(roomUrl, { waitUntil: "domcontentloaded" });
    await expect(tPage.locator("#canvas-window")).toBeVisible({ timeout: 15_000 });

    // Part A: Student is in Code Focus (CLASSROOM-05 & 07)
    await sPage.locator("#pocket-nav-code").click();
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "code");

    // Teacher runs code in Code window
    await tPage.evaluate(() => {
      const runFn = (window as any).executeRunCode;
      if (typeof runFn === "function") {
        runFn({
          code: 'print("Shared Execution Result From Teacher 99")',
          fileName: "main.py",
          runId: "run_teacher_test_1",
          pageId: "page_1",
        });
      }
    });

    // Student terminal drawer should auto-open and contain teacher's output
    const drawer = sPage.locator("#pocket-terminal-drawer");
    await expect(drawer).toBeVisible({ timeout: 8_000 });
    await expect(drawer).not.toHaveClass(/is-collapsed/);

    const pocketConsole = sPage.locator("#pocket-terminal-body");
    await expect(pocketConsole).toContainText("Shared Execution Result From Teacher 99", { timeout: 8_000 });
    await expect(pocketConsole).toContainText("main.py");
    await expect(pocketConsole).toContainText("Код: 0");

    // Part B: Student is in Board Focus (CLASSROOM-06)
    await sPage.locator("#pocket-nav-board").click();
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "board");

    // Teacher runs another program
    await tPage.evaluate(() => {
      const runFn = (window as any).executeRunCode;
      if (typeof runFn === "function") {
        runFn({
          code: 'print("Background Teacher Output 101")',
          fileName: "main.py",
          runId: "run_teacher_test_2",
          pageId: "page_1",
        });
      }
    });

    // Student must remain on Board, and receive an unobtrusive toast notification
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "board");
    const toast = sPage.locator("#pocket-toast");
    await expect(toast).toBeVisible({ timeout: 8_000 });
    await expect(toast).toContainText("Результат запуска: main.py");

    // Clicking "В консоль" switches student to Code focus and opens drawer
    await toast.locator("button:has-text('В консоль')").click();
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "code");
    await expect(sPage.locator("#pocket-terminal-body")).toContainText("Background Teacher Output 101");

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // CLASSROOM-12..14: Classroom Control & Forced Focus Switching
  // ---------------------------------------------------------------------------
  test("CLASSROOM-12..14: Teacher enables classroom control and forcibly switches student focus without data loss", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const tCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

    const sPage = await sCtx.newPage();
    const tPage = await tCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    await login(tPage, tutorUsername);
    await tPage.goto(roomUrl, { waitUntil: "domcontentloaded" });
    await expect(tPage.locator("#canvas-window")).toBeVisible({ timeout: 15_000 });

    // Step 1: Teacher enables "Управлять экраном ученика" and code edit permissions (CLASSROOM-12)
    await tPage.locator("#lesson-os-control-toggle").click();
    const teacherFocusToggle = tPage.locator("#control-teacher-controls-focus");
    await expect(teacherFocusToggle).toBeVisible({ timeout: 5_000 });
    if (!(await teacherFocusToggle.isChecked())) {
      await teacherFocusToggle.click();
    }
    await expect(teacherFocusToggle).toBeChecked();

    const codeEditToggle = tPage.locator("#control-student-code-edit");
    if (!(await codeEditToggle.isChecked())) {
      await codeEditToggle.click();
    }
    await expect(codeEditToggle).toBeChecked();
    await tPage.locator("#lesson-os-control-toggle").click(); // close drawer
    await tPage.waitForTimeout(600);

    // Step 2: Student switches to Code Focus and enters draft code (CLASSROOM-14)
    await sPage.locator("#pocket-nav-code").click();
    const textarea = sPage.locator("#code-editor-textarea");
    await textarea.fill("# Student Important Draft Data 777");

    // Step 3: Teacher forcibly switches student to Task Focus (CLASSROOM-13)
    await tPage.evaluate(() => {
      (window as any).sendFocusSuggestion?.("task");
    });

    // Student must immediately switch to Task Focus without any prompt dialog
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "task", { timeout: 8_000 });
    const focusPill = sPage.locator("#pocket-teacher-focus-pill");
    await expect(focusPill).toBeVisible({ timeout: 5_000 });
    await expect(focusPill).toContainText("управляет преподаватель");

    // Step 4: Teacher forcibly switches student back to Code Focus
    await tPage.evaluate(() => {
      (window as any).sendFocusSuggestion?.("code");
    });
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "code", { timeout: 8_000 });

    // Draft code must be 100% preserved (CLASSROOM-14)
    await expect(textarea).toHaveValue("# Student Important Draft Data 777");

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // CLASSROOM-15: Window Immutability (No Drag / No Resize on Mobile)
  // ---------------------------------------------------------------------------
  test("CLASSROOM-15: Mobile windows cannot be dragged or resized, preserving immutable pocket focus layout", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const sPage = await sCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    // Switch to Code Focus
    await sPage.locator("#pocket-nav-code").click();
    const codeWin = sPage.locator("#code-window");
    await expect(codeWin).toBeVisible();

    // Check resizers are hidden and pointer-events disabled
    const resizerCount = await sPage.evaluate(() => {
      const resizers = document.querySelectorAll(".window-edge-resizer, .window-resize-handle");
      let visibleCount = 0;
      resizers.forEach((r) => {
        const style = window.getComputedStyle(r);
        if (style.display !== "none" && style.pointerEvents !== "none") {
          visibleCount++;
        }
      });
      return visibleCount;
    });
    expect(resizerCount).toBe(0);

    // Attempt to drag header: window top/left must remain unaffected
    const initialBounds = await codeWin.boundingBox();
    expect(initialBounds).toBeTruthy();

    const header = sPage.locator("#code-window .window-header");
    if (await header.count() > 0) {
      const hBox = await header.boundingBox();
      if (hBox) {
        await sPage.mouse.move(hBox.x + 20, hBox.y + 10);
        await sPage.mouse.down();
        await sPage.mouse.move(hBox.x + 100, hBox.y + 100, { steps: 5 });
        await sPage.mouse.up();
      }
    }

    const postBounds = await codeWin.boundingBox();
    expect(postBounds!.x).toBe(initialBounds!.x);
    expect(postBounds!.y).toBe(initialBounds!.y);

    await sCtx.close();
  });
});
