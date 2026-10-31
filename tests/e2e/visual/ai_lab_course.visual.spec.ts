import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { runGeometryAudit } from './geometry-audit';

const storageState = process.env.BOOSTUDY_VISUAL_STORAGE_STATE;
const hasStorageState = Boolean(storageState && fs.existsSync(storageState));
if (hasStorageState) test.use({ storageState });

const viewports = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'desktop-1280', width: 1280, height: 800 },
  { name: 'tablet-1024', width: 1024, height: 768 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'mobile-390', width: 390, height: 844 },
];

test.describe('BooStudy AI Lab product responsive checks', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'Responsive viewport loop runs once on Chromium.');
    test.skip(!hasStorageState, 'Set BOOSTUDY_VISUAL_STORAGE_STATE to an authorized local admin session.');
  });

  test('AI Course history cards do not overlap or escape their panel', async ({ page }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });

    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/admin/ai-lab/course', { waitUntil: 'networkidle' });
      await page.addStyleTag({ content: '#qa-widget-trigger-btn{display:none!important}' });
      await expect(page.getByRole('heading', { name: 'Анализ учебного курса' })).toBeVisible();
      await expect(page.locator('.ac-history').first()).toBeVisible();

      const geometry = await page.locator('.ac-history').evaluateAll((cards) => cards.map((card) => {
        const rect = card.getBoundingClientRect();
        const action = card.querySelector('.ac-button')?.getBoundingClientRect();
        const next = card.nextElementSibling?.classList.contains('ac-history')
          ? card.nextElementSibling.getBoundingClientRect()
          : null;
        return {
          cardBottom: rect.bottom,
          actionBottom: action?.bottom ?? null,
          cardLeft: rect.left,
          cardRight: rect.right,
          actionLeft: action?.left ?? null,
          actionRight: action?.right ?? null,
          nextTop: next?.top ?? null,
          clientWidth: (card as HTMLElement).clientWidth,
          scrollWidth: (card as HTMLElement).scrollWidth,
        };
      }));

      expect(geometry.length).toBeGreaterThan(0);
      for (const card of geometry) {
        if (card.actionBottom !== null) expect(card.actionBottom).toBeLessThanOrEqual(card.cardBottom + 1);
        if (card.actionLeft !== null) expect(card.actionLeft).toBeGreaterThanOrEqual(card.cardLeft - 1);
        if (card.actionRight !== null) expect(card.actionRight).toBeLessThanOrEqual(card.cardRight + 1);
        if (card.nextTop !== null) expect(card.nextTop).toBeGreaterThanOrEqual(card.cardBottom - 1);
        expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth + 1);
      }

      const pageWidth = await page.evaluate(() => ({
        viewport: document.documentElement.clientWidth,
        content: document.documentElement.scrollWidth,
      }));
      expect(pageWidth.content).toBeLessThanOrEqual(pageWidth.viewport + 1);
      const report = await runGeometryAudit(page, '/admin/ai-lab/course');
      expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toHaveLength(0);
      fs.mkdirSync('artifacts/visual/ai-lab', { recursive: true });
      await page.screenshot({ path: `artifacts/visual/ai-lab/ai-course-${viewport.name}.png`, fullPage: true });
    }

    for (const route of [
      { path: '/admin/ai-lab/lesson-intelligence', heading: 'Интеллект урока' },
      { path: '/admin/ai-lab/studio', heading: 'AI Homework Studio' },
    ]) {
      for (const viewport of [viewports[0], viewports[3], viewports[4]]) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.goto(route.path, { waitUntil: 'networkidle' });
        await page.addStyleTag({ content: '#qa-widget-trigger-btn{display:none!important}' });
        await expect(page.getByRole('heading', { name: route.heading })).toBeVisible();
        const width = await page.evaluate(() => ({
          viewport: document.documentElement.clientWidth,
          content: document.documentElement.scrollWidth,
        }));
        expect(width.content).toBeLessThanOrEqual(width.viewport + 1);
        const report = await runGeometryAudit(page, route.path);
        expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toHaveLength(0);
      }
    }

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
