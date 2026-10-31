import { expect, test } from '@playwright/test';
import { execSync } from 'child_process';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const lessonId = 2168;
const lessonRoomUrl = `/lesson/${lessonId}/room`;

async function login(page: any, username: string) {
  await page.context().clearCookies();
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
}

test('Inspect 2-browser tab creation', async ({ browser }) => {
  const teacherContext = await browser.newContext();
  const teacherPage = await teacherContext.newPage();
  await login(teacherPage, tutorUsername);

  const studentContext = await browser.newContext();
  const studentPage = await studentContext.newPage();
  await login(studentPage, studentUsername);

  await teacherPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
  await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

  await studentPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
  await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

  console.log('Teacher tabs BEFORE:', await teacherPage.evaluate(() => (window as any).openTabs));
  console.log('Student tabs BEFORE:', await studentPage.evaluate(() => (window as any).openTabs));

  // Teacher clicks '+' button
  await teacherPage.click('#editor-tabs-add-btn');
  await expect(teacherPage.locator('#lesson-vfs-new-file-modal')).toBeVisible();
  await teacherPage.fill('#lesson-vfs-new-filename-input', 'solution_2.py');
  await teacherPage.click('#lesson-vfs-new-file-card button:has-text("Создать")');

  await teacherPage.waitForTimeout(500);

  console.log('Teacher tabs AFTER CREATE:', await teacherPage.evaluate(() => (window as any).openTabs));
  console.log('Student tabs AFTER CREATE:', await studentPage.evaluate(() => (window as any).openTabs));

  console.log('Teacher active file:', await teacherPage.evaluate(() => (window as any).activeFileName));
  console.log('Student active file:', await studentPage.evaluate(() => (window as any).activeFileName));

  // Now student clicks solution_2.py
  console.log('Student clicking solution_2.py tab...');
  await studentPage.evaluate(() => {
    (window as any).switchEditorTab(null, 'solution_2.py');
  });

  await studentPage.waitForTimeout(1000);

  console.log('Teacher tabs AFTER STUDENT CLICK:', await teacherPage.evaluate(() => (window as any).openTabs));
  console.log('Student tabs AFTER STUDENT CLICK:', await studentPage.evaluate(() => (window as any).openTabs));

  console.log('Teacher active file AFTER:', await teacherPage.evaluate(() => (window as any).activeFileName));
  console.log('Student active file AFTER:', await studentPage.evaluate(() => (window as any).activeFileName));
});
