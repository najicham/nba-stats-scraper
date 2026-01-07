# 📊 NEW CHAT #3: Monitoring & Validation Improvements

**Created**: 2026-01-03
**Priority**: MEDIUM
**Duration**: 3-4 hours
**Objective**: Implement multi-layer validation and monitoring to prevent future gaps

---

## 🎯 COPY-PASTE TO START NEW CHAT

```
I'm implementing monitoring and validation improvements from Jan 3, 2026 session.

PROBLEM:
- Phase 4 gap (87% missing) was not caught by validation
- Only checked Phase 3, never checked Phase 4
- No alerts for Layer 4 coverage drops

MY TASK:
1. Create multi-layer validation script
2. Implement backfill validation checklist
3. Design monitoring dashboard spec
4. Set up automated alerts
5. Create weekly validation automation

Read full context:
/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-NEW-CHAT-3-MONITORING-VALIDATION.md
```

---

## 📋 YOUR MISSION

### Primary Objective
Implement comprehensive validation and monitoring to catch pipeline gaps early

### Success Criteria
- [ ] Multi-layer validation script created and tested
- [ ] Backfill validation checklist documented
- [ ] Monitoring dashboard spec designed
- [ ] Automated alerts configured
- [ ] Weekly validation script created
- [ ] Documentation complete

---

## 🔍 STEP 1: CREATE MULTI-LAYER VALIDATION SCRIPT (1 hour)

### Create Python Script

