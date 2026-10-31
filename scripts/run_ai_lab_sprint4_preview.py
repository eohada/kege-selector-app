"""In-memory browser preview for Sprint 4; real GigaChat is opt-in by environment flag."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

from app import create_app, db
from app.ai_lab import course as course_module
from app.ai_lab import lesson_intelligence as lesson_module
from app.models import User


class PreviewProvider:
    """Deterministic local responses used only by this isolated preview process."""

    def complete_structured(self, model, system_prompt, user_payload, schema):
        if "course" in user_payload:
            course = user_payload["course"]
            material = next(iter(course.get("materials", [])), None)
            proposals = []
            if material:
                proposals.append({
                    "proposal_id": "preview-material-note",
                    "material_id": material["material_id"],
                    "observation": "Проверьте, достаточно ли конкретен приведённый пример.",
                    "proposed_text": material.get("content", "") + " Добавьте самостоятельный проверочный пример.",
                    "source_refs": [material["material_id"]],
                })
            output = {"summary": "Предпросмотр: модель замещена локальным тестовым провайдером.",
                      "material_proposals": proposals}
        else:
            segments = user_payload.get("segments", [])
            source_ids = [item["segment_id"] for item in segments]
            combined = " ".join(item.get("text", "").casefold() for item in segments)
            topics = []
            if any(word in combined for word in ("услов", "границ", "ветв")) and source_ids:
                topics.append({"topic_id": "python.conditions", "title": "Условия и границы", "source_refs": source_ids[:2]})
            if any(word in combined for word in ("цикл", "строк")) and source_ids:
                topics.append({"topic_id": "python.iteration", "title": "Циклы и строки", "source_refs": source_ids[:2]})
            difficulty_ref = next((item["segment_id"] for item in segments
                                   if any(term in item.get("text", "").casefold() for term in ("не понимаю", "не знаю", "не получается"))), None)
            difficulties = ([{"skill_id": "python.boundary_cases",
                              "description": "Синтетическая реплика прямо сообщает о затруднении.",
                              "source_refs": [difficulty_ref]}] if difficulty_ref else [])
            output = {
                "summary": "Предпросмотр: краткий конспект сформирован локальным тестовым провайдером.",
                "topics": topics,
                "content_segments": ([{"segment_id": "preview-summary-1", "summary": "В тексте обсуждаются приведённые темы.",
                                       "source_refs": [source_ids[0]]}] if source_ids else []),
                "observed_difficulties": difficulties,
                "limitations": ["Тестовый ответ не является результатом GigaChat."],
            }
        return SimpleNamespace(content=json.dumps(output, ensure_ascii=False), model="LocalPreviewProvider",
                               input_tokens=40, output_tokens=24,
                               generation_parameters={"temperature": 0, "max_tokens": 3200},
                               payload_id="preview-payload", payload_sha256="0" * 64)


def main() -> None:
    os.environ.setdefault("AI_LAB_ENABLED", "1")
    use_live_provider = os.environ.get("AI_LAB_SPRINT4_LIVE_GIGACHAT") == "1"
    if not use_live_provider:
        course_module.GigaChatProvider = PreviewProvider
        lesson_module.GigaChatProvider = PreviewProvider
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "sprint4-in-memory-preview-only",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })
    with app.app_context():
        db.create_all()
        admin = User.query.filter_by(username="sprint4-preview-admin").first()
        if admin is None:
            admin = User(username="sprint4-preview-admin", email="sprint4-preview@example.test", role="admin")
            admin.set_password("preview-only")
            db.session.add(admin)
            db.session.commit()
        user_id = admin.id
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    cookie = client.get_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))
    print(f"PREVIEW_SESSION_COOKIE={cookie.value if cookie else ''}", flush=True)
    provider_label = "configured GigaChat" if use_live_provider else "LocalPreviewProvider"
    print(f"AI Lab Sprint 4 preview: SQLite :memory:, {provider_label}, 127.0.0.1:5058", flush=True)
    app.run(host="127.0.0.1", port=5058, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
