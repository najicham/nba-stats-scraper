# 📋 Session 4: Complete Execution Commands Reference

**Created**: January 4, 2026
**Purpose**: Copy-paste ready commands for Session 4 execution
**Status**: Ready to execute when orchestrator completes

---

## 🎯 EXECUTION WORKFLOW

This document contains all commands needed to execute Session 4, organized in sequence.

---

## STEP 1: CHECK ORCHESTRATOR COMPLETION

### 1.1 Check if Orchestrator is Still Running
```bash
ps aux | grep backfill_orchestrator | grep -v grep
```
**Expected**: No output (orchestrator has stopped)

### 1.2 Review Orchestrator Final Report
```bash
# View last 200 lines
tail -200 logs/orchestrator_20260103_134700.log

# Extract key sections
grep -E "VALIDATION|COMPLETE|SUMMARY|Phase" logs/orchestrator_20260103_134700.log | tail -50
```

### 1.3 Check Both Phase Logs
```bash
# Phase 1 summary
bash scripts/monitoring/parse_backfill_log.sh logs/team_offense_backfill_phase1.log

# Phase 2 log location (check for it)
ls -lh logs/*player*summary*.log
```

**Expected Outputs**:
- Orchestrator shows both phases COMPLETE
- Phase 1: 1,537/1,537 days (100%)
- Phase 2: Completed successfully
- Both validations PASSED

---

## STEP 2: VALIDATE PHASE 1 (team_offense)

### 2.1 Run Validation Script
```bash
cd /home/naji/code/nba-stats-scraper

bash scripts/validation/validate_team_offense.sh "2021-10-19" "2026-01-02"
```

### 2.2 Expected Output
```
════════════════════════════════════════════════════════
  VALIDATING TEAM_OFFENSE_GAME_SUMMARY
════════════════════════════════════════════════════════
Check 1/4: Game count...
✅ Game count: 5,600+ (threshold: 5,600+) ✓

Check 2/4: Record count...
✅ Record count: ~11,200 (~2 per game) ✓

Check 3/4: Quality metrics...
✅ Avg quality score: 75+ (threshold: 75+) ✓
✅ Production ready: 80%+ (threshold: 80%+) ✓

Check 4/4: Critical issues...
✅ No critical blocking issues ✓

════════════════════════════════════════════════════════
  VALIDATION SUMMARY
════════════════════════════════════════════════════════
✅ team_offense_game_summary: ALL CHECKS PASSED ✓
```

### 2.3 Success Criteria
- ✅ Game count ≥ 5,600
- ✅ Success rate ≥ 95%
- ✅ Quality score ≥ 75
- ✅ Production ready ≥ 80%
- ✅ No critical blocking issues

### 2.4 If Validation Fails
```bash
# Review detailed logs
tail -100 logs/team_offense_backfill_phase1.log

# Check for specific errors
grep -i "error\|exception\|fail" logs/team_offense_backfill_phase1.log | tail -20

# Document issues and determine if blocking
```

---

## STEP 3: VALIDATE PHASE 2 (player_game_summary)

### 3.1 Run Shell Validation
```bash
cd /home/naji/code/nba-stats-scraper

bash scripts/validation/validate_player_summary.sh "2024-05-01" "2026-01-02"
```

### 3.2 Expected Output
```
════════════════════════════════════════════════════════
  VALIDATING PLAYER_GAME_SUMMARY
════════════════════════════════════════════════════════
Check 1/5: Record count...
✅ Record count: 35,000+ (threshold: 35,000+) ✓

Check 2/5: Feature coverage (CRITICAL)...
✅ minutes_played: 99%+ (threshold: 99%+) ✓
✅ usage_rate: 95%+ (threshold: 95%+) ✓
⚠️  shot_zones: 40%+ (threshold: 40%+) ✓ (acceptable)

Check 3/5: Quality metrics...
✅ Avg quality score: 75+ (threshold: 75+) ✓
✅ Production ready: 95%+ (threshold: 95%+) ✓

Check 4/5: Critical issues...
✅ No critical blocking issues ✓

Check 5/5: Spot check...
[Sample data displayed]

════════════════════════════════════════════════════════
  VALIDATION SUMMARY
════════════════════════════════════════════════════════
✅ player_game_summary: CRITICAL CHECKS PASSED ✓
```

### 3.3 Run Python Comprehensive Validation (Optional but Recommended)
```bash
cd /home/naji/code/nba-stats-scraper

PYTHONPATH=. python3 scripts/validation/validate_backfill_features.py \
  --start-date 2024-05-01 \
  --end-date 2026-01-02 \
  --full \
  --verbose
```

