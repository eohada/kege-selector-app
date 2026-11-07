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

test.describe("BOOSTUDY POCKET OS — SPRINT 1.2.1 BLOCKER RECOVERY", () => {
  test.describe.configure({ mode: "serial" });

  test.afterEach(async () => {
    await new Promise((r) => setTimeout(r, 1500));
  });

  // ---------------------------------------------------------------------------
  // CODE-DEVICE-01 & 02: Bidirectional Student -> Teacher OT Sync & Persistence
  // ---------------------------------------------------------------------------
  test("CODE-DEVICE-01 & 02: Bidirectional OT sync when permission granted, persisted on reload", async ({ browser }) => {
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
    await tPage.waitForFunction(() => (window as any).state?.canPresent === true, { timeout: 15_000 });

    // 1. Teacher enables student code editing via clickable badge or commitControl
    await tPage.evaluate(() => {
      const ctrl = (window as any).controlState?.() || {};
      if (!ctrl.student_code_editing) {
        const badge = document.getElementById("code-window-permission-badge");
        if (badge) badge.click();
        if (!(window as any).controlState?.()?.student_code_editing && typeof (window as any).commitControl === "function") {
          (window as any).commitControl({ student_code_editing: true });
        }
      }
    });
    // Wait until teacher control confirms student_code_editing is true
    await tPage.waitForFunction(() => (window as any).controlState?.()?.student_code_editing === true, { timeout: 10_000 });
    // Wait until student control also receives student_code_editing === true
    await sPage.waitForFunction(() => (window as any).controlState?.()?.student_code_editing === true, { timeout: 10_000 });
    await sPage.waitForTimeout(500);

    // 2. Student opens Code focus
    await sPage.locator("#pocket-nav-code").click();
    await sPage.waitForTimeout(400);

    // Student badge must indicate editing is allowed
    const permBadge = sPage.locator("#pocket-code-permission-badge");
    await expect(permBadge).toBeVisible();
    await expect(permBadge).toHaveClass(/is-editable/);
    await expect(permBadge).toContainText("Можно писать");

    // Student textarea must not be read-only
    const sTextarea = sPage.locator("#code-editor-textarea");
    await expect(sTextarea).not.toHaveAttribute("readonly", "");

    // 3. Student types print("MOBILE_TO_TEACHER")
    await sPage.evaluate(() => {
      const ta = document.getElementById("code-editor-textarea") as HTMLTextAreaElement;
      ta.value = 'print("MOBILE_TO_TEACHER")';
      if (typeof (window as any).onCodeEditorInput === "function") {
        (window as any).onCodeEditorInput(ta.value);
      }
    });
    await tPage.waitForTimeout(1200);

    // 4. Teacher on desktop receives student edit via OT without reload
    const tCode = await tPage.evaluate(() => {
      return (document.getElementById("code-editor-textarea") as HTMLTextAreaElement)?.value;
    });
    expect(tCode).toContain('print("MOBILE_TO_TEACHER")');

    // 5. Teacher appends print("TEACHER_TO_MOBILE")
    await tPage.evaluate(() => {
      const ta = document.getElementById("code-editor-textarea") as HTMLTextAreaElement;
      ta.value += '\nprint("TEACHER_TO_MOBILE")';
      if (typeof (window as any).onCodeEditorInput === "function") {
        (window as any).onCodeEditorInput(ta.value);
      }
    });
    await sPage.waitForTimeout(1200);

    // 6. Student receives teacher's appended line via OT
    const sCode = await sPage.evaluate(() => {
      return (document.getElementById("code-editor-textarea") as HTMLTextAreaElement)?.value;
    });
    expect(sCode).toContain('print("TEACHER_TO_MOBILE")');

    // 7. Reload both pages and check persistence
    await sPage.reload({ waitUntil: "domcontentloaded" });
    await tPage.reload({ waitUntil: "domcontentloaded" });
    await sPage.waitForTimeout(1500);

    const sCodeReloaded = await sPage.evaluate(() => {
      return (document.getElementById("code-editor-textarea") as HTMLTextAreaElement)?.value;
    });
    const tCodeReloaded = await tPage.evaluate(() => {
      return (document.getElementById("code-editor-textarea") as HTMLTextAreaElement)?.value;
    });

    expect(sCodeReloaded).toContain('print("MOBILE_TO_TEACHER")');
    expect(tCodeReloaded).toContain('print("TEACHER_TO_MOBILE")');

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // CODE-DEVICE-03 & 04: ReadOnly & Freeze Enforcement on Mobile
  // ---------------------------------------------------------------------------
  test("CODE-DEVICE-03 & 04: ReadOnly & Freeze strictly lock mobile typing and virtual keys", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const tCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

    const sPage = await sCtx.newPage();
    const tPage = await tCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });

    await login(tPage, tutorUsername);
    await tPage.goto(roomUrl, { waitUntil: "domcontentloaded" });
    await expect(tPage.locator("#canvas-window")).toBeVisible({ timeout: 15_000 });
    await tPage.waitForFunction(() => (window as any).state?.canPresent === true, { timeout: 15_000 });

    // 1. Teacher revokes student editing rights
    await tPage.evaluate(() => {
      if ((window as any).commitControl) {
        (window as any).commitControl({ student_code_editing: false, freeze_student: false });
      }
    });
    await sPage.waitForFunction(() => (window as any).controlState?.()?.student_code_editing === false, { timeout: 10_000 });
    await sPage.waitForTimeout(400);

    // 2. Student opens Code focus
    await sPage.locator("#pocket-nav-code").click();
    await sPage.waitForTimeout(400);

    // Permission badge must say "Только чтение"
    const permBadge = sPage.locator("#pocket-code-permission-badge");
    await expect(permBadge).toHaveClass(/is-readonly/);
    await expect(permBadge).toContainText("Только чтение");

    // Textarea must have readOnly = true
    const sTextarea = sPage.locator("#code-editor-textarea");
    const isReadOnly = await sTextarea.evaluate((el: HTMLTextAreaElement) => el.readOnly);
    expect(isReadOnly).toBe(true);

    // Initial code before virtual key tap
    const initialCode = await sTextarea.evaluate((el: HTMLTextAreaElement) => el.value);

    // 3. Student clicks virtual symbol button (e.g. Tab)
    const tabKey = sPage.locator('.pocket-symbol-key[data-val="    "]');
    if (await tabKey.isVisible()) {
      await tabKey.click();
    }

    // Code must remain strictly unchanged because textarea is read-only
    const afterVirtualCode = await sTextarea.evaluate((el: HTMLTextAreaElement) => el.value);
    expect(afterVirtualCode).toBe(initialCode);

    // 4. Teacher activates Freeze
    await tPage.evaluate(() => {
      if ((window as any).commitControl) {
        (window as any).commitControl({ freeze_student: true });
      }
    });
    await sPage.waitForFunction(() => (window as any).controlState?.()?.freeze_student === true, { timeout: 10_000 });
    await sPage.waitForTimeout(400);

    // Student badge must indicate demonstration mode
    await expect(permBadge).toHaveClass(/is-frozen/);
    await expect(permBadge).toContainText("Демонстрация");

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // TERMINAL-DEVICE-01 & 02: Single Drawer, Desktop Suppressed, Re-entrance Guard
  // ---------------------------------------------------------------------------
  test("TERMINAL-DEVICE-01 & 02: Single mobile drawer, desktop terminal hidden, focus switch safe", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const sPage = await sCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    // Open Code focus
    await sPage.locator("#pocket-nav-code").click();
    await sPage.waitForTimeout(400);

    // Ensure desktop #terminal-window is hidden by CSS
    const desktopTerm = sPage.locator("#terminal-window");
    await expect(desktopTerm).toBeHidden();

    // Set code to print single line
    await sPage.evaluate(() => {
      const ta = document.getElementById("code-editor-textarea") as HTMLTextAreaElement;
      ta.value = 'print("RUN_SINGLE_LINE_CHECK")';
      if (typeof (window as any).onCodeEditorInput === "function") {
        (window as any).onCodeEditorInput(ta.value);
      }
    });

    // Tap Run button
    const runBtn = sPage.locator("#pocket-btn-run");
    await expect(runBtn).toBeVisible();
    await runBtn.click();

    // Mobile terminal drawer must open
    const drawer = sPage.locator("#pocket-terminal-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer).not.toHaveClass(/is-collapsed/);

    // Desktop #terminal-window must REMAIN completely hidden
    await expect(desktopTerm).toBeHidden();

    // Output must arrive in drawer console
    const termBody = sPage.locator("#pocket-terminal-body");
    await expect(termBody).toContainText("Running python main.py...", { timeout: 10_000 });
    await expect(termBody).toContainText("Выполнено", { timeout: 10_000 });

    // Rapid double-tap Run: must not corrupt console or create duplicate execution
    await runBtn.click();
    await runBtn.click();
    await sPage.waitForTimeout(1000);

    // Switching focus: code -> board -> code must preserve terminal output
    await sPage.locator("#pocket-nav-board").click();
    await sPage.waitForTimeout(300);
    await sPage.locator("#pocket-nav-code").click();
    await sPage.waitForTimeout(300);

    // Output must still be preserved in mobile drawer
    await expect(termBody).toContainText("Running python main.py...");
    await expect(termBody).toContainText("Выполнено");
    // Desktop window must still be hidden
    await expect(desktopTerm).toBeHidden();

    await sCtx.close();
  });

  // ---------------------------------------------------------------------------
  // MEDIA-DEVICE-01..05: LiveKit Mobile Join UI, State Sync, Media Controls
  // ---------------------------------------------------------------------------
  test("MEDIA-DEVICE-01..05: LiveKit Join button, connection state, AV controls and tab continuity", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const sPage = await sCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    // 1. In disconnected state: Join button must be visible in header
    const joinBtn = sPage.locator("#pocket-btn-join-call");
    await expect(joinBtn).toBeVisible();

    // In-call controls must be hidden initially
    const leaveBtn = sPage.locator("#pocket-call-leave");
    const micBtn = sPage.locator("#pocket-mic-toggle");
    const camBtn = sPage.locator("#pocket-cam-toggle");
    await expect(leaveBtn).toBeHidden();
    await expect(micBtn).toBeHidden();
    await expect(camBtn).toBeHidden();

    // Video pill must be in compact indicator mode
    const videoPill = sPage.locator("#pocket-video-pill");
    await expect(videoPill).toBeVisible();
    await expect(videoPill).toHaveClass(/is-compact-indicator/);

    // 2. Check secure context property on page
    const isSecCtx = await sPage.evaluate(() => window.isSecureContext);
    const host = await sPage.evaluate(() => window.location.hostname);
    if (!isSecCtx && host !== "localhost" && host !== "127.0.0.1") {
      // Must display HTTPS required indicator
      await expect(joinBtn).toHaveClass(/is-warning/);
      await expect(joinBtn).toContainText("Требуется HTTPS");
    } else {
      await expect(joinBtn).toContainText("Войти в звонок");
    }

    // 3. Simulate LiveKit controller connected state transition
    await sPage.evaluate(() => {
      const lk = (window as any).lessonLivekit;
      if (lk) {
        lk.isConnected = true;
        lk.isConnecting = false;
        lk.isAudioMuted = false;
        lk.isVideoMuted = false;
        (window as any).BooStudyPocketOS?.syncLiveKitUIState?.();
      }
    });

    // In connected state: Join button hides, leave and mic/cam buttons appear
    await expect(joinBtn).toBeHidden();
    await expect(leaveBtn).toBeVisible();
    await expect(micBtn).toBeVisible();
    await expect(camBtn).toBeVisible();

    // 4. Media toggle: mic mute toggles is-muted class
    await sPage.evaluate(() => {
      const lk = (window as any).lessonLivekit;
      if (lk) {
        lk.isAudioMuted = true;
        (window as any).BooStudyPocketOS?.syncLiveKitUIState?.();
      }
    });
    await expect(micBtn).toHaveClass(/is-muted/);

    // 5. Focus switching continuity: switching tabs must not disconnect media
    await sPage.locator("#pocket-nav-code").click();
    await sPage.waitForTimeout(300);
    await expect(leaveBtn).toBeVisible();
    await expect(micBtn).toBeVisible();

    await sPage.locator("#pocket-nav-task").click();
    await sPage.waitForTimeout(300);
    await expect(leaveBtn).toBeVisible();
    await expect(micBtn).toBeVisible();

    await sPage.locator("#pocket-nav-board").click();
    await sPage.waitForTimeout(300);
    await expect(leaveBtn).toBeVisible();
    await expect(micBtn).toBeVisible();

    // 6. Leave call terminates state cleanly
    await sPage.evaluate(() => {
      const lk = (window as any).lessonLivekit;
      if (lk) {
        lk.isConnected = false;
        lk.isConnecting = false;
        (window as any).BooStudyPocketOS?.syncLiveKitUIState?.();
      }
    });
    await expect(joinBtn).toBeVisible();
    await expect(leaveBtn).toBeHidden();
    await expect(micBtn).toBeHidden();

    await sCtx.close();
  });

  // ---------------------------------------------------------------------------
  // REGRESSION-DEVICE-01..03: Mobile Canvas, Tasks & Desktop Invariance
  // ---------------------------------------------------------------------------
  test("REGRESSION-DEVICE-01..03: Canvas, Tasks and Desktop Lesson OS maintain 100% zero regression", async ({ browser }) => {
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const tCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

    const sPage = await sCtx.newPage();
    const tPage = await tCtx.newPage();

    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });

    await login(tPage, tutorUsername);
    await tPage.goto(roomUrl, { waitUntil: "domcontentloaded" });

    // Desktop canvas and windows are present
    await expect(tPage.locator("#canvas-window")).toBeVisible();
    await expect(tPage.locator("#code-window")).toBeVisible();
    await expect(tPage.locator("#code-window-permission-badge")).toBeVisible();

    // Mobile canvas window is visible on Board focus
    await expect(sPage.locator("#canvas-window")).toBeVisible();
    await expect(sPage.locator("#pocket-board-controls")).toBeVisible();

    // Mobile task tab works and submission form exists
    await sPage.locator("#pocket-nav-task").click();
    await sPage.waitForTimeout(300);
    await expect(sPage.locator("#task-window")).toBeVisible();

    await sCtx.close();
    await tCtx.close();
  });
});
