# MLB 2026 Launch Runbook

*Created: Session 469 (2026-03-11)*
*Purpose: Step-by-step operational plan with dates, verification, contingencies, and monitoring*

## Key Dates

| Date | Milestone | Automated Reminder |
|------|-----------|-------------------|
| **Mar 18** | Retrain window opens | `mlb-retrain-reminder` scheduler (Slack) |
| **Mar 20** | Retrain deadline (deploy needs 3 days) | Same scheduler |
| **Mar 24** | Resume schedulers | `mlb-resume-reminder` scheduler (Slack) |
| **Mar 27** | Opening Day — verify predictions | `mlb-opening-day-check` scheduler |
| **Apr 3** | Week 1 review — first grading possible | Manual |
| **Apr 14** | 3-week checkpoint — first retrain with in-season data | `mlb-retrain-reminder` scheduler |
| **Apr 28** | Retrain #2 (14-day cadence) | `mlb-retrain-reminder` scheduler |
| **May 1** | UNDER enablement decision | `mlb-under-decision-reminder` scheduler |
| **May 15** | Shadow signal promotion review | `mlb-signal-review-reminder` scheduler |
| **Jun 1** | Blacklist review | `mlb-blacklist-review-reminder` scheduler |
| **Jul 15** | All-Star Break prep | Manual |

---

## Phase 1: Retrain (Mar 18-20)

### Step 1.1: Train CatBoost
```bash
# NOTE: --training-end must be the LAST DAY OF AVAILABLE DATA (end of prior season).
# The data ends 2025-09-28 — using a 2026 date with window=120 would yield 0 rows.
# Session 473: confirmed this is the correct command for pre-season retrain.
PYTHONPATH=. .venv/bin/python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2025-09-28 \
    --window 120
```

### Step 1.2: Verify Training Output
```bash
# Check model file exists
ls -la models/mlb/catboost_mlb_v2_regressor_*.cbm

# Check metadata
cat models/mlb/*_metadata.json | python -m json.tool
```

**Must verify ALL of these:**
- [ ] Feature count = **36** (NOT 40)
- [ ] MAE ~1.4-1.6 (if > 2.0, STOP — investigate)
- [ ] OVER HR >= 55% at edge >= 0.75 (if < 50%, STOP)
- [ ] N >= 30 graded predictions in eval window
- [ ] OVER rate between 30-95% (if outside, model is degenerate)

### Step 1.3: Optional Fleet Training
```bash
# LightGBM
PYTHONPATH=. python scripts/mlb/training/train_lightgbm_v1.py \
    --training-end 2026-03-20 --window 120

# XGBoost
PYTHONPATH=. python scripts/mlb/training/train_xgboost_v1.py \
    --training-end 2026-03-20 --window 120
```

### Contingency: Training Fails
| Symptom | Action |
|---------|--------|
| BQ query error | Check table access, partition filters. Try `--dry_run` flag. |
| MAE > 2.0 | Widen window to 150 days. If still bad, check for data gaps in `pitcher_game_summary`. |
| OVER HR < 50% | Training data may have changed. Compare feature distributions to last successful train. |
| Import error | Check `.venv` has catboost installed. Run `pip install catboost`. |
| numpy not found | Training must run in venv: `.venv/bin/python scripts/mlb/training/...` |
| 0 training rows | Check `pitcher_game_summary` and `bp_pitcher_props` have overlapping date ranges. |

---

## Phase 2: Deploy (Mar 20-23)

### Step 2.1: Upload Model to GCS
```bash
gsutil cp models/mlb/catboost_mlb_v2_regressor_*.cbm \
    gs://nba-props-platform-ml-models/mlb/
gsutil cp models/mlb/*_metadata.json \
    gs://nba-props-platform-ml-models/mlb/

# Verify upload
gsutil ls -l gs://nba-props-platform-ml-models/mlb/
```

### Step 2.2: Push Code
```bash
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
# Wait for all builds SUCCESS
```

