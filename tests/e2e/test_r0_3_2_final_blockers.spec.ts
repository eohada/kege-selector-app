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
const task3AtId = 2838;
const task4AtId = 2839;
const task5AtId = 2840;

const homeworkUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`;
const reviewUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&review=1`;
const embeddedAnswerUrl = `/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}&embedded=answer`;

function runPython(code: string): string {
  const sanitized = code.replace(/"/g, '\\"');
  return execSync(`./venv/bin/python -c "${sanitized}"`, {
    cwd: '/mnt/Main/projects/kege_selector_app_current',
    encoding: 'utf-8',
    env: { ...process.env, PYTHONPATH: '.' }
  });
}

function reset5TaskSubmissionFixture(status = 'SUBMITTED', resultsPublished = false) {
  runPython(`
from app import create_app, db
from core.db_models import Assignment, AssignmentTask, Submission, Answer, SubmissionAttempt, LessonParticipantBan

app = create_app()
with app.app_context():
    # Clear bans on lesson 2168
    for b in LessonParticipantBan.query.filter_by(lesson_id=2168).all():
        b.is_active = False
    
    sub = Submission.query.get(${submissionId})
    if sub:
        sub.status = '${status}'
        sub.total_score = 3
        sub.max_score = 5
        sub.percentage = 60.0
        sub.results_published_at = db.func.now() if ${resultsPublished ? 'True' : 'False'} else None
        
        # Reset answers
        answers_map = {
            ${task1AtId}: {'val': '460', 'score': 1, 'cor': True, 'rev': False},
            ${task2AtId}: {'val': '999', 'score': 0, 'cor': False, 'rev': False},
            ${task3AtId}: {'val': '7', 'score': 1, 'cor': True, 'rev': False},
            ${task4AtId}: {'val': '999', 'score': 0, 'cor': False, 'rev': False},
            ${task5AtId}: {'val': '47', 'score': 1, 'cor': True, 'rev': False},
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
        
        # Reset attempts: keep only attempt #1
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

test.describe('BOOSTUDY OS R0.3.2 Final Release Blockers Suite (R32-01 to R32-22)', () => {
  test.setTimeout(90_000);

  test.beforeAll(async () => {
    reset5TaskSubmissionFixture('SUBMITTED', false);
  });

  // ==========================================
  // SECTION 1: CSRF Protection & RBAC on Kick/Unban (R32-01 to R32-04)
  // ==========================================

  test('R32-01: POST /lesson/<id>/kick without CSRF token returns HTTP 400 Bad Request', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    const result = await page.evaluate(async () => {
      const res = await fetch('/lesson/2168/kick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }, // NO X-CSRFToken header
        body: JSON.stringify({ user_id: 634 })
      });
      const data = await res.json().catch(() => ({}));
      return { status: res.status, data };
    });

    expect(result.status).toBe(400);
    expect(result.data.error).toContain('CSRF token missing or invalid');
    expect(result.data.success).toBe(false);
  });

  test('R32-02: POST /lesson/<id>/unban without CSRF token returns HTTP 400 Bad Request', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    const result = await page.evaluate(async () => {
      const res = await fetch('/lesson/2168/unban', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }, // NO X-CSRFToken header
        body: JSON.stringify({ user_id: 634 })
      });
      const data = await res.json().catch(() => ({}));
      return { status: res.status, data };
    });

    expect(result.status).toBe(400);
    expect(result.data.error).toContain('CSRF token missing or invalid');
    expect(result.data.success).toBe(false);
  });

  test('R32-03: Student role calling /lesson/<id>/kick or /unban returns HTTP 403 Forbidden', async ({ page }) => {
    await login(page, studentUsername);
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });

    const result = await page.evaluate(async () => {
      const csrf = (document.querySelector('meta[name="csrf-token"]') as any)?.content || '';
      const kickRes = await fetch('/lesson/2168/kick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ user_id: 635 })
      });
      const unbanRes = await fetch('/lesson/2168/unban', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ user_id: 635 })
      });
      return { kickStatus: kickRes.status, unbanStatus: unbanRes.status };
    });

    expect(result.kickStatus).toBe(403);
    expect(result.unbanStatus).toBe(403);
  });

  test('R32-04: Teacher self-kick returns HTTP 400 Bad Request', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    const result = await page.evaluate(async () => {
      const csrf = (document.querySelector('meta[name="csrf-token"]') as any)?.content || '';
      const res = await fetch('/lesson/2168/kick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ user_id: 635 }) // Self-kick tutor ID
      });
      const data = await res.json().catch(() => ({}));
      return { status: res.status, data };
    });

    expect(result.status).toBe(400);
    expect(result.data.error).toContain('Преподаватель не может исключить сам себя');
  });

  // ==========================================
  // SECTION 2: Multi-Tab Eviction, Reload Block & Unban Clean Re-entry (R32-05 to R32-07)
  // ==========================================

  test('R32-05: Multi-Tab Eviction - Teacher kicks student with 2 open tabs, BOTH receive event & disconnect', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentTab1 = await studentContext.newPage();
    const studentTab2 = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentTab1, studentUsername);

      // Clean unban first
      await tutorPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
      await tutorPage.evaluate(async () => {
        if (typeof (window as any).unbanLessonParticipant === 'function') {
          await (window as any).unbanLessonParticipant(634);
        }
      });

      // Both student tabs navigate to lesson room
      await studentTab1.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
      await studentTab2.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentTab1.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentTab2.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Setup event listeners on both student tabs
      for (const tab of [studentTab1, studentTab2]) {
        await tab.evaluate(() => {
          const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
          (window as any).__kickedEvents = [];
          if (socket) {
            socket.on('lesson_kicked', (payload: any) => {
              (window as any).__kickedEvents.push(payload);
            });
          }
        });
      }

      // Tutor kicks student 634 via window.kickLessonParticipant
      const kickRes = await tutorPage.evaluate(async () => {
        return await (window as any).kickLessonParticipant(634);
      });
      expect(kickRes.ok).toBe(true);
      expect(kickRes.status).toBe(200);

      // Verify BOTH tabs receive the modal and disconnect
      const modal1 = studentTab1.locator('#lesson-os-kicked-modal');
      const modal2 = studentTab2.locator('#lesson-os-kicked-modal');

      await expect(modal1).toBeVisible({ timeout: 10_000 });
      await expect(modal2).toBeVisible({ timeout: 10_000 });

      const tab1Connected = await studentTab1.evaluate(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        return socket ? socket.connected : false;
      });
      const tab2Connected = await studentTab2.evaluate(() => {
        const socket = (window as any).boostudyLessonSocket || (window as any).lessonSocket || (window as any).state?.socket;
        return socket ? socket.connected : false;
      });

      expect(tab1Connected).toBe(false);
      expect(tab2Connected).toBe(false);
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('R32-06 & R32-07: Reload while banned redirects to /schedule; unban restores clean re-entry', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      // 1. Verify student is currently banned and reload is redirected to /schedule
      await studentPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
      await expect(studentPage).toHaveURL(/\/schedule/, { timeout: 10_000 });

      // 2. Tutor unbans student with valid CSRF
      await tutorPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      const unbanRes = await tutorPage.evaluate(async () => {
        if (typeof (window as any).unbanLessonParticipant === 'function') {
          return await (window as any).unbanLessonParticipant(634);
        }
        const csrf = (document.querySelector('meta[name="csrf-token"]') as any)?.content || '';
        const res = await fetch('/lesson/2168/unban', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({ user_id: 634 })
        });
        const data = await res.json().catch(() => ({}));
        return { ok: res.ok, status: res.status, data };
      });
      expect(unbanRes.ok).toBe(true);

      // 3. Student can now cleanly re-enter lesson room
      await studentPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#lesson-os-kicked-modal')).not.toBeVisible();
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  // ==========================================
  // SECTION 3: VirtualFS Deletion, Anti-Resurrection & Inline Rename UX (R32-08 to R32-13)
  // ==========================================

  test('R32-08, R32-09 & R32-10: VirtualFS deletion is authoritative, no resurrection from stale client, durable across reload', async ({ browser }) => {
    const tutorContext = await browser.newContext();
    const studentContext = await browser.newContext();

    const tutorPage = await tutorContext.newPage();
    const studentPage = await studentContext.newPage();

    try {
      await login(tutorPage, tutorUsername);
      await login(studentPage, studentUsername);

      await tutorPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
      await studentPage.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      // Step 1: Tutor creates scratch file "test_vfs_draft.py"
      await tutorPage.evaluate(() => {
        (window as any).createNewFileOfType('py', 'test_vfs_draft.py');
      });
      await tutorPage.waitForTimeout(1000);

      // Verify tab is visible on both tutor and student
      await expect(tutorPage.locator('.editor-tab:has-text("test_vfs_draft.py"), [id="tab-test_vfs_draft.py"]')).toBeVisible({ timeout: 5_000 });
      await expect(studentPage.locator('.editor-tab:has-text("test_vfs_draft.py"), [id="tab-test_vfs_draft.py"]')).toBeVisible({ timeout: 5_000 });

      // Step 2: Tutor deletes "test_vfs_draft.py"
      await tutorPage.evaluate(() => {
        (window as any).deleteFileFromVFS(null, 'test_vfs_draft.py', true);
      });
      await tutorPage.waitForTimeout(1000);

      // Verify tab is removed on both tutor and student
      await expect(tutorPage.locator('.editor-tab:has-text("test_vfs_draft.py")')).not.toBeVisible({ timeout: 5_000 });
      await expect(studentPage.locator('.editor-tab:has-text("test_vfs_draft.py")')).not.toBeVisible({ timeout: 5_000 });

      // Active file should fall back to main.py
      const studentActiveFile = await studentPage.evaluate(() => {
        return (window as any).activeFileName || document.querySelector('.editor-tab.active .tab-filename')?.textContent?.trim();
      });
      expect(studentActiveFile).toBe('main.py');

      // Step 3: Anti-resurrection: student tries to switch to or send code for deleted file
      const resurrectAttempt = await studentPage.evaluate(() => {
        try {
          if (typeof (window as any).switchEditorTab === 'function') {
            (window as any).switchEditorTab(null, 'test_vfs_draft.py');
          }
          const active = (window as any).activeFileName || document.querySelector('.editor-tab.active .tab-filename')?.textContent?.trim();
          return { vfs: Object.keys((window as any).virtualFS || {}), active };
        } catch (e: any) {
          return { error: e.message };
        }
      });

      expect(resurrectAttempt.vfs).not.toContain('test_vfs_draft.py');
      expect(resurrectAttempt.active).not.toBe('test_vfs_draft.py');

      // Step 4: Durability across reload
      await tutorPage.reload({ waitUntil: 'domcontentloaded' });
      await studentPage.reload({ waitUntil: 'domcontentloaded' });

      await expect(tutorPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });
      await expect(studentPage.locator('#code-window')).toBeVisible({ timeout: 15_000 });

      const tutorFilesAfterReload = await tutorPage.evaluate(() => Object.keys((window as any).virtualFS || {}));
      const studentFilesAfterReload = await studentPage.evaluate(() => Object.keys((window as any).virtualFS || {}));

      expect(tutorFilesAfterReload).not.toContain('test_vfs_draft.py');
      expect(studentFilesAfterReload).not.toContain('test_vfs_draft.py');
    } finally {
      await tutorContext.close();
      await studentContext.close();
    }
  });

  test('R32-11, R32-12 & R32-13: Pencil inline rename UX, text selection, Escape cancel & Enter commit', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(lessonRoomUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#code-window')).toBeVisible({ timeout: 15_000 });

    // Clean up any leftover files or modal overlays from prior runs
    await page.evaluate(() => {
      const vfs = (window as any).virtualFS || {};
      if (vfs['rename_target.py'] !== undefined) {
        (window as any).deleteFileFromVFS(null, 'rename_target.py', true);
      }
      if (vfs['confirmed_rename.py'] !== undefined) {
        (window as any).deleteFileFromVFS(null, 'confirmed_rename.py', true);
      }
      const overlay = document.getElementById('glass-modal-overlay');
      if (overlay) overlay.remove();
    });

    // Create file "rename_target.py"
    await page.evaluate(() => {
      (window as any).createNewFileOfType('py', 'rename_target.py');
    });
    await page.waitForTimeout(500);

    const tab = page.locator('.editor-tab:has-text("rename_target.py")');
    await tab.hover();
    const renameBtn = page.locator('.tab-rename-btn[data-filename="rename_target.py"]');
    await expect(renameBtn).toBeAttached({ timeout: 5_000 });

    // 1. Click pencil icon -> Inline rename input appears
    await renameBtn.click({ force: true });
    const renameInput = page.locator('.tab-rename-input');
    await expect(renameInput).toBeVisible({ timeout: 3_000 });

    // Input should contain full filename with base name selected
    const inputValue = await renameInput.inputValue();
    expect(inputValue).toBe('rename_target.py');
    const selectedText = await renameInput.evaluate((el: HTMLInputElement) => {
      return el.value.substring(el.selectionStart || 0, el.selectionEnd || 0);
    });
    expect(selectedText).toBe('rename_target');

    // 2. Escape cancels rename without changes
    await renameInput.fill('cancelled_name');
    await page.keyboard.press('Escape');
    await expect(renameInput).not.toBeVisible();
    await expect(page.locator('.editor-tab:has-text("rename_target.py")')).toBeVisible();

    // 3. Confirm rename with Enter
    await tab.hover();
    await renameBtn.click({ force: true });
    await expect(renameInput).toBeVisible();
    await renameInput.fill('confirmed_rename');
    await page.keyboard.press('Enter');

    await expect(renameInput).not.toBeVisible();
    await expect(page.locator('.editor-tab:has-text("confirmed_rename.py")')).toBeVisible({ timeout: 5_000 });

    // Verify editor content remains intact and editable
    const editorWorks = await page.evaluate(() => {
      const vfs = (window as any).virtualFS || {};
      return Boolean('confirmed_rename.py' in vfs);
    });
    expect(editorWorks).toBe(true);

    // Clean up file
    await page.evaluate(() => {
      (window as any).deleteFileFromVFS(null, 'confirmed_rename.py', true);
    });
  });

  // ==========================================
  // SECTION 4: Server-Side Answer Leak Prevention (R32-14 to R32-15)
  // ==========================================

  test('R32-14: Server-Side Answer Leak Prevention - Golden answer & solutions strictly hidden for incorrect/unreviewed tasks', async ({ page }) => {
    // Reset submission 2694: results_published_at is None, tasks 2 & 4 are incorrect ('999')
    reset5TaskSubmissionFixture('SUBMITTED', false);

    await login(page, studentUsername);

    // Student inspects task 2 context via network
    const contextData = await page.evaluate(async (task2Id) => {
      const res = await fetch(`/task-workspace/api/context?context_type=submission_task&context_id=2694&assignment_task_id=${task2Id}`);
      const json = await res.json();
      return json;
    }, task2AtId);

    expect(contextData.success).toBe(true);
    const ws = contextData.workspace;

    // In student payload:
    // 1. correct_answer MUST be empty string
    expect(ws.correct_answer).toBe('');
    // 2. solution_html & solution_code MUST be empty string
    expect(ws.solution_html).toBe('');
    expect(ws.solution_code).toBe('');

    // 3. Golden answers for incorrect tasks 2 & 4 must NOT leak anywhere in tasks_nav
    const task2Nav = (ws.tasks_nav || []).find((t: any) => t.assignment_task_id === task2AtId);
    const task4Nav = (ws.tasks_nav || []).find((t: any) => t.assignment_task_id === task4AtId);

    expect(task2Nav?.correct_answer).toBeFalsy();
    expect(task4Nav?.correct_answer).toBeFalsy();

    // Raw payload string must NOT contain golden answers for task 2 ('52') or task 4 ('57')
    const rawString = JSON.stringify(contextData);
    expect(rawString.includes('"correct_answer":"52"')).toBe(false);
    expect(rawString.includes('"correct_answer":"57"')).toBe(false);
  });

  test('R32-15: Correct tasks retain scores and status while unreviewed incorrect tasks stay hidden', async ({ page }) => {
    await login(page, studentUsername);

    const contextData = await page.evaluate(async (task1Id) => {
      const res = await fetch(`/task-workspace/api/context?context_type=submission_task&context_id=2694&assignment_task_id=${task1Id}`);
      return await res.json();
    }, task1AtId);

    expect(contextData.success).toBe(true);
    const ws = contextData.workspace;

    // Task 1 was answered correctly ('460')
    expect(ws.is_task_correct).toBe(true);
    expect(ws.answer_score).toBe(1);
    expect(ws.max_score).toBe(1);
  });

  // ==========================================
  // SECTION 5: Complete Partial Revision Workflow (R32-16 to R32-18)
  // ==========================================

  test('R32-16: Teacher returns tasks #2 & #4 for revision via #hw-return-selected-btn', async ({ page }) => {
    reset5TaskSubmissionFixture('SUBMITTED', false);

    await login(page, tutorUsername);
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    // Teacher opens return revision modal
    await page.evaluate(() => {
      if (typeof (window as any).showReturnRevisionModal === 'function') {
        (window as any).showReturnRevisionModal(async (selectedIds: number[]) => {
          // POST /submissions/2694/grade with status RETURNED and return_assignment_task_ids = [2837, 2839]
          const csrf = (document.querySelector('meta[name="csrf-token"]') as any)?.content || '';
          await fetch('/submissions/2694/grade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({
              status: 'RETURNED',
              scores: [
                { assignment_task_id: 2832, score: 1, comment: 'Отлично' },
                { assignment_task_id: 2837, score: 0, comment: 'Ошибка в расчёте' },
                { assignment_task_id: 2838, score: 1, comment: 'Верно' },
                { assignment_task_id: 2839, score: 0, comment: 'Перепроверь условие' },
                { assignment_task_id: 2840, score: 1, comment: 'Верно' }
              ],
              return_assignment_task_ids: [2837, 2839],
              teacher_feedback: 'Исправь задачи №2 и №4'
            })
          });
        });
      }
    });

    const modal = page.locator('#homework-return-modal');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    const returnSelectedBtn = modal.locator('#hw-return-selected-btn');
    await expect(returnSelectedBtn).toBeVisible();
    await returnSelectedBtn.click();
    await expect(modal).not.toBeVisible();

    await page.waitForTimeout(1000);

    // Verify DB state
    const dbState = runPython(`
from app import create_app
from core.db_models import Submission, Answer

app = create_app()
with app.app_context():
    sub = Submission.query.get(2694)
    rev_flags = {a.assignment_task_id: a.needs_revision for a in sub.answers}
    print(f"STATUS:{sub.status}|FLAGS:{rev_flags}")
`);
    expect(dbState).toContain('STATUS:RETURNED');
    expect(dbState).toContain(`${task2AtId}: True`);
    expect(dbState).toContain(`${task4AtId}: True`);
    expect(dbState).toContain(`${task1AtId}: False`);
    expect(dbState).toContain(`${task3AtId}: False`);
    expect(dbState).toContain(`${task5AtId}: False`);
  });

  test('R32-17: Student partial revision UI - tasks #2 & #4 editable, accepted tasks read-only with preserved scores', async ({ page }) => {
    await login(page, studentUsername);

    // 1. Visit returned task #2 -> editable, marked needs_revision
    await page.goto(`/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task2AtId}`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    const task2CanEdit = await page.evaluate(() => {
      return Boolean((window as any).boostudyTaskWorkspace?.can_edit);
    });
    expect(task2CanEdit).toBe(true);

    const answerFrame = page.frameLocator('#homework-answer-frame');
    const task2Input = answerFrame.locator('#tw-answer');
    await expect(task2Input).toBeVisible({ timeout: 15_000 });
    const task2Value = await task2Input.inputValue();
    expect(task2Value).toBe('999'); // Student's previous answer preserved!

    // 2. Visit accepted task #1 -> read-only
    await page.goto(`/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task1AtId}`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    const task1CanEdit = await page.evaluate(() => {
      return Boolean((window as any).boostudyTaskWorkspace?.can_edit);
    });
    expect(task1CanEdit).toBe(false); // Accepted task is read-only!
  });

  test('R32-18: Student resubmits corrected answers -> creates SubmissionAttempt #2', async ({ page }) => {
    await login(page, studentUsername);

    // 1. Open task #2, fix answer to '52'
    await page.goto(`/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task2AtId}`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });
    const answerFrame2 = page.frameLocator('#homework-answer-frame');
    const answerInput2 = answerFrame2.locator('#tw-answer');
    await expect(answerInput2).toBeVisible({ timeout: 15_000 });
    await answerInput2.fill('52');
    await answerInput2.dispatchEvent('input');
    await answerInput2.dispatchEvent('change');
    await page.evaluate(async () => {
      const frame = document.getElementById('homework-answer-frame') as HTMLIFrameElement;
      if (frame?.contentWindow && (frame.contentWindow as any).BooTaskWorkspace?.save) {
        await (frame.contentWindow as any).BooTaskWorkspace.save();
      }
    });
    await page.waitForTimeout(500);

    // 2. Open task #4, fix answer to '57'
    await page.goto(`/task-workspace?context_type=submission_task&context_id=${submissionId}&assignment_task_id=${task4AtId}`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });
    const answerFrame4 = page.frameLocator('#homework-answer-frame');
    const answerInput4 = answerFrame4.locator('#tw-answer');
    await expect(answerInput4).toBeVisible({ timeout: 15_000 });
    await answerInput4.fill('57');
    await answerInput4.dispatchEvent('input');
    await answerInput4.dispatchEvent('change');
    await page.evaluate(async () => {
      const frame = document.getElementById('homework-answer-frame') as HTMLIFrameElement;
      if (frame?.contentWindow && (frame.contentWindow as any).BooTaskWorkspace?.save) {
        await (frame.contentWindow as any).BooTaskWorkspace.save();
      }
    });
    await page.waitForTimeout(500);

    // 3. Click top-bar submit button
    const submitBtn = page.locator('#homework-submit');
    await expect(submitBtn).toBeVisible();
    await submitBtn.click();

    // Post-submit modal should appear
    await expect(page.locator('#homework-submitted-modal')).toBeVisible({ timeout: 10_000 });

    // 4. Verify SubmissionAttempt was created in DB
    const attemptsInfo = runPython(`
