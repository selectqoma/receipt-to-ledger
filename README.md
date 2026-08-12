# receipt-to-ledger

Cost-aware document understanding for accountants:

**invoice / receipt / expense note → canonical JSON → validated bookkeeping category**

The design goal is not merely to stay under **$0.15 per request on average**. It is to make normal documents cost roughly **$0.01–$0.03**, reserve expensive models for ambiguous cases, and minimize human review without silently creating accounting errors.

## Core idea

Use a cascade instead of sending every document to one large multimodal model:

```text
upload
  ↓
document router
  ├─ structured invoice/XML (UBL, Factur-X/ZUGFeRD) ─┐
  ├─ text PDF ----------------------------------------┤
  └─ scan/photo → OCR / document extraction ----------┤
                                                     ↓
                                            canonical JSON
                                                     ↓
                                           financial validation
                                                     ↓
                                            vendor normalization
                                                     ↓
                                client history + cheap classifier
                                                     ↓
                                          confidence routing
                                      ┌──────────────┴──────────────┐
                                      ↓                             ↓
                                 auto-accept                   LLM fallback
                                                                    ↓
                                                               human review
                                                                    ↓
                                                            correction memory
```

## Supported document classes

The canonical model is deliberately broader than `Invoice`:

- invoice
- receipt
- credit note
- expense note / employee expense
- unknown document requiring review

Expense notes may describe spend without all invoice fields. Validation is therefore document-type aware rather than insisting that every piece of paper possesses an invoice number because schemas, unlike humans, should be allowed to notice reality.

## Why this should be cheap

1. **Do not OCR structured documents.** Extract embedded XML/text when available.
2. **OCR only genuine images/scans.**
3. **Normalize to one internal schema.** Provider-specific output stops at the adapter boundary.
4. **Use deterministic accounting checks before another model call.**
5. **Learn vendor/category behavior per client.** Repeat vendors should approach zero AI cost.
6. **Use a local/cheap classifier for common cases.**
7. **Send only low-confidence cases to an LLM.** Give it the top candidate ledger accounts rather than the entire chart of accounts.
8. **Turn accountant corrections into training data.**

See [`docs/architecture.md`](docs/architecture.md) and [`docs/cost-model.md`](docs/cost-model.md).

## Target economics

Engineering targets:

| Metric | Target |
|---|---:|
| p50 processing cost | < $0.01 |
| average processing cost | < $0.03 |
| p95 processing cost | < $0.08 |
| hard per-request guardrail | $0.15 |

These are architecture targets, not permanent vendor-price promises. Provider pricing belongs in configuration and should be periodically revalidated.

## Canonical output

Example:

```json
{
  "document_type": "receipt",
  "supplier": {
    "name": "Example Coffee BV",
    "vat_number": "BE0123456789"
  },
  "document_number": null,
  "issue_date": "2026-08-12",
  "currency": "EUR",
  "amounts": {
    "subtotal": 4.72,
    "tax": 0.28,
    "total": 5.00
  },
  "lines": [
    {
      "description": "Coffee",
      "quantity": 1,
      "unit_price": 5.00,
      "total": 5.00
    }
  ],
  "category_prediction": {
    "account_code": "613500",
    "label": "Meals and small business expenses",
    "confidence": 0.96,
    "source": "client_vendor_history"
  }
}
```

The exact account code is tenant-specific. The system must never pretend a global category taxonomy is identical to a client's chart of accounts.

## Pipeline contract

```python
result = await processor.process(document)

# result.document       canonical parsed document
# result.validation     invariant checks + confidence
# result.category       predicted ledger account
# result.review_required
# result.estimated_cost_usd
```

## Suggested stack

- FastAPI
- PostgreSQL
- S3-compatible object storage
- Redis or another durable job queue
- Pydantic v2
- OCR/document provider behind an adapter
- CatBoost or LightGBM for tabular/text-derived classification
- embeddings only where they materially improve vendor/description matching
- a small structured-output LLM for ambiguous cases

## Repository layout

```text
.
├── docs/
│   ├── architecture.md
│   ├── cost-model.md
│   └── roadmap.md
├── schemas/
│   └── accounting_document.schema.json
├── src/receipt_to_ledger/
│   ├── __init__.py
│   ├── models.py
│   ├── pipeline.py
│   └── validation.py
├── tests/
│   └── test_validation.py
├── pyproject.toml
└── README.md
```

## The moat

OCR is infrastructure. The defensible asset is the feedback loop:

```text
(client, normalized vendor, description, VAT treatment, amount context)
                               ↓
                     predicted ledger account
                               ↓
                     accountant correction
                               ↓
                    tenant-specific memory
                               ↓
                 better next prediction
```

A corrected categorization should become an event, not a destructive overwrite. That gives an auditable history and clean supervised training data.
