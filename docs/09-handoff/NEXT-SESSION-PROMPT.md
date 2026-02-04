# Next Session Prompt - Final Validation, Deployment & Testing

**Copy this entire prompt to start the next session**

---

I'm continuing work on the NBA prediction system after Session 114 completed major data quality fixes.

## What Was Done in Session 114

Session 114 fixed **critical data quality bugs** in two phases:

**Phase 1 (Deployed ✅):**
- Fixed early season dynamic thresholds for 2 processors
- Regenerated November shot_zone data
- Enhanced validation infrastructure (11 new checks)

**Phase 2 (Code Complete, NOT Deployed ❌):**
- Found 2 CRITICAL bugs where DNP games polluted L5/L10 calculations
- Caused 28-point errors for star players (Jokic: 6.2 vs 34.2!)
- Fixed both bugs in commit 981ff460
- Comprehensive audit: 275 files scanned

## Your Mission

Complete a 3-phase workflow:

### Phase 1: Final Comprehensive Validation Scan (60-90 min)

**Don't just scan for DNP bugs - scan for ALL data quality issues:**

1. **Run comprehensive data quality audit:**
   - Check for ANY averaging bugs (not just DNP)
   - Check for incorrect window calculations
   - Check for missing null checks
   - Check for incorrect date filtering
   - Check for SQL injection risks
   - Check for any pattern that could corrupt data

2. **Use the Explore agent with "very thorough" mode:**
   ```
   Explore the codebase for ANY data quality bugs that could affect predictions.
   Scope: data_processors/, predictions/, shared/
   Focus: Calculations, aggregations, averages, window functions
   Check for: Missing null checks, incorrect filters, wrong windows, SQL issues
   ```

3. **Specific areas to audit:**
   - Phase 3 analytics: ALL calculators and aggregators
   - Phase 4 precompute: ALL processors and utilities
   - Phase 5 predictions: Coordinator and worker
   - Shared utilities: BigQuery ops, data loaders

4. **Patterns to search:**
   - `.mean()`, `.sum()`, `.std()`, `.head(N)` without null checks
   - `AVG()`, `SUM()`, `COUNT()` in SQL without WHERE filters
   - Date comparisons without timezone handling
   - Rolling windows without proper ordering
   - String concatenation in SQL (injection risk)

5. **Create audit report:**
   - What was checked (files, patterns)
   - What was found (bugs, risks, edge cases)
   - What needs fixing (if anything)
   - Confidence level (can we deploy?)

**Expected outcome:** Either "all clear" or "found N issues that need fixing"

### Phase 2: Deploy DNP Fixes (30 min)

**Only proceed if Phase 1 audit is clean (or new issues are fixed)**

1. **Check current deployment status:**
   ```bash
   ./bin/whats-deployed.sh
   ```

2. **Deploy Phase 3 analytics:**
   ```bash
   ./bin/deploy-service.sh nba-phase3-analytics-processors
   ```

3. **Deploy Phase 4 precompute:**
   ```bash
   ./bin/deploy-service.sh nba-phase4-precompute-processors
   ```

4. **Verify deployments show commit 981ff460 or later:**
   ```bash
   gcloud run services describe nba-phase3-analytics-processors \
     --region=us-west2 --format="value(metadata.labels.commit-sha)"

   gcloud run services describe nba-phase4-precompute-processors \
     --region=us-west2 --format="value(metadata.labels.commit-sha)"
   ```

### Phase 3: Validate Fixes & Test (30 min)

1. **Run diagnostic query for Phase 3 fix:**
   ```sql
   -- Should return 0 rows with >1pt difference
   WITH manual_calc AS (
     SELECT player_lookup, game_date,
       ROUND(AVG(points) OVER (
         PARTITION BY player_lookup ORDER BY game_date
         ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
       ), 1) as manual_l5
     FROM nba_analytics.player_game_summary
     WHERE game_date >= '2025-12-01'
       AND points IS NOT NULL AND is_dnp = FALSE
   )
   SELECT
     f.player_lookup, f.game_date,
     f.points_avg_last_5 as feature_l5,
     m.manual_l5,
     ROUND(ABS(f.points_avg_last_5 - m.manual_l5), 1) as diff
   FROM nba_analytics.upcoming_player_game_context f
   JOIN manual_calc m USING (player_lookup, game_date)
   WHERE f.game_date >= '2026-01-01'
     AND ABS(f.points_avg_last_5 - m.manual_l5) > 1.0
   ORDER BY diff DESC
   LIMIT 20;
   ```

2. **Spot-check Jokic (was showing 6.2, should be ~34):**
   ```sql
   SELECT player_lookup, game_date, points_avg_last_5
   FROM nba_analytics.upcoming_player_game_context
   WHERE player_lookup = 'nikolajokic'
     AND game_date >= '2026-02-01'
   ORDER BY game_date DESC
   LIMIT 5;
   ```

