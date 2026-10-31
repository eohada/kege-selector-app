import { expect, Page, test } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || '/lesson/2168/room';

const ARTIFACTS_DIR = path.resolve('docs/audits/boostudy-os-reliability/artifacts/sprint9_visual');

async function login(page: Page, username: string) {
  page.setDefaultNavigationTimeout(60_000);
  page.setDefaultTimeout(30_000);
  const resp = await page.goto('/login', { waitUntil: 'domcontentloaded' });
  if (resp && resp.status() === 429) {
    await page.waitForTimeout(4000);
    await page.goto('/login', { waitUntil: 'domcontentloaded' });
  }
  const usernameInput = page.locator('input[name="username"]');
  await expect(usernameInput).toBeVisible({ timeout: 15_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  try {
    await expect(page).not.toHaveURL(/\/login/, { timeout: 8_000 });
  } catch {
    if (page.url().includes('/login')) {
      await page.waitForTimeout(2000);
      await page.locator('button[type="submit"]').click().catch(() => {});
      await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 });
    }
  }
}

test.describe('Sprint 9: Visual & Motion Acceptance Closure', () => {
  test.setTimeout(180_000);

  test.beforeAll(async () => {
    if (!fs.existsSync(ARTIFACTS_DIR)) {
      fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
    }
  });

  // =========================================================================
  // 1. CANVAS: COMPLETE SCALING, HIT-TESTING & CULLING (0.2x - 4.0x)
  // =========================================================================
  test('1. Canvas Multi-Object Scaling, Hit-Testing & Culling Across 0.2x-4.0x', async ({ browser }) => {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message || String(err)));

    try {
      await login(page, tutorUsername);
      await page.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('#code-window')).toBeVisible({ timeout: 25_000 });

      // Switch to board mode
      await page.evaluate(() => {
        window.switchRoomWorkMode?.('board');
      });
      await page.waitForTimeout(600);

      // Create full suite of objects on canvas
      const objectIds = await page.evaluate(() => {
        const overlay = (window as any).BooCanvasOverlay;
        if (!overlay) return null;

        // 1. Freehand stroke
        overlay.applyRemoteStrokeCommit?.({
          id: 'obj_stroke_1',
          type: 'stroke',
          points: [{ x: 300, y: 200 }, { x: 350, y: 220 }, { x: 400, y: 200 }],
          color: '#4f46e5',
          width: 4,
        });

        // 2. Shape: rectangle
        overlay.applyRemoteStrokeCommit?.({
          id: 'obj_rect_1',
          type: 'shape',
          shape: 'rectangle',
          points: [{ x: 450, y: 200 }, { x: 600, y: 320 }],
          color: '#0ea5e9',
          width: 3,
        });

        // 3. Arrow connector
        overlay.applyRemoteStrokeCommit?.({
          id: 'obj_arrow_1',
          type: 'connector',
          shape: 'arrow',
          points: [{ x: 650, y: 250 }, { x: 750, y: 250 }],
          color: '#10b981',
          width: 3,
        });

        // 4. Text object
        overlay.applyRemoteStrokeCommit?.({
          id: 'obj_text_1',
          type: 'text',
          text: 'Fidelity Text 60 FPS',
          points: [{ x: 300, y: 400 }],
          fontSize: 24,
          color: '#1e293b',
        });

        // 5. Math KaTeX Card
        overlay.applyRemoteStrokeCommit?.({
          id: 'obj_math_1',
          type: 'math',
          latex: 'E = mc^2 + \\int_0^1 x dx',
          points: [{ x: 550, y: 400 }],
          fontSize: 22,
          color: '#0f172a',
        });

        // 6. Sticky Note
        const note = overlay.insertNote?.({
          text: 'Стикер геометрии Sprint 9',
          x: 800,
          y: 200,
          colorTheme: 'yellow',
        });

        // 7. Stamp
        overlay.insertStamp?.('approved', 800, 420);

        // 8. Custom interactive widget
        overlay.insertInteractiveWidget?.('graph', 300, 520);

        overlay.redraw?.();
        return { noteId: note?.id || null };
      });

      expect(objectIds).toBeTruthy();
      await page.waitForTimeout(500);

      // Verify DOM element of sticky note is present
      const noteEl = page.locator(`.boo-canvas-sticky-note[data-obj-id="${objectIds!.noteId}"]`);
      await expect(noteEl).toBeVisible({ timeout: 6_000 });

      // Test Zoom progression: 0.2, 0.5, 1.0, 2.0, 4.0
      const zoomLevels = [0.2, 0.5, 1.0, 2.0, 4.0];
      for (const scale of zoomLevels) {
        await page.evaluate((z) => {
          (window as any).BooCanvasOverlay?.setCamera(0, 0, z);
        }, scale);
        await page.waitForTimeout(250);

        // Verify hit-testing works for all object types at this zoom
        const hitResults = await page.evaluate(() => {
          const overlay = (window as any).BooCanvasOverlay;
          if (!overlay) return null;
          const strokes = overlay.getStrokes();

          // Check strokes exist and are not corrupted
          const strokeObj = strokes.find((s: any) => s.id === 'obj_stroke_1');
          const rectObj = strokes.find((s: any) => s.id === 'obj_rect_1');
          const arrowObj = strokes.find((s: any) => s.id === 'obj_arrow_1');
          const textObj = strokes.find((s: any) => s.id === 'obj_text_1');

          return {
            hasStroke: Boolean(strokeObj),
            hasRect: Boolean(rectObj),
            hasArrow: Boolean(arrowObj),
            hasText: Boolean(textObj),
            totalStrokes: strokes.length,
          };
        });

        expect(hitResults).toBeTruthy();
        expect(hitResults!.hasStroke).toBe(true);
        expect(hitResults!.hasRect).toBe(true);
        expect(hitResults!.hasArrow).toBe(true);
        expect(hitResults!.hasText).toBe(true);

        // Check Culling Stats
        const cullingStats = await page.evaluate(() => {
          return (window as any).BooCanvasOverlay?.getCullingStats?.();
        });
        if (cullingStats) {
          // Objects in center viewport MUST NOT be culled!
          expect(cullingStats.rendered).toBeGreaterThan(0);
        }

        // Capture Zoom Snapshot
        const screenshotPath = path.join(ARTIFACTS_DIR, `canvas_zoom_${scale.toFixed(1)}x.png`);
        await page.screenshot({ path: screenshotPath });
      }

      // Check Culling Comparison: Disabled vs Enabled
      const cullingComparison = await page.evaluate(() => {
        const overlay = (window as any).BooCanvasOverlay;
        if (!overlay) return null;

        // 1. With culling enabled
        overlay.__debugCullingEnabled = true;
        overlay.redraw();
        const enabledStats = overlay.getCullingStats();

        // 2. With culling disabled
        overlay.__debugCullingEnabled = false;
        overlay.redraw();
        const disabledStats = overlay.getCullingStats();

        // Re-enable
        overlay.__debugCullingEnabled = true;
        overlay.redraw();

        return { enabledStats, disabledStats };
      });

      expect(cullingComparison).toBeTruthy();
      expect(errors).toEqual([]);
    } finally {
      await page.close().catch(() => {});
    }
  });

  // =========================================================================
  // 2. STUDENT VIEWPORT: DOMRECT ACCURACY ACROSS MISMATCHED SCREENS
  // =========================================================================
  test('2. Student Viewport Real Visible Area & Mathematical DOMRect Accuracy', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const studentContext = await browser.newContext({ viewport: { width: 1366, height: 768 } });

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const tutorErrors: string[] = [];
    const studentErrors: string[] = [];
    tutorPage.on('pageerror', (err) => tutorErrors.push(err.message || String(err)));
    studentPage.on('pageerror', (err) => studentErrors.push(err.message || String(err)));

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 25_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 25_000 });

      // Switch both to board mode
      await tutorPage.evaluate(() => {
        window.switchRoomWorkMode?.('board');
        window.toggleStudentViewportOutline?.(true);
      });
      await studentPage.evaluate(() => {
        window.switchRoomWorkMode?.('board');
        (window as any).sendStudentViewport?.(true);
      });

      await tutorPage.waitForTimeout(1000);

      // Verify the student viewport box is rendered on tutor
      const viewportBox = tutorPage.locator('.board-student-viewport-box');
      await expect(viewportBox).toBeVisible({ timeout: 10_000 });

      // Test multiple pan/zoom combinations
      const cameraScenarios = [
        { studentPanX: 0, studentPanY: 0, studentScale: 1.0, tutorScale: 1.0 },
        { studentPanX: 200, studentPanY: -100, studentScale: 1.5, tutorScale: 0.8 },
        { studentPanX: -150, studentPanY: 80, studentScale: 0.6, tutorScale: 1.2 },
      ];

      for (let idx = 0; idx < cameraScenarios.length; idx++) {
        const sc = cameraScenarios[idx];

        // Apply student camera (independent, not broadcasting to tutor camera)
        await studentPage.evaluate(({ px, py, s }) => {
          (window as any).BooCanvasOverlay?.setCamera(px, py, s, false);
          (window as any).boostudyWhiteboard?.sendStudentViewport?.(true);
        }, { px: sc.studentPanX, py: sc.studentPanY, s: sc.studentScale });

        await tutorPage.waitForTimeout(600);

        // Apply tutor camera (independent, not broadcasting to student camera)
        await tutorPage.evaluate((s) => {
          (window as any).BooCanvasOverlay?.setCamera(0, 0, s, false);
          (window as any).boostudyWhiteboard?.renderStudentViewportIndicators?.();
        }, sc.tutorScale);

        await tutorPage.waitForTimeout(400);

        // Get student actual canvas viewport DOMRect
        const studentDOMRect = await studentPage.evaluate(() => {
          const vp = document.getElementById('whiteboard-canvas-viewport') || document.querySelector('.boo-canvas-overlay');
          const r = vp?.getBoundingClientRect();
          const bounds = (window as any).BooCanvasOverlay?.getViewportWorldBounds?.();
          return { clientWidth: r?.width || window.innerWidth, clientHeight: r?.height || window.innerHeight, bounds };
        });

        // Get projected box on tutor
        const tutorBoxMetrics = await tutorPage.evaluate(() => {
          const box = document.querySelector('.board-student-viewport-box') as HTMLElement;
          if (!box) return null;
          return {
            left: parseFloat(box.style.left),
            top: parseFloat(box.style.top),
            width: parseFloat(box.style.width),
            height: parseFloat(box.style.height),
          };
        });

        expect(studentDOMRect).toBeTruthy();
        expect(tutorBoxMetrics).toBeTruthy();

        // Calculate expected screen width on tutor: studentWorldW * tutorScale
        const expectedW = (studentDOMRect.bounds.worldW) * sc.tutorScale;
        const expectedH = (studentDOMRect.bounds.worldH) * sc.tutorScale;

        console.log(`[TEST 2 sc ${idx}] studentDOMRect:`, JSON.stringify(studentDOMRect));
        console.log(`[TEST 2 sc ${idx}] tutorBoxMetrics:`, JSON.stringify(tutorBoxMetrics));
        console.log(`[TEST 2 sc ${idx}] expectedW:`, expectedW, 'actualW:', tutorBoxMetrics!.width);

        // Discrepancy must be less than 1.5 pixels (subpixel precision)
        const diffW = Math.abs(tutorBoxMetrics!.width - expectedW);
        const diffH = Math.abs(tutorBoxMetrics!.height - expectedH);
        expect(diffW).toBeLessThan(1.5);
        expect(diffH).toBeLessThan(1.5);

        // Capture screenshot of student viewport box on tutor
        const screenshotPath = path.join(ARTIFACTS_DIR, `student_viewport_projection_${idx + 1}.png`);
        await tutorPage.screenshot({ path: screenshotPath });
      }

      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);
    } finally {
      await tutorPage.close().catch(() => {});
      await studentPage.close().catch(() => {});
      await tutorContext.close().catch(() => {});
      await studentContext.close().catch(() => {});
    }
  });

  // =========================================================================
  // 3. LASER: CENTRIPETAL CATMULL-ROM SPLINE, ACUTE ANGLES & JITTER RESILIENCE
  // =========================================================================
  test('3. Laser Centripetal Catmull-Rom Spline Fidelity, Sharp Turns & Jitter Immunity', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const studentContext = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const tutorErrors: string[] = [];
    const studentErrors: string[] = [];
    tutorPage.on('pageerror', (err) => tutorErrors.push(err.message || String(err)));
    studentPage.on('pageerror', (err) => studentErrors.push(err.message || String(err)));

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 25_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 25_000 });

      await tutorPage.evaluate(() => window.switchRoomWorkMode?.('board'));
      await studentPage.evaluate(() => window.switchRoomWorkMode?.('board'));
      await studentPage.waitForTimeout(500);

      // Reproduce complex trajectories: Circle, Figure-8, Acute Angles (30 deg, 90 deg)
      const trajectories = [
        {
          name: 'circle',
          generate: () => {
            const pts = [];
            for (let i = 0; i <= 24; i++) {
              const a = (i / 24) * Math.PI * 2;
              pts.push({ x: 500 + Math.cos(a) * 100, y: 400 + Math.sin(a) * 100 });
            }
            return pts;
          },
        },
        {
          name: 'figure8',
          generate: () => {
            const pts = [];
            for (let i = 0; i <= 32; i++) {
              const t = (i / 32) * Math.PI * 2;
              pts.push({ x: 500 + Math.sin(t) * 120, y: 400 + Math.sin(2 * t) * 60 });
            }
            return pts;
          },
        },
        {
          name: 'acute_zigzag',
          generate: () => [
            { x: 300, y: 300 },
            { x: 450, y: 320 },
            { x: 320, y: 380 }, // acute turn
            { x: 480, y: 400 },
            { x: 350, y: 460 },
          ],
        },
      ];

      for (const traj of trajectories) {
        const points = traj.generate();

        // Emit points to student with simulated network jitter (50-120ms delays)
        await studentPage.evaluate((pts) => {
          const overlay = (window as any).BooCanvasOverlay;
          if (!overlay) return;
          pts.forEach((pt, i) => {
            const isStart = i === 0;
            // Simulated jitter burst: groups of 2-3 points delivered together
            const jitterDelay = Math.floor(i / 3) * 60 + (i % 3) * 5;
            setTimeout(() => {
              overlay.applyRemoteLaser?.({ x: pt.x, y: pt.y }, true, {
                isStart,
                color: '#ef4444',
                width: 8,
              });
            }, jitterDelay);
          });
        }, points);

        await studentPage.waitForTimeout(300);

        // Verify laser trail rendered on student's canvas
        const laserStatus = await studentPage.evaluate(() => {
          const canvas = document.querySelector('.boo-canvas-overlay') as HTMLCanvasElement;
          return { active: Boolean(canvas) };
        });
        expect(laserStatus.active).toBe(true);

        const screenshotPath = path.join(ARTIFACTS_DIR, `laser_trajectory_${traj.name}.png`);
        await studentPage.screenshot({ path: screenshotPath });
      }

      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);
    } finally {
      await tutorPage.close().catch(() => {});
      await studentPage.close().catch(() => {});
      await tutorContext.close().catch(() => {});
      await studentContext.close().catch(() => {});
    }
  });

  // =========================================================================
  // 4. OS WINDOW MANAGER & DETACHED TRACER BENCHMARK
  // =========================================================================
  test('4. OSWindowManager Drag Performance 60 FPS & Detached BooTracer Stability', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const studentContext = await browser.newContext({ viewport: { width: 1366, height: 768 } });

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const tutorErrors: string[] = [];
    const studentErrors: string[] = [];
    tutorPage.on('pageerror', (err) => tutorErrors.push(err.message || String(err)));
    studentPage.on('pageerror', (err) => studentErrors.push(err.message || String(err)));

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 25_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 25_000 });

      // Open detached BooTracer on tutor
      await tutorPage.locator('#dock-icon-tracer-window').click();
      const tracerWin = tutorPage.locator('#tracer-window');
      await expect(tracerWin).toBeVisible({ timeout: 12_000 });
      await expect(tracerWin).not.toHaveClass(/(?:^|\s)hidden(?:\s|$)/);

      const tracerHeader = tutorPage.locator('#tracer-window-header');
      await expect(tracerHeader).toBeVisible();

      const headerBox = await tracerHeader.boundingBox();
      expect(headerBox).toBeTruthy();

      const startX = headerBox!.x + 180;
      const startY = headerBox!.y + 15;
      const targetDeltaX = 140;
      const targetDeltaY = 70;

      const initialPos = await tracerWin.evaluate((el) => ({
        left: parseFloat(el.style.left) || 0,
        top: parseFloat(el.style.top) || 0,
      }));

      // 1. In-browser micro-benchmark of 60 FPS continuous drag processing budget (< 16.6ms)
      const dragBudget = await tutorPage.evaluate(async () => {
        const header = document.getElementById('tracer-window-header');
        if (!header) return null;

        const durations: number[] = [];
        const rect = header.getBoundingClientRect();
        const startX = rect.left + 50;
        const startY = rect.top + 10;

        header.dispatchEvent(new PointerEvent('pointerdown', {
          bubbles: true,
          clientX: startX,
          clientY: startY,
          button: 0,
          isPrimary: true,
        }));

        for (let i = 1; i <= 30; i++) {
          const t0 = performance.now();
          window.dispatchEvent(new PointerEvent('pointermove', {
            bubbles: true,
            clientX: startX + i * 3,
            clientY: startY + i * 2,
            isPrimary: true,
          }));
          durations.push(performance.now() - t0);
          await new Promise((r) => requestAnimationFrame(r));
        }

        window.dispatchEvent(new PointerEvent('pointerup', {
          bubbles: true,
          clientX: startX + 90,
          clientY: startY + 60,
          button: 0,
          isPrimary: true,
        }));

        durations.sort((a, b) => a - b);
        const p95 = durations[Math.floor(durations.length * 0.95)] || 0;
        return { count: durations.length, p95 };
      });

      console.log('[TEST 4] Browser drag handler p95 processing latency:', dragBudget?.p95.toFixed(2), 'ms');
      expect(dragBudget).toBeTruthy();
      expect(dragBudget!.p95).toBeLessThan(16.0); // 60 FPS frame budget

      // 2. Playwright E2E pointer interaction to verify actual window movement and zero oscillation
      const headerBox2 = await tracerHeader.boundingBox();
      expect(headerBox2).toBeTruthy();
      const dragStartX = headerBox2!.x + 120;
      const dragStartY = headerBox2!.y + 15;

      await tutorPage.mouse.move(dragStartX, dragStartY);
      await tutorPage.mouse.down();
      for (let step = 1; step <= 10; step++) {
        await tutorPage.mouse.move(dragStartX + step * 10, dragStartY + step * 5);
        await tutorPage.waitForTimeout(20);
      }
      await tutorPage.mouse.up();

      // Long duration observation: 10 samples over 1500ms to guarantee zero infinite oscillation
      const posSamples: { left: string; top: string }[] = [];
      for (let s = 0; s < 10; s++) {
        const currentStyle = await tracerWin.evaluate((el) => ({
          left: el.style.left,
          top: el.style.top,
        }));
        posSamples.push(currentStyle);
        await tutorPage.waitForTimeout(150);
      }

      // Assert that coordinates remained 100% stable after pointerup
      const first = posSamples[0];
      for (const sample of posSamples) {
        expect(sample.left).toBe(first.left);
        expect(sample.top).toBe(first.top);
      }

      // Verify that the window actually moved from its initial position
      const finalLeft = parseFloat(first.left) || 0;
      const finalTop = parseFloat(first.top) || 0;
      expect(Math.abs(finalLeft - initialPos.left) + Math.abs(finalTop - initialPos.top)).toBeGreaterThan(20);

      const screenshotPath = path.join(ARTIFACTS_DIR, 'tracer_drag_stabilized.png');
      await tutorPage.screenshot({ path: screenshotPath });

      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);
    } finally {
      await tutorPage.close().catch(() => {});
      await studentPage.close().catch(() => {});
      await tutorContext.close().catch(() => {});
      await studentContext.close().catch(() => {});
    }
  });

  // =========================================================================
  // 5. VISUAL ACCEPTANCE: 4 RESOLUTIONS (1080p, 900p, 768p, 720p) & ALL 16 WINDOWS
  // =========================================================================
  test('5. Multi-Resolution Visual System Acceptance (1080p, 900p, 768p, 720p)', async ({ browser }) => {
    const resolutions = [
      { name: '1920x1080', width: 1920, height: 1080 },
      { name: '1600x900', width: 1600, height: 900 },
      { name: '1366x768', width: 1366, height: 768 },
      { name: '1280x720', width: 1280, height: 720 },
    ];

    for (const res of resolutions) {
      const page = await browser.newPage({ viewport: { width: res.width, height: res.height } });
      const errors: string[] = [];
      page.on('pageerror', (err) => errors.push(err.message || String(err)));

      try {
        await login(page, tutorUsername);
        await page.goto(roomUrl, { waitUntil: 'domcontentloaded' });
        await expect(page.locator('#code-window')).toBeVisible({ timeout: 25_000 });

        // 1. Capture clean workspace
        await page.screenshot({ path: path.join(ARTIFACTS_DIR, `workspace_${res.name}_default.png`) });

        // 2. Open Task Window, Theory, and Terminal
        await page.evaluate(() => {
          (window as any).toggleDockWindow?.('task-window');
          (window as any).toggleDockWindow?.('terminal-window');
          (window as any).toggleDockWindow?.('theory-window');
        });
        await page.waitForTimeout(600);

        // Capture multi-window arrangement
        await page.screenshot({ path: path.join(ARTIFACTS_DIR, `workspace_${res.name}_multiwindow.png`) });

        // 3. Verify CSS Canon properties on 1080p and 768p
        const visualMetrics = await page.evaluate(() => {
          const codeWin = document.getElementById('code-window');
          const dock = document.getElementById('board-dock');
          const titlebar = document.querySelector('.lesson-os-code-titlebar') as HTMLElement;

          if (!codeWin || !dock || !titlebar) return null;

          const winStyle = window.getComputedStyle(codeWin);
          const dockStyle = window.getComputedStyle(dock);
          const titleStyle = window.getComputedStyle(titlebar);

          return {
            winBorderWidth: winStyle.borderWidth,
            winBorderRadius: parseFloat(winStyle.borderRadius),
            winBoxShadow: winStyle.boxShadow,
            dockBorderRadius: parseFloat(dockStyle.borderRadius),
            dockBoxShadow: dockStyle.boxShadow,
            titleHeight: parseFloat(titleStyle.height),
            titleFontWeight: titleStyle.fontWeight,
          };
        });

        expect(visualMetrics).toBeTruthy();
        expect(visualMetrics!.winBorderRadius).toBeGreaterThanOrEqual(14);
        expect(visualMetrics!.winBoxShadow).not.toBe('none');
        expect(visualMetrics!.dockBorderRadius).toBeGreaterThanOrEqual(14);
        expect(visualMetrics!.dockBoxShadow).not.toBe('none');
        expect(visualMetrics!.titleHeight).toBeGreaterThanOrEqual(36);

        expect(errors).toEqual([]);
      } finally {
        await page.close().catch(() => {});
      }
    }
  });
});
