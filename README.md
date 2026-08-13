# receipt-to-ledger

A cost-aware base workflow for accountants:

**invoice / receipt / credit note / expense note → multimodal extraction → canonical JSON → validation → expense category**

This is deliberately a runnable CLI prototype before it becomes a service. The current goal is to throw real accounting documents at it, measure field accuracy and cost, and collect failure cases before adding databases, queues, dashboards, and the rest of the infrastructure furniture humans eventually stack around a working function.

## Default architecture

For PDFs and images, the default workflow now sends the **original document directly to Gemini**. It does not flatten the document through Tesseract first, so the model can use layout, tables, spatial relationships, handwriting, rotation, and the exact visual placement of totals and VAT fields.

DeepSeek remains the cheap ledger classifier.

```text
file
  ↓
input router
  ├─ PDF / image ───────────────→ Gemini 3.6 Flash multimodal extraction ─┐
  └─ XML / plain text ──────────→ local text decode → DeepSeek extraction ┤
                                                                         ↓
                                                               canonical JSON
                                                                         ↓
                                                         deterministic validation
                                                                         ↓
                                                              DeepSeek V4 Flash
                                                              account selection
                                                                         ↓
                                                         confidence + cost routing
                                                                         ↓
                                                                  result JSON
```

Tesseract is still included as a **debug/fallback path**, not the normal OCR path. `rtl extract-text` lets you inspect what a classic OCR/text pipeline would see, and `--document-provider deepseek-text` lets you compare it against the multimodal route.

## What works now

