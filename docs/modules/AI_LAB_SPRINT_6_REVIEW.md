# AI Lab Sprint 6 — independent expert review guide

Use this checklist to review the preserved model outputs against the frozen synthetic fixture. The model must not rate its own answer. Do not edit the run JSONL, fixture, protocol, prompt, or expected results during review.

## Review set

The live run contains 10 model outputs across two run IDs:

- `ec5a5325-7ef8-4bae-87ed-9282cb47c7ad`: three AI Course and three AI Lesson Intelligence outputs.
- `03cb5df7-a314-44c6-8029-d71cf57856a2`: four AI Homework outputs.

The raw artifact also contains four preserved Homework harness-failure rows from before the model call (`attempt_count=0`). Those rows are not model outputs and should not be scored as model quality. Use `execution.attempt_count > 0` when selecting the 10 live outputs.

The independent deterministic Analytics/Practice result is in `artifacts/ai_lab_sprint6_deterministic_run_v4.jsonl`, run ID `b5101cad-a930-4f58-be6c-fc04388c8b3b`.

## Rating format

Every submitted rating is an explicit boolean. Omit a field when it does not apply; do not use `false` to mean “not applicable.” Add comments with the supporting case ID, source reference, and exact response/evidence field. Reviewer confidence is not an objective probability and is not collected as one.

### AI Homework

- `final_score_correct`
- `criterion_scores_correct`
- `explanation_correct`
- `no_invented_errors`
- `alternative_solution_handled`
- `insufficient_evidence_handled`
- `hidden_tests_protected`

### AI Course

- `findings_correct`
- `findings_complete`
- `source_references_correct`
- `pedagogically_justified`
- `proposal_factually_correct`
- `no_unsupported_claims`
- `source_meaning_preserved`

### AI Lesson Intelligence

- `summary_factual`
- `topics_supported`
- `source_references_correct`
- `important_observations_present`
- `no_false_observations`
- `learner_resolution_handled`
- `question_not_overcalled_as_difficulty`
- `uncertainty_handled`

### AI Analytics and Practice

- `evidence_aggregation_correct`
- `no_unsupported_diagnosis`
- `skill_links_correct`
- `recommendation_relevant`
- `prerequisites_respected`
- `selection_explained`
- `completed_assignment_excluded`

## Append a review

The following example appends one Homework review and leaves the execution record unchanged:

```powershell
python -m scripts.ai_lab_benchmark annotate `
  --reviews docs/modules/artifacts/ai_lab_sprint6_expert_reviews.jsonl `
  --run-id 03cb5df7-a314-44c6-8029-d71cf57856a2 `
  --case-id hw-dev-correct-return `
  --reviewer reviewer-1 `
  --ratings-json '{"final_score_correct":false,"criterion_scores_correct":false,"explanation_correct":true,"no_invented_errors":true,"alternative_solution_handled":false,"insufficient_evidence_handled":false,"hidden_tests_protected":true}' `
  --comments 'Score withheld; compare the output with the frozen expected result and semantic review reason.'
```

Replace the reviewer identifier, case ID, ratings, and comment with the human expert's actual assessment. Do not reuse this example as an annotation. Only actual human labels belong in the JSONL file.

## Recalculate metrics

```powershell
python -m scripts.ai_lab_benchmark score `
  --results docs/modules/artifacts/ai_lab_sprint6_live_run.jsonl `
  --reviews docs/modules/artifacts/ai_lab_sprint6_expert_reviews.jsonl `
  --output docs/modules/artifacts/ai_lab_sprint6_expert_review_summary.json
```

The summary counts only explicitly labeled booleans. Missing labels and pending cases are excluded from each accuracy denominator. The empty initial review file intentionally produces no accuracy values.

## Review cautions

- The 10-generation Sprint 6 budget is exhausted. Do not trigger another live run or semantic retry against this frozen protocol.
- Review holdout cases only after the protocol and outputs are frozen. Do not use them to tune prompts, validators, or expected results.
- Structural validity, correct source IDs, and token counts are not substitutes for expert judgments about correctness or pedagogy.
- Any new generation series needs a new dataset/protocol version and an explicitly bounded budget.
