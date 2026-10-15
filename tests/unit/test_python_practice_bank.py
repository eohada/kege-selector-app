import json
from collections import Counter, defaultdict

from app.utils.python_practice_bank import MODULES, TOPICS, _run_reference, generate_python_practice_bank


def test_python_practice_bank_has_exact_scope_and_distribution():
    items = generate_python_practice_bank()
    assert len(items) == 1000
    assert len(MODULES) == 7
    assert [(start, end) for start, end, _name in MODULES] == [
        (101, 104), (105, 108), (109, 112), (113, 117), (118, 121), (122, 126), (127, 130)
    ]
    assert Counter(item["format"] for item in items) == {
        "choice": 180,
        "matching": 70,
        "trace": 350,
        "code": 250,
        "manual_open": 150,
    }
    assert Counter(item["difficulty_name"] for item in items) == {
        "easy": 300,
        "medium": 450,
        "hard": 250,
    }
    assert Counter(item["topic_id"] for item in items) == {
        **{topic_id: 34 for topic_id, *_ in TOPICS[:10]},
        **{topic_id: 33 for topic_id, *_ in TOPICS[10:]},
    }
    assert len({item["content_fingerprint"] for item in items}) == 1000
    assert all(item["answer_spec"] and item["hints"] and item["solution_text"] for item in items)

    by_topic = defaultdict(list)
    for item in items:
        by_topic[item["topic_id"]].append(item)
    for topic_id, tasks in by_topic.items():
        assert {task["difficulty_name"] for task in tasks} == {"easy", "medium", "hard"}, topic_id
        assert {task["format"] for task in tasks} == {"choice", "matching", "trace", "code", "manual_open"}, topic_id
        code_archetypes = {task["reference_code"] for task in tasks if task["format"] == "code"}
        assert len(code_archetypes) >= 2, topic_id


def test_python_bank_choice_and_matching_keys_are_consistent():
    for item in generate_python_practice_bank():
        if item["format"] == "choice":
            assert item["answer"] in {option["value"] for option in item["answer_spec"]["options"]}
            assert len(item["answer_spec"]["options"]) == 4
            assert len({option["label"] for option in item["answer_spec"]["options"]}) == 4
        elif item["format"] == "matching":
            mapping = json.loads(item["answer"])
            assert set(mapping) == {pair["key"] for pair in item["answer_spec"]["pairs"]}
            assert set(mapping.values()) <= {option["value"] for option in item["answer_spec"]["options"]}
        elif item["format"] == "code":
            assert item["answer_spec"]["type"] == "code"
            assert item["answer_spec"]["grading_mode"] == "auto"
            assert item["tests"]
        elif item["format"] == "manual_open":
            assert item["answer_spec"]["grading_mode"] == "manual"
            assert item["tests"] is None


def test_authored_code_references_match_every_hidden_case():
    items = generate_python_practice_bank()
    code_tasks = [item for item in items if item["format"] == "code"]
    assert len(code_tasks) == 250
    for item in code_tasks:
        for case in item["tests"]:
            assert _run_reference(item["reference_code"], case["input"]) == case["output"], item["source_key"]
