from __future__ import annotations

from copy import deepcopy

import pytest

from app.ai_lab import knowledge_base
from app.ai_lab.knowledge_data import DEEPENED_ENTRIES, SEED_ENTRIES


def complete_review_details():
    details = {
        item["key"]: {"status": "checked", "comment": ""}
        for item in knowledge_base.EDITORIAL_CRITERIA
    }
    details["test_evidence"] = {
        "status": "not_applicable",
        "comment": "Автоматическое исполнение пока не записывается.",
    }
    return details


@pytest.fixture()
def isolated_app():
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


def test_fipi_coverage_is_scoped_and_seed_is_idempotent(isolated_app):
    from app import db
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeSource

    with isolated_app.app_context():
        first = knowledge_base.knowledge_snapshot()
        second = knowledge_base.knowledge_snapshot()

        assert first["data_version"] == second["data_version"]
        assert first["counts"]["coverage_items"] == 45
        assert first["counts"]["included_in_2026"] == 29
        assert first["counts"]["included_in_2026"] == sum(row["in_fipi_2026_kim"] for row in first["coverage"])
        assert len(first["coverage_groups"]) == 4
        assert first["counts"]["content_started"] == sum(row["entry_count"] > 0 for row in first["coverage"])
        assert first["counts"]["content_started"] > 8
        assert first["counts"]["approved_for_student_use"] == 0
        assert AiLabKnowledgeEntry.query.count() == 20
        assert AiLabKnowledgeSource.query.count() == 16
        assert sum(len(item["content"]["examples"]) for item in DEEPENED_ENTRIES) >= 18
        assert all((item["content"]["task_links"] or item["content"].get("curriculum_suggestions"))
                   and (item["content"]["lesson_links"] or item["content"].get("curriculum_suggestions"))
                   for item in DEEPENED_ENTRIES)
        project = next(row for row in second["sources"] if row["source_key"] == "fipi.informatics.2027")
        assert project["source_status"] == "official_project"
        assert "проект" in project["metadata"]["coverage_role"]


def test_tutor_core3_seed_appends_current_knowledge_and_enables_exact_practice_skill(isolated_app):
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeReviewEvent, AiLabKnowledgeVersion
    from app.ai_lab.practice import list_practice_skills

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key="ege.inf.ip-prefix-mask.v1").one()
        historical_version = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=3).one()

        knowledge_base.ensure_tutor_core3_knowledge()
        current_version = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=4).one()
        counts_after_first_seed = (
            AiLabKnowledgeEntry.query.count(),
            AiLabKnowledgeVersion.query.count(),
            AiLabKnowledgeReviewEvent.query.count(),
        )
        knowledge_base.ensure_tutor_core3_knowledge()
        counts_after_second_seed = (
            AiLabKnowledgeEntry.query.count(),
            AiLabKnowledgeVersion.query.count(),
            AiLabKnowledgeReviewEvent.query.count(),
        )

        assert counts_after_first_seed == counts_after_second_seed
        assert historical_version.version_no == 3
        assert knowledge_base._status_for_version(current_version.id)[0] == "source_checked"
        ipv4_skill = next(
            item for item in list_practice_skills()
            if item["knowledge_stable_key"] == "ege.inf.ip-prefix-mask.v1"
        )
        assert ipv4_skill["skill_id"] == current_version.content_json["assessed_skill"]["skill_key"]
        assert ipv4_skill["knowledge_version"] == 4


def test_exact_platform_task_binding_requires_source_checked_knowledge_and_fingerprint(isolated_app):
    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()

        bindings = knowledge_base.source_checked_platform_task_bindings()

        assert len(bindings) == 1
        assert bindings[0]["task_id"] == 230
        assert bindings[0]["source_key"] == "kompege-db:Tasks:222"
        assert bindings[0]["course_id"] == 4
        assert bindings[0]["course_version"] == 1
        assert bindings[0]["lesson_id"] == 75
        assert bindings[0]["skill_id"] == "exam-skill:1"
        assert bindings[0]["knowledge_version"] == 1


def test_exact_platform_task_binding_rejects_malformed_fingerprint():
    seed = deepcopy(next(item for item in DEEPENED_ENTRIES
                         if item["stable_key"] == "ege.inf.graph-table-task230-binding.v1"))
    seed["content"]["platform_task_links"][0]["content_fingerprint"] = "not-a-hash"

    with pytest.raises(knowledge_base.KnowledgeBaseError, match="точную связь"):
        knowledge_base._validate_content(seed["content"])


