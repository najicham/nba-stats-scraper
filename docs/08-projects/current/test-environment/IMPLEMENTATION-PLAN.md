# Test Environment Implementation Plan

## Overview

This document outlines the step-by-step implementation of the Pipeline Replay System.

**Total Estimated Effort**: 10-13 hours

## Phase 1: Dataset Prefix Support (2-3 hours)

### 1.1 Raw Processor Base

**File**: `data_processors/raw/processor_base.py`

```python
# Add at top of file (after imports)
DATASET_PREFIX = os.environ.get('DATASET_PREFIX', '')

# Modify __init__ or class definition
class ProcessorBase:
    dataset_id: str = f"{DATASET_PREFIX}nba_source"  # Was: "nba_source"
```

### 1.2 Analytics Processor Base

**File**: `data_processors/analytics/analytics_base.py`

```python
DATASET_PREFIX = os.environ.get('DATASET_PREFIX', '')

class AnalyticsProcessorBase:
    dataset_id: str = f"{DATASET_PREFIX}nba_analytics"  # Was: "nba_analytics"
```

### 1.3 Precompute Processor Base

**File**: `data_processors/precompute/precompute_base.py`

Same pattern as above.

### 1.4 Predictions

**Files**:
- `predictions/coordinator/coordinator.py`
- `predictions/worker/worker.py`
- `predictions/worker/data_loaders.py`

```python
DATASET_PREFIX = os.environ.get('DATASET_PREFIX', '')

# Update all dataset references
PREDICTIONS_DATASET = f"{DATASET_PREFIX}nba_predictions"
ANALYTICS_DATASET = f"{DATASET_PREFIX}nba_analytics"
```

### 1.5 Exporters

**File**: `publishing/exporters/base_exporter.py`

```python
DATASET_PREFIX = os.environ.get('DATASET_PREFIX', '')
GCS_PREFIX = os.environ.get('GCS_PREFIX', '')

# Update dataset and path references
```

### Verification

```bash
# Test that prefix works
DATASET_PREFIX=test_ python -c "
from data_processors.analytics.analytics_base import AnalyticsProcessorBase
print(AnalyticsProcessorBase.dataset_id)  # Should print: test_nba_analytics
"
```

## Phase 2: Test Dataset Setup (1 hour)

### 2.1 Create Setup Script

**File**: `bin/testing/setup_test_datasets.sh`

```bash
#!/bin/bash
set -e

PROJECT_ID=${GCP_PROJECT_ID:-nba-props-platform}
PREFIX=${1:-test_}

echo "Creating test datasets with prefix: $PREFIX"

# Create datasets
for dataset in nba_source nba_analytics nba_predictions nba_precompute; do
    bq mk --dataset \
        --default_table_expiration 604800 \
        --description "Test dataset - auto-expires in 7 days" \
        ${PROJECT_ID}:${PREFIX}${dataset} 2>/dev/null || echo "Dataset ${PREFIX}${dataset} already exists"
done

echo "Test datasets created successfully"
```

### 2.2 Verify

```bash
chmod +x bin/testing/setup_test_datasets.sh
./bin/testing/setup_test_datasets.sh
```

## Phase 3: Replay Script (3-4 hours)

### 3.1 Main Replay Script

**File**: `bin/testing/replay_pipeline.sh`

```bash
#!/bin/bash
set -e

# Parse arguments
REPLAY_DATE=${1:-$(date -d "yesterday" +%Y-%m-%d)}
DATASET_PREFIX=${2:-test_}
DRY_RUN=false
START_PHASE=2

for arg in "$@"; do
    case $arg in
        --dry-run) DRY_RUN=true ;;
        --start-phase=*) START_PHASE="${arg#*=}" ;;
    esac
done

echo "=========================================="
echo "  PIPELINE REPLAY"
echo "  Date: $REPLAY_DATE"
echo "  Prefix: $DATASET_PREFIX"
echo "  Dry Run: $DRY_RUN"
echo "=========================================="

# Set environment
export DATASET_PREFIX=$DATASET_PREFIX
export GCS_PREFIX="test/"
export FIRESTORE_PREFIX="test_"

cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Timing array
declare -A TIMINGS

run_phase() {
    local phase=$1
    local name=$2
    local cmd=$3

    if [ "$phase" -lt "$START_PHASE" ]; then
        echo "⏭️  Skipping Phase $phase: $name"
        return
    fi

    echo ""
    echo "▶️  Phase $phase: $name"
    local start=$(date +%s)

    if [ "$DRY_RUN" = true ]; then
        echo "   [DRY RUN] Would execute: $cmd"
    else
        eval "$cmd"
    fi

    local end=$(date +%s)
    local duration=$((end - start))
    TIMINGS[$name]=$duration
    echo "✅ Phase $phase complete: ${duration}s"
}

# Run phases
run_phase 2 "Raw Processing" \
    "PYTHONPATH=. python -m data_processors.raw.run_all --date $REPLAY_DATE"

run_phase 3 "Analytics" \
    "PYTHONPATH=. python -m data_processors.analytics.run_all --date $REPLAY_DATE"

run_phase 4 "Precompute" \
    "PYTHONPATH=. python -m data_processors.precompute.run_all --date $REPLAY_DATE"

run_phase 5 "Predictions" \
    "PYTHONPATH=. python -m predictions.coordinator.run_local --date $REPLAY_DATE"

run_phase 6 "Export" \
    "PYTHONPATH=. python -m publishing.exporters.run_all --date $REPLAY_DATE"

# Summary
echo ""
echo "=========================================="
echo "  TIMING SUMMARY"
echo "=========================================="
total=0
for phase in "${!TIMINGS[@]}"; do
    echo "  $phase: ${TIMINGS[$phase]}s"
    total=$((total + TIMINGS[$phase]))
done
echo "  ────────────────"
echo "  Total: ${total}s ($(($total / 60))m $(($total % 60))s)"

# Validation
if [ "$DRY_RUN" = false ]; then
    echo ""
    echo "=========================================="
    echo "  VALIDATION"
    echo "=========================================="
    python bin/testing/validate_replay.py --date $REPLAY_DATE --prefix $DATASET_PREFIX
fi
```

