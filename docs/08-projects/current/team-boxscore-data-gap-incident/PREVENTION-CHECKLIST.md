# Data Gap Prevention Checklist
## Preventing Future Multi-Day Data Gaps

Based on the January 22, 2026 team boxscore incident, this checklist outlines the changes needed to prevent similar cascading failures.

---

## Immediate Actions (P0 - This Week)

### 1. Increase Catch-Up Lookback Window

**File:** `shared/config/scraper_retry_config.yaml`

```yaml
# CHANGE FROM:
nbac_team_boxscore:
  lookback_days: 3

# CHANGE TO:
nbac_team_boxscore:
  lookback_days: 14
  alert_on_consecutive_failures: 10
```

- [ ] Update config file
- [ ] Deploy changes
- [ ] Verify catch-up system uses new lookback

### 2. Add Consecutive Failure Alerting

**New File:** `shared/alerting/scraper_failure_tracker.py`

- [ ] Implement consecutive failure tracking
- [ ] Set threshold to 10 failures
- [ ] Connect to alerting system (email/Slack)
- [ ] Test with simulated failures

### 3. Create Historical Completeness Monitor

**New File:** `bin/monitoring/historical_completeness_check.py`

- [ ] Implement 30-day lookback completeness check
- [ ] Add to Cloud Scheduler (daily at 6 AM ET)
- [ ] Connect to alerting system
- [ ] Test by simulating gaps

### 4. Add to Daily Validation

**File:** `bin/validate_pipeline.py`

Add historical completeness section:
- [ ] Check last 7 days of critical tables
- [ ] Flag any day with <80% completeness
- [ ] Include in validation output

---

## Short-Term Actions (P1 - This Month)

### 5. Rolling Window Validation

**File:** `shared/validation/rolling_window_validator.py`

- [ ] Implement window integrity checker
- [ ] Validate 10-game windows span ≤21 days
- [ ] Add quality flag when degraded
- [ ] Integrate into player_daily_cache processor

### 6. Cross-Day Dependency Validation

**File:** `shared/validation/cross_day_validator.py`

- [ ] Check upstream tables for historical completeness
- [ ] Run before Phase 4 starts
- [ ] Block or warn if historical data missing
- [ ] Log dependency check results

### 7. Data Freshness Dashboard

**New Dashboard:** Grafana or BigQuery view

- [ ] Show data freshness for all critical tables
- [ ] Color-code by staleness (green/yellow/red)
- [ ] Include trend graphs (completeness over time)
- [ ] Add to daily monitoring routine

### 8. Scraper Health Dashboard

**New Dashboard:** Show scraper success/failure rates

- [ ] Success rate last 24h, 7d, 30d
- [ ] Consecutive failure counter
- [ ] Last successful run time
- [ ] Error message aggregation

---

## Long-Term Actions (P2 - This Quarter)

### 9. Data Lineage Tracking

- [ ] Document all table dependencies
- [ ] Create dependency graph visualization
- [ ] Add to pipeline documentation
- [ ] Use for impact analysis

### 10. Multi-Source Redundancy

For critical data (team boxscore):
- [ ] Evaluate backup sources (ESPN, CBS)
- [ ] Implement fallback scraper
- [ ] Add source switching logic
- [ ] Test failover scenario

### 11. Bounded Staleness Model

Define max acceptable staleness per feature:
- [ ] Define staleness bounds for each feature
- [ ] Implement staleness tracking
- [ ] Degrade confidence when stale
- [ ] Document in feature specs

### 12. Automated Backfill System

- [ ] Detect gaps automatically
- [ ] Trigger backfill without manual intervention
- [ ] Track backfill progress
- [ ] Alert on backfill completion

---

## Configuration Reference

### Current Configuration (Problematic)

```yaml
# Catch-up system
lookback_days: 3  # TOO SHORT

# Phase validation
validate_historical: false  # MISSING

# Alerting
consecutive_failure_threshold: null  # NOT SET
```

### Target Configuration (Fixed)

```yaml
# Catch-up system
lookback_days: 14  # Catches 2-week gaps
alert_on_gap: true

# Phase validation
validate_historical: true
historical_lookback_days: 7
min_historical_completeness: 0.8

# Alerting
consecutive_failure_threshold: 10
alert_channels: [email, slack]
```

---

## Monitoring Checklist (Daily)

Run these checks every morning before pipeline starts:

- [ ] Check scraper success rates (last 24h)
- [ ] Check consecutive failure counters
- [ ] Check historical completeness (7-day lookback)
- [ ] Check data freshness for critical tables
- [ ] Review any overnight alerts

---

## Testing the Prevention Measures

### Test 1: Consecutive Failure Alert

```bash
# Simulate 10 consecutive failures
for i in {1..10}; do
  python -c "from shared.alerting import track_scraper_result; track_scraper_result('test_scraper', False, 'Simulated failure')"
done
# Verify: Alert should fire after 10th failure
```

### Test 2: Historical Completeness Check

```bash
# Run historical check
python bin/monitoring/historical_completeness_check.py --table=nba_raw.nbac_team_boxscore --lookback=30
# Verify: Should detect any existing gaps
```

### Test 3: Rolling Window Validation

```bash
# Test window validator
python -c "from shared.validation import validate_rolling_window; print(validate_rolling_window('lebron_james', 10, '2026-01-22'))"
# Verify: Should return True if window healthy, False if degraded
```

---

## Incident Response Playbook

If a multi-day gap is detected:

1. **Assess scope:** How many days? Which tables?
2. **Stop the bleeding:** Ensure scraper is fixed and running
3. **Communicate:** Alert stakeholders about degraded predictions
4. **Backfill:** Run backfill for missing data
5. **Reprocess:** Reprocess Phase 2→3→4→5
6. **Verify:** Run validation to confirm recovery
7. **Post-mortem:** Update prevention measures

---

## Success Metrics

| Metric | Before | Target | Measurement |
|--------|--------|--------|-------------|
| Time to detect gap | 26 days | <24 hours | Alert timestamp |
| Consecutive failure threshold | None | 10 | Config value |
| Catch-up lookback | 3 days | 14 days | Config value |
| Historical validation | No | Yes | Feature enabled |
| Rolling window validation | No | Yes | Feature enabled |

---

**Document Created:** January 22, 2026
**Status:** Action Items Defined
**Owner:** TBD
**Review Date:** Weekly until complete
