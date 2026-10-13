import { expect, test } from '@playwright/test';

async function continueNovel(page: import('@playwright/test').Page) {
  await page.locator('#boo-novel-close:visible').click();
}

async function expectNoHorizontalOverflow(page: import('@playwright/test').Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1);
}

async function runLinearDemo(page: import('@playwright/test').Page) {
  test.setTimeout(120000);
  const serverErrors: string[] = [];
  const runtimeErrors: string[] = [];
  page.on('response', response => {
    if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`);
  });
  page.on('pageerror', error => runtimeErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') runtimeErrors.push(message.text());
  });

  await page.goto('/demo', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /Да, показывай/ }).click();
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await page.getByLabel('Твоё имя').fill(`Release ${test.info().project.name}`);
  await page.locator('#grade').selectOption('11');
  await page.getByRole('button', { name: 'Дальше' }).click();
  await page.getByRole('button', { name: 'Guided demo с Бу' }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 30000 });

  await continueNovel(page);
  await page.locator('[data-demo-target="learning-program"]:visible').click();
  await page.getByRole('button', { name: 'Открыть мой курс' }).click();
  await page.locator('[data-demo-program-course]:visible').first().click();
  await page.getByRole('button', { name: 'Показать модуль' }).click();
  await page.locator('[data-demo-target="program-module"]:visible').first().click();
  await page.getByRole('button', { name: 'Вернуться в кабинет' }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  await continueNovel(page);
  await page.locator('[data-demo-target="past-lesson"]:visible').click();
  await expect(page).toHaveURL(/\/lesson\/\d+\/room/);
  await continueNovel(page);
  await page.locator('[data-demo-target="lesson-room-tour"]:visible').click();
  await page.getByRole('button', { name: 'Вернуться в кабинет' }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  await continueNovel(page);
  await page.locator('[data-demo-target="recent-assignments"]:visible').click();
  await page.getByRole('button', { name: /Открыть первое испытание/ }).click();
  await expect(page).toHaveURL(/\/task-workspace/);
  await page.getByRole('button', { name: /Выбрать способ решения/ }).click();
  await page.getByRole('button', { name: 'Режим «Ответ»' }).click();
  await page.getByRole('button', { name: 'Показать поле ответа' }).click();
  await page.locator('#tw-answer').fill('5');
  await page.locator('#tw-submit-work').click();
  await page.getByRole('button', { name: /Посмотреть решение/ }).click();
  await expect(page.locator('#boo-cinema-mode')).toBeHidden();
  await page.getByRole('button', { name: 'Перейти к работе над ошибками' }).click();

  await expect(page).toHaveURL(/\/submissions/);
  await page.getByRole('button', { name: 'Показать разбор ошибки' }).click();
  await page.locator('[data-demo-target="mistake-review"]:visible').click();
  await page.getByRole('button', { name: /Исправить ответ/ }).click();
  await expect(page).toHaveURL(/\/task-workspace/);
  await page.getByRole('button', { name: 'Показать поле ответа' }).click();
  await page.locator('#tw-answer').fill('5');
  await page.locator('#tw-submit-work').click();
  await page.getByRole('button', { name: 'Посмотреть аналитику' }).click();

  await expect(page).toHaveURL(/\/student\/\d+\/analytics/);
  await page.getByRole('button', { name: 'Показать прогресс' }).click();
  await page.locator('[data-demo-target="analytics-progress"]:visible').click();
  await page.getByRole('button', { name: 'Открыть расписание' }).click();

  await expect(page).toHaveURL(/\/schedule/);
  await page.getByRole('button', { name: 'Показать неделю' }).click();
  await page.locator('[data-demo-target="schedule-week"]:visible').click();
  await page.getByRole('button', { name: 'Посмотреть профиль' }).click();

  await expect(page).toHaveURL(/\/workspace\/profile/);
  await page.getByRole('button', { name: 'Показать достижения' }).click();
  await page.locator('[data-demo-target="profile-achievements-action"]:visible').click();
  await page.getByRole('button', { name: 'К финалу' }).click();
  await expect(page.locator('#boo-finale-mode')).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.getByRole('button', { name: 'Оставить заявку на вводный урок' }).click();
  const form = page.locator('#boo-intro-request');
  await form.getByLabel('Имя').fill(`Release ${test.info().project.name}`);
  await form.getByLabel('Класс').fill('11');
  await form.getByLabel('Цель').fill('ЕГЭ 80+');
  await form.getByLabel('Telegram, телефон или email').fill(`@release_${test.info().project.name.replace(/[^a-z0-9]+/gi, '_')}_${Date.now()}`);
  await form.getByLabel('Удобные дата и время').fill('2026-10-07T18:00');
  await form.getByLabel(/Согласен/).check();
  await form.getByRole('button', { name: 'Отправить заявку' }).click();
  await expect(page.locator('#boo-request-followup')).toBeVisible({ timeout: 15000 });
  await expect(form.locator('#boo-request-status')).toHaveText('Заявка у меня. Отвечу в Telegram.');
  await expectNoHorizontalOverflow(page);

  expect(serverErrors).toEqual([]);
  expect(runtimeErrors).toEqual([]);
}

test.describe('BooStudy — canonical linear release journey', () => {
  test('desktop: from welcome to a persisted intro request', async ({ page }) => {
    await runLinearDemo(page);
  });

  test('mobile: from welcome to a persisted intro request', async ({ page }) => {
    await runLinearDemo(page);
  });
});
