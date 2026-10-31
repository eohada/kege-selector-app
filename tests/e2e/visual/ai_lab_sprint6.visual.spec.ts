import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { runGeometryAudit } from './geometry-audit';

const storageState = process.env.BOOSTUDY_VISUAL_STORAGE_STATE;
const hasStorageState = Boolean(storageState && fs.existsSync(storageState));
if (hasStorageState) test.use({ storageState });

const routes = [
  { path: '/admin/ai-lab/studio', heading: 'AI Homework Studio' },
  { path: '/admin/ai-lab/course', heading: 'Анализ учебного курса' },
  { path: '/admin/ai-lab/lesson-intelligence', heading: 'Интеллект урока' },
  { path: '/admin/ai-lab/analytics', heading: 'Аналитика обучения' },
  { path: '/admin/ai-lab/practice', heading: 'Следующая практика' },
];

const viewports = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1366', width: 1366, height: 768 },
  { name: 'tablet-1024', width: 1024, height: 768 },
  { name: 'mobile-390', width: 390, height: 844 },
];

test.describe('BooStudy AI Lab Sprint 6 module UI', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'The route and viewport matrix runs once on desktop Chromium.');
    test.skip(!hasStorageState, 'Set BOOSTUDY_VISUAL_STORAGE_STATE to an authorized local admin session.');
  });

  test('all five modules render without horizontal overflow or geometry failures', async ({ page }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });

    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      for (const route of routes) {
        const response = await page.goto(route.path, { waitUntil: 'networkidle' });
        expect(response?.status(), `${route.path} should load successfully`).toBe(200);
        expect(new URL(page.url()).pathname).toBe(route.path);
        await expect(page.getByRole('heading', { name: route.heading, level: 1 })).toBeVisible();

        const dimensions = await page.evaluate(() => ({
          viewport: document.documentElement.clientWidth,
          content: document.documentElement.scrollWidth,
        }));
        expect(dimensions.content, `${route.path} at ${viewport.name}`).toBeLessThanOrEqual(dimensions.viewport + 1);

        const report = await runGeometryAudit(page, route.path);
        expect(report.findings.filter((finding) => finding.severity === 'FAIL'), `${route.path} at ${viewport.name}`).toHaveLength(0);

        if (viewport.width === 1440 || viewport.width === 390) {
          const routeName = route.path.split('/').at(-1);
          fs.mkdirSync('artifacts/visual/ai-lab-sprint6', { recursive: true });
          await page.screenshot({
            path: `artifacts/visual/ai-lab-sprint6/${routeName}-${viewport.name}.png`,
            fullPage: true,
          });
        }
      }
    }

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
