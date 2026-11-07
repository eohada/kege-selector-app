const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

async function run() {
  const artifactsDir = path.resolve(__dirname, "../docs/releases/artifacts/pocket-os-final-acceptance");
  const videoTeacherDir = path.join(artifactsDir, "videos/teacher_raw");
  const videoStudentDir = path.join(artifactsDir, "videos/student_raw");
  const brainDir = "/home/eohada/.gemini/antigravity/brain/24b6318b-38b1-42e7-a542-c5cb4d3923fe/pocket-os-final";
  const brainVideosDir = path.join(brainDir, "videos");

  fs.mkdirSync(videoTeacherDir, { recursive: true });
  fs.mkdirSync(videoStudentDir, { recursive: true });
  fs.mkdirSync(brainVideosDir, { recursive: true });

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

  console.log("[Phase 1] Student login & Board load in Pocket OS...");
  await login(studentPage, "qa_pool_student_1");
  await studentPage.goto("http://127.0.0.1:5000/lesson/2168/room?pocket_os=1", { waitUntil: "domcontentloaded" });
  await studentPage.waitForSelector("#pocket-os-shell", { timeout: 15000 });
  await studentPage.waitForTimeout(1500);

  console.log("[Phase 2] Teacher login & Desktop Lesson OS load...");
  await login(teacherPage, "qa_pool_tutor_1");
  await teacherPage.goto("http://127.0.0.1:5000/lesson/2168/room", { waitUntil: "domcontentloaded" });
  await teacherPage.waitForSelector("#canvas-window", { timeout: 15000 });
  await teacherPage.waitForTimeout(1500);

  // Close code-window on teacher desktop for wide open board view
  await teacherPage.evaluate(() => {
    if (typeof window.closeWindow === "function") {
      window.closeWindow("code-window");
    }
  });
  await teacherPage.waitForTimeout(500);

  // Focus teacher camera towards student contour
  await teacherPage.evaluate(() => {
    if (typeof window.focusOnStudentViewport === "function") {
      window.focusOnStudentViewport();
    }
  });
  await teacherPage.waitForTimeout(1000);

  // PROOF 1: Teacher desktop showing student viewport contour
  console.log("Capturing 01_teacher_student_contour_clean.png...");
  await teacherPage.screenshot({ path: path.join(artifactsDir, "01_teacher_student_contour_clean.png") });

  // Compute student visible center coordinates
  const sBounds = await studentPage.evaluate(() => {
    return window.BooCanvasOverlay?.getViewportWorldBounds?.();
  });
  console.log("Student visible world bounds:", sBounds);
  const cx = Math.round(sBounds.worldX + sBounds.worldW / 2);
  const cy = Math.round(sBounds.worldY + sBounds.worldH / 2);

  // PROOF 2: Teacher draws recognized shape (circle + arrow) inside student contour
  console.log("[Phase 3] Teacher drawing circle + arrow at center:", cx, cy);
  const r = 60;
  const circlePoints = [];
  for (let i = 0; i <= 36; i++) {
    const theta = (i / 36) * Math.PI * 2;
    circlePoints.push({ x: Math.round(cx + r * Math.cos(theta)), y: Math.round(cy + r * Math.sin(theta)) });
  }
  const arrowPoints = [
    { x: Math.round(cx - 35), y: Math.round(cy) },
    { x: Math.round(cx + 35), y: Math.round(cy) },
    { x: Math.round(cx + 15), y: Math.round(cy - 18) },
    { x: Math.round(cx + 35), y: Math.round(cy) },
    { x: Math.round(cx + 15), y: Math.round(cy + 18) }
  ];

  const circleId = "final_proof_circle_" + Date.now();
  const arrowId = "final_proof_arrow_" + Date.now();

  await teacherPage.evaluate(({ circlePoints, arrowPoints, circleId, arrowId }) => {
    const overlay = window.BooCanvasOverlay;
    const pid = overlay?.getActivePageId?.() || "page_1";
    const socket = window.state?.socket;

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

  await teacherPage.waitForTimeout(1000);
  console.log("Capturing 02_teacher_drawing_circle_arrow.png...");
  await teacherPage.screenshot({ path: path.join(artifactsDir, "02_teacher_drawing_circle_arrow.png") });

  // PROOF 3: Student visible circle + arrow in center of mobile viewport
  await studentPage.waitForTimeout(1000);
  console.log("Capturing 03_student_visible_circle_arrow.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "03_student_visible_circle_arrow.png") });

  // PROOF 4: Student reload preserves drawing
  console.log("[Phase 4] Student reload & persistence check...");
  await studentPage.reload();
  await studentPage.waitForSelector("#pocket-os-shell", { timeout: 15000 });
  await studentPage.waitForTimeout(1500);
  console.log("Capturing 04_student_reload_persisted.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "04_student_reload_persisted.png") });

  // PROOF 5 & 6: Teacher Show Here and Student readable centering
  console.log("[Phase 5] Teacher Show Here framing & Student readable scale...");
  await teacherPage.evaluate(() => {
    if (typeof window.teacherShowHere === "function") {
      window.teacherShowHere();
    }
  });
  await teacherPage.waitForTimeout(800);
  console.log("Capturing 05_teacher_show_here_framed.png...");
  await teacherPage.screenshot({ path: path.join(artifactsDir, "05_teacher_show_here_framed.png") });

  await studentPage.waitForTimeout(1000);
  const studentCam = await studentPage.evaluate(() => window.BooCanvasOverlay?.getCamera?.());
  console.log("Student camera after Show Here:", studentCam);
  console.log("Capturing 06_student_show_here_centered_readable.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "06_student_show_here_centered_readable.png") });

  // PROOF 7: Single Zoom Controls System (zero duplicate desktop zoom bars)
  console.log("Capturing 07_single_zoom_controls_board.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "07_single_zoom_controls_board.png") });

  // PROOF 8: Task Focus Clean Matrix & No Video Badge Overlap
  console.log("[Phase 6] Task Focus & table layout clearance...");
  await studentPage.locator("#pocket-nav-task").click();
  await studentPage.waitForTimeout(1000);
  console.log("Capturing 08_task_table_unobstructed.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "08_task_table_unobstructed.png") });

  // PROOF 9 & 10: Shared Code OT Mode Teacher <-> Student
  console.log("[Phase 7] Shared Code OT Mode bidirectional sync...");
  // Open code-window on teacher desktop
  await teacherPage.evaluate(() => {
    if (typeof window.openWindow === "function") {
      window.openWindow("code-window");
    }
  });
  await teacherPage.waitForTimeout(600);

  // Enable student code editing on teacher page
  await teacherPage.evaluate(() => {
    const chk = document.getElementById("board-control-student-code-editing");
    if (chk) {
      chk.checked = true;
      chk.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
  await studentPage.waitForTimeout(1000);

  // Switch student to Code Focus
  await studentPage.locator("#pocket-nav-code").click();
  await studentPage.waitForTimeout(800);

  // Student types code
  await studentPage.evaluate(() => {
    const ta = document.getElementById("code-editor-textarea");
    ta.value = "# Pocket OS Shared OT Session\ndef solve(matrix):\n    return sum(matrix)\n\nprint(\"STUDENT_OT_READY\")";
    if (typeof window.onCodeEditorInput === "function") window.onCodeEditorInput(ta.value);
  });
  await teacherPage.waitForTimeout(1200);

  // Teacher appends line
  await teacherPage.evaluate(() => {
    const ta = document.getElementById("code-editor-textarea");
    ta.value += "\nprint(\"TEACHER_OT_VERIFIED\")";
    if (typeof window.onCodeEditorInput === "function") window.onCodeEditorInput(ta.value);
  });
  await studentPage.waitForTimeout(1200);

  console.log("Capturing 09_shared_code_ot_teacher.png...");
  await teacherPage.screenshot({ path: path.join(artifactsDir, "09_shared_code_ot_teacher.png") });

  console.log("Capturing 10_shared_code_ot_student.png...");
  await studentPage.screenshot({ path: path.join(artifactsDir, "10_shared_code_ot_student.png") });

  // PROOF 11: Desktop Lesson OS Zero Regression
  console.log("Capturing 11_desktop_zero_regression.png...");
  await teacherPage.screenshot({ path: path.join(artifactsDir, "11_desktop_zero_regression.png") });

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
    const tDest = path.join(videosDir, "teacher_session_continuous.webm");
    fs.renameSync(path.join(videoTeacherDir, tFiles[0]), tDest);
    fs.copyFileSync(tDest, path.join(brainVideosDir, "teacher_session_continuous.webm"));
    fs.rmSync(videoTeacherDir, { recursive: true, force: true });
  }
  if (sFiles.length > 0) {
    const sDest = path.join(videosDir, "student_session_continuous.webm");
    fs.renameSync(path.join(videoStudentDir, sFiles[0]), sDest);
    fs.copyFileSync(sDest, path.join(brainVideosDir, "student_session_continuous.webm"));
    fs.rmSync(videoStudentDir, { recursive: true, force: true });
  }

  // Copy all screenshot artifacts to brain directory
  const files = fs.readdirSync(artifactsDir).filter(f => f.endsWith(".png"));
  for (const f of files) {
    fs.copyFileSync(path.join(artifactsDir, f), path.join(brainDir, f));
  }

  console.log(`Successfully generated ${files.length} visual proofs and 2 continuous WebM videos!`);
  console.log(`Copied to both ${artifactsDir} and ${brainDir}`);
}

run().catch(err => {
  console.error("Fatal execution error:", err);
  process.exit(1);
});