### 3.4 Success Criteria
- ✅ Records ≥ 35,000
- ✅ minutes_played coverage ≥ 99% (CRITICAL)
- ✅ usage_rate coverage ≥ 95% (CRITICAL)
- ✅ shot_zones coverage ≥ 40% (acceptable if lower due to format changes)
- ✅ Quality score ≥ 75
- ✅ Production ready ≥ 95%

---

## STEP 4: GO/NO-GO DECISION (Phase 1/2)

### 4.1 Decision Matrix

**GO CRITERIA** (All must be true):
- ✅ Phase 1 validation: PASSED
- ✅ Phase 2 validation: PASSED
- ✅ minutes_played ≥ 99%
- ✅ usage_rate ≥ 95%
- ✅ No critical blocking issues

**If GO**:
```bash
echo "✅ GO DECISION: Proceeding to Phase 4 execution"
echo "Confidence level: HIGH"
echo "Ready to execute Phase 4 backfill"
```

**If NO-GO**:
```bash
echo "❌ NO-GO DECISION: Issues must be resolved"
echo "Blockers:"
echo "  - [List specific failures]"
echo "Remediation plan:"
echo "  - [Document fix steps]"
echo "DO NOT proceed to Phase 4 until resolved"
```

---

## STEP 5: PRE-FLIGHT CHECK FOR PHASE 4

### 5.1 Verify Phase 3 Readiness
```bash
cd /home/naji/code/nba-stats-scraper

python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2024-10-01 \
  --end-date 2026-01-02 \
  --verbose
```

### 5.2 Expected Output
```
✅ Pre-flight check PASSED: Phase 3 data is ready for Phase 4 processing

Layer 3 Coverage Analysis:
  player_game_summary: 1,815 games (100%)
  team_defense_game_summary: 1,815 games (100%)
  team_offense_game_summary: 1,815 games (100%)
  upcoming_player_game_context: Coverage OK
  upcoming_team_game_context: Coverage OK

Phase 4 can proceed safely.
```

### 5.3 If Pre-flight Fails
**DO NOT proceed to Phase 4** - Phase 3 gaps will cause Phase 4 gaps

---

## STEP 6: EXECUTE PHASE 4 BACKFILL

### 6.1 Create Execution Script
```bash
cd /home/naji/code/nba-stats-scraper

cat > /tmp/run_phase4_backfill_2024_25.py << 'SCRIPT_EOF'
#!/usr/bin/env python3
"""Execute Phase 4 backfill for 2024-25 season (207 processable dates)"""

import requests
import subprocess
import time
import csv
from datetime import datetime

PHASE4_URL = "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date"
DATES_FILE = "/tmp/phase4_processable_dates.csv"
LOG_FILE = f"/tmp/phase4_backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

def get_token():
    """Get GCP auth token"""
    result = subprocess.run(['gcloud', 'auth', 'print-identity-token'],
                          capture_output=True, text=True, check=True)
    return result.stdout.strip()

def load_dates():
    """Load processable dates from CSV"""
    with open(DATES_FILE, 'r') as f:
        reader = csv.DictReader(f)
        return [row['date'] for row in reader]

def process_date(date_str, token, log_f):
    """Process a single date"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"analysis_date": date_str, "backfill_mode": True, "processors": []}

    start = time.time()
    try:
        resp = requests.post(PHASE4_URL, json=payload, headers=headers, timeout=300)
        elapsed = time.time() - start

        if resp.status_code == 200:
            results = resp.json().get('results', [])
            success = sum(1 for r in results if r.get('status') == 'success')
            total = len(results)
            msg = f"✅ {date_str}: {elapsed:.1f}s - {success}/{total} processors"
            print(msg)
            log_f.write(msg + "\n")
            log_f.flush()
            return True
        else:
            msg = f"❌ {date_str}: Error {resp.status_code} - {resp.text[:100]}"
            print(msg)
            log_f.write(msg + "\n")
            log_f.flush()
            return False
    except Exception as e:
        elapsed = time.time() - start
        msg = f"❌ {date_str}: Exception {str(e)[:100]}"
        print(msg)
        log_f.write(msg + "\n")
        log_f.flush()
        return False

def main():
    dates = load_dates()
    print("=" * 70)
    print("PHASE 4 BACKFILL - 2024-25 SEASON")
    print("=" * 70)
    print(f"Total dates: {len(dates)}")
    print(f"Log file: {LOG_FILE}")
    print(f"Started: {datetime.now()}")
    print("")

    token = get_token()

    with open(LOG_FILE, 'w') as log_f:
        log_f.write(f"Phase 4 Backfill Started: {datetime.now()}\n")
        log_f.write(f"Total dates: {len(dates)}\n\n")

        success_count = 0
        for i, date in enumerate(dates, 1):
            print(f"\n[{i}/{len(dates)}] {date}")
            if process_date(date, token, log_f):
                success_count += 1

            # Progress update every 10 dates
            if i % 10 == 0:
                pct = (i / len(dates)) * 100
                success_pct = (success_count / i) * 100
                print(f"\n--- Progress: {i}/{len(dates)} ({pct:.1f}%) - {success_count} successful ({success_pct:.1f}%) ---\n")

            time.sleep(2)  # Rate limiting

    print("\n" + "=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)
    print(f"Success: {success_count}/{len(dates)} ({success_count/len(dates)*100:.1f}%)")
    print(f"Log: {LOG_FILE}")

if __name__ == "__main__":
    main()
SCRIPT_EOF

chmod +x /tmp/run_phase4_backfill_2024_25.py
```

