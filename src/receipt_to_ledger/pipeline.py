from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import CategorizerResult, ExtractorResult
from .models import AccountingDocument, CategoryPrediction, ProviderUsage, SourceExtraction
from .validation import ValidationResult, validate_financials


class Extractor(Protocol):
    async def extract(self, payload: bytes, content_type: str) -> ExtractorResult: ...


class Categorizer(Protocol):
    async def predict(self, document: AccountingDocument) -> CategorizerResult: ...


@dataclass(frozen=True)
class ProcessingResult:
    document: AccountingDocument
    source: SourceExtraction
    validation: ValidationResult
    category: CategoryPrediction | None
    review_required: bool
    provider_usage: tuple[ProviderUsage, ...]
    estimated_cost_usd: float


class InvoiceProcessor:
    def __init__(
        self,
        extractor: Extractor,
        categorizer: Categorizer | None,
        *,
        auto_book_threshold: float = 0.95,
        request_budget_usd: float = 0.15,
    ) -> None:
        self.extractor = extractor
        self.categorizer = categorizer
        self.auto_book_threshold = auto_book_threshold
        self.request_budget_usd = request_budget_usd

    async def process(self, payload: bytes, content_type: str) -> ProcessingResult:
        extraction = await self.extractor.extract(payload, content_type)
        document = extraction.document
        validation = validate_financials(document)
        usage = list(extraction.usage)
        category: CategoryPrediction | None = None

        extraction_cost = sum(item.estimated_cost_usd for item in usage)
        if self.categorizer is not None and extraction_cost <= self.request_budget_usd:
            categorization = await self.categorizer.predict(document)
            category = categorization.prediction
            document.category_prediction = category
            usage.extend(categorization.usage)

        estimated_cost_usd = sum(item.estimated_cost_usd for item in usage)
        review_required = (
            not validation.ok
            or category is None
            or category.confidence < self.auto_book_threshold
            or estimated_cost_usd > self.request_budget_usd
        )

        return ProcessingResult(
            document=document,
            source=extraction.source,
            validation=validation,
            category=category,
            review_required=review_required,
            provider_usage=tuple(usage),
            estimated_cost_usd=estimated_cost_usd,
        )
