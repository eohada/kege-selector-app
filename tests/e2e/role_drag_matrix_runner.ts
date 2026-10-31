import { chromium } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || 'http://127.0.0.1:5000/lesson/2168/room';
const ARTIFACTS_DIR = path.resolve('docs/audits/boostudy-os-reliability/artifacts/sprint10_perf');

async function login(page: any, username: string) {
  page.setDefaultNavigationTimeout(60_000);
  page.setDefaultTimeout(30_000);
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'domcontentloaded' });
  const usernameInput = page.locator('input[name="username"]');
  await usernameInput.waitFor({ state: 'visible', timeout: 15_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  try {
    await page.waitForURL((url: URL) => !url.pathname.includes('/login'), { timeout: 15_000, waitUntil: 'domcontentloaded' });
  } catch {
    if (page.url().includes('/login')) {
      await page.waitForTimeout(1000);
      await page.locator('button[type="submit"]').click().catch(() => {});
      await page.waitForURL((url: URL) => !url.pathname.includes('/login'), { timeout: 15_000, waitUntil: 'domcontentloaded' });
    }
  }
}

// In-depth instrumentation snippet injected into both Teacher and Student pages
const INSTRUMENTATION_SNIPPET = `
window.__perfTelemetry = {
  active: false,
  role: 'unknown',
  pointerMoves: 0,
  rafCount: 0,
  rafDeltas: [],
  lastRaf: 0,
  rafHandle: null,

  // Socket emit telemetry (Sender)
  socketEmits: [],

  // Socket receive telemetry (Receiver)
  socketReceives: [],
  applyUiDurations: [],

  // Layout / Reflow call counters
  reflowCount: 0,
  localStorageWrites: 0,
  localStorageReads: 0,

  // Long tasks
  longTasks: [],
  observer: null,

  start(role) {
    this.active = true;
    this.role = role;
    this.pointerMoves = 0;
    this.rafCount = 0;
    this.rafDeltas = [];
    this.socketEmits = [];
    this.socketReceives = [];
    this.applyUiDurations = [];
    this.reflowCount = 0;
    this.localStorageWrites = 0;
    this.localStorageReads = 0;
    this.longTasks = [];
    this.lastRaf = performance.now();

    // 1. Observe Long Tasks
    try {
      this.observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.entryType === 'longtask') {
            this.longTasks.push({
              startTime: entry.startTime,
              duration: entry.duration,
            });
          }
        }
      });
      this.observer.observe({ entryTypes: ['longtask'] });
    } catch (_) {}

    // 2. Track RAF
    const onFrame = (now) => {
      if (!this.active) return;
      const delta = now - this.lastRaf;
      this.lastRaf = now;
      if (delta > 0 && delta < 1000) {
        this.rafDeltas.push(delta);
      }
      this.rafCount++;
      this.rafHandle = requestAnimationFrame(onFrame);
    };
    this.rafHandle = requestAnimationFrame(onFrame);

    // 3. Track Pointermove events
    this._onPointerMove = () => {
      if (this.active) this.pointerMoves++;
    };
    window.addEventListener('pointermove', this._onPointerMove, { passive: true, capture: true });

    // 4. Hook socket.emit if available
    if (window.boostudyLessonSocket && !this._emitHooked) {
      const origEmit = window.boostudyLessonSocket.emit.bind(window.boostudyLessonSocket);
      window.boostudyLessonSocket.emit = (...args) => {
        if (this.active && args[0] === 'lesson_room_ui') {
          const t0 = performance.now();
          const res = origEmit(...args);
          const t1 = performance.now();
          this.socketEmits.push({
            time: t0,
            duration: t1 - t0,
            kind: args[1]?.kind,
            window_id: args[1]?.window_id,
          });
          return res;
        }
        return origEmit(...args);
      };
      this._emitHooked = true;
    }

    // 5. Hook socket receive (lesson_room_ui)
    if (window.boostudyLessonSocket && !this._recvHooked) {
      window.boostudyLessonSocket.on('lesson_room_ui', (payload) => {
        if (this.active && payload && payload.kind === 'window_layout') {
          const now = performance.now();
          this.socketReceives.push({
            time: now,
            window_id: payload.window_id,
            left: payload.left,
            top: payload.top,
          });
        }
      });
      this._recvHooked = true;
    }

    // 6. Hook localStorage
    if (!this._storageHooked) {
      const origSetItem = localStorage.setItem.bind(localStorage);
      const origGetItem = localStorage.getItem.bind(localStorage);
      localStorage.setItem = (...args) => {
        if (this.active) this.localStorageWrites++;
        return origSetItem(...args);
      };
      localStorage.getItem = (...args) => {
        if (this.active) this.localStorageReads++;
        return origGetItem(...args);
      };
      this._storageHooked = true;
    }
  },

  stop() {
    this.active = false;
    if (this.rafHandle) cancelAnimationFrame(this.rafHandle);
    if (this.observer) this.observer.disconnect();
    if (this._onPointerMove) window.removeEventListener('pointermove', this._onPointerMove, { capture: true });

    const deltas = [...this.rafDeltas];
    deltas.sort((a, b) => a - b);
    const totalDuration = deltas.reduce((acc, d) => acc + d, 0);
    const fps = totalDuration > 0 ? (deltas.length / totalDuration) * 1000 : 0;
    const p50 = deltas.length > 0 ? deltas[Math.floor(deltas.length * 0.50)] : 0;
    const p95 = deltas.length > 0 ? deltas[Math.floor(deltas.length * 0.95)] : 0;
    const p99 = deltas.length > 0 ? deltas[Math.floor(deltas.length * 0.99)] : 0;
    const droppedCount = deltas.filter(d => d > 20).length;
    const droppedPct = deltas.length > 0 ? (droppedCount / deltas.length) * 100 : 0;

    // Calculate inter-receive deltas
    const receiveDeltas = [];
    for (let i = 1; i < this.socketReceives.length; i++) {
      receiveDeltas.push(this.socketReceives[i].time - this.socketReceives[i - 1].time);
    }
    const avgRecvDelta = receiveDeltas.length > 0
      ? receiveDeltas.reduce((a, b) => a + b, 0) / receiveDeltas.length
      : 0;
    const maxRecvDelta = receiveDeltas.length > 0 ? Math.max(...receiveDeltas) : 0;
    const minRecvDelta = receiveDeltas.length > 0 ? Math.min(...receiveDeltas) : 0;

    return {
      role: this.role,
      frameCount: deltas.length,
      fps: Math.round(fps * 10) / 10,
      p50: Math.round(p50 * 100) / 100,
      p95: Math.round(p95 * 100) / 100,
      p99: Math.round(p99 * 100) / 100,
      droppedPct: Math.round(droppedPct * 10) / 10,
      pointerMoves: this.pointerMoves,
      longTasksCount: this.longTasks.length,
      maxLongTask: this.longTasks.length > 0 ? Math.max(...this.longTasks.map(t => t.duration)) : 0,
      socketEmitsCount: this.socketEmits.length,
      avgSocketEmitDuration: this.socketEmits.length > 0
        ? Math.round((this.socketEmits.reduce((acc, e) => acc + e.duration, 0) / this.socketEmits.length) * 100) / 100
        : 0,
      socketReceivesCount: this.socketReceives.length,
      avgRecvDelta: Math.round(avgRecvDelta * 10) / 10,
      minRecvDelta: Math.round(minRecvDelta * 10) / 10,
      maxRecvDelta: Math.round(maxRecvDelta * 10) / 10,
      localStorageWrites: this.localStorageWrites,
      localStorageReads: this.localStorageReads,
    };
  }
};
`;

async function performSmoothDrag(page: any, windowId = 'task-window', steps = 120, intervalMs = 16) {
  // Ensure target window is open and visible
  await page.evaluate((id: string) => {
    const win = document.getElementById(id);
    if (!win || win.classList.contains('hidden') || win.dataset.isMinimized === 'true') {
      (window as any).openWindow?.(id);
    }
  }, windowId);

  const header = page.locator(`#${windowId}-header, #${windowId} .glass-os-window-header, #${windowId} .lesson-os-code-titlebar`).first();
  await header.waitFor({ state: 'visible', timeout: 15_000 });
  const box = await header.boundingBox();
  if (!box) throw new Error(`Window header not found for ${windowId}`);

  const startX = box.x + Math.min(box.width / 2, 100);
  const startY = box.y + box.height / 2;
  await page.mouse.move(startX, startY);
  await page.mouse.down();

  for (let i = 1; i <= steps; i++) {
    const offsetX = Math.sin(i / 10) * 180;
    const offsetY = (i % 30) * 5;
    await page.mouse.move(startX + offsetX, startY + offsetY);
    await page.waitForTimeout(intervalMs);
  }

  await page.mouse.up();
}

async function run() {
  if (!fs.existsSync(ARTIFACTS_DIR)) {
    fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
  }

  console.log('=== ROLE-BASED ASYMMETRY BENCHMARK RUNNER ===');
  console.log('Launching 2 separate browser contexts (Teacher & Student)...');

  const browser = await chromium.launch({
    headless: false,
    args: [
      '--enable-gpu-rasterization',
      '--enable-zero-copy',
      '--ignore-gpu-blocklist',
      '--window-size=1280,800',
    ],
  });

  try {
    // 1. Setup Teacher
    console.log('[Setup] Logging in Teacher...');
    const ctxTeacher = await browser.newContext({ viewport: { width: 1280, height: 768 } });
    const pageTeacher = await ctxTeacher.newPage();
    await login(pageTeacher, tutorUsername);
    await pageTeacher.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await pageTeacher.locator('#code-window').waitFor({ state: 'visible', timeout: 25_000 });
    await pageTeacher.evaluate(INSTRUMENTATION_SNIPPET);
    await pageTeacher.waitForTimeout(2000);

    // 2. Setup Student
    console.log('[Setup] Logging in Student...');
    const ctxStudent = await browser.newContext({ viewport: { width: 1280, height: 768 } });
    const pageStudent = await ctxStudent.newPage();
    await login(pageStudent, studentUsername);
    await pageStudent.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await pageStudent.locator('#code-window').waitFor({ state: 'visible', timeout: 25_000 });
    await pageStudent.evaluate(INSTRUMENTATION_SNIPPET);
    await pageStudent.waitForTimeout(2000);

    const report: Record<string, any> = {};

    // =========================================================================
    // MATRIX 1: TEACHER DRAGS (Local Teacher vs Remote Student Observer)
    // =========================================================================
    console.log('\n--- TEST 1: TEACHER DRAGS WINDOW ---');
    console.log('Measuring Teacher local performance and Student remote reception...');

    // Start telemetry on both
    await pageTeacher.evaluate(() => (window as any).__perfTelemetry.start('teacher_local'));
    await pageStudent.evaluate(() => (window as any).__perfTelemetry.start('student_remote'));

    // Perform smooth drag on Teacher
    await performSmoothDrag(pageTeacher, 'task-window', 120, 16); // ~2.0 seconds drag
    await pageTeacher.waitForTimeout(500);

    // Collect telemetry
    const teacherLocalResult = await pageTeacher.evaluate(() => (window as any).__perfTelemetry.stop());
    const studentRemoteResult = await pageStudent.evaluate(() => (window as any).__perfTelemetry.stop());

    report['1_teacher_drags_local_teacher'] = teacherLocalResult;
    report['1_teacher_drags_remote_student'] = studentRemoteResult;

    console.log('Result Teacher Local:', JSON.stringify(teacherLocalResult, null, 2));
    console.log('Result Student Remote:', JSON.stringify(studentRemoteResult, null, 2));

    await pageTeacher.waitForTimeout(1000);

    // =========================================================================
    // MATRIX 2: STUDENT DRAGS (Local Student vs Remote Teacher Observer)
    // =========================================================================
    console.log('\n--- TEST 2: STUDENT DRAGS WINDOW (Default Teacher-only mode) ---');
    console.log('Measuring Student local performance and Teacher remote reception...');

    // Start telemetry on both
    await pageStudent.evaluate(() => (window as any).__perfTelemetry.start('student_local'));
    await pageTeacher.evaluate(() => (window as any).__perfTelemetry.start('teacher_remote'));

    // Perform smooth drag on Student
    await performSmoothDrag(pageStudent, 'task-window', 120, 16); // ~2.0 seconds drag
    await pageStudent.waitForTimeout(500);

    // Collect telemetry
    const studentLocalResult = await pageStudent.evaluate(() => (window as any).__perfTelemetry.stop());
    const teacherRemoteResult = await pageTeacher.evaluate(() => (window as any).__perfTelemetry.stop());

    report['2_student_drags_local_student'] = studentLocalResult;
    report['2_student_drags_remote_teacher'] = teacherRemoteResult;

    console.log('Result Student Local:', JSON.stringify(studentLocalResult, null, 2));
    console.log('Result Teacher Remote:', JSON.stringify(teacherRemoteResult, null, 2));

    await pageTeacher.waitForTimeout(1000);

    // =========================================================================
    // MATRIX 3: STUDENT DRAGS WITH MUTUAL SYNC (windows_mode: 'both')
    // =========================================================================
    console.log('\n--- TEST 3: STUDENT DRAGS WINDOW (Mutual Sync mode: windows_mode = both) ---');
    await pageTeacher.evaluate(() => {
      const btn = document.querySelector('.win-mode-btn[data-mode="both"]') as HTMLElement;
      if (btn) btn.click();
    });
    await pageTeacher.waitForTimeout(1000);

    await pageStudent.evaluate(() => (window as any).__perfTelemetry.start('student_local_mutual'));
    await pageTeacher.evaluate(() => (window as any).__perfTelemetry.start('teacher_remote_mutual'));

    await performSmoothDrag(pageStudent, 'task-window', 120, 16);
    await pageStudent.waitForTimeout(500);

    const studentLocalMutualResult = await pageStudent.evaluate(() => (window as any).__perfTelemetry.stop());
    const teacherRemoteMutualResult = await pageTeacher.evaluate(() => (window as any).__perfTelemetry.stop());

    report['3_student_drags_mutual_local_student'] = studentLocalMutualResult;
    report['3_student_drags_mutual_remote_teacher'] = teacherRemoteMutualResult;

    console.log('Result Student Local (Mutual):', JSON.stringify(studentLocalMutualResult, null, 2));
    console.log('Result Teacher Remote (Mutual):', JSON.stringify(teacherRemoteMutualResult, null, 2));

    // Save final report artifact
    const artifactPath = path.join(ARTIFACTS_DIR, 'role_asymmetry_matrix_results.json');
    fs.writeFileSync(artifactPath, JSON.stringify(report, null, 2), 'utf-8');
    console.log(`\nSuccessfully wrote diagnostic artifact to: ${artifactPath}`);

  } finally {
    await browser.close();
  }
}

run().catch((err) => {
  console.error('Benchmark runner error:', err);
  process.exit(1);
});
