from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .document_text import LocalDocumentTextExtractor
from .models import LedgerAccount
from .pipeline import InvoiceProcessor, ProcessingResult
from .providers.deepseek import DeepSeekCategorizer, DeepSeekClient, DeepSeekDocumentExtractor


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    return {
        ".xml": "application/xml",
        ".txt": "text/plain",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


def _load_chart(path: Path) -> list[LedgerAccount]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("accounts", [])
    return [LedgerAccount.model_validate(item) for item in payload]


def _result_json(result: ProcessingResult) -> dict[str, Any]:
    return {
        "document": result.document.model_dump(mode="json"),
        "source": result.source.model_dump(mode="json"),
        "validation": asdict(result.validation),
        "category": result.category.model_dump(mode="json") if result.category else None,
        "review_required": result.review_required,
        "provider_usage": [item.model_dump(mode="json") for item in result.provider_usage],
        "estimated_cost_usd": round(result.estimated_cost_usd, 8),
    }


async def _process(args: argparse.Namespace) -> int:
    path = Path(args.file)
    chart = _load_chart(Path(args.chart)) if args.chart else []
    text_extractor = LocalDocumentTextExtractor(
        tesseract_lang=args.ocr_lang,
        min_pdf_page_chars=args.min_pdf_page_chars,
    )
    client = DeepSeekClient(api_key=args.api_key, model=args.model)
    extractor = DeepSeekDocumentExtractor(client, text_extractor)
    categorizer = DeepSeekCategorizer(client, chart) if chart else None
    processor = InvoiceProcessor(
        extractor,
        categorizer,
        auto_book_threshold=args.auto_book_threshold,
        request_budget_usd=args.budget_usd,
    )

    result = await processor.process(path.read_bytes(), _content_type(path))
    rendered = json.dumps(_result_json(result), indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def _extract_text(args: argparse.Namespace) -> int:
    path = Path(args.file)
    extractor = LocalDocumentTextExtractor(
        tesseract_lang=args.ocr_lang,
        min_pdf_page_chars=args.min_pdf_page_chars,
    )
    result = extractor.extract(path.read_bytes(), _content_type(path))
    print(json.dumps(result.source.model_dump(mode="json"), indent=2))
    print("\n--- extracted text ---\n")
    print(result.text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipt-to-ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser("extract-text", help="run local PDF/text/OCR extraction")
    text_parser.add_argument("file")
    text_parser.add_argument("--ocr-lang", default=os.getenv("TESSERACT_LANG", "eng"))
    text_parser.add_argument("--min-pdf-page-chars", type=int, default=24)

    process = subparsers.add_parser("process", help="extract, validate, and categorize a document")
    process.add_argument("file")
    process.add_argument("--chart", help="JSON chart of accounts; omit to skip categorization")
    process.add_argument("--output", "-o")
    process.add_argument("--api-key", default=os.getenv("DEEPSEEK_API_KEY"))
    process.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    process.add_argument("--ocr-lang", default=os.getenv("TESSERACT_LANG", "eng"))
    process.add_argument("--min-pdf-page-chars", type=int, default=24)
    process.add_argument("--auto-book-threshold", type=float, default=0.95)
    process.add_argument("--budget-usd", type=float, default=0.15)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "extract-text":
        return _extract_text(args)
    if args.command == "process":
        return asyncio.run(_process(args))
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
