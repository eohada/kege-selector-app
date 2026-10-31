from app.ai_lab.lesson_intelligence import (
    _build_prioritized_lesson_plan,
    _downgrade_unverified_independent_events,
    _enrich_learner_event_evidence,
    _is_explicit_difficulty_self_report,
    _is_only_verbal_understanding_claim,
    _merge_lesson_chunk_results,
    _recover_independent_attempt_candidates,
    _recover_literal_difficulty_self_reports,
    _validate_ai_result,
)


def _utterance(segment_id, role, text):
    return {
        "segment_id": segment_id,
        "segment_kind": "utterance",
        "speaker": "Ученик" if role == "student" else "Преподаватель",
        "speaker_role": role,
        "text": text,
        "timestamp": "00:00",
    }


def test_direct_difficulty_self_reports_are_preserved_without_promoting_them_to_diagnoses():
    assert _is_explicit_difficulty_self_report(
        _utterance("segment-247", "student", "Я, кажется, понял, что меня смущает."))
    assert _is_explicit_difficulty_self_report(
        _utterance("segment-265", "student", "Адрес сети без подсказки пока не всегда нахожу."))
    assert not _is_explicit_difficulty_self_report(
        _utterance("segment-control", "student", "Теперь понимаю и могу объяснить."))
    assert not _is_explicit_difficulty_self_report(
        _utterance("teacher-control", "teacher", "Я не понимаю этот пример."))


def test_explicit_independent_attempts_are_captured_across_subjects_as_unverified_candidates():
    examples = [
        ("logic", "Проверь логическое выражение сам, я не подсказываю.", "При x=1 выражение ложно."),
        ("spreadsheet", "Реши задачу в таблице без подсказки.", "Формула суммирует только строки с нужной категорией."),
        ("algorithm", "Выполни алгоритм самостоятельно.", "После третьего шага получаю число 14."),
        ("number-system", "Переведи число сам, без моей помощи.", "В шестнадцатеричной записи это 2F."),
        ("alternative", "Реши задачу самостоятельно, я не подсказываю.", "Я перебрал допустимые варианты и получил четыре решения."),
    ]

    for domain, prompt, answer in examples:
        segments = [
            _utterance(f"{domain}-teacher", "teacher", prompt),
            _utterance(f"{domain}-student", "student", answer),
        ]
        event, = _recover_independent_attempt_candidates(segments, [])

        assert event["kind"] == "independent_demonstration"
        assert event["source_refs"] == [f"{domain}-teacher", f"{domain}-student"]
        assert event["semantic_support_status"] == "manual_review_required"
        assert "правильность" in event["summary"]
        assert event["skill_id"] is None


def test_independent_attempt_keeps_all_student_steps_across_neutral_teacher_turn():
    segments = [
        _utterance("teacher-task", "teacher", "Вот задание; я не подсказываю."),
        _utterance("student-step-1", "student", "Блок по 32, значение 109 входит в диапазон 96–127."),
        _utterance("teacher-neutral", "teacher", "Продолжай."),
        _utterance("student-step-2", "student", "Тогда сеть заканчивается на 96, broadcast — 127."),
    ]

    event, = _recover_independent_attempt_candidates(segments, [])

    assert event["source_refs"] == ["teacher-task", "student-step-1", "student-step-2"]
    assert "попытку, но не правильность" in event["validation_reason"]


def test_no_hint_cue_does_not_promote_self_report_with_numbers_and_merges_student_steps():
    segments = [
        _utterance("segment-173", "teacher", "Повтори это на другом примере без моей помощи."),
        _utterance("segment-175", "student", "Не уверен. Когда меняется третий октет, я начинаю путаться."),
        _utterance("segment-181", "teacher", "Найди маску и сеть для 192.168.10.109/27. Я не подсказываю."),
        _utterance("segment-183", "student", "Маска 255.255.255.224. Блок по 32: диапазон 96–127."),
        _utterance("segment-185", "teacher", "Продолжай."),
        _utterance("segment-187", "student", "Сеть .96, broadcast .127, устройствам доступны 30 адресов."),
        _utterance("segment-247", "student", "Меня смущает, что я продолжаю смотреть только на последнее число IP."),
        _utterance("segment-265", "student", "Когда маска меняется в третьем октете, адрес сети без подсказки пока не всегда нахожу."),
        _utterance("segment-281", "student", "Я раньше думал, что /27 означает 27 устройств, а теперь понял, что это длина маски."),
    ]
    existing_model_event = {
        "kind": "independent_demonstration",
        "summary": "Модель сочла всю задачу полностью решённой.",
        "source_refs": ["segment-181", "segment-183", "segment-185", "segment-187"],
        "validation_status": "unverified",
    }

    assert _is_only_verbal_understanding_claim(segments[-1])
    assert _recover_independent_attempt_candidates(segments, [existing_model_event]) == []
    assert existing_model_event["source_refs"] == ["segment-181", "segment-183", "segment-187"]
    assert existing_model_event["event_origin"] == "explicit_independent_prompt.v1"
    assert "требуют отдельной проверки" in existing_model_event["summary"]
    assert existing_model_event["summary_variants"] == ["Модель сочла всю задачу полностью решённой."]

    reports = _recover_literal_difficulty_self_reports(segments, [existing_model_event])
    report_refs = {event["source_refs"][0] for event in reports}
    assert {"segment-175", "segment-247", "segment-265"}.issubset(report_refs)
    assert "segment-281" not in report_refs
    assert all(event["skill_id"] is None for event in reports)


