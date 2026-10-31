import { expect, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const lessonId = 2168;
const lessonRoomUrl = `/lesson/${lessonId}/room`;

test('DEBUG VFS CREATE', async ({ page }) => {
  page.on('console', msg => console.log('[Browser console]', msg.type(), msg.text()));

  await page.goto('/login');
  await page.fill('input[name="username"]', tutorUsername);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/login/, { timeout: 10000, waitUntil: 'domcontentloaded' }).catch(() => {});

  await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#code-window')).toBeVisible({ timeout: 20_000 });

  // Check state before
  const before = await page.evaluate(() => {
    return {
      openTabs: (window as any).openTabs,
      virtualFS: Object.keys((window as any).virtualFS || {}),
      deletedFiles: Array.from((window as any).deletedFileNames || []),
      tabsHTML: document.getElementById('editor-tabs-list')?.innerHTML
    };
  });
  console.log('BEFORE CREATE:', before);

  // Click add btn
  await page.click('#editor-tabs-add-btn');
  await expect(page.locator('#lesson-vfs-new-file-modal')).toBeVisible();

  await page.fill('#lesson-vfs-new-filename-input', 'solution_2.py');
  await page.click('#lesson-vfs-new-file-card button:has-text("Создать")');

  // Immediately check state
  const immediately = await page.evaluate(() => {
    return {
      openTabs: (window as any).openTabs,
      virtualFS: Object.keys((window as any).virtualFS || {}),
      deletedFiles: Array.from((window as any).deletedFileNames || []),
      tabsHTML: document.getElementById('editor-tabs-list')?.innerHTML
    };
  });
  console.log('IMMEDIATELY AFTER CREATE:', immediately);

  await page.waitForTimeout(1000);

  const after1s = await page.evaluate(() => {
    return {
      openTabs: (window as any).openTabs,
      virtualFS: Object.keys((window as any).virtualFS || {}),
      deletedFiles: Array.from((window as any).deletedFileNames || []),
      tabsHTML: document.getElementById('editor-tabs-list')?.innerHTML
    };
  });
  console.log('AFTER 1 SECOND:', after1s);
});
