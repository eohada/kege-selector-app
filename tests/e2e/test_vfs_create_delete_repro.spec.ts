import { expect, test } from '@playwright/test';
import { execSync } from 'child_process';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const lessonId = 2168;
const lessonRoomUrl = `/lesson/${lessonId}/room`;

function runPython(code: string): string {
  const sanitized = code.replace(/"/g, '\\"');
  return execSync(`./venv/bin/python -c "${sanitized}"`, {
    cwd: '/mnt/Main/projects/kege_selector_app_current',
    encoding: 'utf-8',
    env: { ...process.env, PYTHONPATH: '.' }
  });
}

function clearBans() {
  runPython(`
from app import create_app, db
from core.db_models import LessonParticipantBan
from app.runtime_state import get_redis_client
app = create_app()
with app.app_context():
    for b in LessonParticipantBan.query.filter_by(lesson_id=2168).all():
        b.is_active = False
    db.session.commit()
    r = get_redis_client()
    if r:
        r.delete('lesson:2168:banned_users')
`);
}

function resetLessonCodeState() {
  runPython(`
from app import create_app
from app.lessons.lesson_socket import _load_cached_code_state, _update_cached_code_state
app = create_app()
with app.app_context():
    _update_cached_code_state(2168, {
        "file_name": "main.py",
        "code": "x = 5\\ny = 15\\nres = x + y\\nprint(\\"RES:\\", res)\\n",
        "files": {"main.py": "x = 5\\ny = 15\\nres = x + y\\nprint(\\"RES:\\", res)\\n"},
        "open_tabs": ["main.py"],
        "active_file": "main.py",
        "deleted_files": [],
        "revision": 1,
        "version": 1,
    })
`);
}

async function login(page: any, username: string) {
  await page.context().clearCookies();
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  const usernameInput = page.locator('input[name="username"]');
  await expect(usernameInput).toBeVisible({ timeout: 10_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
}

test.describe('VFS Create/Delete Protocol Reproduction', () => {
  test.setTimeout(90_000);

  test.beforeEach(async () => {
    clearBans();
    resetLessonCodeState();
  });

  test('VFS-CLOSE-TAB-01: Closing tab locally keeps file in project, does not close other participant tab, and can reopen from explorer', async ({ browser }) => {
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

    await teacherPage.waitForTimeout(1000);

    // 1. Teacher creates solution_2.py via add button
    const addBtn = teacherPage.locator('#editor-tabs-add-btn');
    await expect(addBtn).toBeVisible({ timeout: 5_000 });
    await addBtn.click();

    const modal = teacherPage.locator('#lesson-vfs-new-file-modal');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    const input = teacherPage.locator('#lesson-vfs-new-filename-input');
    await input.fill('solution_2.py');
    const submitBtn = teacherPage.locator('#lesson-vfs-new-file-card button:has-text("Создать")');
    await submitBtn.click();

    // Verify solution_2.py tab appears on both teacher and student
    const teacherTab = teacherPage.locator('#tab-solution_2\\.py');
    await expect(teacherTab).toBeVisible({ timeout: 10_000 });
    const studentTab = studentPage.locator('#tab-solution_2\\.py');
    await expect(studentTab).toBeVisible({ timeout: 10_000 });

    // 2. Student closes tab locally via .tab-close-btn
    const studentCloseBtn = studentPage.locator('#tab-solution_2\\.py .tab-close-btn');
    await expect(studentCloseBtn).toBeVisible({ timeout: 5_000 });
    await studentCloseBtn.click();

    // Student tab is closed
    await expect(studentTab).not.toBeVisible({ timeout: 5_000 });

    // Teacher tab MUST REMAIN OPEN (Close Tab is local to participant)
    await expect(teacherTab).toBeVisible({ timeout: 5_000 });

    // 3. File solution_2.py must still exist in Student's virtualFS
    const hasSolution = await studentPage.evaluate(() => {
      return Boolean((window as any).virtualFS && (window as any).virtualFS['solution_2.py'] !== undefined);
    });
    expect(hasSolution).toBe(true);

    // Reopen file tab on student via openFileFromExplorer
    await studentPage.evaluate(() => {
      (window as any).openFileFromExplorer('solution_2.py');
    });

    // Tab is reopened on student
    await expect(studentTab).toBeVisible({ timeout: 5_000 });

    await teacherContext.close();
    await studentContext.close();
  });

  test('VFS-DELETE-FILE-02: Explicit delete with modal removes file for all participants, explorer cleared, no resurrection on reload', async ({ browser }) => {
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

    await teacherPage.waitForTimeout(1000);

    // 1. Teacher creates helper_shared.py via add button
    const addBtn = teacherPage.locator('#editor-tabs-add-btn');
    await expect(addBtn).toBeVisible({ timeout: 5_000 });
    await addBtn.click();

    const modal = teacherPage.locator('#lesson-vfs-new-file-modal');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    const input = teacherPage.locator('#lesson-vfs-new-filename-input');
    await input.fill('helper_shared.py');
    const submitBtn = teacherPage.locator('#lesson-vfs-new-file-card button:has-text("Создать")');
    await submitBtn.click();

    const teacherTab = teacherPage.locator('#tab-helper_shared\\.py');
    await expect(teacherTab).toBeVisible({ timeout: 10_000 });
    const studentTab = studentPage.locator('#tab-helper_shared\\.py');
    await expect(studentTab).toBeVisible({ timeout: 10_000 });

    // 2. Teacher clicks delete button on tab -> Glass confirmation modal opens
    const deleteBtn = teacherPage.locator('#tab-helper_shared\\.py .tab-delete-btn');
    await deleteBtn.click({ force: true });

    const glassModal = teacherPage.locator('#glass-modal-overlay');
    await expect(glassModal).toBeVisible({ timeout: 5_000 });
    await expect(teacherPage.locator('#glass-modal-message')).toContainText('безвозвратно удалить файл "helper_shared.py"');

    // Confirm deletion
    const confirmBtn = teacherPage.locator('#glass-modal-btn-confirm');
    await confirmBtn.click();

    // 3. Tab disappears for both teacher and student
    await expect(teacherTab).not.toBeVisible({ timeout: 5_000 });
    await expect(studentTab).not.toBeVisible({ timeout: 10_000 });

    // 4. Explorer on student does not list helper_shared.py
    await expect(studentPage.locator('#explorer-file-list span:has-text("helper_shared.py")')).not.toBeVisible();

    // 5. Reload student page -> file must NOT be resurrected
    await studentPage.reload({ waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });
    await expect(studentPage.locator('#tab-helper_shared\\.py')).not.toBeVisible();
    await expect(studentPage.locator('#explorer-file-list span:has-text("helper_shared.py")')).not.toBeVisible();

    // 6. Reload teacher page -> file must NOT be resurrected
    await teacherPage.reload({ waitUntil: 'domcontentloaded' });
    await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });
    await expect(teacherPage.locator('#tab-helper_shared\\.py')).not.toBeVisible();
    await expect(teacherPage.locator('#explorer-file-list span:has-text("helper_shared.py")')).not.toBeVisible();

    await teacherContext.close();
    await studentContext.close();
  });
});
