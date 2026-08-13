# receipt-to-ledger

A cost-aware base workflow for accountants:

**invoice / receipt / credit note / expense note → text/OCR → canonical JSON → validation → expense category**

This is deliberately a runnable CLI prototype before it is a service. Point it at documents, inspect the JSON, collect failures, then add persistence and production infrastructure once the core quality deserves it.

## What works now

- text PDFs: extract embedded text locally
- scanned/mixed PDFs: OCR only pages without enough embedded text
- PNG/JPEG/WebP/etc.: local Tesseract OCR
- XML/UBL/plain text: pass structured text directly to the LLM
- DeepSeek OpenAI-compatible API adapter
- DeepSeek JSON mode for canonical document extraction
- a separate DeepSeek call for ledger-account categorization
- deterministic financial validation
- configurable chart of accounts
- token usage + conservative estimated API cost
- `$0.15` request-budget/review guardrail
- invoices, receipts, credit notes, and employee expense notes

DeepSeek is intentionally **not** the OCR layer. Its API models take text input, so the cheap path is local text/OCR first, then DeepSeek for understanding and classification.

## Pipeline

```text
file
  ↓
local document text extractor
  ├─ XML / text ────────────────────────┐
  ├─ text PDF → embedded text ----------┤
  ├─ mixed PDF → text + OCR weak pages -┤
  └─ image / scan → Tesseract OCR -------┤
                                        ↓
                              DeepSeek JSON extraction
                                        ↓
                                canonical document
                                        ↓
                           deterministic validation
                                        ↓
                          DeepSeek account selection
                                        ↓
                      confidence + cost review routing
                                        ↓
                                  result JSON
```

## Quick start

Requirements:

- Python 3.12+
- a DeepSeek API key
- Tesseract if you want to process images or scanned PDF pages

On Debian/Ubuntu:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

For Belgian documents, install Dutch/French language packs too if your OS provides them.

Install:

```bash
git clone https://github.com/selectqoma/receipt-to-ledger.git
cd receipt-to-ledger
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Configure DeepSeek:

```bash
export DEEPSEEK_API_KEY="your-key"
# optional; defaults to deepseek-v4-flash
export DEEPSEEK_MODEL="deepseek-v4-flash"
```

### Check OCR/text extraction without spending API money

```bash
rtl extract-text path/to/invoice.pdf
```

For multilingual scans:

```bash
rtl extract-text path/to/receipt.jpg --ocr-lang nld+fra+eng
```

### Process + categorize

An example chart is included for testing:

```bash
rtl process path/to/invoice.pdf \
  --chart examples/chart_of_accounts.json \
  --output result.json
```

Try the included expense note:

```bash
rtl process examples/sample_expense_note.txt \
  --chart examples/chart_of_accounts.json
```

Omit `--chart` to test document extraction/validation without categorization:

```bash
rtl process path/to/invoice.pdf
```

### Batch-test different document types

```bash
mkdir -p results
for f in test-docs/*; do
  name="$(basename "$f")"
  rtl process "$f" \
    --chart examples/chart_of_accounts.json \
    --output "results/${name}.json" || true
done
```

Useful test cases:

- normal text PDF invoice
- scanned PDF invoice
- photographed receipt
- credit note
- employee expense note
- UBL/XML invoice
- ugly low-resolution scan

The ugly documents are the useful ones. Perfect invoices mostly test whether computers remain capable of reading text in 2026.

## Result shape

The CLI returns one JSON object with:

```json
{
  "document": {},
  "source": {
    "method": "pdf_text+tesseract_ocr",
    "content_type": "application/pdf",
    "pages": 2,
    "ocr_pages": 1,
    "characters": 1340
  },
  "validation": {
    "ok": true,
    "failures": []
  },
  "category": {
    "account_code": "614000",
    "label": "Travel and transport",
    "confidence": 0.91,
    "source": "deepseek",
    "reason": "Business train travel"
  },
  "review_required": true,
  "provider_usage": [
    {
      "provider": "deepseek",
      "model": "deepseek-v4-flash",
      "operation": "document_extraction",
      "prompt_tokens": 1700,
      "completion_tokens": 300,
      "estimated_cost_usd": 0.000322
    }
  ],
  "estimated_cost_usd": 0.0005
}
```

Actual model output/token counts vary.

## Review logic

A result requires review by default if:

- deterministic validation fails
- no category is produced
- category confidence is below `0.95`
- estimated request cost exceeds `$0.15`

Override thresholds while experimenting:

```bash
rtl process invoice.pdf \
  --chart examples/chart_of_accounts.json \
  --auto-book-threshold 0.90 \
  --budget-usd 0.15
```

**The current confidence is model self-confidence, not calibrated probability.** It is useful for experimentation, not production auto-booking. Calibration should come from real accountant corrections.

## Cost accounting

The DeepSeek adapter records prompt/completion tokens and estimates cost from configurable per-million-token rates. Input is priced conservatively as cache-miss input.

```bash
export DEEPSEEK_INPUT_USD_PER_M="0.14"
export DEEPSEEK_OUTPUT_USD_PER_M="0.28"
```

Provider pricing changes. Re-check it before treating these defaults as billing truth.

## Supported inputs

| Input | Base workflow |
|---|---|
| PDF with embedded text | local extraction |
| scanned/mixed PDF | Tesseract OCR only on weak pages |
| PNG/JPEG/WebP/etc. | Tesseract OCR |
| XML / UBL | structured text sent to DeepSeek |
| plain text | pass through |
| Factur-X/ZUGFeRD embedded XML | deterministic extraction not implemented yet |

## Chart of accounts

`--chart` accepts an array or `{ "accounts": [...] }`:

```json
{
  "accounts": [
    {
      "account_code": "611100",
      "label": "Cloud infrastructure",
      "description": "Cloud compute, hosting and storage",
      "examples": ["AWS", "Azure", "Google Cloud"]
    }
  ]
}
```

The adapter rejects any account code not present in your supplied chart. The model does not get to invent a new ledger because it felt inspired.

## Tests

```bash
pytest -q
```

The suite covers validation, text/XML routing, pipeline cost aggregation, and rejection of hallucinated ledger accounts. The implementation was also smoke-tested locally with Tesseract on an image invoice and a scanned PDF.

## Next highest-value work

1. deterministic UBL / Factur-X parsing so structured invoices skip the first LLM call
2. vendor normalization + tenant-specific categorization memory
3. persisted accountant corrections
4. calibrated confidence/evaluation corpus
5. duplicate detection
6. VAT/country-specific validation
7. candidate retrieval for very large charts of accounts
8. provider/OCR fallbacks
9. service/API layer after quality is measured
