import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { runGeometryAudit } from './geometry-audit';

const viewports = [
  { name: 'desktop-1920', width: 1920, height: 1080 },
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1366', width: 1366, height: 768 },
  { name: 'compact-1280', width: 1280, height: 800 },
  { name: 'tablet-1024', width: 1024, height: 768 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'mobile-390', width: 390, height: 844 },
];

const storageState = process.env.BOOSTUDY_VISUAL_STORAGE_STATE;
const hasStorageState = Boolean(storageState && fs.existsSync(storageState));
if (hasStorageState) test.use({ storageState });

test.describe('BooStudy AI Lab visual QA', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'AI Lab viewport audit runs once on desktop Chromium.');
    test.skip(!hasStorageState, 'Set BOOSTUDY_VISUAL_STORAGE_STATE to an authorized local admin session.');
  });

  test('overview geometry at supported viewport sizes', async ({ page }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });

    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/admin/ai-lab', { waitUntil: 'networkidle' });
      expect(new URL(page.url()).pathname).toBe('/admin/ai-lab');
      await expect(page.getByRole('heading', { name: 'BooStudy AI Lab' })).toBeVisible();
      await expect(page.locator('.ai-lab-module')).toHaveCount(5);

      const report = await runGeometryAudit(page, '/admin/ai-lab');
      expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toHaveLength(0);
      fs.mkdirSync('artifacts/visual/ai-lab', { recursive: true });
      await page.screenshot({ path: `artifacts/visual/ai-lab/${viewport.name}.png`, fullPage: true });
    }

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });

  test('section links support keyboard navigation and show the active section', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/admin/ai-lab', { waitUntil: 'networkidle' });

    const experimentsTab = page.getByRole('link', { name: 'Эксперименты' });
    await experimentsTab.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/section=experiments/);
    await expect(page.getByRole('heading', { name: 'Центр экспериментов' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Эксперименты' })).toHaveAttribute('aria-current', 'page');

    await page.getByRole('link', { name: 'Модели' }).click();
    await expect(page.getByRole('heading', { name: 'Подключённые модели' })).toBeVisible();
    await expect(page.getByText(/Выключено: нужен локальный режим/)).toBeVisible();
  });

  test('all five sections render and stay within desktop and mobile viewports', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    const sections = [
      { key: 'overview', heading: 'BooStudy AI Lab', tab: 'Обзор' },
      { key: 'experiments', heading: 'Центр экспериментов', tab: 'Эксперименты' },
      { key: 'instructions', heading: 'Инструкции и правила', tab: 'Инструкции' },
      { key: 'models', heading: 'Подключённые модели', tab: 'Модели' },
      { key: 'history', heading: 'История экспериментов', tab: 'История' },
    ];
    const sizes = [
      { name: 'desktop', width: 1440, height: 900 },
      { name: 'mobile', width: 390, height: 844 },
    ];

    for (const size of sizes) {
      await page.setViewportSize({ width: size.width, height: size.height });
      for (const section of sections) {
        await page.goto(`/admin/ai-lab?section=${section.key}`, { waitUntil: 'networkidle' });
        await expect(page.getByRole('heading', { name: section.heading })).toBeVisible();
        await expect(page.getByRole('link', { name: section.tab })).toHaveAttribute('aria-current', 'page');

        const report = await runGeometryAudit(page, `/admin/ai-lab/${section.key}`);
        expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toHaveLength(0);
        fs.mkdirSync('artifacts/visual/ai-lab', { recursive: true });
        await page.screenshot({ path: `artifacts/visual/ai-lab/${section.key}-${size.name}.png`, fullPage: true });
      }
    }
    expect(consoleErrors).toEqual([]);
  });

  test('AI Homework Studio controls work and its layout fits desktop, tablet and mobile', async ({ page }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });

    const sizes = [
      { name: 'desktop', width: 1440, height: 1000 },
      { name: 'tablet', width: 768, height: 1024 },
      { name: 'mobile', width: 390, height: 844 },
    ];
    for (const size of sizes) {
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.goto('/admin/ai-lab/studio', { waitUntil: 'networkidle' });
      await expect(page.getByRole('heading', { name: 'AI Homework Studio' })).toBeVisible();
      await expect(page.locator('#hw-scenario option')).toHaveCount(15);
      await expect(page.locator('#hw-load-models')).toBeDisabled();
      await expect(page.locator('#hw-run')).toBeDisabled();

      const dimensions = await page.evaluate(() => ({
        viewport: document.documentElement.clientWidth,
        content: document.documentElement.scrollWidth,
      }));
      expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1);

      const report = await runGeometryAudit(page, '/admin/ai-lab/studio');
      expect(report.findings.filter((finding) => finding.severity === 'FAIL')).toHaveLength(0);
      fs.mkdirSync('artifacts/visual/ai-lab', { recursive: true });
      await page.screenshot({
        path: 'artifacts/visual/ai-lab/homework-studio-' + size.name + '.png',
        fullPage: true,
      });
    }

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto('/admin/ai-lab/studio', { waitUntil: 'networkidle' });
    await page.locator('#hw-scenario').selectOption('py-for-06');
    await expect(page.locator('#hw-case-type')).toHaveText('python');
    await expect(page.locator('#hw-solution')).toHaveValue(/range\(1, n \+ 1\)/);
    await page.getByRole('tab', { name: 'Технические данные' }).click();
    await expect(page.getByRole('tabpanel', { name: 'Технические данные' })).toBeVisible();
    await expect(page.getByRole('tabpanel', { name: 'Педагогический результат' })).toBeHidden();
    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