def test_tutor_rag_retrieves_exact_source_checked_platform_task_binding(isolated_app):
    from app.ai_lab.tutor_core import _attach_knowledge_context

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        binding = knowledge_base.source_checked_platform_task_bindings()[0]
        proposal = {
            "evidence": [{
                "event_id": "platform-submission:501:attempt:1:task:230",
                "skill_ids": [binding["skill_id"]],
                "reason": "Проверенный ответ сохранённой сдачи.",
                "provenance": {"platform_task_binding": binding},
            }],
            "skill_summary": {"skill_id": binding["skill_id"], "task_number": 1},
            "next_lesson": {"title": "Чтение графика и таблицы"},
            "proposal": {"skill_titles": ["Чтение графика и таблицы"]},
        }

        result = _attach_knowledge_context(proposal)

        assert result["knowledge_context_status"] == "retrieved"
        exact_binding = next(item for item in result["knowledge_context"]
                             if item["stable_key"] == "ege.inf.graph-table-task230-binding.v1")
        assert exact_binding["knowledge_ref"] == "knowledge:ege.inf.graph-table-task230-binding.v1:v1"
        assert exact_binding["status"] == "source_checked"


def test_tutor_profile_list_includes_exact_platform_task_knowledge(isolated_app, monkeypatch):
    from app.ai_lab import tutor_core

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        binding = knowledge_base.source_checked_platform_task_bindings()[0]
        case = {
            "profile_id": "platform-student:12",
            "evidence": [{
                "event_id": "platform-submission:501:attempt:1:task:230",
                "skill_ids": [binding["skill_id"]],
                "reason": "Проверенный ответ сохранённой сдачи.",
                "provenance": {"platform_task_binding": binding},
            }],
            "skill_summary": {"skill_id": binding["skill_id"], "task_number": 1},
            "next_lesson": {"title": "Чтение графика и таблицы"},
            "proposal": {"skill_titles": ["Чтение графика и таблицы"]},
        }
        monkeypatch.setattr(tutor_core, "_safe_course", lambda: ({"course_version": 1, "title": "Пилот"}, []))
        monkeypatch.setattr(tutor_core, "_fixture_events", lambda *_args: {})
        monkeypatch.setattr(tutor_core, "_lesson_payload", lambda *_args: [])
        monkeypatch.setattr(tutor_core, "_platform_profile_cases", lambda _actor_id: [case])

        result = tutor_core.list_tutor_cases(actor_user_id=4)

        listed_case = next(item for item in result["cases"] if item["profile_id"] == "platform-student:12")
        assert listed_case["knowledge_context_status"] == "retrieved"
        assert any(item["stable_key"] == "ege.inf.graph-table-task230-binding.v1"
                   for item in listed_case["knowledge_context"])


def test_new_version_is_immutable_and_manual_review_unlocks_retrieval(isolated_app):
    from app import db
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeReviewEvent, AiLabKnowledgeVersion

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key="ege.inf.positional-number-systems.v1").one()
        version_one = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=1).one()
        original_content = deepcopy(version_one.content_json)
        seed = deepcopy(SEED_ENTRIES[2])
        seed["content"]["explanation"] += " Дополнение для проверки версионирования."

        version_two = knowledge_base.create_knowledge_version(None, {
            "stable_key": seed["stable_key"],
            "title": seed["title"],
            "codifier_codes": seed["codes"],
            "tags": seed["tags"],
            "source_refs": seed["source_refs"],
            "change_reason": "Уточнение учебного объяснения после проверки.",
            "content": seed["content"],
        })

        assert version_two.version_no == 4
        assert version_one.content_json == original_content
        assert knowledge_base._status_for_version(version_two.id)[0] == "draft"
        assert not knowledge_base.retrieve_knowledge("позиционные системы счисления")

        knowledge_base.review_knowledge_version(
            None, version_two.id, "reviewed", "Факты и примеры проверены по источнику.",
            complete_review_details(),
        )
        results = knowledge_base.retrieve_knowledge("позиционные системы счисления")

        assert results[0]["stable_key"] == entry.stable_key
        assert results[0]["version_no"] == 4
        assert results[0]["status"] == "reviewed"
        assert version_one.content_json == original_content
        old_events = AiLabKnowledgeReviewEvent.query.filter_by(version_id=version_one.id).all()
        assert len(old_events) == 1
        assert old_events[0].decision == "source_checked"


