# 📋 Monitoring Implementation Priorities

**Created**: 2026-01-02
**Based on**: Ultrathink validation gap analysis
**Objective**: Prevent future Phase 4-style gaps with automated monitoring

---

## 🎯 EXECUTIVE SUMMARY

### The Finding
**Existing validation tools WORK** - they correctly detect the Phase 4 gap when run:
```bash
# Test confirms: validation catches Phase 4 gaps
PYTHONPATH=. python3 bin/validate_pipeline.py 2024-12-15

Output:
  Phase 4: △ Partial - needs attention
  ✗ No data for 2024-12-15: player_composite_factors
```

### The Problem
**Tools weren't being run proactively on historical data!**

- ✅ Have: Validation tools
- ✅ Have: Phase 4 checking
- ❌ Missing: Automation (cron jobs, scheduled runs)
- ❌ Missing: Alerting (email, Slack)
- ❌ Missing: Simple coverage monitoring

### The Solution
Add **4 lightweight components** to convert validation → monitoring:

1. **Simple coverage checker** - Quick health check (not full validation)
2. **Weekly automation** - Cron job runs validation every Sunday
3. **Hourly alerts** - Cloud Function checks Phase 4 coverage
4. **Validation checklist** - Standardized post-backfill process

---

## 🚀 IMPLEMENTATION PLAN

### P0 - CRITICAL (Prevent Recurrence) - 2.5 hours total

These prevent the Phase 4 gap from ever happening again.

#### 1. Create Simple Multi-Layer Coverage Script (1 hour)

**File**: `scripts/validation/validate_pipeline_completeness.py`

**Purpose**: Quick health check for automation (not full validation)

**Key differences from `bin/validate_pipeline.py`**:
- **Simpler**: Only checks game counts across layers
- **Faster**: No player-level checks, no quality distribution
- **Alert mode**: Exit code 1 if gaps found (for cron)
- **Cross-layer**: Shows L4 as % of L1 (catches coverage gaps)

**Implementation**:
```python
class PipelineValidator:
    def validate_all_layers(self, start_date, end_date):
        # Count games in each layer
        l1_games = count_games("nba_raw.bdl_player_boxscores", start_date, end_date)
        l3_games = count_games("nba_analytics.player_game_summary", start_date, end_date)
        l4_games = count_games("nba_precompute.player_composite_factors", start_date, end_date)

        # Calculate coverage
        l3_pct = (l3_games / l1_games * 100) if l1_games > 0 else 0
        l4_pct = (l4_games / l1_games * 100) if l1_games > 0 else 0

        # Check thresholds
        if l3_pct < 90:
            self.gaps.append(f"L3 coverage: {l3_pct:.1f}% (target: >= 90%)")
        if l4_pct < 80:  # This would have caught Phase 4 gap!
            self.gaps.append(f"L4 coverage: {l4_pct:.1f}% (target: >= 80%)")

        # Find specific date gaps
        date_gaps = find_dates_with_l4_gaps(start_date, end_date)

        return {
            'l1_games': l1_games,
            'l3_games': l3_games,
            'l3_pct': l3_pct,
            'l4_games': l4_games,
            'l4_pct': l4_pct,
            'gaps': self.gaps,
            'date_gaps': date_gaps
        }
```

**Usage**:
```bash
# Manual run
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py

# Specific date range
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --start-date 2024-10-01 --end-date 2024-12-31

# Alert mode (for automation)
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --alert-on-gaps
```

**Why separate from `validate_pipeline.py`?**
- `validate_pipeline.py`: Deep dive, investigative (slow, detailed)
- `validate_pipeline_completeness.py`: Health check, monitoring (fast, simple)

**Create it**: Copy template from monitoring doc (already written!)

---

#### 2. Set Up Weekly Validation Cron Job (30 min)

**File**: `scripts/monitoring/weekly_pipeline_health.sh`

**Purpose**: Run validation every Sunday to catch gaps within 7 days

