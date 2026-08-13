from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Protocol

from pydantic import ValidationError
from pypdf import PdfReader

from ..contracts import ExtractorResult
from ..models import AccountingDocument, ProviderUsage, SourceExtraction


DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    # USD per 1M input / output tokens. Output pricing also applies to thinking tokens.
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}


class GeminiExtractionClient(Protocol):
    async def extract_document(
        self, payload: bytes, content_type: str
    ) -> tuple[AccountingDocument, tuple[ProviderUsage, ...]]: ...


class GeminiClient:
    """Thin Google Gen AI SDK wrapper for multimodal accounting extraction."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        thinking_level: str | None = None,
        media_resolution: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for PDF/image extraction")

        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.thinking_level = thinking_level or os.getenv("GEMINI_THINKING_LEVEL", "low")
        if self.thinking_level not in {"minimal", "low", "medium", "high"}:
            raise ValueError("GEMINI_THINKING_LEVEL must be minimal, low, medium, or high")
        self.media_resolution = media_resolution or os.getenv("GEMINI_MEDIA_RESOLUTION", "auto")
        if self.media_resolution not in {"auto", "low", "medium", "high"}:
            raise ValueError("GEMINI_MEDIA_RESOLUTION must be auto, low, medium, or high")

        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on optional runtime package
            raise RuntimeError(
                "Gemini support requires google-genai; install the project dependencies"
            ) from exc

        self.client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"},
        )
        default_input, default_output = DEFAULT_PRICES.get(self.model, (1.50, 7.50))
        self.input_usd_per_m = float(
            os.getenv("GEMINI_INPUT_USD_PER_M", str(default_input))
        )
        self.output_usd_per_m = float(
            os.getenv("GEMINI_OUTPUT_USD_PER_M", str(default_output))
        )

    async def extract_document(
        self, payload: bytes, content_type: str
    ) -> tuple[AccountingDocument, tuple[ProviderUsage, ...]]:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized != "application/pdf" and not normalized.startswith("image/"):
            raise ValueError(f"Gemini vision extractor does not accept {content_type}")

        try:
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depends on optional runtime package
            raise RuntimeError(
                "Gemini support requires google-genai; install the project dependencies"
            ) from exc

        resolution = self._resolution_for(normalized)
        media = types.Part.from_bytes(data=payload, mime_type=normalized)
        media_resolution = getattr(
            types.MediaResolution, f"MEDIA_RESOLUTION_{resolution.upper()}"
        )
        prompt = (
            "Extract this accounting document into the requested schema. The document may be an "
            "invoice, receipt, credit note, or employee expense note. Read the actual visual "
            "document, including layout, tables, handwritten annotations, and rotated text. "
            "Never invent missing values. Use null for unknown optional values and XXX only when "
            "the currency genuinely cannot be determined. Dates must be ISO YYYY-MM-DD. Amounts "
            "must be numbers, preserving the sign shown by the document. For field_confidence, "
            "include only important extracted fields such as supplier.name, supplier.vat_number, "
            "document_number, issue_date, amounts.subtotal, amounts.tax, and amounts.total. "
            "Confidence is 0..1 and should reflect visual certainty, not plausibility. "
            "Set category_prediction to null because ledger categorization happens separately."
        )

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=[media, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=AccountingDocument.model_json_schema(),
                thinking_config=types.ThinkingConfig(thinking_level=self.thinking_level),
                media_resolution=media_resolution,
            ),
        )

        parsed = getattr(response, "parsed", None)
        try:
            if isinstance(parsed, AccountingDocument):
                document = parsed
            elif parsed is not None:
                document = AccountingDocument.model_validate(parsed)
            else:
                text = getattr(response, "text", None)
                if not text:
                    raise ValueError("Gemini returned no structured document")
                document = AccountingDocument.model_validate_json(text)
        except (ValidationError, ValueError) as exc:
            raise RuntimeError(f"Gemini returned invalid accounting JSON: {exc}") from exc

        document.category_prediction = None
        return document, (self._usage(response),)

    def _resolution_for(self, content_type: str) -> str:
        if self.media_resolution != "auto":
            return self.media_resolution
        # Google's current guidance: medium for PDFs, high for image analysis.
        return "medium" if content_type == "application/pdf" else "high"

    def _usage(self, response: Any) -> ProviderUsage:
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        thinking_tokens = int(getattr(usage, "thoughts_token_count", 0) or 0)
        billable_output_tokens = completion_tokens + thinking_tokens
        estimated_cost = (
            prompt_tokens * self.input_usd_per_m / 1_000_000
            + billable_output_tokens * self.output_usd_per_m / 1_000_000
        )
        return ProviderUsage(
            provider="gemini",
            model=self.model,
            operation="multimodal_document_extraction",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            thinking_tokens=thinking_tokens,
            estimated_cost_usd=estimated_cost,
        )


class GeminiDocumentExtractor:
    def __init__(self, client: GeminiExtractionClient) -> None:
        self.client = client

    async def extract(self, payload: bytes, content_type: str) -> ExtractorResult:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized != "application/pdf" and not normalized.startswith("image/"):
            raise ValueError(f"GeminiDocumentExtractor only accepts PDF/image input, got {content_type}")

        document, usage = await self.client.extract_document(payload, normalized)
        pages = _page_count(payload, normalized)
        return ExtractorResult(
            document=document,
            source=SourceExtraction(
                method="gemini_multimodal",
                content_type=normalized,
                pages=pages,
                ocr_pages=0,
                vision_pages=pages,
                characters=0,
            ),
            usage=usage,
        )


def _page_count(payload: bytes, content_type: str) -> int:
    if content_type == "application/pdf":
        try:
            return max(1, len(PdfReader(BytesIO(payload)).pages))
        except Exception as exc:
            raise ValueError("invalid or unreadable PDF") from exc
    return 1
