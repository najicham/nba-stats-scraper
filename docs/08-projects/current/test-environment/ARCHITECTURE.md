# Test Environment Architecture

## Design Philosophy

### Why Local Replay Over Cloud Replay?

The production pipeline uses Pub/Sub and Cloud Functions for **reliability and event-driven processing**. But for testing, we need:

1. **Speed**: Direct function calls are 10-100x faster than Pub/Sub roundtrips
2. **Control**: Can pause, inspect, and debug at any point
3. **Repeatability**: Same inputs always produce same outputs
4. **Cost**: No cloud function invocations or Pub/Sub messages

The cloud orchestration is **glue code** - simple message passing. Bugs occur in the **processor logic**, which we test fully.

### What We're Testing

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRODUCTION PIPELINE                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Pub/Sub  │───▶│ Cloud Fn │───▶│ Pub/Sub  │───▶│ Cloud Fn │  │
│  │ Message  │    │ Trigger  │    │ Message  │    │ Trigger  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │              │                │              │          │
│       │              ▼                │              ▼          │
│       │         ┌────────────────────────────────────────┐      │
│       │         │         PROCESSOR LOGIC                │      │
│       └────────▶│  (BigQuery queries, transformations,   │◀─────┘
│                 │   data validation, exports)            │      │
│                 └────────────────────────────────────────┘      │
│                              │                                  │
│                              ▼                                  │
│                 ┌────────────────────────────────────────┐      │
│                 │      BigQuery / GCS / Firestore        │      │
│                 └────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘

                              │
                              │ REPLAY TESTS THIS
                              ▼

┌─────────────────────────────────────────────────────────────────┐
│                      REPLAY PIPELINE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              DIRECT PROCESSOR CALLS                       │  │
│  │  (Same code, same logic, no Pub/Sub overhead)            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         TEST BigQuery / GCS (with prefix)                 │  │
│  │  test_nba_analytics.player_game_summary                   │  │
│  │  gs://bucket/test/exports/...                             │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Component Design

### 1. Dataset Prefix System

**Goal**: Route all BigQuery writes to test datasets without code changes.

**Implementation**:
```python
# In processor base classes
DATASET_PREFIX = os.environ.get('DATASET_PREFIX', '')

class ProcessorBase:
    def __init__(self):
        self.dataset_id = f"{DATASET_PREFIX}nba_analytics"
```

**Files to modify**:
- `data_processors/raw/processor_base.py` - Line ~85
- `data_processors/analytics/analytics_base.py` - Line ~81
- `data_processors/precompute/precompute_base.py` - Similar
- `predictions/coordinator/coordinator.py` - Dataset refs
- `predictions/worker/worker.py` - Dataset refs
- `publishing/exporters/base_exporter.py` - Dataset refs

**Resulting datasets**:
| Production | Test (prefix=`test_`) |
|------------|----------------------|
| `nba_source` | `test_nba_source` |
| `nba_analytics` | `test_nba_analytics` |
| `nba_predictions` | `test_nba_predictions` |

### 2. GCS Path Prefix

**Goal**: Separate test exports from production.

**Implementation**:
```python
GCS_PREFIX = os.environ.get('GCS_PREFIX', '')
export_path = f"{GCS_PREFIX}exports/{date}/{filename}"
```

**Resulting paths**:
| Production | Test (prefix=`test/`) |
|------------|----------------------|
| `gs://bucket/exports/2024-12-15/` | `gs://bucket/test/exports/2024-12-15/` |

### 3. Firestore Prefix (Optional)

For phase tracking during replay (if needed):
```python
FIRESTORE_PREFIX = os.environ.get('FIRESTORE_PREFIX', '')
collection = f"{FIRESTORE_PREFIX}phase2_completion"
```

**Note**: For local replay, we may skip Firestore entirely since we're calling processors directly.

### 4. Replay Orchestrator

**Goal**: Execute phases sequentially with timing and error capture.

```python
class PipelineReplay:
    def __init__(self, date: str, dataset_prefix: str = 'test_'):
        self.date = date
        self.prefix = dataset_prefix
        self.timings = {}
        self.errors = []

    def run(self):
        self.run_phase('phase2_raw', self.run_phase2)
        self.run_phase('phase3_analytics', self.run_phase3)
        self.run_phase('phase4_precompute', self.run_phase4)
        self.run_phase('phase5_predictions', self.run_phase5)
        self.run_phase('phase6_export', self.run_phase6)

        return self.generate_report()

    def run_phase(self, name, func):
        start = time.time()
        try:
            func()
        except Exception as e:
            self.errors.append({'phase': name, 'error': str(e)})
            raise
        finally:
            self.timings[name] = time.time() - start
```

### 5. Validation Framework

**Post-replay validation checks**:

```python
class ReplayValidator:
    def validate(self, date: str, prefix: str) -> ValidationReport:
        return ValidationReport(
            predictions=self.check_predictions(date, prefix),
            analytics=self.check_analytics(date, prefix),
            exports=self.check_exports(date, prefix),
            duplicates=self.check_duplicates(date, prefix),
            completeness=self.check_completeness(date, prefix)
        )

    def check_predictions(self, date, prefix):
        query = f"""
        SELECT COUNT(*) as count,
               COUNT(DISTINCT CONCAT(game_id, player_id, stat_type)) as unique_count
        FROM `{prefix}nba_predictions.player_prop_predictions`
        WHERE game_date = '{date}'
        """
        result = self.bq.query(query).result()
        row = list(result)[0]
        return {
            'count': row.count,
            'unique_count': row.unique_count,
            'has_duplicates': row.count != row.unique_count,
            'meets_minimum': row.count >= 400  # Typical game day minimum
        }
```

## Performance Thresholds

Based on production baselines, alert if replay exceeds:

| Phase | Threshold | Critical |
|-------|-----------|----------|
| Phase 2 (Raw) | 5 min | 10 min |
| Phase 3 (Analytics) | 10 min | 20 min |
| Phase 4 (Precompute) | 10 min | 20 min |
| Phase 5 (Predictions) | 15 min | 30 min |
| Phase 6 (Export) | 5 min | 10 min |
| **Total Pipeline** | **45 min** | **90 min** |

## Error Categories

The replay system categorizes errors for actionability:

| Category | Example | Action |
|----------|---------|--------|
| **Data Missing** | No GCS files for date | Check scrapers ran |
| **Query Failed** | BigQuery timeout | Check query efficiency |
| **Validation Failed** | Zero predictions | Check processor logic |
| **Threshold Exceeded** | Phase 3 took 25 min | Performance regression |

## Comparison with Production

After replay, compare outputs:

```python
def compare_with_production(date: str, prefix: str):
    """Compare test outputs with production for same date."""

    prod_predictions = query(f"SELECT * FROM nba_predictions.* WHERE date='{date}'")
    test_predictions = query(f"SELECT * FROM {prefix}nba_predictions.* WHERE date='{date}'")

    return {
        'count_match': len(prod_predictions) == len(test_predictions),
        'values_match': compare_values(prod_predictions, test_predictions),
        'differences': find_differences(prod_predictions, test_predictions)
    }
```

## Future Enhancements

1. **CI Integration**: Run replay on every PR with reduced date range
2. **Benchmark Database**: Store historical replay timings for trend analysis
3. **Parallel Execution**: Run multiple dates concurrently for load testing
4. **Failure Injection**: Test error handling by injecting failures
5. **Data Subset Mode**: Replay with subset of players for faster iteration
