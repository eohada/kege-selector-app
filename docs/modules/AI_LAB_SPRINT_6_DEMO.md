# BooStudy AI Lab Sprint 6 — demo guide

This demonstration is for local AI Lab only and uses synthetic data. Do not use real student work or production databases.

## 1. Validate the frozen protocol

From the repository root:

```powershell
python -m scripts.ai_lab_benchmark validate
python -m scripts.run_ai_lab_sprint6_benchmark --plan
```

The first command checks dataset, protocol, and preserved fixture hashes. The second prints the frozen model/case plan without requesting the GigaChat catalogue or generating a response.

## 2. Run deterministic Analytics and Practice cases

Use a new file under the operating system temporary directory and a separate results path:

```powershell
python -m scripts.run_ai_lab_sprint6_benchmark `
  --run-deterministic `
  --database "$env:TEMP\boostudy-ai-lab-sprint6-demo.sqlite" `
  --output docs/modules/artifacts/ai_lab_sprint6_demo_deterministic.jsonl
```

This invokes the BooStudy Analytics and Practice services against synthetic fixture evidence. It makes zero GigaChat generations. The demo output is separate from the immutable Sprint 6 run artifact.

## 3. Browse the five modules

Sign in to the local synthetic preview and inspect:

- `/admin/ai-lab/studio` — AI Homework
- `/admin/ai-lab/course` — AI Course
- `/admin/ai-lab/lesson-intelligence` — text-only Lesson Intelligence
- `/admin/ai-lab/analytics` — evidence, uncertainty, skills, and sources
- `/admin/ai-lab/practice` — existing-task recommendation and suppression reasons

The preview provider is synthetic. It does not count as a live GigaChat quality result. The Sprint 6 browser test checks all five routes at 1440×900, 1366×768, 1024×768, and 390×844.

## 4. Inspect the preserved live experiment

Open `artifacts/ai_lab_sprint6_live_run.jsonl` and select only rows with `execution.attempt_count > 0` to see the 10 actual GigaChat responses. The other four rows record pre-call harness failures; all rows are retained for auditability.

The 10-call budget is fully used. A second `--run-live` now reads the canonical ledger even if `--output` points elsewhere and exits before making a catalogue or completion request when all frozen cases are already attempted. Do not start another series under the same protocol. A new series requires a new protocol and fixture version.

## 5. Complete independent human review

Follow [AI_LAB_SPRINT_6_REVIEW.md](AI_LAB_SPRINT_6_REVIEW.md). The initial append-only review file is empty, and the current summary intentionally reports no accuracy values. After a qualified human reviewer appends real labels, recalculate the summary with the documented score command.

## 6. Expected evidence and limits

- Dataset validation: 19 cases, split 5 development / 3 regression / 11 holdout.
- Live benchmark: 10 actual generations, all with recorded usage, parameters, model version, prompt/payload hashes, and duration.
- Deterministic benchmark: six Analytics/Practice cases, no model generations.
- Browser geometry matrix: 20 route/viewport combinations, zero geometry failures.
- Human review: still pending; do not report model accuracy or production readiness.

See [AI_LAB_SPRINT_6_REPORT.md](AI_LAB_SPRINT_6_REPORT.md) for detailed findings, usage totals, failed cases, and residual limitations.
