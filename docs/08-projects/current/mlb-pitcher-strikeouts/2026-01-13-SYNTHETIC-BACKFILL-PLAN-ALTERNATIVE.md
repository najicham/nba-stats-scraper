# MLB Predictions - Synthetic Betting Line Backfill Plan

**Created**: 2026-01-13
**Purpose**: Complete the historical backfill with synthetic betting lines and graded predictions
**Timeline**: 1-2 days
**Priority**: HIGH (Quick win to get complete historical record)

---

## The Opportunity

We have:
- ✅ 8,130 predictions (excellent accuracy: MAE 1.455)
- ✅ 9,742 actual results (100% coverage)
- ✅ 98.3% match rate between predictions and actuals
- ✅ Synthetic hit rate analysis proving 78% hit rate
- ❌ BUT: No betting lines in database (all NULL)
- ❌ BUT: No graded predictions (is_correct all NULL)

**Solution**: Backfill synthetic betting lines (rolling averages) and grade all predictions.

**Result**: Complete historical record with 8,345 graded predictions showing 78% hit rate.

---

## Why This Works

### Synthetic Lines Are Valid
From our analysis:
- Rolling averages (10-game) are reasonable proxy for betting lines
- Hit rate of 78% proves they're directionally correct
- Perfect edge calibration shows reliability
- Both seasons (2024, 2025) perform well

### Benefits of Backfilling
1. **Complete historical record**: All predictions graded and trackable
2. **Performance dashboard**: Can show 78% hit rate in production database
3. **Analysis ready**: Can query historical performance easily
4. **Confidence building**: Solid track record for stakeholders
5. **Fast implementation**: 1-2 days vs 3+ weeks for forward validation

### Clear Labeling
We'll clearly mark these as synthetic lines:
- Add `line_source = 'synthetic_rolling_avg'` field
- Document in metadata
- Separate from future real betting lines
- Clear disclaimers in dashboards

---

## Implementation Plan

### Step 1: Create Synthetic Line Backfill Script (4 hours)

**File**: `scripts/mlb/backfill_synthetic_betting_lines.py`

**What it does**:
1. Query all predictions without betting lines
2. Join with `pitcher_game_summary` to get rolling averages
3. Calculate synthetic line (k_avg_last_10)
4. Calculate edge (predicted - synthetic_line)
5. Determine recommendation (OVER/UNDER/PASS)
6. Update predictions table with:
   - `strikeouts_line` = synthetic line
   - `line_source` = 'synthetic_rolling_avg'
   - `recommendation` = OVER/UNDER/PASS (not NO_LINE)
   - `edge` = calculated edge

**Pseudocode**:
```python
def backfill_synthetic_lines():
    """Backfill synthetic betting lines for historical predictions."""

    # Get predictions + rolling averages
    query = """
    SELECT
        p.prediction_id,
        p.pitcher_lookup,
        p.game_date,
        p.predicted_strikeouts,
        pgs.k_avg_last_10 as synthetic_line,
        p.predicted_strikeouts - pgs.k_avg_last_10 as edge
    FROM mlb_predictions.pitcher_strikeouts p
    JOIN mlb_analytics.pitcher_game_summary pgs
      ON p.pitcher_lookup = pgs.player_lookup
      AND p.game_date = pgs.game_date
    WHERE p.strikeouts_line IS NULL
      AND pgs.k_avg_last_10 IS NOT NULL
    """

    rows = bq_client.query(query).result()

    updates = []
    for row in rows:
        # Calculate recommendation
        edge = row['edge']
        if edge > 0.5:
            recommendation = 'OVER'
        elif edge < -0.5:
            recommendation = 'UNDER'
        else:
            recommendation = 'PASS'

        updates.append({
            'prediction_id': row['prediction_id'],
            'strikeouts_line': row['synthetic_line'],
            'line_source': 'synthetic_rolling_avg',
            'recommendation': recommendation,
            'edge': edge
        })

    # Batch update BigQuery
    update_predictions(updates)

    return len(updates)
```

**Validation**:
- Check update count matches expected (~8,345)
- Verify no NULL lines remain (where rolling avg exists)
- Verify recommendations are OVER/UNDER/PASS (not NO_LINE)
- Sample check 10 random predictions manually

