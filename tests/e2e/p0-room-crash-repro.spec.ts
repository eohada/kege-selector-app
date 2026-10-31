import { expect, Page, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || '/lesson/2168/room';

async function login(page: Page, username: string) {
  await page.goto('/logout').catch(() => undefined);
  await page.goto('/login');
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/);
}

test('P0 REPRO: Reproduce ReferenceError applyControlState is not defined in joinLessonRooms', async ({ browser }) => {
  const tutorContext = await browser.newContext();
  const studentContext = await browser.newContext();

  const tutorPage = await tutorContext.newPage();
  const studentPage = await studentContext.newPage();

  const tutorPageErrors: string[] = [];
  const studentPageErrors: string[] = [];

  tutorPage.on('pageerror', (err) => {
    tutorPageErrors.push(err.message || String(err));
  });

  studentPage.on('pageerror', (err) => {
    studentPageErrors.push(err.message || String(err));
  });

  try {
    await login(tutorPage, tutorUsername);
    await login(studentPage, studentUsername);

    await tutorPage.goto(roomUrl);
    await studentPage.goto(roomUrl);

    await tutorPage.waitForLoadState('domcontentloaded');
    await studentPage.waitForLoadState('domcontentloaded');

    await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
    await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    // Wait 2 seconds for Socket.IO connect chain
    await tutorPage.waitForTimeout(2000);
    await studentPage.waitForTimeout(2000);

    console.log('TUTOR PAGE ERRORS:', tutorPageErrors);
    console.log('STUDENT PAGE ERRORS:', studentPageErrors);

    // Expect the P0 ReferenceError to be caught on at least one page
    const allErrors = [...tutorPageErrors, ...studentPageErrors];
    const hasReferenceError = allErrors.some(e => e.includes('applyControlState is not defined'));

    expect(hasReferenceError).toBe(true);
  } finally {
    await tutorContext.close();
    await studentContext.close();
  }
});