def test_project_material_is_never_injected_into_tutor_retrieval(isolated_app):
    from core.db_models import AiLabKnowledgeEntry

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        entry = AiLabKnowledgeEntry(
            stable_key="ege.inf.project-only-test",
            codifier_codes_json=["1.2"], entry_kind="concept",
        )
        from app import db
        db.session.add(entry)
        db.session.flush()
        seed = deepcopy(SEED_ENTRIES[0])
        version = knowledge_base.create_knowledge_version(None, {
            "stable_key": entry.stable_key,
            "title": "Проектная заметка о подсетях",
            "codifier_codes": ["1.2"],
            "tags": ["проектный материал", "cidr", "маска"],
            "source_refs": ["fipi.informatics.2027"],
            "change_reason": "Проверка фильтрации проектной редакции.",
            "content": seed["content"],
        })
        knowledge_base.review_knowledge_version(
            None, version.id, "approved", "Тестовое решение владельца базы знаний.",
            complete_review_details(),
        )

        results = knowledge_base.retrieve_knowledge("проектный материал cidr маска")

        assert all(result["stable_key"] != entry.stable_key for result in results)


def test_review_rejects_stale_versions_and_unknown_sources(isolated_app):
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeVersion

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key="ege.inf.logic-boundaries.v1").one()
        original = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=1).one()
        seed = deepcopy(SEED_ENTRIES[1])
        seed["content"]["learning_goal"] += " Проверяемая версия."
        newer = knowledge_base.create_knowledge_version(None, {
            "stable_key": seed["stable_key"], "title": seed["title"], "codifier_codes": seed["codes"],
            "tags": seed["tags"], "source_refs": seed["source_refs"],
            "change_reason": "Новая версия для теста stale.", "content": seed["content"],
        })
        with pytest.raises(knowledge_base.KnowledgeBaseError, match="последняя версия"):
            knowledge_base.review_knowledge_version(None, original.id, "approved", "Не следует утверждать старый снимок.")

        payload = {
            "stable_key": "ege.inf.unregistered-source-test", "title": "Проверка неизвестного источника",
            "codifier_codes": ["3.6"], "tags": ["контроль"], "source_refs": ["unknown.source"],
            "change_reason": "Проверка отказа неизвестному источнику.",
            "content": deepcopy(SEED_ENTRIES[3]["content"]),
        }
        with pytest.raises(knowledge_base.KnowledgeBaseError, match="источников"):
            knowledge_base.create_knowledge_version(None, payload)
        assert newer.version_no == 4


def test_tutor_attaches_source_backed_knowledge_for_matching_lesson(isolated_app):
    from app.ai_lab.tutor_core import _attach_knowledge_context

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        proposal = _attach_knowledge_context({
            "skill_summary": {"skill_id": "number_systems.positional", "task_number": 14},
            "next_lesson": {"title": "Урок 12. Задание №14. Системы счисления"},
            "proposal": {"skill_titles": ["Позиционные системы счисления"]},
            "evidence": [],
        })

        assert proposal["knowledge_context_status"] == "retrieved"
        assert any(item["stable_key"] == "ege.inf.positional-number-systems.v1"
                   for item in proposal["knowledge_context"])
        assert all(item["source_refs"] for item in proposal["knowledge_context"])
        assert all(item["status"] in {"source_checked", "reviewed", "approved"}
                   for item in proposal["knowledge_context"])


def test_tutor_retrieves_graph_article_for_exact_course_skill(isolated_app):
    from app.ai_lab.tutor_core import _attach_knowledge_context

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        proposal = _attach_knowledge_context({
            "skill_summary": {"skill_id": "exam-skill:1", "task_number": 1},
            "next_lesson": {"title": "Урок 9. Задание №1. Графы и таблицы"},
            "proposal": {"skill_titles": ["Сопоставление графа и весовой таблицы"]},
            "evidence": [],
        })

        retrieved_keys = {item["stable_key"] for item in proposal["knowledge_context"]}
        assert {
            "ege.inf.graph-table-matching.v1",
            "ege.inf.graph-table-task230-binding.v1",
        }.issubset(retrieved_keys)
        exact_binding = next(item for item in proposal["knowledge_context"]
                             if item["stable_key"] == "ege.inf.graph-table-task230-binding.v1")
        assert exact_binding["knowledge_ref"].endswith("graph-table-task230-binding.v1:v1")
        matching_article = next(item for item in proposal["knowledge_context"]
                                if item["stable_key"] == "ege.inf.graph-table-matching.v1")
        assert matching_article["content"]["assessed_skill"]["skill_key"] == "skill.inf.graph-table-matching"
        assert matching_article["content"]["solution_steps"]
        assert matching_article["content"]["diagnostic_patterns"]
        assert "не равен экспертному" in matching_article["scope_note"]
        assert proposal["knowledge_context"][0]["source_refs"]


