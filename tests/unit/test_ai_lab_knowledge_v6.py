from __future__ import annotations

import json
import sqlite3
from collections import Counter
from ipaddress import ip_network
from itertools import product
from pathlib import Path

import pytest

from app.ai_lab import knowledge_base


FIXTURE = Path(__file__).parents[1] / "fixtures" / "ai_lab_knowledge_v6_expert_pilot.json"


@pytest.fixture()
def v6_isolated_app():
    from app import create_app, db

    test_app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })
    with test_app.app_context():
        db.create_all()
    try:
        yield test_app
    finally:
        with test_app.app_context():
            db.session.remove()
            db.drop_all()


def _base_to_decimal(value: str, base: int) -> int:
    result = 0
    for digit in value:
        number = int(digit, 36)
        if number >= base:
            raise ValueError("digit outside base")
        result = result * base + number
    return result


def _decimal_to_base(value: int, base: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if value == 0:
        return "0"
    digits = []
    while value:
        value, remainder = divmod(value, base)
        digits.append(alphabet[remainder])
    return "".join(reversed(digits))


def _run_case(case: dict) -> dict:
    data = case["input"]
    case_id = case["case_id"]
    if case_id == "v6-logic-precedence-counterexample":
        rows = []
        for a, b, c in product((False, True), repeat=3):
            rows.append(((a or b) and c, a or (b and c)))
        a, b, c = data["distinguishing_row"]
        return {
            "left": (a or b) and c,
            "right": a or (b and c),
            "truth_table_rows": len(rows),
            "left_outputs": [row[0] for row in rows],
            "right_outputs": [row[1] for row in rows],
        }
    if case_id == "v6-number-base-seven-round-trip":
        return {
            "expanded_value": _base_to_decimal(data["base7"], 7),
            "reverse_base7": _decimal_to_base(data["decimal"], 7),
            "digits_valid": all(int(digit) < 7 for digit in data["base7"]),
        }
    if case_id == "v6-spreadsheet-filtered-duplicate-values":
        selected = [value for value in data["values"] if value >= 10]
        return {
            "selected": selected, "count": len(selected), "sum": sum(selected),
            "mean": sum(selected) / len(selected), "minimum": min(selected), "maximum": max(selected),
        }
    if case_id == "v6-python-negative-integer-semantics":
        return {
            "odd_by_modulo": [value % 2 != 0 for value in data["values"]],
            "odd_by_bit": [bool(value & 1) for value in data["values"]],
            "divmod_minus17_by_2": [-17 // 2, -17 % 2],
        }
    if case_id == "v6-graph-isolated-vertex":
        degrees = Counter({vertex: 0 for vertex in data["vertices"]})
        for left, right in data["edges"]:
            degrees[left] += 1
            degrees[right] += 1
        return {"degrees": dict(degrees), "degree_sum": sum(degrees.values()), "twice_edges": 2 * len(data["edges"])}
    if case_id == "v6-ipv4-prefix-boundary-29":
        subnet = ip_network(data["address"], strict=False)
        point_to_point = ip_network(data["point_to_point_prefix"], strict=False)
        return {
            "network": str(subnet.network_address), "broadcast": str(subnet.broadcast_address),
            "addresses": subnet.num_addresses, "ordinary_hosts": subnet.num_addresses - 2,
            "rfc3021_point_to_point_hosts": [str(address) for address in point_to_point.hosts()],
        }
    if case_id == "v6-sql-left-join-duplicate-names":
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(
                "CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
                "CREATE TABLE orders(order_id INTEGER PRIMARY KEY, person_id INTEGER, amount INTEGER);"
            )
            connection.executemany("INSERT INTO people VALUES (?, ?)", data["people"])
            connection.executemany("INSERT INTO orders VALUES (?, ?, ?)", data["orders"])
            rows = connection.execute(
                "SELECT p.name, p.id, COUNT(o.order_id), COALESCE(SUM(o.amount), 0) "
                "FROM people p LEFT JOIN orders o ON o.person_id=p.id "
                "GROUP BY p.id, p.name ORDER BY p.name, p.id"
            ).fetchall()
            return {"rows": [list(row) for row in rows]}
        finally:
            connection.close()
    raise AssertionError(f"Unknown pilot test case: {case_id}")


def test_v6_new_subject_checks_reproduce_frozen_expected_results(v6_isolated_app):
    from app.ai_lab.knowledge_audit import TECHNICAL_AUDIT_V6_CASES

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["technical_cases"]
    assert fixture["protocol"]["independent_of_v5_cases"] is True
    assert fixture["protocol"]["no_learner_data"] is True
    assert fixture["protocol"]["no_teacher_approval"] is True
    published = {case["case_id"]: case for case in TECHNICAL_AUDIT_V6_CASES}

    with v6_isolated_app.app_context():
        snapshot = knowledge_base.knowledge_snapshot()
        reports = {report["case_id"]: report for report in snapshot["technical_audits"]}
        for case in cases:
            observed = _run_case(case)
            assert observed == case["expected"], case["case_id"]
            assert published[case["case_id"]]["input"] == case["input"]
            assert published[case["case_id"]]["observed"] == observed
            assert reports[case["case_id"]]["result"] == "passed"
            assert reports[case["case_id"]]["matches_current_version"] is True

        assert snapshot["counts"]["machine_check_results_recorded"] == 14
        assert snapshot["counts"]["machine_check_results_current"] == 14
        assert snapshot["counts"]["approved_for_student_use"] == 0


def test_v6_teacher_dossiers_are_complete_but_wait_for_human_review(v6_isolated_app):
    with v6_isolated_app.app_context():
        snapshot = knowledge_base.knowledge_snapshot()
        entries = {item["stable_key"]: item for item in snapshot["entries"]}
        sources = {item["source_key"]: item for item in snapshot["sources"]}
        dossiers = snapshot["expert_pilot_dossiers"]

        assert len(dossiers) == 7
        for dossier in dossiers:
            entry = entries[dossier["stable_key"]]
            content = entry["content"]
            assert dossier["matches_current_version"] is True
            assert dossier["review_status"] == "awaiting_teacher_expert_review"
            assert len(dossier["human_questions"]) >= 2
            assert content["assessed_skill"]["skill_key"]
            assert len(content["skill_progression"]) == 5
            assert content["examples"] and content["misconceptions"] and content["diagnostics"]
            assert content["solution_steps"] and content["interventions"] and content["subject_checks"]
            assert entry["source_refs"]
            assert all(ref["source_key"] in sources for ref in entry["source_refs"])
            assert all(link["relationship"] == "preliminary" for link in content.get("task_links", []))


def test_v6_tutor_retrieval_uses_sources_without_claiming_student_mastery(v6_isolated_app):
    from app.ai_lab.lesson_intelligence import _lesson_knowledge_context
    from app.ai_lab.tutor_core import _attach_knowledge_context

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with v6_isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        for scenario in fixture["tutor_scenarios"]:
            segments = [{"segment_kind": "dialogue", "speaker_role": "student", "text": scenario["query"]}]
            lesson_context = _lesson_knowledge_context(segments)
            keys = [item["stable_key"] for item in lesson_context["items"]]
            assert scenario["knowledge_key"] in keys, (scenario["scenario_id"], keys)
            assert lesson_context["used_as_transcript_evidence"] is False

            proposal = {
                "evidence": [],
                "skill_summary": {"skill_id": scenario["skill_id"], "task_number": scenario["task_number"]}
                if scenario["skill_id"] else {"status": "insufficient_data"},
                "next_lesson": {"title": scenario["query"]},
                "proposal": {"skill_titles": []},
            }
            _attach_knowledge_context(proposal)
            if scenario["evidence_state"] == "insufficient_data":
                assert proposal["knowledge_context"] == []
                assert proposal["knowledge_context_status"] == "no_source_match"
            else:
                attached = {item["stable_key"]: item for item in proposal["knowledge_context"]}
                assert scenario["knowledge_key"] in attached
                assert attached[scenario["knowledge_key"]]["status"] in knowledge_base.RETRIEVAL_DECISIONS
            assert scenario["student_status_claim_allowed"] is False

