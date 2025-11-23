# Processing Patterns

**Purpose:** Reference documentation for optimization patterns used across all processor phases

---

## Pattern Catalog

### Core Patterns (1-3)
1. [Circuit Breaker Implementation](01-circuit-breaker-implementation.md) - Stop processing on critical failures
2. [Dependency Precheck Comparison](02-dependency-precheck-comparison.md) - Validate dependencies before processing
3. [Early Exit Implementation](03-early-exit-implementation.md) - Skip unnecessary processing

### Batch Optimization (4-7)
4. [Batch Coalescing Reference](04-batch-coalescing-reference.md) - Combine multiple operations
5. [Processing Priority Reference](05-processing-priority-reference.md) - Prioritize critical entities
6. [Processing Checkpoints Reference](06-processing-checkpoints-reference.md) - Resume from failures
7. [BigQuery Batching Current](07-bigquery-batching-current.md) - Optimize BigQuery operations

### Smart Processing (8-12)
8. [Smart Skip Implementation](08-smart-skip-implementation.md) - Intelligent processing decisions
9. [Smart Backfill Detection](09-smart-backfill-detection.md) - Detect and handle backfills
10. [Change Classification Reference](10-change-classification-reference.md) - Classify data changes
11. [Smart Caching Reference](11-smart-caching-reference.md) - Intelligent caching strategies
12. [Smart Idempotency Reference](12-smart-idempotency-reference.md) - Hash-based change detection

---

## Pattern Application by Phase

- **Phase 2 (Raw):** Patterns 1, 8, 9, 12
- **Phase 3 (Analytics):** Patterns 1, 2, 8, 9, 12
- **Phase 4 (Precompute):** Patterns 1, 2, 8, 9, 12
- **Phase 5 (Predictions):** Patterns 1, 2, 3, 10

---

## Cost Impact

These patterns are estimated to reduce processing costs by **30-50%** by:
- Skipping unnecessary processing (smart skip, idempotency)
- Reducing BigQuery queries (batching, caching)
- Preventing cascade failures (circuit breaker)
- Optimizing dependency checks (precheck, early exit)

---

**See also:**
- [Guides - Processor Patterns](../guides/processor-patterns/) for implementation guides
- [Reference - Optimization Pattern Catalog](../reference/02-optimization-pattern-catalog.md) for advanced patterns
