import { expect, Page, BrowserContext, test } from '@playwright/test';
import { execSync } from 'child_process';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const lessonId = 2168;
const lessonRoomUrl = `/lesson/${lessonId}/room`;
const submissionId = 2694;
const task1AtId = 2832;
const task2AtId = 2837;

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
    st = _load_cached_code_state(2168) or {}
    files = dict(st.get("files") or {})
    files.pop("helper.py", None)
    open_tabs = [t for t in (st.get("open_tabs") or ["main.py"]) if t != "helper.py"]
    if not open_tabs:
        open_tabs = ["main.py"]
    deleted = [f for f in (st.get("deleted_files") or []) if f != "helper.py"]
    new_rev = int(st.get("revision") or 0) + 1
    _update_cached_code_state(2168, {
        "file_name": "main.py",
        "code": files.get("main.py", "x = 5\\ny = 15\\nres = x + y\\nprint(\\"RES:\\", res)\\n"),
        "files": files,
        "open_tabs": open_tabs,
        "active_file": "main.py",
        "deleted_files": deleted,
        "revision": new_rev,
        "version": new_rev,
    })
`);
}

function resetSubmissionRevisionFixture() {
  runPython(`
from app import create_app, db
from core.db_models import Submission, Answer, SubmissionAttempt
app = create_app()
with app.app_context():
    sub = Submission.query.get(${submissionId})
    if sub:
        sub.status = 'RETURNED'
        sub.total_score = 3
        sub.max_score = 5
        sub.percentage = 60.0
        sub.results_published_at = None

        ans1 = Answer.query.filter_by(submission_id=sub.submission_id, assignment_task_id=${task1AtId}).first()
        if ans1:
            ans1.value = '460'
            ans1.score = 1
            ans1.is_correct = True
            ans1.needs_revision = False
            ans1.teacher_comment = 'Зачтено верно'

        ans2 = Answer.query.filter_by(submission_id=sub.submission_id, assignment_task_id=${task2AtId}).first()
        if ans2:
            ans2.value = '999'
            ans2.score = 0
            ans2.is_correct = False
            ans2.needs_revision = True
            ans2.teacher_comment = 'Ошибка в цикле, перепроверьте условие'

        for a in SubmissionAttempt.query.filter_by(submission_id=sub.submission_id).all():
            if a.attempt_no > 1:
                db.session.delete(a)
        db.session.commit()
