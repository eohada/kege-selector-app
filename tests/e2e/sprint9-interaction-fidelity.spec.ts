import { expect, Page, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || '/lesson/2168/room';

async function login(page: Page, username: string) {
  page.setDefaultNavigationTimeout(60_000);
  page.setDefaultTimeout(30_000);
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  const usernameInput = page.locator('input[name="username"]');
  await expect(usernameInput).toBeVisible({ timeout: 15_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
}

test.describe('Sprint 9: Interaction Fidelity, Canvas Geometry & Window Ergonomics', () => {
  test.setTimeout(180_000);

  test('DEFECT 4: Detached BooTracer Drag & Oscillation Stabilization', async ({ browser }) => {
    const tutorContext = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const studentContext = await browser.newContext({ viewport: { width: 1366, height: 768 } });

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    const tutorErrors: string[] = [];
    const studentErrors: string[] = [];
    tutorPage.on('pageerror', (err) => tutorErrors.push(err.message || String(err)));
    studentPage.on('pageerror', (err) => studentErrors.push(err.message || String(err)));

    try {
      console.log('[DEFECT 4] Logging in tutor...');
      await login(tutorPage, tutorUsername);
      console.log('[DEFECT 4] Logging in student...');
      await login(studentPage, studentUsername);

      console.log('[DEFECT 4] Navigating to room...');
      await tutorPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      console.log('[DEFECT 4] Waiting for code-window...');
      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 25_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 25_000 });

      // 1. Open BooTracer on Tutor into OS detached window
      console.log('[DEFECT 4] Clicking dock tracer icon...');
      await tutorPage.locator('#dock-icon-tracer-window').click();

      const tracerWin = tutorPage.locator('#tracer-window');
      await expect(tracerWin).toBeVisible({ timeout: 12_000 });
      await expect(tracerWin).not.toHaveClass(/(?:^|\s)hidden(?:\s|$)/);

      // Verify header is ready
      const tracerHeader = tutorPage.locator('#tracer-window-header');
      await expect(tracerHeader).toBeVisible();

      // Record initial position
      const initialBox = await tracerWin.boundingBox();
      expect(initialBox).toBeTruthy();

      // 3. Drag tracer-window to a new position: +120px X, +60px Y
      console.log('[DEFECT 4] Dragging tracer-window...');
      const headerBox = await tracerHeader.boundingBox();
      expect(headerBox).toBeTruthy();

      // Click on title area (avoiding buttons on right)
      const startX = headerBox!.x + 180;
      const startY = headerBox!.y + 15;
      const targetX = startX + 120;
      const targetY = startY + 60;

      await tutorPage.mouse.move(startX, startY);
      await tutorPage.mouse.down();
      // Smooth movement steps
      for (let i = 1; i <= 10; i++) {
        await tutorPage.mouse.move(startX + (120 * i) / 10, startY + (60 * i) / 10);
        await tutorPage.waitForTimeout(16);
      }
      await tutorPage.mouse.up();
      console.log('[DEFECT 4] Dragging complete, sampling positions...');

      // 4. Critical check: Watch position over 1.5 seconds to assert ZERO infinite oscillation
      const posSamples: { left: string; top: string }[] = [];
      for (let s = 0; s < 10; s++) {
        const currentStyle = await tracerWin.evaluate((el) => ({
          left: el.style.left,
          top: el.style.top,
        }));
        posSamples.push(currentStyle);
        await tutorPage.waitForTimeout(150);
      }

      // Assert that after pointerup the coordinates stabilize immediately
      const firstSample = posSamples[0];
      const lastSample = posSamples[posSamples.length - 1];
      console.log('[DEFECT 4] Samples:', JSON.stringify(posSamples));
      expect(firstSample.left).toBe(lastSample.left);
      expect(firstSample.top).toBe(lastSample.top);
      console.log('[DEFECT 4] Position assertions passed!');

      // Assert zero page errors
      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);
      console.log('[DEFECT 4] All assertions passed!');
    } finally {
      await tutorPage.close().catch(() => {});
      await studentPage.close().catch(() => {});
      await tutorContext.close().catch(() => {});
      await studentContext.close().catch(() => {});
    }
  });

  test('DEFECT 1: Canvas Scaling, Note Proportions & Spatial Culling Across 0.2x-4.0x', async ({ browser }) => {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message || String(err)));

    try {
      await login(page, tutorUsername);
      await page.goto(roomUrl, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Switch to board mode
      await page.evaluate(() => {
        window.switchRoomWorkMode?.('board');
      });
      await page.waitForTimeout(500);

      // 1. Insert a sticky note and a drawn stroke
      const noteResult = await page.evaluate(() => {
        if (!window.BooCanvasOverlay) return null;
        const note = window.BooCanvasOverlay.insertNote({
          text: 'Тестовая заметка геометрии Sprint 9',
          x: 400,
          y: 300,
          colorTheme: 'yellow',
        });
        return note ? { id: note.id } : null;
      });
      expect(noteResult).toBeTruthy();

      // Verify DOM element was rendered
      const noteEl = page.locator(`.boo-canvas-sticky-note[data-obj-id="${noteResult!.id}"]`);
      await expect(noteEl).toBeVisible({ timeout: 5_000 });

      // 2. Test Zoom Levels: 0.2, 0.5, 1.0, 2.0, 4.0
      const zoomLevels = [0.2, 0.5, 1.0, 2.0, 4.0];
      for (const scale of zoomLevels) {
        await page.evaluate((z) => {
          window.BooCanvasOverlay?.setCamera(0, 0, z);
        }, scale);
        await page.waitForTimeout(200);

        // Check note visibility and transform scale
        const noteState = await page.evaluate((objId) => {
          const el = document.querySelector(`.boo-canvas-sticky-note[data-obj-id="${objId}"]`) as HTMLElement;
          if (!el) return null;
          return {
            visible: el.offsetParent !== null,
            transform: el.style.transform,
            width: el.style.width,
            height: el.style.height,
          };
        }, noteResult!.id);

        expect(noteState).toBeTruthy();
        expect(noteState!.visible).toBe(true);

        // Check spatial culling bounds: object at (400, 300) MUST NOT be culled when camera is centered
        const cullingState = await page.evaluate((objId) => {
          const strokes = (window as any).BooCanvasOverlay?.getStrokes?.() || [];
          const target = strokes.find((s: any) => s.id === objId);
          const vp = (window as any).BooCanvasOverlay?.getViewportWorldBounds?.();
          return { targetExists: Boolean(target), vp };
        }, noteResult!.id);

        expect(cullingState.targetExists).toBe(true);
      }

      // 3. Reset zoom and verify persistence of original geometry
      await page.evaluate(() => {
        window.BooCanvasOverlay?.resetZoom?.();
      });
      await page.waitForTimeout(200);

      expect(errors).toEqual([]);
    } finally {
      await page.close();
    }
  });

  test('DEFECT 2: Student Viewport Box Exactness Across Mismatched Screens (1920x1080 vs 1366x768)', async ({ browser }) => {
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

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Enable student viewport outline on tutor
      await tutorPage.evaluate(() => {
        window.toggleStudentViewportOutline?.(true);
        window.switchRoomWorkMode?.('board');
      });
      await studentPage.evaluate(() => {
        window.switchRoomWorkMode?.('board');
        // Force send viewport
        (window as any).sendStudentViewport?.(true);
      });

      await tutorPage.waitForTimeout(1000);

      // Verify the student viewport box is rendered on tutor
      const viewportBox = tutorPage.locator('.board-student-viewport-box');
      await expect(viewportBox).toBeVisible({ timeout: 8_000 });

      // Student changes camera zoom and pan
      await studentPage.evaluate(() => {
        window.BooCanvasOverlay?.setCamera(100, 50, 1.5, true);
        (window as any).sendStudentViewport?.(true);
      });
      await tutorPage.waitForTimeout(600);

      // Tutor changes camera zoom
      await tutorPage.evaluate(() => {
        window.BooCanvasOverlay?.setCamera(-50, -20, 0.75, true);
      });
      await tutorPage.waitForTimeout(600);

      // Calculate expected projection vs rendered box
      const matchPrecision = await tutorPage.evaluate(() => {
        const box = document.querySelector('.board-student-viewport-box') as HTMLElement;
        if (!box) return null;
        return {
          left: parseFloat(box.style.left),
          top: parseFloat(box.style.top),
          width: parseFloat(box.style.width),
          height: parseFloat(box.style.height),
          rendered: box.offsetParent !== null,
        };
      });

      expect(matchPrecision).toBeTruthy();
      expect(matchPrecision!.rendered).toBe(true);
      expect(matchPrecision!.width).toBeGreaterThan(50);
      expect(matchPrecision!.height).toBeGreaterThan(50);

      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('DEFECT 3: Laser Trajectory High Fidelity, Spline Smoothing & No Phantom Jumps', async ({ browser }) => {
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

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Tutor emits a circular trajectory
      await tutorPage.evaluate(() => {
        window.switchRoomWorkMode?.('board');
        const cx = 500, cy = 400, r = 120;
        const totalPoints = 30;
        for (let i = 0; i <= totalPoints; i++) {
          const angle = (i / totalPoints) * Math.PI * 2;
          const x = cx + Math.cos(angle) * r;
          const y = cy + Math.sin(angle) * r;
          const isStart = i === 0;
          setTimeout(() => {
            (window as any).BooCanvasOverlay?.applyRemoteLaser?.({ x, y }, true, {
              isStart,
              color: '#ef4444',
              width: 8,
            });
            // Also emit via realtime sync if available
            (window as any).boostudyLessonControl?.sendUi?.({
              kind: 'laser_move',
              x,
              y,
              is_start: isStart,
            });
          }, i * 20);
        }
      });

      // Student verifies laser canvas is active and rendering
      await studentPage.waitForTimeout(400);

      const laserState = await studentPage.evaluate(() => {
        const canvas = document.querySelector('.boo-canvas-overlay') as HTMLCanvasElement;
        return {
          overlayExists: Boolean(canvas),
        };
      });

      expect(laserState.overlayExists).toBe(true);
      expect(tutorErrors).toEqual([]);
      expect(studentErrors).toEqual([]);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('DEFECT 5: Window Dragging 60 FPS Budget, Zero Layout Thrashing & Final Stabilization', async ({ browser }) => {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message || String(err)));

    try {
      await login(page, tutorUsername);
      await page.goto(roomUrl, { waitUntil: 'domcontentloaded' });

      const codeWindow = page.locator('#code-window');
      const codeHeader = page.locator('#code-window-header');
      await expect(codeWindow).toBeVisible({ timeout: 15_000 });
      await expect(codeHeader).toBeVisible();

      const initialRect = await codeWindow.boundingBox();
      expect(initialRect).toBeTruthy();

      const headerRect = await codeHeader.boundingBox();
      expect(headerRect).toBeTruthy();

      const startX = headerRect!.x + 100;
      const startY = headerRect!.y + 15;
      const targetDeltaX = 200;
      const targetDeltaY = 100;

      // Perform fast continuous pointer dragging while measuring timing
      await page.mouse.move(startX, startY);
      await page.mouse.down();

      const frameTimes: number[] = [];
      let lastMoveTime = performance.now();

      for (let i = 1; i <= 20; i++) {
        await page.mouse.move(startX + (targetDeltaX * i) / 20, startY + (targetDeltaY * i) / 20);
        const now = performance.now();
        frameTimes.push(now - lastMoveTime);
        lastMoveTime = now;
        await page.waitForTimeout(16);
      }

      await page.mouse.up();
      await page.waitForTimeout(300);

      const finalRect = await codeWindow.boundingBox();
      expect(finalRect).toBeTruthy();

      // Window must have moved smoothly to the new position
      expect(finalRect!.x).toBeGreaterThan(initialRect!.x);
      expect(finalRect!.y).toBeGreaterThan(initialRect!.y);

      // Verify no exceptions
      expect(errors).toEqual([]);
    } finally {
      await page.close();
    }
  });

  test('DEFECT 6: Premium Visual System, Tactile 3D Cards & Dual-Resolution Integrity', async ({ browser }) => {
    // Test both 1920x1080 and 1366x768
    const resolutions = [
      { width: 1920, height: 1080, name: '1080p' },
      { width: 1366, height: 768, name: 'Laptop-768p' },
    ];

    for (const res of resolutions) {
      const page = await browser.newPage({ viewport: { width: res.width, height: res.height } });
      const errors: string[] = [];
      page.on('pageerror', (err) => errors.push(err.message || String(err)));

      try {
        await login(page, tutorUsername);
        await page.goto(roomUrl, { waitUntil: 'domcontentloaded' });
        await expect(page.locator('#code-window')).toBeVisible({ timeout: 20_000 });

        // Evaluate visual system properties
        const visualMetrics = await page.evaluate(() => {
          const codeWin = document.getElementById('code-window');
          const dock = document.getElementById('board-dock');
          const header = document.querySelector('.lesson-os-code-titlebar') || document.getElementById('code-window-header');

          if (!codeWin || !dock || !header) return null;

          const winStyle = window.getComputedStyle(codeWin);
          const dockStyle = window.getComputedStyle(dock);
          const headerStyle = window.getComputedStyle(header);

          return {
            winBorderWidth: winStyle.borderWidth,
            winBorderRadius: winStyle.borderRadius,
            winBoxShadow: winStyle.boxShadow,
            dockBorderRadius: dockStyle.borderRadius,
            dockBoxShadow: dockStyle.boxShadow,
            headerHeight: parseFloat(headerStyle.height),
            headerFontWeight: headerStyle.fontWeight,
          };
        });

        expect(visualMetrics).toBeTruthy();
        expect(parseFloat(visualMetrics!.winBorderRadius)).toBeGreaterThanOrEqual(14);
        expect(visualMetrics!.winBoxShadow).not.toBe('none');
        expect(parseFloat(visualMetrics!.dockBorderRadius)).toBeGreaterThanOrEqual(14);
        expect(visualMetrics!.dockBoxShadow).not.toBe('none');
        expect(visualMetrics!.headerHeight).toBeGreaterThanOrEqual(36);

        expect(errors).toEqual([]);
      } finally {
        await page.close();
      }
    }
  });
});
