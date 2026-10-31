import { expect, test, type Page } from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const baseURL = process.env.BOOSTUDY_E2E_BASE_URL || 'http://127.0.0.1:5196';
const dbPath = process.env.BOOSTUDY_E2E_SAFE_DB_PATH || '';
const teacherPassword = process.env.BOOSTUDY_SYNTHETIC_TEACHER_PASSWORD || '';
const studentPassword = process.env.BOOSTUDY_SYNTHETIC_STUDENT_PASSWORD || '';
const enabled = process.env.BOOSTUDY_ADAPTIVE_E2E === '1';

test.skip(!enabled, 'Требуется отдельная разрешённая synthetic SQLite и safe backend.');
test.describe.configure({ mode: 'serial' });

function verifySyntheticDatabaseIdentity() {
  assert.equal(new URL(baseURL).hostname, '127.0.0.1', 'E2E разрешён только на loopback.');
  assert.equal(new URL(baseURL).port, '5196', 'Ожидался safe backend на порту 5196.');
  assert.ok(dbPath, 'Укажите BOOSTUDY_E2E_SAFE_DB_PATH.');
  assert.equal(path.basename(dbPath), 'adaptive_learning_synthetic.sqlite');
  assert.ok(path.basename(path.dirname(dbPath)).startsWith('BooStudy_Adaptive_Lab_Synthetic_Linux_'));
  const manifestPath = dbPath.replace(/adaptive_learning_synthetic\.sqlite$/, 'adaptive_learning_synthetic.manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as {
    format?: string;
    synthetic?: boolean;
    db_identity?: string;
  };
  const stat = fs.statSync(dbPath);
  assert.equal(manifest.format, 'boostudy.adaptive-lab-synthetic.v1');
  assert.equal(manifest.synthetic, true);
  assert.equal(manifest.db_identity, `${stat.dev}:${stat.ino}`);
}

async function login(page: Page, username: string, password: string) {
  await page.goto('/login');
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', { name: /войти/i }).click();
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
}

async function openLessonAssignmentBuilder(page: Page) {
  await page.goto('/courses/3/lessons/7/edit');
  await expect(page.locator('body')).toContainText('Достижимость, отсутствие пути и нулевая стоимость');
  await expect(page.locator('body')).toContainText('Сохранить урок');

  // Task 8 was already seen by this learner. Use the genuinely different task
  // only as an explicit shared review; its exact prompt repeats task 1, so it
  // must never be described as independent evidence.
  await page.getByText('Подобрать существующее задание', { exact: true }).click();
  const task7Card = page.locator('[data-bank-task-card]').filter({ has: page.locator('input[name="bank_task_ids"][value="7"]') });
  const task7State = await task7Card.innerText();
  if (task7State.includes('ещё не добавлен в урок')) {
    await task7Card.locator('input[name="bank_task_ids"]').check();
    await page.locator('select[name="bank_assignment_type"]').selectOption('homework');
    await page.locator('select[name="bank_task_purpose_7"]').selectOption('shared_review');
    await page.locator('input[name="bank_tasks_confirmed"]').check();
    await page.locator('#programChangeReason').fill(
      'Synthetic acceptance: добавить задачу #7 только для повторного закрепления. Её условие совпадает с ранее предъявлявшейся задачей #1; результат не считать независимой диагностикой или подтверждением освоения.',
    );
    await page.getByRole('button', { name: 'Сохранить урок' }).click();
    await page.waitForLoadState('domcontentloaded');
  }
  await page.goto('/courses/3/lessons/7/edit');
  const lessonText = await page.locator('body').innerText();
  const versionMatch = lessonText.match(/версия индивидуального урока\s*[·:]?\s*v(\d+)/i);
  expect(versionMatch, 'У индивидуального урока должна быть видна версия').not.toBeNull();
  const courseVersion = Number(versionMatch![1]);
  expect(courseVersion).toBeGreaterThanOrEqual(8);

  await page.getByRole('link', { name: /назначить обычное домашнее задание/i }).click();
  await expect(page).toHaveURL(/\/assignments\/create\?.*lesson_id=7.*synthetic_course_id=3/);
  await expect(page.locator('body')).toContainText(`версия ${courseVersion}`);
  await expect(page.locator('#assignment-tasks-container')).toContainText('A–B=2, B–D=4');

  for (const staleCondition of ['L–M=0', 'P–Q=4']) {
    const staleExercise = page.locator('#assignment-tasks-container > div').filter({ hasText: staleCondition });
    if (await staleExercise.count()) {
      await staleExercise.locator('button[title="Удалить из работы"]').click();
    }
  }
  await expect(page.locator('#assignment-tasks-container')).toContainText('A–B=2, B–D=4');
  await expect(page.locator('#assignment-tasks-container')).not.toContainText('L–M=0');
  await expect(page.locator('#assignment-tasks-container')).not.toContainText('P–Q=4');
  await page.locator('#assignment-title').fill(`Synthetic acceptance · Course 3 v${courseVersion} · Lesson 7`);
  await page.locator('#assignment-description').fill(
    'Контролируемое повторение: этот граф совпадает с ранее предъявлявшимся упражнением. Работа проверяет ответ этой попытки и не является независимой диагностикой или подтверждением освоения навыка.',
  );
  const deadline = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
  const pad = (value: number) => String(value).padStart(2, '0');
  await page.locator('#assignment-deadline').fill(
    `${deadline.getFullYear()}-${pad(deadline.getMonth() + 1)}-${pad(deadline.getDate())}T${pad(deadline.getHours())}:${pad(deadline.getMinutes())}`,
  );
  return courseVersion;
}

