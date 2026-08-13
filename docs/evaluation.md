# Ground-truth evaluation

This repository includes an evaluation harness for measuring field accuracy, whole-document exactness, category accuracy, latency, and real provider cost.

Keep API keys in environment variables. Do not put keys in manifests, test fixtures, shell history you share, or Git commits.

## Install

```bash
pip install -e ".[dev,eval]"
```

## Public receipt benchmark: CORD v2

CORD v2 contains receipt images with JSON ground truth for totals, tax, and detailed menu/line-item fields. The evaluator streams the public dataset from Hugging Face and sends the original images to Gemini.

DeepSeek is intentionally not part of the CORD score because CORD does not contain tenant-specific bookkeeping-account labels.

Start with 25 validation receipts and a hard experiment budget of $0.50:

```bash
export GEMINI_API_KEY="your-google-key"

rtl eval cord \
  --split validation \
  --limit 25 \
  --max-cost-usd 0.50 \
  --output evaluation-cord.json
```

Run the complete 100-document validation split once the smoke run looks sane:

```bash
rtl eval cord \
  --split validation \
  --limit 100 \
  --max-cost-usd 2.00 \
  --output evaluation-cord-full.json
```

The report includes exact accuracy for:

- document type
- subtotal
- tax
- total
- line descriptions
- line totals
- exact line rows
- whole-document exactness
- mean / p50 / p95 API cost
- mean / p50 / p95 latency
- failed API cases

Money is scored to the cent. Line items are scored as multisets, so row ordering does not change the score.

## Private invoice benchmark

Public datasets cannot tell us whether a Belgian accountant would trust the system, and they cannot provide a client's chart-of-accounts truth. For that, create a local JSONL manifest pointing at documents plus partial or full canonical ground truth.

Do not commit customer documents or manifests containing customer data. `test-docs/`, `results/`, `data/`, and `evaluation*.json` are ignored by Git.

Example `test-docs/manifest.jsonl` entry:

```json
{"id":"invoice-001","file":"invoice-001.pdf","ground_truth":{"document_type":"invoice","supplier":{"name":"Example BV","vat_number":"BE0123456789"},"document_number":"INV-001","issue_date":"2026-08-01","currency":"EUR","amounts":{"subtotal":100.0,"tax":21.0,"total":121.0},"lines":[{"description":"Cloud hosting","total":100.0}],"category_prediction":{"account_code":"611100"}}}
```

Evaluate extraction only with Gemini:

```bash
export GEMINI_API_KEY="your-google-key"

rtl eval manifest test-docs/manifest.jsonl \
  --limit 20 \
  --max-cost-usd 0.50 \
  --output evaluation-private.json
```

Evaluate extraction and ledger categorization with Gemini + DeepSeek:

```bash
export GEMINI_API_KEY="your-google-key"
export DEEPSEEK_API_KEY="your-deepseek-key"

rtl eval manifest test-docs/manifest.jsonl \
  --chart examples/chart_of_accounts.json \
  --limit 20 \
  --max-cost-usd 0.50 \
  --output evaluation-private-with-category.json
```

If a manifest case contains `ground_truth.category_prediction.account_code` or a top-level `expected_account_code`, the report includes category accuracy. Only ground-truth fields that are present are scored, so a useful first gold set can label just supplier, VAT ID, invoice number, dates, subtotal, VAT, and total, then add line items later.

## Experiment budget

The default total experiment budget is `$0.50`. The runner stops starting new cases once measured API spend reaches the configured amount:

```bash
rtl eval cord --limit 100 --max-cost-usd 0.25
```

A single in-flight request can push the measured total slightly above the cap. The cap is a guardrail, not a prepaid card.

## Recommended progression

1. Run 10-25 CORD validation receipts to confirm the evaluator and API setup.
2. Run all 100 CORD validation receipts with Gemini 3.6 Flash.
3. Repeat with Gemini 3.5 Flash-Lite and compare accuracy/cost.
4. Label 25-50 private Belgian invoices in the manifest format.
5. Add expected ledger accounts and run the category benchmark with DeepSeek.
6. Expand the private set around failures: multiple VAT rates, credit notes, French/Dutch invoices, bad phone photos, long line tables, and expense notes.

The private gold set should become the product benchmark. Public leaderboards are useful for orientation; your real documents decide whether the system deserves automation privileges.
