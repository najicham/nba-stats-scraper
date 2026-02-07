# Session 147 Prompt

Read these handoff docs for context:
- `docs/09-handoff/2026-02-07-SESSION-146-HANDOFF.md` - Cache miss tracking, Cloud Build, architectural insight
- `docs/08-projects/current/feature-completeness/00-PROJECT-OVERVIEW.md` - Full project overview

## Uncommitted Changes - Commit First

Session 146 left uncommitted changes. Commit before doing anything else:
```bash
git add cloudbuild.yaml bin/cloud-deploy.sh \
  data_processors/precompute/ml_feature_store/feature_extractor.py \
  data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  data_processors/precompute/player_daily_cache/player_daily_cache_processor.py \
  schemas/bigquery/predictions/04_ml_feature_store_v2.sql \
  docs/08-projects/current/feature-completeness/00-PROJECT-OVERVIEW.md \
  docs/09-handoff/NEXT-SESSION-PROMPT.md \
  docs/09-handoff/2026-02-07-SESSION-146-HANDOFF.md
git commit -m "feat: Add cache miss tracking and Cloud Build deploy (Session 146)"
```

## Immediate Tasks

### 1. Update Validation Skills for Cache Miss Tracking (PRIORITY)

Session 146 added `cache_miss_fallback_used BOOL` to `ml_feature_store_v2` and deployed it. Now update our validation tooling to surface this:

**Where to add checks:**
- `/validate-daily` skill - add a cache miss rate check
- Any pipeline canary monitoring

**What to check:**
```sql
-- Daily predictions: cache miss rate should be ~0%
-- Backfill dates: 5-15% is expected
SELECT game_date,
  COUNTIF(cache_miss_fallback_used) as cache_misses,
  COUNT(*) as total,
  ROUND(COUNTIF(cache_miss_fallback_used) / COUNT(*) * 100, 1) as miss_rate_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1;
```

**Alert logic:** If `miss_rate_pct > 0%` for today's date (non-backfill), flag as issue -- means `upcoming_player_game_context` and `player_daily_cache` have a player list mismatch.

**Post-game reconciliation (user request):** After boxscores arrive, compare who played (`player_game_summary`) vs who was cached (`player_daily_cache`). This identifies gaps in `upcoming_player_game_context` for continuous improvement. Could be added to validate-daily as a next-day check.

### 2. Deploy Prediction Coordinator

Still needs deploy from Session 145 (vegas optional gating). Use the new cloud deploy script:
```bash
./bin/cloud-deploy.sh prediction-coordinator
```
This is the first real test of the Cloud Build deploy. If it fails, debug and fix the script.

After deploying, verify:
```bash
gcloud run services describe prediction-coordinator --region=us-west2 --format="value(metadata.labels.commit-sha)"
# Should show recent commit
```

### 3. Verify Vegas Optional Impact

After coordinator is deployed, check that quality-ready rates improved:
```sql
SELECT game_date,
  COUNT(*) as total_records,
  COUNTIF(is_quality_ready) as quality_ready,
  ROUND(COUNTIF(is_quality_ready) / COUNT(*) * 100, 1) as pct_ready
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 1;
```
Before: ~37-45% quality_ready. Expected after: ~90-95%.

### 4. Check ML Feature Store Backfill

A backfill was running (2025-11-04 to 2026-02-06). Check if it completed:
```bash
# Check checkpoint
cat /tmp/backfill_checkpoints/ml_feature_store_2025-11-04_2026-02-06.json 2>/dev/null | python -m json.tool | tail -5
```

## Key Architecture (from Session 146)

**Daily predictions:** Both `PlayerDailyCacheProcessor` and `MLFeatureStoreProcessor` use `upcoming_player_game_context WHERE game_date = TODAY`. Same source = same players = no cache misses expected.

**Backfill:** Feature store uses `player_game_summary` (who actually played) while historical cache used `upcoming_player_game_context` (who was expected). The Session 144 fallback (`_compute_cache_fields_from_games()`) handles mismatches. `cache_miss_fallback_used` now tracks these.

## Deployment State

| Service | Status | Notes |
|---------|--------|-------|
| nba-phase4-precompute-processors | **Deployed** | Cache miss tracking |
| nba-phase3-analytics-processors | Deployed | |
| nba-phase2-raw-processors | Deployed | |
| prediction-worker | Deployed | Vegas optional |
| prediction-coordinator | **NEEDS DEPLOY** | Vegas optional gating |
