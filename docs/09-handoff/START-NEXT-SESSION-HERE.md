# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 429 — MLB fully deployed)
**Status:** MLB pipeline live. CatBoost V1 enabled + serving. All scheduler jobs paused (resume Mar 24-25). NBA running normally.

## What Happened This Session

### MLB Sprint 4: Full Deployment
- CatBoost V1 enabled in BQ registry (is_production=TRUE)
- MLB worker deployed: catboost_v1, v1_6_rolling, ensemble_v1 all loading
- 22 Cloud Scheduler jobs created (all paused until season start)
- Batter analytics migrated from BDL to unified source (BDL + mlbapi UNION)
- Feature contract fixed (4 missing features + velocity_change formula)
- Dockerfile fixed (libgomp1 + urllib3==2.6.3)
- Main scraper registry synced with 3 new MLB scrapers
- ODDS_API_KEY verified (configured via secret)
- Slack notifications working

### NBA Session 429
- Removed `mean_reversion_under` from UNDER_SIGNAL_WEIGHTS (cross-season decay to 53.0%)
- Algorithm version bumped to `v429_signal_weight_cleanup`
- Filter demotion from Session 428 still being monitored (deployed Mar 6)

---

## What to Do Next

### Priority 1: Resume Schedulers Before Season (Mar 24-25)

```bash
# Resume all MLB scheduler jobs before opening day (Mar 27)
for job in $(gcloud scheduler jobs list --location=us-west2 --format='value(name)' | grep mlb); do
  gcloud scheduler jobs resume $job --location=us-west2
done
```

### Priority 2: Pre-Season Retrain (Mar 24-25)

Current model trained through Aug 2025. Retrain on freshest available data:

```bash
PYTHONPATH=. python ml/training/mlb/quick_retrain_mlb.py \
  --model-type catboost \
  --training-window 120 \
  --upload --register
```

### Priority 3: Statcast Raw Backfill (Optional)

Raw table empty but analytics has data. For pipeline completeness:

```bash
PYTHONPATH=. python scripts/mlb/backfill_statcast.py --start 2025-07-01 --end 2025-09-28 --sleep 2
```

### Priority 4: NBA Monitoring

- Filter demotion (Session 428) deployed Mar 6 — monitor BB HR for 7 days
- New signals (bounce_back_over, CLV, over_streak_reversion_under) first fired Mar 7
- `/daily-steering` for morning status

---

## What's Done (Full Checklist)

- [x] Sprint 2+3 code committed (43 files, +8,158 lines)
- [x] Feature contract fix (pitcher_loader provides all 31 CatBoost features)
- [x] Dockerfile fixed (libgomp1 + urllib3 pin)
- [x] CatBoost V1 enabled in BQ registry
- [x] MLB worker deployed with all 3 systems
- [x] 22 Cloud Scheduler jobs (all paused)
- [x] Batter analytics migrated to unified BDL + mlbapi source
- [x] Pitcher analytics already migrated (mlb_pitcher_stats)
- [x] ODDS_API_KEY configured
- [x] Slack notifications working
- [x] E2E local tests pass (model, signals, exporter)
- [x] cloudbuild-mlb-worker.yaml Dockerfile path fixed
- [x] Main scraper registry synced

## What's Left

| Task | When | Effort |
|------|------|--------|
| Resume scheduler jobs | Mar 24-25 | 5 min |
| Retrain CatBoost on freshest data | Mar 24-25 | 30 min |
| Statcast raw backfill | Optional | 15 min |
| BDL injury source replacement | Post-launch | 1 hr |
| BDL subscription retirement | After mlbapi analytics validated | — |

## Post-Launch Monitoring (Apr 1+)

- [ ] Monitor first week predictions daily
- [ ] Promote shadow signals after 30 days
- [ ] First retrain decision based on live performance
- [ ] Watch for July drift (walk-forward showed dip)

---

## Key Files

| File | Purpose |
|------|---------|
| `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md` | MLB project status |
| `predictions/mlb/prediction_systems/catboost_v1_predictor.py` | CatBoost V1 predictor (31 features) |
| `predictions/mlb/pitcher_loader.py` | Shared feature loader |
| `ml/training/mlb/quick_retrain_mlb.py` | Retrain script |
| `ml/signals/mlb/registry.py` | Signal registry (8+6+4) |

## Deployment State

- **NBA:** Algorithm `v429_signal_weight_cleanup` deployed
- **MLB:** Fully deployed. CatBoost V1 enabled. Worker serving 3 systems. Schedulers paused.
- **Drift:** Check with `./bin/check-deployment-drift.sh --verbose`
