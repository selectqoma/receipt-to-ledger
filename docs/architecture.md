# Architecture

## 1. Goals

The system accepts invoices, receipts, credit notes, and expense notes and returns:

1. canonical structured data;
2. explicit validation results;
3. normalized merchant/vendor identity;
4. a ledger-category prediction;
5. confidence at each stage;
6. whether human review is required;
7. estimated processing cost.

Primary constraint: **average end-to-end processing cost below $0.15/request**, with a preferred operating target below $0.03.

Accuracy is a harder requirement than raw transcription quality. A beautifully extracted wrong total is still a wrong total.

## 2. Stage A: input router

Keep routing deliberately small:

1. Machine-readable XML / UBL / plain text → decode locally, then use structured text extraction.
2. PDFs and images → send the original document directly to the multimodal document extractor.
3. Malformed or unsupported inputs → reject or route to review rather than guessing.

The current default visual extractor is Gemini. The structured-text path uses DeepSeek until deterministic UBL / Factur-X mapping is implemented.

The router should emit:

```python
DocumentRoute(
    kind="structured_text" | "visual_document" | "unknown",
    document_type_hint="invoice" | "receipt" | "credit_note" | "expense_note" | None,
    page_count=1,
    confidence=0.99,
)
```

## 3. Stage B: canonical extraction

All extraction providers map into a provider-independent `AccountingDocument`.

Important rules:

- preserve raw source values alongside normalized values when useful;
- store field-level confidence;
- record provider/model/version;
- record page provenance for important fields;
- never let provider-specific JSON leak into downstream accounting logic.

The schema intentionally has optional invoice-specific fields. A receipt or employee expense note may not contain an invoice number, payment terms, or customer VAT identifier.

## 4. Stage C: financial validation

Run deterministic invariants before paying another model.

Examples:

```text
subtotal + tax ≈ total
sum(line totals) ≈ subtotal (when line prices exclude tax)
sum(tax breakdown) ≈ tax
due date >= issue date (when both exist)
currency is valid
VAT/tax identifier passes country-specific syntax/checksum when supported
supplier and customer are not obviously the same legal entity
duplicate fingerprint not already booked
```

Use tolerances appropriate to currency rounding. Validation failures should lower document confidence and may trigger a second extraction pass or review.

### Duplicate detection

Strong fingerprint:

```text
supplier identity + document number
```

Fallback fingerprint:

```text
supplier identity + issue date + total + currency
```

Use fuzzy matching rather than assuming extracted strings are identical every time.

## 5. Stage D: vendor normalization

Resolve noisy extracted names to a stable vendor identity.

Signals:

- VAT/tax identifier
- IBAN/account number where legally and operationally appropriate
- normalized legal name
- address/domain/email
- client-specific aliases
- fuzzy name similarity

Vendor resolution should itself have confidence.

## 6. Stage E: categorization cascade

### Level 1: deterministic tenant rule

Examples:

```text
client A + vendor AWS Europe → account 613200
client B + vendor AWS Europe → account 612100
```

Same vendor can map differently for different clients.

### Level 2: historical classifier

Features can include:

- `client_id`
- `vendor_id`
- vendor tax ID
- normalized description terms
- line-description embedding or sparse text features
- amount / log(amount)
- currency
- tax rate and tax treatment
- day/month/recurrence features
- previous account assignments
- document type

Start with CatBoost or LightGBM before inventing a neural architecture merely to give the GPU something to do.

### Level 3: global classifier

Useful for cold-start clients. It should produce top-k candidate accounts/categories, ideally through a mapping layer between a global taxonomy and the client's chart of accounts.

### Level 4: LLM discriminator

Only for uncertain cases.

Give the model:

- concise canonical document data;
- normalized vendor;
- top 3–10 candidate accounts;
- relevant client-specific examples;
- explicit structured-output schema.

Do **not** send the entire chart of accounts unless genuinely necessary.

### Level 5: human review

Human review is not failure. Silent confident misclassification is failure.

Every correction becomes an immutable learning event:

```text
prediction → corrected account → who corrected it → timestamp → model/version
```

## 7. Confidence model

Keep separate confidences rather than manufacturing one mystical score.

```text
route_confidence
extraction_confidence
financial_validation_confidence
vendor_resolution_confidence
category_confidence
```

A policy layer decides whether to auto-book:

```python
if not validation.ok:
    review()
elif extraction_confidence < 0.97:
    review_or_retry()
elif category_confidence >= tenant.auto_book_threshold:
    auto_book()
else:
    review()
```

Thresholds should be calibrated from historical outcomes, not selected because `0.95` has pleasing typography.

## 8. Expense notes

Treat an expense note as a first-class document type.

Possible fields:

- employee/submitter
- expense date
- merchant
- business purpose
- project/cost center
- payment method
- reimbursable flag
- receipt attachment references
- total/tax/currency
- lines

An expense note may aggregate multiple receipts. Model this as a parent `expense_note` with zero or more attached `AccountingDocument` children rather than flattening everything into one synthetic invoice.

## 9. Auditability

Store:

- source document hash
- immutable original file
- extraction provider/model/version
- raw extraction result or retrievable reference
- canonical result versions
- validation outcomes
- category predictions
- human corrections
- final bookkeeping decision

This allows replay when schemas/models change and provides the paper trail accountants unsurprisingly insist on.

## 10. Privacy and isolation

Client bookkeeping history is sensitive and tenant-specific.

Minimum expectations:

- strict tenant isolation
- encrypted object storage
- encrypted database connections/storage
- short-lived signed document URLs
- secrets in a secret manager
- configurable retention
- no cross-tenant training examples unless explicitly permitted and appropriately anonymized/aggregated
- audit log for human access and corrections
