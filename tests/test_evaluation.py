import json
from pathlib import Path

import pytest

from receipt_to_ledger.evaluation import (
    CaseResult,
    EvaluationCase,
    build_report,
    load_manifest_cases,
    run_evaluation,
    score_document,
)
from receipt_to_ledger.models import (
    AccountingDocument,
    DocumentLine,
    DocumentType,
    MoneyTotals,
    Party,
    ProviderUsage,
)


def test_score_document_fields_and_lines() -> None:
    prediction = AccountingDocument(
        document_type=DocumentType.INVOICE,
        supplier=Party(name="Acme BV", vat_number="BE 0123 456 789"),
        document_number="INV-001",
        issue_date="2026-08-01",
        currency="EUR",
        amounts=MoneyTotals(subtotal=100.0, tax=21.0, total=121.0),
        lines=[
            DocumentLine(description="Cloud hosting", total=80.0),
            DocumentLine(description="Support", total=20.0),
        ],
    )
    truth = {
        "document_type": "invoice",
        "supplier": {"name": "ACME BV", "vat_number": "BE0123456789"},
        "document_number": "INV-001",
        "issue_date": "2026-08-01",
        "currency": "eur",
        "amounts": {"subtotal": 100, "tax": 21, "total": 121},
        "lines": [
            {"description": "Support", "total": 20},
            {"description": "Cloud hosting", "total": 80},
        ],
    }
    scores, exact = score_document(prediction, truth)
    assert exact
    assert scores["amounts.total"] == (1, 1)
    assert scores["lines.row_exact"] == (2, 2)


def test_document_exact_fails_on_one_cent_error() -> None:
    prediction = AccountingDocument(
        document_type=DocumentType.RECEIPT,
        amounts=MoneyTotals(total=10.01),
    )
    scores, exact = score_document(prediction, {"amounts": {"total": 10.00}})
    assert scores["amounts.total"] == (0, 1)
    assert not exact


def test_report_aggregates_costs() -> None:
    results = [
        CaseResult("a", {"amounts.total": (1, 1)}, True, None, 0.01, 1.0),
        CaseResult("b", {"amounts.total": (0, 1)}, False, None, 0.03, 3.0),
    ]
    report = build_report(results, dataset="x", model="m")
    assert report["fields"]["amounts.total"]["accuracy"] == 0.5
    assert report["cost_usd"]["mean"] == 0.02
    assert report["document_exact"]["accuracy"] == 0.5


def test_manifest_loads_relative_files(tmp_path: Path) -> None:
    doc = tmp_path / "invoice.pdf"
    doc.write_bytes(b"fake")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "case-1",
                "file": "invoice.pdf",
                "ground_truth": {"amounts": {"total": 12.34}},
                "expected_account_code": "6100",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cases = load_manifest_cases(manifest)
    assert len(cases) == 1
    assert cases[0].case_id == "case-1"
    assert cases[0].expected_account_code == "6100"


class _FakeExtractor:
    def __init__(self) -> None:
        self.calls = 0

    async def extract_document(self, payload: bytes, content_type: str):
        self.calls += 1
        return (
            AccountingDocument(
                document_type=DocumentType.RECEIPT,
                amounts=MoneyTotals(total=1.0),
            ),
            (
                ProviderUsage(
                    provider="fake",
                    model="fake",
                    operation="extract",
                    estimated_cost_usd=0.06,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_evaluation_stops_after_budget() -> None:
    extractor = _FakeExtractor()
    cases = [
        EvaluationCase(str(i), b"x", "image/jpeg", {"amounts": {"total": 1.0}})
        for i in range(10)
    ]
    report, results = await run_evaluation(
        cases,
        extractor,
        dataset="x",
        model="m",
        max_total_cost_usd=0.10,
    )
    assert len(results) == 2
    assert report["stopped_reason"] == "max_total_cost_usd_reached"
