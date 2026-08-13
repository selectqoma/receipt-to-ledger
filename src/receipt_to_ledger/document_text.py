from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image
from pypdf import PdfReader

from .models import SourceExtraction


class DocumentTextError(RuntimeError):
    pass


@dataclass(frozen=True)
class TextExtractionResult:
    text: str
    source: SourceExtraction


class LocalDocumentTextExtractor:
    """Extract text cheaply before involving an LLM."""

    def __init__(
        self,
        *,
        tesseract_lang: str = "eng",
        min_pdf_page_chars: int = 24,
        pdf_render_scale: float = 2.0,
    ) -> None:
        self.tesseract_lang = tesseract_lang
        self.min_pdf_page_chars = min_pdf_page_chars
        self.pdf_render_scale = pdf_render_scale

    def extract(self, payload: bytes, content_type: str) -> TextExtractionResult:
        normalized = content_type.split(";", 1)[0].strip().lower()

        if normalized == "application/pdf":
            return self._extract_pdf(payload, normalized)
        if normalized.startswith("image/"):
            return self._extract_image(payload, normalized)
        if normalized in {
            "application/xml",
            "text/xml",
            "application/ubl+xml",
            "text/plain",
            "application/json",
        }:
            text = self._decode_text(payload)
            return TextExtractionResult(
                text=text,
                source=SourceExtraction(
                    method="structured_text" if "xml" in normalized else "plain_text",
                    content_type=normalized,
                    pages=1,
                    ocr_pages=0,
                    characters=len(text),
                ),
            )

        raise DocumentTextError(f"unsupported content type: {content_type}")

    @staticmethod
    def _decode_text(payload: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return payload.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        raise DocumentTextError("could not decode text document")

    def _extract_image(self, payload: bytes, content_type: str) -> TextExtractionResult:
        try:
            import pytesseract

            with Image.open(BytesIO(payload)) as image:
                text = pytesseract.image_to_string(image, lang=self.tesseract_lang).strip()
        except Exception as exc:
            raise DocumentTextError(
                "image OCR failed; install the Tesseract binary and the requested language packs"
            ) from exc

        return TextExtractionResult(
            text=text,
            source=SourceExtraction(
                method="tesseract_ocr",
                content_type=content_type,
                pages=1,
                ocr_pages=1,
                characters=len(text),
            ),
        )

    def _extract_pdf(self, payload: bytes, content_type: str) -> TextExtractionResult:
        try:
            reader = PdfReader(BytesIO(payload))
        except Exception as exc:
            raise DocumentTextError("invalid or unreadable PDF") from exc

        page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
        ocr_page_indexes = [
            index for index, text in enumerate(page_texts) if len(text) < self.min_pdf_page_chars
        ]

        if ocr_page_indexes:
            ocr_text = self._ocr_pdf_pages(payload, ocr_page_indexes)
            for index, text in ocr_text.items():
                if len(text) > len(page_texts[index]):
                    page_texts[index] = text

        text = "\n\n".join(
            f"--- page {index + 1} ---\n{page_text}"
            for index, page_text in enumerate(page_texts)
        ).strip()
        method = "pdf_text" if not ocr_page_indexes else "pdf_text+tesseract_ocr"

        return TextExtractionResult(
            text=text,
            source=SourceExtraction(
                method=method,
                content_type=content_type,
                pages=max(1, len(page_texts)),
                ocr_pages=len(ocr_page_indexes),
                characters=len(text),
            ),
        )

    def _ocr_pdf_pages(self, payload: bytes, page_indexes: list[int]) -> dict[int, str]:
        try:
            import pypdfium2 as pdfium
            import pytesseract

            pdf = pdfium.PdfDocument(payload)
            output: dict[int, str] = {}
            for page_index in page_indexes:
                page = pdf[page_index]
                bitmap = page.render(scale=self.pdf_render_scale)
                image = bitmap.to_pil()
                output[page_index] = pytesseract.image_to_string(
                    image, lang=self.tesseract_lang
                ).strip()
                image.close()
                page.close()
            pdf.close()
            return output
        except Exception as exc:
            raise DocumentTextError(
                "scanned-PDF OCR failed; install the Tesseract binary and language packs"
            ) from exc
