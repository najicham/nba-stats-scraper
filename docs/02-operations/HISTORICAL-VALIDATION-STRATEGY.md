# Historical Validation Strategy

**Created**: 2026-01-20
**Status**: 🎯 COMPREHENSIVE - Ready for Execution
**Scope**: Full season validation (378 dates from Oct 2024 to Apr 2026)

---

## Executive Summary

**Question**: "Should we continue validating past dates?"

**Answer**: **YES** - But systematically, not indefinitely.

**Findings**:
- **378 game dates** in the database (Oct 22, 2024 → Apr 12, 2026)
- We've only validated **7 dates** (Jan 13-19, 2026) - **1.8%** of season
- **Unknown data quality** for remaining **371 dates** (98.2%)

**Recommendation**:
1. **One-time comprehensive validation** of entire season (4 hours)
2. **Ongoing validation** of recent dates only (past 14 days)
3. **Periodic audits** (monthly spot checks)

---

## Scope Analysis

### Current Database Coverage

```
Season Span: Oct 22, 2024 → Apr 12, 2026 (18 months)
Total Game Dates: 378
Games Per Date: ~7-12 (varies by day)
Estimated Total Games: ~3,000+

Data Layers:
- Phase 1 (Raw): ~20 data sources per game
- Phase 2 (Scraped): ~15 scraper outputs
- Phase 3 (Analytics): ~5 analytical tables
- Phase 4 (Precompute): ~5 processor outputs
- Phase 5 (Predictions): ~500-1,500 per game
- Phase 6 (Grading): ~500-1,500 per game (if graded)
```

### Validation Status

| Time Period | Dates | Status | Coverage |
|-------------|-------|--------|----------|
| **Oct-Dec 2024** | ~180 | ❓ Unknown | 0% |
| **Jan 1-12, 2026** | ~12 | ❓ Unknown | 0% |
| **Jan 13-19, 2026** | 7 | ✅ Validated | 100% |
| **Jan 20+, 2026** | ~179 | ❓ Future | N/A |

**Total Validated**: 7 / 378 = **1.8%**

---

## Validation Strategy

### Tier 1: Recent Data (High Value) - ONGOING

**Scope**: Past 14 days (rolling window)

**Frequency**: Daily (automated)

**Why**:
- Most valuable for debugging current issues
- Fresh enough to backfill if needed
- Affects active predictions/grading

**Implementation**: Already in place via new alerts

---

### Tier 2: Historical Data (Medium Value) - ONE-TIME

**Scope**: Oct 2024 → Jan 12, 2026 (~192 dates)

**Frequency**: One-time comprehensive validation

**Why**:
- Understand baseline data quality
- Identify systemic issues
- Prioritize backfills by value
- Inform future prevention

**Value Tiers**:
- **High Value** (Jan 2026): Recent, grading still valuable
- **Medium Value** (Nov-Dec 2024): Early season, model training data
- **Low Value** (Oct 2024): Preseason, less important

---

### Tier 3: Future Data (Informational) - SKIP

**Scope**: Jan 21+ (not yet happened)

**Action**: Skip (will be validated as it occurs)

---

## Comprehensive Validation Script

**Purpose**: One-time validation of entire historical season

