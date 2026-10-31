from __future__ import annotations

import json
import sqlite3
from ipaddress import ip_interface
from pathlib import Path

import pytest

from app.ai_lab import knowledge_base


FIXTURE = Path(__file__).parents[1] / "fixtures" / "ai_lab_knowledge_v5_review_cases.json"


@pytest.fixture()
def v5_isolated_app():
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


def _review_details(status="checked"):
    result = {
        item["key"]: {"status": status, "comment": ""}
        for item in knowledge_base.EDITORIAL_CRITERIA
    }
    result["test_evidence"] = {
        "status": "not_applicable",
        "comment": "Для этой версии автоматический запуск не зарегистрирован.",
    }
    return result


def test_knowledge_seed_is_idempotent_and_does_not_replace_manual_versions(v5_isolated_app):
    from app.ai_lab.knowledge_data import KNOWLEDGE_DATA_VERSION
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeSource, AiLabKnowledgeVersion

    with v5_isolated_app.app_context():
        first = knowledge_base.knowledge_snapshot()
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key="ege.inf.logic-boundaries.v1").one()
        latest = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id).order_by(
            AiLabKnowledgeVersion.version_no.desc()
        ).first()
        content = dict(latest.content_json)
        content["explanation"] += " Редакционное дополнение для проверки воспроизводимости."
        next_version = knowledge_base.create_knowledge_version(None, {
            "stable_key": entry.stable_key,
            "title": latest.title,
            "codifier_codes": entry.codifier_codes_json,
            "tags": latest.tags_json,
            "source_refs": latest.source_refs_json,
            "change_reason": "Проверка идемпотентного seed v5.",
            "content": content,
        })

        second = knowledge_base.knowledge_snapshot()

        assert first["data_version"] == KNOWLEDGE_DATA_VERSION == second["data_version"]
        assert AiLabKnowledgeEntry.query.count() == 20
        assert AiLabKnowledgeSource.query.count() == 16
        assert next_version.version_no == latest.version_no + 1
        assert AiLabKnowledgeVersion.query.filter_by(id=next_version.id).one().content_json == content
        assert next(item for item in second["entries"] if item["stable_key"] == entry.stable_key)["version_no"] == next_version.version_no
        assert second["counts"]["approved_for_student_use"] == 0
        historical_audit = next(item for item in second["technical_audits"] if item["stable_key"] == entry.stable_key)
        assert historical_audit["result"] == "passed"
        assert historical_audit["matches_current_version"] is False


def test_knowledge_seed_persists_and_reloads_in_a_disposable_sqlite_file(tmp_path):
    from app import create_app, db

    sqlite_path = (tmp_path / "knowledge-v5-synthetic.sqlite").as_posix()
    config = {
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + sqlite_path,
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    }
    first_app = create_app(config)
    with first_app.app_context():
        db.create_all()
        first = knowledge_base.knowledge_snapshot()
        assert first["counts"]["materials"] == 20
        db.session.remove()

    second_app = create_app(config)
    with second_app.app_context():
        second = knowledge_base.knowledge_snapshot()
        assert second["data_version"] == first["data_version"]
        assert second["counts"]["materials"] == first["counts"]["materials"]
        assert second["counts"]["sources"] == first["counts"]["sources"]
        assert second["counts"]["approved_for_student_use"] == 0
        db.session.remove()
        db.drop_all()


def test_v5_coverage_reports_separate_dimensions_without_inventing_test_runs(v5_isolated_app):
    with v5_isolated_app.app_context():
        snapshot = knowledge_base.knowledge_snapshot()
        ipv4 = next(item for item in snapshot["coverage"] if item["code"] == "1.2")
        gap = next(item for item in snapshot["coverage"] if item["status"] == "not_developed")

        assert snapshot["counts"]["coverage_items"] == 45
        assert snapshot["counts"]["materials"] == 20
        assert snapshot["counts"]["machine_check_results_recorded"] == 14
        assert snapshot["counts"]["machine_check_results_current"] == 14
        assert snapshot["counts"]["machine_check_results_outdated"] == 0
        assert ipv4["status"] == "has_material"
        assert ipv4["quality"]["full_card_count"] >= 1
        assert ipv4["quality"]["example_count"] >= 1
        assert ipv4["quality"]["machine_check_status"] == "current"
        assert ipv4["quality"]["machine_check_case_count"] == 2
        assert gap["status"] == "not_developed"
        assert snapshot["status_labels"]["source_checked"].startswith("Источники сверены")
        assert snapshot["counts"]["approved_for_student_use"] == 0


