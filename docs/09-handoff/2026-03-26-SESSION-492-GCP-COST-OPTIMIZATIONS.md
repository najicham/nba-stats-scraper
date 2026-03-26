# Session 492 Handoff — GCP Cost Optimizations + Best Bets Doubles

**Date:** 2026-03-26
**Previous session:** Session 491 (GCP cost structure review — `2026-03-26-SESSION-491-GCP-COST-REVIEW.md`)

---

## What Was Accomplished This Session

Full GCP cost audit using parallel agents, followed by targeted optimizations. **~$49-54/month in estimated savings implemented.**

### Changes Already Live (deployed/pushed)

#### GCP Infrastructure (immediate effect)
| Change | Detail | Savings |
|--------|--------|---------|
| Deleted `monthly-retrain` CF + scheduler | DEPRECATED per CLAUDE.md, still running at 4Gi | ~$2-5/mo |
| Deleted 3 stale one-time schedulers | `mlb-resume-reminder-mar24`, `mlb-retrain-reminder-mar18`, `registry-health-check` | cleanup |
| Fixed `morning-deployment-check` maxInstances | 100 → 3 (all others are 3; 100 was a runaway risk) | risk fix |
| Set 4 orchestrators to min=0 | `phase3-to-phase4-orchestrator`, `phase4-to-phase5-orchestrator`, `phase5-to-phase6-orchestrator`, `phase3-to-grading` were all min=1 (paying 24/7) | **~$15/mo** |
| Artifact Registry cleanup policies | `nba-props` (58.4 GB), `cloud-run-source-deploy` (28.7 GB), `gcf-artifacts` (20.5 GB) — keep 5 most recent, delete untagged >7d | **~$11/mo** |

#### Code Fixes (commit `77095d94`, auto-deploying via Cloud Build)
| File | Fix | Savings |
|------|-----|---------|
| `orchestration/cleanup_processor.py:335` | Partition window 7 DAY → 1 DAY. Cleanup checks files from last 5h — 7-day window scanned 13 tables incl. 8GB bettingpros table unnecessarily | **~$16/mo** |
| `predictions/shared/batch_staging_writer.py:569` | Added `AND T.game_date = S.game_date` to MERGE ON clause for `player_prop_predictions`. Was scanning full 603K-row table (2.07 GB/run, hourly) | ~$2/mo |
| `data_processors/precompute/ml_feature_store/batch_writer.py:396` | Added `AND target.game_date = '{game_date}'` literal to MERGE ON clause. Was doing full 1 GB feature store scan every hourly write | ~$5/mo |

### BQ Cost Breakdown (from audit)
- **Total BQ: ~$4/day (~$120/month)**
- Default compute SA (CFs): $86/30d — biggest driver
- `bigdataball-puller` SA: $16/30d — cleanup query (fixed above)
- User queries: $11.80/30d
- Most expensive patterns: MERGE on `player_prop_predictions` (2.07 GB/run hourly), MERGE on `ml_feature_store_v2` (1.05 GB/run hourly)

---

## PRIORITY 1: Investigate Best Bets Doubles (Morning of 2026-03-26)

**Symptom:** Duplicate best bets picks seen this morning. Unknown root cause.

### Diagnostic queries to run first

```sql
-- 1. Find duplicate picks for today
SELECT player_lookup, system_id, recommendation, current_points_line,
       COUNT(*) as count,
       ARRAY_AGG(signal_status ORDER BY created_at) as statuses,
       ARRAY_AGG(FORMAT_TIMESTAMP('%H:%M', created_at) ORDER BY created_at) as created_times
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE()
GROUP BY 1,2,3,4
HAVING COUNT(*) > 1
ORDER BY count DESC

-- 2. Check if player_prop_predictions itself has duplicates (MERGE fix might have caused this)
SELECT player_lookup, game_id, system_id,
       COUNT(*) as count,
       ARRAY_AGG(FORMAT_TIMESTAMP('%H:%M', created_at) ORDER BY created_at) as times
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY 1,2,3
HAVING COUNT(*) > 1
ORDER BY count DESC LIMIT 20

-- 3. Check prediction worker runs today
SELECT run_id, status, prediction_count, created_at, completed_at,
       game_date
FROM nba_predictions.prediction_worker_runs
WHERE game_date = CURRENT_DATE()
ORDER BY created_at DESC LIMIT 10

-- 4. Check best bets export runs today
SELECT export_type, target_date, status, picks_count, created_at
FROM nba_predictions.best_bets_export_audit
WHERE target_date = CURRENT_DATE()
ORDER BY created_at DESC LIMIT 10
```

### Possible causes to check
1. **Phase 6 triggered twice** — if `signal-best-bets` export ran twice, and the scoped DELETE didn't fully clean up, duplicates can persist in `signal_best_bets_picks`
2. **Prediction worker ran twice** — if the coordinator triggered two runs, and the MERGE dedup didn't catch it (e.g., different `current_points_line` values between runs), you'd get 2 active predictions per player
3. **MERGE game_date fix caused duplicate rows** — the new `AND T.game_date = S.game_date` condition on the player_prop_predictions MERGE could theoretically have changed MERGE behavior if the source staging data contained a different game_date than expected. Check if today was the first run with the new code deployed.
4. **Line change between prediction runs** — if odds moved between two prediction runs, `current_points_line` would differ, creating two rows with different lines that both pass the MERGE key (game_id + player_lookup + system_id + line).