```bash
cd /home/naji/code/nba-stats-scraper
mkdir -p scripts/validation

cat > scripts/validation/validate_pipeline_completeness.py << 'EOF'
#!/usr/bin/env python3
"""
Multi-Layer Pipeline Validation

Validates data completeness across all pipeline layers to catch gaps early.
Prevents issues like the Phase 4 gap that went undetected.
"""

import argparse
from datetime import datetime, date, timedelta
from google.cloud import bigquery
from typing import Dict, List, Tuple
import sys

PROJECT_ID = "nba-props-platform"

class PipelineValidator:
    def __init__(self, start_date: str, end_date: str):
        self.client = bigquery.Client(project=PROJECT_ID)
        self.start_date = start_date
        self.end_date = end_date
        self.gaps = []
        self.warnings = []

    def validate_all_layers(self) -> bool:
        """Validate all pipeline layers. Returns True if all pass."""
        print("=" * 80)
        print(" PIPELINE COMPLETENESS VALIDATION")
        print("=" * 80)
        print(f"Date range: {self.start_date} to {self.end_date}")
        print()

        all_passed = True

        # Layer 1: Raw Data
        print("📊 Layer 1: Raw Data (BDL)")
        l1_count = self._validate_layer("nba_raw.bdl_player_boxscores", "L1")
        print(f"   Games: {l1_count}")

        # Layer 3: Analytics
        print("\n📊 Layer 3: Analytics")
        l3_count = self._validate_layer("nba_analytics.player_game_summary", "L3")
        l3_pct = (l3_count / l1_count * 100) if l1_count > 0 else 0
        print(f"   Games: {l3_count} ({l3_pct:.1f}% of L1)")

        if l3_pct < 90:
            self.gaps.append(f"❌ L3 coverage: {l3_pct:.1f}% (target: >= 90%)")
            all_passed = False
        else:
            print(f"   ✅ Coverage OK")

        # Layer 4: Precompute Features (CRITICAL - was missing before!)
        print("\n📊 Layer 4: Precompute Features ⚠️")
        l4_count = self._validate_layer("nba_precompute.player_composite_factors", "L4")
        l4_pct = (l4_count / l1_count * 100) if l1_count > 0 else 0
        print(f"   Games: {l4_count} ({l4_pct:.1f}% of L1)")

        if l4_pct < 80:
            self.gaps.append(f"❌ L4 coverage: {l4_pct:.1f}% (target: >= 80%)")
            all_passed = False
        elif l4_pct < 90:
            self.warnings.append(f"⚠️  L4 coverage: {l4_pct:.1f}% (below ideal 90%)")
        else:
            print(f"   ✅ Coverage OK")

        # Find specific date gaps
        print("\n🔍 Checking for date-level gaps...")
        date_gaps = self._find_date_gaps()

        if date_gaps:
            print(f"\n❌ Found {len(date_gaps)} dates with gaps:")
            for gap in date_gaps[:10]:  # Show first 10
                print(f"   {gap}")
            if len(date_gaps) > 10:
                print(f"   ... and {len(date_gaps) - 10} more")
        else:
            print("   ✅ No date-level gaps found")

        # Summary
        print("\n" + "=" * 80)
        print(" VALIDATION SUMMARY")
        print("=" * 80)

        if all_passed and not date_gaps:
            print("✅ ALL VALIDATIONS PASSED")
            return True
        else:
            if self.gaps:
                print("\n❌ FAILURES:")
                for gap in self.gaps:
                    print(f"   {gap}")
            if self.warnings:
                print("\n⚠️  WARNINGS:")
                for warning in self.warnings:
                    print(f"   {warning}")
            if date_gaps:
                print(f"\n📋 {len(date_gaps)} dates with incomplete data")

            return False

    def _validate_layer(self, table: str, layer_name: str) -> int:
        """Count distinct games in a layer."""
        query = f"""
        SELECT COUNT(DISTINCT game_id) as game_count
        FROM `{PROJECT_ID}.{table}`
        WHERE game_date >= '{self.start_date}'
          AND game_date <= '{self.end_date}'
        """

        try:
            result = list(self.client.query(query).result())
            return result[0]['game_count'] if result else 0
        except Exception as e:
            print(f"   ❌ Error querying {layer_name}: {e}")
            self.gaps.append(f"❌ {layer_name} query failed: {e}")
            return 0

    def _find_date_gaps(self) -> List[str]:
        """Find dates with incomplete Layer 4 coverage."""
        query = f"""
        WITH layer1 AS (
          SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
          FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
          WHERE game_date >= '{self.start_date}'
            AND game_date <= '{self.end_date}'
          GROUP BY date
        ),
        layer4 AS (
          SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
          FROM `{PROJECT_ID}.nba_precompute.player_composite_factors`
          WHERE game_date >= '{self.start_date}'
            AND game_date <= '{self.end_date}'
          GROUP BY date
        )
        SELECT
          l1.date,
          l1.games as l1_games,
          COALESCE(l4.games, 0) as l4_games,
          ROUND(100.0 * COALESCE(l4.games, 0) / l1.games, 1) as coverage_pct
        FROM layer1 l1
        LEFT JOIN layer4 l4 ON l1.date = l4.date
        WHERE COALESCE(l4.games, 0) < l1.games * 0.8  -- Less than 80% coverage
        ORDER BY l1.date DESC
        """

        try:
            results = list(self.client.query(query).result())
            return [
                f"{row['date']}: {row['l4_games']}/{row['l1_games']} games ({row['coverage_pct']}%)"
                for row in results
            ]
        except Exception as e:
            print(f"   ⚠️  Could not check date-level gaps: {e}")
            return []

def main():
    parser = argparse.ArgumentParser(description='Validate pipeline completeness across all layers')
    parser.add_argument('--start-date', default=(date.today() - timedelta(days=30)).isoformat(),
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default=date.today().isoformat(),
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--alert-on-gaps', action='store_true',
                       help='Exit with error code if gaps found (for CI/CD)')

    args = parser.parse_args()

    validator = PipelineValidator(args.start_date, args.end_date)
    passed = validator.validate_all_layers()

    if args.alert_on_gaps and not passed:
        sys.exit(1)  # Fail for automation

    sys.exit(0 if passed else 0)  # Success even if gaps (for manual runs)

if __name__ == "__main__":
    main()
EOF

chmod +x scripts/validation/validate_pipeline_completeness.py
```

### Test the Script

