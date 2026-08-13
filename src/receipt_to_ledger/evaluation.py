from __future__ import annotations

import json
import math
import mimetypes
import re
import statistics
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from .models import AccountingDocument, CategoryPrediction, ProviderUsage


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    payload: bytes
    content_type: str
    ground_truth: dict[str, Any]
    expected_account_code: str | None = None


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    field_scores: dict[str, tuple[int, int]]
    document_exact: bool
    category_correct: bool | None
    cost_usd: float
    latency_seconds: float
    prediction: dict[str, Any] | None = None
    error: str | None = None


class DocumentExtractionClient(Protocol):
    async def extract_document(
        self, payload: bytes, content_type: str
    ) -> tuple[AccountingDocument, tuple[ProviderUsage, ...]]: ...


class Categorizer(Protocol):
    async def predict(self, document: AccountingDocument) -> Any: ...


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = " ".join(text.split()).strip().casefold()
    return text or None


def normalize_identifier(value: Any) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    # IDs commonly differ only in spaces around separators after OCR.
    return re.sub(r"\s+", "", text)


def normalize_money(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return int(round(numeric * 100))


def normalize_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, 6)


def _get_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _has_path(payload: dict[str, Any], path: str) -> bool:
    value: Any = payload
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return isinstance(value, dict) and parts[-1] in value


def _counter_f1(predicted: list[Any], expected: list[Any]) -> tuple[int, int]:
    """Return matched item count and denominator as max(predicted, expected).

    This behaves like exact multiset accuracy for equal-size lists and penalizes
    both missing and extra line items without requiring row ordering.
    """
    pred = Counter(item for item in predicted if item is not None)
    exp = Counter(item for item in expected if item is not None)
    matched = sum(min(pred[key], exp[key]) for key in pred.keys() | exp.keys())
    denominator = max(sum(pred.values()), sum(exp.values()))
    return matched, denominator


_FIELD_RULES: dict[str, tuple[str, Any]] = {
    "document_type": ("document_type", normalize_text),
    "supplier.name": ("supplier.name", normalize_text),
    "supplier.vat_number": ("supplier.vat_number", normalize_identifier),
    "document_number": ("document_number", normalize_identifier),
    "issue_date": ("issue_date", normalize_text),
    "due_date": ("due_date", normalize_text),
    "currency": ("currency", normalize_text),
    "amounts.subtotal": ("amounts.subtotal", normalize_money),
    "amounts.tax": ("amounts.tax", normalize_money),
    "amounts.total": ("amounts.total", normalize_money),
}


def score_document(
    prediction: AccountingDocument,
    ground_truth: dict[str, Any],
) -> tuple[dict[str, tuple[int, int]], bool]:
    pred = prediction.model_dump(mode="json")
    scores: dict[str, tuple[int, int]] = {}
    all_correct = True
    evaluated_any = False

    for metric_name, (path, normalizer) in _FIELD_RULES.items():
        if not _has_path(ground_truth, path):
            continue
        expected = normalizer(_get_path(ground_truth, path))
        actual = normalizer(_get_path(pred, path))
        correct = int(actual == expected)
        scores[metric_name] = (correct, 1)
        evaluated_any = True
        all_correct = all_correct and bool(correct)

    if "lines" in ground_truth:
        evaluated_any = True
        expected_lines = ground_truth.get("lines") or []
        predicted_lines = pred.get("lines") or []

        expected_desc = [normalize_text(line.get("description")) for line in expected_lines]
        predicted_desc = [normalize_text(line.get("description")) for line in predicted_lines]
        scores["lines.description"] = _counter_f1(predicted_desc, expected_desc)

        if any("total" in line for line in expected_lines):
            expected_total = [
                normalize_money(line.get("total"))
                for line in expected_lines
                if "total" in line
            ]
            predicted_total = [normalize_money(line.get("total")) for line in predicted_lines]
            scores["lines.total"] = _counter_f1(predicted_total, expected_total)

        expected_rows = [
            (
                normalize_text(line.get("description")),
                normalize_money(line.get("total")) if "total" in line else None,
            )
            for line in expected_lines
        ]
        predicted_rows = [
            (normalize_text(line.get("description")), normalize_money(line.get("total")))
            for line in predicted_lines
        ]
        scores["lines.row_exact"] = _counter_f1(predicted_rows, expected_rows)

        for correct, total in scores.values():
            if total and correct != total:
                all_correct = False

    return scores, all_correct if evaluated_any else False


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def build_report(
    results: list[CaseResult],
    *,
    dataset: str,
    model: str,
) -> dict[str, Any]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    document_exact = 0
    category_correct = 0
    category_evaluated = 0
    costs: list[float] = []
    latencies: list[float] = []
    errors: list[dict[str, str]] = []

    for result in results:
        if result.error:
            errors.append({"case_id": result.case_id, "error": result.error})
            continue
        document_exact += int(result.document_exact)
        costs.append(result.cost_usd)
        latencies.append(result.latency_seconds)
        if result.category_correct is not None:
            category_evaluated += 1
            category_correct += int(result.category_correct)
        for name, (correct, evaluated) in result.field_scores.items():
            totals[name][0] += correct
            totals[name][1] += evaluated

    successful = len(results) - len(errors)
    field_metrics = {
        name: {
            "correct": correct,
            "evaluated": evaluated,
            "accuracy": round(correct / evaluated, 6) if evaluated else None,
        }
        for name, (correct, evaluated) in sorted(totals.items())
    }
    return {
        "dataset": dataset,
        "model": model,
        "cases": len(results),
        "successful": successful,
        "errors": len(errors),
        "document_exact": {
            "correct": document_exact,
            "evaluated": successful,
            "accuracy": round(document_exact / successful, 6) if successful else None,
        },
        "category": {
            "correct": category_correct,
            "evaluated": category_evaluated,
            "accuracy": (
                round(category_correct / category_evaluated, 6)
                if category_evaluated
                else None
            ),
        },
        "fields": field_metrics,
        "cost_usd": {
            "total": round(sum(costs), 8),
            "mean": round(statistics.fmean(costs), 8) if costs else 0.0,
            "p50": round(_percentile(costs, 0.50), 8),
            "p95": round(_percentile(costs, 0.95), 8),
        },
        "latency_seconds": {
            "mean": round(statistics.fmean(latencies), 4) if latencies else 0.0,
            "p50": round(_percentile(latencies, 0.50), 4),
            "p95": round(_percentile(latencies, 0.95), 4),
        },
        "failures": errors,
    }


