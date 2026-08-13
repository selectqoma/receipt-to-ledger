from __future__ import annotations

from dataclasses import dataclass

from .models import AccountingDocument, CategoryPrediction, ProviderUsage, SourceExtraction


@dataclass(frozen=True)
class ExtractorResult:
    document: AccountingDocument
    source: SourceExtraction
    usage: tuple[ProviderUsage, ...] = ()


@dataclass(frozen=True)
class CategorizerResult:
    prediction: CategoryPrediction
    usage: tuple[ProviderUsage, ...] = ()
