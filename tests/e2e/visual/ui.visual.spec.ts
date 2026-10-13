import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { runGeometryAudit } from './geometry-audit';

const viewports = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1366', width: 1366, height: 768 },
  { name: 'tablet-1024', width: 1024, height: 768 },
  { name: 'mobile-390', width: 390, height: 844 },
];

test.describe('BooStudy UI showcase', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'Visual showcase runs once per viewport on desktop Chromium.');
  });

  for (const viewport of viewports) {
    test(`${viewport.name} screenshot and geometry`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/dev/ui', { waitUntil: 'networkidle' });
      await expect(page).toHaveTitle(/BooStudy UI Showcase/);
      const report = await runGeometryAudit(page, '/dev/ui');
      expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toHaveLength(0);
      fs.mkdirSync('artifacts/visual/ui', { recursive: true });
      await page.screenshot({ path: `artifacts/visual/ui/${viewport.name}.png`, fullPage: true });
    });
  }
});