def test_validator_accepts_cited_no_hint_cue_but_rejects_intervening_instruction():
    def validate(segments):
        raw = {
            "summary": "Краткий синтетический разбор.", "topics": [], "content_segments": [],
            "observed_difficulties": [], "limitations": [],
            "learner_events": [{"kind": "independent_demonstration", "skill": "Попытка",
                                "summary": "Ученик самостоятельно отвечал.", "skill_id": "",
                                "skill_facet_id": "", "source_refs": [segment["segment_id"] for segment in segments
                                                                          if segment["speaker_role"] in {"teacher", "student"}]}],
        }
        request = {"segments": segments, "allowed_skill_ids": [], "knowledge_context": {"items": []},
                   "lesson_id": "synthetic", "lesson_version": 1, "source_ref": "synthetic-text"}
        return _validate_ai_result(raw, request)["learner_events"][0]

    valid = validate([
        _utterance("cue", "teacher", "Найди решение самостоятельно, я не подсказываю."),
        _utterance("answer", "student", "Для 109 диапазон 96–127."),
    ])
    assert valid["validation_status"] == "supported_by_transcript"
    assert "самостоятельно" in valid["validation_reason"]

    invalid = validate([
        _utterance("cue", "teacher", "Найди решение самостоятельно, я не подсказываю."),
        _utterance("hint", "teacher", "Сначала возьми блок по 32."),
        _utterance("answer", "student", "Диапазон 96–127."),
    ])
    assert invalid["validation_status"] == "unverified"
    assert "содержательную подсказку" in invalid["validation_reason"]


def test_unverified_model_independence_is_not_counted_as_an_independent_event():
    events = [{"kind": "independent_demonstration", "validation_status": "unverified",
               "summary": "Модель считает ответ самостоятельным.", "source_refs": ["guided-answer"]}]

    _downgrade_unverified_independent_events(events)

    assert events[0]["kind"] == "other"
    assert events[0]["model_claimed_kind"] == "independent_demonstration"
    assert events[0]["summary_variants"] == ["Модель считает ответ самостоятельным."]
    assert "не подтверждено" in events[0]["summary"]


def test_event_contains_hint_context_evidence_limits_and_pending_review():
    segments = [
        _utterance("cue", "teacher", "Найди адрес сети без подсказки."),
        _utterance("answer", "student", "Сеть 192.168.10.96, broadcast 192.168.10.127."),
    ]
    events = [{"kind": "independent_demonstration", "source_refs": ["cue", "answer"],
               "validation_status": "supported_by_transcript", "event_origin": "explicit_independent_prompt.v1"}]

    _enrich_learner_event_evidence(events, segments)

    event = events[0]
    assert event["action"]["type"] == "independent_demonstration"
    assert event["context"]["hint_status"] == "explicit_no_hint"
    assert event["context"]["explicit_independent_prompt_refs"] == ["cue"]
    assert event["review_status"] == "pending"
    assert "правильность" in " ".join(event["what_is_not_established"])
    assert "попытка" in event["what_dialogue_supports"][0]

    tool_segments = [
        _utterance("tool-prompt", "teacher", "Можно использовать калькулятор, но объясни границы сети самостоятельно."),
        _utterance("claim", "student", "Теперь понимаю, что /27 задаёт длину маски."),
    ]
    tool_events = [{"kind": "verbal_understanding_claim", "source_refs": ["tool-prompt", "claim"]}]
    _enrich_learner_event_evidence(tool_events, tool_segments)
    assert tool_events[0]["context"]["hint_status"] == "explicit_independent_prompt"
    assert tool_events[0]["context"]["permitted_tools"] == ["калькулятор"]
    assert tool_events[0]["review_status"] == "pending"