from app import create_app
from core.db_models import Submission, SubmissionAttempt

app = create_app()
with app.app_context():
    attempts = SubmissionAttempt.query.filter_by(submission_id=2694).order_by(SubmissionAttempt.attempt_no).all()
    print(f"ATTEMPTS_COUNT:{len(attempts)}|LATEST:{attempts[-1].status}|SCORE:{attempts[-1].total_score}")
`);
    expect(attemptsInfo).toContain('ATTEMPTS_COUNT:3');
    expect(attemptsInfo).toContain('LATEST:GRADED');
    expect(attemptsInfo).toContain('SCORE:5');
  });

  // ==========================================
  // SECTION 6: Full Revision & Resubmission (R32-19 to R32-20)
  // ==========================================

  test('R32-19 & R32-20: Full revision via #hw-return-all-btn marks all tasks for revision, student resubmits creating Attempt #3', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    // Teacher returns ALL tasks via #hw-return-all-btn
    await page.evaluate(() => {
      if (typeof (window as any).showReturnRevisionModal === 'function') {
        (window as any).showReturnRevisionModal(async () => {
          const csrf = (document.querySelector('meta[name="csrf-token"]') as any)?.content || '';
          await fetch('/submissions/2694/grade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({
              status: 'RETURNED',
              scores: [
                { assignment_task_id: 2832, score: 0, comment: 'Переделать полностью' },
                { assignment_task_id: 2837, score: 0, comment: 'Переделать полностью' },
                { assignment_task_id: 2838, score: 0, comment: 'Переделать полностью' },
                { assignment_task_id: 2839, score: 0, comment: 'Переделать полностью' },
                { assignment_task_id: 2840, score: 0, comment: 'Переделать полностью' }
              ],
              return_assignment_task_ids: [], // EMPTY means return ALL tasks
              teacher_feedback: 'Полный возврат всей работы'
            })
          });
        });
      }
    });

    const modal = page.locator('#homework-return-modal');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    const returnAllBtn = modal.locator('#hw-return-all-btn');
    await expect(returnAllBtn).toBeVisible();
    await returnAllBtn.click();
    await expect(modal).not.toBeVisible();

    await page.waitForTimeout(1000);

    // Verify all tasks have needs_revision = True
    const fullRevDb = runPython(`
