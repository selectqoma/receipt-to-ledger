from __future__ import annotations

import json
import os
from typing import Any

from pydantic import ValidationError

from ..contracts import CategorizerResult, ExtractorResult
from ..document_text import LocalDocumentTextExtractor
from ..models import AccountingDocument, CategoryPrediction, LedgerAccount, ProviderUsage


DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (0.435, 0.87),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
}


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = "https://api.deepseek.com",
        max_retries: int = 1,
    ) -> None:
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is required")

        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.max_retries = max_retries
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "DeepSeek support requires the openai package; install the project dependencies"
            ) from exc
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        default_input, default_output = DEFAULT_PRICES.get(self.model, (0.50, 1.50))
        self.input_usd_per_m = float(
            os.getenv("DEEPSEEK_INPUT_USD_PER_M", str(default_input))
        )
        self.output_usd_per_m = float(
            os.getenv("DEEPSEEK_OUTPUT_USD_PER_M", str(default_output))
        )

    async def json_completion(
        self,
        *,
        operation: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], tuple[ProviderUsage, ...]]:
        usages: list[ProviderUsage] = []
        current_user_prompt = user_prompt
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": current_user_prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
            )
            usages.append(self._usage(operation, response))
            content = response.choices[0].message.content or ""

            try:
                if not content.strip():
                    raise ValueError("DeepSeek returned empty JSON content")
                return json.loads(content), tuple(usages)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                current_user_prompt = (
                    user_prompt
                    + "\n\nYour previous answer was empty or invalid JSON. Return exactly one valid JSON "
                    "object and no markdown."
                )

        assert last_error is not None
        raise RuntimeError(f"DeepSeek JSON completion failed: {last_error}") from last_error

    def _usage(self, operation: str, response: Any) -> ProviderUsage:
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        estimated_cost = (
            prompt_tokens * self.input_usd_per_m / 1_000_000
            + completion_tokens * self.output_usd_per_m / 1_000_000
        )
        return ProviderUsage(
            provider="deepseek",
            model=self.model,
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost,
        )


class DeepSeekDocumentExtractor:
    def __init__(
        self,
        client: DeepSeekClient,
        text_extractor: LocalDocumentTextExtractor,
    ) -> None:
        self.client = client
        self.text_extractor = text_extractor

    async def extract(self, payload: bytes, content_type: str) -> ExtractorResult:
        extracted = self.text_extractor.extract(payload, content_type)
        if not extracted.text.strip():
            raise ValueError("no readable text was extracted from the document")

        schema = AccountingDocument.model_json_schema()
        system_prompt = (
            "You extract bookkeeping data from invoices, receipts, credit notes, and employee "
            "expense notes. Output JSON only. Never invent a value that is not present or "
            "strongly implied by the document. Use null for unknown optional values and XXX for "
            "unknown currency. Dates must be ISO YYYY-MM-DD. Amounts are numeric, never strings. "
            "document_type must be one of invoice, receipt, credit_note, expense_note, unknown. "
            "For field_confidence, include only important extracted fields and assign 0..1. "
            "Do not include category_prediction; categorization happens separately."
        )
        user_prompt = (
            "Return one JSON object matching this JSON schema:\n"
            f"{json.dumps(schema, separators=(',', ':'))}\n\n"
            "DOCUMENT TEXT:\n"
            f"{extracted.text}"
        )

        raw, usage = await self.client.json_completion(
            operation="document_extraction",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=5000,
        )
        raw["category_prediction"] = None

        try:
            document = AccountingDocument.model_validate(raw)
        except ValidationError as exc:
            repair_prompt = (
                user_prompt
                + "\n\nThe JSON you returned failed schema validation with these errors:\n"
                + exc.json()
                + "\nReturn a corrected JSON object only."
            )
            repaired, repair_usage = await self.client.json_completion(
                operation="document_extraction_repair",
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                max_tokens=5000,
            )
            repaired["category_prediction"] = None
            document = AccountingDocument.model_validate(repaired)
            usage = usage + repair_usage

        return ExtractorResult(document=document, source=extracted.source, usage=usage)


class DeepSeekCategorizer:
    def __init__(self, client: DeepSeekClient, accounts: list[LedgerAccount]) -> None:
        if not accounts:
            raise ValueError("at least one ledger account is required")
        self.client = client
        self.accounts = accounts
        self._accounts_by_code = {account.account_code: account for account in accounts}

    async def predict(self, document: AccountingDocument) -> CategorizerResult:
        account_payload = [account.model_dump(mode="json") for account in self.accounts]
        document_payload = document.model_dump(mode="json", exclude={"category_prediction"})
        system_prompt = (
            "You are an expense-account classifier. Choose exactly one account from the supplied "
            "chart of accounts. Output JSON only with account_code, confidence, and reason. "
            "confidence is your uncertainty estimate from 0 to 1, not a guarantee. Never output an "
            "account code that is not in the supplied chart. Prefer the most specific account whose "
            "description fits the supplier, line items, business purpose, and document type."
        )
        user_prompt = (
            "Return JSON in this shape: "
            '{"account_code":"...","confidence":0.0,"reason":"..."}.\n\n'
            f"CHART OF ACCOUNTS:\n{json.dumps(account_payload, ensure_ascii=False)}\n\n"
            f"DOCUMENT:\n{json.dumps(document_payload, ensure_ascii=False)}"
        )
        raw, usage = await self.client.json_completion(
            operation="expense_categorization",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=600,
        )

        account_code = str(raw.get("account_code", ""))
        account = self._accounts_by_code.get(account_code)
        if account is None:
            raise ValueError(f"DeepSeek selected unknown account code: {account_code!r}")

        prediction = CategoryPrediction(
            account_code=account.account_code,
            label=account.label,
            confidence=float(raw.get("confidence", 0.0)),
            source="deepseek",
            reason=str(raw.get("reason")) if raw.get("reason") is not None else None,
        )
        return CategorizerResult(prediction=prediction, usage=usage)
