import pytest

from receipt_to_ledger.models import AccountingDocument, DocumentType, LedgerAccount, MoneyTotals
from receipt_to_ledger.providers.deepseek import DeepSeekCategorizer


class FakeClient:
    async def json_completion(self, **kwargs):
        return (
            {"account_code": "614000", "confidence": 0.91, "reason": "train ticket"},
            (),
        )


@pytest.mark.asyncio
async def test_categorizer_can_only_return_known_account() -> None:
    categorizer = DeepSeekCategorizer(
        FakeClient(),
        [LedgerAccount(account_code="614000", label="Travel", description="Transport")],
    )
    document = AccountingDocument(
        document_type=DocumentType.EXPENSE_NOTE,
        currency="EUR",
        amounts=MoneyTotals(total=18.4),
    )
    result = await categorizer.predict(document)
    assert result.prediction.account_code == "614000"
    assert result.prediction.label == "Travel"


@pytest.mark.asyncio
async def test_categorizer_rejects_hallucinated_account() -> None:
    class BadClient:
        async def json_completion(self, **kwargs):
            return ({"account_code": "999999", "confidence": 0.99}, ())

    categorizer = DeepSeekCategorizer(
        BadClient(),
        [LedgerAccount(account_code="614000", label="Travel")],
    )
    document = AccountingDocument(
        document_type=DocumentType.RECEIPT,
        currency="EUR",
        amounts=MoneyTotals(total=10),
    )
    with pytest.raises(ValueError, match="unknown account code"):
        await categorizer.predict(document)