def test_tutor_retrieval_refuses_material_when_every_source_is_stale(v5_isolated_app):
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeSource, AiLabKnowledgeVersion

    with v5_isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key="ege.inf.sql-relational-query.v1").one()
        version = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id).order_by(
            AiLabKnowledgeVersion.version_no.desc()
        ).first()
        query = "SQL JOIN внешний ключ реляционная таблица"
        assert entry.stable_key in [item["stable_key"] for item in knowledge_base.retrieve_knowledge(query)]

        for source_key in version.source_refs_json:
            source = AiLabKnowledgeSource.query.filter_by(source_key=source_key).one()
            source.source_status = "superseded"
        from app import db
        db.session.commit()

        assert entry.stable_key not in [item["stable_key"] for item in knowledge_base.retrieve_knowledge(query)]


def test_review_queue_checklist_is_auditable_and_never_auto_approves(v5_isolated_app):
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeVersion

    with v5_isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key="ege.inf.logic-boundaries.v1").one()
        version = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id).order_by(
            AiLabKnowledgeVersion.version_no.desc()
        ).first()
        incomplete = _review_details()
        incomplete["subject_accuracy"] = {"status": "unchecked", "comment": ""}
        try:
            knowledge_base.review_knowledge_version(
                1, version.id, "approved", "Попытка неполного утверждения.", incomplete
            )
        except knowledge_base.KnowledgeBaseError as error:
            assert error.code == "review_checklist_incomplete"
        else:
            raise AssertionError("Неполный чек-лист не должен утверждать материал")

        partial = _review_details()
        partial["subject_accuracy"] = {"status": "needs_work", "comment": "Не проверен граничный случай."}
        event = knowledge_base.review_knowledge_version(
            1, version.id, "in_review", "Предварительная редакционная проверка.", partial
        )
        assert event.review_details_json["subject_accuracy"]["status"] == "needs_work"
        assert knowledge_base._status_for_version(version.id)[0] == "in_review"

        try:
            knowledge_base.review_knowledge_version(
                1, version.id, "reviewed", "Попытка закрыть открытое замечание.", partial
            )
        except knowledge_base.KnowledgeBaseError as error:
            assert error.code == "review_has_open_issues"
        else:
            raise AssertionError("Открытое замечание не должно позволять завершить проверку")

        rework = knowledge_base.review_knowledge_version(
            1, version.id, "rework", "Вернуть с предметным замечанием.", partial
        )
        assert rework.decision == "rework"
        history = knowledge_base.knowledge_entry_history(entry.id)["versions"][0]
        assert len(history["review_history"]) == 3
        assert history["review_history"][0]["details"]["subject_accuracy"]["comment"] == "Не проверен граничный случай."
        assert knowledge_base._status_for_version(version.id)[0] == "rework"


