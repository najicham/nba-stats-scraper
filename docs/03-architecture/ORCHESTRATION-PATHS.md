# NBA Pipeline Orchestration Paths

**Purpose**: Explain the two distinct orchestration paths and when each is used

---

## Overview

The NBA prediction pipeline has **two orchestration paths** that serve different purposes:

1. **Full Pipeline** (Event-driven) - For historical/backfill data
2. **Same-Day Predictions** (Time-driven) - For live game predictions

Understanding these paths eliminates confusion about "missing" orchestration events or prediction timing.

---

## Path 1: Full Pipeline (Historical/Backfill)

### Flow
```
Phase 1 (Scrapers)
    ↓ Pub/Sub: nba-phase1-scrapers-complete
Phase 2 (Raw Processors)
    ↓ Pub/Sub: nba-phase2-raw-complete
Phase 3 (Analytics)
    ↓ Pub/Sub: nba-phase3-analytics-complete
Phase 4 (Precompute/ML Features)
    ↓ Pub/Sub: nba-phase4-precompute-complete
Phase 5 (Predictions)
```

### Characteristics
- **Trigger**: Event-driven via Pub/Sub messages
- **State Tracking**: Firestore tracks completion per phase per date
- **Duration**: 6-8 hours end-to-end
- **Completeness**: Full analytics + team statistics + all ML features

### Use Cases
- Historical data processing
- Backfill operations
- Batch analytics jobs
- Complete data regeneration
- Quality assurance runs

### Firestore Structure
```
/pipeline_state/{date}/phase1 → {status: 'complete', timestamp: '...'}
/pipeline_state/{date}/phase2 → {status: 'complete', timestamp: '...'}
/pipeline_state/{date}/phase3 → {status: 'complete', timestamp: '...'}
/pipeline_state/{date}/phase4 → {status: 'complete', timestamp: '...'}
/pipeline_state/{date}/phase5 → {status: 'complete', timestamp: '...'}
```

### Example
Processing data for **2025-12-15** (historical):
1. Scraper runs for 12/15 games
2. Publishes to `nba-phase1-scrapers-complete`
3. Phase 2 processes raw JSON → BigQuery
4. Publishes to `nba-phase2-raw-complete`
5. Phase 3 generates analytics
6. ... continues through Phase 5
7. Each phase waits for previous phase completion

---

## Path 2: Same-Day Predictions (Live)

### Flow
```
Phase 1/2 (Data Collection)
         ↓ (direct trigger, no Pub/Sub)
Phase 5 (Predictions ONLY)
```

### Characteristics
- **Trigger**: Time-driven via Cloud Scheduler
- **State Tracking**: None (direct execution)
- **Duration**: <2 hours
- **Completeness**: Uses yesterday's analytics + today's props

### Use Cases
- Tonight's game predictions
- Live prediction updates
- Quick turnaround predictions
- When full pipeline would be too slow

### Schedulers

**1. overnight-predictions**
- **Schedule**: Daily at 7:00 AM ET
- **Purpose**: Generate predictions for tonight using yesterday's complete data
- **Data Used**:
  - Player/team analytics: From yesterday (Phase 3)
  - ML features: From yesterday (Phase 4)
  - Props: Fresh from Odds API (today)
  - Schedule: Today's games
- **Bypasses**: Phases 3 & 4 (too slow for same-day)

**2. evening-predictions**
- **Schedule**: Daily at 4:00 PM ET
- **Purpose**: Update predictions with latest injury reports and line movements
- **Data Used**:
  - Same as overnight-predictions
  - Updated injury reports
  - Latest betting lines

### Why Bypass Phases 3-4?

Full pipeline takes 6-8 hours:
- Phase 3 (Analytics): ~2 hours
- Phase 4 (Precompute): ~3 hours
- Phase 5 (Predictions): ~1 hour

For 7 PM games, we need predictions by 6 PM.
- Starting at 7 AM: Can't wait 6-8 hours
- Solution: Use yesterday's analytics (still highly relevant)

### Example
Generating predictions for **tonight (2026-01-01)**:
1. 7:00 AM: `overnight-predictions` scheduler triggers
2. Phase 5 directly executes with:
   - player_game_summary: from 2025-12-31 ✅
   - team_offense_game_summary: from 2025-12-31 ✅
   - ml_feature_store: from 2025-12-31 ✅
   - odds_api_player_props: from 2026-01-01 (fresh) ✅
3. Predictions generated in ~1 hour
4. Available by 8:00 AM for tonight's 7:00 PM games

---

## Comparison Table