```bash
cd /home/naji/code/nba-stats-scraper

# Test on last 30 days
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py

# Test on specific date range
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --start-date=2024-10-01 \
  --end-date=2024-12-31

# Test with alert mode (for automation)
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --alert-on-gaps
```

**Expected output**:
```
================================================================================
 PIPELINE COMPLETENESS VALIDATION
================================================================================
Date range: 2024-10-01 to 2024-12-31

📊 Layer 1: Raw Data (BDL)
   Games: 2027

📊 Layer 3: Analytics
   Games: 1813 (89.4% of L1)
   ✅ Coverage OK

📊 Layer 4: Precompute Features ⚠️
   Games: 275 (13.6% of L1)
   ❌ L4 coverage: 13.6% (target: >= 80%)

🔍 Checking for date-level gaps...
❌ Found 82 dates with gaps:
   2024-12-31: 0/11 games (0.0%)
   2024-12-30: 0/9 games (0.0%)
   ...
```

---

## 📋 STEP 2: CREATE VALIDATION CHECKLIST (30 min)

### Document in Project

```bash
cat > docs/08-projects/current/backfill-system-analysis/VALIDATION-CHECKLIST.md << 'ENDFILE'
# Pipeline Validation Checklist

**Use this checklist after EVERY backfill or when investigating data issues!**

## Pre-Flight Checks

- [ ] Define date range to validate
- [ ] Confirm BigQuery access working
- [ ] Latest code pulled from main

## Run Multi-Layer Validation

```bash
cd /home/naji/code/nba-stats-scraper

# Validate last 30 days
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py

# Or specific date range
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --start-date=YYYY-MM-DD \
  --end-date=YYYY-MM-DD
```

## Manual Checks

### Layer 1: Raw Data
```sql
SELECT
  'BDL Boxscores' as source,
  COUNT(DISTINCT game_id) as games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date >= '[START_DATE]'
```

**Acceptance**:
- [ ] Games count >= expected (check NBA schedule)
- [ ] No gaps > 3 consecutive days
- [ ] Date range matches backfill period

### Layer 3: Analytics
```sql
SELECT
  'Analytics' as source,
  COUNT(DISTINCT game_id) as games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '[START_DATE]'
```

**Acceptance**:
- [ ] Games >= 90% of Layer 1
- [ ] No gaps > 3 consecutive days

### Layer 4: Precompute (CRITICAL!)
```sql
SELECT
  'Precompute' as source,
  COUNT(DISTINCT game_id) as games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '[START_DATE]'
```

**Acceptance**:
- [ ] Games >= 80% of Layer 1
- [ ] No gaps > 3 consecutive days
- [ ] **This was missing before - always check!**

### Cross-Layer Comparison
```sql
WITH all_layers AS (
  SELECT
    (SELECT COUNT(DISTINCT game_id) FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
     WHERE game_date >= '[START_DATE]') as layer1,
    (SELECT COUNT(DISTINCT game_id) FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date >= '[START_DATE]') as layer3,
    (SELECT COUNT(DISTINCT game_id) FROM `nba-props-platform.nba_precompute.player_composite_factors`
     WHERE game_date >= '[START_DATE]') as layer4
)
SELECT
  layer1,
  layer3,
  layer4,
  ROUND(100.0 * layer3 / layer1, 1) as l3_pct,
  ROUND(100.0 * layer4 / layer1, 1) as l4_pct
FROM all_layers
```

**Acceptance**:
- [ ] L3_pct >= 90%
- [ ] L4_pct >= 80%

## Sign-Off

Validated by: _______________
Date: _______________
Date range: _______________
All checks passed: [ ] YES [ ] NO
Issues documented: _______________

ENDFILE
```

---

## 📊 STEP 3: DESIGN MONITORING DASHBOARD (1 hour)

### Create Dashboard Spec