def test_next_lesson_draft_rechecks_candidate_and_stays_within_session_duration():
    candidate = {
        "kind": "independent_demonstration",
        "skill_id": None,
        "source_refs": ["teacher-task", "student-answer"],
        "summary": "Предметная правильность автоматически не проверена.",
        "semantic_support_status": "manual_review_required",
    }
    request = {
        "planned_session_minutes": 60,
        "segments": [
            _utterance("earlier-teacher", "teacher", "После шага с подсказкой попробуй сам."),
            _utterance("earlier-answer", "student", "Получаю 14 после третьего шага."),
            _utterance("teacher-task", "teacher", "Я не подсказываю."),
            _utterance("student-answer", "student", "Решение."),
            _utterance("difficulty", "student", "Путаюсь в следующем шаге."),
        ],
        "knowledge_context": {"items": []},
        "baseline_plan": None,
        "assigned_practice": None,
    }
    merged = {
        "topics": [],
        "learner_events": [
            {**candidate, "event_origin": "model_event.v1", "source_refs": ["earlier-teacher", "earlier-answer"]},
            {**candidate, "event_origin": "explicit_independent_prompt.v1"},
        ],
        "observed_difficulties": [{
            "skill_id": "synthetic.skill.v1",
            "skill_facet_id": "synthetic.facet",
            "description": "Нужно повторно проверить следующий шаг.",
            "source_refs": ["difficulty"],
            "resolution_source_refs": [],
            "progress_evidence": [],
            "resolution_status": "unresolved_or_unknown",
        }],
    }

    plan = _build_prioritized_lesson_plan(request, merged)

    assert plan["total_minutes"] == 60
    assert plan["stages"][0]["source_refs"] == ["teacher-task", "student-answer"]
    assert "Короткая перепроверка самостоятельной попытки" in plan["stages"][0]["title"]
    assert "synthetic.skill.v1" not in " ".join(stage["title"] for stage in plan["stages"])
    assert "не считается подтверждённым освоением" in plan["reason"]


def test_merge_reconciles_only_unqualified_absence_and_keeps_scoped_limits():
    segments = [
        _utterance("independent-task", "teacher", "Найди сеть и broadcast для 192.168.10.109/27. Я не подсказываю."),
        _utterance("independent-step-1", "student", "Блок 32: 109 попадает в диапазон 96–127."),
        _utterance("neutral-continuation", "teacher", "Продолжай."),
        _utterance("independent-step-2", "student", "Сеть .96, broadcast .127, для устройств 30 адресов."),
        _utterance("difficulty", "student", "С /20 я пока путаюсь, в каком октете считать блок."),
    ]
    chunks = [{
        "chunk_id": "part-1",
        "result": {
            "summary": "Синтетический разбор IPv4.",
            "topics": [],
            "content_segments": [],
            "observed_difficulties": [{
                "skill_id": "ege.inf.ip-prefix-mask.v1",
                "skill_facet_id": "ipv4.prefix.third_octet_boundary",
                "description": "Ученик сообщает о затруднении при выборе октета для /20.",
                "source_refs": ["difficulty"],
            }],
            "unsubstantiated_observations": [],
            "learner_events": [{
                "kind": "independent_demonstration",
                "skill": "IPv4 /27",
                "skill_id": "ege.inf.ip-prefix-mask.v1",
                "skill_facet_id": "ipv4.prefix.last_octet_boundary",
                "summary": "Самостоятельная попытка; предметная проверка нужна.",
                "source_refs": ["independent-task", "independent-step-1", "independent-step-2"],
                "event_origin": "explicit_independent_prompt.v1",
                "validation_status": "supported_by_transcript",
            }],
            "limitations": [
                "Нет явных примеров самостоятельного применения навыка.",
                "Нет самостоятельной работы после подсказки преподавателя.",
                "Нет подтверждения самостоятельного решения с границей в третьем октете.",
                "Перенос навыка на новые примеры остаётся недостаточно подтверждённым.",
            ],
        },
    }]
    request = {
        "lesson_id": "synthetic-ipv4",
        "lesson_version": 1,
        "source_ref": "synthetic-test",
        "planned_session_minutes": 60,
        "segments": segments,
        "knowledge_context": {"items": []},
    }

    merged = _merge_lesson_chunk_results(request, chunks)
    plan = _build_prioritized_lesson_plan(request, merged)
    limitations = merged["limitations"]
    independent = [event for event in merged["learner_events"]
                   if event["kind"] == "independent_demonstration"]
    self_report_refs = {ref for event in merged["learner_events"]
                        if event["kind"] == "difficulty_self_report" for ref in event["source_refs"]}

    assert len(independent) == 1
    assert independent[0]["source_refs"] == ["independent-task", "independent-step-1", "independent-step-2"]
    assert "difficulty" in self_report_refs
    assert not any("Нет явных примеров самостоятельного применения" in item for item in limitations)
    assert any("после подсказки преподавателя" in item for item in limitations)
    assert any("с границей в третьем октете" in item for item in limitations)
    assert any("Перенос навыка на новые примеры" in item for item in limitations)
    assert any("правильность и полнота ответа требуют ручной" in item for item in limitations)
    assert plan["stages"][0]["source_refs"] == independent[0]["source_refs"]
    assert plan["total_minutes"] == 60
