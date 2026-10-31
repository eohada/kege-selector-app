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

// In-browser performance probe that tracks frame intervals via requestAnimationFrame
// AND tracks DOM input latency & Long Tasks via PerformanceObserver
const DIAG_PROBE_SNIPPET = `
window.__diagProbe = {
  active: false,
  frameTimes: [],
  longTasks: [],
  lastRafTime: 0,
  rafHandle: null,
  observer: null,

  start() {
    this.active = true;
    this.frameTimes = [];
    this.longTasks = [];
    this.lastRafTime = performance.now();

    try {
      this.observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.entryType === 'longtask') {
            this.longTasks.push({
              startTime: entry.startTime,
              duration: entry.duration,
              name: entry.name,
            });
          }
        }
      });
      this.observer.observe({ entryTypes: ['longtask'] });
    } catch (_) {}

    const onFrame = (now) => {
      if (!this.active) return;
      const delta = now - this.lastRafTime;
      this.lastRafTime = now;
      if (delta > 0 && delta < 1000) {
        this.frameTimes.push(delta);
      }
      this.rafHandle = requestAnimationFrame(onFrame);
    };
    this.rafHandle = requestAnimationFrame(onFrame);
  },

  stop() {
    this.active = false;
    if (this.rafHandle) cancelAnimationFrame(this.rafHandle);
    if (this.observer) this.observer.disconnect();

    const frames = [...this.frameTimes];
    if (frames.length < 2) {
      return { frameCount: frames.length, fps: 0, p50: 0, p95: 0, p99: 0, low1Pct: 0, droppedPct: 0, longTasksCount: 0, maxLongTask: 0 };
    }

    frames.sort((a, b) => a - b);
    const totalDuration = this.frameTimes.reduce((acc, d) => acc + d, 0);
    const fps = (this.frameTimes.length / totalDuration) * 1000;

    const p50 = frames[Math.floor(frames.length * 0.50)];
    const p95 = frames[Math.floor(frames.length * 0.95)];
    const p99 = frames[Math.floor(frames.length * 0.99)];

    const worstCount = Math.max(1, Math.floor(frames.length * 0.01));
    const worstFrames = frames.slice(frames.length - worstCount);
    const avgWorstFrameTime = worstFrames.reduce((a, b) => a + b, 0) / worstCount;
    const low1Pct = avgWorstFrameTime > 0 ? 1000 / avgWorstFrameTime : 0;

    const dropped = frames.filter((f) => f > 20).length;
    const droppedPct = (dropped / frames.length) * 100;

    const longTasksCount = this.longTasks.length;
    const maxLongTask = longTasksCount > 0 ? Math.max(...this.longTasks.map(t => t.duration)) : 0;

    return {
      frameCount: frames.length,
      fps: Math.round(fps * 10) / 10,
      p50: Math.round(p50 * 100) / 100,
      p95: Math.round(p95 * 100) / 100,
      p99: Math.round(p99 * 100) / 100,
      low1Pct: Math.round(low1Pct * 10) / 10,
      droppedPct: Math.round(droppedPct * 10) / 10,
      longTasksCount,
      maxLongTask: Math.round(maxLongTask * 10) / 10,
    };
  }
};
`;

async function getEnvironmentProfile(page: any) {
  return await page.evaluate(() => {
    let unmaskedVendor = 'unknown';
    let unmaskedRenderer = 'unknown';
    try {
      const c = document.createElement('canvas');
      const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
      if (gl) {
        const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
        if (debugInfo) {
          unmaskedVendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
          unmaskedRenderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
        }
      }
    } catch (_) {}

    return {
      userAgent: navigator.userAgent,
      dpr: window.devicePixelRatio,
      screenW: window.screen.width,
      screenH: window.screen.height,
      availW: window.screen.availWidth,
      availH: window.screen.availHeight,
      colorDepth: window.screen.colorDepth,
      gpuVendor: unmaskedVendor,
      gpuRenderer: unmaskedRenderer,
      visibilityState: document.visibilityState,
      hardwareConcurrency: navigator.hardwareConcurrency,
    };
  });
}

