from app.utils.python_programming_bank import (
    build_final_test,
    build_programming_final_test,
    grade_answers,
    load_bank,
    load_programming_bank,
    validate_bank,
    validate_programming_bank,
)


def test_programming_bank_has_required_volume_and_sources():
    report = validate_bank()

    assert report["total"] >= 200
    assert report["topics"] >= 20
    assert report["sources"] == ["ege", "foundation"]


def test_final_test_has_twenty_unique_tasks_and_both_sources():
    variant = build_final_test(seed=20261004)

    assert len(variant) == 20
    assert len({task.task_id for task in variant}) == 20
    assert {task.source for task in variant} == {"ege", "foundation"}
    assert len({task.topic for task in variant}) >= 16


def test_final_test_is_reproducible_with_seed():
    first = [task.task_id for task in build_final_test(seed=17)]
    second = [task.task_id for task in build_final_test(seed=17)]

    assert first == second


def test_bank_fingerprints_remove_exact_duplicates():
    tasks = load_bank()

    assert len({task.fingerprint for task in tasks}) == len(tasks)


def test_python_200_bank_structure_and_blocks():
    tasks = load_programming_bank()
    assert len(tasks) == 200

    report = validate_programming_bank(tasks)
    assert report["total"] == 200
    assert report["blocks"] == 4

    by_block = {}
    for task in tasks:
        by_block.setdefault(task.block, []).append(task)

    for block_num in (1, 2, 3, 4):
        block_tasks = by_block[block_num]
        assert len(block_tasks) == 50
        types = {t.task_type for t in block_tasks}
        assert types == {"single_choice", "matching", "short_answer"}
        assert sum(1 for t in block_tasks if t.task_type == "single_choice") == 20
        assert sum(1 for t in block_tasks if t.task_type == "matching") == 15
        assert sum(1 for t in block_tasks if t.task_type == "short_answer") == 15


def test_programming_final_test_variant_has_strictly_five_tasks_per_block_in_order():
    variant = build_programming_final_test(seed=42)
    assert len(variant) == 20
    assert len({t.task_id for t in variant}) == 20

    # Задания 1..5: Блок 1
    assert [t.block for t in variant[:5]] == [1, 1, 1, 1, 1]
    # Задания 6..10: Блок 2
    assert [t.block for t in variant[5:10]] == [2, 2, 2, 2, 2]
    # Задания 11..15: Блок 3
    assert [t.block for t in variant[10:15]] == [3, 3, 3, 3, 3]
    # Задания 16..20: Блок 4
    assert [t.block for t in variant[15:20]] == [4, 4, 4, 4, 4]


def test_grade_answers_handles_single_choice_matching_and_short_answer():
    tasks = load_programming_bank()
    by_id = {t.task_id: t for t in tasks}

    b1_01_ans = by_id["B1-01"].answer
    b1_21_ans = by_id["B1-21"].answer
    b1_36_ans = str(by_id["B1-36"].answer)

    sample_answers = {
        "B1-01": b1_01_ans,
        "B1-21": b1_21_ans,
        "B1-36": f" {b1_36_ans} ",
    }

    result = grade_answers(sample_answers, tasks=tasks)
    assert result["checked"] == 3
    assert result["correct"] == 3

    # Matching with Cyrillic letters test
    latin_to_cyr = {"A": "А", "B": "Б", "C": "В", "D": "Г"}
    cyrillic_matching = {
        "B1-21": {k: latin_to_cyr.get(v, v) for k, v in b1_21_ans.items()}
    }
    res_cyr = grade_answers(cyrillic_matching, tasks=tasks)
    assert res_cyr["correct"] == 1

    # Partial match failure test (1 error -> 0 points)
    bad_matching = dict(b1_21_ans)
    k0 = list(bad_matching.keys())[0]
    bad_matching[k0] = "A" if bad_matching[k0] != "A" else "B"
    partial_matching = {
        "B1-21": bad_matching
    }
    res_partial = grade_answers(partial_matching, tasks=tasks)
    assert res_partial["correct"] == 0


def test_programming_final_test_retry_diversity_at_least_eighty_percent():
    v1 = build_programming_final_test(seed=101)
    v1_ids = [t.task_id for t in v1]
    assert len(v1_ids) == 20

    # Retry variant: pass v1_ids as previous_task_ids and history_task_ids
    v2 = build_programming_final_test(seed=202, previous_task_ids=v1_ids, history_task_ids=v1_ids)
    v2_ids = [t.task_id for t in v2]
    assert len(v2_ids) == 20

    overlap = len(set(v1_ids) & set(v2_ids))
    # Must have at most 4 overlapping questions (overlap <= 20%, changed >= 80%)
    assert overlap <= 4
    changed = len(v2_ids) - overlap
    assert changed >= 16

    # Test sequential retry sequence across 4 attempts
    all_seen = set(v1_ids)
    last_ids = v1_ids
    for i in range(3):
        next_var = build_programming_final_test(seed=300 + i, previous_task_ids=last_ids, history_task_ids=all_seen)
        next_ids = [t.task_id for t in next_var]
        assert len(next_ids) == 20
        curr_overlap = len(set(last_ids) & set(next_ids))
        assert curr_overlap <= 4, f"Overlap with previous variant must be <= 4 (got {curr_overlap})"
        all_seen.update(next_ids)
        last_ids = next_ids

