# Cascade Contamination Prevention Guide

> **Date:** 2025-12-08
> **Status:** Design Document
> **Author:** Session 77

---

## 1. Problem Definition

### What is Cascade Contamination?

**Cascade Contamination** occurs when gaps in upstream data cause downstream processes to execute with incomplete inputs, producing records that:
1. **Exist** (pass existence checks)
2. **Look valid** (have timestamps, IDs, etc.)
3. **Contain invalid values** (NULLs, zeros, or incorrect calculations)

This is distinct from:
- **Missing data** - Records don't exist (easy to detect)
- **Stale data** - Data is old but was valid when created
- **Processing errors** - Exceptions during processing (logged as PROCESSING_ERROR)

### Why "Cascade Contamination"?

- **Cascade**: The problem propagates through multiple pipeline layers
- **Contamination**: The data is "infected" by upstream gaps and needs cleanup

### Real Example (Dec 2021)

```
Root Cause: team_defense_game_summary.opp_paint_attempts = NULL
    ↓ TDZA reads NULL paint data
Cascade L1: team_defense_zone_analysis.paint_defense_vs_league_avg = NULL
    ↓ PCF uses NULL for opponent strength calculation
Cascade L2: player_composite_factors.opponent_strength_score = 0
    ↓ MLFS extracts from PCF
Cascade L3: ml_feature_store_v2 would have bad features

Impact: 10,068 PCF records with opponent_strength_score = 0
```

---

## 2. Detection Methods

### 2.1 Critical Field Validation Query

Efficient single-query validation for a date range:

```sql
-- Detect cascade contamination across pipeline
WITH validation AS (
  SELECT
    'Phase3_TDGS' as stage,
    game_date as check_date,
    COUNT(*) as total,
    COUNTIF(opp_paint_attempts IS NOT NULL AND opp_paint_attempts > 0) as valid
  FROM `nba_analytics.team_defense_game_summary`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date

  UNION ALL

  SELECT
    'Phase4_TDZA',
    analysis_date,
    COUNT(*),
    COUNTIF(paint_defense_vs_league_avg IS NOT NULL)
  FROM `nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date BETWEEN @start_date AND @end_date
  GROUP BY analysis_date

  UNION ALL

  SELECT
    'Phase4_PCF',
    game_date,
    COUNT(*),
    COUNTIF(opponent_strength_score > 0)
  FROM `nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
)
SELECT
  stage,
  check_date,
  total,
  valid,
  ROUND(100.0 * valid / NULLIF(total, 0), 1) as valid_pct,
  CASE
    WHEN valid = 0 THEN 'CONTAMINATED'
    WHEN valid < total THEN 'PARTIAL'
    ELSE 'CLEAN'
  END as status
FROM validation
WHERE valid < total  -- Only show problem dates
ORDER BY stage, check_date;
```

### 2.2 Contamination Status Levels

| Status | Definition | Action |
|--------|------------|--------|
| **CLEAN** | 100% of records have valid critical fields | None |
| **PARTIAL** | Some records have invalid values | Investigate |
| **CONTAMINATED** | 0% valid or >90% invalid | Reprocess required |

### 2.3 Quick Health Check Commands

```bash
# Check Phase 3 paint data
bq query --use_legacy_sql=false '
SELECT game_date,
       COUNT(*) as total,
       COUNTIF(opp_paint_attempts > 0) as with_paint
FROM nba_analytics.team_defense_game_summary
WHERE game_date BETWEEN "2021-12-01" AND "2021-12-31"
GROUP BY 1 ORDER BY 1'

# Check Phase 4 TDZA
bq query --use_legacy_sql=false '
SELECT analysis_date,
       COUNT(*) as total,
       COUNTIF(paint_defense_vs_league_avg IS NOT NULL) as valid
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date BETWEEN "2021-12-01" AND "2021-12-31"
GROUP BY 1 ORDER BY 1'

# Check Phase 4 PCF
bq query --use_legacy_sql=false '
SELECT game_date,
       COUNT(*) as total,
       COUNTIF(opponent_strength_score > 0) as valid
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN "2021-12-01" AND "2021-12-31"
GROUP BY 1 ORDER BY 1'
```

---

## 3. Prevention Strategies

### 3.1 Three-Layer Defense

