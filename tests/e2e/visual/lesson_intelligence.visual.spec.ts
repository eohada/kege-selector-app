import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { runGeometryAudit } from './geometry-audit';

const sizes = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1366', width: 1366, height: 768 },
  { name: 'tablet-1024', width: 1024, height: 768 },
  { name: 'mobile-390', width: 390, height: 844 },
];

const storageState = process.env.BOOSTUDY_VISUAL_STORAGE_STATE;
const hasStorageState = Boolean(storageState && fs.existsSync(storageState));
if (hasStorageState) test.use({ storageState });

test.describe('AI Lesson Intelligence responsive review', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'Responsive audit runs once on desktop Chromium.');
    test.skip(!hasStorageState, 'Set BOOSTUDY_VISUAL_STORAGE_STATE to an authorized local admin session.');
  });

  test('manual review and transcript panels fit supported viewport sizes', async ({ page }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });

    for (const size of sizes) {
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.goto('/admin/ai-lab/lesson-intelligence', { waitUntil: 'networkidle' });
      await expect(page.getByRole('heading', { name: 'Интеллект урока' })).toBeVisible();
      await expect(page.locator('#li-transcript')).toBeVisible();
      const dimensions = await page.evaluate(() => ({
        viewport: document.documentElement.clientWidth,
        content: document.documentElement.scrollWidth,
      }));
      expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1);

      const report = await runGeometryAudit(page, '/admin/ai-lab/lesson-intelligence');
      expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toHaveLength(0);
      fs.mkdirSync('artifacts/visual/ai-lab/lesson-intelligence', { recursive: true });
      await page.screenshot({
        path: `artifacts/visual/ai-lab/lesson-intelligence/${size.name}.png`,
        fullPage: true,
      });
    }
    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