```bash
cat > docs/08-projects/current/monitoring/PIPELINE-HEALTH-DASHBOARD-SPEC.md << 'ENDFILE'
# Pipeline Health Dashboard Specification

**Objective**: Real-time monitoring of data pipeline health across all layers

## Dashboard Layout

### Section 1: Overall Health (Top)
- **Status Badge**: ✅ Healthy / ⚠️ Degraded / ❌ Critical
- **Last Updated**: Timestamp of last check
- **Active Alerts**: Count of current alerts

### Section 2: Layer Coverage (Main)

**Table: Coverage by Layer**

| Layer | Today | Last 7d Avg | Last 30d Avg | Trend | Status |
|-------|-------|-------------|--------------|-------|--------|
| L1: Raw (BDL) | 11 games | 8.2 games | 7.5 games | ↑ | ✅ |
| L3: Analytics | 11 games (100%) | 8.0 games (97.6%) | 7.2 games (96%) | ↑ | ✅ |
| L4: Precompute | 10 games (90.9%) | 7.5 games (91.5%) | 6.8 games (90.7%) | → | ✅ |
| L5: Predictions | 11 games (100%) | 8.1 games (98.8%) | 7.4 games (98.7%) | ↑ | ✅ |

**Chart: Coverage Trend (Last 30 Days)**
- Line chart showing games processed per layer
- X-axis: Date
- Y-axis: Game count
- 4 lines: L1, L3, L4, L5

### Section 3: Conversion Rates

**Chart: Layer Conversion Rates**

```
L1 (Raw)     100% │█████████████████████│ 11 games
                  ↓
L3 (Analytics) 100% │█████████████████████│ 11 games
                  ↓
L4 (Precompute) 90.9% │███████████████████  │ 10 games
                  ↓
L5 (Predictions) 100% │█████████████████████│ 11 games
```

### Section 4: Active Gaps

**Table: Date-Level Gaps (Last 30 Days)**

| Date | L1 | L3 | L4 | L5 | Gap Type | Duration |
|------|----|----|----|----|----------|----------|
| 2025-12-29 | 5 | 5 | 0 | 5 | L4 missing | 5 days |
| 2024-11-01 | 8 | 8 | 0 | 8 | L4 missing | 63 days |

### Section 5: Orchestrator Health

**Table: Orchestrator Triggers (Last 7 Days)**

| Orchestrator | Total Triggers | Success | Failed | Success Rate |
|--------------|----------------|---------|--------|--------------|
| Phase 2→3 | 47 | 47 | 0 | 100% |
| Phase 3→4 | 47 | 42 | 5 | 89.4% |
| Phase 4→5 | 42 | 42 | 0 | 100% |

### Section 6: Processing Latency

**Chart: End-to-End Latency**

Average time from game completion to all layers processed:
- P50: 45 minutes
- P90: 2 hours
- P99: 4 hours

**Breakdown by Stage**:
- L1 scraping: 15 min
- L3 analytics: 10 min
- L4 precompute: 15 min
- L5 predictions: 5 min

## Data Sources

### BigQuery Queries

**Coverage Query** (runs every hour):
```sql
WITH layer_counts AS (
  SELECT
    DATE(game_date) as date,
    'L1' as layer,
    COUNT(DISTINCT game_id) as games
  FROM `nba_raw.bdl_player_boxscores`
  WHERE game_date >= CURRENT_DATE() - 30
  GROUP BY date

  UNION ALL

  SELECT
    DATE(game_date) as date,
    'L3' as layer,
    COUNT(DISTINCT game_id) as games
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= CURRENT_DATE() - 30
  GROUP BY date

  UNION ALL

  SELECT
    DATE(game_date) as date,
    'L4' as layer,
    COUNT(DISTINCT game_id) as games
  FROM `nba_precompute.player_composite_factors`
  WHERE game_date >= CURRENT_DATE() - 30
  GROUP BY date
)
SELECT * FROM layer_counts
ORDER BY date DESC, layer
```

**Gap Detection Query** (runs every 4 hours):
```sql
WITH l1 AS (
  SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
  FROM `nba_raw.bdl_player_boxscores`
  WHERE game_date >= CURRENT_DATE() - 30
  GROUP BY date
),
l4 AS (
  SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
  FROM `nba_precompute.player_composite_factors`
  WHERE game_date >= CURRENT_DATE() - 30
  GROUP BY date
)
SELECT
  l1.date,
  l1.games as l1_games,
  COALESCE(l4.games, 0) as l4_games,
  CASE
    WHEN COALESCE(l4.games, 0) = 0 THEN 'Critical'
    WHEN COALESCE(l4.games, 0) < l1.games * 0.5 THEN 'Major'
    WHEN COALESCE(l4.games, 0) < l1.games * 0.8 THEN 'Minor'
    ELSE 'OK'
  END as gap_severity
