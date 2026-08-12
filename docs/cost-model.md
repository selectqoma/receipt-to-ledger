# Cost model

## Objective

Hard business constraint:

> Average total processing cost < **$0.15/request**.

Internal engineering target:

> Average variable compute/API cost < **$0.03/request**.

The remaining budget is margin for retries, unusually long documents, observability, storage, queueing, support, and provider price changes.

## Cost equation

For a request `r`:

```text
C(r) = C_route
     + C_extract
     + C_validate
     + C_vendor
     + C_classify
     + C_llm_fallback
     + C_infra
     + C_retry
```

The useful optimization target is the expected value across the workload, not the cost of one pristine one-page invoice.

## Example workload model

Illustrative assumptions:

| Route | Share | Typical variable cost |
|---|---:|---:|
| Structured XML / embedded data | 15% | $0.001 |
| Native text PDF | 20% | $0.002 |
| OCR scan/photo | 60% | $0.010 |
| Hard fallback/retry | 5% | $0.060 |

Expected extraction-side cost:

```text
0.15×0.001 + 0.20×0.002 + 0.60×0.010 + 0.05×0.060
= $0.00955/request
```

Add classification, DB/queue/storage, and observability and the design can still plausibly operate around $0.01–$0.03/request at useful scale.

Vendor pricing changes, so keep per-provider prices in configuration and attach `estimated_cost_usd` to each pipeline span.

## Budget guardrail

Before an expensive retry/fallback:

```python
remaining = request_budget_usd - spent_so_far
if predicted_next_step_cost > remaining:
    route_to_human_review(reason="cost_budget_exceeded")
```

A human review queue is preferable to an unbounded retry loop that converts one blurry restaurant receipt into a small venture round.

## Cost telemetry

Record by request:

- pages processed
- route chosen
- OCR provider/model
- model tokens if applicable
- retries
- per-stage estimated and actual billed cost where available
- total cost
- review outcome
- final correctness/correction event

Track:

```text
cost/request
cost/page
cost/auto-booked document
cost/correctly categorized document
human-review rate
correction rate after auto-book
```

The last two matter more than shaving another tenth of a cent from OCR.