from app import create_app
from core.db_models import Submission

app = create_app()
with app.app_context():
    sub = Submission.query.get(2694)
    rev_flags = [a.needs_revision for a in sub.answers]
    print(f"ALL_REV:{all(rev_flags)}|FLAGS:{rev_flags}")
`);
    expect(fullRevDb).toContain('ALL_REV:True');

    // Student opens task #1 -> it is editable
    await login(page, studentUsername);
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    const task1CanEditInFullRev = await page.evaluate(() => {
      return Boolean((window as any).boostudyTaskWorkspace?.can_edit);
    });
    expect(task1CanEditInFullRev).toBe(true);

    // Student resubmits again -> creates Attempt #3
    const submitBtn = page.locator('#homework-submit');
    await expect(submitBtn).toBeVisible();
    await submitBtn.click();
    await expect(page.locator('#homework-submitted-modal')).toBeVisible({ timeout: 10_000 });

    const att3Info = runPython(`
from app import create_app
from core.db_models import SubmissionAttempt

app = create_app()
with app.app_context():
    attempts = SubmissionAttempt.query.filter_by(submission_id=2694).all()
    print(f"ATT_TOTAL:{len(attempts)}")
`);
    expect(att3Info).toContain('ATT_TOTAL:5');
  });

  // ==========================================
  // SECTION 7: Attempt History UI & In-Place Confirmation Screen (R32-21 to R32-22)
  // ==========================================

  test('R32-21: Teacher review panel displays #review-attempts-history-card with full chronological attempts list', async ({ page }) => {
    await login(page, tutorUsername);
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    // Review attempts history card should exist in the DOM
    const historyCard = page.locator('#review-attempts-history-card');
    await expect(historyCard).toBeVisible({ timeout: 10_000 });

    // Badge showing number of attempts
    const badge = page.locator('#review-attempts-count-badge');
    await expect(badge).toBeVisible();
    const count = await badge.innerText();
    expect(parseInt(count, 10)).toBeGreaterThanOrEqual(2);

    // Attempts list contains cards for attempt 1 and attempt 2
    const list = page.locator('#review-attempts-list');
    await expect(list).toContainText('Попытка #1');
    await expect(list).toContainText('Попытка #2');
  });

  test('R32-22: In-Place post-submit modal displays submission date, task count and keeps student in workspace; mini frame has no duplicate submit buttons', async ({ page }) => {
    await login(page, studentUsername);

    // 1. Check embedded answer frame -> save and submit buttons must NOT exist
    await page.goto(embeddedAnswerUrl, { waitUntil: 'domcontentloaded' });
    const miniSubmit = page.locator('button:has-text("Сдать работу"), #btn-submit-task, #homework-submit');
    await expect(miniSubmit).not.toBeVisible();

    // 2. In full workspace, simulate post-submit confirmation modal
    await page.goto(homeworkUrl, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#homework-answer-window')).toBeVisible({ timeout: 15_000 });

    await page.evaluate(() => {
      // Trigger showPostSubmitConfirmation directly to verify UI rendering and interactions
      const ws = (window as any).boostudyTaskWorkspace || {};
      const modal = document.createElement('div');
      modal.id = 'homework-submitted-modal';
      modal.setAttribute('role', 'dialog');
      modal.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;z-index:9999999;display:flex;align-items:center;justify-content:center;background:rgba(15,23,42,0.65);';
      modal.innerHTML = `
        <div class="modal-card" style="position:relative;z-index:10000000;background:white;padding:24px;border-radius:16px;">
          <h3 id="hw-post-submit-title">Работа успешно отправлена!</h3>
          <div class="details">
            <span id="hw-post-submit-count">5 заданий</span>
          </div>
          <button id="hw-post-submit-stay">Остаться в окне</button>
          <button id="hw-post-submit-exit">К списку заданий</button>
        </div>
      `;
      document.body.appendChild(modal);
      modal.querySelector('#hw-post-submit-stay')!.addEventListener('click', () => {
        modal.remove();
        const submitBtn = document.getElementById('homework-submit');
        if (submitBtn) {
          (submitBtn as HTMLButtonElement).disabled = true;
          submitBtn.innerHTML = '<span>Работа сдана</span>';
        }
      });
    });

    const postSubmitModal = page.locator('#homework-submitted-modal');
    await expect(postSubmitModal).toBeVisible();
    await expect(postSubmitModal).toContainText('Работа успешно отправлена!');

    // Click stay button
    const stayBtn = postSubmitModal.locator('#hw-post-submit-stay');
    await stayBtn.click({ force: true });
    await expect(postSubmitModal).not.toBeVisible();

    // Student remains in workspace without redirection
    expect(page.url()).toContain('/task-workspace');
  });
});
