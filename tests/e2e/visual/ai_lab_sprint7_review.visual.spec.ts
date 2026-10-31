import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { runGeometryAudit } from './geometry-audit';

const viewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'laptop', width: 1366, height: 768 },
  { name: 'tablet', width: 1024, height: 768 },
  { name: 'mobile', width: 390, height: 844 },
];

test('Sprint 8 Quality Review presents evidence and remains within the viewport', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium');
  await page.goto('/login');
  await page.locator('input[name="username"]').fill('sprint5-preview-admin');
  await page.locator('input[name="password"]').fill('preview-only');
  await page.getByRole('button', { name: /ВОЙТИ В СИСТЕМУ/i }).click();

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const response = await page.goto('/admin/ai-lab/quality-review', { waitUntil: 'networkidle' });
    expect(response?.status()).toBe(200);
    await expect(page.getByRole('heading', { name: 'Проверка сохранённых результатов', level: 1 })).toBeVisible();
    await expect(page.locator('.qr-stats article').first()).toContainText('10');
    await expect(page.locator('.qr-stats article').last()).toContainText('4');
    const dimensions = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth,
                                                   content: document.documentElement.scrollWidth }));
    expect(dimensions.content, viewport.name).toBeLessThanOrEqual(dimensions.viewport + 1);
    const report = await runGeometryAudit(page, 'quality-review');
    expect(report.findings.filter((finding) => finding.severity === 'FAIL'), viewport.name).toHaveLength(0);
    fs.mkdirSync('artifacts/visual/ai-lab-sprint8', { recursive: true });
    await page.screenshot({ path: `artifacts/visual/ai-lab-sprint8/review-sprint6-${viewport.name}.png`, fullPage: true });

    const sprint7 = await page.goto('/admin/ai-lab/quality-review?benchmark=sprint7&module=ai_homework&case_id=s7-classify-alternative-hybrid', { waitUntil: 'networkidle' });
    expect(sprint7?.status()).toBe(200);
    await expect(page.locator('.qr-stats article').first()).toContainText('12');
    await expect(page.getByRole('heading', { name: 's7-classify-alternative-hybrid' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Код ученика' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Сравнение оценок' })).toBeVisible();
    await expect(page.locator('.qr-score-strip')).toContainText('Code Judge');
    await expect(page.locator('.qr-criterion').first()).toBeVisible();
    const rawDetails = page.locator('details').filter({ hasText: 'Технические данные и исходный JSON' }).first();
    await expect(rawDetails).toBeVisible();
    await expect(rawDetails).not.toHaveAttribute('open', '');
    const sprint7Width = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth,
                                                     content: document.documentElement.scrollWidth }));
    expect(sprint7Width.content, `Sprint 7 ${viewport.name}`).toBeLessThanOrEqual(sprint7Width.viewport + 1);
    const sprint7Report = await runGeometryAudit(page, `quality-review-sprint8-${viewport.name}`);
    expect(sprint7Report.findings.filter((finding) => finding.severity === 'FAIL'), viewport.name).toHaveLength(0);
    if (viewport.name === 'mobile') {
      await page.screenshot({ path: 'artifacts/visual/ai-lab-sprint8/review-sprint7-mobile.png', fullPage: true });
    }
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/admin/ai-lab/quality-review?benchmark=sprint7&module=ai_course', { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Исходный материал курса' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Предлагаемое изменение' }).first()).toBeVisible();
  await page.goto('/admin/ai-lab/quality-review?benchmark=sprint7&module=ai_lesson_intelligence', { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Исходные реплики' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Конспект и наблюдения' })).toBeVisible();
});
