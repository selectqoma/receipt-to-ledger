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
from .providers.gemini import GeminiClient, GeminiDocumentExtractor


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


def _is_visual_document(content_type: str) -> bool:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized == "application/pdf" or normalized.startswith("image/")


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
    payload = path.read_bytes()
    content_type = _content_type(path)
    chart = _load_chart(Path(args.chart)) if args.chart else []
    visual_document = _is_visual_document(content_type)

    use_gemini = args.document_provider == "gemini" or (
        args.document_provider == "auto" and visual_document
    )

    deepseek_client = None
    if not use_gemini or chart:
        deepseek_client = DeepSeekClient(
            api_key=args.deepseek_api_key,
            model=args.deepseek_model,
        )

    if use_gemini:
        gemini_client = GeminiClient(
            api_key=args.gemini_api_key,
            model=args.gemini_model,
            thinking_level=args.gemini_thinking_level,
            media_resolution=args.gemini_media_resolution,
        )
        extractor = GeminiDocumentExtractor(gemini_client)
    else:
        text_extractor = LocalDocumentTextExtractor(
            tesseract_lang=args.ocr_lang,
            min_pdf_page_chars=args.min_pdf_page_chars,
        )
        assert deepseek_client is not None
        extractor = DeepSeekDocumentExtractor(deepseek_client, text_extractor)

    categorizer = None
    if chart:
        assert deepseek_client is not None
        categorizer = DeepSeekCategorizer(deepseek_client, chart)

    processor = InvoiceProcessor(
        extractor,
        categorizer,
        auto_book_threshold=args.auto_book_threshold,
        request_budget_usd=args.budget_usd,
    )

    result = await processor.process(payload, content_type)
    rendered = json.dumps(_result_json(result), indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


async def _evaluate(args: argparse.Namespace) -> int:
    from .cord_eval import load_cord_cases
    from .evaluation import load_manifest_cases, run_evaluation

    if args.dataset == "cord":
        cases = load_cord_cases(split=args.split, limit=args.limit)
        dataset_name = f"cord-v2:{args.split}"
    else:
        if not args.manifest:
            raise ValueError("rtl eval manifest requires a manifest path")
        manifest_path = Path(args.manifest)
        cases = load_manifest_cases(manifest_path, limit=args.limit)
        dataset_name = f"manifest:{manifest_path.name}"

    gemini_client = GeminiClient(
        api_key=args.gemini_api_key,
        model=args.gemini_model,
        thinking_level=args.gemini_thinking_level,
        media_resolution=args.gemini_media_resolution,
    )

    categorizer = None
    if args.chart:
        chart = _load_chart(Path(args.chart))
        deepseek_client = DeepSeekClient(
            api_key=args.deepseek_api_key,
            model=args.deepseek_model,
        )
        categorizer = DeepSeekCategorizer(deepseek_client, chart)

    report, case_results = await run_evaluation(
        cases,
        gemini_client,
        dataset=dataset_name,
        model=args.gemini_model,
        categorizer=categorizer,
        include_predictions=args.include_predictions,
        max_total_cost_usd=args.max_cost_usd,
    )
    payload = {
        "summary": report,
        "cases": [asdict(result) for result in case_results],
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
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


def _add_gemini_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gemini-api-key", default=os.getenv("GEMINI_API_KEY"))
    parser.add_argument(
        "--gemini-model", default=os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    )
    parser.add_argument(
        "--gemini-thinking-level",
        choices=("minimal", "low", "medium", "high"),
        default=os.getenv("GEMINI_THINKING_LEVEL", "low"),
    )
    parser.add_argument(
        "--gemini-media-resolution",
        choices=("auto", "low", "medium", "high"),
        default=os.getenv("GEMINI_MEDIA_RESOLUTION", "auto"),
        help="auto uses medium for PDFs and high for images",
    )


def _add_deepseek_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--deepseek-api-key",
        "--api-key",
        dest="deepseek_api_key",
        default=os.getenv("DEEPSEEK_API_KEY"),
    )
    parser.add_argument(
        "--deepseek-model",
        "--model",
        dest="deepseek_model",
        default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipt-to-ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser(
        "extract-text", help="run the local PDF/text/Tesseract debug extractor"
    )
    text_parser.add_argument("file")
    text_parser.add_argument("--ocr-lang", default=os.getenv("TESSERACT_LANG", "eng"))
    text_parser.add_argument("--min-pdf-page-chars", type=int, default=24)

    process = subparsers.add_parser("process", help="extract, validate, and categorize a document")
    process.add_argument("file")
    process.add_argument("--chart", help="JSON chart of accounts; omit to skip categorization")
    process.add_argument("--output", "-o")
    process.add_argument(
        "--document-provider",
        choices=("auto", "gemini", "deepseek-text"),
        default="auto",
        help=(
            "auto: Gemini for PDFs/images and text extraction + DeepSeek for text/XML; "
            "deepseek-text keeps the old Tesseract/text path"
        ),
    )
    _add_gemini_args(process)
    _add_deepseek_args(process)
    process.add_argument("--ocr-lang", default=os.getenv("TESSERACT_LANG", "eng"))
    process.add_argument("--min-pdf-page-chars", type=int, default=24)
    process.add_argument("--auto-book-threshold", type=float, default=0.95)
    process.add_argument("--budget-usd", type=float, default=0.15)

    evaluate = subparsers.add_parser(
        "eval", help="benchmark extraction against public or private ground truth"
    )
    evaluate.add_argument("dataset", choices=("cord", "manifest"))
    evaluate.add_argument(
        "manifest",
        nargs="?",
        help="JSON/JSONL manifest path when dataset=manifest",
    )
    evaluate.add_argument("--split", default="validation", choices=("train", "validation", "test"))
    evaluate.add_argument("--limit", type=int, default=25)
    evaluate.add_argument("--max-cost-usd", type=float, default=0.50)
    evaluate.add_argument("--chart", help="optional chart for labeled category evaluation")
    evaluate.add_argument("--include-predictions", action="store_true")
    evaluate.add_argument("--output", "-o", default="evaluation.json")
    _add_gemini_args(evaluate)
    _add_deepseek_args(evaluate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "extract-text":
        return _extract_text(args)
    if args.command == "process":
        return asyncio.run(_process(args))
    if args.command == "eval":
        return asyncio.run(_evaluate(args))
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