```
┌─────────────────────────────────────────────────────────────┐
│                    PREVENTION LAYERS                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: PRE-RUN VALIDATION (Prevent)                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Before processing, verify upstream critical fields   │   │
│  │ have valid data. Fail fast if contaminated.          │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                 │
│  Layer 2: POST-RUN VALIDATION (Detect)                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ After processing, verify output critical fields.     │   │
│  │ Alert and optionally halt if contamination found.    │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                 │
│  Layer 3: LINEAGE TRACKING (Trace)                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Record upstream state when downstream computed.      │   │
│  │ Enable staleness detection on future runs.           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Critical Fields Registry

| Table | Critical Fields | Valid Condition |
|-------|-----------------|-----------------|
| team_defense_game_summary | opp_paint_attempts | > 0 |
| team_defense_game_summary | opp_mid_range_attempts | > 0 |
| team_defense_zone_analysis | paint_defense_vs_league_avg | IS NOT NULL |
| team_defense_zone_analysis | mid_range_defense_vs_league_avg | IS NOT NULL |
| player_composite_factors | opponent_strength_score | > 0 |
| player_composite_factors | shot_zone_mismatch_score | IS NOT NULL |
| player_shot_zone_analysis | paint_fg_pct | IS NOT NULL |
| ml_feature_store_v2 | opponent_strength_score | > 0 |

### 3.3 Validation Mode Configuration

| Mode | Pre-run Check | Post-run Validation | Use Case |
|------|---------------|---------------------|----------|
| **strict** | FAIL on invalid | FAIL + ALERT | Production runs |
| **backfill** | WARN only | FAIL | Ordered backfills |
| **force** | SKIP | WARN | Emergency/testing |

```python
# Example configuration in processor
VALIDATION_CONFIG = {
    'mode': 'backfill',  # strict, backfill, or force
    'critical_fields': {
        'upstream': [
            ('team_defense_game_summary', 'opp_paint_attempts', '> 0'),
        ],
        'output': [
            ('paint_defense_vs_league_avg', 'IS NOT NULL'),
        ]
    }
}
```

---

## 4. Recovery Procedures

### 4.1 Recovery Flowchart

```
Contamination Detected
        │
        ▼
┌───────────────────┐
│ 1. IDENTIFY ROOT  │  Which upstream table/field is the source?
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 2. SCOPE IMPACT   │  Run cascade detection query
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 3. FIX UPSTREAM   │  Backfill the root cause table first
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 4. VALIDATE FIX   │  Verify upstream now has valid data
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 5. REPROCESS      │  Backfill downstream in dependency order
│    DOWNSTREAM     │  Validate after each stage
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 6. FINAL VERIFY   │  Run full pipeline health check
└───────────────────┘
```

### 4.2 Backfill Order (Critical!)

```bash
# Always process in dependency order:

# 1. Phase 3 - Fix root cause
team_defense_game_summary  # Shot zone data

# 2. Phase 4 - Layer 1 (can parallel)
├── team_defense_zone_analysis (TDZA)  # Uses TDGS
└── player_shot_zone_analysis (PSZA)   # Independent

# 3. Phase 4 - Layer 2 (sequential)
├── player_daily_cache (PDC)           # Uses PSZA
└── player_composite_factors (PCF)     # Uses TDZA, PSZA

# 4. Phase 5
└── ml_feature_store (MLFS)            # Uses PCF, PDC
```

### 4.3 Validation Gates

After each backfill stage, run validation before proceeding:

```bash
# After Phase 3
validate_critical_fields "team_defense_game_summary" "2021-12-01" "2021-12-31"
# Expected: opp_paint_attempts > 0 for all records

# After TDZA
validate_critical_fields "team_defense_zone_analysis" "2021-12-01" "2021-12-31"
# Expected: paint_defense_vs_league_avg IS NOT NULL

# After PCF
validate_critical_fields "player_composite_factors" "2021-12-01" "2021-12-31"
# Expected: opponent_strength_score > 0
```

---

## 5. Implementation Plan

### 5.1 Phase 1: Validation Functions (Immediate)

Add to `shared/validation/critical_fields.py`:

```python
CRITICAL_FIELDS = {
    'team_defense_game_summary': [
        ('opp_paint_attempts', '> 0', 'Shot zone paint data'),
        ('opp_mid_range_attempts', '> 0', 'Shot zone mid-range data'),
    ],
    'team_defense_zone_analysis': [
        ('paint_defense_vs_league_avg', 'IS NOT NULL', 'Paint defense metric'),
    ],
    'player_composite_factors': [
        ('opponent_strength_score', '> 0', 'Opponent strength calculation'),
    ],
}

def validate_critical_fields(table: str, start_date: str, end_date: str) -> dict:
    """
    Validate critical fields for a table and date range.

    Returns:
        {
            'status': 'CLEAN' | 'PARTIAL' | 'CONTAMINATED',
            'total_records': int,
            'valid_records': int,
            'invalid_dates': list[str],
            'details': dict
        }
    """
    pass
