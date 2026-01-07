# 📋 Session 4 Quick Reference Guide

**1-Page Summary for Fast Execution**

---

## ⚡ QUICK START (When Orchestrator Completes)

### 1. Check Completion (1 min)
```bash
tail -50 logs/orchestrator_20260103_134700.log | grep -E "COMPLETE|VALIDATION"
```

### 2. Validate Phase 1 & 2 (30 min)
```bash
cd /home/naji/code/nba-stats-scraper
bash scripts/validation/validate_team_offense.sh "2021-10-19" "2026-01-02"
bash scripts/validation/validate_player_summary.sh "2024-05-01" "2026-01-02"
```

### 3. GO Decision (2 min)
✅ **GO if**: Both validations PASS + minutes_played ≥99% + usage_rate ≥95%
❌ **NO-GO if**: Any critical check fails

### 4. Execute Phase 4 (3-4 hours)
```bash
python3 /tmp/run_phase4_backfill_2024_25.py 2>&1 | tee /tmp/phase4_backfill_console.log
```

### 5. Validate Phase 4 (30 min)
```bash
bash /tmp/run_phase4_validation.sh
```
**Target**: Coverage ≥ 88%

---

## 📊 SUCCESS CRITERIA

| Phase | Metric | Threshold | Critical? |
|-------|--------|-----------|-----------|
| Phase 1 | Games | ≥ 5,600 | ✅ Yes |
| Phase 1 | Success rate | ≥ 95% | ✅ Yes |
| Phase 2 | Records | ≥ 35,000 | ✅ Yes |
| Phase 2 | minutes_played | ≥ 99% | ✅ YES |
| Phase 2 | usage_rate | ≥ 95% | ✅ YES |
| Phase 2 | shot_zones | ≥ 40% | ⚠️  No (acceptable lower) |
| Phase 4 | Coverage | ≥ 88% | ✅ Yes |
| Phase 4 | NULL rate | < 5% | ✅ Yes |

---

## 🎯 KEY FILES

| Purpose | File Path |
|---------|-----------|
| Phase 4 dates | `/tmp/phase4_processable_dates.csv` |
| Backfill script | `/tmp/run_phase4_backfill_2024_25.py` |
| Validation script | `/tmp/run_phase4_validation.sh` |
| Validation queries | `/tmp/phase4_validation_queries.sql` |
| Execution commands | `docs/09-handoff/2026-01-04-SESSION-4-EXECUTION-COMMANDS.md` |

---

## ⏰ TIMELINE

| Event | Time (PST) | Duration |
|-------|------------|----------|
| Phase 1 complete | ~20:42 | - |
| Validate Phase 1/2 | ~20:45 | 30 min |
| GO decision | ~21:15 | 5 min |
| Start Phase 4 | ~21:20 | - |
| Phase 4 complete | ~01:00 | 3-4 hrs |
| Validate Phase 4 | ~01:00 | 30 min |
| Document results | ~01:30 | 30 min |
| **Session 4 complete** | ~02:00 | - |

---

## 🚨 DECISION POINTS

### After Phase 1/2 Validation
- **GO**: All checks pass → Execute Phase 4
- **NO-GO**: Any critical fails → Investigate & fix

### After Phase 4 Validation
- **GO**: Coverage ≥88% → Ready for ML (Session 5)
- **NO-GO**: Coverage <80% → Investigate gaps

---

## 📞 TROUBLESHOOTING

### Phase 4 API errors?
```bash
# Test auth
gcloud auth print-identity-token

# Check Cloud Run logs
gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors"' --limit 20
```

### Coverage too low?
```bash
# Find missing dates
bq query --use_legacy_sql=false '
WITH missing AS (
  SELECT DISTINCT DATE(game_date) as date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= "2024-10-01"
  EXCEPT DISTINCT
  SELECT DISTINCT DATE(game_date)
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= "2024-10-01"
)
SELECT * FROM missing ORDER BY date LIMIT 20'
```

---

## 💡 CRITICAL FACTS

1. **88% coverage is MAXIMUM** (not 100%) - first 14 days of season skipped by design
2. **Bootstrap period**: Oct 22 - Nov 5, 2024 will have NO Phase 4 data (this is correct!)
3. **Processing time**: ~100 seconds per date (tested with samples)
4. **207 dates** to backfill for 2024-25 season
5. **Sample tests**: 3/3 passed (100% success rate) ✅

---

## 📝 QUICK VALIDATION

### One-Liner Coverage Check
```bash
bq query --use_legacy_sql=false --format=csv "SELECT ROUND(100.0 * (SELECT COUNT(DISTINCT game_id) FROM \`nba-props-platform.nba_precompute.player_composite_factors\` WHERE game_date >= '2024-10-01') / (SELECT COUNT(DISTINCT game_id) FROM \`nba-props-platform.nba_analytics.player_game_summary\` WHERE game_date >= '2024-10-01'), 1)" | tail -1
```
**Expected**: ~88.0

### One-Liner Bootstrap Check
```bash
bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) FROM \`nba-props-platform.nba_precompute.player_composite_factors\` WHERE game_date >= '2024-10-22' AND game_date <= '2024-11-05'" | tail -1
```
**Expected**: 0

---

## 🎯 NEXT SESSION (5)

**When**: After Session 4 completes with GO decision
**Duration**: 3-3.5 hours
**Goal**: Train XGBoost v5, beat 4.27 MAE baseline
**Command**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.
.venv/bin/python ml/train_real_xgboost.py
```

---

**Status**: Ready for execution
**ETA**: Phase 1 completes ~20:42 PST tonight
**Preparation**: ✅ Complete