**Implementation**:
```bash
#!/bin/bash
# Weekly Pipeline Health Check
# Runs every Sunday at 8 AM

echo "========================================"
echo " WEEKLY PIPELINE HEALTH CHECK"
echo "========================================"

cd /home/naji/code/nba-stats-scraper

# Run validation for last 30 days
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --start-date=$(date -d '30 days ago' +%Y-%m-%d) \
  --end-date=$(date +%Y-%m-%d) \
  | tee /tmp/weekly_validation_$(date +%Y%m%d).log

# Check exit code
if [ ${PIPESTATUS[0]} -eq 0 ]; then
    echo "✅ Weekly validation PASSED"
else
    echo "❌ Weekly validation FAILED - gaps detected"
fi
```

**Deployment**:
```bash
# Add to crontab
crontab -e

# Add this line:
0 8 * * 0 /home/naji/code/nba-stats-scraper/scripts/monitoring/weekly_pipeline_health.sh
```

**Impact**: Gap detected within 6 days instead of 90+ days!

---

#### 3. Document Validation Checklist (30 min)

**File**: `docs/08-projects/current/backfill-system-analysis/VALIDATION-CHECKLIST.md`

**Purpose**: Standardized process - always check ALL layers

**Implementation**: Copy template from monitoring doc

**Key sections**:
```markdown
## Post-Backfill Validation Checklist

- [ ] Layer 1: Raw Data (BDL boxscores)
- [ ] Layer 3: Analytics (player_game_summary)
- [ ] Layer 4: Precompute (player_composite_factors)  ← CRITICAL!
- [ ] Layer 5: Predictions (ml_feature_store_v2)

## Acceptance Criteria

- [ ] L3 >= 90% of L1
- [ ] L4 >= 80% of L1  ← This would have caught the gap!
- [ ] L5 >= 90% of L3
```

**Usage**: After EVERY backfill, run through checklist

**Impact**: Human process to complement automation

---

#### 4. Update Documentation (30 min)

**Files to update**:
- `docs/08-projects/current/monitoring/README.md` - Create overview
- `README.md` - Add monitoring section

**Content**:
- Link to new validation tools
- When to run what
- Alert severity levels
- Troubleshooting

---

### P1 - HIGH (Early Detection) - 2 hours total

These add real-time alerting for immediate detection.

#### 5. Deploy Hourly Phase 4 Coverage Alert (1 hour)

**File**: `scripts/monitoring/check_phase4_coverage.py`

**Purpose**: Hourly check - alert if Phase 4 falls behind

**Implementation**:
```python
def check_phase4_coverage():
    """Check Phase 4 coverage for last 7 days."""
    gaps = query("""
        WITH l1 AS (
            SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
            FROM nba_raw.bdl_player_boxscores
            WHERE game_date >= CURRENT_DATE() - 7
            GROUP BY date
        ),
        l4 AS (
            SELECT DATE(game_date) as date, COUNT(DISTINCT game_id) as games
            FROM nba_precompute.player_composite_factors
            WHERE game_date >= CURRENT_DATE() - 7
            GROUP BY date
        )
        SELECT l1.date, l1.games as l1_games, COALESCE(l4.games, 0) as l4_games
        FROM l1 LEFT JOIN l4 ON l1.date = l4.date
        WHERE COALESCE(l4.games, 0) < l1.games * 0.8  -- Below 80%
    """)

    if gaps:
        send_alert(f"⚠️ {len(gaps)} dates with L4 coverage < 80%")
        return FAIL
    return OK
```

**Deployment**:
```bash
# Deploy as Cloud Function
gcloud functions deploy phase4-coverage-alert \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=scripts/monitoring \
  --entry-point=check_phase4_coverage \
  --trigger-topic=hourly-check

# Schedule to run hourly
gcloud scheduler jobs create pubsub phase4-hourly-check \
  --schedule="0 * * * *" \
  --topic=hourly-check \
  --message-body='{"check": "phase4_coverage"}'
```

**Impact**: Gap detected within 1 hour of occurrence!

---

#### 6. Enhance Backfill Validator with Cross-Layer Comparison (1 hour)

**File**: `scripts/validate_backfill_coverage.py` (existing - enhance)