### Step 2.3: Deploy MLB Worker (MANUAL — not auto-deployed)
```bash
gcloud builds submit --config cloudbuild-mlb-worker.yaml

# CRITICAL: Route traffic to new revision
gcloud run services update-traffic mlb-prediction-worker \
    --region=us-west2 --to-latest

# Verify traffic routing
gcloud run services describe mlb-prediction-worker --region=us-west2 \
    --format="value(status.traffic)"
```

### Step 2.4: Set Environment Variables
**ALWAYS `--update-env-vars`, NEVER `--set-env-vars` (wipes all vars)**
```bash
gcloud run services update mlb-prediction-worker \
    --region=us-west2 \
    --update-env-vars="\
MLB_ACTIVE_SYSTEMS=catboost_v2_regressor,\
MLB_CATBOOST_V2_MODEL_PATH=gs://nba-props-platform-ml-models/mlb/catboost_mlb_v2_regressor_YYYYMMDD.cbm,\
MLB_EDGE_FLOOR=0.75,\
MLB_AWAY_EDGE_FLOOR=1.25,\
MLB_BLOCK_AWAY_RESCUE=true,\
MLB_MAX_EDGE=2.0,\
MLB_MAX_PROB_OVER=0.85,\
MLB_MAX_PICKS_PER_DAY=5,\
MLB_UNDER_ENABLED=false"
```
**Replace `YYYYMMDD` with actual model date from Step 1.1.**

### Step 2.5: Smoke Test (before scrapers resume)
```bash
# Hit the health endpoint
curl -s https://mlb-prediction-worker-756957797294.us-west2.run.app/health | python -m json.tool

# Hit the predict endpoint with a test request (should return empty — no games yet)
curl -s https://mlb-prediction-worker-756957797294.us-west2.run.app/predict \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2026-03-27"}' | python -m json.tool
```

### Contingency: Deploy Fails
| Symptom | Action |
|---------|--------|
| Cloud Build fails | Check `cloudbuild-mlb-worker.yaml`. Common: missing COPY in Dockerfile. |
| Traffic not routing | `gcloud run services update-traffic mlb-prediction-worker --region=us-west2 --to-latest` |
| Health check fails | Check Cloud Run logs: `gcloud logging read 'resource.labels.service_name="mlb-prediction-worker" AND severity>=ERROR' --limit=20` |
| Model load fails | Verify GCS path matches env var exactly. Check model file isn't corrupted. |
| Import errors | Check Dockerfile has all `pip install` deps. Common: missing `lightgbm` or `xgboost` if fleet enabled. |

### Rollback Plan
```bash
# Find previous working revision
gcloud run revisions list --service=mlb-prediction-worker --region=us-west2 --limit=5

# Route traffic back to previous revision
gcloud run services update-traffic mlb-prediction-worker \
    --region=us-west2 \
    --to-revisions=PREVIOUS_REVISION=100
```

---

## Phase 3: Resume (Mar 24)

### Step 3.1: Resume Schedulers
```bash
# Dry run first
./bin/mlb-season-resume.sh --dry-run

# Resume for real
./bin/mlb-season-resume.sh
```

### Step 3.2: Verify Schedule Scraper Fires
Within 24 hours, check:
```sql
-- 2026 schedule should be populated
SELECT COUNT(*) as games_2026
FROM mlb_raw.mlb_schedule
WHERE season = 2026;
-- Expected: ~2,400 games
```

### Step 3.3: Verify All Scrapers Running (Mar 25-26)
```bash
# Check Cloud Run logs for scraper activity
gcloud logging read 'resource.labels.service_name="mlb-phase1-scrapers" AND severity>=ERROR' \
    --limit=20 --format="table(timestamp,textPayload)"

# Check scheduler job runs
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2 \
    --format="table(name,state,status.lastAttemptTime)" | grep mlb
```

