# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 429 — MLB Sprint 3 deployed + feature contract fix)
**Status:** MLB code committed and deploying. CatBoost V1 model NOT YET ENABLED in BQ. NBA running normally.

## What Happened This Session

### MLB Sprint 3 Deployed
- Committed all Sprint 2+3 code (predictors, signals, grading, scrapers, schemas)
- **Fixed critical feature contract mismatch** — pitcher_loader was missing 4 of 31 CatBoost features (season_swstr_pct, season_csw_pct, k_avg_vs_line, over_implied_prob, velocity_change). Would have blocked 100% of predictions.
- Fixed Dockerfile: added `libgomp1` for CatBoost runtime
- Synced main scraper registry with 3 new MLB scrapers
- Agent audit found no other deployment blockers

### NBA Session 429
- Removed `mean_reversion_under` from UNDER_SIGNAL_WEIGHTS (cross-season decay to 53.0%)
- Algorithm version bumped to `v429_signal_weight_cleanup`
- Filter demotion from Session 428 still being monitored (deployed Mar 6)

---

## What to Do Next

### Priority 1: Enable CatBoost V1 Model (5 min)

```sql
UPDATE `nba-props-platform.mlb_predictions.model_registry`
SET enabled = TRUE, is_production = TRUE, updated_at = CURRENT_TIMESTAMP()
WHERE model_id = 'catboost_mlb_v1_31f_train20250430_20250828';
```

### Priority 2: Verify Deployment (10 min)

```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
./bin/check-deployment-drift.sh --verbose
```

### Priority 3: Cloud Scheduler Jobs (30 min)

New scrapers need scheduler jobs before season start:

```bash
# Check existing MLB jobs
gcloud scheduler jobs list --project=nba-props-platform | grep mlb

# Add: Statcast daily (2 AM ET, after overnight games)
# Add: Box scores MLBAPI (replace BDL overnight job)
# Optional: Reddit discussion (11 AM ET)
```

### Priority 4: Pre-Season Retrain (30 min)

Retrain CatBoost on freshest available data before Mar 27:

```bash
PYTHONPATH=. python ml/training/mlb/quick_retrain_mlb.py \
  --model-type catboost \
  --training-window 120 \
  --upload --register
```

### Priority 5: E2E Pipeline Test

```bash
# Test CatBoost predictor loads
PYTHONPATH=. python -c "
from predictions.mlb.prediction_systems.catboost_v1_predictor import CatBoostV1Predictor
p = CatBoostV1Predictor(); assert p.load_model(); print('CatBoost V1 OK')
"

# Test signal system
PYTHONPATH=. python -c "
from ml.signals.mlb.registry import build_mlb_registry
r = build_mlb_registry()
print(f'Active: {len(r.active_signals())}, Shadow: {len(r.shadow_signals())}, Filters: {len(r.negative_filters())}')
"

# Verify model registry
bq query --nouse_legacy_sql 'SELECT model_id, enabled, is_production, evaluation_hr_edge_1plus FROM mlb_predictions.model_registry'
```

### Priority 6: NBA Monitoring

- Filter demotion (Session 428) deployed Mar 6 — monitor BB HR for 7 days
- New signals (bounce_back_over, CLV, over_streak_reversion_under) first fired Mar 7
- `/daily-steering` for morning status

---

## MLB Sprint 4 Remaining Plan (Mar 27 Opening Day)

### Week 1 (Mar 8-14): Infrastructure
- [ ] Enable CatBoost V1 in BQ registry
- [ ] Verify Cloud Build success
- [ ] Add Cloud Scheduler jobs for new scrapers
- [ ] Verify scraper credentials (ODDS_API_KEY, pybaseball)
- [ ] Test Slack notifications for MLB pipeline

### Week 2 (Mar 15-21): Testing + Polish
- [ ] Run Statcast backfill (Jul-Sep 2025) for completeness
- [ ] Retrain CatBoost on freshest data
- [ ] E2E pipeline test with historical game date
- [ ] Verify grading processor handles void logic correctly
- [ ] Fix cloudbuild-mlb-worker.yaml Dockerfile path if needed

### Week 3 (Mar 22-27): Launch
- [ ] Resume all MLB scheduler jobs
- [ ] Final retrain with latest data
- [ ] Opening day monitoring plan
- [ ] Set up daily review cadence for first week

### Post-Launch (Apr 1+): In-Season
- [ ] Monitor first week predictions daily
- [ ] Promote shadow signals after 30 days accumulation
- [ ] First retrain decision based on live performance
- [ ] Watch for July drift pattern (walk-forward showed dip)

---

## Key Files

| File | Purpose |
|------|---------|
| `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md` | MLB project status |
| `docs/08-projects/current/mlb-pitcher-strikeouts/2026-03-MLB-MASTER-PLAN.md` | Full master plan |
| `docs/09-handoff/2026-03-07-MLB-SPRINT3-HANDOFF.md` | Sprint 3 details |
| `ml/training/mlb/quick_retrain_mlb.py` | Retrain script |
| `results/mlb_walkforward_2025/simulation_summary.json` | Walk-forward results |

## Deployment State

- **NBA:** Algorithm `v429_signal_weight_cleanup` deployed
- **MLB:** Sprint 2+3 code committed and deploying. CatBoost V1 in GCS, NOT yet enabled in BQ.
- **Drift:** Check with `./bin/check-deployment-drift.sh --verbose`