FROM l1
LEFT JOIN l4 ON l1.date = l4.date
WHERE COALESCE(l4.games, 0) < l1.games * 0.8
ORDER BY l1.date DESC
```

## Alerts

### Alert Rules

1. **Critical: Layer 4 Missing**
   - Condition: L4 coverage = 0% for any date with L1 data
   - Action: Email + Slack immediately
   - Priority: P0

2. **Major: Layer 4 Low Coverage**
   - Condition: L4 coverage < 50% of L1 for any date
   - Action: Email + Slack within 1 hour
   - Priority: P1

3. **Warning: Layer 4 Below Target**
   - Condition: L4 coverage < 80% of L1 for any date
   - Action: Email daily digest
   - Priority: P2

4. **Info: Orchestrator Failure**
   - Condition: Phase 3→4 orchestrator fails
   - Action: Log + Slack notification
   - Priority: P3

### Alert Channels
- **Email**: nchammas@gmail.com
- **Slack**: #nba-pipeline-alerts
- **PagerDuty**: (for P0 only)

## Implementation Options

### Option A: Google Data Studio / Looker
**Pros**: Easy setup, good visualizations, Google integration
**Cons**: Limited alerting, manual query setup

### Option B: Grafana + BigQuery Plugin
**Pros**: Powerful alerting, customizable, open source
**Cons**: Need to host, more complex setup

### Option C: Custom React Dashboard
**Pros**: Full control, can integrate with other systems
**Cons**: Most development effort

**Recommended**: Start with Data Studio (quick win), migrate to Grafana (long-term)

## Rollout Plan

### Phase 1: MVP (1 week)
- [ ] Create Data Studio dashboard
- [ ] Implement coverage query
- [ ] Set up email alerts for P0/P1

### Phase 2: Enhanced (2 weeks)
- [ ] Add gap detection
- [ ] Set up Slack integration
- [ ] Add orchestrator monitoring

### Phase 3: Advanced (1 month)
- [ ] Migrate to Grafana
- [ ] Add latency tracking
- [ ] Implement PagerDuty integration

ENDFILE
```

---

## 🚨 STEP 4: CONFIGURE AUTOMATED ALERTS (1 hour)

### Create Alert Script