| Aspect | Full Pipeline | Same-Day Predictions |
|--------|--------------|---------------------|
| **Trigger** | Event (Pub/Sub) | Time (Scheduler) |
| **Phases** | 1 → 2 → 3 → 4 → 5 | 1/2 → 5 (direct) |
| **Duration** | 6-8 hours | <2 hours |
| **State Tracking** | Firestore | None |
| **Data Freshness** | Same-day complete | Yesterday analytics + today props |
| **Use Case** | Historical/backfill | Live predictions |
| **Completeness** | 100% analytics | ~95% (good enough for predictions) |

---

## How to Identify Which Path Was Used

### Check Firestore for Full Pipeline
```python
from google.cloud import firestore

db = firestore.Client()
doc = db.collection('pipeline_state').document('2025-12-31').get()

if doc.exists:
    print("Full pipeline executed")
    print(f"Phases: {doc.to_dict()}")
else:
    print("Only same-day prediction path used")
```

### Check Scheduler Logs for Same-Day
```bash
# Check if overnight-predictions ran
gcloud logging read \
  'resource.labels.job_name="overnight-predictions"' \
  --limit=10 --freshness=1d
```

### Check Prediction Table Timestamps
```sql
SELECT
  game_date,
  MIN(created_at) as first_prediction,
  MAX(created_at) as last_prediction,
  COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2026-01-01'
GROUP BY game_date;
```
- Early morning timestamps (7-9 AM): Same-day path
- Evening timestamps (6-8 PM): Full pipeline path

---

## Monitoring Tips

### Full Pipeline Health
```sql
-- Check Firestore state for date range
SELECT date, phase, status
FROM firestore_pipeline_state
WHERE date >= '2025-12-25'
ORDER BY date, phase
```

### Same-Day Prediction Health
```bash
# Check scheduler execution
gcloud scheduler jobs describe overnight-predictions
gcloud scheduler jobs describe evening-predictions

# Check recent runs
gcloud logging read \
  'resource.labels.job_name=~"predictions"' \
  --limit=5 --freshness=2d
```

---

## Common Questions

### Q: Why do I see predictions but no Phase 3/4 completion?
**A:** Same-day prediction path was used. This is normal and expected for tonight's games.

### Q: When should I use full pipeline vs same-day?
**A:**
- **Full pipeline**: Historical data, backfills, quality assurance
- **Same-day**: Live predictions for tonight's games

### Q: Can both paths run for the same date?
**A:** Yes! Common scenario:
1. 7 AM: Same-day path generates quick predictions
2. Later: Full pipeline runs and updates predictions with complete analytics

### Q: Which predictions are more accurate?
**A:** Full pipeline (all phases) has marginally better accuracy (~1-2%) but same-day is "good enough" and much faster. The prediction model is designed to work well with D-1 (yesterday's) data.

### Q: What happens if same-day predictions fail?
**A:** System falls back to yesterday's predictions or waits for full pipeline to complete.

---

## Troubleshooting

### Same-Day Predictions Not Generating
1. Check scheduler status:
   ```bash
   gcloud scheduler jobs describe overnight-predictions
   ```

2. Check scheduler execution logs:
   ```bash
   gcloud logging read 'resource.labels.job_name="overnight-predictions"' --limit=5
   ```

3. Check Phase 5 service health:
   ```bash
   gcloud run services describe prediction-coordinator --region=us-west2
   ```

### Full Pipeline Stuck
1. Check Firestore state:
   ```python
   # Which phase is stuck?
   doc = firestore.Client().collection('pipeline_state').document('2025-12-31').get()
   ```

2. Check Pub/Sub subscriptions:
   ```bash
   gcloud pubsub subscriptions list | grep nba-phase
   ```

3. Check unacknowledged messages:
   ```bash
   gcloud pubsub subscriptions describe nba-phase3-analytics-complete-sub
   ```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Full Pipeline Path                       │
│  Phase1 ─Pub/Sub→ Phase2 ─Pub/Sub→ Phase3 ─Pub/Sub→ Phase4  │
│                                              ─Pub/Sub→ Phase5 │
│  Duration: 6-8 hours  |  State: Firestore  |  Use: Historical│
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  Same-Day Prediction Path                    │
│  Phase1/2 (data) ────── Scheduler (7AM) ────── Phase5        │
│  Duration: <2 hours   |  State: None       |  Use: Tonight   │
└─────────────────────────────────────────────────────────────┘
```

---

**Last Updated**: 2026-01-01
**Maintained By**: Platform Team
**Related Docs**:
- `docs/02-workflows/prediction-pipeline.md`
- `docs/04-operations/orchestration-guide.md`
