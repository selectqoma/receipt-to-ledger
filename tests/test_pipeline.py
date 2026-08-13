import pytest

from receipt_to_ledger.contracts import CategorizerResult, ExtractorResult
from receipt_to_ledger.models import (
    AccountingDocument,
    CategoryPrediction,
    DocumentType,
    MoneyTotals,
    ProviderUsage,
    SourceExtraction,
)
from receipt_to_ledger.pipeline import InvoiceProcessor


class FakeExtractor:
    async def extract(self, payload: bytes, content_type: str) -> ExtractorResult:
        return ExtractorResult(
            document=AccountingDocument(
                document_type=DocumentType.RECEIPT,
                currency="EUR",
                amounts=MoneyTotals(subtotal=10, tax=2.1, total=12.1),
            ),
            source=SourceExtraction(
                method="plain_text", content_type=content_type, pages=1, characters=20
            ),
            usage=(
                ProviderUsage(
                    provider="deepseek",
                    model="test",
                    operation="extract",
                    prompt_tokens=100,
                    completion_tokens=50,
                    estimated_cost_usd=0.001,
                ),
            ),
        )


class FakeCategorizer:
    async def predict(self, document: AccountingDocument) -> CategorizerResult:
        return CategorizerResult(
            prediction=CategoryPrediction(
                account_code="613500",
                label="Meals",
                confidence=0.97,
                source="test",
            ),
            usage=(
                ProviderUsage(
                    provider="deepseek",
                    model="test",
                    operation="categorize",
                    estimated_cost_usd=0.002,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_pipeline_aggregates_cost_and_auto_accepts() -> None:
    processor = InvoiceProcessor(FakeExtractor(), FakeCategorizer())
    result = await processor.process(b"whatever", "text/plain")
    assert result.category is not None
    assert result.review_required is False
    assert result.estimated_cost_usd == pytest.approx(0.003)