### Contingency: Scrapers Don't Fire
| Symptom | Action |
|---------|--------|
| Scheduler still PAUSED | Re-run `./bin/mlb-season-resume.sh` |
| Scheduler fires but 500 | Check target URL. Common: stale service URL. |
| Schedule empty | Manually trigger: `gcloud scheduler jobs run mlb-schedule-scraper --location=us-west2` |
| Props not populating | Check BettingPros — MLB props may not be available until day of games |

---

## Phase 4: Opening Day (Mar 27)

### Step 4.1: Verify Predictions
```sql
-- Are predictions generating?
SELECT game_date, system_id, COUNT(*) as n,
       COUNTIF(recommendation = 'OVER') as n_over,
       AVG(edge) as avg_edge,
       MIN(edge) as min_edge, MAX(edge) as max_edge
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-03-27'
GROUP BY 1, 2 ORDER BY 1, 2;
-- Expected: ~15-20 predictions, mostly OVER, avg edge 0.5-1.0 K
```

### Step 4.2: Verify Best Bets
```sql
-- Are picks publishing?
SELECT game_date, COUNT(*) as n_picks,
       AVG(edge) as avg_edge,
       COUNTIF(ultra_tier = TRUE) as n_ultra
FROM mlb_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-27'
GROUP BY 1 ORDER BY 1;
-- Expected: 3-5 picks/day, avg edge 1.0-1.5 K
```

### Step 4.3: Verify Filters
```sql
-- Are filters working?
SELECT filter_name, COUNT(*) as n_blocked
FROM mlb_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-27'
GROUP BY 1 ORDER BY 2 DESC;
-- Expected: pitcher_blacklist and whole_line_over blocking some picks
```

### Step 4.4: Verify Edge Range
```sql
-- Edges should be in K units (0.3-2.0), NOT probability (0.5-5.0)
SELECT system_id,
       MIN(edge) as min_edge, MAX(edge) as max_edge,
       AVG(edge) as avg_edge, STDDEV(edge) as std_edge
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-03-27'
GROUP BY 1;
```

### Step 4.5: Verify Supplemental Data
```sql
-- Umpire assignments flowing?
SELECT COUNT(*) FROM mlb_raw.mlb_umpire_assignments
WHERE game_date >= '2026-03-24';

-- Weather data flowing?
SELECT COUNT(*) FROM mlb_raw.mlb_weather
WHERE game_date >= '2026-03-24';
```

### Contingency: No Predictions
| Symptom | Action |
|---------|--------|
| 0 predictions | Check worker logs. Common: model path wrong in env var, or no games in schedule. |
| 0 best bets | All filtered out. Check filter audit. Possible: edge floor too high or blacklist too aggressive. |
| Edges > 3.0 | Model is predicting probabilities, not K counts. Check predictor code. |
| Props missing | BettingPros may not have K props yet. Check `bp_pitcher_props` for opening day. |

---

## Phase 5: Daily Monitoring (Ongoing)

### Daily Checks (automated where possible)
1. **Predictions generated?** — Check `pitcher_strikeouts` has rows for today
2. **Best bets published?** — Check `signal_best_bets_picks` has 3-5 rows
3. **Grading completed?** — Check `prediction_accuracy` for yesterday (after 11 AM ET)
4. **No service errors?** — Cloud Run logs for mlb-prediction-worker
5. **Props coverage?** — How many pitchers had BettingPros lines vs started

### Weekly Checks
1. **HR tracker** — Running hit rate by week
2. **Signal fires** — Which signals are actually firing? Any dead?
3. **Blacklist effectiveness** — Are blacklisted pitchers still < 45%?
4. **Ultra performance** — Ultra picks maintaining 69%+ HR?
5. **Edge distribution** — Is edge compressing or expanding?