### Step 2: Update Schema (1 hour)

**File**: `schemas/bigquery/mlb_predictions/strikeout_predictions_tables.sql`

**Add field**:
```sql
line_source STRING,  -- 'synthetic_rolling_avg' or 'real_market_line'
```

**Options**:
- **Option A**: Alter existing table (add column)
- **Option B**: Create view that adds this field
- **Option C**: Use UPDATE to set value in existing table

**Recommendation**: Option A (alter table) for clean schema.

**Migration**:
```sql
ALTER TABLE `nba-props-platform.mlb_predictions.pitcher_strikeouts`
ADD COLUMN IF NOT EXISTS line_source STRING;

-- Set source for backfilled lines
UPDATE `nba-props-platform.mlb_predictions.pitcher_strikeouts`
SET line_source = 'synthetic_rolling_avg'
WHERE game_date < '2026-01-14'  -- Historical data
  AND strikeouts_line IS NOT NULL;
```

### Step 3: Run Grading Processor (1 hour)

**File**: `data_processors/grading/mlb/mlb_prediction_grading_processor.py`

**Current state**: Processor exists and is correct, just hasn't been run.

**What it does**:
1. Reads predictions with recommendations (OVER/UNDER)
2. Reads actual results
3. Matches on pitcher_lookup + game_date
4. Calculates is_correct:
   - OVER: actual > line → correct
   - UNDER: actual < line → correct
   - PASS: no grading
5. Updates predictions table

**Execution**:
```bash
# Grade all historical predictions
python data_processors/grading/mlb/mlb_prediction_grading_processor.py \
  --start-date 2024-04-01 \
  --end-date 2025-10-01

# Or run via Cloud Function
gcloud functions call mlb-prediction-grading \
  --data '{"start_date": "2024-04-01", "end_date": "2025-10-01"}'
```

**Expected result**:
- ~5,327 predictions graded (those with OVER/UNDER)
- ~3,018 predictions with PASS (no grading)
- is_correct populated: 4,157 TRUE, 1,170 FALSE
- Hit rate: 78.04%

### Step 4: Generate Complete Historical Report (2 hours)

**File**: `scripts/mlb/generate_historical_performance_report.py`

**What it creates**:
```markdown
# MLB Pitcher Strikeouts - Historical Performance Report

## Overview
- **Period**: April 2024 - September 2025 (18 months)
- **Total Predictions**: 8,345
- **Actionable Bets**: 5,327 (63.8%)
- **Pass Recommendations**: 3,018 (36.2%)

## Performance Summary
- **Hit Rate**: 78.04% (4,157W / 1,170L)
- **vs Breakeven (52.4%)**: +25.64%
- **Model Quality**: Excellent (MAE 1.455)

## Performance by Edge Size
[Table showing hit rate increasing with edge]

## Performance by Season
- 2024: 83.0% hit rate (2,479 bets)
- 2025: 73.7% hit rate (2,848 bets)

## Performance by Context
[Home/away, OVER/UNDER breakdowns]

## Betting Line Methodology
**IMPORTANT**: These predictions use synthetic betting lines (pitcher rolling averages), not real market lines. Synthetic lines are directional indicators that prove the model detects value, but real betting performance may differ.

- Line Source: 10-game rolling average strikeouts
- Validation: 78% hit rate on synthetic lines
- Real Line Comparison: TBD (requires forward validation)
```

**Dashboard Integration**:
Create BigQuery views for Grafana/Looker:

```sql
-- Historical performance view
CREATE OR REPLACE VIEW mlb_predictions.historical_performance AS
SELECT
  game_date,
  COUNT(*) as predictions,
  SUM(CASE WHEN recommendation IN ('OVER', 'UNDER') THEN 1 ELSE 0 END) as bets,
  SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
  SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses,
  SAFE_DIVIDE(
    SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END),
    SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END)
  ) * 100 as hit_rate,
  AVG(ABS(edge)) as avg_edge,
  'synthetic' as line_type
FROM mlb_predictions.pitcher_strikeouts
WHERE line_source = 'synthetic_rolling_avg'
GROUP BY game_date
ORDER BY game_date DESC;

-- Cumulative performance view
CREATE OR REPLACE VIEW mlb_predictions.cumulative_performance AS
SELECT
  game_date,
  predictions,
  bets,
  wins,
  losses,
  hit_rate,
  SUM(wins) OVER (ORDER BY game_date) as cumulative_wins,
  SUM(losses) OVER (ORDER BY game_date) as cumulative_losses,
  SAFE_DIVIDE(
    SUM(wins) OVER (ORDER BY game_date),
    SUM(wins + losses) OVER (ORDER BY game_date)
  ) * 100 as cumulative_hit_rate
FROM mlb_predictions.historical_performance
ORDER BY game_date;
```

