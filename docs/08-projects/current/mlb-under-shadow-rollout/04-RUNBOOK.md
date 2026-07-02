# Runbook — MLB UNDER shadow rollout / promotion

**Status:** DRAFT (not yet executable — Phase 0 + Phase 1 must ship first)
**Promote to:** `docs/02-operations/runbooks/mlb-under-promotion.md` when shipping
**Context:** `00-OVERVIEW.md`, `01-PLAN.md`, `03-DECISIONS.md`

This runbook covers:
1. Verifying shadow is healthy after Phase 1 deploy
2. Evaluating the graduation gate at Day 47
3. Flipping UNDER live (only if gate passes)
4. Rolling back at each stage

---

## Pre-flight (Day 1 post-Phase-1-deploy)

After Phase 1 ships, verify shadow is producing data within 24 hours.

```bash
# Check shadow UNDER picks were written
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  game_date,
  shadow_reason,
  COUNT(*) AS n_picks,
  COUNTIF(would_be_selected) AS n_top5
FROM `nba-props-platform.mlb_predictions.blacklist_shadow_picks`
WHERE shadow_reason IN ("under_shadow", "under_shadow_backfill")
  AND game_date >= CURRENT_DATE() - 7
GROUP BY game_date, shadow_reason
ORDER BY game_date DESC
'
```

**Expected:** Non-zero rows in `under_shadow` from Phase 1 deploy date forward. `under_shadow_backfill` rows from the historical replay (Step 7) for 2024-04-01 through 2025-09-30.

