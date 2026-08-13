from __future__ import annotations

from dataclasses import dataclass, field

from .models import AccountingDocument


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    failures: tuple[str, ...] = field(default_factory=tuple)


def validate_financials(
    document: AccountingDocument,
    *,
    tolerance: float = 0.02,
) -> ValidationResult:
    failures: list[str] = []
    amounts = document.amounts

    if amounts.total is None:
        failures.append("missing_total")

    if amounts.subtotal is not None and amounts.tax is not None and amounts.total is not None:
        expected = amounts.subtotal + amounts.tax
        if abs(expected - amounts.total) > tolerance:
            failures.append("subtotal_plus_tax_does_not_equal_total")

    if document.due_date and document.issue_date and document.due_date < document.issue_date:
        failures.append("due_date_before_issue_date")

    line_totals = [line.total for line in document.lines if line.total is not None]
    if line_totals and len(line_totals) == len(document.lines):
        line_sum = sum(line_totals)
        comparable = [value for value in (amounts.subtotal, amounts.total) if value is not None]
        if comparable and all(abs(line_sum - value) > tolerance for value in comparable):
            failures.append("line_sum_matches_neither_subtotal_nor_total")

    if document.document_type.value in {"invoice", "credit_note"} and not document.supplier:
        failures.append("missing_supplier_for_invoice_like_document")

    return ValidationResult(ok=not failures, failures=tuple(failures))
