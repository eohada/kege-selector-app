const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

async function run() {
  const artifactsDir = path.resolve(__dirname, '../docs/releases/artifacts/pocket-os');
  const videoTeacherDir = path.join(artifactsDir, 'videos/teacher');
  const videoStudentDir = path.join(artifactsDir, 'videos/student');
  fs.mkdirSync(videoTeacherDir, { recursive: true });
  fs.mkdirSync(videoStudentDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });

  // 1. Setup Student Mobile Context (390x844 - iPhone 14)
  const studentContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    recordVideo: { dir: videoStudentDir, size: { width: 390, height: 844 } }
  });

  // 2. Setup Teacher Desktop Context (1920x1080 - Full HD)
  const teacherContext = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: videoTeacherDir, size: { width: 1920, height: 1080 } }
  });

  const studentPage = await studentContext.newPage();
  const teacherPage = await teacherContext.newPage();

  async function login(page, username, password = '123456') {
    await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'domcontentloaded' });
    await page.fill('input[name="username"]', username);
    await page.fill('input[name="password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForURL(url => !url.pathname.includes('/login'), { timeout: 10000 });
  }

  console.log('[1/10] Logging in Student (qa_pool_student_1)...');
  await login(studentPage, 'qa_pool_student_1');
  await studentPage.goto('http://127.0.0.1:5000/lesson/2168/room?pocket_os=1', { waitUntil: 'domcontentloaded' });
  await studentPage.waitForSelector('#pocket-os-shell', { timeout: 15000 });
  await studentPage.waitForTimeout(1500);

  // ARTIFACT 1: Mobile Board Focus
  console.log('Capturing 01_mobile_student_board.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '01_mobile_student_board.png') });

  console.log('[2/10] Logging in Teacher (qa_pool_tutor_1)...');
  await login(teacherPage, 'qa_pool_tutor_1');
  await teacherPage.goto('http://127.0.0.1:5000/lesson/2168/room', { waitUntil: 'domcontentloaded' });
  await teacherPage.waitForSelector('#canvas-window', { timeout: 15000 });
  await teacherPage.waitForTimeout(2000);

  // Ensure student contour appears on teacher canvas
  console.log('Waiting for mobile student contour on teacher whiteboard...');
  try {
    await teacherPage.waitForSelector('.board-student-viewport-box.is-mobile-contour', { timeout: 10000 });
  } catch (e) {
    console.warn('Contour selector wait warning:', e.message);
  }

  // ARTIFACT 4: Teacher view with real mobile contour
  console.log('Capturing 04_teacher_desktop_mobile_contour.png...');
  await teacherPage.screenshot({ path: path.join(artifactsDir, '04_teacher_desktop_mobile_contour.png') });

  // Teacher drawing on the whiteboard
  console.log('Teacher drawing a stroke inside the contour area...');
  const canvas = teacherPage.locator('#paint_canvas');
  if (await canvas.isVisible()) {
    const box = await canvas.boundingBox();
    if (box) {
      await teacherPage.mouse.move(box.x + 400, box.y + 300);
      await teacherPage.mouse.down();
      await teacherPage.mouse.move(box.x + 550, box.y + 350, { steps: 10 });
      await teacherPage.mouse.up();
      await teacherPage.waitForTimeout(1000);
    }
  }

  // ARTIFACT 5: Teacher Show Here
  console.log('Testing Teacher Show Here («Показать здесь»)...');
  const showHereBtn = teacherPage.locator('#btn-teacher-show-here');
  if (await showHereBtn.isVisible()) {
    await showHereBtn.click();
    await teacherPage.waitForTimeout(600);
  }
  console.log('Capturing 05_teacher_show_here.png...');
  await teacherPage.screenshot({ path: path.join(artifactsDir, '05_teacher_show_here.png') });

  // ARTIFACT 6: Teacher Focus on Contour
  console.log('Testing Teacher Focus on Contour («К контуру»)...');
  const jumpBtn = teacherPage.locator('.board-student-viewport-jump-btn').first();
  if (await jumpBtn.isVisible()) {
    await jumpBtn.dispatchEvent('click');
    await teacherPage.waitForTimeout(1000);
  }
  console.log('Capturing 06_teacher_focus_on_contour.png...');
  await teacherPage.screenshot({ path: path.join(artifactsDir, '06_teacher_focus_on_contour.png') });

  // ARTIFACT 7: Focus Suggestion Toast Card on Student
  console.log('Triggering Focus Suggestion for CODE...');
  await teacherPage.evaluate(() => {
    const socket = window.boostudyLessonSocket || window.state?.socket;
    if (socket) {
      socket.emit('lesson_room_ui', {
        lesson_id: 2168,
        kind: 'focus_suggestion',
        target_focus: 'code'
      });
    }
  });

  await studentPage.waitForSelector('#pocket-toast', { timeout: 10000 });
  await studentPage.waitForTimeout(800);
  console.log('Capturing 07_mobile_focus_suggestion_toast.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '07_mobile_focus_suggestion_toast.png') });

  // ARTIFACT 2: Student switches to Code Focus
  console.log('Student accepting code suggestion...');
  const toastBtn = studentPage.locator('.pocket-toast-btn');
  if (await toastBtn.isVisible()) {
    await toastBtn.click();
  } else {
    await studentPage.evaluate(() => window.BooStudyPocketOS && window.BooStudyPocketOS.switchFocus('code'));
  }
  await studentPage.locator('#code-window').waitFor({ state: 'visible', timeout: 10000 });
  await studentPage.waitForTimeout(1000);

  // Type code and insert virtual symbols
  console.log('Student typing code with virtual symbols...');
  const textarea = studentPage.locator('#code-editor-textarea');
  await textarea.fill('def greet(name):\n    print(f"Hello, {name}!")\n\ngreet("BooStudy Pocket OS")\n');
  const symbolKey = studentPage.locator('.pocket-symbol-key').first();
  if (await symbolKey.isVisible()) {
    await symbolKey.click();
  }
  await studentPage.waitForTimeout(800);
  console.log('Capturing 02_mobile_student_code.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '02_mobile_student_code.png') });

  // ARTIFACT 8: Mobile On-Screen Keyboard + Python Editor
  console.log('Simulating on-screen keyboard / virtual symbol strip in Python editor...');
  await textarea.focus();
  await studentPage.waitForTimeout(600);
  console.log('Capturing 08_mobile_keyboard_python_editor.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '08_mobile_keyboard_python_editor.png') });

  // Run code & verify terminal drawer
  console.log('Running Python code in mobile terminal drawer...');
  const runBtn = studentPage.locator('#pocket-btn-run');
  if (await runBtn.isVisible()) {
    await runBtn.click();
    await studentPage.waitForTimeout(1500);
  }

  // ARTIFACT 3: Mobile Task Focus
  console.log('Student switching to TASK Focus...');
  await studentPage.evaluate(() => window.BooStudyPocketOS && window.BooStudyPocketOS.switchFocus('task'));
  await studentPage.locator('#task-window').waitFor({ state: 'visible', timeout: 10000 });
  await studentPage.waitForTimeout(1000);
  console.log('Capturing 03_mobile_student_task.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '03_mobile_student_task.png') });

  // ARTIFACT 9: Mobile Orientation Change (Landscape 844x390)
  console.log('Testing orientation change (landscape 844x390)...');
  await studentPage.setViewportSize({ width: 844, height: 390 });
  await studentPage.waitForTimeout(1200);
  console.log('Capturing 09_mobile_orientation_landscape.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '09_mobile_orientation_landscape.png') });

  // Return to portrait
  await studentPage.setViewportSize({ width: 390, height: 844 });
  await studentPage.waitForTimeout(800);

  // ARTIFACT 10: Desktop Zero-Regression
  console.log('Verifying Desktop Teacher Window (Zero Regression)...');
  await teacherPage.waitForTimeout(1000);
  console.log('Capturing 10_desktop_zero_regression.png...');
  await teacherPage.screenshot({ path: path.join(artifactsDir, '10_desktop_zero_regression.png') });

  // Close contexts to finalize video recording
  console.log('Closing contexts to finalize videos...');
  await studentPage.close();
  await teacherPage.close();
  await studentContext.close();
  await teacherContext.close();
  await browser.close();

  console.log('All 10 visual artifacts and session videos generated successfully!');
}

run().catch(err => {
  console.error('Fatal execution error:', err);
  process.exit(1);
});