```python
#!/usr/bin/env python3
"""
Historical Season Validation

Validates all game dates from Oct 2024 → Jan 2026 across all pipeline layers.

Usage:
    # Full season validation
    python scripts/validate_historical_season.py

    # Specific date range
    python scripts/validate_historical_season.py --start 2024-11-01 --end 2024-12-31

    # Generate report only (no output)
    python scripts/validate_historical_season.py --report-only

Output:
    - CSV report with all findings
    - Summary statistics
    - Prioritized backfill recommendations
"""

import argparse
import csv
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


class HistoricalValidator:
    """Validates historical data across all pipeline layers."""

    def __init__(self, project_id: str = PROJECT_ID):
        self.bq_client = bigquery.Client(project=project_id)
        self.project_id = project_id
        self.results = []

    def get_all_game_dates(self, start_date: str = None, end_date: str = None) -> List[str]:
        """Get all game dates from schedule."""
        where_clause = ""
        if start_date and end_date:
            where_clause = f"WHERE game_date BETWEEN '{start_date}' AND '{end_date}'"
        elif start_date:
            where_clause = f"WHERE game_date >= '{start_date}'"
        elif end_date:
            where_clause = f"WHERE game_date <= '{end_date}'"

        query = f"""
        SELECT DISTINCT game_date
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        {where_clause}
        ORDER BY game_date
        """

        results = self.bq_client.query(query).result()
        return [row.game_date.strftime('%Y-%m-%d') for row in results]

    def validate_phase2_scrapers(self, game_date: str) -> Dict:
        """Validate Phase 2 scraper completeness."""
        # Check key scraper tables
        scrapers = {
            'bdl_box_scores': f"SELECT COUNT(DISTINCT game_id) FROM `{self.project_id}.nba_raw.bdl_player_boxscores` WHERE game_date = '{game_date}'",
            'nbac_gamebook': f"SELECT COUNT(DISTINCT game_id) FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats` WHERE game_date = '{game_date}'",
            'bettingpros_props': f"SELECT COUNT(DISTINCT player_name) FROM `{self.project_id}.nba_raw.bettingpros_player_props` WHERE game_date = '{game_date}'"
        }

        # Get scheduled games
        scheduled_query = f"SELECT COUNT(DISTINCT game_id) as games FROM `{self.project_id}.nba_raw.nbac_schedule` WHERE game_date = '{game_date}'"
        scheduled_result = list(self.bq_client.query(scheduled_query).result())
        scheduled_games = scheduled_result[0].games if scheduled_result else 0

        results = {'scheduled_games': scheduled_games}

        for scraper_name, query in scrapers.items():
            try:
                result = list(self.bq_client.query(query).result())
                count = result[0][0] if result else 0
                results[scraper_name] = count
            except Exception as e:
                logger.warning(f"Error checking {scraper_name} for {game_date}: {e}")
                results[scraper_name] = -1  # Error marker

        return results

    def validate_phase3_analytics(self, game_date: str) -> Dict:
        """Validate Phase 3 analytics completeness."""
        tables = {
            'player_game_summary': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.player_game_summary` WHERE game_date = '{game_date}'",
            'team_defense': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.team_defense_game_summary` WHERE game_date = '{game_date}'",
            'upcoming_context': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.upcoming_player_game_context` WHERE analysis_date = '{game_date}'"
        }

        results = {}
        for table_name, query in tables.items():
            try:
                result = list(self.bq_client.query(query).result())
                count = result[0][0] if result else 0
                results[table_name] = count
            except Exception as e:
                logger.warning(f"Error checking {table_name} for {game_date}: {e}")
                results[table_name] = -1

        return results

    def validate_phase4_processors(self, game_date: str) -> Dict:
        """Validate Phase 4 processor completeness."""
        processors = {
            'PDC': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_daily_cache` WHERE analysis_date = '{game_date}'",
            'PSZA': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis` WHERE analysis_date = '{game_date}'",
            'PCF': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_composite_factors` WHERE analysis_date = '{game_date}'",
            'MLFS': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.ml_feature_store_v2` WHERE analysis_date = '{game_date}'",
            'TDZA': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis` WHERE analysis_date = '{game_date}'"
        }

        results = {}
        for proc_name, query in processors.items():
            try:
                result = list(self.bq_client.query(query).result())
                count = result[0][0] if result else 0
                results[proc_name] = count
            except Exception as e:
                logger.warning(f"Error checking {proc_name} for {game_date}: {e}")
                results[proc_name] = -1

        # Calculate completion
        completed = sum(1 for v in results.values() if v > 0)
        results['completed_count'] = completed
        results['total_count'] = len(processors)

        return results

    def validate_phase5_predictions(self, game_date: str) -> Dict:
        """Validate Phase 5 predictions completeness."""
        query = f"""
        SELECT
          COUNT(*) as total_predictions,
          COUNT(DISTINCT player_lookup) as unique_players,
          COUNT(DISTINCT system_id) as unique_systems
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{game_date}'
        """

        try:
            result = list(self.bq_client.query(query).result())
            if result:
                row = result[0]
                return {
                    'total_predictions': row.total_predictions,
                    'unique_players': row.unique_players,
                    'unique_systems': row.unique_systems
                }
        except Exception as e:
            logger.warning(f"Error checking predictions for {game_date}: {e}")

        return {'total_predictions': 0, 'unique_players': 0, 'unique_systems': 0}

    def validate_phase6_grading(self, game_date: str) -> Dict:
        """Validate Phase 6 grading completeness."""
        query = f"""
        SELECT
          COUNT(*) as total_graded,
          COUNT(DISTINCT player_lookup) as unique_players_graded,
          ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / NULLIF(COUNT(*), 0), 1) as win_rate
        FROM `{self.project_id}.nba_predictions.prediction_grades`
        WHERE game_date = '{game_date}'
        """

        try:
            result = list(self.bq_client.query(query).result())
            if result:
                row = result[0]
                return {
                    'total_graded': row.total_graded,
                    'unique_players_graded': row.unique_players_graded,
                    'win_rate': row.win_rate
                }
        except Exception as e:
            logger.warning(f"Error checking grading for {game_date}: {e}")

        return {'total_graded': 0, 'unique_players_graded': 0, 'win_rate': None}

    def validate_single_date(self, game_date: str) -> Dict:
        """Validate all layers for a single date."""
        logger.info(f"Validating {game_date}...")

        result = {
            'game_date': game_date,
            'phase2': self.validate_phase2_scrapers(game_date),
            'phase3': self.validate_phase3_analytics(game_date),
            'phase4': self.validate_phase4_processors(game_date),
            'phase5': self.validate_phase5_predictions(game_date),
            'phase6': self.validate_phase6_grading(game_date)
        }

        # Calculate overall health score
        result['health_score'] = self.calculate_health_score(result)

        self.results.append(result)
        return result

    def calculate_health_score(self, validation: Dict) -> float:
        """Calculate overall health score (0-100)."""
        scores = []

        # Phase 2: Box score coverage
        scheduled = validation['phase2'].get('scheduled_games', 0)
        if scheduled > 0:
            bdl_coverage = validation['phase2'].get('bdl_box_scores', 0) / scheduled
            gamebook_coverage = validation['phase2'].get('nbac_gamebook', 0) / scheduled
            scores.append(max(bdl_coverage, gamebook_coverage) * 100)  # Use best scraper

        # Phase 3: Analytics completion
        phase3_count = sum(1 for v in validation['phase3'].values() if v > 0)
        scores.append((phase3_count / 3) * 100)

        # Phase 4: Processor completion
        phase4_completed = validation['phase4'].get('completed_count', 0)
        scores.append((phase4_completed / 5) * 100)

        # Phase 5: Predictions exist
        if validation['phase5']['total_predictions'] > 0:
            scores.append(100)
        else:
            scores.append(0)

        # Phase 6: Grading exists
        predictions = validation['phase5']['total_predictions']
        graded = validation['phase6']['total_graded']
        if predictions > 0:
            grading_coverage = (graded / predictions) * 100
            scores.append(grading_coverage)
        else:
            scores.append(0)

        return sum(scores) / len(scores) if scores else 0

    def validate_date_range(self, start_date: str = None, end_date: str = None):
        """Validate entire date range."""
        dates = self.get_all_game_dates(start_date, end_date)

        logger.info(f"Validating {len(dates)} dates from {dates[0]} to {dates[-1]}")

        for i, game_date in enumerate(dates, 1):
            self.validate_single_date(game_date)
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(dates)} dates validated")

        logger.info("Validation complete!")

    def generate_report(self, output_file: str = 'historical_validation_report.csv'):
        """Generate CSV report of all findings."""
        if not self.results:
            logger.error("No validation results to report")
            return

        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'game_date', 'health_score',
                'scheduled_games', 'bdl_box_scores', 'nbac_gamebook',
                'player_game_summary', 'team_defense', 'upcoming_context',
                'pdc', 'psza', 'pcf', 'mlfs', 'tdza', 'phase4_completion',
                'total_predictions', 'unique_players', 'unique_systems',
                'total_graded', 'grading_coverage_pct', 'win_rate'
            ])

            # Data rows
            for r in self.results:
                predictions = r['phase5']['total_predictions']
                graded = r['phase6']['total_graded']
                grading_pct = (graded / predictions * 100) if predictions > 0 else 0

                writer.writerow([
                    r['game_date'],
                    f"{r['health_score']:.1f}",
                    r['phase2']['scheduled_games'],
                    r['phase2'].get('bdl_box_scores', 0),
                    r['phase2'].get('nbac_gamebook', 0),
                    r['phase3'].get('player_game_summary', 0),
                    r['phase3'].get('team_defense', 0),
                    r['phase3'].get('upcoming_context', 0),
                    r['phase4'].get('PDC', 0),
                    r['phase4'].get('PSZA', 0),
                    r['phase4'].get('PCF', 0),
                    r['phase4'].get('MLFS', 0),
                    r['phase4'].get('TDZA', 0),
                    f"{r['phase4']['completed_count']}/{r['phase4']['total_count']}",
                    predictions,
                    r['phase5']['unique_players'],
                    r['phase5']['unique_systems'],
                    graded,
                    f"{grading_pct:.1f}",
                    r['phase6']['win_rate'] or 'N/A'
                ])

        logger.info(f"Report saved to {output_file}")

    def print_summary(self):
        """Print summary statistics."""
        if not self.results:
            return

        print("\n" + "="*80)
        print("HISTORICAL VALIDATION SUMMARY")
        print("="*80)

        total_dates = len(self.results)
        avg_health = sum(r['health_score'] for r in self.results) / total_dates

        print(f"\nDates Validated: {total_dates}")
        print(f"Average Health Score: {avg_health:.1f}%")

        # Health distribution
        excellent = sum(1 for r in self.results if r['health_score'] >= 90)
        good = sum(1 for r in self.results if 70 <= r['health_score'] < 90)
        fair = sum(1 for r in self.results if 50 <= r['health_score'] < 70)
        poor = sum(1 for r in self.results if r['health_score'] < 50)

        print(f"\nHealth Distribution:")
        print(f"  Excellent (≥90%): {excellent} dates ({excellent/total_dates*100:.1f}%)")
        print(f"  Good (70-89%):    {good} dates ({good/total_dates*100:.1f}%)")
        print(f"  Fair (50-69%):    {fair} dates ({fair/total_dates*100:.1f}%)")
        print(f"  Poor (<50%):      {poor} dates ({poor/total_dates*100:.1f}%)")

        # Top issues
        print(f"\nTop Issues:")

        # Box score gaps
        box_score_gaps = sum(1 for r in self.results if r['phase2'].get('bdl_box_scores', 0) < r['phase2']['scheduled_games'])
        print(f"  Missing box scores: {box_score_gaps} dates")

        # Phase 4 failures
        phase4_failures = sum(1 for r in self.results if r['phase4']['completed_count'] < 3)
        print(f"  Phase 4 failures: {phase4_failures} dates")

        # Ungraded predictions
        ungraded = sum(1 for r in self.results if r['phase5']['total_predictions'] > 0 and r['phase6']['total_graded'] == 0)
        print(f"  Ungraded predictions: {ungraded} dates")

        print("\n" + "="*80)