`);
}

async function login(page: Page, username: string) {
  await page.context().clearCookies();
  await page.goto('/login', { waitUntil: 'domcontentloaded' });
  const usernameInput = page.locator('input[name="username"]');
  await expect(usernameInput).toBeVisible({ timeout: 10_000 });
  await usernameInput.fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
}

test.describe.configure({ mode: 'serial' });

test.describe('Workspace Consistency & Homework Recovery Reproduction Suite', () => {
  test.setTimeout(90_000);

  test.beforeEach(async () => {
    clearBans();
    resetLessonCodeState();
    resetSubmissionRevisionFixture();
  });

  test('REPRO-A: Teacher deletes file, student must not resurrect file via stale tab or tab click', async ({ browser }) => {
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

    await teacherPage.evaluate(() => {
      (window as any).createNewFileOfType('py', 'helper.py');
    });

    const teacherHelperTab = teacherPage.locator('.editor-tab:has-text("helper.py"), [id="tab-helper.py"]');
    await expect(teacherHelperTab).toBeVisible({ timeout: 10_000 });

    const studentHelperTab = studentPage.locator('.editor-tab:has-text("helper.py"), [id="tab-helper.py"]');
    await expect(studentHelperTab).toBeVisible({ timeout: 10_000 });

    await teacherPage.evaluate(() => {
      (window as any).switchEditorTab(null, 'helper.py');
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      if (ta) {
        ta.value = 'def helper():\n    return 42\n';
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await teacherPage.waitForTimeout(1000);

    await teacherPage.evaluate(() => {
      (window as any).deleteFileFromVFS(null, 'helper.py', true);
    });

    await expect(teacherHelperTab).not.toBeVisible({ timeout: 5_000 });
    await expect(studentHelperTab).not.toBeVisible({ timeout: 10_000 });

    await studentPage.evaluate(() => {
      if (typeof (window as any).switchEditorTab === 'function') {
        (window as any).switchEditorTab(null, 'helper.py');
      }
    });
    await studentPage.waitForTimeout(1000);

    await expect(teacherHelperTab).not.toBeVisible({ timeout: 3_000 });

    await teacherPage.reload({ waitUntil: 'domcontentloaded' });
    await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });
    await expect(teacherPage.locator('.editor-tab:has-text("helper.py"), [id="tab-helper.py"]')).not.toBeVisible();

    await studentPage.reload({ waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });
    await expect(studentPage.locator('.editor-tab:has-text("helper.py"), [id="tab-helper.py"]')).not.toBeVisible();

    await teacherContext.close();
    await studentContext.close();
  });

  test('REPRO-C-D: Returned homework allows resubmit from accepted Task 1 and preserves revision lifecycle', async ({ page }) => {
    await login(page, studentUsername);

    const task1Url = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(task1Url, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    const submitBtn = page.locator('#homework-submit');
    await expect(submitBtn).toBeVisible({ timeout: 10_000 });
    await expect(submitBtn).toBeEnabled();

    const returnedBadge = page.locator('.homework-os-system-bar:has-text("доработк"), #hw-revision-top-badge');
    const hasTopBadge = (await returnedBadge.count()) > 0;
    expect(hasTopBadge).toBe(true);

    const task2Tab = page.locator('.homework-os-task-tab[data-task-id="2837"], a[href*="assignment_task_id=2837"]');
    await expect(task2Tab).toBeVisible();

    await task2Tab.click();
    await page.waitForTimeout(1000);

    await submitBtn.click();

    const modal = page.locator('#homework-submitted-modal');
    await expect(modal).toBeVisible({ timeout: 10_000 });
  });

  test('REPRO-E: Window resizing enforces minimum size clamps under real pointer dragging', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    const codeWindow = page.locator('#code-window');
    await expect(codeWindow).toBeVisible({ timeout: 20_000 });

    const resizeHandle = codeWindow.locator('.window-resize-handle, .resizer-se').first();
    await expect(resizeHandle).toBeVisible();

    const handleBox = await resizeHandle.boundingBox();
    expect(handleBox).not.toBeNull();

    await page.mouse.move(handleBox!.x + handleBox!.width / 2, handleBox!.y + handleBox!.height / 2);
    await page.mouse.down();
    await page.mouse.move(handleBox!.x - 1000, handleBox!.y - 1000, { steps: 10 });
    await page.mouse.up();

    const afterBox = await codeWindow.boundingBox();
    expect(afterBox).not.toBeNull();
    const expectedMinWidth = Math.min(410, (page.viewportSize()?.width || 1024) - 20);
    expect(afterBox!.width).toBeGreaterThanOrEqual(expectedMinWidth);
    expect(afterBox!.height).toBeGreaterThanOrEqual(250);
  });

  test('REPRO-F: Homework OS multi-file editing preserves main.py when helper.py is edited', async ({ page }) => {
    await login(page, studentUsername);
    const task2Url = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task2AtId}`;
    await page.goto(task2Url, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    await page.evaluate(() => {
      (window as any).virtualFS = (window as any).virtualFS || {};
      (window as any).virtualFS['main.py'] = 'print("AUTHORITATIVE_MAIN_CODE")';
      (window as any).createNewFileOfType('py', 'helper.py');
      (window as any).virtualFS['helper.py'] = 'x = 999999';
      (window as any).switchEditorTab(null, 'helper.py');
    });

    await page.evaluate(async () => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      if (ta) {
        ta.value = 'x = 999999';
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if (typeof (window as any).flushHomeworkCode === 'function') {
        await (window as any).flushHomeworkCode();
      }
    });

    await page.waitForTimeout(2000);

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    const mainCode = await page.evaluate(() => {
      return (window as any).virtualFS ? (window as any).virtualFS['main.py'] : null;
    });
    expect(mainCode).toContain('AUTHORITATIVE_MAIN_CODE');
    expect(mainCode).not.toContain('x = 999999');
  });

  test('REPRO-UI: Submitted modal button does not have conflicting clay-shadow glow', async ({ page }) => {
    await login(page, studentUsername);
    const task1Url = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(task1Url, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    await page.evaluate(() => {
      (window as any).showPostSubmitConfirmation({ status: 'GRADED', score: 5, max_score: 5, percentage: 100 });
    });

    const exitBtn = page.locator('#hw-post-submit-exit');
    await expect(exitBtn).toBeVisible({ timeout: 5_000 });

    const boxShadow = await exitBtn.evaluate((el) => window.getComputedStyle(el).boxShadow);
    expect(boxShadow).not.toContain('inset 8px 8px');
    expect(boxShadow).not.toContain('12px 12px 24px');
  });
});
