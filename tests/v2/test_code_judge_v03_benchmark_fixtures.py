import hashlib
import json
from pathlib import Path


_FIXTURES = Path(__file__).parents[1] / "fixtures"
_CONTROL_SHA256 = "28b1dc0a576cf873f8991dec9edaddb514ee85e43c22949e76c61d26ef6b212d"
_DEVELOPMENT_SHA256 = "9846b448aaae336558b9c9eb62bc568dfe08ad85252decd103df9afba9778df5"


def _read_frozen(name, expected_hash):
    content = (_FIXTURES / name).read_bytes()
    assert hashlib.sha256(content).hexdigest() == expected_hash
    return json.loads(content)


def test_v03_holdout_is_frozen_separate_from_development_set():
    control = _read_frozen("ai_lab_code_judge_v03_holdout.json", _CONTROL_SHA256)
    development = _read_frozen("ai_lab_code_judge_v03_dev.json", _DEVELOPMENT_SHA256)
    cases = control["cases"]
    assert control["name"] == "digit-sum-control-holdout"
    assert len(cases) == 20
    assert len({item["id"] for item in cases}) == 20
    assert not ({item["id"] for item in cases} & {item["id"] for item in development["cases"]})
    assert [item["expected_score"] for item in cases[:10]] == [3] * 10
    assert any(item["expected_score"] is None for item in cases)
    assert any(item.get("suite") == "digit-sum-alternative" for item in cases)


def test_benchmark_counts_unmapped_criterion_conflict_as_manual_review():
    from scripts.run_local_code_judge_v03_benchmark import _aggregate

    def experiment(conflict):
        return {
            "metrics": {
                "score_correct": False,
                "criterion_comparisons": [],
                "issue_tag_checks": [],
                "recommendation_tag_checks": [],
                "unexpected_mistake_claim": False,
            },
            "quality": {"code_judge_conflict": conflict},
            "authoritative_result": {"score_awarded": None, "grading_status": "manual_review"},
            "attempt_count": 1,
            "duration_ms": 10,
            "usage": {},
        }

    report = {
        "cases": [{
            "case": {"expected_score": None},
            "code_judge": {"rubric": {"confirmed_score": 2, "unconfirmed_max_score": 0}},
            "without_code_judge": experiment(False),
            "with_code_judge": experiment(True),
        }]
    }

    metrics = _aggregate(report)

    assert metrics["code_judge_score_correct"] == 1
    assert metrics["model_claims"]["with_code_judge"]["code_judge_conflicts"] == 1
    assert metrics["model_claims"]["with_code_judge"]["manual_reviews"] == 1