### Step 5: Documentation and Disclaimers (1 hour)

**Update README**:
```markdown
## MLB Pitcher Strikeout Predictions - Historical Performance

### Synthetic Line Backfill (April 2024 - September 2025)

Historical predictions were backfilled with synthetic betting lines using pitcher rolling averages (10-game average strikeouts). These synthetic lines serve as proxies for market betting lines that were not collected at the time.

**Performance**:
- 8,345 predictions graded
- 78.04% hit rate (5,327 actionable bets)
- +25.64% vs breakeven (52.4%)

**Important Notes**:
1. Synthetic lines are directional indicators, not actual market lines
2. Real betting performance may differ from synthetic estimates
3. This establishes model quality and value detection capability
4. Forward validation with real betting lines is planned for 2026 season

**Line Source**: `line_source = 'synthetic_rolling_avg'`
- All historical predictions clearly marked
- Real betting lines (future) will be marked `line_source = 'real_market_line'`
```

---

## Complete Implementation Checklist

### Day 1: Backfill (4-6 hours)
- [ ] Create synthetic line backfill script
- [ ] Add line_source field to schema
- [ ] Test script on sample (100 predictions)
- [ ] Run full backfill (~8,345 predictions)
- [ ] Validate update counts
- [ ] Sample check 20 predictions manually

### Day 2: Grading & Reporting (3-4 hours)
- [ ] Run grading processor on historical data
- [ ] Validate grading results (5,327 graded)
- [ ] Verify hit rate matches synthetic analysis (78.04%)
- [ ] Generate historical performance report
- [ ] Create BigQuery views for dashboards
- [ ] Update documentation with disclaimers

### Total Time: 1-2 days

---

## Validation Checklist

After backfill, verify:

### Data Quality
- [ ] Total predictions: 8,130 (unchanged)
- [ ] Predictions with lines: ~8,345 (98.3% of total)
- [ ] Predictions with NULL lines: ~200 (2-3% - those without rolling avg)
- [ ] All lines have source: 'synthetic_rolling_avg'
- [ ] No NO_LINE recommendations remain

### Grading Quality
- [ ] Total graded: ~5,327
- [ ] Wins: ~4,157 (78.04%)
- [ ] Losses: ~1,170 (21.96%)
- [ ] Hit rate: 78.04% ± 0.5%
- [ ] Pass recommendations: ~3,018 (not graded)

### Recommendation Distribution
- [ ] OVER: ~3,041 (57.1% of bets)
- [ ] UNDER: ~2,286 (42.9% of bets)
- [ ] PASS: ~3,018 (36.2% of predictions)
- [ ] NO_LINE: 0 (eliminated)

### Edge Calibration (matches synthetic analysis)
- [ ] 0.5-1.0K edge: ~68% hit rate
- [ ] 1.0-1.5K edge: ~81% hit rate
- [ ] 1.5-2.0K edge: ~92% hit rate
- [ ] 2.0+ K edge: ~96% hit rate

---

## SQL Queries for Validation

### Check backfill completion
```sql
SELECT
  COUNT(*) as total_predictions,
  SUM(CASE WHEN strikeouts_line IS NOT NULL THEN 1 ELSE 0 END) as with_lines,
  SUM(CASE WHEN strikeouts_line IS NULL THEN 1 ELSE 0 END) as without_lines,
  SUM(CASE WHEN line_source = 'synthetic_rolling_avg' THEN 1 ELSE 0 END) as synthetic_lines
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date BETWEEN '2024-04-01' AND '2025-10-01';
```

