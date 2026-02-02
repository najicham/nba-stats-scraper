# Session 76 Start Prompt

Copy the prompt below and paste it into the next chat session:

---

## Session 76: Fix Critical Validation Issues

Hello! Session 75 ran a comprehensive daily validation for Jan 31 data and found **3 P1 CRITICAL issues** and **3 P2 HIGH issues** that need immediate attention.

Please read the full handoff document first:
```bash
cat docs/09-handoff/2026-02-01-SESSION-75-VALIDATION-ISSUES.md
```

Then work through this checklist systematically:

### 🔴 CRITICAL Priority (Next 45 Minutes)

#### [ ] Issue 1: Fix Phase 3 Completion (15 min)
**Problem**: Only 3/5 Phase 3 processors completed. Missing `player_game_summary` (CRITICAL!) and `upcoming_team_game_context`. Phase 4 NOT triggered, entire pipeline stalled.

**Actions**:
```bash
# 1. Check logs for player_game_summary errors
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=200 \
  | grep -B 10 -A 10 "player_game_summary\|AttributeError\|registry\|ERROR"

# 2. Verify data exists in BigQuery
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records, COUNT(DISTINCT game_id) as games
FROM nba_analytics.player_game_summary
WHERE game_date = DATE('2026-01-31')"

# Expected: 212 records, 6 games
# If data exists, processor failed at finalize step
```

**If data exists** (212 records):
- Suspected: Session 60 registry bug (`self.registry` vs `self.registry_handler`)
- Check if fix deployed
- Manually mark Phase 3 complete (see handoff doc for Python code)
- Trigger Phase 4 manually

**If data missing**:
- Check deployment drift
- Check for quota errors blocking writes
- May need to reprocess

#### [ ] Issue 2: Deploy BigQuery Quota Batching Fix (10 min)
**Problem**: 5 rate limit errors at 16:46 UTC. "Exceeded rate limits: too many table dml insert operations"

**Actions**:
```bash
# 1. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 2. Verify batching fix exists in repo
git log --oneline | grep -i "batch\|quota" | head -5

# 3. If not deployed, deploy all processor services
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
```

#### [ ] Issue 3: Fix Feature Store Vegas Line Coverage (20 min)
**Problem**: Only 40.1% of feature store records have Vegas line (expected ≥80%). This directly degrades prediction quality and likely explains V9 hit rate drop to 51.6%.

**Actions**:
```bash
# 1. Check if Session 62 fix is deployed
./bin/check-deployment-drift.sh nba-phase4-precompute-processors
git log --oneline --grep="Session 62\|betting.*feature" | head -5

# 2. Check upstream data (is issue in Phase 3 or Phase 4?)
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(current_points_line > 0) as has_line,
  ROUND(100.0 * COUNTIF(current_points_line > 0) / COUNT(*), 1) as pct
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"

# If Phase 3 has >80% coverage → Issue is Phase 4 join
# If Phase 3 has ~40% coverage → Issue is Phase 3 betting workflow
```

**If Session 62 fix NOT deployed**:
- Deploy fix
- Regenerate feature store for last 7 days (see handoff doc for loop)

**If fix IS deployed**:
- Check when feature store was last generated
- If before Session 62 deployment → Regenerate

---

### 🟡 HIGH Priority (Next 1-2 Hours)

#### [ ] Issue 4: Run Grading Backfill for Ensemble Models (30 min)
**Problem**: Ensemble models have <20% grading coverage (ensemble_v1: 2.8%, ensemble_v1_1: 19.1%). Can't assess if ensemble is working.

**Actions**:
```bash
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-25 \
  --end-date 2026-02-01 \
  --systems catboost_v8,catboost_v9,ensemble_v1,ensemble_v1_1
```

#### [ ] Issue 5: Investigate V9 Model Degradation (30 min)
**Problem**: catboost_v9 hit rate dropped to 51.6% week of Jan 25 (below 55% threshold).

