import { expect, Page, BrowserContext, test } from '@playwright/test';
import { execSync } from 'child_process';

const password = process.env.BOOSTUDY_E2E_PASSWORD || '123456';
const tutorUsername = process.env.BOOSTUDY_E2E_TUTOR || 'qa_pool_tutor_1';
const studentUsername = process.env.BOOSTUDY_E2E_STUDENT || 'qa_pool_student_1';
const lessonId = 2168;
const lessonRoomUrl = `/lesson/${lessonId}/room`;
const assignmentId = 2712;
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

function reset5TaskSubmissionFixture(status = 'SUBMITTED', resultsPublished = false) {
  runPython(`
from app import create_app, db
from core.db_models import Assignment, AssignmentTask, Submission, Answer, SubmissionAttempt, LessonParticipantBan

app = create_app()
with app.app_context():
    for b in LessonParticipantBan.query.filter_by(lesson_id=2168).all():
        b.is_active = False
    
    sub = Submission.query.get(${submissionId})
    if sub:
        sub.status = '${status}'
        sub.total_score = 3
        sub.max_score = 5
        sub.percentage = 60.0
        sub.results_published_at = db.func.now() if ${resultsPublished ? 'True' : 'False'} else None
        
        answers_map = {
            2832: {'val': '460', 'score': 1, 'cor': True, 'rev': False},
            2837: {'val': '999', 'score': 0, 'cor': False, 'rev': False},
            2838: {'val': '7', 'score': 1, 'cor': True, 'rev': False},
            2839: {'val': '999', 'score': 0, 'cor': False, 'rev': False},
            2840: {'val': '47', 'score': 1, 'cor': True, 'rev': False},
        }
        for at_id, data in answers_map.items():
            ans = Answer.query.filter_by(submission_id=sub.submission_id, assignment_task_id=at_id).first()
            if not ans:
                ans = Answer(submission_id=sub.submission_id, assignment_task_id=at_id, max_score=1)
                db.session.add(ans)
            ans.value = data['val']
            ans.score = data['score']
            ans.is_correct = data['cor']
            ans.needs_revision = data['rev']
            ans.teacher_comment = 'Требуется исправление' if data['cor'] is False else 'Верно'
        
        for a in SubmissionAttempt.query.filter_by(submission_id=sub.submission_id).all():
            if a.attempt_no > 1:
                db.session.delete(a)
        att1 = SubmissionAttempt.query.filter_by(submission_id=sub.submission_id, attempt_no=1).first()
        if not att1:
            att1 = SubmissionAttempt(submission_id=sub.submission_id, attempt_no=1, status='SUBMITTED', total_score=3, max_score=5, percentage=60.0)
            db.session.add(att1)
        else:
            att1.status = 'SUBMITTED'
            att1.total_score = 3
            att1.max_score = 5
            att1.percentage = 60.0

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

test.describe('R0.3.2 Owner Retest Blockers Suite', () => {
  test.setTimeout(90_000);

  test.beforeEach(async () => {
    clearBans();
    resetLessonCodeState();
  });

  test('VFS-01: Teacher deletes helper.py, student must not resurrect file via stale tab', async ({ browser }) => {
    // Teacher context
    const teacherContext = await browser.newContext();
    const teacherPage = await teacherContext.newPage();
    await login(teacherPage, tutorUsername);

    // Student context
    const studentContext = await browser.newContext();
    const studentPage = await studentContext.newPage();
    await login(studentPage, studentUsername);

    // Both open Lesson Room
    await teacherPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    await studentPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    // 1. Teacher creates helper.py via createNewFileOfType
    await teacherPage.evaluate(() => {
      if ((window as any).virtualFS && (window as any).virtualFS['helper.py'] !== undefined) {
        delete (window as any).virtualFS['helper.py'];
      }
      (window as any).createNewFileOfType('py', 'helper.py');
    });
    // Wait for helper.py tab to exist on teacher
    const teacherHelperTab = teacherPage.locator('.editor-tab:has-text("helper.py"), [id="tab-helper.py"]');
    await expect(teacherHelperTab).toBeVisible({ timeout: 10_000 });

    // Helper tab should appear on student
    const studentHelperTab = studentPage.locator('.editor-tab:has-text("helper.py"), [id="tab-helper.py"]');
    await expect(studentHelperTab).toBeVisible({ timeout: 10_000 });

    // 2. Teacher writes code into helper.py
    await teacherPage.evaluate(() => {
      (window as any).switchEditorTab(null, 'helper.py');
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      if (ta) {
        ta.value = 'def test_func():\n    return 42\n';
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await teacherPage.waitForTimeout(1000);

    // 3. Teacher deletes helper.py via UI button / deleteFileFromVFS
    await teacherPage.evaluate(() => {
      (window as any).deleteFileFromVFS(null, 'helper.py', true);
    });

    // helper.py should disappear from teacher
    await expect(teacherHelperTab).not.toBeVisible({ timeout: 5_000 });

    // helper.py MUST disappear from student
    await expect(studentHelperTab).not.toBeVisible({ timeout: 10_000 });

    // Verify virtualFS on student does not contain helper.py
    const studentHasHelper = await studentPage.evaluate(() => {
      return Boolean((window as any).virtualFS && (window as any).virtualFS['helper.py'] !== undefined);
    });
    expect(studentHasHelper).toBe(false);

    // Student switches tab or triggers save
    await studentPage.evaluate(() => {
      if (typeof (window as any).switchEditorTab === 'function') {
        (window as any).switchEditorTab(null, 'helper.py');
      }
    });
    await studentPage.waitForTimeout(1000);

    // helper.py MUST NOT be resurrected on teacher!
    await expect(teacherHelperTab).not.toBeVisible({ timeout: 3_000 });

    await teacherContext.close();
    await studentContext.close();
  });

  test('KICK-01: Teacher kicks student, teacher sees Unban button and unbans student via UI', async ({ browser }) => {
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

    // Open presence drawer on teacher
    const presenceToggle = teacherPage.locator('#lesson-os-presence-toggle');
    await presenceToggle.click();
    const presenceList = teacherPage.locator('#lesson-os-presence-list');
    await expect(presenceList).toBeVisible();

    // Teacher kicks student
    const kickBtn = teacherPage.locator('.lesson-os-kick-btn').first();
    await expect(kickBtn).toBeVisible({ timeout: 10_000 });
    await kickBtn.click();

    // Confirm glass modal
    const confirmBtn = teacherPage.locator('#glass-modal-btn-confirm');
    await expect(confirmBtn).toBeVisible({ timeout: 5_000 });
    await confirmBtn.click();

    // Student must receive kick modal
    await expect(studentPage.locator('#lesson-os-kicked-modal')).toBeVisible({ timeout: 15_000 });

    // Ensure teacher presence list is open
    if (!(await presenceList.isVisible())) {
      await presenceToggle.click();
      await expect(presenceList).toBeVisible({ timeout: 5_000 });
    }

    // Teacher presence panel MUST now show Banned section with "Разрешить вернуться" button!
    const unbanBtn = teacherPage.locator('.lesson-os-unban-btn');
    await expect(unbanBtn).toBeVisible({ timeout: 10_000 });

    // Teacher clicks "Разрешить вернуться"
    await unbanBtn.click();
    await expect(confirmBtn).toBeVisible({ timeout: 5_000 });
    await confirmBtn.click();

    // Unban button should disappear as student is no longer banned
    await expect(unbanBtn).not.toBeVisible({ timeout: 10_000 });

    // Student reloads and can rejoin without redirect
    await studentPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    await teacherContext.close();
    await studentContext.close();
  });

  test('UI-03: Homework answer window has no empty bottom white bar and guidance does not overflow', async ({ page }) => {
    await login(page, studentUsername);
    const answerUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&embedded=answer`;
    await page.goto(answerUrl, { waitUntil: 'domcontentloaded' });

    // Check .tw-bottom-bar is either not in DOM or display: none
    const bottomBar = page.locator('.tw-bottom-bar');
    const isVisible = await bottomBar.isVisible();
    expect(isVisible).toBe(false);

    // Check guidance box does not overflow horizontally
    const guidance = page.locator('.tw-answer-guidance');
    if (await guidance.isVisible()) {
      const box = await guidance.boundingBox();
      const bodyBox = await page.locator('body').boundingBox();
      if (box && bodyBox) {
        expect(box.width).toBeLessThanOrEqual(bodyBox.width);
      }
    }
  });

  test('UI-01: Universal Window Minimum Sizing enforcement across OS windows', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    const minSizes = await page.evaluate(() => {
      const WM = (window as any).WindowManager || (window as any).windowManager;
      if (!WM || typeof WM.getWindowMinSizes !== 'function') return null;
      return {
        code: WM.getWindowMinSizes('code-window', 1920, 1080),
        task: WM.getWindowMinSizes('task-window', 1920, 1080),
        answer: WM.getWindowMinSizes('homework-answer-window', 1920, 1080),
        review: WM.getWindowMinSizes('review-grade-window', 1920, 1080),
        terminal: WM.getWindowMinSizes('terminal-window', 1920, 1080),
        fallback: WM.getWindowMinSizes('unknown-window-xyz', 1920, 1080)
      };
    });

    expect(minSizes).not.toBeNull();
    expect(minSizes!.code.minWidth).toBe(440);
    expect(minSizes!.code.minHeight).toBe(280);
    expect(minSizes!.task.minWidth).toBe(380);
    expect(minSizes!.task.minHeight).toBe(240);
    expect(minSizes!.answer.minWidth).toBe(460);
    expect(minSizes!.answer.minHeight).toBe(320);
    expect(minSizes!.review.minWidth).toBe(440);
    expect(minSizes!.review.minHeight).toBe(340);
    expect(minSizes!.terminal.minWidth).toBe(360);
    expect(minSizes!.terminal.minHeight).toBe(200);
    expect(minSizes!.fallback.minWidth).toBe(280);
    expect(minSizes!.fallback.minHeight).toBe(180);
  });

  test('UI-02: Homework submitted modal has BooStudy glass styling tokens', async ({ page }) => {
    await login(page, studentUsername);
    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });

    await page.evaluate(() => {
      if (typeof (window as any).showPostSubmitConfirmation === 'function') {
        (window as any).showPostSubmitConfirmation({ status: 'GRADED', score: 5, max_score: 5, percentage: 100 });
      }
    });

    const modal = page.locator('#homework-submitted-modal');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    const card = modal.locator('.bg-white\\/95');
    await expect(card).toBeVisible();
    const classList = await card.getAttribute('class');
    expect(classList).toContain('backdrop-blur-2xl');
    expect(classList).toContain('rounded-2xl');
    expect(classList).toContain('border-white/80');

    // Click stay button
    const stayBtn = modal.locator('#hw-post-submit-stay');
    await expect(stayBtn).toBeVisible();
    await stayBtn.click();
    await expect(modal).not.toBeVisible();
  });

  test('REV-01: Read-only answer display with score badge when workspace is not editable', async ({ page }) => {
    reset5TaskSubmissionFixture('SUBMITTED');
    await login(page, studentUsername);
    const embeddedAnswerUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&embedded=answer`;
    await page.goto(embeddedAnswerUrl, { waitUntil: 'domcontentloaded' });

    const answerInput = page.locator('#tw-answer');
    await expect(answerInput).toBeVisible({ timeout: 10_000 });
    await expect(answerInput).toHaveAttribute('readonly', '');
    const classAttr = await answerInput.getAttribute('class');
    expect(classAttr).toContain('is-readonly');

    const badge = page.locator('.tw-answer-score-badge');
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('Зачтено');
  });

  test('REV-02: Return revision toggle visual state, indicator badge, and modal selected task list', async ({ page }) => {
    reset5TaskSubmissionFixture('SUBMITTED');
    await login(page, tutorUsername);
    const reviewUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&review=1`;
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 20_000 });

    const toggleLabel = page.locator('label[for="review-task-return-toggle"]');
    await expect(toggleLabel).toBeVisible({ timeout: 10_000 });

    const toggleInput = page.locator('#review-task-return-toggle');
    const badge = page.locator('#review-task-return-status-badge');

    // Ensure initial unselected state
    if (await toggleInput.isChecked()) {
      await toggleLabel.click();
    }
    await expect(toggleInput).not.toBeChecked();
    await expect(badge).toHaveClass(/hidden/);

    // Click to select for return
    await toggleLabel.click();
    await expect(toggleInput).toBeChecked();
    await expect(badge).not.toHaveClass(/hidden/);
    await expect(badge).toContainText('ВЫБРАНО');

    // Open return revision modal and verify selected tasks list
    await page.evaluate(() => {
      if (typeof (window as any).showReturnRevisionModal === 'function') {
        (window as any).showReturnRevisionModal(() => {});
      }
    });

    const returnModal = page.locator('#homework-return-modal');
    await expect(returnModal).toBeVisible({ timeout: 5_000 });

    const selectedSummary = returnModal.locator('#homework-return-selected-tasks-summary');
    await expect(selectedSummary).toBeVisible();
    await expect(selectedSummary).toContainText('Задание 1');

    // Close modal via cancel button
    const cancelBtn = returnModal.locator('#hw-return-cancel-btn');
    await cancelBtn.click();
    await expect(returnModal).not.toBeVisible();
  });

  test('ATT-01: Interactive attempt history switching with archive banner rollback', async ({ page }) => {
    runPython(`
from app import create_app, db
from app.models import Submission, SubmissionAttempt
from datetime import datetime, timezone
app = create_app()
with app.app_context():
    sub = db.session.get(Submission, ${submissionId})
    existing = SubmissionAttempt.query.filter_by(submission_id=${submissionId}).count()
    if existing < 2:
        SubmissionAttempt.query.filter_by(submission_id=${submissionId}).delete()
        a1 = SubmissionAttempt(
            submission_id=${submissionId},
            attempt_no=1,
            submitted_at=datetime.now(timezone.utc),
            status='RETURNED',
            total_score=4,
            max_score=10,
            percentage=40,
            teacher_feedback='Попытка 1: доработать'
        )
        a2 = SubmissionAttempt(
            submission_id=${submissionId},
            attempt_no=2,
            submitted_at=datetime.now(timezone.utc),
            status='SUBMITTED',
            total_score=8,
            max_score=10,
            percentage=80,
            teacher_feedback='Попытка 2'
        )
        db.session.add_all([a1, a2])
        db.session.commit()
`);

    await login(page, tutorUsername);
    const reviewUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&review=1`;
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#review-grade-window')).toBeVisible({ timeout: 20_000 });

    const historyCard = page.locator('#review-attempts-history-card');
    await expect(historyCard).toBeVisible({ timeout: 10_000 });

    // Verify at least 2 attempts are rendered
    const attemptItems = page.locator('#review-attempts-list > div');
    const count = await attemptItems.count();
    expect(count).toBeGreaterThanOrEqual(2);

    // Click Attempt #1
    const attempt1 = page.locator('#review-attempts-list div[data-attempt-no="1"]');
    await expect(attempt1).toBeVisible();
    await attempt1.click();

    // Verify Archive Banner appears
    const banner = page.locator('#review-attempt-archive-banner');
    await expect(banner).toBeVisible({ timeout: 5_000 });
    await expect(banner).toContainText('Попытки #1');

    // Click "Вернуться к текущему состоянию"
    const restoreBtn = page.locator('#review-attempt-restore-current-btn');
    await expect(restoreBtn).toBeVisible();
    await restoreBtn.click();

    // Verify Archive Banner disappears
    await expect(banner).not.toBeVisible({ timeout: 5_000 });
  });

  test('HW-CODE-01: Student writes code in homework, submits, and upon page reload/teacher review, code and files remain intact', async ({ browser }) => {
    // 1. Reset submission 2694 to IN_PROGRESS so student can edit and submit
    runPython(`
from app import create_app, db
from core.db_models import Submission, Answer, SubmissionAttempt
app = create_app()
with app.app_context():
    sub = db.session.get(Submission, ${submissionId})
    if sub:
        sub.status = "IN_PROGRESS"
        sub.submitted_at = None
        if sub.assignment:
            sub.assignment.max_attempts_default = 10
            for t in sub.assignment.tasks:
                t.max_attempts = 10
        SubmissionAttempt.query.filter_by(submission_id=${submissionId}).delete()
        ans = Answer.query.filter_by(submission_id=${submissionId}, assignment_task_id=${task1AtId}).first()
        if ans:
            ans.student_code = "print('INITIAL_STUDENT_CODE')"
            ans.value = "42"
        db.session.commit()
`);

    // 2. Student context opens homework OS
    const studentContext = await browser.newContext();
    const studentPage = await studentContext.newPage();
    await login(studentPage, studentUsername);

    const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
    await studentPage.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    // Student types custom unique code
    const uniqueMarker = `test_code_marker_${Date.now()}`;
    await studentPage.evaluate((marker) => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      if (ta) {
        ta.value = `# HW Solution\nprint("${marker}")\n`;
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if ((window as any).virtualFS) {
        (window as any).virtualFS['main.py'] = `# HW Solution\nprint("${marker}")\n`;
      }
    }, uniqueMarker);

    await studentPage.waitForTimeout(1000);

    // Student clicks submit button
    const submitBtn = studentPage.locator('#homework-submit');
    await expect(submitBtn).toBeVisible({ timeout: 5_000 });
    await submitBtn.click();

    // Verify submission modal appears
    const modal = studentPage.locator('#homework-submitted-modal');
    await expect(modal).toBeVisible({ timeout: 15_000 });

    // 3. Reload student page (now in submitted / read-only state)
    await studentPage.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    // Verify student code is still present in textarea and virtualFS
    const studentRetainedCode = await studentPage.evaluate(() => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return {
        textareaVal: ta ? ta.value : '',
        vfsMain: (window as any).virtualFS ? (window as any).virtualFS['main.py'] : ''
      };
    });
    expect(studentRetainedCode.textareaVal).toContain(uniqueMarker);
    expect(studentRetainedCode.vfsMain).toContain(uniqueMarker);

    // 4. Teacher opens review workspace
    const teacherContext = await browser.newContext();
    const teacherPage = await teacherContext.newPage();
    await login(teacherPage, tutorUsername);

    const reviewUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&review=1`;
    await teacherPage.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await expect(teacherPage.locator('#code-window')).toBeVisible({ timeout: 20_000 });

    // Verify teacher sees student's submitted code!
    const teacherCode = await teacherPage.evaluate(() => {
      const ta = document.getElementById('code-editor-textarea') as HTMLTextAreaElement;
      return {
        textareaVal: ta ? ta.value : '',
        vfsMain: (window as any).virtualFS ? (window as any).virtualFS['main.py'] : ''
      };
    });
    expect(teacherCode.textareaVal).toContain(uniqueMarker);
    expect(teacherCode.vfsMain).toContain(uniqueMarker);

    await studentContext.close();
    await teacherContext.close();
  });

});
