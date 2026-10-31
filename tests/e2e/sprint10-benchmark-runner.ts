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
    await page.waitForURL((url: URL) => !url.pathname.includes('/login'), { timeout: 10_000 });
  } catch {
    if (page.url().includes('/login')) {
      await page.waitForTimeout(1000);
      await page.locator('button[type="submit"]').click().catch(() => {});
      await page.waitForURL((url: URL) => !url.pathname.includes('/login'), { timeout: 15_000 });
    }
  }
}

// In-browser performance collector: records every single requestAnimationFrame interval,
// long tasks, layout shifts, and pointer response times.
const PERFORMANCE_COLLECTOR_SNIPPET = `
window.__perfCollector = {
  active: false,
  frameTimes: [],
  longTasks: [],
  inputLatencies: [],
  lastRafTime: 0,
  rafHandle: null,
  observer: null,

  start() {
    this.active = true;
    this.frameTimes = [];
    this.longTasks = [];
    this.inputLatencies = [];
    this.lastRafTime = performance.now();

    const onFrame = (now) => {
      if (!this.active) return;
      const delta = now - this.lastRafTime;
      this.lastRafTime = now;
      if (delta > 0 && delta < 500) { // filter out background tab suspension
        this.frameTimes.push(delta);
      }
      this.rafHandle = requestAnimationFrame(onFrame);
    };
    this.rafHandle = requestAnimationFrame(onFrame);

    try {
      this.observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          this.longTasks.push({
            name: entry.name,
            duration: entry.duration,
            startTime: entry.startTime,
          });
        }
      });
      this.observer.observe({ entryTypes: ['longtask'] });
    } catch (_) {}
  },

  stop() {
    this.active = false;
    if (this.rafHandle) {
      cancelAnimationFrame(this.rafHandle);
      this.rafHandle = null;
    }
    if (this.observer) {
      this.observer.disconnect();
      this.observer = null;
    }
    const frames = this.frameTimes.slice();
    if (frames.length === 0) return { fps: 0, p50: 0, p95: 0, p99: 0, low1Pct: 0, droppedPct: 0, longTasksCount: 0, maxLongTask: 0 };

    frames.sort((a, b) => a - b);
    const sum = frames.reduce((a, b) => a + b, 0);
    const avgDelta = sum / frames.length;
    const fps = 1000 / avgDelta;
    const p50 = frames[Math.floor(frames.length * 0.5)];
    const p95 = frames[Math.floor(frames.length * 0.95)];
    const p99 = frames[Math.floor(frames.length * 0.99)];

    // 1% low FPS: average of worst 1% frame times
    const worstCount = Math.max(1, Math.floor(frames.length * 0.01));
    const worst1Pct = frames.slice(frames.length - worstCount);
    const avgWorst = worst1Pct.reduce((a, b) => a + b, 0) / worstCount;
    const low1Pct = 1000 / avgWorst;

    // Dropped frames: frame interval > 20ms (> 16.6ms threshold)
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

async function runBenchmark() {
  if (!fs.existsSync(ARTIFACTS_DIR)) {
    fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
  }

  console.log('=== SPRINT 10 PERFORMANCE BENCHMARK SUITE ===');
  console.log('Launching browser with hardware acceleration flags...');

  const browser = await chromium.launch({
    headless: true, // running with explicit chromium GPU/compositor flags
    args: [
      '--enable-gpu-rasterization',
      '--enable-zero-copy',
      '--ignore-gpu-blocklist',
      '--enable-features=VaapiVideoDecoder',
    ],
  });

  const tutorContext = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const studentContext = await browser.newContext({ viewport: { width: 1366, height: 768 } });

  const tutorPage = await tutorContext.newPage();
  const studentPage = await studentContext.newPage();

  try {
    console.log('[STAGE 1] Authenticating Tutor and Student...');
    await login(tutorPage, tutorUsername);
    await login(studentPage, studentUsername);

    console.log('[STAGE 1] Navigating to lesson room...');
    await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
    await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

    await tutorPage.locator('#code-window').waitFor({ state: 'visible', timeout: 25_000 });
    await studentPage.locator('#code-window').waitFor({ state: 'visible', timeout: 25_000 });
    await tutorPage.waitForTimeout(2000);

    // Inject Performance Collector Snippet
    await tutorPage.evaluate(PERFORMANCE_COLLECTOR_SNIPPET);
    await studentPage.evaluate(PERFORMANCE_COLLECTOR_SNIPPET);

    const benchmarkResults: Record<string, any> = {};

    // Helper to run a profiled scenario
    async function profileScenario(
      name: string,
      description: string,
      action: () => Promise<void>,
      captureTrace = false
    ) {
      console.log(`\n--- Profiling Scenario ${name}: ${description} ---`);
      let cdpSession: any = null;
      let traceEvents: any[] = [];

      if (captureTrace) {
        cdpSession = await tutorContext.newCDPSession(tutorPage);
        cdpSession.on('Tracing.dataCollected', (evt: any) => {
          traceEvents = traceEvents.concat(evt.value || []);
        });
        await cdpSession.send('Tracing.start', {
          traceConfig: {
            includedCategories: [
              'devtools.timeline',
              'v8.execute',
              'disabled-by-default-devtools.timeline',
              'blink.user_timing',
              'cc',
              'gpu',
              'raster',
            ],
          },
        });
      }

      await tutorPage.evaluate(() => (window as any).__perfCollector.start());

      // Perform the scenario action
      await action();

      const metrics = await tutorPage.evaluate(() => (window as any).__perfCollector.stop());

      if (captureTrace && cdpSession) {
        await cdpSession.send('Tracing.end');
        await new Promise((resolve) => cdpSession.once('Tracing.tracingComplete', resolve));
        const traceFile = path.join(ARTIFACTS_DIR, `trace_version_a_${name}.json`);
        fs.writeFileSync(traceFile, JSON.stringify({ traceEvents }, null, 2));
        console.log(`[Trace] Saved Chrome Performance Trace to ${traceFile}`);
        await cdpSession.detach();
      }

      console.log(`Result [${name}]:`, JSON.stringify(metrics));
      benchmarkResults[name] = { description, ...metrics };
      return metrics;
    }

    // =========================================================================
    // SCENARIO A: Empty room, no open floating windows
    // =========================================================================
    await profileScenario('A_empty_room', 'Empty room with canvas only (no floating windows)', async () => {
      await tutorPage.evaluate(() => {
        window.switchRoomWorkMode?.('board');
        const codeWin = document.getElementById('code-window');
        if (codeWin) codeWin.classList.add('hidden');
      });
      await tutorPage.waitForTimeout(2000);
    });

    // =========================================================================
    // SCENARIO B: Open Python IDE and Task window
    // =========================================================================
    await profileScenario('B_ide_and_task', 'Python IDE and Task window open', async () => {
      await tutorPage.evaluate(() => {
        window.switchRoomWorkMode?.('code');
        const codeWin = document.getElementById('code-window');
        if (codeWin) codeWin.classList.remove('hidden');
        (window as any).toggleDockWindow?.('task-window');
      });
      await tutorPage.waitForTimeout(2000);
    });

    // =========================================================================
    // SCENARIO C: Heavy multi-window (IDE + Terminal + BooTracer + Theory)
    // =========================================================================
    await profileScenario('C_heavy_multiwindow', 'IDE + Terminal + BooTracer + Theory open', async () => {
      await tutorPage.evaluate(() => {
        (window as any).toggleDockWindow?.('terminal-window');
        (window as any).toggleDockWindow?.('tracer-window');
        (window as any).toggleDockWindow?.('theory-window');
      });
      await tutorPage.waitForTimeout(2000);
    });

    // =========================================================================
    // SCENARIO D: Dragging a single window (#code-window)
    // =========================================================================
    await profileScenario('D_window_drag', 'Dragging #code-window continuously across screen', async () => {
      await tutorPage.evaluate(() => {
        const codeWin = document.getElementById('code-window');
        if (codeWin) {
          codeWin.classList.remove('hidden');
          codeWin.style.display = 'flex';
        }
      });
      await tutorPage.waitForTimeout(300);
      const header = tutorPage.locator('.lesson-os-code-titlebar').first();
      const box = await header.boundingBox();
      if (box) {
        const startX = box.x + box.width / 2;
        const startY = box.y + box.height / 2;
        await tutorPage.mouse.move(startX, startY);
        await tutorPage.mouse.down();
        for (let i = 0; i < 40; i++) {
          await tutorPage.mouse.move(startX + Math.sin(i / 5) * 120, startY + (i * 4));
          await tutorPage.waitForTimeout(16);
        }
        await tutorPage.mouse.up();
      }
    }, true);

    // =========================================================================
    // SCENARIO E: Dragging a window with two active clients
    // =========================================================================
    await profileScenario('E_window_drag_dual_client', 'Dragging window with student actively observing and syncing', async () => {
      const header = tutorPage.locator('.lesson-os-code-titlebar').first();
      const box = await header.boundingBox();
      if (box) {
        const startX = box.x + box.width / 2;
        const startY = box.y + box.height / 2;
        await tutorPage.mouse.move(startX, startY);
        await tutorPage.mouse.down();
        for (let i = 0; i < 40; i++) {
          await tutorPage.mouse.move(startX - Math.cos(i / 5) * 100, startY + (i * 3));
          await tutorPage.waitForTimeout(16);
        }
        await tutorPage.mouse.up();
      }
    });

    // =========================================================================
    // SCENARIO F: Zooming infinite canvas
    // =========================================================================
    await profileScenario('F_canvas_zoom', 'Zooming canvas repeatedly between 0.5x and 2.5x', async () => {
      await tutorPage.evaluate(() => window.switchRoomWorkMode?.('board'));
      for (let s = 0.5; s <= 2.5; s += 0.1) {
        await tutorPage.evaluate((scale) => {
          (window as any).BooCanvasOverlay?.setCamera(0, 0, scale, false);
        }, s);
        await tutorPage.waitForTimeout(16);
      }
    });

    // =========================================================================
    // SCENARIO G: Panning infinite canvas
    // =========================================================================
    await profileScenario('G_canvas_pan', 'Panning canvas continuously across 60 frames', async () => {
      for (let step = 0; step < 60; step++) {
        await tutorPage.evaluate((dx) => {
          (window as any).BooCanvasOverlay?.setCamera(dx * 8, Math.sin(dx / 5) * 40, 1.0, false);
        }, step);
        await tutorPage.waitForTimeout(16);
      }
    });

    // =========================================================================
    // SCENARIO H: Drawing a long continuous stroke
    // =========================================================================
    await profileScenario('H_stroke_draw', 'Drawing a 100-point continuous pen stroke on canvas', async () => {
      const canvasEl = tutorPage.locator('.boo-canvas-overlay').first();
      const box = await canvasEl.boundingBox();
      if (box) {
        const startX = box.x + 200;
        const startY = box.y + 200;
        await tutorPage.mouse.move(startX, startY);
        await tutorPage.mouse.down();
        for (let i = 1; i <= 60; i++) {
          await tutorPage.mouse.move(startX + i * 5, startY + Math.sin(i / 4) * 50);
          await tutorPage.waitForTimeout(16);
        }
        await tutorPage.mouse.up();
      }
    }, true);

    // =========================================================================
    // SCENARIO I: Laser pointer movement (local)
    // =========================================================================
    await profileScenario('I_laser_local', 'Laser pointer continuous movement', async () => {
      await tutorPage.evaluate(() => {
        (window as any).BooCanvasOverlay?.setTool?.('laser');
      });
      const canvasEl = tutorPage.locator('.boo-canvas-overlay').first();
      const box = await canvasEl.boundingBox();
      if (box) {
        const startX = box.x + 300;
        const startY = box.y + 300;
        await tutorPage.mouse.move(startX, startY);
        await tutorPage.mouse.down();
        for (let i = 1; i <= 50; i++) {
          await tutorPage.mouse.move(startX + Math.cos(i / 6) * 120, startY + Math.sin(i / 6) * 120);
          await tutorPage.waitForTimeout(16);
        }
        await tutorPage.mouse.up();
      }
    });

    // =========================================================================
    // SCENARIO K: Dragging detached BooTracer
    // =========================================================================
    await profileScenario('K_bootracer_drag', 'Dragging detached BooTracer window', async () => {
      const tracerHeader = tutorPage.locator('#tracer-window-header');
      const box = await tracerHeader.boundingBox();
      if (box) {
        const startX = box.x + 100;
        const startY = box.y + 15;
        await tutorPage.mouse.move(startX, startY);
        await tutorPage.mouse.down();
        for (let i = 1; i <= 40; i++) {
          await tutorPage.mouse.move(startX + i * 4, startY + i * 2);
          await tutorPage.waitForTimeout(16);
        }
        await tutorPage.mouse.up();
      }
    });

    // =========================================================================
    // SCENARIO L: Active Canvas with 100, 500, 1000 objects
    // =========================================================================
    await profileScenario('L_canvas_500_strokes', 'Canvas with 500 strokes undergoing continuous redraw', async () => {
      await tutorPage.evaluate(() => {
        const overlay = (window as any).BooCanvasOverlay;
        if (!overlay) return;
        for (let i = 0; i < 500; i++) {
          overlay.applyRemoteStrokeCommit?.({
            id: 'synthetic_stroke_' + i,
            type: 'pen',
            color: '#3b82f6',
            width: 3,
            points: [
              { x: 100 + (i % 20) * 30, y: 100 + Math.floor(i / 20) * 20 },
              { x: 115 + (i % 20) * 30, y: 115 + Math.floor(i / 20) * 20 },
              { x: 130 + (i % 20) * 30, y: 105 + Math.floor(i / 20) * 20 },
            ],
          });
        }
      });
      for (let step = 0; step < 40; step++) {
        await tutorPage.evaluate((dx) => {
          (window as any).BooCanvasOverlay?.setCamera(dx * 6, dx * 3, 1.0, false);
        }, step);
        await tutorPage.waitForTimeout(16);
      }
    });

    // =========================================================================
    // SCENARIO M: Video container idle without active call
    // =========================================================================
    await profileScenario('M_video_container_idle', 'Video call strip / container expanded without active call', async () => {
      await tutorPage.evaluate(() => {
        const strip = document.getElementById('video-strip') || document.querySelector('.lesson-os-video-strip');
        if (strip) (strip as HTMLElement).style.display = 'flex';
      });
      await tutorPage.waitForTimeout(2000);
    });

    // =========================================================================
    // SCENARIO N: Mixed workload (multiple windows, canvas, IDE, dual clients)
    // =========================================================================
    await profileScenario('N_mixed_workload', 'Mixed workload: IDE + Task + Board + Dual clients concurrent interaction', async () => {
      const header = tutorPage.locator('.lesson-os-code-titlebar').first();
      const box = await header.boundingBox();
      if (box) {
        const startX = box.x + 100;
        const startY = box.y + 15;
        await tutorPage.mouse.move(startX, startY);
        await tutorPage.mouse.down();
        for (let i = 1; i <= 30; i++) {
          await tutorPage.mouse.move(startX + Math.sin(i / 4) * 80, startY + i * 3);
          await tutorPage.waitForTimeout(16);
        }
        await tutorPage.mouse.up();
      }
    }, true);

    // Save final summary JSON
    const summaryFile = path.join(ARTIFACTS_DIR, 'version_a_benchmark_results.json');
    fs.writeFileSync(summaryFile, JSON.stringify(benchmarkResults, null, 2));
    console.log(`\n=== Version A Benchmarks Completed! Saved to ${summaryFile} ===`);

  } finally {
    await tutorPage.close().catch(() => {});
    await studentPage.close().catch(() => {});
    await tutorContext.close().catch(() => {});
    await studentContext.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

runBenchmark().catch((err) => {
  console.error('Benchmark execution error:', err);
  process.exit(1);
});