3. **Check if data regeneration is needed:**
   - If diagnostic queries still show errors, data needs regeneration
   - Phase 3 may need reprocessing for recent dates
   - Phase 4 may need cache regeneration

4. **Run validation skills:**
   ```bash
   /spot-check-features
   /validate-daily
   ```

## Important Files to Reference

**Main handoff doc:**
- `docs/09-handoff/2026-02-04-SESSION-114-FINAL-HANDOFF.md`

**Audit report:**
- `docs/09-handoff/2026-02-04-SESSION-114-DNP-BUG-AUDIT-COMPLETE.md`

**Code fixes (commit 981ff460):**
- `data_processors/analytics/upcoming_player_game_context/player_stats.py`
- `data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py`

**Validation queries:**
- In Phase 3 section above
- In SESSION-114-FINAL-HANDOFF.md

## Key Context

**What the DNP bugs were:**
- L5/L10 calculations included games where players didn't play (DNP)
- Example: Jokic had 2 DNPs in last 5 games
- Broken: (35 + 0 + 33 + 0 + 34) / 5 = 20.4 ❌
- Correct: (35 + 33 + 34) / 3 = 34.0 ✅
- Affected 20+ star players with 10-28 point errors

**What was fixed:**
```python
# Filter DNPs BEFORE averaging
played_games = historical_data[
    (historical_data['points'].notna()) &
    ((historical_data['points'] > 0) |
     (historical_data['minutes_played'].notna()))
]
last_5 = played_games.head(5)
```

**Why comprehensive scan matters:**
- Session 114 found bugs Sessions 113 missed
- Can't be too careful with prediction accuracy
- Better to find issues now than in production

## Decision Points

**After Phase 1 audit:**
- If ALL CLEAR → Proceed to Phase 2 (deploy)
- If ISSUES FOUND → Fix them first, then deploy
- If UNSURE → Investigate further, ask user

**After Phase 2 deployment:**
- If validation queries pass → Success! ✅
- If queries show errors → Data needs regeneration
- If Jokic still wrong → Something's not working

**After Phase 3 validation:**
- If everything looks good → Consider /model-experiment
- If data needs regen → Plan regeneration approach
- If issues persist → Debug and investigate

## Optional: Model Experiment (20 min)

**If everything validates successfully:**

1. Run model experiment to measure impact:
   ```bash
   /model-experiment
   ```

2. Compare V9 (buggy data) vs challenger (clean data)

3. Look for:
   - Hit rate improvements
   - Better calibration on DNP-prone stars
   - ROI improvements on medium/high quality picks

4. Decide: Retrain V10 or keep V9?

## Success Criteria

**Phase 1 (Audit):**
- [ ] Comprehensive scan complete
- [ ] All patterns checked
- [ ] Report generated
- [ ] Confidence level: HIGH

**Phase 2 (Deploy):**
- [ ] Both services deployed
- [ ] Commit sha verified (981ff460+)
- [ ] No deployment errors

**Phase 3 (Validate):**
- [ ] Diagnostic queries pass (0 errors)
- [ ] Jokic shows correct values (~34 not 6.2)
- [ ] Validation skills pass
- [ ] No new issues discovered

**Optional (Experiment):**
- [ ] Model experiment run
- [ ] Results analyzed
- [ ] V10 decision made

## What to Report Back

**Create a summary showing:**
1. Audit results (what was checked, what was found)
2. Deployment status (services deployed, commits verified)
3. Validation results (queries passed, spot-checks good)
4. Any issues encountered
5. Recommendation for next steps

## If Something Goes Wrong

**Deployment fails:**
- Check build logs in Cloud Run
- Verify Dockerfile hasn't changed
- Check service account permissions

**Validation queries show errors:**
- Data may not be regenerated yet
- Services may need time to process
- Check if processors are running

**New bugs found in audit:**
- Fix them before deploying
- Follow same pattern as Session 114
- Document thoroughly

**Can't verify fixes working:**
- Check service logs for errors
- Verify services are actually running new code
- May need to manually trigger processors

## Emergency Rollback

**If deployed code causes issues:**
```bash
# Rollback to previous revision
gcloud run services update-traffic nba-phase3-analytics-processors \
  --region=us-west2 --to-revisions=PREVIOUS_REVISION=100

gcloud run services update-traffic nba-phase4-precompute-processors \
  --region=us-west2 --to-revisions=PREVIOUS_REVISION=100
```

## Final Checklist

Before ending your session:
- [ ] All phases complete or documented why not
- [ ] Services deployed and verified
- [ ] Validation results documented
- [ ] Any new issues logged
- [ ] Next steps clear
- [ ] User informed of status

---

**Start with Phase 1** - Don't deploy anything until the audit is complete and clean!

**Be thorough** - This affects live predictions and real money!

**Document everything** - Next session may need to pick up where you left off!

Good luck! 🚀