def test_tutor_rejects_unknown_knowledge_citations():
    from app.ai_lab.tutor_core import TutorCoreError, _validate_narrative

    raw = {
        "student_feedback": "Разберём границу в условии.",
        "teacher_explanation": "В ответе есть ссылка на проверяемый материал.",
        "uncertainty_note": "Вывод ограничен доступными событиями.",
        "evidence_refs": ["event:1"],
        "knowledge_refs": ["knowledge:unknown:v1"],
    }

    with pytest.raises(TutorCoreError, match="неизвестную версию"):
        _validate_narrative(raw, {"event:1"}, {"knowledge:known:v1"}, require_knowledge_refs=True)

    raw["knowledge_refs"] = ["knowledge:known:v1"]
    validated = _validate_narrative(raw, {"event:1"}, {"knowledge:known:v1"}, require_knowledge_refs=True)
    assert validated["knowledge_refs"] == ["knowledge:known:v1"]


def test_deepened_examples_and_course_links_are_machine_checkable(isolated_app):
    import ipaddress
    from itertools import product

    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeVersion

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        for item in DEEPENED_ENTRIES:
            entry = AiLabKnowledgeEntry.query.filter_by(stable_key=item["stable_key"]).one()
            version = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=item["version_no"]).one()
            content = version.content_json
            if content["lesson_links"]:
                assert all(link["relationship"] in {"curriculum", "preliminary"}
                           for link in content["lesson_links"])
            else:
                assert content.get("curriculum_suggestions")
            assert all(link["relationship"] == "preliminary" for link in content["task_links"])

        subnet = ipaddress.ip_interface("192.168.7.141/26").network
        assert str(subnet.network_address) == "192.168.7.128"
        assert subnet.num_addresses == 64
        assert sum(1 for _ in subnet.hosts()) == 62
        assert sum(1 for _ in ipaddress.ip_network("192.0.2.0/30").hosts()) == 2
        assert sum(1 for _ in ipaddress.ip_network("192.0.2.0/31").hosts()) == 2

        assert all((not (a and b)) == ((not a) or (not b)) for a, b in product((False, True), repeat=2))
        assert int("101101", 2) == 45
        assert int("2F", 16) == 47
        assert int("120", 3) == 15
        assert [(n % 2 == 0, (n & 1) == 0) for n in (-4, -3, 0, 5)] == [
            (True, True), (False, False), (True, True), (False, False),
        ]
        def divisor_count(n):
            return sum(1 for divisor in range(1, n + 1) if n % divisor == 0)

        assert [divisor_count(n) for n in (36, 49, 1)] == [9, 3, 1]
        values = (4, 6, 8, 2)
        assert (sum(values), sum(values) / len(values), min(values), max(values)) == (20, 5, 2, 8)


def test_graph_table_example_degree_counts_are_machine_checked():
    from app.ai_lab.knowledge_data import DEEPENED_ENTRIES

    article = next(item for item in DEEPENED_ENTRIES
                   if item["stable_key"] == "ege.inf.graph-table-matching.v1")
    edges = [("A", "B"), ("A", "C"), ("A", "D"), ("C", "D")]
    degrees = {vertex: 0 for vertex in "ABCD"}
    for left, right in edges:
        degrees[left] += 1
        degrees[right] += 1

    assert degrees == {"A": 3, "B": 1, "C": 2, "D": 2}
    assert sum(degrees.values()) == 2 * len(edges)
    assert article["content"]["task_links"][0]["skill_id"] == "exam-skill:1"


