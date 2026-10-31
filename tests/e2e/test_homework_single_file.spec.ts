import { expect, Page, test } from '@playwright/test';
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
  return execSync('./venv/bin/python', {
    input: code,
    cwd: '/mnt/Main/projects/kege_selector_app_current',
    encoding: 'utf-8',
    env: { ...process.env, PYTHONPATH: '.' }
  });
}

function resetLessonCodeState() {
  runPython(`
from app import create_app
from app.lessons.lesson_socket import _load_cached_code_state, _update_cached_code_state
app = create_app()
with app.app_context():
    st = _load_cached_code_state(${lessonId}) or {}
    files = dict(st.get("files") or {})
    files.pop("helper.py", None)
    open_tabs = [t for t in (st.get("open_tabs") or ["main.py"]) if t != "helper.py"]
    if not open_tabs:
        open_tabs = ["main.py"]
    deleted = [f for f in (st.get("deleted_files") or []) if f != "helper.py"]
    new_rev = int(st.get("revision") or 0) + 1
    _update_cached_code_state(${lessonId}, {
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

function setupSubmissionFixture(options: {
  status?: string;
  studentCodes?: Record<number, string>;
  extraFiles?: Record<number, Record<string, string>>;
  needsRevisionMap?: Record<number, boolean>;
  attemptsCount?: number;
} = {}) {
  const status = options.status || 'IN_PROGRESS';
  const codesB64 = Buffer.from(JSON.stringify(options.studentCodes || {})).toString('base64');
  const extraFilesB64 = Buffer.from(JSON.stringify(options.extraFiles || {})).toString('base64');
  const revMapB64 = Buffer.from(JSON.stringify(options.needsRevisionMap || {})).toString('base64');
  const attemptsCount = options.attemptsCount ?? 0;

  runPython(`
import json
import base64
from app import create_app, db
from core.db_models import Submission, Answer, SubmissionAttempt, LessonParticipantBan
from app.runtime_state import get_redis_client

app = create_app()
with app.app_context(), app.test_request_context():
    for b in LessonParticipantBan.query.filter_by(lesson_id=${lessonId}).all():
        b.is_active = False

    sub = Submission.query.get(${submissionId})
    if sub:
        sub.student_id = 630 # qa_pool_student_1
        sub.status = '${status}'
        sub.total_score = None
        sub.max_score = 5
        sub.percentage = None
        sub.teacher_feedback = 'Пожалуйста, проверьте код.' if '${status}' == 'RETURNED' else ''

        codes = json.loads(base64.b64decode('${codesB64}').decode('utf-8'))
        extra_files_map = json.loads(base64.b64decode('${extraFilesB64}').decode('utf-8'))
        rev_map = json.loads(base64.b64decode('${revMapB64}').decode('utf-8'))

        for at_id in [${task1AtId}, ${task2AtId}, 2838, 2839, 2840]:
            ans = Answer.query.filter_by(submission_id=sub.submission_id, assignment_task_id=at_id).first()
            if not ans:
                ans = Answer(submission_id=sub.submission_id, assignment_task_id=at_id, max_score=1)
                db.session.add(ans)
            
            str_id = str(at_id)
            if str_id in codes:
                ans.student_code = codes[str_id]
                ans.student_code_saved_at = db.func.now()
            else:
                ans.student_code = None
                ans.student_code_saved_at = None

            ans.needs_revision = bool(rev_map.get(str_id, False))
            ans.value = '42' if str_id in codes else ''
            ans.score = 1 if not ans.needs_revision and '${status}' in ['SUBMITTED', 'GRADED'] else 0

        # Reset attempts
        SubmissionAttempt.query.filter_by(submission_id=sub.submission_id).delete()
        if ${attemptsCount} >= 1:
            task_data = {}
            for at_id in [${task1AtId}, ${task2AtId}]:
                str_id = str(at_id)
                c1 = '# Attempt 1 code' if ${attemptsCount} > 1 else codes.get(str_id, '# Attempt 1 code')
                task_data[str_id] = {
                    'student_code': c1,
                    'files': {'main.py': c1},
                    'answer': '42',
                    'score': 1,
                    'max_score': 1
                }
            att1 = SubmissionAttempt(
                submission_id=sub.submission_id,
                attempt_no=1,
                status='RETURNED' if ${attemptsCount} > 1 else '${status}',
                total_score=2,
                max_score=5,
                percentage=40.0,
                teacher_feedback='Первая попытка: доработать второе задание',
                attempt_data={'tasks': task_data}
            )
            db.session.add(att1)

        if ${attemptsCount} >= 2:
            task_data2 = {}
            for at_id in [${task1AtId}, ${task2AtId}]:
                str_id = str(at_id)
                c = codes.get(str_id, '# Attempt 2 code')
                task_data2[str_id] = {
                    'student_code': c,
                    'files': {'main.py': c},
                    'answer': '42',
                    'score': 2,
                    'max_score': 1
                }
            att2 = SubmissionAttempt(
                submission_id=sub.submission_id,
                attempt_no=2,
                status='${status}',
                total_score=4,
                max_score=5,
                percentage=80.0,
                teacher_feedback='Вторая попытка: отлично',
                attempt_data={'tasks': task_data2}
            )
            db.session.add(att2)

        db.session.commit()

        # Store versions with extra files in SQLite so all server processes access preserved secondary files
        from app.task_workspace.service import resolve_workspace_context, cache_workspace_snapshot, clear_cached_workspace_snapshot
        from core.db_models import User, CodeWorkspaceVersion
        stu = User.query.filter_by(username="${studentUsername}").first()
        for at_id in [${task1AtId}, ${task2AtId}, 2838, 2839, 2840]:
            ctx = resolve_workspace_context(stu, "submission_task", sub.submission_id, at_id)
            clear_cached_workspace_snapshot(ctx)
            str_id = str(at_id)
            if str_id in extra_files_map:
                files = {'main.py': codes.get(str_id, '')}
                files.update(extra_files_map[str_id])
                cache_workspace_snapshot(ctx, codes.get(str_id, ''), '42', files=files, revision=1)
                snap = {'files': files, 'open_tabs': ['main.py'], 'active_file': 'main.py', 'revision': 1}
                CodeWorkspaceVersion.query.filter_by(
                    context_type=ctx.context_type,
                    context_id=ctx.assignment_task_id,
                    task_id=ctx.task_id
                ).delete()
                wv = CodeWorkspaceVersion(
                    context_type=ctx.context_type,
                    context_id=ctx.assignment_task_id,
                    task_id=ctx.task_id,
                    student_id=ctx.student_id,
                    student_user_id=ctx.student_user_id,
                    answer_id=ctx.answer_id,
                    code=codes.get(str_id, ''),
                    answer='42',
                    source='autosave',
                    snapshot=snap
                )
                db.session.add(wv)
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

async function setEditorCode(page: Page, code: string) {
  await page.evaluate((val) => {
    if (typeof (window as any).setEditorMainPyCode === 'function') {
      (window as any).setEditorMainPyCode(val);
      if (typeof (window as any).onCodeEditorInput === 'function') {
        (window as any).onCodeEditorInput(val);
      }
    } else {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      if (ta) {
        ta.value = val;
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
  }, code);
}

async function getEditorCode(page: Page): Promise<string> {
  return await page.evaluate(() => {
    if (typeof (window as any).getEditorMainPyCode === 'function') {
      return (window as any).getEditorMainPyCode();
    }
    const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
    return ta ? ta.value : '';
  });
}

async function ensureCodeWindowOpen(page: Page) {
  const codeWin = page.locator('#code-window');
  if (!(await codeWin.isVisible())) {
    await page.evaluate(() => {
      if (typeof (window as any).openWindow === 'function') {
        (window as any).openWindow('code-window');
      }
    });
  }
  await expect(codeWin).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

test.describe('Homework OS Single-File Verification Suite', () => {
  test.setTimeout(90_000);

  test.beforeEach(async () => {
    resetLessonCodeState();
  });

  test('HW-SINGLE-01: UI Architecture Validation (Single-file header, no tab bar, no file creation/deletion)', async ({ page }) => {
    setupSubmissionFixture({ status: 'IN_PROGRESS' });
    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // 1. Homework OS must display single-file header with main.py badge
    const hwHeader = page.locator('#hw-single-file-header');
    await expect(hwHeader).toBeVisible();
    await expect(hwHeader).toContainText('main.py');

    // 2. Autosave indicator must be present in header
    const saveIndicator = page.locator('#hw-code-save-indicator');
    await expect(saveIndicator).toBeVisible();

    // 3. Multi-file tabs bar list must NOT be rendered in Homework OS
    const tabsList = page.locator('#editor-tabs-list');
    await expect(tabsList).not.toBeVisible();

    // 4. File creation modal must NOT be rendered
    const newFileModal = page.locator('#lesson-vfs-new-file-modal');
    await expect(newFileModal).not.toBeAttached();

    // 5. File explorer button in sidebar palette must NOT be rendered
    const explorerBtn = page.locator('#sidebar-tools-palette button[title*="Проводник"]');
    await expect(explorerBtn).not.toBeAttached();

    // 6. Explorer drawer content must NOT be rendered
    const explorerDrawer = page.locator('#drawer-content-explorer');
    await expect(explorerDrawer).not.toBeAttached();
  });

  test('HW-SINGLE-02: Single-File Editing & Input verification', async ({ page }) => {
    setupSubmissionFixture({ status: 'IN_PROGRESS' });
    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    const testCode = 'print("Hello from HW-SINGLE-02")\nresult = 42\n';
    await setEditorCode(page, testCode);

    const currentCode = await getEditorCode(page);
    expect(currentCode).toBe(testCode);

    // Trigger save and verify saved indicator
    await page.evaluate(async () => {
      if (typeof (window as any).flushHomeworkCode === 'function') {
        await (window as any).flushHomeworkCode();
      }
    });

    const indicator = page.locator('#hw-code-save-indicator');
    await expect(indicator).toContainText('Сохранено');
  });

  test('HW-SINGLE-03 & HW-SINGLE-04: Per-Task Isolation and Task Switching Integrity', async ({ page }) => {
    setupSubmissionFixture({
      status: 'IN_PROGRESS',
      studentCodes: {
        [task1AtId]: 'print("FIRST_TASK_CODE")',
        [task2AtId]: 'print("SECOND_TASK_CODE")',
      }
    });

    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // 1. Task 1 code verification
    let code1 = await getEditorCode(page);
    expect(code1).toContain('FIRST_TASK_CODE');

    // 2. Switch to Task 2
    const task2Tab = page.locator(`.homework-os-task-tab[data-task-id="${task2AtId}"]`);
    await task2Tab.click();
    await expect(page.locator('#task-current-title')).toContainText('Задание 2', { timeout: 10_000 });

    // Task 2 must show its own code and NOT Task 1 code
    let code2 = await getEditorCode(page);
    expect(code2).toContain('SECOND_TASK_CODE');
    expect(code2).not.toContain('FIRST_TASK_CODE');

    // 3. Edit Task 2 code
    await setEditorCode(page, 'print("SECOND_TASK_CODE_MODIFIED")\n');
    await page.evaluate(async () => {
      if (typeof (window as any).flushHomeworkCode === 'function') {
        await (window as any).flushHomeworkCode();
      }
    });

    // 4. Switch back to Task 1
    const task1Tab = page.locator(`.homework-os-task-tab[data-task-id="${task1AtId}"]`);
    await task1Tab.click();
    await expect(page.locator('#task-current-title')).toContainText('Задание 1', { timeout: 10_000 });

    // Task 1 code must be completely intact
    code1 = await getEditorCode(page);
    expect(code1).toContain('FIRST_TASK_CODE');
    expect(code1).not.toContain('MODIFIED');

    // 5. Switch back to Task 2
    await task2Tab.click();
    await expect(page.locator('#task-current-title')).toContainText('Задание 2', { timeout: 10_000 });

    // Task 2 must retain the modified code
    code2 = await getEditorCode(page);
    expect(code2).toContain('SECOND_TASK_CODE_MODIFIED');
  });

  test('HW-SINGLE-05: Page Reload Persistence across multiple tasks', async ({ page }) => {
    setupSubmissionFixture({
      status: 'IN_PROGRESS',
      studentCodes: {
        [task1AtId]: 'print("PERSIST_TASK_1")',
        [task2AtId]: 'print("PERSIST_TASK_2")',
      }
    });

    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Check Task 1 after load
    expect(await getEditorCode(page)).toContain('PERSIST_TASK_1');

    // Reload page
    await page.reload({ waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Verify Task 1 code persisted
    expect(await getEditorCode(page)).toContain('PERSIST_TASK_1');

    // Switch to Task 2 and verify its code persisted
    const task2Tab = page.locator(`.homework-os-task-tab[data-task-id="${task2AtId}"]`);
    await task2Tab.click();
    await page.waitForTimeout(600);
    expect(await getEditorCode(page)).toContain('PERSIST_TASK_2');
  });

  test('HW-SINGLE-06 & HW-SINGLE-08: Instant Submit After Edit & Post-Submit Locking', async ({ page }) => {
    setupSubmissionFixture({
      status: 'IN_PROGRESS',
      studentCodes: {
        [task1AtId]: 'print("CODE_FOR_SUBMIT_T1")',
        [task2AtId]: 'print("CODE_FOR_SUBMIT_T2")',
      }
    });

    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task2AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Type immediate edit in Task 2
    const instantCode = 'print("INSTANT_SUBMIT_TASK_2")\n';
    await setEditorCode(page, instantCode);

    // Immediately click submit button without waiting for autosave
    const submitBtn = page.locator('#homework-submit');
    await submitBtn.click();

    // Confirmation modal must appear
    const modal = page.locator('#homework-submitted-modal');
    await expect(modal).toBeVisible({ timeout: 10_000 });
    await expect(modal.locator('#hw-post-submit-title')).toContainText('Работа успешно отправлена!');

    // Click stay button
    const stayBtn = modal.locator('#hw-post-submit-stay');
    await stayBtn.click();
    await expect(modal).not.toBeVisible();

    // Submit button must be disabled and show "Работа сдана"
    await expect(submitBtn).toBeDisabled();
    await expect(submitBtn).toContainText('Работа сдана');

    // Editor must be locked (read-only)
    const isReadOnly = await page.evaluate(() => {
      const ed = (window as any).codeEditor;
      if (ed && typeof ed.getOption === 'function') {
        return ed.getOption('readOnly') === true;
      }
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return ta ? ta.readOnly : false;
    });
    expect(isReadOnly).toBe(true);

    // Check DB has the submitted code for Task 2
    const dbCode = runPython(`
from app import create_app, db
from core.db_models import Answer
app = create_app()
with app.app_context():
    ans = Answer.query.filter_by(submission_id=${submissionId}, assignment_task_id=${task2AtId}).first()
    print(ans.student_code if ans else '')
`);
    expect(dbCode).toContain('INSTANT_SUBMIT_TASK_2');
  });

  test('HW-SINGLE-07: Teacher Review Fidelity (Exact task code, no tab bars)', async ({ page }) => {
    setupSubmissionFixture({
      status: 'SUBMITTED',
      studentCodes: {
        [task1AtId]: 'print("STUDENT_T1_FOR_REVIEW")',
        [task2AtId]: 'print("STUDENT_T2_FOR_REVIEW")',
      }
    });

    await login(page, tutorUsername);
    const reviewUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&review=1`;
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Review window must be visible
    await expect(page.locator('#review-grade-window')).toBeVisible({ timeout: 10_000 });

    // 1. Task 1 code check
    expect(await getEditorCode(page)).toContain('STUDENT_T1_FOR_REVIEW');

    // 2. Switch to Task 2
    const task2Tab = page.locator(`.homework-os-task-tab[data-task-id="${task2AtId}"]`);
    await task2Tab.click();
    await page.waitForTimeout(600);

    // 3. Task 2 code check
    expect(await getEditorCode(page)).toContain('STUDENT_T2_FOR_REVIEW');

    // 4. In review mode, no multi-file tabs bar
    await expect(page.locator('#editor-tabs-list')).not.toBeVisible();
    await expect(page.locator('#hw-single-file-header')).toBeVisible();
  });

  test('HW-SINGLE-09: Partial Revision (Returned Task Editable, Non-Returned Read-Only)', async ({ page }) => {
    // Setup partial revision: Task 2 needs revision, Task 1 is accepted
    setupSubmissionFixture({
      status: 'RETURNED',
      studentCodes: {
        [task1AtId]: 'print("ACCEPTED_TASK_1")',
        [task2AtId]: 'print("NEEDS_REVISION_TASK_2")',
      },
      needsRevisionMap: {
        [task2AtId]: true,
        [task1AtId]: false,
      }
    });

    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Task 1: read-only
    const t1ReadOnly = await page.evaluate(() => {
      const ed = (window as any).codeEditor;
      if (ed && typeof ed.getOption === 'function') {
        return ed.getOption('readOnly') === true;
      }
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return ta ? ta.readOnly : false;
    });
    expect(t1ReadOnly).toBe(true);

    // Switch to Task 2
    const task2Tab = page.locator(`.homework-os-task-tab[data-task-id="${task2AtId}"]`);
    await task2Tab.click();
    await page.waitForTimeout(600);

    // Task 2: must be EDITABLE
    const t2ReadOnly = await page.evaluate(() => {
      const ed = (window as any).codeEditor;
      if (ed && typeof ed.getOption === 'function') {
        return ed.getOption('readOnly') === true;
      }
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return ta ? ta.readOnly : false;
    });
    expect(t2ReadOnly).toBe(false);

    // Task 2 code is preserved
    expect(await getEditorCode(page)).toContain('NEEDS_REVISION_TASK_2');

    // Student can edit Task 2
    await setEditorCode(page, 'print("REVISED_TASK_2_NEW_CODE")\n');
    expect(await getEditorCode(page)).toContain('REVISED_TASK_2_NEW_CODE');
  });

  test('HW-SINGLE-10: Full Revision (All Tasks Editable)', async ({ page }) => {
    setupSubmissionFixture({
      status: 'RETURNED',
      studentCodes: {
        [task1AtId]: 'print("FULL_REV_TASK_1")',
        [task2AtId]: 'print("FULL_REV_TASK_2")',
      },
      needsRevisionMap: {} // All tasks editable
    });

    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Task 1: editable
    const t1ReadOnly = await page.evaluate(() => {
      const ed = (window as any).codeEditor;
      if (ed && typeof ed.getOption === 'function') {
        return ed.getOption('readOnly') === true;
      }
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return ta ? ta.readOnly : false;
    });
    expect(t1ReadOnly).toBe(false);

    // Switch to Task 2: editable
    const task2Tab = page.locator(`.homework-os-task-tab[data-task-id="${task2AtId}"]`);
    await task2Tab.click();
    await page.waitForTimeout(600);

    const t2ReadOnly = await page.evaluate(() => {
      const ed = (window as any).codeEditor;
      if (ed && typeof ed.getOption === 'function') {
        return ed.getOption('readOnly') === true;
      }
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return ta ? ta.readOnly : false;
    });
    expect(t2ReadOnly).toBe(false);
  });

  test('HW-SINGLE-11 & HW-SINGLE-12: Resubmission Versioning and Historical Attempt Inspection', async ({ page }) => {
    // Setup with 2 historical attempts
    setupSubmissionFixture({
      status: 'GRADED',
      studentCodes: {
        [task1AtId]: 'print("ATTEMPT_2_TASK_1")',
        [task2AtId]: 'print("ATTEMPT_2_TASK_2")',
      },
      attemptsCount: 2
    });

    await login(page, tutorUsername);
    const reviewUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&review=1`;
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Verify attempts list card
    const attemptsCard = page.locator('#review-attempts-history-card');
    await expect(attemptsCard).toBeVisible({ timeout: 10_000 });

    // Verify 2 attempts badge
    const badge = page.locator('#review-attempts-count-badge');
    await expect(badge).toContainText('2 попытки');

    // Current code before clicking archive is Attempt 2 code
    expect(await getEditorCode(page)).toContain('ATTEMPT_2_TASK_1');

    // Click Attempt 1 in the list
    const attempt1Item = page.locator('#review-attempts-list div[data-attempt-no="1"]');
    await attempt1Item.scrollIntoViewIfNeeded();
    await attempt1Item.evaluate(el => (el as HTMLElement).click());

    // Archive banner must appear
    const banner = page.locator('#review-attempt-archive-banner');
    await expect(banner).toBeVisible({ timeout: 5_000 });
    await expect(banner).toContainText('Попытки #1');

    // Editor should display Attempt 1 code
    expect(await getEditorCode(page)).toContain('Attempt 1 code');

    // Click "Вернуться к текущему состоянию"
    const restoreBtn = banner.locator('#review-attempt-restore-current-btn');
    await restoreBtn.click();

    // Banner removed, Attempt 2 code restored
    await expect(banner).not.toBeVisible();
    expect(await getEditorCode(page)).toContain('ATTEMPT_2_TASK_1');
  });

  test('HW-SINGLE-13: Preserved Secondary Files Accessible via Read-Only Archive', async ({ page }) => {
    setupSubmissionFixture({
      status: 'IN_PROGRESS',
      studentCodes: {
        [task1AtId]: 'print("MAIN_CODE_WITH_ARCHIVE")',
      },
      extraFiles: {
        [task1AtId]: {
          'helper.py': 'def helper(): return "archive_helper_content"\n',
          'notes.txt': 'historical notes from multi-file\n'
        }
      }
    });

    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Verify "Архив файлов (2)" button is visible in single-file header
    const archiveBtn = page.locator('#hw-archived-files-btn');
    await expect(archiveBtn).toBeVisible({ timeout: 10_000 });
    await expect(archiveBtn).toContainText('Архив файлов (2)');

    // Click archive button to open modal
    await archiveBtn.click();
    const modal = page.locator('#hw-archived-files-modal');
    await expect(modal).toBeVisible();

    // Verify helper.py and notes.txt are listed
    const listEl = page.locator('#hw-archived-files-list');
    await expect(listEl).toContainText('helper.py');
    await expect(listEl).toContainText('notes.txt');

    // Viewer displays file content
    const viewer = page.locator('#hw-archived-file-viewer');
    await expect(viewer).toHaveValue(/archive_helper_content/);

    // Close modal
    const closeBtn = page.locator('#hw-archived-files-close');
    await closeBtn.click();
    await expect(modal).not.toBeVisible();
  });

  test('HW-SINGLE-14: Resilience Against Revision Conflict (HTTP 409 handled without code drop)', async ({ page }) => {
    setupSubmissionFixture({
      status: 'IN_PROGRESS',
      studentCodes: {
        [task1AtId]: 'print("REV_TEST")',
      }
    });

    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(page);

    // Manually increment server revision behind client's back to simulate stale revision
    runPython(`
from app import create_app
from app.task_workspace.service import resolve_workspace_context, cache_workspace_snapshot, load_workspace_multi_file_state
from core.db_models import User
app = create_app()
with app.app_context(), app.test_request_context():
    stu = User.query.filter_by(username="${studentUsername}").first()
    ctx = resolve_workspace_context(stu, "submission_task", ${submissionId}, ${task1AtId})
    mf = load_workspace_multi_file_state(ctx)
    cache_workspace_snapshot(ctx, "print('REV_TEST')", "", revision=99)
`);

    // Client edits code and triggers autosave
    await setEditorCode(page, 'print("RESOLVED_AFTER_409")\n');
    await page.evaluate(async () => {
      if (typeof (window as any).flushHomeworkCode === 'function') {
        await (window as any).flushHomeworkCode();
      }
    });

    // Client must absorb revision and complete save successfully
    const saveIndicator = page.locator('#hw-code-save-indicator');
    await expect(saveIndicator).toContainText('Сохранено', { timeout: 10_000 });

    // In DB, code must be updated
    const dbCode = runPython(`
from app import create_app, db
from core.db_models import Answer
app = create_app()
with app.app_context():
    ans = Answer.query.filter_by(submission_id=${submissionId}, assignment_task_id=${task1AtId}).first()
    print(ans.student_code if ans else '')
`);
    expect(dbCode).toContain('RESOLVED_AFTER_409');
  });

  test('HW-SINGLE-15: Lesson OS Multi-File Regression Guard (Lesson room tabs, create, switch, delete intact)', async ({ browser }) => {
    test.skip(true, 'Superseded by Unified Single-File Lesson OS contract (PAGE-01 in test_unified_editor_and_windows.spec.ts)');
    const teacherContext = await browser.newContext();
    const teacherPage = await teacherContext.newPage();
    await login(teacherPage, tutorUsername);

    const studentContext = await browser.newContext();
    const studentPage = await studentContext.newPage();
    await login(studentPage, studentUsername);

    // Open Lesson OS room for both
    await teacherPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    await studentPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    // In Lesson OS, tabs list must be present
    await expect(teacherPage.locator('#editor-tabs-list')).toBeVisible();
    await expect(studentPage.locator('#editor-tabs-list')).toBeVisible();

    // Teacher creates helper.py in Lesson OS
    await teacherPage.evaluate(() => {
      (window as any).createNewFileOfType('py', 'collab_helper.py');
    });

    // Tab appears for teacher and student
    const teacherTab = teacherPage.locator('.editor-tab:has-text("collab_helper.py")');
    const studentTab = studentPage.locator('.editor-tab:has-text("collab_helper.py")');
    await expect(teacherTab).toBeVisible({ timeout: 10_000 });
    await expect(studentTab).toBeVisible({ timeout: 10_000 });

    // Delete file
    await teacherPage.evaluate(() => {
      (window as any).deleteFileFromVFS(null, 'collab_helper.py', true);
    });

    await expect(teacherTab).not.toBeVisible({ timeout: 10_000 });
    await expect(studentTab).not.toBeVisible({ timeout: 10_000 });

    await teacherContext.close();
    await studentContext.close();
  });

  test('HW-SINGLE-E2E: Complete Owner Retest User Journey', async ({ browser }) => {
    // 1. Initial State: 2 tasks in progress
    setupSubmissionFixture({
      status: 'IN_PROGRESS',
      studentCodes: {}
    });

    const studentContext = await browser.newContext();
    const studentPage = await studentContext.newPage();
    await login(studentPage, studentUsername);

    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await studentPage.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(studentPage);

    // 2. Student writes code in Task 1
    await setEditorCode(studentPage, 'print("FIRST_TASK")\n');
    await studentPage.evaluate(async () => {
      if (typeof (window as any).flushHomeworkCode === 'function') {
        await (window as any).flushHomeworkCode();
      }
    });

    // 3. Fast switch to Task 2
    const task2Tab = studentPage.locator(`.homework-os-task-tab[data-task-id="${task2AtId}"]`);
    await task2Tab.click();
    await expect(studentPage.locator('#task-current-title')).toContainText('Задание 2', { timeout: 10_000 });

    // 4. Student writes code in Task 2
    await setEditorCode(studentPage, 'print("SECOND_TASK")\n');
    await studentPage.evaluate(async () => {
      if (typeof (window as any).flushHomeworkCode === 'function') {
        await (window as any).flushHomeworkCode();
      }
    });

    // 5. Fast switch back to Task 1 and verify
    const task1Tab = studentPage.locator(`.homework-os-task-tab[data-task-id="${task1AtId}"]`);
    await task1Tab.click();
    await expect(studentPage.locator('#task-current-title')).toContainText('Задание 1', { timeout: 10_000 });
    expect(await getEditorCode(studentPage)).toContain('FIRST_TASK');

    // 6. Fast switch back to Task 2, edit and instant submit
    await task2Tab.click();
    await expect(studentPage.locator('#task-current-title')).toContainText('Задание 2', { timeout: 10_000 });
    expect(await getEditorCode(studentPage)).toContain('SECOND_TASK');

    await setEditorCode(studentPage, 'print("SECOND_TASK_EDITED")\n');
    await studentPage.waitForTimeout(500);
    const submitBtn = studentPage.locator('#homework-submit');
    await submitBtn.evaluate(el => (el as HTMLElement).click());

    // Confirm submission modal
    const modal = studentPage.locator('#homework-submitted-modal');
    await expect(modal).toBeVisible({ timeout: 10_000 });
    const stayBtn = modal.locator('#hw-post-submit-stay');
    await stayBtn.click();
    await expect(modal).not.toBeVisible();

    // 7. Reload page: check both codes are preserved and locked
    await studentPage.reload({ waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(studentPage);
    expect(await getEditorCode(studentPage)).toContain('SECOND_TASK_EDITED');

    await task1Tab.click();
    await expect(studentPage.locator('#task-current-title')).toContainText('Задание 1', { timeout: 10_000 });
    expect(await getEditorCode(studentPage)).toContain('FIRST_TASK');

    // 8. Teacher opens review
    const teacherContext = await browser.newContext();
    const teacherPage = await teacherContext.newPage();
    await login(teacherPage, tutorUsername);

    const reviewUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&review=1`;
    await teacherPage.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(teacherPage);

    // Teacher sees FIRST_TASK on Task 1
    expect(await getEditorCode(teacherPage)).toContain('FIRST_TASK');

    // Teacher switches to Task 2: sees SECOND_TASK_EDITED
    const teacherTask2Tab = teacherPage.locator(`.homework-os-task-tab[data-task-id="${task2AtId}"]`);
    await teacherTask2Tab.click();
    await expect(teacherPage.locator('#task-current-title')).toContainText('Задание 2', { timeout: 10_000 });
    expect(await getEditorCode(teacherPage)).toContain('SECOND_TASK_EDITED');

    // 9. Teacher returns Task 2 on revision via API / DB
    runPython(`
from app import create_app, db
from core.db_models import Submission, Answer
app = create_app()
with app.app_context():
    sub = Submission.query.get(${submissionId})
    sub.status = 'RETURNED'
    sub.teacher_feedback = 'Доработайте задание 2'
    ans2 = Answer.query.filter_by(submission_id=${submissionId}, assignment_task_id=${task2AtId}).first()
    if ans2:
        ans2.needs_revision = True
        ans2.teacher_comment = 'Исправьте алгоритм'
    db.session.commit()
`);

    // 10. Student opens homework: Task 2 is editable, Task 1 is read-only
    await studentPage.reload({ waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(studentPage);

    // Task 1 is read-only
    const sT1ReadOnly = await studentPage.evaluate(() => {
      const ed = (window as any).codeEditor;
      if (ed && typeof ed.getOption === 'function') {
        return ed.getOption('readOnly') === true;
      }
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return ta ? ta.readOnly : false;
    });
    expect(sT1ReadOnly).toBe(true);

    // Switch to Task 2: editable!
    await task2Tab.click();
    await expect(studentPage.locator('#task-current-title')).toContainText('Задание 2', { timeout: 10_000 });

    const sT2ReadOnly = await studentPage.evaluate(() => {
      const ed = (window as any).codeEditor;
      if (ed && typeof ed.getOption === 'function') {
        return ed.getOption('readOnly') === true;
      }
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return ta ? ta.readOnly : false;
    });
    expect(sT2ReadOnly).toBe(false);

    // 11. Student updates Task 2 to SECOND_TASK_RESUBMITTED and resubmits
    await setEditorCode(studentPage, 'print("SECOND_TASK_RESUBMITTED")\n');
    const resubmitBtn = studentPage.locator('#homework-submit');
    await resubmitBtn.click();

    const resubmitModal = studentPage.locator('#homework-submitted-modal');
    await expect(resubmitModal).toBeVisible({ timeout: 10_000 });

    // 12. Teacher reloads review: verifies Attempt #1 vs Attempt #2
    await teacherPage.reload({ waitUntil: 'domcontentloaded' });
    await ensureCodeWindowOpen(teacherPage);

    // Teacher on Task 2 sees latest SECOND_TASK_RESUBMITTED
    await teacherTask2Tab.click();
    await teacherPage.waitForTimeout(400);
    expect(await getEditorCode(teacherPage)).toContain('SECOND_TASK_RESUBMITTED');

    // Teacher clicks Attempt #1 in history
    const att1Item = teacherPage.locator('#review-attempts-list div[data-attempt-no="1"]');
    if (await att1Item.isVisible()) {
      await att1Item.evaluate(el => (el as HTMLElement).click());
      const archiveBanner = teacherPage.locator('#review-attempt-archive-banner');
      await expect(archiveBanner).toBeVisible();

      // Attempt 1 had SECOND_TASK_EDITED
      expect(await getEditorCode(teacherPage)).toContain('SECOND_TASK_EDITED');

      // Return to live state
      await archiveBanner.locator('#review-attempt-restore-current-btn').evaluate(el => (el as HTMLElement).click());
      await expect(archiveBanner).not.toBeVisible();
      expect(await getEditorCode(teacherPage)).toContain('SECOND_TASK_RESUBMITTED');
    }

    await studentContext.close();
    await teacherContext.close();
  });
});
