# Code Examples

**Purpose:** Working code examples demonstrating implementation patterns
**Last Updated:** 2025-11-23

---

## What's Here

This directory contains **complete, runnable code examples** that demonstrate how to implement common patterns and features in the NBA Props Platform.

**Use these when:**
- Implementing a new processor with similar patterns
- Learning how a specific pattern works
- Understanding integration points between components
- Debugging issues with existing implementations

---

## Available Examples

### [smart_reprocessing_integration.py](smart_reprocessing_integration.py)

**Pattern:** Smart Reprocessing (Hash-based change detection)
**Applies to:** Phase 3 Analytics Processors
**Impact:** 30-50% reduction in processing costs

#### What It Shows

Complete integration example demonstrating:
- **Smart reprocessing** - Skip processing when Phase 2 source data unchanged
- **Dependency tracking** - How to configure dependency checks
- **Skip detection** - Check if processing can be skipped
- **Metrics tracking** - Count skips vs processes
- **Two approaches** - Check primary source only (lenient) vs all sources (strict)

#### Key Code Sections

```python
# 1. Dependency Configuration
DEPENDENCIES = {
    'source_table': {
        'field_prefix': 'source_gamebook',
        'check_type': 'date_range',
        'critical': True
    }
}

# 2. Smart Skip Check
skip, reason = self.should_skip_processing(
    game_date=start_date,
    check_all_sources=False  # Only check first dependency
)

# 3. Handle Skip
if skip:
    self.raw_data = []  # Signal skip
    return
```

#### When to Use This Pattern

✅ **Use when:**
- Phase 3 processor consuming Phase 2 data
- Want to avoid reprocessing unchanged data
- Processing is expensive (BigQuery queries, computations)

❌ **Don't use when:**
- Phase 2 processor (different pattern)
- Real-time processing (smart reprocessing adds latency)
- Data always changes (no benefit)

#### Integration Steps

1. **Copy dependency configuration** to your processor
2. **Add skip check** at start of `extract_raw_data()`
3. **Set `self.raw_data = []`** when skipping
4. **Test** with unchanged data to verify skip works
5. **Monitor metrics** to measure skip rate

#### Expected Results

- **Skip rate:** 70-85% for typical scenarios
- **Cost reduction:** 30-50% in Phase 3 processing
- **No data loss:** Skipped processing is identical to reprocessing

---

## Related Documentation

### Pattern Implementation Guides
- [Smart Reprocessing Pattern](../patterns/12-smart-idempotency-reference.md) - Full pattern reference
- [Processor Development Guide](../guides/01-processor-development-guide.md) - General processor development
- [Processor Patterns](../guides/processor-patterns/04-smart-reprocessing.md) - Pattern integration guide

### Implementation References
- [Smart Idempotency Strategy](../implementation/reference/smart-idempotency/) - Detailed implementation docs
- [Dependency Checking](../dependency-checks/02-analytics-processors.md) - Phase 3 dependency patterns
- [Phase 2 Hash Strategy](../reference/phase2-processor-hash-strategy.md) - How hashes are calculated

### Operational Docs
- [Phase 3 Operations Guide](../processors/02-phase3-operations-guide.md) - Running Phase 3 processors
- [Monitoring](../monitoring/08-pattern-efficiency-monitoring.md) - Track skip rates

---

## Adding New Examples

When adding examples to this directory:

### Guidelines
1. **Complete and runnable** - Should work with minimal modification
2. **Well-commented** - Explain what each section does
3. **Single pattern focus** - One clear pattern per example
4. **Real-world applicable** - Based on actual implementation needs
5. **Include context** - Add docstring explaining when to use it

### Documentation Required
- Update this README with new example details
- Add "When to Use" and "When NOT to Use" sections
- Include expected results/metrics
- Link to related documentation

### Example Template
```python
#!/usr/bin/env python3
"""
[Pattern Name] Integration Example

Shows how to integrate [pattern] into [processor type].
This enables [benefit].

Expected Impact: [quantified impact]
"""

# Implementation here...
```

---

## Testing Examples

All examples should be:
- ✅ **Syntax validated** - Python files must be valid syntax
- ✅ **Import verified** - All imports must resolve
- ✅ **Pattern verified** - Example matches actual implementation
- ⚠️ **Not executable as-is** - Examples are templates, not production code

**Note:** These are integration examples, not unit tests. See [testing/](../testing/) for test examples.

---

## Contributing

When you implement a useful pattern that others might reuse:

1. Extract the pattern into a clean example
2. Remove project-specific details
3. Add comprehensive comments
4. Update this README
5. Link from relevant guide docs

**Good examples save hours of implementation time!**

---

**Directory Status:** ✅ Active
**Examples Count:** 1 (smart reprocessing)
**Planned Additions:**
- Completeness checking integration
- Historical dependency checking
- Circuit breaker implementation
- Batch coalescing pattern
