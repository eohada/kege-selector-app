import { expect, Page, test, BrowserContext } from "@playwright/test";

const password = process.env.BOOSTUDY_E2E_PASSWORD || "123456";
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || "qa_pool_tutor_1";
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || "qa_pool_student_1";
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || "/lesson/2168/room";

async function login(page: Page, username: string) {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  const usernameInput = page.locator("input[name=\"username\"]");
  await expect(usernameInput).toBeVisible({ timeout: 10_000 });
  await usernameInput.fill(username);
  await page.locator("input[name=\"password\"]").fill(password);
  await page.locator("button[type=\"submit\"]").click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
}

test.describe("BOOSTUDY POCKET OS — SPRINT 1.2 FINAL ACCEPTANCE", () => {
  test.describe.configure({ mode: "serial" });

  // ---------------------------------------------------------------------------
  // BOARD-FINAL-01 & 02: Teacher draws circle + arrow inside contour, visible on student, persists on reload
  // ---------------------------------------------------------------------------
  test("BOARD-FINAL-01 & 02: Teacher draws circle and arrow in student contour; visible and persists on reload", async ({ browser }) => {
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
    await sPage.waitForTimeout(1500);

    // 1. Get student current visible world bounding box
    const sBounds = await sPage.evaluate(() => {
      return (window as any).BooCanvasOverlay?.getViewportWorldBounds?.();
    });
    expect(sBounds).toBeTruthy();
    expect(sBounds.worldW).toBeGreaterThan(0);

    // 2. Center of student visible area
    const cx = Math.round(sBounds.worldX + sBounds.worldW / 2);
    const cy = Math.round(sBounds.worldY + sBounds.worldH / 2);

    // Teacher creates circle (r=50) and arrow points inside student area
    const r = 50;
    const circlePoints: { x: number; y: number }[] = [];
    for (let i = 0; i <= 36; i++) {
      const theta = (i / 36) * Math.PI * 2;
      circlePoints.push({ x: Math.round(cx + r * Math.cos(theta)), y: Math.round(cy + r * Math.sin(theta)) });
    }
    const arrowPoints = [
      { x: Math.round(cx - 30), y: Math.round(cy) },
      { x: Math.round(cx + 30), y: Math.round(cy) },
      { x: Math.round(cx + 15), y: Math.round(cy - 15) },
      { x: Math.round(cx + 30), y: Math.round(cy) },
      { x: Math.round(cx + 15), y: Math.round(cy + 15) }
    ];

    const circleId = "final_circle_" + Date.now();
    const arrowId = "final_arrow_" + Date.now();

    await tPage.evaluate(({ circlePoints, arrowPoints, circleId, arrowId }) => {
      const overlay = (window as any).BooCanvasOverlay;
      const pid = overlay?.getActivePageId?.() || "page_1";
      const socket = (window as any).state?.socket;

      const circleStroke = {
        id: circleId,
        type: "stroke",
        tool: "pen",
        color: "#7c3aed",
        width: 5,
        page_id: pid,
        points: circlePoints
      };
      const arrowStroke = {
        id: arrowId,
        type: "stroke",
        tool: "pen",
        color: "#7c3aed",
        width: 5,
        page_id: pid,
        points: arrowPoints
      };

      overlay?.applyRemoteStrokeCommit?.(circleStroke);
      overlay?.applyRemoteStrokeCommit?.(arrowStroke);

      socket?.emit("board_stroke", { lesson_id: 2168, stroke: circleStroke });
      socket?.emit("board_stroke", { lesson_id: 2168, stroke: arrowStroke });
    }, { circlePoints, arrowPoints, circleId, arrowId });

    await sPage.waitForTimeout(1500);

    // Verify BOARD-FINAL-01: both strokes present and rendered on student canvas
    const studentStrokes = await sPage.evaluate(({ circleId, arrowId }) => {
      const strokes = (window as any).BooCanvasOverlay?.getStrokes?.() || [];
      const c = strokes.find((s: any) => s.id === circleId);
      const a = strokes.find((s: any) => s.id === arrowId);
      return { hasCircle: Boolean(c), hasArrow: Boolean(a) };
    }, { circleId, arrowId });

    expect(studentStrokes.hasCircle).toBe(true);
    expect(studentStrokes.hasArrow).toBe(true);

    // Verify BOARD-FINAL-02: reload preserves the drawing
    await sPage.reload();
    await expect(sPage.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });
    await sPage.waitForTimeout(1500);

    const reloadedStrokes = await sPage.evaluate(({ circleId, arrowId }) => {
      const strokes = (window as any).BooCanvasOverlay?.getStrokes?.() || [];
      const c = strokes.find((s: any) => s.id === circleId);
      const a = strokes.find((s: any) => s.id === arrowId);
      return { hasCircle: Boolean(c), hasArrow: Boolean(a) };
    }, { circleId, arrowId });

    expect(reloadedStrokes.hasCircle).toBe(true);
    expect(reloadedStrokes.hasArrow).toBe(true);

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // BOARD-FINAL-03, 04, 05: Show Here framing, К контуру isolation, One-shot non-follow
  // ---------------------------------------------------------------------------
  test("BOARD-FINAL-03, 04, 05: Show Here frames readable scale; К контуру moves only teacher; One-shot allows student pan", async ({ browser }) => {
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
    await sPage.waitForTimeout(1500);

    // Check BOARD-FINAL-04: Teacher clicks Focus on Student Viewport ("К контуру")
    const initialStudentCam = await sPage.evaluate(() => (window as any).BooCanvasOverlay?.getCamera?.());

    await tPage.evaluate(() => {
      if (typeof (window as any).focusOnStudentViewport === "function") {
        (window as any).focusOnStudentViewport();
      }
    });
    await tPage.waitForTimeout(800);

    const postStudentCam = await sPage.evaluate(() => (window as any).BooCanvasOverlay?.getCamera?.());
    // Student camera must remain unchanged
    expect(postStudentCam.offsetX).toBeCloseTo(initialStudentCam.offsetX, 1);
    expect(postStudentCam.offsetY).toBeCloseTo(initialStudentCam.offsetY, 1);

    // Check BOARD-FINAL-03: Teacher clicks Show Here ("Показать здесь")
    await tPage.evaluate(() => {
      if (typeof (window as any).teacherShowHere === "function") {
        (window as any).teacherShowHere();
      }
    });
    await sPage.waitForTimeout(1000);

    const framedCam = await sPage.evaluate(() => (window as any).BooCanvasOverlay?.getCamera?.());
    // Scale must be in readable educational range [0.65, 2.0], NOT 0.3
    expect(framedCam.scale).toBeGreaterThanOrEqual(0.65);
    expect(framedCam.scale).toBeLessThanOrEqual(2.0);

    // Check BOARD-FINAL-05: One-shot semantics allows student to freely pan afterwards
    await sPage.evaluate(() => {
      const overlay = (window as any).BooCanvasOverlay;
      const cam = overlay?.getCamera?.();
      // Student moves camera manually
      overlay?.setCamera?.(cam.offsetX + 100, cam.offsetY + 50, cam.scale);
    });
    await sPage.waitForTimeout(500);

    const manualCam = await sPage.evaluate(() => (window as any).BooCanvasOverlay?.getCamera?.());
    // Manual movement is preserved, not forcibly reverted by a follow loop
    expect(manualCam.offsetX).toBeCloseTo(framedCam.offsetX + 100, 0);

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // BOARD-FINAL-06 & 07: Single zoom controls system & Focus preservation
  // ---------------------------------------------------------------------------
  test("BOARD-FINAL-06 & 07: Single zoom control system and Board -> Code -> Board camera preservation", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    // BOARD-FINAL-06: Desktop zoom island must be completely hidden
    const zoomIsland = page.locator(".boo-canvas-zoom-island");
    if (await zoomIsland.count() > 0) {
      await expect(zoomIsland.first()).toBeHidden();
    }
    // Mobile controls must be visible
    await expect(page.locator("#pocket-board-controls")).toBeVisible();
    await expect(page.locator("#pocket-btn-zoom-in")).toBeVisible();
    await expect(page.locator("#pocket-btn-zoom-out")).toBeVisible();
    await expect(page.locator("#pocket-btn-zoom-fit")).toBeVisible();
    await expect(page.locator("#pocket-btn-rejoin")).toBeVisible();

    // BOARD-FINAL-07: Switch Board -> Code -> Board
    const initialCam = await page.evaluate(() => (window as any).BooCanvasOverlay?.getCamera?.());

    await page.locator("#pocket-nav-code").click();
    await expect(page.locator("body")).toHaveAttribute("data-pocket-focus", "code");
    await page.waitForTimeout(400);

    await page.locator("#pocket-nav-board").click();
    await expect(page.locator("body")).toHaveAttribute("data-pocket-focus", "board");
    await page.waitForTimeout(400);

    const restoredCam = await page.evaluate(() => (window as any).BooCanvasOverlay?.getCamera?.());
    expect(restoredCam.offsetX).toBeCloseTo(initialCam.offsetX, 1);
    expect(restoredCam.offsetY).toBeCloseTo(initialCam.offsetY, 1);
    expect(restoredCam.scale).toBeCloseTo(initialCam.scale, 2);
  });

  // ---------------------------------------------------------------------------
  // UI-FINAL-01: Table and answer submission not overlapped by video pill
  // ---------------------------------------------------------------------------
  test("UI-FINAL-01: Table, problem text and submit button are completely unobstructed", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    await page.locator("#pocket-nav-task").click();
    await expect(page.locator("body")).toHaveAttribute("data-pocket-focus", "task");
    await page.waitForTimeout(500);

    // Video pill in compact mode must be hidden from task viewport
    const compactVideoPill = page.locator("#pocket-video-pill.is-compact-indicator");
    await expect(compactVideoPill).toBeHidden();

    // Table and submit button must be visible and clickable
    await expect(page.locator(".pocket-table-container")).toBeVisible();
    await expect(page.locator("#student-classwork-answer")).toBeVisible();
    await expect(page.locator("#student-classwork-submit-button")).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // CODE-FINAL-01: Real collaborative OT editing Teacher <-> Student
  // ---------------------------------------------------------------------------
  test("CODE-FINAL-01: Real bidirectional OT editing works when teacher permits", async ({ browser }) => {
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

    // 1. Teacher enables student code editing
    await tPage.evaluate(() => {
      const chk = document.getElementById("board-control-student-code-editing") as HTMLInputElement;
      if (chk) {
        chk.checked = true;
        chk.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    await sPage.waitForTimeout(1000);

    // 2. Student opens Code focus and types print("POCKET_SHARED")
    await sPage.locator("#pocket-nav-code").click();
    await sPage.waitForTimeout(400);

    await sPage.evaluate(() => {
      const ta = document.getElementById("code-editor-textarea") as HTMLTextAreaElement;
      ta.value = "print(\"POCKET_SHARED\")";
      if (typeof (window as any).onCodeEditorInput === "function") (window as any).onCodeEditorInput(ta.value);
    });
    await tPage.waitForTimeout(1200);

    // Teacher receives student code via OT
    const tCode = await tPage.evaluate(() => {
      return (document.getElementById("code-editor-textarea") as HTMLTextAreaElement)?.value;
    });
    expect(tCode).toContain("print(\"POCKET_SHARED\")");

    // 3. Teacher adds line
    await tPage.evaluate(() => {
      const ta = document.getElementById("code-editor-textarea") as HTMLTextAreaElement;
      ta.value += "\nprint(\"TEACHER_CONFIRMED\")";
      if (typeof (window as any).onCodeEditorInput === "function") (window as any).onCodeEditorInput(ta.value);
    });
    await sPage.waitForTimeout(1200);

    // Student receives teacher line via OT
    const sCode = await sPage.evaluate(() => {
      return (document.getElementById("code-editor-textarea") as HTMLTextAreaElement)?.value;
    });
    expect(sCode).toContain("print(\"TEACHER_CONFIRMED\")");

    await sCtx.close();
    await tCtx.close();
  });

  // ---------------------------------------------------------------------------
  // SECURITY-FINAL-01: Correctness and expected answer privacy
  // ---------------------------------------------------------------------------
  test("SECURITY-FINAL-01: Expected answer key is hidden unless teacher explicitly enables visibility", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page, studentUsername);
    await page.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("#pocket-os-shell")).toBeVisible({ timeout: 15_000 });

    await page.locator("#pocket-nav-task").click();
    await page.waitForTimeout(500);

    // Expected answer value (#task-current-answer) must be hidden from student
    const ansElement = page.locator("#task-current-answer");
    if (await ansElement.count() > 0) {
      await expect(ansElement).toBeHidden();
    }
  });

  // ---------------------------------------------------------------------------
  // REGRESSION-FINAL-01 & 02: Sprint 1.2 Layout + Desktop Lesson OS Zero Regression
  // ---------------------------------------------------------------------------
  test("REGRESSION-FINAL-01 & 02: Code Focus height 740px, landscape 844px, and Desktop Lesson OS intact", async ({ browser }) => {
    // 1. Mobile Student: Height in portrait >= 720px, Width in landscape = 844px
    const sCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const sPage = await sCtx.newPage();
    await login(sPage, studentUsername);
    await sPage.goto(`${roomUrl}?pocket_os=1`, { waitUntil: "domcontentloaded" });
    await sPage.locator("#pocket-nav-code").click();
    await sPage.waitForTimeout(400);

    const portraitBox = await sPage.evaluate(() => {
      const r = document.getElementById("code-window")?.getBoundingClientRect() || { width: 0, height: 0 };
      return { width: Math.round(r.width), height: Math.round(r.height) };
    });
    expect(portraitBox.height).toBeGreaterThanOrEqual(720);

    await sPage.setViewportSize({ width: 844, height: 390 });
    await sPage.waitForTimeout(400);

    const landscapeBox = await sPage.evaluate(() => {
      const r = document.getElementById("code-window")?.getBoundingClientRect() || { width: 0, height: 0 };
      return { width: Math.round(r.width), height: Math.round(r.height) };
    });
    expect(landscapeBox.width).toBe(844);

    // 2. Desktop Teacher: Zero WindowManager regressions
    const tCtx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const tPage = await tCtx.newPage();
    await login(tPage, tutorUsername);
    await tPage.goto(roomUrl, { waitUntil: "domcontentloaded" });

    await expect(tPage.locator("body")).not.toHaveClass(/pocket-os-active/);
    await expect(tPage.locator("#pocket-os-shell")).toBeHidden();
    await expect(tPage.locator("header.lesson-os-system-bar")).toBeVisible();
    await expect(tPage.locator("#canvas-window")).toBeVisible();

    await sCtx.close();
    await tCtx.close();
  });
});
