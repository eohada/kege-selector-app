"""Mock-адаптер используется только автоматическими тестами через dependency injection."""
from __future__ import annotations

import json
import hashlib
import uuid

from app.ai_lab.provider import CompletionResult, ai_lab_limits
from app.ai_lab.schemas import RESPONSE_SCHEMA


class MockProvider:
    name = "mock"

    def __init__(self, content: str | list[str], model: str = "mock-homework-review"):
        self.responses = content if isinstance(content, list) else [content]
        self.content = content[0] if isinstance(content, list) else content
        self.model = model
        self.list_models_calls = 0
        self.complete_calls = 0
        self.last_payload = None

    def list_models(self) -> list[str]:
        self.list_models_calls += 1
        return [self.model]

    def complete(
        self,
        model: str,
        system_prompt: str,
        user_payload: dict,
        *,
        repair_issue: str | None = None,
    ) -> CompletionResult:
        self.complete_calls += 1
        self.last_payload = user_payload
        sent_payload = (
            {**user_payload, "semantic_repair_issue": repair_issue}
            if repair_issue
            else user_payload
        )
        request_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(sent_payload, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": 0.1,
            "max_tokens": ai_lab_limits()["max_completion_tokens"],
            "response_format": {"type": "json_schema", "schema": RESPONSE_SCHEMA, "strict": True},
        }
        payload_id = str(uuid.uuid4())
        payload_hash = hashlib.sha256(
            json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        response_content = self.responses[min(self.complete_calls - 1, len(self.responses) - 1)]
        try:
            result = json.loads(response_content)
        except (TypeError, json.JSONDecodeError):
            return CompletionResult(
                content=response_content,
                model=model,
                input_tokens=17,
                output_tokens=23,
                prompt_tokens=17,
                precached_prompt_tokens=0,
                total_tokens=40,
                payload_id=payload_id,
                payload_sha256=payload_hash,
                request_payload=request_payload,
                generation_parameters={
                    "temperature": 0.1,
                    "max_tokens": ai_lab_limits()["max_completion_tokens"],
                    "top_p": None,
                    "top_p_note": "not set; provider default",
                    "response_format": "json_schema_strict",
                },
            )
        criteria = user_payload.get("scoring_criteria") or []
        deterministic = user_payload.get("verified_deterministic_check") or {}
        if deterministic.get("score_awarded") is not None:
            result["score_awarded"] = deterministic["score_awarded"]
            result["max_score"] = deterministic["max_score"]
        if not result.get("criterion_scores") and criteria:
            criterion_scores = []
            remaining = float(result.get("score_awarded") or 0)
            for criterion in criteria:
                maximum = criterion.get("max_score")
                if maximum is None:
                    continue
                awarded = min(float(maximum), max(0.0, remaining))
                remaining -= awarded
                criterion_scores.append(
                    {
                        "criterion": criterion["criterion"],
                        "score_awarded": awarded,
                        "max_score": maximum,
                        "rationale": "Mock: проверка синтетического критерия.",
                    }
                )
            result["criterion_scores"] = criterion_scores
        result.setdefault("insufficient_data_reason", "")
        return CompletionResult(
            content=json.dumps(result, ensure_ascii=False),
            model=model,
            input_tokens=17,
            output_tokens=23,
            prompt_tokens=17,
            precached_prompt_tokens=0,
            total_tokens=40,
            payload_id=payload_id,
            payload_sha256=payload_hash,
            request_payload=request_payload,
            generation_parameters={
                "temperature": 0.1,
                "max_tokens": ai_lab_limits()["max_completion_tokens"],
                "top_p": None,
                "top_p_note": "not set; provider default",
                "response_format": "json_schema_strict",
            },
        )
