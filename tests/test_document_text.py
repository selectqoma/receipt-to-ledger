from receipt_to_ledger.document_text import LocalDocumentTextExtractor


def test_plain_text_passes_through() -> None:
    result = LocalDocumentTextExtractor().extract(b"Invoice total EUR 12.34", "text/plain")
    assert result.text == "Invoice total EUR 12.34"
    assert result.source.method == "plain_text"
    assert result.source.ocr_pages == 0


def test_xml_passes_through_as_structured_text() -> None:
    payload = b"<Invoice><ID>INV-42</ID></Invoice>"
    result = LocalDocumentTextExtractor().extract(payload, "application/xml")
    assert "INV-42" in result.text
    assert result.source.method == "structured_text"