**Add**:
```python
def compare_layers(self, start_date, end_date):
    """Compare Layer 3 vs Layer 4 coverage."""
    l3_games = count_games("nba_analytics.player_game_summary", start_date, end_date)
    l4_games = count_games("nba_precompute.player_composite_factors", start_date, end_date)

    coverage_pct = (l4_games / l3_games * 100) if l3_games > 0 else 0

    print(f"\nLayer Coverage Comparison:")
    print(f"  Layer 3 (Analytics): {l3_games} games")
    print(f"  Layer 4 (Precompute): {l4_games} games ({coverage_pct:.1f}%)")

    if coverage_pct < 80:
        print(f"  ❌ Layer 4 coverage below 80%!")
        return False
    return True
```

---

### P2 - MEDIUM (Visibility) - 3-4 hours total

These add visibility and comprehensive monitoring.

#### 7. Create Monitoring Dashboard (3-4 hours)

**Tool**: Google Data Studio (easiest) or Grafana (more powerful)

**Datasets**:
```sql
-- Coverage query (runs hourly)
WITH layer_counts AS (
  SELECT DATE(game_date) as date, 'L1' as layer, COUNT(DISTINCT game_id) as games
  FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= CURRENT_DATE() - 30
  GROUP BY date

  UNION ALL

  SELECT DATE(game_date) as date, 'L3' as layer, COUNT(DISTINCT game_id) as games
  FROM nba_analytics.player_game_summary
  WHERE game_date >= CURRENT_DATE() - 30
  GROUP BY date

  UNION ALL

  SELECT DATE(game_date) as date, 'L4' as layer, COUNT(DISTINCT game_id) as games
  FROM nba_precompute.player_composite_factors
  WHERE game_date >= CURRENT_DATE() - 30
  GROUP BY date
)
SELECT * FROM layer_counts ORDER BY date DESC, layer
```

**Charts**:
1. **Coverage Trend** - Line chart (L1, L3, L4 games over time)
2. **Conversion Rates** - Bar chart (L3/L1, L4/L1 percentages)
3. **Active Gaps** - Table (dates with < 80% L4 coverage)
4. **Overall Health** - Status badge (✅ Healthy / ⚠️ Degraded)

---

#### 8. Set Up Email/Slack Alerting (1 hour)

**Integration**: SendGrid (email) + Slack webhook

**Alert levels**:
- **P0 (Critical)**: L4 coverage = 0% → Email + Slack immediately
- **P1 (Major)**: L4 coverage < 50% → Email + Slack within 1 hour
- **P2 (Warning)**: L4 coverage < 80% → Daily digest email
- **P3 (Info)**: Orchestrator failures → Slack notification

---

### P3 - NICE TO HAVE (Advanced) - 1+ week

#### 9. Migrate to Grafana (1 week)
- More powerful alerting
- Better customization
- Open source

#### 10. Add Latency Tracking (2-3 hours)
- End-to-end processing time
- Bottleneck identification
- P50/P90/P99 metrics

---

## 📊 WHAT'S ACTUALLY MISSING (Summary)

### Already Have ✅

1. ✅ **Phase validation logic** - All phases validated correctly
2. ✅ **Date range support** - Can validate multiple dates
3. ✅ **Player reconciliation** - Expected vs actual tracking
4. ✅ **Failure categorization** - Understand why data missing
5. ✅ **Quality checks** - Data completeness metrics

**Proof**: `bin/validate_pipeline.py 2024-12-15` correctly shows Phase 4 partial!

### Need to Add ❌

1. ❌ **Scheduled execution** - No cron jobs running validation
2. ❌ **Cross-layer coverage monitoring** - No "L4 as % of L1" tracking
3. ❌ **Alerting infrastructure** - No email/Slack on gaps
4. ❌ **Weekly automation** - No regular health checks
5. ❌ **Simple coverage script** - Complex validation, no quick check

---

## 📅 IMPLEMENTATION TIMELINE

