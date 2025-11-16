# [Processor Name] - Quick Reference

**Last Updated**: [Date]
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase X - [Analytics/Precompute] |
| **Schedule** | [When it runs - e.g., "Nightly at 11:00 PM"] |
| **Duration** | [Expected runtime] |
| **Priority** | [High/Medium/Low] + [Why] |
| **Status** | ✅ Production Ready / 🚧 In Development |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `path/to/processor.py` | XXX lines |
| **Schema** | `path/to/schema.sql` | XX fields |
| **Tests** | `tests/path/` | **XX total** |
| | - Unit tests | XX tests |
| | - Integration tests | XX tests |
| | - Validation tests | XX tests |

---

## Dependencies (v4.0 Tracking)

```
Phase X Sources:
  ├─ source_table_1 (CRITICAL) - What it provides
  ├─ source_table_2 (CRITICAL) - What it provides
  └─ source_table_3 (OPTIONAL) - What it provides

Consumers:
  ├─ downstream_processor_1 - What it uses
  └─ downstream_processor_2 - What it uses
```

---

## What It Does

1. **Primary Function**: [One sentence description]
2. **Key Output**: [What it produces]
3. **Value**: [Why it matters]

---

## Key Metrics Calculated

### 1. [Metric Name]
```python
# Formula
metric = calculation_here
```
- **Range**: [Min - Max]
- **Example**: [Concrete example]

### 2. [Metric Name]
```python
# Formula
metric = calculation_here
```
- **Range**: [Min - Max]
- **Example**: [Concrete example]

### 3. [Metric Name]
```python
# Formula
metric = calculation_here
```
- **Range**: [Min - Max]
- **Example**: [Concrete example]

---

## Output Schema Summary

**Total Fields**: XX

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | X | player_lookup, game_id |
| Business Metrics | XX | points_avg, usage_rate |
| Source Tracking (v4.0) | XX | source_*_last_updated |
| Data Quality | X | data_quality_tier |
| Metadata | X | processed_at, created_at |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  COUNT(*) as records_processed,
  AVG(quality_metric) as avg_quality,
  MAX(processed_at) as last_run
FROM `project.dataset.table_name`
WHERE partition_date = CURRENT_DATE();

-- Expected Results:
-- records_processed: XXX-XXX
-- avg_quality: XX-XX
-- last_run: < 24 hours old
```

---

## Common Issues & Quick Fixes

### Issue 1: [Problem Description]
**Symptom**: [What you see]
**Diagnosis**:
```sql
-- Quick check query
SELECT ...
```
**Fix**: [Steps to resolve]

### Issue 2: [Problem Description]
**Symptom**: [What you see]
**Diagnosis**:
```sql
-- Quick check query
SELECT ...
```
**Fix**: [Steps to resolve]

### Issue 3: [Problem Description]
**Symptom**: [What you see]
**Fix**: [Steps to resolve]

---

## Processing Flow

```
[upstream_1] ─┐
              ├─→ [THIS PROCESSOR] ─→ [downstream_1]
[upstream_2] ─┘                     └─→ [downstream_2]
```

**Timing**:
- Waits for: [upstream processors] to complete
- Must complete before: [downstream processors] can run
- Total window: [time range]

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Records processed | < XXX | Critical |
| Processing time | > XX min | Warning |
| Source age | > 24 hrs | Warning |
| Source age | > 72 hrs | Critical |
| Data quality | < XX% | Warning |

---

## Quick Links

- 📄 **Detailed Documentation**: [Link to full wiki page]
- 🗂️ **Schema Definition**: `schemas/bigquery/[path]/schema.sql`
- 🧪 **Test Suite**: `tests/processors/[path]/`
- 📊 **Related Processors**:
  - [Upstream Processor Name]
  - [Downstream Processor Name]

---

## Notes

- [Special consideration 1]
- [Special consideration 2]
- [Special consideration 3]

---

**Template Version**: 1.0
**Created**: 2025-11-15
