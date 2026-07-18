import { expect, Page, test } from '@playwright/test';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';

const accounts = {
  student: process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1',
  tutor: process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1',
  parent: process.env.BOOSTUDY_E2E_PARENT || 'qa_pool_parent_1',
  admin: process.env.BOOSTUDY_E2E_ADMIN || 'qa_pool_admin_1',
};

const criticalUrls = {
  student: ['/dashboard', '/submissions', '/trainer/v2'],
  tutor: ['/dashboard', '/assignments', '/submissions', '/trainer/v2'],
  parent: ['/parent/dashboard'],
  admin: ['/dashboard', '/qa/pool'],
};

test.beforeEach(async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedResponses: string[] = [];

  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text());
    }
  });

  page.on('response', (response) => {
    const status = response.status();
    const url = response.url();
    if (status >= 500) {
      failedResponses.push(`${status} ${url}`);
    }
  });

  page.on('pageerror', (error) => {
    consoleErrors.push(error.message);
  });

  await page.context().addInitScript(() => {
    window.localStorage.setItem('boostudy-e2e-run', '1');
  });

  test.info().attach('error-buffers', {
    body: JSON.stringify({ consoleErrors, failedResponses }, null, 2),
    contentType: 'application/json',
  });

  (page as Page & { __releaseAuditErrors?: () => { consoleErrors: string[]; failedResponses: string[] } }).__releaseAuditErrors = () => ({
    consoleErrors,
    failedResponses,
  });
});

async function login(page: Page, username: string) {
  await page.goto('/logout').catch(() => undefined);
  await page.goto('/login');
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', { name: /войти/i }).click();
  await page.waitForLoadState('networkidle');
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
}

async function assertNoCriticalBrowserErrors(page: Page) {
  const audit = (page as Page & { __releaseAuditErrors?: () => { consoleErrors: string[]; failedResponses: string[] } }).__releaseAuditErrors?.();
  const ignoredConsole = [
    /favicon/i,
    /ResizeObserver loop/i,
    /Failed to load resource.*404/i,
  ];
  const consoleErrors = (audit?.consoleErrors || []).filter((message) => !ignoredConsole.some((pattern) => pattern.test(message)));
  const failedResponses = audit?.failedResponses || [];
  expect([...consoleErrors, ...failedResponses]).toEqual([]);
}

async function openAndCheck(page: Page, url: string) {
  const response = await page.goto(url, { waitUntil: 'domcontentloaded' });
  expect(response?.status(), `${url} should not return server error`).toBeLessThan(500);
  await expect(page.locator('body')).toBeVisible();
  await expect(page.locator('body')).not.toContainText(/страница не загрузилась|ошибка!!|traceback|internal server error/i);
  await assertNoCriticalBrowserErrors(page);
}

test.describe('BooStudy release smoke by role', () => {
  test('student can open core cabinet pages', async ({ page }) => {
    await login(page, accounts.student);
    for (const url of criticalUrls.student) {
      await openAndCheck(page, url);
    }
  });

  test('tutor can open teaching workflow pages', async ({ page }) => {
    await login(page, accounts.tutor);
    for (const url of criticalUrls.tutor) {
      await openAndCheck(page, url);
    }
  });

  test('parent can open parent dashboard without broken child scope', async ({ page }) => {
    await login(page, accounts.parent);
    for (const url of criticalUrls.parent) {
      await openAndCheck(page, url);
    }
  });

  test('admin can open dashboard and QA pool', async ({ page }) => {
    await login(page, accounts.admin);
    for (const url of criticalUrls.admin) {
      await openAndCheck(page, url);
    }
  });
});
