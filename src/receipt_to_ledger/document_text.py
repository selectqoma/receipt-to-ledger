from __future__ import annotations

from dataclasses import dataclass

from .models import SourceExtraction


class DocumentTextError(RuntimeError):
    pass


@dataclass(frozen=True)
class TextExtractionResult:
    text: str
    source: SourceExtraction


class LocalDocumentTextExtractor:
    """Decode already-textual documents before involving an LLM."""

    _TEXT_TYPES = {
        "application/xml",
        "text/xml",
        "application/ubl+xml",
        "text/plain",
        "application/json",
    }

    def extract(self, payload: bytes, content_type: str) -> TextExtractionResult:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized not in self._TEXT_TYPES:
            raise DocumentTextError(
                f"local text extraction only supports XML/plain text; {content_type} should use Gemini"
            )

        text = self._decode_text(payload)
        return TextExtractionResult(
            text=text,
            source=SourceExtraction(
                method="structured_text" if "xml" in normalized else "plain_text",
                content_type=normalized,
                pages=1,
                ocr_pages=0,
                vision_pages=0,
                characters=len(text),
            ),
        )

    @staticmethod
    def _decode_text(payload: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return payload.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        raise DocumentTextError("could not decode text document")