### 6.2 Execute Backfill
```bash
# Run backfill (will take 3-4 hours)
python3 /tmp/run_phase4_backfill_2024_25.py 2>&1 | tee /tmp/phase4_backfill_console.log
```

### 6.3 Monitor Progress (in separate terminal)
```bash
# Watch progress in real-time
tail -f /tmp/phase4_backfill_console.log

# Check progress summary
grep "Progress:" /tmp/phase4_backfill_console.log | tail -5
```

### 6.4 Expected Timeline
- **Start**: When Phase 1/2 validation passes
- **Duration**: 3-4 hours (207 dates × 100 sec/date ≈ 5.75 hours, with 2 sec gaps ≈ 6.5 hours total)
- **Rate**: ~60 dates/hour
- **Success rate**: Expected >90%

---

## STEP 7: VALIDATE PHASE 4 RESULTS

### 7.1 Quick Coverage Check
```bash
bash /tmp/run_phase4_validation.sh
```

### 7.2 Manual Coverage Validation
```bash
bq query --use_legacy_sql=false --format=pretty '
WITH p3 AS (
  SELECT COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= "2024-10-01"
),
p4 AS (
  SELECT COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= "2024-10-01"
)
SELECT
  p3.games as phase3_analytics_games,
  p4.games as phase4_precompute_games,
  ROUND(100.0 * p4.games / p3.games, 1) as coverage_pct,
  CASE
    WHEN 100.0 * p4.games / p3.games >= 88.0 THEN "✅ PASS"
    WHEN 100.0 * p4.games / p3.games >= 80.0 THEN "⚠️  MARGINAL"
    ELSE "❌ FAIL"
  END as status
FROM p3, p4
'
```

### 7.3 Expected Results
```
+----------------------+-----------------------+---------------+--------+
| phase3_analytics_... | phase4_precompute_... | coverage_pct  | status |
+----------------------+-----------------------+---------------+--------+
|                 1815 |                  1600 |          88.1 | ✅ PASS |
+----------------------+-----------------------+---------------+--------+
```

### 7.4 Bootstrap Period Validation
```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT
  game_date,
  COUNT(*) as records
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= "2024-10-22" AND game_date <= "2024-11-05"
GROUP BY game_date
ORDER BY game_date
'
```

**Expected**: No rows returned (bootstrap period correctly excluded)

### 7.5 Sample Data Quality Check
```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT
  game_date,
  COUNT(DISTINCT player_id) as unique_players,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= "2024-11-06"
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 10
'
```

**Expected**: Reasonable record counts (100-300 per date)

### 7.6 Validation Success Criteria
- ✅ Coverage ≥ 88% (accounts for bootstrap)
- ✅ Bootstrap dates (Oct 22 - Nov 5) correctly excluded
- ✅ NULL rate < 5%
- ✅ Sample data looks reasonable
- ✅ All 4 processors completed successfully

---

## STEP 8: FINAL GO/NO-GO DECISION (ML Training)