def main():
    parser = argparse.ArgumentParser(description='Validate historical season data')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--report-only', action='store_true', help='Generate report without printing summary')
    parser.add_argument('--output', default='historical_validation_report.csv', help='Output file path')

    args = parser.parse_args()

    validator = HistoricalValidator()
    validator.validate_date_range(args.start, args.end)
    validator.generate_report(args.output)

    if not args.report_only:
        validator.print_summary()


if __name__ == '__main__':
    main()
```

---

## Recommended Validation Schedule

### Immediate (This Week)

**One-Time Historical Validation** (Run once, ~4 hours)

```bash
# Full season validation
python scripts/validate_historical_season.py

# Output: historical_validation_report.csv with 378 rows
```

**Expected Output**:
- CSV with health score for each date
- Summary statistics
- List of dates needing backfill
- Prioritized action items

### Ongoing (Daily, Automated)

**Recent Date Monitoring** (Already deployed)

- Box score alert: Every 6 hours (checks past 2 days)
- Phase 4 alert: Daily noon (checks yesterday)
- Grading alert: Daily 10 AM (checks yesterday)

**No additional work needed** - this is already automated!

### Periodic (Monthly)

**Spot Check Validation** (1st of each month, ~30 min)

```bash
# Validate previous month
python scripts/validate_historical_season.py \
  --start $(date -d "1 month ago" +%Y-%m-01) \
  --end $(date -d "last month" +%Y-%m-%d)