def test_v5_technical_cases_use_independent_new_inputs(v5_isolated_app):
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["technical_cases"]
    from core.db_models import AiLabKnowledgeEntry

    with v5_isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        known = {item.stable_key for item in AiLabKnowledgeEntry.query.all()}
        snapshot = knowledge_base.knowledge_snapshot()
        reports = {item["case_id"]: item for item in snapshot["technical_audits"]}
        for case in cases:
            assert case["knowledge_key"] in known
            report = reports[case["case_id"]]
            assert report["stable_key"] == case["knowledge_key"]
            assert report["input"] == case["input"]
            assert report["observed"] == case["expected"]
            assert report["result"] == "passed"
            assert report["matches_current_version"] is True
            assert len(report["content_sha256"]) == 64

    outcomes = {}
    for case in cases:
        case_id = case["case_id"]
        data = case["input"]
        expected = case["expected"]
        if case_id == "logic-boundary-new-values":
            outcomes[case_id] = {
                "positive": [value > 0 for value in data["values"]],
                "nonnegative": [value >= 0 for value in data["values"]],
            }
        elif case_id == "number-base-round-trip":
            outcomes[case_id] = {
                "binary_decimal": int(data["binary"], 2),
                "hexadecimal": format(data["decimal"], "X"),
            }
        elif case_id == "spreadsheet-new-selection":
            selected = [row["value"] for row in data["rows"] if row["include"]]
            outcomes[case_id] = {
                "count": len(selected),
                "sum": sum(selected),
                "minimum": min(selected),
                "maximum": max(selected),
                "mean": sum(selected) / len(selected),
            }
        elif case_id == "python-negative-parity":
            outcomes[case_id] = {
                "odd": [value % 2 != 0 for value in data["values"]],
            }
            assert outcomes[case_id]["odd"] == [bool(value & 1) for value in data["values"]]
        elif case_id == "graph-degree-handshake":
            degrees = dict.fromkeys(data["vertices"], 0)
            for left, right in data["edges"]:
                degrees[left] += 1
                degrees[right] += 1
            outcomes[case_id] = {
                "degrees": degrees,
                "degree_sum": sum(degrees.values()),
                "edge_count": len(data["edges"]),
            }
        elif case_id == "ipv4-new-prefix-boundary":
            network = ip_interface(data["address"]).network
            outcomes[case_id] = {
                "network": str(network.network_address),
                "broadcast": str(network.broadcast_address),
                "addresses": network.num_addresses,
                "hosts": network.num_addresses - 2,
            }
        elif case_id == "sql-join-new-data":
            connection = sqlite3.connect(":memory:")
            try:
                connection.executescript(
                    "CREATE TABLE students(id TEXT PRIMARY KEY, name TEXT);"
                    "CREATE TABLE scores(student_id TEXT, score INTEGER);"
                )
                connection.executemany("INSERT INTO students VALUES (?, ?)", data["students"])
                connection.executemany("INSERT INTO scores VALUES (?, ?)", data["scores"])
                rows = connection.execute(
                    "SELECT s.name, COUNT(g.score), SUM(g.score) "
                    "FROM students s JOIN scores g ON g.student_id=s.id "
                    "GROUP BY s.id, s.name ORDER BY s.name"
                ).fetchall()
                outcomes[case_id] = {"rows": [list(row) for row in rows]}
            finally:
                connection.close()
        assert outcomes[case_id] == expected, case_id


def test_technical_audit_report_is_bound_to_immutable_content_hash(v5_isolated_app):
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeVersion

    with v5_isolated_app.app_context():
        snapshot = knowledge_base.knowledge_snapshot()
        key = "ege.inf.ip-prefix-mask.v1"
        report = next(item for item in snapshot["technical_audits"] if item["stable_key"] == key)
        assert report["matches_current_version"] is True
        assert report["current_content_sha256"] == report["content_sha256"]

        entry = AiLabKnowledgeEntry.query.filter_by(stable_key=key).one()
        latest = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id).order_by(
            AiLabKnowledgeVersion.version_no.desc()
        ).first()
        content = dict(latest.content_json)
        content["explanation"] += " Небольшое новое редакционное уточнение."
        knowledge_base.create_knowledge_version(None, {
            "stable_key": entry.stable_key,
            "title": latest.title,
            "codifier_codes": entry.codifier_codes_json,
            "tags": latest.tags_json,
            "source_refs": latest.source_refs_json,
            "change_reason": "Проверка устаревания техотчёта.",
            "content": content,
        })
        updated = knowledge_base.knowledge_snapshot()
        updated_report = next(item for item in updated["technical_audits"] if item["stable_key"] == key)
        assert updated_report["result"] == "passed"
        assert updated_report["matches_current_version"] is False
        assert updated_report["current_content_sha256"] != updated_report["content_sha256"]


def test_v5_retrieval_control_queries_are_frozen(v5_isolated_app):
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["search_cases"]
    with v5_isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        results_by_case = {}
        for case in cases:
            matches = knowledge_base.retrieve_knowledge(case["query"], limit=5)
            keys = [item["stable_key"] for item in matches]
            results_by_case[case["case_id"]] = keys
            assert all(key in keys for key in case["must_include"]), (case["case_id"], keys)
            assert not any(key in keys for key in case["must_exclude"]), (case["case_id"], keys)
            assert keys == case["expected_keys"], (case["case_id"], keys)
