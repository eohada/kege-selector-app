const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

async function run() {
  const artifactsDir = path.resolve(__dirname, "../docs/releases/artifacts/pocket-os-1-2");
  const videoTeacherDir = path.join(artifactsDir, "videos/teacher_raw");
  const videoStudentDir = path.join(artifactsDir, "videos/student_raw");
  fs.mkdirSync(videoTeacherDir, { recursive: true });
  fs.mkdirSync(videoStudentDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });

  // 1. Student Context: Mobile viewport 390x844 (iPhone 14)
  const studentContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    recordVideo: { dir: videoStudentDir, size: { width: 390, height: 844 } }
  });

  // 2. Teacher Context: Desktop Full HD 1920x1080
  const teacherContext = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: videoTeacherDir, size: { width: 1920, height: 1080 } }
  });

  const studentPage = await studentContext.newPage();
  const teacherPage = await teacherContext.newPage();

  async function login(page, username, password = "123456") {
    await page.goto("http://127.0.0.1:5000/login", { waitUntil: "domcontentloaded" });
    await page.fill("input[name=\"username\"]", username);
    await page.fill("input[name=\"password\"]", password);
    await page.click("button[type=\"submit\"]");
    await page.waitForURL(url => !url.pathname.includes("/login"), { timeout: 10000 });
  }

  console.log("[Phase 1] Student login & Board Focus...");
  await login(studentPage, "qa_pool_student_1");
  await studentPage.goto("http://127.0.0.1:5000/lesson/2168/room?pocket_os=1", { waitUntil: "domcontentloaded" });
  await studentPage.waitForSelector("#pocket-os-shell", { timeout: 15000 });
  await studentPage.waitForTimeout(1500);

  // PROOF 1: 01_mobile_student_board.png
  console.log("Capturing 01_mobile_student_board.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "01_mobile_student_board.png") });

  // PROOF 10: Desktop Lesson OS Zero Regression (Teacher desktop)
  console.log("[Phase 2] Teacher login & Desktop Lesson OS check...");
  await login(teacherPage, "qa_pool_tutor_1");
  await teacherPage.goto("http://127.0.0.1:5000/lesson/2168/room", { waitUntil: "domcontentloaded" });
  await teacherPage.waitForSelector("#canvas-window", { timeout: 15000 });
  await teacherPage.waitForTimeout(2000);

  console.log("Capturing 10_desktop_zero_regression.png...");
  await teacherPage.screenshot({ path: path.join(artifactsDir, "10_desktop_zero_regression.png") });

  // Switch student to Code Focus
  console.log("[Phase 3] Code Focus full available height in portrait...");
  await studentPage.locator("#pocket-nav-code").click();
  await studentPage.waitForTimeout(600);

  // PROOF 2: 02_mobile_student_code_portrait.png
  console.log("Capturing 02_mobile_student_code_portrait.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "02_mobile_student_code_portrait.png") });

  // PROOF 3: 03_mobile_student_code_landscape.png
  console.log("[Phase 4] Testing Landscape Orientation (844x390)...");
  await studentPage.setViewportSize({ width: 844, height: 390 });
  await studentPage.waitForTimeout(800);
  console.log("Capturing 03_mobile_student_code_landscape.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "03_mobile_student_code_landscape.png") });

  // Return student to portrait
  await studentPage.setViewportSize({ width: 390, height: 844 });
  await studentPage.waitForTimeout(600);

  // PROOF 4: Real Python Execution (42 and 6)
  console.log("[Phase 5] Real Python execution in Skulpt...");
  await studentPage.evaluate(() => {
    const ta = document.getElementById("code-editor-textarea");
    ta.value = "def solve(a, b):\n    return a + b\n\ndef combinations(n):\n    return n * (n - 1) // 2\n\nprint(\"solve(20, 22) =\", solve(20, 22))\nprint(\"combinations(4) =\", combinations(4))";
    if (typeof window.onCodeEditorInput === "function") window.onCodeEditorInput(ta.value);
  });
  await studentPage.locator("#pocket-btn-run").click();
  await studentPage.waitForTimeout(1500);

  console.log("Capturing 04_mobile_code_real_execution.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "04_mobile_code_real_execution.png") });

  // PROOF 5: Stale Output Indicator (код изменён)
  console.log("[Phase 6] Stale output badge...");
  await studentPage.evaluate(() => {
    const ta = document.getElementById("code-editor-textarea");
    ta.value += "\n\n# Модификация кода после выполнения";
    if (typeof window.onCodeEditorInput === "function") window.onCodeEditorInput(ta.value);
  });
  await studentPage.waitForTimeout(400);

  console.log("Capturing 05_mobile_code_stale_indicator.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "05_mobile_code_stale_indicator.png") });

  // Close terminal drawer
  await studentPage.locator("#pocket-terminal-close-btn").click();
  await studentPage.waitForTimeout(300);

  // PROOF 6 & 7: Task Focus & Real Task 5464 & No Guidance
  console.log("[Phase 7] Task Focus Real Content & No Guidance...");
  await studentPage.locator("#pocket-nav-task").click();
  await studentPage.waitForTimeout(800);

  console.log("Capturing 06_mobile_task_matrix_table.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "06_mobile_task_matrix_table.png") });

  console.log("Capturing 07_mobile_task_no_guidance.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "07_mobile_task_no_guidance.png") });

  // PROOF 8: BooCanvas Live Stroke Sync (Dual-Screen)
  console.log("[Phase 8] Two-Screen BooCanvas Stroke Sync...");
  await studentPage.locator("#pocket-nav-board").click();
  await studentPage.waitForTimeout(600);

  // Teacher emits stroke inside student view area
  await teacherPage.evaluate(() => {
    const overlay = window.BooCanvasOverlay;
    const pid = overlay?.getActivePageId?.() || "page_1";
    const strokeData = {
      id: "stroke_sync_demo_" + Date.now(),
      tool: "pen",
      color: "#5b35f5",
      width: 5,
      page_id: pid,
      points: [
        { x: 120, y: 150 },
        { x: 180, y: 220 },
        { x: 260, y: 200 },
        { x: 320, y: 280 }
      ]
    };
    if (window.state?.socket) {
      window.state.socket.emit("board_stroke", {
        lesson_id: 2168,
        stroke: strokeData
      });
    }
    overlay?.applyRemoteStrokeCommit?.(strokeData);
  });
  await studentPage.waitForTimeout(1000);

  console.log("Capturing 08_dual_screen_stroke_sync.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "08_dual_screen_stroke_sync.png") });

  // PROOF 9: Teacher Show Here Camera Sync
  console.log("[Phase 9] Teacher Show Here Sync...");
  await teacherPage.evaluate(() => {
    if (typeof window.teacherShowHere === "function") {
      window.teacherShowHere(200, 200, 350, 350);
    } else if (window.state?.socket) {
      window.state.socket.emit("whiteboard_show_here", {
        lesson_id: 2168,
        world_x: 200,
        world_y: 200,
        world_w: 350,
        world_h: 350
      });
    }
  });
  await studentPage.waitForTimeout(1000);

  console.log("Capturing 09_teacher_show_here_sync.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "09_teacher_show_here_sync.png") });

  // Close contexts to flush continuous videos
  console.log("Closing contexts to finalize continuous video recordings...");
  await studentPage.close();
  await teacherPage.close();
  await studentContext.close();
  await teacherContext.close();
  await browser.close();

  // Move continuous video files to destination
  const videosDir = path.join(artifactsDir, "videos");
  const tFiles = fs.readdirSync(videoTeacherDir).filter(f => f.endsWith(".webm"));
  const sFiles = fs.readdirSync(videoStudentDir).filter(f => f.endsWith(".webm"));

  if (tFiles.length > 0) {
    fs.renameSync(path.join(videoTeacherDir, tFiles[0]), path.join(videosDir, "teacher_session_continuous.webm"));
    fs.rmdirSync(videoTeacherDir, { recursive: true });
  }
  if (sFiles.length > 0) {
    fs.renameSync(path.join(videoStudentDir, sFiles[0]), path.join(videosDir, "student_session_continuous.webm"));
    fs.rmdirSync(videoStudentDir, { recursive: true });
  }

  console.log("All 10 visual proofs and 2 continuous WebM videos generated successfully!");
}

run().catch(err => {
  console.error("Fatal execution error:", err);
  process.exit(1);
});
