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

    if amounts.subtotal is not None and amounts.tax is not None:
        expected = amounts.subtotal + amounts.tax
        if abs(expected - amounts.total) > tolerance:
            failures.append("subtotal_plus_tax_does_not_equal_total")

    if document.due_date and document.issue_date and document.due_date < document.issue_date:
        failures.append("due_date_before_issue_date")

    if document.lines and amounts.subtotal is not None:
        line_sum = sum(line.total for line in document.lines)
        # Line totals vary by source: some include tax. Only enforce this check
        # when line totals look compatible with the extracted subtotal.
        if abs(line_sum - amounts.subtotal) > tolerance and abs(line_sum - amounts.total) > tolerance:
            failures.append("line_sum_matches_neither_subtotal_nor_total")

    return ValidationResult(ok=not failures, failures=tuple(failures))
