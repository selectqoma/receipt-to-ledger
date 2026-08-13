from io import BytesIO

import pytest
from pypdf import PdfWriter

from receipt_to_ledger.models import AccountingDocument, DocumentType, MoneyTotals, ProviderUsage
from receipt_to_ledger.providers.gemini import GeminiDocumentExtractor


class FakeGeminiClient:
    async def extract_document(self, payload: bytes, content_type: str):
        assert payload
        return (
            AccountingDocument(
                document_type=DocumentType.INVOICE,
                currency="EUR",
                amounts=MoneyTotals(subtotal=100, tax=21, total=121),
            ),
            (
                ProviderUsage(
                    provider="gemini",
                    model="test",
                    operation="multimodal_document_extraction",
                    prompt_tokens=300,
                    completion_tokens=100,
                    thinking_tokens=20,
                    estimated_cost_usd=0.001,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_image_goes_directly_to_multimodal_extractor() -> None:
    extractor = GeminiDocumentExtractor(FakeGeminiClient())

    result = await extractor.extract(b"fake-image", "image/jpeg")

    assert result.document.amounts.total == 121
    assert result.source.method == "gemini_multimodal"
    assert result.source.pages == 1
    assert result.source.vision_pages == 1
    assert result.source.ocr_pages == 0
    assert result.usage[0].thinking_tokens == 20


@pytest.mark.asyncio
async def test_pdf_page_count_is_preserved() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)

    result = await GeminiDocumentExtractor(FakeGeminiClient()).extract(
        stream.getvalue(), "application/pdf"
    )

    assert result.source.pages == 2
    assert result.source.vision_pages == 2


def test_gemini_cost_includes_thinking_tokens() -> None:
    from types import SimpleNamespace

    from receipt_to_ledger.providers.gemini import GeminiClient

    client = GeminiClient.__new__(GeminiClient)
    client.model = "gemini-3.6-flash"
    client.input_usd_per_m = 1.50
    client.output_usd_per_m = 7.50
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=300,
            candidates_token_count=100,
            thoughts_token_count=20,
        )
    )

    usage = client._usage(response)

    assert usage.thinking_tokens == 20
    assert usage.estimated_cost_usd == pytest.approx(0.00135)


def test_auto_media_resolution_uses_pdf_medium_and_image_high() -> None:
    from receipt_to_ledger.providers.gemini import GeminiClient

    client = GeminiClient.__new__(GeminiClient)
    client.media_resolution = "auto"

    assert client._resolution_for("application/pdf") == "medium"
    assert client._resolution_for("image/jpeg") == "high"
