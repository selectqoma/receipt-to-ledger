from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import AccountingDocument, CategoryPrediction
from .validation import ValidationResult, validate_financials


class Extractor(Protocol):
    async def extract(self, payload: bytes, content_type: str) -> AccountingDocument: ...


class Categorizer(Protocol):
    async def predict(self, document: AccountingDocument) -> CategoryPrediction: ...


@dataclass(frozen=True)
class ProcessingResult:
    document: AccountingDocument
    validation: ValidationResult
    category: CategoryPrediction | None
    review_required: bool
    estimated_cost_usd: float


class InvoiceProcessor:
    """Thin orchestration shell.

    Production code should split routing, extraction, vendor resolution,
    categorization, retries, and cost accounting into separate adapters/services.
    """

    def __init__(
        self,
        extractor: Extractor,
        categorizer: Categorizer,
        *,
        auto_book_threshold: float = 0.95,
        request_budget_usd: float = 0.15,
    ) -> None:
        self.extractor = extractor
        self.categorizer = categorizer
        self.auto_book_threshold = auto_book_threshold
        self.request_budget_usd = request_budget_usd

    async def process(self, payload: bytes, content_type: str) -> ProcessingResult:
        document = await self.extractor.extract(payload, content_type)
        validation = validate_financials(document)

        category: CategoryPrediction | None = None
        if validation.ok:
            category = await self.categorizer.predict(document)

        review_required = (
            not validation.ok
            or category is None
            or category.confidence < self.auto_book_threshold
        )

        # Placeholder until adapters report measured/provider-specific cost.
        estimated_cost_usd = 0.0
        if estimated_cost_usd > self.request_budget_usd:
            review_required = True

        return ProcessingResult(
            document=document,
            validation=validation,
            category=category,
            review_required=review_required,
            estimated_cost_usd=estimated_cost_usd,
        )