async def run_evaluation(
    cases: Iterable[EvaluationCase],
    extractor: DocumentExtractionClient,
    *,
    dataset: str,
    model: str,
    categorizer: Categorizer | None = None,
    include_predictions: bool = False,
    max_total_cost_usd: float | None = None,
) -> tuple[dict[str, Any], list[CaseResult]]:
    results: list[CaseResult] = []
    spent_usd = 0.0
    stopped_reason: str | None = None
    for case in cases:
        if max_total_cost_usd is not None and spent_usd >= max_total_cost_usd:
            stopped_reason = "max_total_cost_usd_reached"
            break
        started = time.perf_counter()
        try:
            document, usage = await extractor.extract_document(case.payload, case.content_type)
            category_correct: bool | None = None
            category_usage: tuple[ProviderUsage, ...] = ()
            if categorizer is not None and case.expected_account_code is not None:
                categorized = await categorizer.predict(document)
                prediction: CategoryPrediction = categorized.prediction
                category_usage = tuple(categorized.usage)
                category_correct = prediction.account_code == case.expected_account_code

            field_scores, document_exact = score_document(document, case.ground_truth)
            all_usage = tuple(usage) + category_usage
            cost = sum(item.estimated_cost_usd for item in all_usage)
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    field_scores=field_scores,
                    document_exact=document_exact,
                    category_correct=category_correct,
                    cost_usd=cost,
                    latency_seconds=time.perf_counter() - started,
                    prediction=document.model_dump(mode="json") if include_predictions else None,
                )
            )
            spent_usd += cost
        except Exception as exc:  # benchmark should finish and report bad cases
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    field_scores={},
                    document_exact=False,
                    category_correct=None,
                    cost_usd=0.0,
                    latency_seconds=time.perf_counter() - started,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    report = build_report(results, dataset=dataset, model=model)
    report["budget_usd"] = max_total_cost_usd
    report["stopped_reason"] = stopped_reason
    return report, results


def load_manifest_cases(path: Path, *, limit: int | None = None) -> list[EvaluationCase]:
    base = path.parent
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        parsed = json.loads(text)
        records = parsed if isinstance(parsed, list) else parsed.get("cases", [])

    cases: list[EvaluationCase] = []
    for index, record in enumerate(records):
        if limit is not None and len(cases) >= limit:
            break
        file_path = Path(record["file"])
        if not file_path.is_absolute():
            file_path = base / file_path
        ground_truth = record.get("ground_truth")
        if ground_truth is None and record.get("ground_truth_file"):
            gt_path = Path(record["ground_truth_file"])
            if not gt_path.is_absolute():
                gt_path = base / gt_path
            ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))
        if not isinstance(ground_truth, dict):
            raise ValueError(f"manifest case {index} has no ground_truth object")

        content_type = record.get("content_type") or mimetypes.guess_type(file_path.name)[0]
        if not content_type:
            content_type = "application/octet-stream"
        expected_account_code = record.get("expected_account_code")
        if expected_account_code is None:
            expected_account_code = _get_path(ground_truth, "category_prediction.account_code")

        cases.append(
            EvaluationCase(
                case_id=str(record.get("id") or file_path.name),
                payload=file_path.read_bytes(),
                content_type=content_type,
                ground_truth=ground_truth,
                expected_account_code=(
                    str(expected_account_code) if expected_account_code is not None else None
                ),
            )
        )
    return cases