- PDF invoices and scanned PDFs → Gemini native PDF vision
- photographed/scanned receipts → Gemini image vision
- Gemini structured output directly into the canonical Pydantic schema
- XML/UBL/plain text → local decode + DeepSeek structured extraction
- DeepSeek V4 Flash ledger-account categorization
- deterministic financial validation
- configurable chart of accounts
- prompt/output/**thinking** token usage and estimated API cost
- `$0.15` request-budget/review guardrail
- invoices, receipts, credit notes, and employee expense notes
- Tesseract local OCR retained for debugging and A/B testing

## Why Gemini is the default vision extractor

The OCR stage is not treated as “turn pixels into a string.” For accounting documents we care about relations such as which number belongs to `TOTAL`, which VAT rate belongs to which base, how line-item columns align, and whether a photographed receipt is rotated or messy.

The default is `gemini-3.6-flash`, a stable multimodal model that accepts image and PDF inputs and supports structured outputs. For cheaper A/B tests, switch to `gemini-3.5-flash-lite` without changing the pipeline.

## Quick start

Requirements:

- Python 3.12+
- Gemini API key for PDF/image extraction
- DeepSeek API key for categorization and text/XML extraction
- Tesseract only if you want the local OCR debug/fallback path

```bash
git clone https://github.com/selectqoma/receipt-to-ledger.git
cd receipt-to-ledger

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Configure providers:

```bash
export GEMINI_API_KEY="your-google-key"
export DEEPSEEK_API_KEY="your-deepseek-key"
```

Defaults:

```bash
export GEMINI_MODEL="gemini-3.6-flash"
export GEMINI_THINKING_LEVEL="low"
export GEMINI_MEDIA_RESOLUTION="auto"  # medium PDFs, high images
export DEEPSEEK_MODEL="deepseek-v4-flash"
```

### Process a PDF invoice

```bash
rtl process path/to/invoice.pdf \
  --chart examples/chart_of_accounts.json \
  --output result.json
```

### Process a photographed receipt

```bash
rtl process path/to/receipt.jpg \
  --chart examples/chart_of_accounts.json \
  --output receipt.json
```

### Process the included expense note

Plain text does not need Gemini. It goes through the text/DeepSeek route:

```bash
rtl process examples/sample_expense_note.txt \
  --chart examples/chart_of_accounts.json
```

### Extract only, without categorization

For a PDF/image, this needs only `GEMINI_API_KEY`:

```bash
rtl process path/to/invoice.pdf
```

### Compare against the old local OCR route

Install Tesseract, for example on Debian/Ubuntu:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

Inspect local OCR/text extraction without an API call:

```bash
rtl extract-text path/to/invoice.pdf
rtl extract-text path/to/receipt.jpg --ocr-lang nld+fra+eng
```

Run the full pipeline but force the local-text/Tesseract + DeepSeek route:

```bash
rtl process path/to/receipt.jpg \
  --document-provider deepseek-text \
  --ocr-lang nld+fra+eng \
  --chart examples/chart_of_accounts.json
```

That is useful for building our own benchmark instead of arguing with generic OCR leaderboards until morale improves.

### Compare Gemini models

Quality-first default:

```bash
rtl process invoice.pdf \
  --gemini-model gemini-3.6-flash \
  --chart examples/chart_of_accounts.json
```

Cheaper experiment:

```bash
rtl process invoice.pdf \
  --gemini-model gemini-3.5-flash-lite \
  --gemini-thinking-level minimal \
  --chart examples/chart_of_accounts.json
```

Gemini's default media-resolution policy in this repo follows Google's current guidance: `medium` for PDFs and `high` for standalone images. Override it when benchmarking:

```bash
rtl process receipt.jpg \
  --gemini-media-resolution medium \
  --chart examples/chart_of_accounts.json
```

## Batch-test real documents

Create a local corpus that is **not committed** if it contains customer data:

```bash
mkdir -p test-docs results

for f in test-docs/*; do
  name="$(basename "$f")"
  rtl process "$f" \
    --chart examples/chart_of_accounts.json \
    --output "results/${name}.json" || true
done
```

Useful test cases:

- pristine born-digital PDF invoice
- scanned PDF invoice
- phone photo of a crumpled receipt
- rotated receipt
- multilingual Belgian invoice
- credit note with negative values
- employee expense note
- UBL/XML invoice
- invoice with several VAT rates
- invoice with a long line-item table

For this product, the benchmark that matters is not generic OCR accuracy. Track exact correctness for:

- supplier name
- supplier VAT number
- invoice/document number
- issue date
- currency
- subtotal
- VAT total
- grand total
- VAT breakdown
- line-item totals/descriptions
- chosen ledger account
- review-required decision
- cost per document

## Result JSON

The CLI emits the accounting result plus operational metadata:

```json
{
  "document": {
    "document_type": "invoice",
    "supplier": {
      "name": "Example BV",
      "vat_number": "BE0123456789",
      "address": null
    },
    "document_number": "INV-2026-1042",
    "issue_date": "2026-08-01",
    "currency": "EUR",
    "amounts": {
      "subtotal": 100.0,
      "tax": 21.0,
      "total": 121.0
    },
    "category_prediction": {
      "account_code": "613200",
      "label": "Cloud infrastructure",
      "confidence": 0.96,
      "source": "deepseek",
      "reason": "Supplier and line items describe cloud hosting"
    }
  },
  "source": {
    "method": "gemini_multimodal",
    "content_type": "application/pdf",
    "pages": 1,
    "ocr_pages": 0,
    "vision_pages": 1,
    "characters": 0
  },
  "validation": {
    "ok": true,
    "failures": []
  },
  "review_required": false,
  "provider_usage": [
    {
      "provider": "gemini",
      "model": "gemini-3.6-flash",
      "operation": "multimodal_document_extraction",
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "thinking_tokens": 0,
      "estimated_cost_usd": 0.0
    }
  ],
  "estimated_cost_usd": 0.0
}
```

Token values above are placeholders; live API results report real usage.

## Review logic

By default a result requires review when any of these is true:

- deterministic validation fails
- no category is produced
- category confidence is below `0.95`
- estimated request cost exceeds `$0.15`

```bash
rtl process invoice.pdf \
  --chart examples/chart_of_accounts.json \
  --auto-book-threshold 0.90 \
  --budget-usd 0.15
```

**Important:** category confidence is currently model-reported, not statistically calibrated. Production auto-booking thresholds should come from labeled accountant corrections.

## Estimated cost per document

The current architecture is comfortably below the `$0.15` request ceiling for normal accounting documents. These are **engineering estimates**, not billing guarantees. Actual cost depends mostly on page/image count and Gemini output/thinking tokens.

Current list-price assumptions used by the code:

| Provider/model | Input | Output / thinking |
|---|---:|---:|
| Gemini 3.6 Flash | $1.50 / 1M tokens | $7.50 / 1M tokens |
| Gemini 3.5 Flash-Lite | $0.30 / 1M tokens | $2.50 / 1M tokens |
| DeepSeek V4 Flash | $0.14 / 1M cache-miss tokens | $0.28 / 1M tokens |

With the repo defaults, Gemini uses `medium` resolution for PDFs and `high` for standalone images. Gemini 3 media token budgets are approximately:

- PDF at `medium`: ~560 vision tokens per page; native embedded PDF text is included for the model but is not billed
- image at `high`: ~1,120 vision tokens per image

That means the **visual input itself is cheap**: roughly `$0.00084` per PDF page at medium resolution or `$0.00168` for a high-resolution image on Gemini 3.6 Flash. Structured output and thinking generally cost more than the image input.

Reasonable starting estimates for this pipeline:

| Document | Route | Expected API cost |
|---|---|---:|
| 1-page PDF invoice | Gemini 3.6 Flash → DeepSeek category | **~$0.005–$0.012** |
| photographed receipt | Gemini 3.6 Flash → DeepSeek category | **~$0.005–$0.012** |
| 2–3 page detailed invoice | Gemini 3.6 Flash → DeepSeek category | **~$0.01–$0.03** |
| 1-page document with Flash-Lite | Gemini 3.5 Flash-Lite → DeepSeek category | **~$0.002–$0.006** |
| XML/plain-text document | DeepSeek extraction → DeepSeek category | **usually < $0.001** |

A representative one-page Gemini 3.6 Flash request might use roughly `800` billed input tokens (prompt + medium-resolution PDF) and `800` billed output/thinking tokens. That is about `$0.0072` for extraction. A typical DeepSeek categorization call adds roughly `$0.0001–$0.0003`, putting the whole request near **three quarters of a cent**.

These estimates deliberately leave substantial headroom for retries and unusually verbose/complex documents. The CLI reports measured provider token usage and `estimated_cost_usd` for every request, so once we have a real invoice corpus, the README ranges should be replaced by observed p50/p95 costs rather than educated guesses.

The product targets remain:

| Metric | Target |
|---|---:|
| p50 processing cost | < $0.01 |
| average processing cost | < $0.03 |
| p95 processing cost | < $0.08 |
| hard per-request guardrail | $0.15 |

## Cost accounting

Each provider call records:

- provider/model
- operation
- input/prompt tokens
- visible output tokens
- thinking tokens when reported
- estimated USD cost

Gemini pricing overrides:

```bash
export GEMINI_INPUT_USD_PER_M="1.50"
export GEMINI_OUTPUT_USD_PER_M="7.50"
```

DeepSeek pricing overrides:

```bash
export DEEPSEEK_INPUT_USD_PER_M="0.14"
export DEEPSEEK_OUTPUT_USD_PER_M="0.28"
```

These are configuration, not eternal truths handed down on stone tablets. Re-check provider pricing before using the estimates for billing or margin reporting.

Pricing references checked 2026-08-13:

- Gemini models/pricing: https://ai.google.dev/gemini-api/docs/latest-model
- Gemini media token budgets: https://ai.google.dev/gemini-api/docs/media-resolution
- DeepSeek pricing: https://api-docs.deepseek.com/quick_start/pricing/

## Supported inputs

| Input | Default route |
|---|---|
| PDF with embedded text | Gemini native PDF understanding |
| scanned/mixed PDF | Gemini native PDF vision |
| PNG/JPEG/WebP/etc. | Gemini image vision |
| XML / UBL | local text decode → DeepSeek |
| plain text | local text decode → DeepSeek |
| local OCR comparison | Tesseract via `extract-text` or `--document-provider deepseek-text` |
| Factur-X/ZUGFeRD embedded XML | not deterministically extracted yet |

The next structured-document improvement is deterministic UBL/Factur-X mapping so those documents skip extraction-model calls entirely.