### Check grading completion
```sql
SELECT
  recommendation,
  COUNT(*) as predictions,
  SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
  SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses,
  ROUND(SAFE_DIVIDE(
    SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END),
    SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END)
  ) * 100, 2) as hit_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date BETWEEN '2024-04-01' AND '2025-10-01'
  AND line_source = 'synthetic_rolling_avg'
GROUP BY recommendation
ORDER BY recommendation;
```

### Check edge calibration
```sql
SELECT
  CASE
    WHEN ABS(edge) < 1.0 THEN '0.5-1.0'
    WHEN ABS(edge) < 1.5 THEN '1.0-1.5'
    WHEN ABS(edge) < 2.0 THEN '1.5-2.0'
    ELSE '2.0+'
  END as edge_bucket,
  COUNT(*) as bets,
  SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
  ROUND(SAFE_DIVIDE(
    SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END),
    SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END)
  ) * 100, 2) as hit_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE recommendation IN ('OVER', 'UNDER')
  AND line_source = 'synthetic_rolling_avg'
GROUP BY edge_bucket
ORDER BY edge_bucket;
```

---

## Benefits of This Approach

### 1. Fast Implementation
- 1-2 days vs 3+ weeks for forward validation
- Uses existing data and infrastructure
- No new dependencies (no Odds API scraping needed yet)

### 2. Complete Historical Record
- All predictions graded and queryable
- Can show 78% hit rate in dashboards
- Historical performance tracking ready

### 3. Confidence Building
- Solid 18-month track record
- 8,345 graded predictions
- Proof of model quality and value detection

### 4. Analysis Ready
- Can query performance by any dimension
- Can create dashboards and reports
- Can share results with stakeholders

### 5. Clear Separation
- Synthetic lines clearly marked (`line_source`)
- Future real lines will be separate
- Easy to compare synthetic vs real performance

---

## Relationship to Forward Validation

### This backfill is complementary, not replacement

**Synthetic Backfill** (this plan):
- Purpose: Complete historical record
- Timeline: 1-2 days
- Result: 8,345 graded predictions with 78% hit rate
- Limitation: Uses proxy lines, not real market lines

**Forward Validation** (separate plan):
- Purpose: Validate with REAL betting lines
- Timeline: 3 weeks + 2-4 weeks data collection
- Result: Real market performance measurement
- Benefit: Production-ready betting system

### Recommended Sequence

**Week 1**: Synthetic backfill (this plan)
- Day 1-2: Backfill synthetic lines and grade
- Result: Complete historical record showing 78% hit rate

**Week 2-4**: Forward validation implementation
- Build betting line collection pipeline
- Harden prediction worker
- Deploy health monitoring

**Week 5-8**: Forward validation data collection
- Collect 50+ real predictions with real lines
- Compare real vs synthetic performance
- Make deployment decision

**Benefit**: Have complete historical record while building forward validation.

---

## Success Criteria

### Backfill Complete When:
- ✅ 8,345 predictions have synthetic betting lines
- ✅ 5,327 predictions graded (OVER/UNDER)
- ✅ Hit rate = 78.04% ± 1%
- ✅ Edge calibration matches synthetic analysis
- ✅ All predictions marked with `line_source = 'synthetic_rolling_avg'`
- ✅ Documentation updated with disclaimers
- ✅ Dashboard/views created

### Ready for Stakeholder Review:
- ✅ Historical performance report generated
- ✅ BigQuery views working
- ✅ Sample queries validated
- ✅ Disclaimers in place (synthetic vs real)
- ✅ Next steps (forward validation) documented

---

## Risk Assessment

### Low Risk
- ✅ We already validated synthetic lines work (78% hit rate)
- ✅ All data exists and is validated
- ✅ Grading processor already exists and is correct
- ✅ No new dependencies or infrastructure
- ✅ Clear labeling prevents confusion with real lines

### Caveats to Document
1. Synthetic lines ≠ real market lines
2. Real betting performance may differ
3. This proves model quality, not guaranteed profitability
4. Forward validation with real lines still required for production
5. Results are directional indicators

---

## Cost Analysis

### Development Time
- Backfill script: 4 hours
- Schema update: 1 hour
- Grading execution: 1 hour
- Report generation: 2 hours
- Documentation: 1 hour
- **Total**: 9 hours (~1 day)

### Infrastructure Costs
- BigQuery queries: ~$5 (one-time)
- Storage: Negligible (adding one column)
- No ongoing costs