```bash
cat > scripts/monitoring/check_phase4_coverage.py << 'EOF'
#!/usr/bin/env python3
"""
Phase 4 Coverage Alert

Checks Phase 4 coverage and sends alerts if below threshold.
Runs hourly via Cloud Scheduler.
"""

import sys
from datetime import date, timedelta
from google.cloud import bigquery
import smtplib
from email.mime.text import MIMEText

PROJECT_ID = "nba-props-platform"
ALERT_EMAIL = "nchammas@gmail.com"

def check_phase4_coverage() -> dict:
    """Check Phase 4 coverage for last 7 days."""
    client = bigquery.Client(project=PROJECT_ID)

    query = """
    WITH l1 AS (
      SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
      FROM `nba_raw.bdl_player_boxscores`
      WHERE game_date >= CURRENT_DATE() - 7
      GROUP BY date
    ),
    l4 AS (
      SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
      FROM `nba_precompute.player_composite_factors`
      WHERE game_date >= CURRENT_DATE() - 7
      GROUP BY date
    )
    SELECT
      l1.date,
      l1.games as l1_games,
      COALESCE(l4.games, 0) as l4_games,
      ROUND(100.0 * COALESCE(l4.games, 0) / l1.games, 1) as coverage_pct
    FROM l1
    LEFT JOIN l4 ON l1.date = l4.date
    WHERE COALESCE(l4.games, 0) < l1.games * 0.8  -- Below 80%
    ORDER BY l1.date DESC
    """

    results = list(client.query(query).result())

    gaps = []
    for row in results:
        gaps.append({
            'date': str(row['date']),
            'l1_games': row['l1_games'],
            'l4_games': row['l4_games'],
            'coverage_pct': row['coverage_pct']
        })

    return {'gaps': gaps, 'gap_count': len(gaps)}

def send_alert(gaps: list):
    """Send email alert about gaps."""
    if not gaps:
        return

    # Format message
    message = "⚠️ PHASE 4 COVERAGE ALERT\n\n"
    message += f"Found {len(gaps)} dates with low Phase 4 coverage (< 80%):\n\n"

    for gap in gaps:
        message += f"{gap['date']}: {gap['l4_games']}/{gap['l1_games']} games ({gap['coverage_pct']}%)\n"

    message += "\nAction needed:\n"
    message += "1. Check Phase 4 processor logs\n"
    message += "2. Check Phase 3→4 orchestrator status\n"
    message += "3. Run manual backfill if needed\n"

    print(message)

    # TODO: Implement actual email sending
    # For now, just print (requires SMTP config)

def main():
    result = check_phase4_coverage()

    if result['gap_count'] > 0:
        print(f"❌ Found {result['gap_count']} dates with coverage issues")
        send_alert(result['gaps'])
        sys.exit(1)  # Fail for monitoring systems
    else:
        print("✅ Phase 4 coverage OK for last 7 days")
        sys.exit(0)

if __name__ == "__main__":
    main()
EOF

chmod +x scripts/monitoring/check_phase4_coverage.py
```

### Deploy as Cloud Function (Optional)

```bash
# Create Cloud Function for hourly monitoring
cat > /tmp/deploy_phase4_alert.sh << 'EOF'
#!/bin/bash
# Deploy Phase 4 coverage alert as Cloud Function

gcloud functions deploy phase4-coverage-alert \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=scripts/monitoring \
  --entry-point=check_phase4_coverage \
  --trigger-topic=hourly-check \
  --set-env-vars GCP_PROJECT=nba-props-platform \
  --memory=256MB \
  --timeout=60s \
  --project=nba-props-platform

# Create Cloud Scheduler job to trigger hourly
gcloud scheduler jobs create pubsub phase4-hourly-check \
  --schedule="0 * * * *" \
  --topic=hourly-check \
  --message-body='{"check": "phase4_coverage"}' \
  --location=us-west2 \
  --project=nba-props-platform
EOF

chmod +x /tmp/deploy_phase4_alert.sh
```

---

## 🔄 STEP 5: CREATE WEEKLY VALIDATION AUTOMATION (30 min)

### Create Weekly Script

```bash
cat > scripts/monitoring/weekly_pipeline_health.sh << 'EOF'
#!/bin/bash
# Weekly Pipeline Health Check
# Runs every Sunday to validate completeness across all layers

set -e

echo "========================================"
echo " WEEKLY PIPELINE HEALTH CHECK"
echo "========================================"
echo "Date: $(date)"
echo ""

cd /home/naji/code/nba-stats-scraper

# Run validation for last 30 days
echo "📊 Validating last 30 days..."
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --start-date=$(date -d '30 days ago' +%Y-%m-%d) \
  --end-date=$(date +%Y-%m-%d) \
  | tee /tmp/weekly_validation_$(date +%Y%m%d).log

# Check exit code
if [ ${PIPESTATUS[0]} -eq 0 ]; then
    echo ""
    echo "✅ Weekly validation PASSED"
    echo ""
else
    echo ""
    echo "❌ Weekly validation FAILED - gaps detected"
    echo "Review log: /tmp/weekly_validation_$(date +%Y%m%d).log"
    echo ""
fi

# Email report (TODO: implement email sending)
echo "📧 Report saved to: /tmp/weekly_validation_$(date +%Y%m%d).log"
EOF

chmod +x scripts/monitoring/weekly_pipeline_health.sh
```