def test_full_cards_have_independent_subject_checks_and_no_auto_approval(isolated_app):
    import fnmatch
    import ipaddress
    import sqlite3
    from itertools import product

    from app.ai_lab.knowledge_data import DEEPENED_ENTRIES
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeVersion

    full = [item for item in DEEPENED_ENTRIES if "assessed_skill" in item["content"]]
    full_by_check = {
        check["test_id"]: (item, check)
        for item in full
        for check in item["content"]["subject_checks"]
    }
    assert len(full) == 19
    assert len(full_by_check) == sum(len(item["content"]["subject_checks"]) for item in full)

    # Execute independent checks; user-authored source text is never evaluated as code.
    ipnet = ipaddress.ip_interface("192.168.7.141/26").network
    assert (str(ipnet.network_address), str(ipnet.broadcast_address), ipnet.num_addresses) == (
        "192.168.7.128", "192.168.7.191", 64,
    )
    subnet31 = ipaddress.ip_network("192.0.2.0/31")
    assert (subnet31.num_addresses, len(list(subnet31.hosts()))) == (2, 2)
    assert [(n > 0, n >= 0) for n in (-1, 0, 1)] == [
        (False, False), (False, True), (True, True),
    ]
    assert [(a, b) for a, b in product((False, True), repeat=2)
            if (a and b) != (a or b)] == [(False, True), (True, False)]
    assert int("101101", 2) == 45 and format(45, "b") == "101101"
    assert int("2F", 16) == 47 and format(47, "X") == "2F"
    assert [(n % 2 == 0, (n & 1) == 0) for n in (-4, -3, 0, 5)] == [
        (True, True), (False, False), (True, True), (False, False),
    ]
    assert (sum((4, 6, 8, 2)), sum((4, 6, 8, 2)) / 4, min((4, 6, 8, 2)), max((4, 6, 8, 2))) == (20, 5, 2, 8)
    assert [sum(1 for d in range(1, n + 1) if n % d == 0) for n in (36, 49, 1)] == [9, 3, 1]

    edges = [("A", "B"), ("A", "C"), ("A", "D"), ("C", "D")]
    degrees = {node: sum(node in edge for edge in edges) for node in "ABCD"}
    assert degrees == {"A": 3, "B": 1, "C": 2, "D": 2}
    assert sum(degrees.values()) == 2 * len(edges)
    assert all(not other.startswith(word) for word in ("0", "10", "110", "111")
               for other in ("0", "10", "110", "111") if other != word)
    assert [name for name in ("ab.txt", "a.txt", "abc.csv")
            if fnmatch.fnmatchcase(name, "??*.txt")] == ["ab.txt"]
    assert (1024 * 768 * 24 // 8, 44_100 * 16 * 2 * 10 // 8) == (2_359_296, 1_764_000)
    seq = [4, 1, 6, 3]
    selected = [value for value in seq if value > 3]
    assert (len(selected), sum(selected)) == (2, 10)
    assert [value for value in [] if value > 3] == []
    assert [value for value in (3, 4) if value > 3] == [4]
    assert ("ABABA".count("A"), "ABABA".count("ABA")) == (3, 1)

    def recurrence(n):
        return 0 if n == 0 else 2 * recurrence(n - 1) + 1

    assert [recurrence(n) for n in range(4)] == [0, 1, 3, 7]
    sql = sqlite3.connect(":memory:")
    try:
        sql.executescript(
            "CREATE TABLE clients(id INTEGER PRIMARY KEY, name TEXT);"
            "CREATE TABLE orders(id INTEGER PRIMARY KEY, client_id INTEGER, amount INTEGER);"
            "INSERT INTO clients VALUES (1, 'Alice'), (2, 'Bob');"
            "INSERT INTO orders VALUES (1, 1, 10), (2, 1, 20), (3, 2, 5);"
        )
        assert sql.execute(
            "SELECT clients.name, SUM(orders.amount) FROM clients "
            "JOIN orders ON orders.client_id = clients.id GROUP BY clients.id ORDER BY clients.id"
        ).fetchall() == [("Alice", 30), ("Bob", 5)]
    finally:
        sql.close()
    assert (0.1 * 200, 0.1 * 500) == (20.0, 50.0)
    raw = [18, 19, 19, None, 20, 190]
    flagged = [value for value in raw if value is not None and not 0 <= value <= 100]
    assert flagged == [190] and raw[3] is None and raw.count(19) == 2

    def can_force_win(total):
        if total >= 5:
            return False
        return any(total + step >= 5 or not can_force_win(total + step) for step in (1, 2))

    assert [can_force_win(total) for total in range(5)] == [True, True, False, True, True]

    assert set(full_by_check) == {
        "kb-ip-prefix", "kb-logic-boundary", "kb-number-base", "kb-python-parity",
        "kb-spreadsheet-aggregates", "kb-divisor-count", "kb-graph-matching",
        "kb-logic-truth-table", "kb-prefix-code", "kb-file-mask", "kb-media-volume",
        "kb-graph-degree", "kb-sequence-processing", "kb-string-processing",
        "kb-recursion-trace", "kb-sql-query", "kb-spreadsheet-reference",
        "kb-data-quality", "kb-game-strategy",
    }
    assert all(check["method"] and check["scope"] for _, check in full_by_check.values())
    stage_keys = ("concept", "routine", "choice", "transfer", "verification")
    assert all(tuple(stage["stage_key"] for stage in item["content"]["skill_progression"]) == stage_keys
               for item in full)

    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        for item in full:
            entry = AiLabKnowledgeEntry.query.filter_by(stable_key=item["stable_key"]).one()
            version = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=item["version_no"]).one()
            assert knowledge_base._status_for_version(version.id)[0] == "source_checked"
            assert _is_full_pedagogical_card(version.content_json)