### Weekly HR Query
```sql
SELECT
    DATE_TRUNC(game_date, WEEK) as week,
    COUNT(*) as n_picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    ROUND(COUNTIF(prediction_correct = TRUE) / COUNT(*) * 100, 1) as hr_pct,
    ROUND(AVG(edge), 2) as avg_edge
FROM mlb_predictions.prediction_accuracy
WHERE game_date >= '2026-03-27'
    AND has_prop_line = TRUE
    AND recommendation = 'OVER'
    AND prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

---

## Key Decision Playbooks

### Apr 14: 3-Week Checkpoint
```bash
# 1. Retrain with in-season data
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2026-04-14 --window 120

# 2. Review blacklist
PYTHONPATH=. python bin/mlb/review_blacklist.py --since 2026-03-27

# 3. Compare fleet (if multi-model)
```
```sql
SELECT system_id,
       COUNT(*) as n,
       COUNTIF(prediction_correct = TRUE) as wins,
       ROUND(COUNTIF(prediction_correct = TRUE) / COUNT(*) * 100, 1) as hr
FROM mlb_predictions.prediction_accuracy
WHERE game_date >= '2026-03-27'
    AND has_prop_line = TRUE
    AND prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY hr DESC;
```

### May 1: UNDER Decision
**Enable if:** OVER HR >= 58% at N >= 50
```bash
gcloud run services update mlb-prediction-worker \
    --region=us-west2 \
    --update-env-vars="MLB_UNDER_ENABLED=true"
```
**Don't enable if:** OVER HR < 55% or N < 50. Wait until May 15.

### May 15: Signal Promotion
**Promote if:** HR >= 60% at N >= 30 in live data
```sql
SELECT signal_name, direction,
       COUNT(*) as n,
       COUNTIF(prediction_correct = TRUE) as wins,
       ROUND(COUNTIF(prediction_correct = TRUE) / COUNT(*) * 100, 1) as hr
FROM mlb_predictions.signal_performance
WHERE game_date >= '2026-03-27'
    AND is_shadow = TRUE
GROUP BY 1, 2
HAVING COUNT(*) >= 30
ORDER BY hr DESC;
```

---

## Automated Reminder Schedule

Set up these Cloud Scheduler jobs to send Slack alerts:

| Job Name | Schedule | Message |
|----------|----------|---------|
| `mlb-retrain-reminder` | Mar 18, 9 AM ET | "MLB retrain window opens today. Run train_regressor_v2.py" |
| `mlb-resume-reminder` | Mar 24, 8 AM ET | "Resume MLB schedulers today: ./bin/mlb-season-resume.sh" |
| `mlb-opening-day-check` | Mar 27, 2 PM ET | "Opening Day! Verify MLB predictions in BQ." |
| `mlb-weekly-hr-report` | Every Monday 10 AM ET (Apr+) | "Check MLB weekly HR and signal performance" |
| `mlb-retrain-biweekly` | Every other Monday 9 AM ET (Apr+) | "MLB retrain due. 14-day cadence." |
| `mlb-under-decision` | May 1, 9 AM ET | "UNDER enablement decision. Check OVER HR >= 58%." |
| `mlb-signal-review` | May 15, 9 AM ET | "Shadow signal promotion review. Check HR >= 60% at N >= 30." |
| `mlb-blacklist-review` | Jun 1, 9 AM ET | "Blacklist review. Run bin/mlb/review_blacklist.py." |

---

## Bootstrap Performance Expectations

Don't panic if early performance is lower:

| Period | Expected BB HR | Picks/Day | Why |
|--------|---------------|-----------|-----|
| Week 0-2 (Mar 27-Apr 10) | ~56% | ~3 | Pitchers need 3+ starts for rolling features |
| Week 3-7 (Apr 11-May 14) | ~58% | ~4-5 | Season stats still noisy. FanGraphs xFIP not stable. |
| Week 8+ (May 15+) | ~63-65% | ~5 | Full signal coverage, stable features |

**RED FLAGS (investigate immediately):**
- HR < 45% over any 7-day window at N >= 10
- 0 predictions for 2+ consecutive game days
- Edge consistently > 2.0 (model is miscalibrated)
- Blacklisted pitcher predictions leaking through
- All picks from one team or one game