```

### 5.2 Phase 2: Pre-run Checks (Short-term)

Add to processor base class:

```python
def validate_upstream_before_processing(self, analysis_date: str) -> bool:
    """Check upstream critical fields before processing."""
    for dep_table, fields in self.UPSTREAM_CRITICAL_FIELDS.items():
        for field, condition, desc in fields:
            if not self._check_field(dep_table, field, condition, analysis_date):
                if self.validation_mode == 'strict':
                    raise CascadeContaminationError(
                        f"Upstream {dep_table}.{field} fails {condition}"
                    )
                else:
                    logger.warning(f"⚠️ Upstream contamination: {dep_table}.{field}")
    return True
```

### 5.3 Phase 3: Post-run Validation (Short-term)

Add to processor base class:

```python
def validate_output_after_processing(self, analysis_date: str, results: list) -> bool:
    """Validate output critical fields after processing."""
    for field, condition, desc in self.OUTPUT_CRITICAL_FIELDS:
        valid_count = sum(1 for r in results if self._eval_condition(r, field, condition))
        valid_pct = valid_count / len(results) * 100 if results else 0

        if valid_pct < 10:  # >90% invalid = CONTAMINATED
            logger.error(f"❌ Output contaminated: {field} only {valid_pct:.1f}% valid")
            if self.validation_mode in ['strict', 'backfill']:
                raise CascadeContaminationError(f"Output {field} contaminated")
        elif valid_pct < 100:
            logger.warning(f"⚠️ Partial contamination: {field} {valid_pct:.1f}% valid")

    return True
```

### 5.4 Phase 4: Lineage Tracking (Medium-term)

Add lightweight tracking fields:

```python
# Store with each downstream record
lineage_fields = {
    'upstream_validated_at': datetime.utcnow(),
    'upstream_tdza_count': len(tdza_data),
    'upstream_tdza_valid_pct': calc_valid_pct(tdza_data, 'paint_defense_vs_league_avg'),
}
```

---

## 6. Efficiency Considerations

### 6.1 Query Efficiency

| Check Type | Overhead | Strategy |
|------------|----------|----------|
| Pre-run upstream | ~1-2s per table | Single COUNT query |
| Post-run output | ~0s (in-memory) | Validate before BQ write |
| Lineage tracking | ~0.1s | Compute during processing |

### 6.2 Efficient Validation Query Pattern

```sql
-- DO: Single aggregation query
SELECT
  COUNT(*) as total,
  COUNTIF(field IS NOT NULL AND field > 0) as valid
FROM table
WHERE date = @date

-- DON'T: Per-record queries
SELECT * FROM table WHERE date = @date  -- Then validate in Python
```

### 6.3 Batch Validation

Validate entire date range in one query rather than per-date:

```sql
-- Efficient: One query for all dates
SELECT game_date, COUNT(*), COUNTIF(field > 0)
FROM table
WHERE game_date BETWEEN @start AND @end
GROUP BY game_date
HAVING COUNTIF(field > 0) < COUNT(*)  -- Only return problem dates
```

---

## 7. Quick Reference

### Contamination Detection Command

```bash
# Run full pipeline health check
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-12-01 \
    --end-date 2021-12-31
```

### Expected Output

```
Pipeline Contamination Check: 2021-12-01 to 2021-12-31
═══════════════════════════════════════════════════════

Phase 3: team_defense_game_summary
  ├── opp_paint_attempts: CONTAMINATED (0% valid)
  └── Status: REPROCESS REQUIRED

Phase 4: team_defense_zone_analysis
  ├── paint_defense_vs_league_avg: CONTAMINATED (0% valid)
  └── Status: REPROCESS REQUIRED (after Phase 3)

Phase 4: player_composite_factors
  ├── opponent_strength_score: CONTAMINATED (0% valid)
  └── Status: REPROCESS REQUIRED (after TDZA)

Recommended Recovery:
1. Run: team_defense_game_summary backfill
2. Validate: opp_paint_attempts > 0
3. Run: team_defense_zone_analysis backfill
4. Validate: paint_defense_vs_league_avg IS NOT NULL
5. Run: player_composite_factors backfill
6. Validate: opponent_strength_score > 0
```

---

## Appendix A: Error Classes

```python
class CascadeContaminationError(Exception):
    """Raised when cascade contamination is detected."""

    def __init__(self, message: str, table: str = None, field: str = None,
                 date: str = None, valid_pct: float = None):
        self.table = table
        self.field = field
        self.date = date
        self.valid_pct = valid_pct
        super().__init__(message)
```

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **Cascade Contamination** | Invalid data propagating through pipeline layers |
| **Critical Field** | A field that must have valid values for downstream to work |
| **Contaminated** | >90% of records have invalid critical field values |
| **Validation Gate** | Check point between pipeline stages |
| **Lineage Tracking** | Recording upstream state when downstream computed |

---

*Last updated: 2025-12-08*