### 3.2 Local Coordinator Runner

**File**: `predictions/coordinator/run_local.py`

```python
#!/usr/bin/env python3
"""Run predictions locally without Pub/Sub."""

import argparse
import os
from datetime import datetime
from coordinator import PredictionCoordinator

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    args = parser.parse_args()

    # Run coordinator in local mode
    coordinator = PredictionCoordinator(local_mode=True)
    coordinator.run_for_date(args.date)

if __name__ == '__main__':
    main()
```

## Phase 4: Validation Framework (2-3 hours)

### 4.1 Validation Script

**File**: `bin/testing/validate_replay.py`

```python
#!/usr/bin/env python3
"""Validate replay outputs."""

import argparse
from google.cloud import bigquery

class ReplayValidator:
    def __init__(self, date: str, prefix: str):
        self.date = date
        self.prefix = prefix
        self.bq = bigquery.Client()
        self.results = {}

    def validate(self):
        self.check_predictions()
        self.check_analytics()
        self.check_duplicates()
        self.print_report()

    def check_predictions(self):
        query = f"""
        SELECT
            COUNT(*) as count,
            COUNT(DISTINCT game_id) as games
        FROM `{self.prefix}nba_predictions.player_prop_predictions`
        WHERE game_date = '{self.date}'
        """
        result = list(self.bq.query(query).result())[0]
        self.results['predictions'] = {
            'count': result.count,
            'games': result.games,
            'pass': result.count >= 400
        }

    def check_analytics(self):
        tables = ['player_game_summary', 'team_defense_game_summary']
        self.results['analytics'] = {}
        for table in tables:
            query = f"""
            SELECT COUNT(*) as count
            FROM `{self.prefix}nba_analytics.{table}`
            WHERE game_date = '{self.date}'
            """
            result = list(self.bq.query(query).result())[0]
            self.results['analytics'][table] = result.count

    def check_duplicates(self):
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT CONCAT(game_id, player_id, stat_type, system_id)) as unique_count
        FROM `{self.prefix}nba_predictions.player_prop_predictions`
        WHERE game_date = '{self.date}'
        """
        result = list(self.bq.query(query).result())[0]
        self.results['duplicates'] = {
            'total': result.total,
            'unique': result.unique_count,
            'has_duplicates': result.total != result.unique_count
        }

    def print_report(self):
        print("\n=== REPLAY VALIDATION REPORT ===")
        print(f"Date: {self.date}")
        print(f"Prefix: {self.prefix}")

        pred = self.results['predictions']
        dup = self.results['duplicates']

        print(f"\nPREDICTIONS:")
        print(f"  {'✓' if pred['pass'] else '✗'} Count: {pred['count']} (minimum: 400)")
        print(f"  {'✓' if not dup['has_duplicates'] else '✗'} Unique: {dup['unique']} (no duplicates)")
        print(f"  Games covered: {pred['games']}")

        print(f"\nANALYTICS:")
        for table, count in self.results['analytics'].items():
            print(f"  {'✓' if count > 0 else '✗'} {table}: {count} records")

        all_pass = pred['pass'] and not dup['has_duplicates']
        print(f"\nSTATUS: {'PASSED' if all_pass else 'FAILED'}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    parser.add_argument('--prefix', default='test_')
    args = parser.parse_args()

    validator = ReplayValidator(args.date, args.prefix)
    validator.validate()

if __name__ == '__main__':
    main()
```

## Phase 5: Documentation & Testing (1 hour)

### 5.1 Test the Full Flow

```bash
# 1. Set up test datasets
./bin/testing/setup_test_datasets.sh

# 2. Run dry run first
./bin/testing/replay_pipeline.sh 2024-12-15 test_ --dry-run

# 3. Run actual replay
./bin/testing/replay_pipeline.sh 2024-12-15

# 4. Verify results
bq query "SELECT COUNT(*) FROM test_nba_predictions.player_prop_predictions WHERE game_date = '2024-12-15'"
```

### 5.2 Update README

Add to main project README:
```markdown
## Testing

See [Test Environment Documentation](docs/08-projects/current/test-environment/README.md) for running pipeline replays.
```

## Implementation Checklist

- [ ] Phase 1.1: Raw processor prefix support
- [ ] Phase 1.2: Analytics processor prefix support
- [ ] Phase 1.3: Precompute processor prefix support
- [ ] Phase 1.4: Predictions prefix support
- [ ] Phase 1.5: Exporters prefix support
- [ ] Phase 2.1: Dataset setup script
- [ ] Phase 3.1: Main replay script
- [ ] Phase 3.2: Local coordinator runner
- [ ] Phase 4.1: Validation framework
- [ ] Phase 5.1: End-to-end test
- [ ] Phase 5.2: Documentation updates

## Success Criteria

1. Can run full pipeline replay for any date
2. Test data isolated in `test_*` datasets
3. Timing reported for each phase
4. Validation catches common issues
5. Clear documentation for users