async function performWindowDrag(page: any, steps = 60) {
  const header = page.locator('.lesson-os-code-titlebar').first();
  const box = await header.boundingBox();
  if (!box) return;

  const startX = box.x + 100;
  const startY = box.y + 15;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(startX + Math.sin(i / 5) * 150, startY + (i % 20) * 10);
    await page.waitForTimeout(16);
  }
  await page.mouse.up();
}

async function main() {
  if (!fs.existsSync(ARTIFACTS_DIR)) {
    fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
  }

  console.log('=== REAL ENVIRONMENT PERFORMANCE DIAGNOSTICS ===');
  console.log('Starting hardware-accelerated diagnostic suite on Windows 11...');

  const results: Record<string, any> = {};

  // 1. Launch browser in headed mode to bind to real Windows Desktop Window Manager (DWM)
  const browser = await chromium.launch({
    headless: false, // Headed mode: actual DWM presentation and VSync
    args: [
      '--enable-gpu-rasterization',
      '--enable-zero-copy',
      '--ignore-gpu-blocklist',
      '--window-size=1280,800',
    ],
  });

  try {
    // =========================================================================
    // SCENARIO A: 1 browser session, Monitor 1
    // =========================================================================
    console.log('\n[Scenario A] 1 session, Monitor 1...');
    const ctxA = await browser.newContext({ viewport: { width: 1280, height: 768 } });
    const pageA = await ctxA.newPage();
    await login(pageA, tutorUsername);
    await pageA.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await pageA.locator('#code-window').waitFor({ state: 'visible', timeout: 25_000 });
    await pageA.waitForTimeout(2000);

    const envInfo = await getEnvironmentProfile(pageA);
    console.log('[System GPU & Env Profile]:', JSON.stringify(envInfo, null, 2));
    results.envProfile = envInfo;

    await pageA.evaluate(DIAG_PROBE_SNIPPET);
    await pageA.evaluate(() => (window as any).__diagProbe.start());
    await performWindowDrag(pageA, 40);
    const metricsA = await pageA.evaluate(() => (window as any).__diagProbe.stop());
    console.log('[Result Scenario A]:', JSON.stringify(metricsA));
    results.scenarioA_single_client_mon1 = metricsA;
    await pageA.close();
    await ctxA.close();

    // =========================================================================
    // SCENARIO B: 2 sessions, both on Monitor 1
    // =========================================================================
    console.log('\n[Scenario B] 2 sessions, both on Monitor 1...');
    const ctxB_tutor = await browser.newContext({ viewport: { width: 1100, height: 750 } });
    const ctxB_student = await browser.newContext({ viewport: { width: 1100, height: 750 } });
    const pageB_tutor = await ctxB_tutor.newPage();
    const pageB_student = await ctxB_student.newPage();

    await login(pageB_tutor, tutorUsername);
    await login(pageB_student, studentUsername);
    await pageB_tutor.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await pageB_student.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await pageB_tutor.locator('#code-window').waitFor({ state: 'visible', timeout: 25_000 });
    await pageB_student.locator('#code-window').waitFor({ state: 'visible', timeout: 25_000 });
    await pageB_tutor.waitForTimeout(2000);

    await pageB_tutor.evaluate(DIAG_PROBE_SNIPPET);
    await pageB_tutor.evaluate(() => (window as any).__diagProbe.start());
    await performWindowDrag(pageB_tutor, 40);
    const metricsB = await pageB_tutor.evaluate(() => (window as any).__diagProbe.stop());
    console.log('[Result Scenario B]:', JSON.stringify(metricsB));
    results.scenarioB_dual_client_mon1 = metricsB;

    // =========================================================================
    // SCENARIO C: 2 sessions on Different Physical Monitors (Monitor 1 vs Monitor 2)
    // =========================================================================
    console.log('\n[Scenario C] 2 sessions across 2 physical monitors (Mon 1 @ 165Hz vs Mon 2 @ 144Hz)...');
    try {
      const studentBrowserMon2 = await chromium.launch({
        headless: false,
        args: [
          '--enable-gpu-rasterization',
          '--enable-zero-copy',
          '--ignore-gpu-blocklist',
          '--window-position=1950,50', // Positioned on DISPLAY2 (X=1920)
          '--window-size=1100,750',
        ],
      });
      const ctxC_student = await studentBrowserMon2.newContext({ viewport: { width: 1100, height: 750 } });
      const pageC_student = await ctxC_student.newPage();
      await login(pageC_student, studentUsername);
      await pageC_student.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await pageC_student.locator('#code-window').waitFor({ state: 'visible', timeout: 25_000 });
      await pageC_student.waitForTimeout(1500);

      await pageB_tutor.evaluate(() => (window as any).__diagProbe.start());
      await performWindowDrag(pageB_tutor, 40);
      const metricsC = await pageB_tutor.evaluate(() => (window as any).__diagProbe.stop());
      console.log('[Result Scenario C (Dual Physical Monitors)]: ', JSON.stringify(metricsC));
      results.scenarioC_dual_physical_monitors = metricsC;

      await pageC_student.close().catch(() => {});
      await ctxC_student.close().catch(() => {});
      await studentBrowserMon2.close().catch(() => {});
    } catch (errMon2) {
      console.warn('[Scenario C Warning]:', errMon2);
      results.scenarioC_dual_physical_monitors = { error: String(errMon2) };
    }

    // =========================================================================
    // SCENARIO D: 2 sessions, Only IDE open
    // =========================================================================
    console.log('\n[Scenario D] 2 sessions, Only IDE open...');
    await pageB_tutor.evaluate(() => {
      window.switchRoomWorkMode?.('code');
      ['terminal-window', 'tracer-window', 'theory-window', 'task-window'].forEach((w) => {
        const el = document.getElementById(w);
        if (el && !el.classList.contains('hidden')) (window as any).toggleDockWindow?.(w);
      });
    });
    await pageB_tutor.waitForTimeout(1000);
    await pageB_tutor.evaluate(() => (window as any).__diagProbe.start());
    await performWindowDrag(pageB_tutor, 40);
    const metricsD = await pageB_tutor.evaluate(() => (window as any).__diagProbe.stop());
    console.log('[Result Scenario D]:', JSON.stringify(metricsD));
    results.scenarioD_only_ide = metricsD;

    // =========================================================================
    // SCENARIO E: 2 sessions, IDE + Terminal + Tracer + Task + Board
    // =========================================================================
    console.log('\n[Scenario E] 2 sessions, Heavy Multiwindow (IDE + Terminal + Tracer + Task)...');
    await pageB_tutor.evaluate(() => {
      ['terminal-window', 'tracer-window', 'task-window'].forEach((w) => {
        const el = document.getElementById(w);
        if (el && el.classList.contains('hidden')) (window as any).toggleDockWindow?.(w);
      });
    });
    await pageB_tutor.waitForTimeout(1500);
    await pageB_tutor.evaluate(() => (window as any).__diagProbe.start());
    await performWindowDrag(pageB_tutor, 40);
    const metricsE = await pageB_tutor.evaluate(() => (window as any).__diagProbe.stop());
    console.log('[Result Scenario E]:', JSON.stringify(metricsE));
    results.scenarioE_heavy_multiwindow = metricsE;

    // =========================================================================
    // SCENARIO F: Drag without socket network broadcast (isolated drag cost)
    // =========================================================================
    console.log('\n[Scenario F] Drag with socket emissions temporarily suppressed...');
    await pageB_tutor.evaluate(() => {
      (window as any).__origSendUi = window.boostudyLessonControl?.sendUi;
      if (window.boostudyLessonControl) {
        window.boostudyLessonControl.sendUi = () => {};
      }
    });
    await pageB_tutor.evaluate(() => (window as any).__diagProbe.start());
    await performWindowDrag(pageB_tutor, 40);
    const metricsF = await pageB_tutor.evaluate(() => (window as any).__diagProbe.stop());
    console.log('[Result Scenario F]:', JSON.stringify(metricsF));
    results.scenarioF_local_drag_no_network = metricsF;
    await pageB_tutor.evaluate(() => {
      if (window.boostudyLessonControl && (window as any).__origSendUi) {
        window.boostudyLessonControl.sendUi = (window as any).__origSendUi;
      }
    });

    // =========================================================================
    // SCENARIO G: Drag with CDP Performance Tracing active (DevTools effect)
    // =========================================================================
    console.log('\n[Scenario G] Capturing Chrome Performance Trace during Drag (DevTools CDP active)...');
    const cdp = await ctxB_tutor.newCDPSession(pageB_tutor);
    let traceEvents: any[] = [];
    cdp.on('Tracing.dataCollected', (e: any) => {
      traceEvents = traceEvents.concat(e.value || []);
    });
    await cdp.send('Tracing.start', {
      traceConfig: {
        includedCategories: [
          'devtools.timeline',
          'v8.execute',
          'disabled-by-default-devtools.timeline',
          'cc',
          'gpu',
          'raster',
        ],
      },
    });

    await pageB_tutor.evaluate(() => (window as any).__diagProbe.start());
    await performWindowDrag(pageB_tutor, 40);
    const metricsG = await pageB_tutor.evaluate(() => (window as any).__diagProbe.stop());

    await cdp.send('Tracing.end');
    await new Promise((resolve) => cdp.once('Tracing.tracingComplete', resolve));
    const tracePath = path.join(ARTIFACTS_DIR, 'trace_diag_drag_monitors.json');
    fs.writeFileSync(tracePath, JSON.stringify({ traceEvents }, null, 2));
    console.log(`[Trace Saved]: ${tracePath}`);
    await cdp.detach();

    console.log('[Result Scenario G (with CDP/DevTools)]: ', JSON.stringify(metricsG));
    results.scenarioG_with_cdp_trace = metricsG;

    // =========================================================================
    // 5. Measure Synchronization Latency Chain (Round-Trip)
    // =========================================================================
    console.log('\n[Diagnostic 5] Measuring End-to-End Latency Chain across dual clients...');
    // Setup listener on student page
    await pageB_student.evaluate(() => {
      (window as any).__syncTimestamps = [];
      window.boostudyLessonSocket?.on('lesson_room_ui', (payload) => {
        if (payload?.kind === 'window_layout' && payload?._diag_id) {
          const t_recv = performance.now();
          requestAnimationFrame(() => {
            const t_rendered = performance.now();
            (window as any).__syncTimestamps.push({
              diag_id: payload._diag_id,
              t_client_emit: payload._diag_ts,
              t_server_updated_at: payload.updated_at,
              t_client_recv: t_recv,
              t_client_rendered: t_rendered,
            });
          });
        }
      });
    });

    // Tutor emits test window_layout with diag metadata
    const syncResults = await pageB_tutor.evaluate(async () => {
      const records = [];
      for (let i = 0; i < 10; i++) {
        const diag_id = 'diag_sync_' + i + '_' + Date.now();
        const t_emit = performance.now();
        window.boostudyLessonControl?.sendUi?.({
          kind: 'window_layout',
          window_id: 'code-window',
          left: 100 + i * 5,
          top: 100 + i * 5,
          _diag_id: diag_id,
          _diag_ts: t_emit,
        });
        await new Promise((r) => setTimeout(r, 60));
      }
      return true;
    });

    await pageB_tutor.waitForTimeout(1000);

    const studentSyncTimestamps = await pageB_student.evaluate(() => {
      return (window as any).__syncTimestamps || [];
    });
    console.log('[Diagnostic 5 Sync Timestamps Count]:', studentSyncTimestamps.length);
    results.syncLatencySamples = studentSyncTimestamps;

    await pageB_tutor.close();
    await pageB_student.close();
    await ctxB_tutor.close();
    await ctxB_student.close();

    // Save final report JSON
    const reportPath = path.join(ARTIFACTS_DIR, 'real_environment_diag_results.json');
    fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
    console.log(`\n=== All Diagnostics Completed! Saved to ${reportPath} ===`);

  } finally {
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error('Diagnostics error:', err);
  process.exit(1);
});
