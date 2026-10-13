import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { runGeometryAudit } from './geometry-audit';

const viewports = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1366', width: 1366, height: 768 },
  { name: 'tablet-1024', width: 1024, height: 768 },
  { name: 'mobile-390', width: 390, height: 844 },
];
const storageState = process.env.BOOSTUDY_VISUAL_STORAGE_STATE;
if (storageState && fs.existsSync(storageState)) test.use({ storageState });

test.describe('BooStudy dashboard visual harness', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'Dashboard visual harness runs once per viewport on desktop Chromium.');
  });

  for (const viewport of viewports) {
    test(`${viewport.name} screenshot and geometry`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/dashboard', { waitUntil: 'networkidle' });
      expect(new URL(page.url()).pathname).toBe('/dashboard');
      const report = await runGeometryAudit(page, '/dashboard');
      expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toHaveLength(0);
      fs.mkdirSync('artifacts/visual/dashboard', { recursive: true });
      await page.screenshot({ path: `artifacts/visual/dashboard/${viewport.name}.png`, fullPage: true });
    });
  }
});
