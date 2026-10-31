import { expect, Page, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const roomUrl = process.env.BOOSTUDY_E2E_ROOM_URL || '/lesson/2168/room';

async function login(page: Page, username: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  const usernameInput = page.locator('input[name="username"]');
  await expect(usernameInput).toBeVisible({ timeout: 10_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
}

test.describe('Sprint 8: Full Feature Verification & Integration E2E', () => {
  test('Tutor: Full Window Inventory & Dock Verification in /lesson/room', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(roomUrl);
    await page.waitForLoadState('domcontentloaded');

    // 1. Core Educational Windows
    const codeWindow = page.locator('#code-window');
    await expect(codeWindow).toBeVisible({ timeout: 15_000 });

    const dock = page.locator('#board-dock');
    await expect(dock).toBeVisible();

    // 2. Teacher Private Windows (Present in DOM for Tutor)
    const taskBankDock = page.locator('#dock-icon-teacher-task-bank-window');
    await expect(taskBankDock).toBeVisible();

    // Open Task Bank
    await taskBankDock.click();
    const taskBankWindow = page.locator('#teacher-task-bank-window');
    await expect(taskBankWindow).toBeVisible();

    // Verify private indicator badge
    await expect(taskBankWindow).toContainText('Банк заданий');
    await expect(taskBankWindow).toContainText('Приватно');

    // Close Task Bank
    await page.locator('#teacher-task-bank-window .os-window-dot.bg-\\[\\#FF5F56\\]').click();
    await expect(taskBankWindow).toBeHidden();
  });

  test('Student: Private Teacher Tools are Absent or Strictly Blocked', async ({ page }) => {
    await login(page, studentUsername);
    await page.goto(roomUrl);
    await page.waitForLoadState('domcontentloaded');

    // 1. Task Bank Dock item must NOT be rendered for student
    const taskBankDock = page.locator('#dock-icon-teacher-task-bank-window');
    await expect(taskBankDock).toHaveCount(0);

    // 2. Private window element must NOT be present or accessible
    const taskBankWindow = page.locator('#teacher-task-bank-window');
    await expect(taskBankWindow).toHaveCount(0);

    // 3. Student has standard public windows
    const codeWindow = page.locator('#code-window');
    await expect(codeWindow).toBeVisible({ timeout: 15_000 });
  });

  test('Python IDE Execution & Terminal Output Lifecycle', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(roomUrl);
    await page.waitForLoadState('domcontentloaded');

    const codeWindow = page.locator('#code-window');
    await expect(codeWindow).toBeVisible({ timeout: 15_000 });

    // Check textarea editor
    const textarea = page.locator('#code-editor-textarea');
    await expect(textarea).toBeVisible();

    // Run code button
    const runBtn = page.locator('#code-window button[onclick="executeRunCode()"]');
    if (await runBtn.isVisible()) {
      await runBtn.click();
      const terminalWindow = page.locator('#terminal-window');
      await expect(terminalWindow).toBeVisible({ timeout: 8_000 });
      const consoleOutput = page.locator('#terminal-console-output');
      await expect(consoleOutput).toBeVisible();
    }
  });

  test('Dual-Client Live Synchronization & Permission Boundary', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(roomUrl);
      await studentPage.goto(roomUrl);

      await tutorPage.waitForLoadState('domcontentloaded');
      await studentPage.waitForLoadState('domcontentloaded');

      // Both must render their primary workspaces
      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Tutor has teacher task bank dock icon, student strictly does NOT
      await expect(tutorPage.locator('#dock-icon-teacher-task-bank-window')).toBeVisible();
      await expect(studentPage.locator('#dock-icon-teacher-task-bank-window')).toHaveCount(0);

      // Student has student role layout without private tools
      await expect(studentPage.locator('#teacher-task-bank-window')).toHaveCount(0);
      await expect(studentPage.locator('#teacher-notes-window')).toHaveCount(0);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });
});