**Actions**:
```bash
# 1. Check if low hit rate correlates with low Vegas line coverage
bq query --use_legacy_sql=false "
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  COUNTIF(line_value IS NOT NULL) as has_line,
  ROUND(100.0 * COUNTIF(line_value IS NOT NULL) / COUNT(*), 1) as line_pct
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE('2026-01-25')
GROUP BY week"

# If line_pct is low for week of Jan 25 → Issue #3 is causing Issue #5!

# 2. Run tier-specific analysis
/hit-rate-analysis
```

**Hypothesis**: V9's hit rate drop is caused by missing Vegas lines (Issue #3). After fixing Issue #3, V9 performance should improve.

#### [ ] Issue 6: Backfill Historical Odds Data (20 min)
**Problem**: Jan 26-27 missing most game lines (43% and 14% coverage).

**Actions**:
```bash
# 1. Check if data exists in GCS
gsutil ls gs://nba-scraped-data/odds-api/game-lines/2026/01/26/ | wc -l
gsutil ls gs://nba-scraped-data/odds-api/game-lines/2026/01/27/ | wc -l

# If data exists → Run processor
# If data missing → Run historical scraper (see handoff doc)
```

---

### 📋 Verification After Fixes

Once you've addressed the critical issues, verify the pipeline is healthy:

```bash
# 1. Check Phase 3 is now 5/5
python3 -c "from google.cloud import firestore; db = firestore.Client(); \
  doc = db.collection('phase3_completion').document('2026-02-01').get(); \
  data = doc.to_dict(); \
  print(f'Complete: {len([k for k in data.keys() if not k.startswith(\"_\")])}/5')"

# 2. Verify feature store Vegas line coverage improved
bq query --use_legacy_sql=false "
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33"

# Expected: >80%

# 3. Check grading coverage improved
bq query --use_legacy_sql=false "
SELECT system_id,
  COUNT(*) as predictions,
  (SELECT COUNT(*) FROM nba_predictions.prediction_accuracy pa
   WHERE pa.system_id = p.system_id
   AND pa.game_date >= DATE('2026-01-25')) as graded
FROM nba_predictions.player_prop_predictions p
WHERE game_date >= DATE('2026-01-25')
GROUP BY system_id"

# Expected: All models >80% graded

# 4. Run quick validation
python scripts/validate_tonight_data.py --date 2026-01-31
```

---

### 📝 Documentation After Completion

Please create a brief Session 76 handoff documenting:
1. Which issues were fixed
2. Root causes confirmed
3. Any issues that require follow-up
4. Current pipeline status

Use this template:
```bash
# Create handoff
cat > docs/09-handoff/2026-02-01-SESSION-76-FIXES-APPLIED.md << 'EOF'
# Session 76 - Validation Issues Fixed - Feb 1, 2026

## Summary
[One-line summary of what was accomplished]

## Issues Addressed

### Issue 1: Phase 3 Completion
- Root cause: [what you found]
- Fix applied: [what you did]
- Status: ✅ Fixed / ⚠️ Partial / ❌ Needs follow-up

[Repeat for each issue]

## Verification Results
[Paste output of verification commands]

## Outstanding Issues
[Any issues that still need attention]

## Next Session Recommendations
[What should Session 77 focus on?]
EOF
```

---

### ⚠️ Important Notes

1. **Work Systematically**: Fix Phase 3 FIRST (it blocks Phase 4 and Phase 5)
2. **Verify Deployments**: Use `./bin/check-deployment-drift.sh` before investigating bugs
3. **Check Logs Thoroughly**: Don't assume - verify with actual log outputs
4. **Document Findings**: The handoff doc has space for root cause confirmation
5. **Vegas Line Coverage is KEY**: This likely explains model degradation

### 🔗 Key Reference

Full details in: `docs/09-handoff/2026-02-01-SESSION-75-VALIDATION-ISSUES.md`

---

**Start with the Critical issues in order (1 → 2 → 3). They have dependencies.**

Good luck! 🚀
