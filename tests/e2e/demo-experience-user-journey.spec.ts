import { expect, test } from '@playwright/test';

async function continueBoo(page: import('@playwright/test').Page) {
  const close = page.locator('#boo-novel-close:visible');
  await expect(close).toBeVisible({ timeout: 30000 });
  await close.click();
}

async function expectNoHorizontalOverflow(page: import('@playwright/test').Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1);
}

test('полный пользовательский маршрут до работы над ошибками не зацикливается', async ({ page }) => {
  const runtimeErrors: string[] = [];
  page.on('pageerror', error => runtimeErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') runtimeErrors.push(message.text());
  });

  await page.goto('/demo', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /Да, показывай/ }).click();
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await page.getByLabel('ТВОЁ ИМЯ').fill('UI-маршрут');
  await page.getByLabel('В КАКОМ ТЫ КЛАССЕ?').selectOption('10');
  await page.getByRole('button', { name: 'Дальше' }).click();
  await page.getByRole('button', { name: 'Guided demo с Бу' }).click();

  await continueBoo(page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Продолжить' }).click();
  await expect(page.locator('[data-demo-target="learning-program"]:visible')).toHaveClass(/boo-target-pulse/);
  await expectNoHorizontalOverflow(page);
  await page.locator('[data-demo-target="learning-program"]:visible').click();
  await page.getByRole('button', { name: 'Открыть мой курс' }).click();
  await expectNoHorizontalOverflow(page);
  await page.locator('[data-demo-program-course]:visible').first().click();
  await page.getByRole('button', { name: 'Показать модуль' }).click();
  await page.locator('[data-demo-target="program-module"]:visible').first().click();
  await page.getByRole('button', { name: 'Вернуться в кабинет' }).click();

  await continueBoo(page);
  await page.locator('[data-demo-target="past-lesson"]:visible').click();
  await expectNoHorizontalOverflow(page);
  await continueBoo(page);
  await page.locator('[data-demo-target="lesson-room-tour"]:visible').click();
  await page.getByRole('button', { name: 'Вернуться в кабинет' }).click();

  await page.locator('#boo-novel-close:visible').click();
  await page.locator('[data-demo-target="recent-assignments"]:visible').click();
  await page.getByRole('button', { name: 'Открыть первое испытание' }).click();
  await expectNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'Выбрать способ решения' }).click();
  await page.getByRole('button', { name: 'Режим «Ответ»' }).click();
  await page.getByRole('button', { name: 'Показать поле ответа' }).click();
  await page.locator('#tw-answer').fill('5');
  await page.locator('#tw-submit-work').click();

  await expect(page.getByRole('button', { name: /Посмотреть решение/ })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: /Посмотреть решение/ }).click();
  await page.getByRole('button', { name: /Перейти к работе над ошибками/ }).click();
  await expect(page).toHaveURL(/\/submissions/);
  await expect(page.getByRole('button', { name: 'Показать разбор ошибки' })).toBeVisible({ timeout: 10000 });

  await page.getByRole('button', { name: 'Показать разбор ошибки' }).click();
  await expect(page.locator('[data-demo-target="mistake-review"]')).toHaveClass(/boo-target-pulse/);
  expect(runtimeErrors).toEqual([]);
});