### If it's a Phase 6 double-run issue
```bash
# Check Phase 6 export Cloud Function invocations today
gcloud logging read 'resource.labels.service_name="phase6-export"' \
  --project=nba-props-platform --freshness=12h --limit=50 \
  --format="value(timestamp, textPayload)" 2>/dev/null | head -40
```

### If duplicates need immediate cleanup
```sql
-- Remove duplicates keeping the most recent (ONLY run after understanding root cause)
DELETE FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE()
  AND STRUCT(player_lookup, system_id, recommendation) IN (
    SELECT STRUCT(player_lookup, system_id, recommendation)
    FROM nba_predictions.signal_best_bets_picks
    WHERE game_date = CURRENT_DATE()
    GROUP BY 1,2,3 HAVING COUNT(*) > 1
  )
  AND created_at NOT IN (
    SELECT MAX(created_at)
    FROM nba_predictions.signal_best_bets_picks
    WHERE game_date = CURRENT_DATE()
    GROUP BY player_lookup, system_id, recommendation
  )
```

---

## PRIORITY 2: Remaining Cost Optimizations (Next Session)

### Easy wins not yet done

#### 1. `phase3-to-grading` still has max=100
Min was set to 0 (done) but max is still 100. Not a cost risk since it rarely runs, but worth normalizing.
```bash
gcloud run services update phase3-to-grading \
  --region=us-west2 --project=nba-props-platform \
  --max-instances=3
```

#### 2. Try `prediction-worker` min=0 (~$8/month savings)
Cold start for 2Gi ML model = 30-60 seconds. For a pipeline that takes minutes per phase, this is acceptable. Test it:
```bash
gcloud run services update prediction-worker \
  --region=us-west2 --project=nba-props-platform \
  --min-instances=0
```
Watch the 7 AM ET pipeline the next morning — predictions should still arrive, just ~1 min later.

#### 3. Right-size `prediction-coordinator` to 1Gi/1CPU (~$7/month savings)
Currently 2Gi/2CPU. It orchestrates but imports CatBoost (for signal calcs). May not need full 2Gi.
```bash
gcloud run services update prediction-coordinator \
  --region=us-west2 --project=nba-props-platform \
  --memory=1Gi --cpu=1
```
Watch for OOM errors in logs after. Revert if needed:
```bash
gcloud run services update prediction-coordinator \
  --region=us-west2 --project=nba-props-platform \
  --memory=2Gi --cpu=2
```

#### 4. Reduce `stale-processor-monitor` frequency (every 5 min → 15 min)
288 invocations/day is extreme for a stale-process check. Reducing to every 15 min cuts to 96/day — same as other monitors. Edit via scheduler:
```bash
gcloud scheduler jobs update http stale-processor-monitor \
  --location=us-west2 --project=nba-props-platform \
  --schedule="*/15 * * * *"
```

#### 5. Audit `nba-scraped-data` GCS bucket
The `gcloud storage du` timed out — bucket is very large. Add lifecycle rule to delete files older than 90 days (already ingested into BigQuery):
```bash
# First, see what's in there and how old
gcloud storage ls gs://nba-scraped-data --project=nba-props-platform | head -20

# Then add lifecycle rule
cat > /tmp/lifecycle.json << 'EOF'
{
  "rule": [{
    "action": {"type": "Delete"},
    "condition": {"age": 90}
  }]
}
EOF
gcloud storage buckets update gs://nba-scraped-data \
  --lifecycle-file=/tmp/lifecycle.json \
  --project=nba-props-platform
```

#### 6. `nba-props-platform_cloudbuild` GCS bucket (21.8 GB build artifacts)
Add 30-day retention:
```bash
gcloud storage buckets update gs://nba-props-platform_cloudbuild \
  --lifecycle-file=/tmp/lifecycle.json \  # reuse 90-day file or use 30-day
  --project=nba-props-platform
```

---

## Cost Audit Findings (for reference)

### GCP Resource Inventory
- **Cloud Run services:** ~80 total, 6 were always-on (now 2 after this session)
- **Cloud Functions:** ~70 deployed (including `monthly-retrain` which was DEPRECATED)
- **Cloud Scheduler jobs:** 172 total (164 enabled in us-west2, 6 in us-central1, 2 paused)
- **Pub/Sub topics:** 47, subscriptions: 20
- **Artifact Registry:** 110 GB across 6 repos (cleanup policies now set)

### Always-on services after this session
| Service | Min | Memory | CPU | Monthly idle |
|---------|-----|--------|-----|-------------|
| `prediction-coordinator` | 1 | 2Gi | 2 | ~$14 |
| `prediction-worker` | 1 | 2Gi | 1 | ~$8 |
| All orchestrators | **0** | — | — | $0 |

### BQ table sizes (big query targets)
| Table | Size | Notes |
|-------|------|-------|
| `nba_raw.bettingpros_player_points_props` | 8.0 GB | Scanned by cleanup query (now fixed) |
| `nba_raw.odds_api_player_points_props` | 5.6 GB | Same |
| `nba_raw.bigdataball_play_by_play` | 1.8 GB | Same |
| `nba_predictions.ml_feature_store_v2` | 1.0 GB | MERGE now partition-pruned |
| `nba_predictions.player_prop_predictions` | 0.3 GB | MERGE now partition-pruned |

---

## End of Session Checklist

- [x] Commit pushed: `77095d94`
- [x] Auto-deploy triggered for: `nba-scrapers`, `prediction-worker`, `nba-phase4-precompute-processors`
- [ ] Verify Cloud Build succeeded for the 3 auto-deployed services
- [ ] Investigate best bets doubles (PRIORITY 1 above)
- [ ] Update memory files with cost structure findings