test('обычная домашняя работа Course 3 / Lesson 7 проходит teacher → student → evidence', async ({ browser, request }) => {
  verifySyntheticDatabaseIdentity();
  assert.ok(teacherPassword && studentPassword, 'Задайте пароли только через переменные окружения процесса теста.');
  const ready = await request.get('/ready');
  expect(ready.status()).toBe(200);
  expect(await ready.json()).toMatchObject({ environment: 'local', status: 'OK' });

  const teacherContext = await browser.newContext();
  const teacher = await teacherContext.newPage();
  await login(teacher, 'synthetic_tutor', teacherPassword);
  const studentContext = await browser.newContext();
  const student = await studentContext.newPage();
  await login(student, 'synthetic_graph_learner_1', studentPassword);
  await student.goto('/assignments');
  const courseVersion = await openLessonAssignmentBuilder(teacher);
  const assignmentTitle = `Synthetic acceptance · Course 3 v${courseVersion} · Lesson 7`;
  const preexistingAssignment = await student.locator('body').innerText().then(text => text.includes(assignmentTitle));
  if (!preexistingAssignment) {
    await student.goto('/courses/3');
    await expect(student.locator('body')).not.toContainText('A–B=2, B–D=4, A–C=3');
  }

  const publishPromise = teacher.waitForResponse(response =>
    response.url().endsWith('/assignments/distribute') && response.request().method() === 'POST');
  await teacher.getByRole('button', { name: /Создать и отправить работу/i }).last().click();
  const publishResponse = await publishPromise;
  const published = await publishResponse.json() as {
    success: boolean;
    already_assigned?: boolean;
    assignment_id: number;
    error?: string;
  };
  expect([200, 201], JSON.stringify(published)).toContain(publishResponse.status());
  expect(published.success).toBe(true);
  if (preexistingAssignment) expect(published.already_assigned).toBe(true);
  const publishPayload = publishResponse.request().postDataJSON() as {
    lesson_id: number;
    synthetic_course_id: number;
    synthetic_course_version: number;
    recipientIds: number[];
    tasks: Array<{ task_id: number }>;
  };
  expect(publishPayload).toMatchObject({
    lesson_id: 7,
    synthetic_course_id: 3,
    synthetic_course_version: courseVersion,
    recipientIds: [2],
    tasks: [{ task_id: 7 }],
  });

  // Repeating the same teacher action returns the original Assignment.
  await openLessonAssignmentBuilder(teacher);
  const duplicatePromise = teacher.waitForResponse(response =>
    response.url().endsWith('/assignments/distribute') && response.request().method() === 'POST');
  await teacher.getByRole('button', { name: /Создать и отправить работу/i }).last().click();
  const duplicateResponse = await duplicatePromise;
  expect(duplicateResponse.status()).toBe(200);
  const duplicate = await duplicateResponse.json() as {
    success: boolean;
    already_assigned: boolean;
    assignment_id: number;
  };
  expect(duplicate).toMatchObject({ success: true, already_assigned: true, assignment_id: published.assignment_id });

  await student.goto('/assignments');
  await expect(student.locator('body')).toContainText(assignmentTitle);
  const assignmentLink = student.locator('a[href^="/submissions/"]').first();
  await expect(assignmentLink).toBeVisible();
  await assignmentLink.click();
  await expect(student).toHaveURL(/\/task-workspace\/\?context_type=submission_task&context_id=\d+&assignment_task_id=\d+/);
  await expect(student.locator('body')).toContainText('A–B=2, B–D=4');
  const answerFrame = student.frameLocator('#homework-answer-frame');
  const answerField = answerFrame.locator('#tw-answer');
  const studentVisibleTextBeforeAnswer = await answerFrame.locator('body').innerText();
  const hasReview = (await answerFrame.locator('.tw-review-correct-answer').count()) > 0;
  if (!hasReview) {
    await expect(answerField).toBeVisible();
    expect(studentVisibleTextBeforeAnswer).not.toMatch(/правильный ответ|эталонный ответ/i);
  }

  // The acceptance exercise has one deterministic exact checker. Existing
  // submissions are reopened on reruns instead of submitting a second time.
  const bodyBeforeSubmit = `${await student.locator('body').innerText()}\n${studentVisibleTextBeforeAnswer}`;
  if (!hasReview && !/отправлено|проверено|оценка|результат/i.test(bodyBeforeSubmit)) {
    await expect(answerField).toBeVisible();
    if (!(await answerField.inputValue()).trim()) await answerField.fill('6');
    const saveButton = answerFrame.getByRole('button', { name: /сохранить черновик|сохранить ответ/i });
    if (await saveButton.count()) {
      await saveButton.first().click();
      await student.reload();
      await expect(answerFrame.locator('#tw-answer')).toHaveValue('6');
    }
    const submitButton = answerFrame.getByRole('button', { name: /отправить|сдать работу|проверить ответ/i }).last();
    await expect(submitButton).toBeVisible();
    await submitButton.click();
    await expect(student.locator('body')).toContainText(/1\s*\/\s*1|1 из 1|проверено/i);
  }
  await student.reload();
  await expect(student.locator('body')).toContainText(/1\s*\/\s*1|1 из 1|проверено|результат/i);

  await teacher.goto(`/assignments/${published.assignment_id}`);
  await expect(teacher.locator('body')).toContainText('synthetic_graph_learner_1');
  await expect(teacher.locator('body')).toContainText(/1\s*\/\s*1|1 из 1|проверено/i);
  await teacher.reload();
  await expect(teacher.locator('body')).toContainText(/1\s*\/\s*1|1 из 1|проверено/i);

  await studentContext.close();
  await teacherContext.close();
});