### Set Up Cron Job

```bash
# Add to crontab (runs every Sunday at 8 AM)
echo "0 8 * * 0 /home/naji/code/nba-stats-scraper/scripts/monitoring/weekly_pipeline_health.sh" | crontab -

# Verify cron job
crontab -l
```

---

## 📚 STEP 6: DOCUMENT EVERYTHING (30 min)

### Create Monitoring Overview

```bash
cat > docs/08-projects/current/monitoring/README.md << 'ENDFILE'
# Pipeline Monitoring & Validation

**Overview**: Comprehensive monitoring and validation system to catch data gaps early

## Quick Links

- **Validation Script**: `scripts/validation/validate_pipeline_completeness.py`
- **Alert Script**: `scripts/monitoring/check_phase4_coverage.py`
- **Weekly Check**: `scripts/monitoring/weekly_pipeline_health.sh`
- **Dashboard Spec**: `PIPELINE-HEALTH-DASHBOARD-SPEC.md`
- **Validation Checklist**: `../backfill-system-analysis/VALIDATION-CHECKLIST.md`

## Daily Operations

### Run Manual Validation
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py
```

### Check Phase 4 Coverage
```bash
PYTHONPATH=. python3 scripts/monitoring/check_phase4_coverage.py
```

### Weekly Health Check
```bash
./scripts/monitoring/weekly_pipeline_health.sh
```

## Alert Severity Levels

| Level | Coverage | Action |
|-------|----------|--------|
| P0 - Critical | 0% | Immediate investigation |
| P1 - Major | < 50% | Investigate within 1 hour |
| P2 - Warning | < 80% | Review in daily digest |
| P3 - Info | < 90% | Monitor trend |

## Lessons from Phase 4 Gap

**What went wrong**: Only validated Phase 3, never checked Phase 4

**Prevention**: Always validate ALL layers (L1, L3, L4, L5)

**Tools**: Multi-layer validation script catches this automatically

ENDFILE
```

---

## ✅ COMPLETION CHECKLIST

- [ ] Multi-layer validation script created
- [ ] Script tested on sample date range
- [ ] Validation checklist documented
- [ ] Dashboard spec designed
- [ ] Alert script created (Phase 4 coverage)
- [ ] Weekly validation script created
- [ ] Cron job configured (optional)
- [ ] Cloud Function deployed (optional)
- [ ] Documentation created
- [ ] Team trained on new tools

---

## 🆘 TROUBLESHOOTING

### Validation Script Fails
**Error**: "Table not found"
**Fix**: Check table names in script, verify BigQuery access

**Error**: "Insufficient permissions"
**Fix**: Grant BigQuery Data Viewer role

### Alerts Not Firing
**Issue**: Gaps exist but no alert sent
**Cause**: Alert threshold may be too permissive
**Action**: Lower threshold or check alert script logic

### Weekly Script Not Running
**Issue**: Cron job doesn't execute
**Cause**: Cron not configured or path issues
**Action**: Check cron logs, verify script permissions

---

## 📞 NEED HELP?

- **Master context**: `docs/09-handoff/2026-01-03-COMPREHENSIVE-SESSION-HANDOFF.md`
- **Phase 4 gap details**: `docs/09-handoff/2026-01-03-ML-TRAINING-AND-PHASE4-STATUS.md`
- **Backfill analysis**: `docs/08-projects/current/backfill-system-analysis/`

---

**Good luck! You're building the monitoring infrastructure that will prevent future gaps like the Phase 4 issue!** 🚀
