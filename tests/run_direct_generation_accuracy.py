from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from src.config.settings import get_settings, normalize_reasoning_effort
from src.generation.llm_client import create_llm_client, parse_json_response

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = REPO_ROOT / "data" / "benchmark_QA.csv"
DEFAULT_OUTPUT_CSV_PATH = REPO_ROOT / "docs" / "evaluation" / "generation" / "direct_answers.csv"
RAG_BASELINE_ACCURACY = 0.825


def _build_answer_prompt(question: str) -> str:
    return f"""
Answer the question directly, without using retrieval context.

Rules:
- Return only the answer text.
- Keep the answer concise.
- If the answer cannot be determined from general model knowledge, say:
  Unable to answer with confidence.

Question:
{question}
""".strip()


def _build_judge_prompt(
    question: str,
    expected_answer: str,
    expected_supporting_materials: str,
    expected_explanation: str,
    candidate_answer: str,
) -> str:
    return f"""
Judge whether the candidate answer is semantically equivalent to the expected answer.

Use the supporting materials and explanation only to interpret the expected answer. Do not require identical wording.
Numeric answers may be correct when they are equivalent after unit conversion, rounding, or obvious range formatting.
True/False answers may be correct when the candidate clearly expresses the same truth value.
If the expected answer says the documents cannot answer the question, mark the candidate correct only when it also refuses or says the answer is not known with confidence.

Return only JSON with this schema:
{{"correct": true, "reason": "short explanation"}}

Question:
{question}

Expected answer:
{expected_answer}

Expected supporting materials:
{expected_supporting_materials}

Expected explanation:
{expected_explanation}

Candidate answer:
{candidate_answer}
""".strip()


def _parse_correctness(raw_text: str) -> tuple[bool, str]:
    payload = parse_json_response(raw_text)
    if payload is not None:
        raw_correct = payload.get("correct", False)
        if isinstance(raw_correct, bool):
            return raw_correct, str(payload.get("reason", "")).strip()
        if isinstance(raw_correct, str):
            return raw_correct.strip().lower() in {"true", "yes", "correct", "1"}, str(
                payload.get("reason", "")
            ).strip()

    lowered = raw_text.strip().lower()
    if lowered.startswith("true") or '"correct": true' in lowered:
        return True, raw_text.strip()
    return False, raw_text.strip()


def _write_results_csv(rows: list[dict[str, Any]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "question_id",
        "question",
        "expected_answer",
        "expected_supporting_materials",
        "expected_explanation",
        "llm_backend",
        "answer_model",
        "judge_model",
        "answer",
        "judge_correct",
        "judge_reason",
        "generation_latency_ms",
        "judge_latency_ms",
        "error_type",
        "error_message",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_direct_generation_accuracy(
    *,
    dataset: Path,
    output_csv: Path,
    llm_backend: str,
    answer_model: str | None,
    judge_model: str | None,
    api_key: str | None,
    base_url: str | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    answer_client = create_llm_client(
        llm_backend,
        model=answer_model,
        api_key=api_key,
        base_url=base_url,
        reasoning_effort=reasoning_effort if llm_backend == "api" else None,
    )
    judge_client = create_llm_client(
        llm_backend,
        model=judge_model or answer_model,
        api_key=api_key,
        base_url=base_url,
        reasoning_effort=reasoning_effort if llm_backend == "api" else None,
    )

    rows: list[dict[str, Any]] = []
    with dataset.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            question_id = str(raw.get("question_id", raw.get("id", ""))).strip()
            question = str(raw.get("question", "")).strip()
            if not question:
                continue

            row: dict[str, Any] = {
                "question_id": question_id,
                "question": question,
                "expected_answer": str(raw.get("answer", "")).strip(),
                "expected_supporting_materials": str(raw.get("supporting_materials", "")).strip(),
                "expected_explanation": str(raw.get("explanation", "")).strip(),
                "llm_backend": llm_backend,
                "answer_model": answer_model or "",
                "judge_model": judge_model or answer_model or "",
                "answer": "",
                "judge_correct": "",
                "judge_reason": "",
                "generation_latency_ms": "",
                "judge_latency_ms": "",
                "error_type": "",
                "error_message": "",
            }

            try:
                generation_start = time.perf_counter()
                answer = answer_client.generate(
                    _build_answer_prompt(question),
                    system_prompt="Answer directly from your model knowledge. Do not mention retrieval context.",
                ).strip()
                row["generation_latency_ms"] = round((time.perf_counter() - generation_start) * 1000, 3)
                row["answer"] = answer

                judge_start = time.perf_counter()
                judge_text = judge_client.generate(
                    _build_judge_prompt(
                        question=question,
                        expected_answer=row["expected_answer"],
                        expected_supporting_materials=row["expected_supporting_materials"],
                        expected_explanation=row["expected_explanation"],
                        candidate_answer=answer,
                    ),
                    system_prompt="You are a strict semantic-equivalence evaluator. Return only JSON.",
                )
                row["judge_latency_ms"] = round((time.perf_counter() - judge_start) * 1000, 3)
                correct, reason = _parse_correctness(judge_text)
                row["judge_correct"] = correct
                row["judge_reason"] = reason
            except Exception as exc:
                row["error_type"] = exc.__class__.__name__
                row["error_message"] = str(exc)

            rows.append(row)
            print(f"[{question_id}] done")

    _write_results_csv(rows, output_csv)

    judged_rows = [row for row in rows if row["judge_correct"] != "" and not row["error_type"]]
    correct_count = sum(1 for row in judged_rows if row["judge_correct"] is True)
    accuracy = correct_count / len(judged_rows) if judged_rows else 0.0
    return {
        "output_csv": str(output_csv),
        "num_questions": len(rows),
        "num_judged": len(judged_rows),
        "correct": correct_count,
        "direct_generation_accuracy": accuracy,
        "rag_baseline_accuracy": RAG_BASELINE_ACCURACY,
        "accuracy_delta": accuracy - RAG_BASELINE_ACCURACY,
        "error_count": sum(1 for row in rows if row["error_type"]),
    }


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Evaluate direct generation accuracy without retrieval and compare it with the 82.5% RAG baseline."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV_PATH)
    parser.add_argument("--llm-backend", choices=["api", "ollama"], default=settings.llm_backend)
    parser.add_argument("--answer-model", default=None)
    parser.add_argument("--judge-model", default=None, help="Defaults to --answer-model")
    parser.add_argument("--api-key", default=settings.api_key)
    parser.add_argument("--base-url", default=settings.api_base_url)
    parser.add_argument("--reasoning-effort", default="none")
    args = parser.parse_args()

    default_model = settings.ollama_model if args.llm_backend == "ollama" else settings.api_model
    answer_model = args.answer_model or default_model

    summary = run_direct_generation_accuracy(
        dataset=args.dataset,
        output_csv=args.output_csv,
        llm_backend=args.llm_backend,
        answer_model=answer_model,
        judge_model=args.judge_model,
        api_key=args.api_key,
        base_url=args.base_url,
        reasoning_effort=normalize_reasoning_effort(args.reasoning_effort),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