def _is_full_pedagogical_card(content):
    from app.ai_lab.knowledge_base import FULL_ENTRY_CONTENT_FIELDS

    return FULL_ENTRY_CONTENT_FIELDS.issubset(content)


def test_subject_search_retrieves_distinct_sections_with_pedagogical_context(isolated_app):
    queries = {
        "маска файлов звёздочка вопрос расширение": "ege.inf.file-mask-search.v1",
        "рекурсия базовый случай стек вызовов": "ege.inf.python-recursion-trace.v1",
        "реляционная таблица sql join первичный ключ": "ege.inf.sql-relational-query.v1",
        "электронные таблицы абсолютная ссылка адресация": "ege.inf.spreadsheet-cell-references.v1",
        "граф вершины степень матрица смежности": "ege.inf.graph-degree.v1",
    }
    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        for query, expected_key in queries.items():
            results = knowledge_base.retrieve_knowledge(query, limit=3)
            assert expected_key in {item["stable_key"] for item in results}, query

        recursion = next(item for item in knowledge_base.retrieve_knowledge(
            "рекурсия базовый случай стек вызовов", limit=3
        ) if item["stable_key"] == "ege.inf.python-recursion-trace.v1")
        assert recursion["content"]["assessed_skill"]
        assert [stage["stage_key"] for stage in recursion["content"]["skill_progression"]] == [
            "concept", "routine", "choice", "transfer", "verification",
        ]
        assert recursion["content"]["solution_steps"]
        assert recursion["content"]["diagnostics"]
        assert "subject_checks" not in recursion["content"]
        assert recursion["status"] == "source_checked"
        assert "не равен экспертному педагогическому утверждению" in recursion["scope_note"]


def test_editorial_full_card_creates_new_unapproved_version(isolated_app):
    from copy import deepcopy

    from app.ai_lab.knowledge_data import DEEPENED_ENTRIES
    from core.db_models import AiLabKnowledgeEntry, AiLabKnowledgeVersion

    card = next(item for item in DEEPENED_ENTRIES
                if item["stable_key"] == "ege.inf.python-string-processing.v1"
                and "assessed_skill" in item["content"])
    with isolated_app.app_context():
        knowledge_base.ensure_seeded_knowledge_base()
        old_entry = AiLabKnowledgeEntry.query.filter_by(stable_key=card["stable_key"]).one()
        old_version = AiLabKnowledgeVersion.query.filter_by(entry_id=old_entry.id, version_no=1).one()
        old_digest = old_version.content_sha256
        created = knowledge_base.create_knowledge_version(None, {
            "stable_key": card["stable_key"], "title": card["title"], "codifier_codes": card["codes"],
            "tags": card["tags"], "source_refs": card["source_refs"],
            "change_reason": "Редакторская версия для проверки полной структуры карточки.",
            "content": deepcopy(card["content"]),
        })
        assert created.version_no == 2
        assert knowledge_base._status_for_version(created.id)[0] == "draft"
        assert old_version.content_sha256 == old_digest
        assert knowledge_base._status_for_version(old_version.id)[0] == "source_checked"

        partial = deepcopy(card["content"])
        partial.pop("subject_checks")
        with pytest.raises(knowledge_base.KnowledgeBaseError, match="Полноценная карточка"):
            knowledge_base._validate_content(partial)


def test_knowledge_base_editor_template_compiles(isolated_app):
    with isolated_app.app_context():
        template = isolated_app.jinja_env.get_template("sandbox/ai_lab_knowledge.html")
        assert template.name == "sandbox/ai_lab_knowledge.html"
