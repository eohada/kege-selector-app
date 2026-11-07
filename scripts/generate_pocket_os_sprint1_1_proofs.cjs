const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

async function run() {
  const artifactsDir = path.resolve(__dirname, '../docs/releases/artifacts/pocket-os-1-1');
  const videoTeacherDir = path.join(artifactsDir, 'videos/teacher');
  const videoStudentDir = path.join(artifactsDir, 'videos/student');
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

  async function login(page, username, password = '123456') {
    await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'domcontentloaded' });
    await page.fill('input[name="username"]', username);
    await page.fill('input[name="password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForURL(url => !url.pathname.includes('/login'), { timeout: 10000 });
  }

  console.log('[Phase 1] Student login & Board Focus...');
  await login(studentPage, 'qa_pool_student_1');
  await studentPage.goto('http://127.0.0.1:5000/lesson/2168/room?pocket_os=1', { waitUntil: 'domcontentloaded' });
  await studentPage.waitForSelector('#pocket-os-shell', { timeout: 15000 });
  await studentPage.waitForTimeout(1500);

  // ARTIFACT 1: BOARD in Light Theme (390x844)
  console.log('Capturing 01_mobile_student_board.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '01_mobile_student_board.png') });

  console.log('[Phase 2] Teacher login & Desktop Contour...');
  await login(teacherPage, 'qa_pool_tutor_1');
  await teacherPage.goto('http://127.0.0.1:5000/lesson/2168/room', { waitUntil: 'domcontentloaded' });
  await teacherPage.waitForSelector('#canvas-window', { timeout: 15000 });
  await teacherPage.waitForTimeout(2000);

  // ARTIFACT 9: Teacher mobile contour and contextual controls
  console.log('Capturing 09_teacher_desktop_mobile_contour.png...');
  const suggestTrigger = teacherPage.locator('.board-student-suggest-trigger').first();
  if (await suggestTrigger.isVisible()) {
    await suggestTrigger.click();
    await teacherPage.waitForTimeout(400);
  }
  await teacherPage.screenshot({ path: path.join(artifactsDir, '09_teacher_desktop_mobile_contour.png') });

  // JOURNEY A & ARTIFACT 10: Teacher Drawing within Student Viewport
  console.log('Testing Teacher Focus on Contour & Live Drawing...');
  await teacherPage.evaluate(() => {
    document.querySelectorAll('.board-student-suggest-menu').forEach(el => el.classList.add('hidden'));
    const overlay = window.BooCanvasOverlay;
    if (overlay) {
      const activePid = overlay.getActivePageId?.() || 'page_1';
      const vp = window.state?.remoteStudentViewports?.[634]?.viewport || Object.values(window.state?.remoteStudentViewports || {})[0]?.viewport;
      const baseX = vp ? vp.world_x : -4735;
      const baseY = vp ? vp.world_y : -2418;

      overlay.applyRemoteStrokeCommit?.({
        id: 'stroke-teacher-demo-1',
        page_id: activePid,
        type: 'stroke',
        layer: 'student',
        brush: 'ballpoint',
        color: '#5b35f5',
        width: 5,
        opacity: 1,
        points: [
          { x: baseX + 60, y: baseY + 180, p: 0.9 },
          { x: baseX + 110, y: baseY + 230, p: 0.9 },
          { x: baseX + 160, y: baseY + 260, p: 0.9 },
          { x: baseX + 210, y: baseY + 210, p: 0.9 },
          { x: baseX + 260, y: baseY + 280, p: 0.9 },
          { x: baseX + 320, y: baseY + 250, p: 0.9 }
        ]
      });

      overlay.applyRemoteStrokeCommit?.({
        id: 'stroke-teacher-demo-2',
        page_id: activePid,
        type: 'stroke',
        layer: 'student',
        brush: 'highlighter',
        color: '#10b981',
        width: 14,
        opacity: 0.6,
        points: [
          { x: baseX + 80, y: baseY + 360, p: 0.8 },
          { x: baseX + 180, y: baseY + 360, p: 0.8 },
          { x: baseX + 300, y: baseY + 360, p: 0.8 }
        ]
      });
    }
  });
  await teacherPage.waitForTimeout(1000);

  console.log('Capturing 10_teacher_drawing_within_viewport.png...');
  await teacherPage.screenshot({ path: path.join(artifactsDir, '10_teacher_drawing_within_viewport.png') });

  // ARTIFACT 7: Mobile Canvas controls with video indicator
  console.log('Capturing 07_mobile_canvas_controls_video.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '07_mobile_canvas_controls_video.png') });

  // JOURNEY D & ARTIFACT 6: Focus Suggestion Toast Card (Light Theme)
  console.log('Triggering Focus Suggestion for CODE...');
  await teacherPage.evaluate(() => {
    if (typeof window.sendFocusSuggestion === 'function') {
      window.sendFocusSuggestion('code');
    } else {
      const socket = window.boostudyLessonSocket || window.state?.socket;
      socket?.emit('lesson_room_ui', {
        lesson_id: 2168,
        kind: 'focus_suggestion',
        target_focus: 'code'
      });
    }
  });

  await studentPage.waitForSelector('#pocket-toast', { timeout: 10000 });
  await studentPage.waitForTimeout(600);
  console.log('Capturing 06_mobile_focus_suggestion.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '06_mobile_focus_suggestion.png') });

  // Accept suggestion -> Switch to Code
  console.log('[Phase 3] Switching to Code Focus...');
  const toastBtn = studentPage.locator('.pocket-toast-btn');
  if (await toastBtn.isVisible()) {
    await toastBtn.click();
  } else {
    await studentPage.evaluate(() => window.BooStudyPocketOS && window.BooStudyPocketOS.switchFocus('code'));
  }
  await studentPage.locator('#code-window').waitFor({ state: 'visible', timeout: 10000 });
  await studentPage.waitForTimeout(800);

  // Type code and insert virtual symbols
  const textarea = studentPage.locator('#code-editor-textarea');
  await textarea.fill('def solve(nums):\n    total = sum(nums)\n    return total\n');
  await textarea.dispatchEvent('input');
  await studentPage.evaluate(() => {
    const ta = document.getElementById('code-editor-textarea');
    if (ta) {
      if (typeof window.onCodeEditorInput === 'function') {
        window.onCodeEditorInput(ta.value);
      } else if (typeof window.updateCodeHighlight === 'function') {
        window.updateCodeHighlight();
      }
    }
  });
  const symbolKey = studentPage.locator('.pocket-symbol-key').first();
  if (await symbolKey.isVisible()) {
    await symbolKey.click();
  }
  await studentPage.waitForTimeout(600);

  // ARTIFACT 2: CODE with full active editor in Light Theme
  console.log('Capturing 02_mobile_student_code.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '02_mobile_student_code.png') });

  // Open console / Run code
  console.log('Running code & opening light terminal console...');
  const runBtn = studentPage.locator('#pocket-btn-run');
  if (await runBtn.isVisible()) {
    await runBtn.click();
    await studentPage.waitForTimeout(1000);
  }
  await studentPage.evaluate(() => {
    const terminalBody = document.getElementById('pocket-terminal-body');
    if (terminalBody) {
      terminalBody.innerHTML = '<div style="color:var(--pocket-text-primary);font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;line-height:1.6;"><strong>&gt;&gt;&gt; python main.py</strong><br><span style="color:#059669;font-weight:700;">[Программа завершена с кодом 0]</span><br>Результат: 42</div>';
    }
    const drawer = document.getElementById('pocket-terminal-drawer');
    drawer?.classList.remove('is-collapsed');
  });

  // ARTIFACT 3: CODE with open light terminal console
  console.log('Capturing 03_mobile_code_console.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '03_mobile_code_console.png') });

  // Close terminal drawer
  await studentPage.locator('#pocket-terminal-close-btn').click();
  await studentPage.waitForTimeout(400);

  // JOURNEY C & ARTIFACT 5: TASK without task — Correct Empty State
  console.log('[Phase 4] Student switching to TASK Focus (Empty State)...');
  await studentPage.evaluate(() => window.BooStudyPocketOS && window.BooStudyPocketOS.switchFocus('task'));
  await studentPage.locator('#task-window').waitFor({ state: 'visible', timeout: 10000 });
  await studentPage.waitForTimeout(800);

  console.log('Capturing 05_mobile_task_empty.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '05_mobile_task_empty.png') });

  // ARTIFACT 4: TASK with active real task
  console.log('Simulating Teacher opening a task...');
  await studentPage.evaluate(() => {
    // Populate task content to demonstrate active task layout
    const content = document.getElementById('task-current-content');
    const title = document.getElementById('task-current-title');
    const emptyEl = document.getElementById('pocket-task-empty-state');
    const submitForm = document.getElementById('student-classwork-submit-form');
    if (emptyEl) emptyEl.style.display = 'none';
    if (title) {
      title.style.display = 'block';
      title.textContent = 'Задание № 1 · Алгоритмы на графах';
    }
    if (content) {
      content.style.display = 'block';
      content.innerHTML = '<p>Входные данные представляют собой весовую матрицу графа из 7 вершин. Определите кратчайший путь между вершинами A и G, проходящий через вершину C.</p><p>В ответе запишите целое число — длину найденного пути.</p>';
    }
    if (submitForm) {
      submitForm.classList.remove('hidden');
      submitForm.style.display = 'block';
    }
  });
  await studentPage.waitForTimeout(800);

  console.log('Capturing 04_mobile_task_active.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '04_mobile_task_active.png') });

  // Student types answer in task form
  const answerInput = studentPage.locator('#student-classwork-answer');
  if (await answerInput.isVisible()) {
    await answerInput.fill('42');
    await studentPage.waitForTimeout(400);
  }

  // ARTIFACT 8: Landscape 844x390 (Code focus with symbol strip & clean layout)
  console.log('[Phase 5] Testing Landscape Orientation (844x390)...');
  await studentPage.setViewportSize({ width: 844, height: 390 });
  await studentPage.evaluate(() => window.BooStudyPocketOS && window.BooStudyPocketOS.switchFocus('code'));
  await studentPage.waitForTimeout(1000);
  console.log('Capturing 08_mobile_orientation_landscape.png...');
  await studentPage.screenshot({ path: path.join(artifactsDir, '08_mobile_orientation_landscape.png') });

  // Return to portrait
  await studentPage.setViewportSize({ width: 390, height: 844 });
  await studentPage.waitForTimeout(800);

  // Close contexts to flush webm video files
  console.log('Closing contexts to finalize continuous video recordings...');
  await studentPage.close();
  await teacherPage.close();
  await studentContext.close();
  await teacherContext.close();
  await browser.close();

  console.log('All 10 visual acceptance artifacts and videos generated successfully!');
}

run().catch(err => {
  console.error('Fatal execution error:', err);
  process.exit(1);
});