### Day 1 (Today) - 2.5 hours
- [ ] Create `validate_pipeline_completeness.py` (1 hour)
- [ ] Create `weekly_pipeline_health.sh` (30 min)
- [ ] Document validation checklist (30 min)
- [ ] Update documentation (30 min)

### Day 2 - 2 hours
- [ ] Deploy hourly Phase 4 alert (1 hour)
- [ ] Enhance backfill validator (1 hour)

### Week 1 - 3-4 hours
- [ ] Create monitoring dashboard (3-4 hours)

### Week 2 - 1 hour
- [ ] Set up email/Slack alerting (1 hour)

**Total P0-P2 effort**: ~8-9 hours

---

## ✅ ACCEPTANCE CRITERIA

### Success Metrics

1. **Weekly validation runs automatically** via cron
2. **Gaps detected within 7 days** (vs 90+ days previously)
3. **Hourly alerts fire** when L4 coverage drops
4. **Dashboard shows trends** for all layers
5. **Checklist prevents** manual validation oversights

### Testing Plan

1. **Test weekly cron job**:
   ```bash
   # Manually run to verify
   ./scripts/monitoring/weekly_pipeline_health.sh
   ```

2. **Test alert script**:
   ```bash
   # Should alert on Oct-Dec 2024 gap
   PYTHONPATH=. python3 scripts/monitoring/check_phase4_coverage.py
   ```

3. **Test coverage script**:
   ```bash
   # Should show 13.6% coverage for 2024-25
   PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
     --start-date 2024-10-01 --end-date 2025-01-02
   ```

---

## 🎯 KEY DECISIONS

### Why Not Just Use Existing `validate_pipeline.py`?

**Existing tool** (`bin/validate_pipeline.py`):
- **Purpose**: Deep investigation, debugging
- **Speed**: Slow (20-30s per date)
- **Complexity**: Checks chains, players, quality, orchestration
- **Output**: Detailed per-table status
- **Best for**: "Why did this specific date fail?"

**New tool** (`validate_pipeline_completeness.py`):
- **Purpose**: Quick health check, monitoring
- **Speed**: Fast (< 5s for 30 days)
- **Complexity**: Simple game counts, coverage %
- **Output**: High-level layer coverage
- **Best for**: "Is Layer 4 falling behind?"

**Both are needed!**
- Use `validate_pipeline.py` for investigation
- Use `validate_pipeline_completeness.py` for monitoring

### Why Weekly + Hourly Checks?

- **Weekly** (30-day validation): Catches historical gaps, trending issues
- **Hourly** (7-day check): Catches recent gaps, real-time issues

**Together**: Comprehensive coverage (recent + historical)

---

## 📚 REFERENCE

### Files to Create

1. **P0**:
   - `scripts/validation/validate_pipeline_completeness.py`
   - `scripts/monitoring/weekly_pipeline_health.sh`
   - `docs/08-projects/current/backfill-system-analysis/VALIDATION-CHECKLIST.md`
   - `docs/08-projects/current/monitoring/README.md`

2. **P1**:
   - `scripts/monitoring/check_phase4_coverage.py`
   - Update: `scripts/validate_backfill_coverage.py`

3. **P2**:
   - Data Studio dashboard
   - Email/Slack alerting config

### Existing Files to Use

- ✅ `bin/validate_pipeline.py` - Use for deep dives
- ✅ `scripts/validate_backfill_coverage.py` - Use for backfill validation
- ✅ `scripts/check_data_completeness.py` - Use for raw data checks

### Templates Available

- ✅ All code templates in: `docs/09-handoff/2026-01-03-NEW-CHAT-3-MONITORING-VALIDATION.md`
- ✅ Dashboard spec ready
- ✅ SQL queries ready
- ✅ Deployment scripts ready

---

## 🎬 NEXT STEPS

1. **Review this document** with team
2. **Start with P0** (prevents recurrence)
3. **Test each component** before moving to next
4. **Deploy gradually** (weekly cron → hourly alerts → dashboard)
5. **Document learnings** as we implement

---

**Bottom line**: We have the validation tools - now we need to **automate** and **monitor** them!
