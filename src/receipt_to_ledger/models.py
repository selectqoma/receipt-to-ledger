from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(StrEnum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    CREDIT_NOTE = "credit_note"
    EXPENSE_NOTE = "expense_note"
    UNKNOWN = "unknown"


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    vat_number: str | None = None
    address: str | None = None


class MoneyTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None


class TaxLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: float | None = None
    taxable: float | None = None
    tax: float | None = None


class DocumentLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    quantity: float | None = None
    unit_price: float | None = None
    total: float | None = None
    tax_rate: float | None = None


class LedgerAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_code: str
    label: str
    description: str | None = None
    examples: list[str] = Field(default_factory=list)


class CategoryPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_code: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    reason: str | None = None


class SourceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    content_type: str
    pages: int = Field(ge=1)
    ocr_pages: int = Field(default=0, ge=0)
    vision_pages: int = Field(default=0, ge=0)
    characters: int = Field(ge=0)


class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    operation: str
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    thinking_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)


class AccountingDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    supplier: Party | None = None
    customer: Party | None = None
    employee: Party | None = None
    document_number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    currency: str = Field(default="XXX", min_length=3, max_length=3)
    business_purpose: str | None = None
    project_code: str | None = None
    reimbursable: bool | None = None
    amounts: MoneyTotals
    tax_breakdown: list[TaxLine] = Field(default_factory=list)
    lines: list[DocumentLine] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    category_prediction: CategoryPrediction | None = None
