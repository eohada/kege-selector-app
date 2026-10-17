import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { runGeometryAudit } from './geometry-audit';

const storageState = process.env.BOOSTUDY_VISUAL_STORAGE_STATE;
const authenticated = Boolean(storageState && fs.existsSync(storageState));
if (authenticated) test.use({ storageState });

const viewports = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];

test('Code Judge solution and constructor fit supported viewports', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium' || !authenticated, 'Requires an authorized local admin session.');
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto('/admin/ai-lab/code-judge', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: 'Code Judge', exact: true })).toBeVisible();
    await expect(page.locator('#cj-run')).toBeVisible();
    let report = await runGeometryAudit(page, '/admin/ai-lab/code-judge/solution');
    expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toEqual([]);
    if (viewport.width >= 1280) {
      const visible = await page.evaluate(() => {
        const editor = document.querySelector('#cj-editor-panel')!.getBoundingClientRect();
        const result = document.querySelector('.cj-results-panel')!.getBoundingClientRect();
        return editor.bottom <= innerHeight && result.top < innerHeight;
      });
      expect(visible).toBe(true);
    }
    await page.getByRole('tab', { name: 'Конструктор' }).click();
    await expect(page.locator('#cj-test-list')).toBeVisible();
    report = await runGeometryAudit(page, '/admin/ai-lab/code-judge/constructor');
    expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toEqual([]);
    await page.getByRole('tab', { name: 'Решение' }).click();
  }
});