**If empty after 3 game days:**
- Check `MLB_UNDER_SHADOW` env var: `gcloud run services describe mlb-prediction-worker --region=us-west2 --format="value(spec.template.spec.containers[0].env)"`
- Check filter audit: `bq query ... 'SELECT filter_name, COUNT(*) FROM mlb_predictions.best_bets_filter_audit WHERE filter_result="BLOCKED" AND recommendation="UNDER" GROUP BY 1 ORDER BY 2 DESC'`
- Most likely cause: `UNDER_MIN_SIGNALS=3` still unreachable (Phase 0 Step 1 didn't fully ship)

---

## Daily monitoring (during 45-day shadow window)

The `mlb-under-shadow-monitor` CF fires at 9:30 AM ET daily and alerts to `#nba-alerts` on:
- 7d HR < 50% (N >= 14)
- No shadow UNDER picks 5+ consecutive days

**Manual spot-check query (run any time):**

```sql
WITH shadow AS (
  SELECT
    s.game_date,
    s.pitcher_lookup,
    s.recommendation,
    s.edge,
    s.line_value,
    s.signal_count,
    s.real_signal_count,
    pa.prediction_correct,
    pa.is_voided
  FROM `nba-props-platform.mlb_predictions.blacklist_shadow_picks` s
  LEFT JOIN `nba-props-platform.mlb_predictions.prediction_accuracy` pa
    ON s.game_date = pa.game_date
    AND s.pitcher_lookup = pa.pitcher_lookup
    AND s.recommendation = pa.recommendation
    AND s.line_value = pa.line_value
  WHERE s.shadow_reason = 'under_shadow'
    AND s.game_date >= CURRENT_DATE() - 45
)
SELECT
  COUNT(*) AS n_total,
  COUNTIF(prediction_correct IS NOT NULL AND NOT is_voided) AS n_graded,
  COUNTIF(prediction_correct) AS n_hits,
  ROUND(COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0) * 100, 1) AS hr_pct
FROM shadow;
```

---

## Day 30 — ranker discovery checkpoint

**Owner:** the user or future Claude session

After 30 days of shadow data, run the discovery scanner:

```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. .venv/bin/python scripts/mlb/discovery/under_ranking_scanner.py \
  --start-date $(date -d "30 days ago" +%Y-%m-%d) \
  --end-date $(date -d "yesterday" +%Y-%m-%d) \
  --output docs/08-projects/current/mlb-under-shadow-rollout/05-RANKING-REDESIGN.md
```

(Script doesn't exist yet — Phase 1 Step 5 deliverable.)

Output should populate `05-RANKING-REDESIGN.md` with the empirical ranker design. Implement the ranker in `best_bets_exporter.py` and deploy BEFORE the Day 47 graduation gate.

---

## Day 47 — graduation gate

**Run all 4 checks. Live flip ONLY if all pass.**

### Check 1 — Sample size and rolling HR

```sql
WITH graded AS (
  SELECT
    pa.prediction_correct,
    pa.game_date,
    EXTRACT(MONTH FROM pa.game_date) AS month
  FROM `nba-props-platform.mlb_predictions.blacklist_shadow_picks` s
  JOIN `nba-props-platform.mlb_predictions.prediction_accuracy` pa
    ON s.game_date = pa.game_date
    AND s.pitcher_lookup = pa.pitcher_lookup
    AND s.recommendation = pa.recommendation
    AND s.line_value = pa.line_value
  WHERE s.shadow_reason = 'under_shadow'
    AND s.game_date >= CURRENT_DATE() - 45
    AND pa.prediction_correct IS NOT NULL
    AND pa.is_voided = FALSE
)
SELECT
  COUNT(*) AS n,
  COUNTIF(prediction_correct) AS hits,
  ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) AS hr_pct
FROM graded;
```

**Gate:** N >= 60 AND HR >= 56.0%

### Check 2 — Monthly consistency

```sql
-- Same WITH clause as Check 1
SELECT
  month,
  COUNT(*) AS n,
  ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) AS hr_pct
FROM graded
GROUP BY month
ORDER BY month;
```

**Gate:** Every month with N >= 10 must have HR >= 50.0%.

### Check 3 — Vig-adjusted ROI

```sql
-- Assumes -110 standard juice. Adjust if MLB pricing differs.
-- WITH clause from Check 1
SELECT
  COUNT(*) AS n,
  COUNTIF(prediction_correct) AS hits,
  ROUND(SUM(CASE WHEN prediction_correct THEN 0.909 ELSE -1.0 END), 2) AS profit_units,
  ROUND(SUM(CASE WHEN prediction_correct THEN 0.909 ELSE -1.0 END) / COUNT(*) * 100, 2) AS roi_pct
FROM graded;
```

**Gate:** roi_pct >= +3.0%

### Check 4 — No regime collapse warning

Confirm the daily monitor CF has NOT alerted in the last 7 days. Check the GCS dedup file:

```bash
gcloud storage ls gs://nba-props-platform-api/v1/admin/alerts/mlb-under-shadow-* 2>&1 | head -10
```

**Gate:** No alert file with timestamp within last 7 days.

---

## Live flip (only when all 4 gates pass)

```bash
# 1. Flip env var (NEVER --set-env-vars — wipes everything else)
gcloud run services update mlb-prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars=MLB_UNDER_ENABLED=true

# 2. Verify env var took effect (wait for new revision)
gcloud run services describe mlb-prediction-worker \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | grep MLB_UNDER

# 3. Verify latest revision serves 100% of traffic
gcloud run services describe mlb-prediction-worker \
  --region=us-west2 \
  --format="value(status.traffic[0].latestRevision)"
# Expected output: True

# 4. Force a fresh prediction run for today (do NOT call /predict-batch — duplicates)
# Wait for next scheduled run, or trigger via:
gcloud pubsub topics publish nba-phase5-best-bets-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","target_date":"today"}'

# 5. Verify UNDER picks landed in signal_best_bets_picks (next morning)
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT recommendation, COUNT(*) AS n
FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
WHERE game_date = CURRENT_DATE()
GROUP BY recommendation
'
```

**Expected after live flip:** Both OVER and UNDER rows appear (UNDER will be rare — competes with OVER for 5-slot quota; per-day UNDER count depends on signal coverage that day).

---

## Post-flip monitoring (first 14 days live)

**Keep shadow ON** (`MLB_UNDER_SHADOW=true` remains default) for parity check. Compare live UNDER picks to shadow UNDER picks — they should be identical when both flags are on.

**Daily check for first 14 days:**

```sql
SELECT
  game_date,
  COUNTIF(recommendation = 'OVER') AS over_picks,
  COUNTIF(recommendation = 'UNDER') AS under_picks,
  ROUND(AVG(CASE WHEN recommendation = 'OVER' THEN ABS(edge) END), 2) AS avg_over_edge,
  ROUND(AVG(CASE WHEN recommendation = 'UNDER' THEN ABS(edge) END), 2) AS avg_under_edge
FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
WHERE game_date >= CURRENT_DATE() - 14
GROUP BY game_date
ORDER BY game_date DESC;
```

**Red flags:**
- UNDER picks dominating (> 60% of daily volume) — gate was too loose
- Zero UNDER picks for 3+ consecutive days — pipeline regression
- UNDER HR dropping > 5pp below shadow projection — regime shift

If any red flag fires in first 14 days, immediately roll back (next section).

---

## Rollback procedures

### Rollback A — Phase 0 (pre-work)

```bash
git revert <commit-sha>
# Push, auto-deploy via Cloud Build trigger
git push origin main
```

Schema migrations from Phase 0 Step 3 are additive — no data loss. The new columns just stop being populated.

### Rollback B — Phase 1 (shadow live)

```bash
gcloud run services update mlb-prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars=MLB_UNDER_SHADOW=false
```

Effect: shadow UNDER picks stop being written within ~5 min (next prediction worker request). Existing shadow rows remain in BQ for analysis.

### Rollback C — Phase 2 (UNDER live in prod)

```bash
gcloud run services update mlb-prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars=MLB_UNDER_ENABLED=false
```

Effect: reverts to OVER-only within ~5 min. Existing UNDER picks in `signal_best_bets_picks` remain in BQ. Frontend will continue to show them until the next Phase 6 export overwrites that day's published JSON. To force immediate removal from the public site:

```bash
# Re-export today's GCS JSON without UNDER
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["best-bets"],"target_date":"today"}'
```

**WARNING:** Per memory `sessions-472-488.md`, never trigger `signal-best-bets` historical re-export — deletes picks. Only re-export "today".

---

## If graduation gate FAILS

Document in `02-AGENT-FINDINGS.md` addendum (or new `06-GRADUATION-DAY-47.md`):
- Which gate(s) failed (N? HR? monthly? ROI?)
- Most likely root cause (regime shift? signal coverage? bookkeeping?)
- Whether to keep shadow running for 90 days or abandon

Default action on failure: **keep shadow ON, revisit at Day 90.** Do NOT flip live.

---

## Emergency contacts and tooling

- Slack `#nba-alerts` — all MLB monitoring alerts
- `bin/check-deployment-drift.sh --verbose` — check if deployed env vars match repo
- `bin/monitoring/mlb_daily_performance.py` — 5 BQ queries for daily MLB tracking (already exists)
- `mlb-prediction-worker` Cloud Run logs — debug per-pick decisions

## Related runbooks

- `docs/02-operations/runbooks/halt-mode-operations.md` (NBA pattern, similar shape)
- `docs/02-operations/runbooks/observability-alerts.md`
