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

test.describe("BOOSTUDY POCKET OS — SPRINT 1.2.3 FINAL STABILIZATION", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async () => {
    test.setTimeout(120_000);
  });

  test.afterEach(async () => {
    await new Promise((r) => setTimeout(r, 1500));
  });

  // ---------------------------------------------------------------------------
  // STABILITY-01 & 02: Focus Suggestion Reliability, ACK & Bounded Controlled Mode
  // ---------------------------------------------------------------------------
  test("STABILITY-01 & 02: Focus suggestions deliver reliably with ACK, accept/dismiss work, controlled mode forces focus", async ({ browser }) => {
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

    // Ensure teacher_controls_focus is FALSE initially
    await tPage.evaluate(() => {
      const ctrl = (window as any).controlState?.() || {};
      if (ctrl.teacher_controls_focus) {
        (window as any).commitControl?.({ teacher_controls_focus: false });
      }
    });

    // Student starts on Board
    await sPage.locator("#pocket-nav-board").click();
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "board");

    // STABILITY-01: Verify 20 sequential soft focus suggestions
    // Test accept on first, dismiss on second, and verify delivery across all
    for (let i = 0; i < 20; i++) {
      const targetFocus = (i % 2 === 0) ? "code" : "task";
      // Teacher sends focus suggestion
      await tPage.evaluate((focus) => {
        (window as any).sendFocusSuggestion?.(focus);
      }, targetFocus);

      const toast = sPage.locator("#pocket-toast");
      await expect(toast).toBeVisible({ timeout: 6_000 });

      if (i === 0) {
        // Accept first suggestion -> switches focus to code
        await toast.locator("#pocket-toast-btn-action").click();
        await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "code");
        await expect(toast).not.toHaveClass(/is-visible/);
        // Switch back to board for next tests
        await sPage.locator("#pocket-nav-board").click();
        await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "board");
      } else if (i === 1) {
        // Dismiss second suggestion -> retains board focus
        await toast.locator("#pocket-toast-btn-dismiss").click();
        await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "board");
        await expect(toast).not.toHaveClass(/is-visible/);
      } else {
        // Dismiss to keep testing loop fast
        await toast.locator("#pocket-toast-btn-dismiss").click();
        await expect(toast).not.toHaveClass(/is-visible/);
      }
      await sPage.waitForTimeout(200);
    }

    // STABILITY-02: Controlled Mode (teacher_controls_focus = true)
    await tPage.evaluate(() => {
      (window as any).commitControl?.({ teacher_controls_focus: true });
    });
    await tPage.waitForTimeout(500);

    // Teacher sends set_focus to task
    await tPage.evaluate(() => {
      (window as any).sendFocusSuggestion?.("task");
    });
    // Student switches immediately without prompt dialog
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "task", { timeout: 6_000 });
    const pill = sPage.locator("#pocket-teacher-focus-pill");
    await expect(pill).toBeVisible({ timeout: 4_000 });
    await expect(pill).toContainText("управляет преподаватель");

    // Teacher turns off Controlled Mode
    await tPage.evaluate(() => {
      (window as any).commitControl?.({ teacher_controls_focus: false });
    });
    await tPage.waitForTimeout(500);

    // Now sendFocusSuggestion reverts to Suggest Mode
    await tPage.evaluate(() => {
      (window as any).sendFocusSuggestion?.("code");
    });
    const toastAfter = sPage.locator("#pocket-toast");
    await expect(toastAfter).toBeVisible({ timeout: 6_000 });
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "task"); // stayed on task until accepted

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // STABILITY-03 & 04: Mobile Window Geometry: 100 Focus Switches & Orientation
  // ---------------------------------------------------------------------------
  test("STABILITY-03 & 04: 100 focus switches maintain full width without half-screen collapse, orientation is safe", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const sPage = await sCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    const modes = ["board", "code", "task"] as const;

    // STABILITY-03: 100 rapid focus switches
    for (let i = 0; i < 100; i++) {
      const mode = modes[i % 3];
      await sPage.evaluate((targetMode) => {
        (window as any).BooStudyPocketOS?.switchFocus?.(targetMode);
      }, mode);

      if (i % 20 === 0 || i === 99) {
        // Sample geometry verification: active window must occupy exactly 390px (full viewport width)
        const winSelector = mode === "board" ? "#canvas-window" : (mode === "code" ? "#code-window" : "#task-window");
        const activeWin = sPage.locator(winSelector);
        await expect(activeWin).toBeVisible();
        const box = await activeWin.boundingBox();
        expect(box).toBeTruthy();
        expect(box!.width).toBe(390);
        expect(box!.x).toBe(0);
      }
    }

    // STABILITY-04: Orientation changes portrait -> landscape -> portrait
    await sPage.locator("#pocket-nav-code").click();
    await expect(sPage.locator("#code-window")).toBeVisible();

    // Landscape (844x390)
    await sPage.setViewportSize({ width: 844, height: 390 });
    await sPage.waitForTimeout(300);
    const codeLandscapeBox = await sPage.locator("#code-window").boundingBox();
    expect(codeLandscapeBox!.width).toBe(844);
    expect(codeLandscapeBox!.x).toBe(0);

    // Portrait (390x844)
    await sPage.setViewportSize({ width: 390, height: 844 });
    await sPage.waitForTimeout(300);
    const codePortraitBox = await sPage.locator("#code-window").boundingBox();
    expect(codePortraitBox!.width).toBe(390);
    expect(codePortraitBox!.x).toBe(0);

    await sCtx.close();
  });

  // ---------------------------------------------------------------------------
  // STABILITY-05..08: Python Editor 16px Font (No Zoom) & Virtual Symbols UX
  // ---------------------------------------------------------------------------
  test("STABILITY-05..08: Editor has 16px font preventing zoom, symbols don't trigger keyboard when closed, and sync via OT", async ({ browser }) => {
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

    // Teacher enables student code editing
    await tPage.evaluate(() => {
      (window as any).commitControl?.({ student_code_editing: true, freeze_student: false });
    });
    await tPage.waitForTimeout(500);

    // Switch student to code
    await sPage.locator("#pocket-nav-code").click();
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "code");

    // STABILITY-05: Check font metrics: 16px font-size and 24px line-height
    const textarea = sPage.locator("#code-editor-textarea");
    const highlight = sPage.locator("#code-editor-highlight");
    await expect(textarea).toBeVisible();

    const textMetrics = await textarea.evaluate((el) => {
      const s = window.getComputedStyle(el);
      return { fontSize: s.fontSize, lineHeight: s.lineHeight };
    });
    expect(textMetrics.fontSize).toBe("16px");
    expect(textMetrics.lineHeight).toBe("24px");

    const highlightMetrics = await highlight.evaluate((el) => {
      const s = window.getComputedStyle(el);
      return { fontSize: s.fontSize, lineHeight: s.lineHeight };
    });
    expect(highlightMetrics.fontSize).toBe("16px");
    expect(highlightMetrics.lineHeight).toBe("24px");

    // Clear textarea for clean test
    await textarea.fill("");

    // STABILITY-06: Tap virtual symbols when keyboard is closed
    // Ensure keyboard is closed (document.activeElement is NOT textarea)
    await sPage.locator(".pocket-code-filename").click();
    const isFocusedBefore = await sPage.evaluate(() => document.activeElement?.id === "code-editor-textarea");
    expect(isFocusedBefore).toBe(false);

    // Tap 20 virtual symbol keys
    const symbols = [":", "=", "(", ")", "[", "]", "{", "}"];
    for (let i = 0; i < 20; i++) {
      const sym = symbols[i % symbols.length];
      const keyBtn = sPage.locator(`.pocket-symbol-key[data-val="${sym}"]`);
      await keyBtn.dispatchEvent("pointerdown");
      await keyBtn.dispatchEvent("click");
    }

    // Verify keyboard remained closed
    const isKbOpenAfter = await sPage.evaluate(() => {
      return document.body.classList.contains("pocket-keyboard-open") || (document.activeElement?.id === "code-editor-textarea");
    });
    expect(isKbOpenAfter).toBe(false);

    // Verify text contains inserted characters
    const currentVal = await textarea.inputValue();
    expect(currentVal.length).toBeGreaterThanOrEqual(10);

    // STABILITY-07: Virtual symbols when keyboard IS open
    await textarea.focus();
    await sPage.waitForTimeout(100);
    const keyColon = sPage.locator('.pocket-symbol-key[data-val=":"]');
    await keyColon.dispatchEvent("pointerdown");
    await keyColon.dispatchEvent("click");
    const isStillFocused = await sPage.evaluate(() => document.activeElement?.id === "code-editor-textarea");
    expect(isStillFocused).toBe(true);

    // STABILITY-08: OT Synchronization of Virtual Symbol input to teacher
    await textarea.fill("");
    const keyOpenParen = sPage.locator('.pocket-symbol-key[data-val="("]');
    const keyCloseParen = sPage.locator('.pocket-symbol-key[data-val=")"]');
    await keyOpenParen.dispatchEvent("pointerdown");
    await keyOpenParen.dispatchEvent("click");
    await keyCloseParen.dispatchEvent("pointerdown");
    await keyCloseParen.dispatchEvent("click");

    // Verify student textarea has "()"
    await expect(textarea).toHaveValue("()", { timeout: 4_000 });

    // Verify teacher code editor synchronizes via OT
    const tutorTextarea = tPage.locator("#code-editor-textarea");
    await expect(tutorTextarea).toHaveValue("()", { timeout: 8_000 });

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // STABILITY-09..12: Shared Terminal Lifecycle & Presence Synchronization
  // ---------------------------------------------------------------------------
  test("STABILITY-09..12: Teacher Close closes student terminal drawer, student local close is private, presence stays accurate", async ({ browser }) => {
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

    // Student in Code Focus
    await sPage.locator("#pocket-nav-code").click();
    await expect(sPage.locator("body")).toHaveAttribute("data-pocket-focus", "code");

    // Teacher runs python code
    await tPage.evaluate(async () => {
      await new Promise<void>((resolve) => {
        window.addEventListener("boostudy:terminal-output", () => resolve(), { once: true });
        (window as any).executeRunCode({
          code: 'print("Shared Output Lifecycle Test 42")',
          fileName: "main.py",
          runId: "run_lifecycle_test",
          pageId: "page_1",
        });
      });
    });

    // Student terminal auto-opens with output
    const drawer = sPage.locator("#pocket-terminal-drawer");
    await expect(drawer).toBeVisible({ timeout: 8_000 });
    await expect(drawer).not.toHaveClass(/is-collapsed/);
    const consoleBody = sPage.locator("#pocket-terminal-body");
    await expect(consoleBody).toContainText("Shared Output Lifecycle Test 42");

    // Teacher sees student presence: "Код · Консоль открыта"
    const termBadge = tPage.locator('.board-student-viewport-status-tag[data-terminal-status="open"]');
    await expect(termBadge).toBeVisible({ timeout: 6_000 });
    await expect(termBadge).toContainText("Код · Консоль открыта");

    // STABILITY-09: Teacher closes desktop terminal
    await tPage.evaluate(() => {
      (window as any).closeWindow?.("terminal-window");
    });

    // Student terminal drawer collapses automatically
    await expect(drawer).toHaveClass(/is-collapsed/, { timeout: 8_000 });

    // Output is preserved inside drawer
    await expect(consoleBody).toContainText("Shared Output Lifecycle Test 42");

    // STABILITY-11: Teacher presence updates to "Код · Консоль закрыта"
    const closedBadge = tPage.locator('.board-student-viewport-status-tag[data-terminal-status="closed"]');
    await expect(closedBadge).toBeVisible({ timeout: 6_000 });
    await expect(closedBadge).toContainText("Код · Консоль закрыта");

    // Student re-opens drawer locally
    await sPage.locator("#pocket-btn-console-toggle").click();
    await expect(drawer).not.toHaveClass(/is-collapsed/);
    await expect(termBadge).toBeVisible({ timeout: 6_000 });

    // STABILITY-10: Student Local Close does NOT close Teacher terminal
    // Teacher re-opens desktop terminal
    await tPage.evaluate(() => {
      (window as any).openWindow?.("terminal-window");
    });
    await expect(tPage.locator("#terminal-window")).toBeVisible();

    // Student closes drawer locally
    await sPage.locator("#pocket-terminal-close-btn").click();
    await expect(drawer).toHaveClass(/is-collapsed/);

    // Teacher terminal must remain open
    await expect(tPage.locator("#terminal-window")).toBeVisible();

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // STABILITY-13 & 14: Zero Regression on Mobile Board/Tasks & Desktop Lesson OS
  // ---------------------------------------------------------------------------
  test("STABILITY-13 & 14: Board, Tasks and Desktop Lesson OS maintain zero regression", async ({ browser }) => {
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

    // STABILITY-13: Mobile Board & Task focus
    await sPage.locator("#pocket-nav-board").click();
    await expect(sPage.locator("#canvas-window")).toBeVisible();
    await expect(sPage.locator("#pocket-read-only-pill")).toBeVisible();

    await sPage.locator("#pocket-nav-task").click();
    await expect(sPage.locator("#task-window")).toBeVisible();

    // STABILITY-14: Desktop Lesson OS operates normally
    await expect(tPage.locator("#canvas-window")).toBeVisible();
    const codeWin = tPage.locator("#code-window");
    await tPage.evaluate(() => {
      (window as any).openWindow?.("code-window");
    });
    await expect(codeWin).toBeVisible();

    await sCtx.close();
    await tCtx.close();
  });
});
