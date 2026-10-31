"""Isolated file-backed AI Lab preview for Sprint 5; synthetic provider by default."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from app import create_app, db
from app.ai_lab import course as course_module
from app.ai_lab import lesson_intelligence as lesson_module
from app.models import User


class PreviewProvider:
    """Synthetic-only stand-in used for browser persistence and UX checks."""

    def complete_structured(self, model, system_prompt, user_payload, schema):
        if "course" in user_payload:
            course = user_payload["course"]
            material = next(iter(course.get("materials", [])), None)
            fragment = next(iter(material.get("source_fragments", [])), None) if material else None
            proposals = []
            if material and fragment:
                proposals.append({
                    "proposal_id": "sprint5-preview-material-note",
                    "material_id": material["material_id"],
                    "observation": "Проверьте, достаточно ли конкретен приведённый пример.",
                    "proposed_text": "Добавьте ещё один самостоятельный проверочный пример.",
                    "source_refs": [fragment["source_ref"]],
                })
            output = {"summary": "Локальный синтетический результат предпросмотра.",
                      "material_proposals": proposals}
        else:
            segments = user_payload.get("segments", [])
            source_ids = [item["segment_id"] for item in segments]
            difficulty = next((item for item in segments
                               if item.get("speaker", "").casefold().startswith(("ученик", "student", "learner"))
                               and any(phrase in item.get("text", "").casefold()
                                       for phrase in ("не понимаю", "не знаю", "не получается"))), None)
            output = {
                "summary": "Локальный синтетический конспект предпросмотра.",
                "topics": ([{"topic_id": "python.boundary", "title": "Границы и условия",
                             "source_refs": source_ids[:1]}] if source_ids else []),
                "content_segments": ([{"segment_id": "preview-summary", "summary": "Реплика для демонстрации цитирования.",
                                       "source_refs": [source_ids[0]]}] if source_ids else []),
                "observed_difficulties": ([{"skill_id": "python.boundary_cases",
                                             "description": "Синтетическая реплика прямо сообщает о затруднении.",
                                             "source_refs": [difficulty["segment_id"]]}] if difficulty else []),
                "limitations": ["Тестовый ответ не является ответом GigaChat."],
            }
        self.calls = getattr(self, "calls", 0) + 1
        return SimpleNamespace(content=json.dumps(output, ensure_ascii=False), model="LocalSprint5Preview",
                               input_tokens=40, output_tokens=24,
                               generation_parameters={"temperature": 0, "max_tokens": 3200},
                               payload_id=f"preview-{self.calls}", payload_sha256=f"{self.calls:064x}")


def main() -> None:
    os.environ.setdefault("AI_LAB_ENABLED", "1")
    os.environ.setdefault("SECRET_KEY", "sprint5-isolated-preview-session-key")
    use_live_provider = os.environ.get("AI_LAB_SPRINT5_LIVE_GIGACHAT") == "1"
    if not use_live_provider:
        course_module.GigaChatProvider = PreviewProvider
        lesson_module.GigaChatProvider = PreviewProvider

    configured_path = os.environ.get("AI_LAB_SPRINT5_PREVIEW_DB")
    db_path = Path(configured_path) if configured_path else Path(tempfile.gettempdir()) / "boostudy-ai-lab-sprint5-preview.sqlite"
    db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path.as_posix()}",
        "SECRET_KEY": "sprint5-isolated-preview-only",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })
    with app.app_context():
        db.create_all()
        admin = User.query.filter_by(username="sprint5-preview-admin").first()
        if admin is None:
            admin = User(username="sprint5-preview-admin", email="sprint5-preview@example.test", role="admin")
            admin.set_password("preview-only")
            db.session.add(admin)
            db.session.commit()
    provider_label = "configured GigaChat" if use_live_provider else "LocalSprint5Preview"
    print(f"AI Lab Sprint 5 isolated preview: SQLite file at {db_path}; provider={provider_label}; http://localhost:5058", flush=True)
    print("Preview admin login: sprint5-preview-admin / preview-only", flush=True)
    app.run(host="127.0.0.1", port=5058, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