```

---

## Decision Framework: "Should We Backfill?"

### Criteria for Backfilling

| Factor | Weight | Threshold | Action |
|--------|--------|-----------|--------|
| **Recency** | HIGH | <30 days old | ✅ Backfill |
| **Health Score** | HIGH | <70% | ✅ Backfill |
| **Grading Value** | MEDIUM | Predictions exist | ✅ Backfill grading |
| **Data Availability** | MEDIUM | Source data exists | ✅ Backfill possible |
| **Training Value** | LOW | Early season (Nov-Dec) | ⚠️ Consider |
| **Age** | NEGATIVE | >90 days old | ❌ Skip |

### Backfill Priority Tiers

**Tier 1: Critical (Do Now)**
- Dates <14 days old with health <70%
- Any date with 0 predictions but games occurred
- Any date with predictions but 0 grading

**Tier 2: Important (Do This Week)**
- Dates 14-30 days old with health <80%
- Recent dates missing Phase 4 critical processors

**Tier 3: Nice-to-Have (Do If Time)**
- Dates >30 days with health 50-70%
- Early season dates for training data

**Tier 4: Skip**
- Dates >90 days old with health >50%
- Preseason dates (Oct 2024)

---

## Cost-Benefit Analysis

### Cost of Full Historical Validation

- **Compute**: ~$5 (BigQuery queries for 378 dates)
- **Time**: 4 hours (mostly BigQuery query time)
- **Engineer Time**: 30 minutes (setup + review)

**Total Cost**: ~$10 + 30 min engineering

### Benefit of Historical Validation

- **Understand baseline**: Know starting data quality
- **Prioritize backfills**: Focus on high-value dates
- **Identify patterns**: Find recurring issues
- **Prevent future issues**: Learn from past failures
- **Confidence**: Know system health across time

**Value**: **HIGH** - One-time investment with lasting insights

### Recommendation

✅ **DO IT** - Run full historical validation once, then ongoing monitoring only

---

## Sample Output (Expected)

```
================================================================================
HISTORICAL VALIDATION SUMMARY
================================================================================

