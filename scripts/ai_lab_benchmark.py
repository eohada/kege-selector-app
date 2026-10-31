"""Validate frozen AI Lab data and manage separate expert benchmark reviews."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.ai_lab.benchmark import (
    append_expert_review,
    attach_expert_reviews,
    load_expert_reviews,
    load_frozen_manifest,
    load_run_records,
    summarize_expert_reviews,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/fixtures/ai_lab_sprint6_manifest_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="Verify protocol, fixture, and preserved prior hashes.")
    validate.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    annotate = subparsers.add_parser("annotate", help="Append an independent review without editing run output.")
    annotate.add_argument("--reviews", required=True)
    annotate.add_argument("--run-id", required=True)
    annotate.add_argument("--case-id", required=True)
    annotate.add_argument("--reviewer", required=True)
    annotate.add_argument("--ratings-json", required=True, help="JSON object with explicit true/false ratings.")
    annotate.add_argument("--comments", default="")
    score = subparsers.add_parser("score", help="Count only separately reviewed boolean criteria.")
    score.add_argument("--results", required=True)
    score.add_argument("--reviews", required=True)
    score.add_argument("--output")
    args = parser.parse_args()

    if args.command == "validate":
        manifest, dataset = load_frozen_manifest(args.manifest)
        splits = {split: sum(case["split"] == split for case in dataset["cases"])
                  for split in ("development", "regression", "holdout")}
        print(json.dumps({"ok": True, "dataset_id": dataset["dataset_id"], "dataset_version": dataset["dataset_version"],
                          "fixture_sha256": dataset["fixture_sha256"], "protocol_sha256": manifest["protocol_sha256"],
                          "case_count": len(dataset["cases"]), "splits": splits,
                          "live_generation_budget": manifest["maximum_logical_generations"]}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "annotate":
        try:
            ratings = json.loads(args.ratings_json)
        except json.JSONDecodeError as exc:
            parser.error(f"--ratings-json должен быть JSON-объектом: {exc}")
        if not isinstance(ratings, dict) or any(not isinstance(value, bool) for value in ratings.values()):
            parser.error("Каждая экспертная оценка должна быть true или false.")
        append_expert_review(args.reviews, run_id=args.run_id, case_id=args.case_id,
                             reviewer=args.reviewer, ratings=ratings, comments=args.comments)
        print(json.dumps({"saved": True, "run_id": args.run_id, "case_id": args.case_id}, ensure_ascii=False))
        return 0

    rows = load_run_records(args.results)
    reviews = load_expert_reviews(args.reviews)
    reviewed_rows = attach_expert_reviews(rows, reviews)
    summary = summarize_expert_reviews(reviewed_rows)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
