# Roadmap

## Phase 0: evaluation corpus

Before building clever machinery, collect a representative, permissioned corpus:

- clean invoices
- ugly scans
- phone photos
- receipts
- credit notes
- expense notes
- multi-page documents
- multiple languages
- different VAT/tax regimes relevant to target customers

Label canonical fields and final ledger categories.

Primary metrics:

- field exact match / normalized match
- amount/date accuracy
- document-level validation pass rate
- category top-1/top-3 accuracy
- human-review rate
- false auto-book rate
- mean and p95 variable cost

The public CORD benchmark and private JSONL manifest evaluator are already available through `rtl eval`.

## Phase 1: extraction MVP

- upload API
- immutable object storage
- small input router
- Gemini multimodal document adapter for PDFs/images
- DeepSeek structured extraction for XML/plain text
- deterministic UBL / Factur-X mapping where possible
- canonical Pydantic model
- financial validation
- JSON API result

Do not build categorization ML until extraction quality is measurable.

## Phase 2: bookkeeping categorization

- tenant charts of accounts
- vendor normalization
- deterministic vendor rules
- correction event model
- baseline classifier
- calibrated confidence
- review queue

## Phase 3: LLM fallback

- top-k candidate retrieval
- structured-output LLM discriminator
- cost budget enforcement
- fallback evaluation set

## Phase 4: learning loop

- retraining dataset builder from immutable correction events
- scheduled model evaluation
- shadow deployment
- model/version registry
- tenant-level drift monitoring

## Phase 5: production hardening

- idempotency
- duplicate detection
- dead-letter queue
- backpressure
- rate limits
- provider failover
- PII/security review
- data retention controls
- complete audit trail
- replay pipeline

## Do not build first

- a custom OCR foundation model
- a vector database for every string in sight
- a giant agent workflow
- fine-tuned LLM categorization before you have correction data

The first moat is feedback data and trustworthy workflow integration, not owning more CUDA kernels.