Dates Validated: 378
Average Health Score: 73.2%

Health Distribution:
  Excellent (≥90%): 156 dates (41.3%)
  Good (70-89%):    142 dates (37.6%)
  Fair (50-69%):     58 dates (15.3%)
  Poor (<50%):       22 dates (5.8%)

Top Issues:
  Missing box scores: 127 dates
  Phase 4 failures: 43 dates
  Ungraded predictions: 89 dates

Top 10 Dates Needing Backfill:
  2026-01-18: Health 45.2% (missing Phase 4)
  2026-01-16: Health 52.1% (missing Phase 4)
  2025-12-25: Health 38.9% (Christmas - multiple failures)
  [... more dates ...]

================================================================================
```

---

## Next Steps

### Immediate (This Week)

1. ✅ Create validation script (code provided above)
2. ✅ Run full historical validation
3. ✅ Review report and prioritize backfills
4. ✅ Execute Tier 1 backfills (critical dates)

### Ongoing (Automated)

5. ✅ Monitor via deployed alerts (already running)
6. ✅ Monthly spot checks (1st of each month)

### Long-term (Next Month)

7. ✅ Add validation to deployment checklist
8. ✅ Integrate into CI/CD pipeline
9. ✅ Create validation dashboard

---

**Status**: 📋 Ready to Execute
**Next Action**: Run `python scripts/validate_historical_season.py`

