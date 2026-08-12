from receipt_to_ledger.models import AccountingDocument, DocumentType, MoneyTotals
from receipt_to_ledger.validation import validate_financials


def test_valid_totals() -> None:
    doc = AccountingDocument(
        document_type=DocumentType.RECEIPT,
        currency="EUR",
        amounts=MoneyTotals(subtotal=100.0, tax=21.0, total=121.0),
    )

    result = validate_financials(doc)

    assert result.ok
    assert result.failures == ()


def test_invalid_totals_are_flagged() -> None:
    doc = AccountingDocument(
        document_type=DocumentType.INVOICE,
        currency="EUR",
        amounts=MoneyTotals(subtotal=100.0, tax=21.0, total=130.0),
    )

    result = validate_financials(doc)

    assert not result.ok
    assert "subtotal_plus_tax_does_not_equal_total" in result.failures