### 8.1 Complete Checklist
```bash
# Create decision summary
cat << 'EOF'
════════════════════════════════════════════════════════
  ML TRAINING GO/NO-GO DECISION
════════════════════════════════════════════════════════

PHASE 1 VALIDATION:
[ ] team_offense validation: PASS/FAIL
[ ] Games: [COUNT] (≥ 5,600 required)
[ ] Success rate: [%] (≥ 95% required)

PHASE 2 VALIDATION:
[ ] player_game_summary validation: PASS/FAIL
[ ] Records: [COUNT] (≥ 35,000 required)
[ ] minutes_played: [%] (≥ 99% required - CRITICAL)
[ ] usage_rate: [%] (≥ 95% required - CRITICAL)

PHASE 4 VALIDATION:
[ ] Coverage: [%] (≥ 88% required)
[ ] Bootstrap period: EXCLUDED/PRESENT
[ ] NULL rate: [%] (< 5% required)

OVERALL ASSESSMENT:
[ ] All critical checks PASSED
[ ] No blocking issues identified
[ ] Data quality acceptable for ML training

DECISION: GO / NO-GO
CONFIDENCE: HIGH / MEDIUM / LOW
REASONING: [Document rationale]

NEXT ACTION:
- If GO: Proceed to Session 5 (ML Training)
- If NO-GO: Document blockers and remediation plan
EOF
```

### 8.2 If GO
```bash
echo "✅ ML TRAINING: GO DECISION"
echo "Ready to proceed to Session 5"
echo "Expected MAE: 3.70-4.20 (baseline: 4.27)"
echo "Training duration: ~1-2 hours"
```

### 8.3 If NO-GO
```bash
echo "❌ ML TRAINING: NO-GO DECISION"
echo "Blockers identified: [LIST]"
echo "Remediation required before proceeding"
echo "DO NOT start Session 5 until resolved"
```

---

## STEP 9: DOCUMENTATION

### 9.1 Fill Session 4 Template
```bash
# Update template with actual results
nano docs/09-handoff/2026-01-04-SESSION-4-PHASE4-EXECUTION.md
```

### 9.2 Key Sections to Complete
- Orchestrator final report
- Phase 1 validation results
- Phase 2 validation results
- GO/NO-GO decision (Phase 1/2)
- Phase 4 execution details
- Phase 4 validation results
- GO/NO-GO decision (ML training)
- Final data state
- Key findings & insights

### 9.3 Create Handoff for Session 5
```bash
cat > docs/09-handoff/2026-01-04-SESSION-5-ML-TRAINING-READY.md << 'EOF'
# Session 5: ML Training Ready

PREPARATION COMPLETE:
- Phase 1: [RESULTS]
- Phase 2: [RESULTS]
- Phase 4: [RESULTS]

DATA STATE:
- Phase 3: [SUMMARY]
- Phase 4: [COVERAGE]%
- Features: minutes_played [%], usage_rate [%]

READY FOR ML TRAINING: ✅/❌

READ FIRST:
- docs/09-handoff/2026-01-04-SESSION-4-PHASE4-EXECUTION.md
- docs/09-handoff/2026-01-03-SESSION-2-ML-TRAINING-REVIEW.md

NEXT STEPS:
1. Train XGBoost v5 model
2. Target: MAE < 4.27
3. Validate results
EOF
```

---

## 📊 QUICK REFERENCE

### Time Estimates
- Orchestrator review: 10 min
- Phase 1 validation: 15 min
- Phase 2 validation: 15 min
- GO/NO-GO decision: 5 min
- Pre-flight check: 5 min
- Phase 4 execution: 3-4 hours ⏰
- Phase 4 validation: 30 min
- Documentation: 30 min

### Total Session 4 Time
**Active work**: ~2 hours
**Waiting (Phase 4 running)**: ~3-4 hours
**Total**: ~5-6 hours

---

## ⚠️ TROUBLESHOOTING

### Issue: Phase 4 API Returns Errors
```bash
# Check Cloud Run logs
gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors"' \
  --limit 50 \
  --format=json

# Verify auth token
gcloud auth print-identity-token

# Test single date manually
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2024-11-18", "backfill_mode": true}'
```

### Issue: Coverage Below 88%
```bash
# Check which dates are missing
bq query --use_legacy_sql=false '
WITH all_dates AS (
  SELECT DISTINCT DATE(game_date) as date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= "2024-10-01"
),
phase4_dates AS (
  SELECT DISTINCT DATE(game_date) as date
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= "2024-10-01"
)
SELECT
  a.date,
  "MISSING" as status
FROM all_dates a
LEFT JOIN phase4_dates p4 ON a.date = p4.date
WHERE p4.date IS NULL
ORDER BY a.date
LIMIT 50
'
```

### Issue: High NULL Rates
```bash
# Check NULL patterns
bq query --use_legacy_sql=false '
SELECT
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(*) as total,
  COUNTIF(advanced_metrics IS NULL) as nulls,
  ROUND(100.0 * COUNTIF(advanced_metrics IS NULL) / COUNT(*), 1) as null_pct
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= "2024-10-01"
GROUP BY month
ORDER BY month
'
```

---

**Document Status**: Ready for execution
**Last Updated**: January 4, 2026
**Next Update**: After Session 4 completion