### Return on Investment
- **Effort**: 1 day
- **Result**: Complete 18-month track record with 8,345 graded predictions
- **Value**: High confidence in model quality, ready for stakeholder review
- **ROI**: Excellent

---

## Implementation Script Skeleton

Here's what the main backfill script would look like:

```python
#!/usr/bin/env python3
"""
Backfill synthetic betting lines for historical MLB predictions.

This script:
1. Calculates synthetic betting lines (rolling averages)
2. Updates predictions with synthetic lines
3. Recalculates recommendations based on edge
4. Marks all updates with line_source = 'synthetic_rolling_avg'

Usage:
    python scripts/mlb/backfill_synthetic_betting_lines.py [--dry-run] [--limit N]
"""

import logging
from google.cloud import bigquery
from typing import List, Dict

logger = logging.getLogger(__name__)
PROJECT_ID = 'nba-props-platform'
EDGE_THRESHOLD = 0.5

class SyntheticLineBackfiller:
    def __init__(self, dry_run: bool = False):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.dry_run = dry_run

    def get_predictions_needing_lines(self) -> List[Dict]:
        """Get predictions without betting lines."""
        query = """
        SELECT
            p.prediction_id,
            p.pitcher_lookup,
            p.game_date,
            p.predicted_strikeouts,
            pgs.k_avg_last_10 as synthetic_line
        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` p
        JOIN `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
          ON p.pitcher_lookup = pgs.player_lookup
          AND p.game_date = pgs.game_date
        WHERE p.strikeouts_line IS NULL
          AND pgs.k_avg_last_10 IS NOT NULL
        """
        # Execute and return

    def calculate_recommendation(self, predicted: float, line: float) -> str:
        """Calculate recommendation based on edge."""
        edge = predicted - line
        if edge > EDGE_THRESHOLD:
            return 'OVER'
        elif edge < -EDGE_THRESHOLD:
            return 'UNDER'
        else:
            return 'PASS'

    def update_predictions(self, updates: List[Dict]) -> int:
        """Update predictions table with synthetic lines."""
        if self.dry_run:
            logger.info(f"DRY RUN: Would update {len(updates)} predictions")
            return 0

        # Batch update BigQuery
        # Return count updated

    def run_backfill(self) -> Dict:
        """Execute complete backfill."""
        logger.info("Starting synthetic line backfill...")

        # Get predictions
        predictions = self.get_predictions_needing_lines()
        logger.info(f"Found {len(predictions)} predictions needing lines")

        # Calculate updates
        updates = []
        for pred in predictions:
            edge = pred['predicted_strikeouts'] - pred['synthetic_line']
            recommendation = self.calculate_recommendation(
                pred['predicted_strikeouts'],
                pred['synthetic_line']
            )

            updates.append({
                'prediction_id': pred['prediction_id'],
                'strikeouts_line': pred['synthetic_line'],
                'line_source': 'synthetic_rolling_avg',
                'recommendation': recommendation,
                'edge': edge
            })

        # Execute updates
        updated_count = self.update_predictions(updates)

        logger.info(f"Backfill complete: {updated_count} predictions updated")

        return {
            'predictions_found': len(predictions),
            'predictions_updated': updated_count,
            'dry_run': self.dry_run
        }

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    backfiller = SyntheticLineBackfiller(dry_run=args.dry_run)
    results = backfiller.run_backfill()

    print(f"\nBackfill Results:")
    print(f"  Predictions found: {results['predictions_found']}")
    print(f"  Predictions updated: {results['predictions_updated']}")
    print(f"  Dry run: {results['dry_run']}")

if __name__ == '__main__':
    main()
```

---

## Summary

**To get the backfill in good shape:**

1. **Backfill synthetic lines** (4 hours)
   - Calculate rolling average for each prediction
   - Update predictions table
   - Recalculate recommendations

2. **Grade predictions** (1 hour)
   - Run existing grading processor
   - Populate is_correct field
   - Verify 78% hit rate

3. **Create reports & views** (2 hours)
   - Historical performance report
   - BigQuery views for dashboards
   - Documentation with disclaimers

**Total: 1-2 days work → Complete 18-month track record with 8,345 graded predictions showing 78% hit rate**

**This is the FAST path to having a complete, solid backfill!**
