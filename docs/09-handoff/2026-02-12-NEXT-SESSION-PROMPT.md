# Next Session Start Prompt — 2026-02-13

## What Happened (Sessions 215–223 on Feb 12)

Ten sessions of infrastructure recovery, model analysis, and experiments:

- **Sessions 215–219B**: Infrastructure recovery — fixed 15→0 scheduler failures, 23 IAM fixes, deployment drift 0/16
- **Session 220**: Phase 4 fixes, recovered Feb 12 to 337 predictions, champion decay confirmed (39.9% edge 3+ HR)
- **Session 221**: Deploy sweep (4 deploys), all systems green
- **Session 222**: Deep model decay analysis — 96 prior experiments reviewed, 5 failure modes identified, 5 experiments proposed. See `docs/08-projects/current/model-improvement-analysis/01-SESSION-222-MODEL-ANALYSIS.md`
- **Session 222B (lost context)**: Ran **16 experiments** testing different params. Key finding: **Q43 + 14d recency = 55.4% HR on 92 picks** (best result). OVER specialist models catastrophic (18-45% HR).
- **Session 223**: Recovered lost context, documented all 16 experiment results in handoff

## Morning Checklist

### 1. Check scheduler health
```bash
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2 --format=json > /tmp/sched.json && python3 << 'EOF'
import json
with open("/tmp/sched.json") as f:
    jobs = json.load(f)
failing = [(j.get("name","").split("/")[-1], j.get("status",{}).get("code",0)) for j in jobs if j.get("state") == "ENABLED" and j.get("status",{}).get("code",0) != 0]
print(f"Failing: {len(failing)} (was 0 on Feb 12)")
for name, code in sorted(failing): print(f"  {name}: code {code}")
if not failing: print("  ALL PASSING!")
EOF
```

### 2. Check predictions and grading
```bash
bq query --nouse_legacy_sql "SELECT game_date, COUNT(*) as predictions FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE() - 2 GROUP BY 1 ORDER BY 1 DESC"
bq query --nouse_legacy_sql "SELECT game_date, COUNT(*) as graded FROM nba_predictions.prediction_accuracy WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1 ORDER BY 1 DESC"
```

### 3. Run daily validation
```bash
/validate-daily
```

## Primary Task — Model Experiments

The champion is at 39.9% edge 3+ HR (35+ days stale, far below 52.4% breakeven). **No model passes governance gates** (60% edge 3+ HR). February is structurally hard (trade deadline, scoring shift).

### Best Results from 16 Experiments (Session 222B)

| Rank | Experiment | Edge 3+ HR | N | Key Finding |
|------|-----------|-----------|---|-------------|
| 1 | **Perf Boost** (perf 2x, vegas 0.5x) | **55.6%** | 45 | UNDER-only 58.8% (n=34) |
| 2 | **Q43 + 14d recency** | **55.4%** | 92 | Best volume+accuracy. Starters UNDER 67% |
| 3 | **Q40** (aggressive quantile) | **53.7%** | 136 | Most volume. Starters UNDER 60.5% |
| 4 | **Q42** | **53.6%** | 84 | Stars UNDER 67% (n=12) |
| 5 | **Vegas30** (vegas dampened 30%) | **52.8%** | 36 | Stars 80%, High lines 73% |

### Experiments to Run Next

**1. Multi-season training (HIGHEST PRIORITY — untested)**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_MULTISZN_Q43" \
    --quantile-alpha 0.43 \
    --train-start 2023-10-01 \
    --train-end 2026-02-10 \
    --recency-weight 120 \
    --walkforward --force
```
We use only 13% of available data (8.4K of 63K rows). More data may fix generalization.

**2. Q43 + 14d recency with latest data**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_Q43_R14_LATEST" \
    --quantile-alpha 0.43 \
    --recency-weight 14 \
    --train-start 2025-11-02 \
    --train-end 2026-02-11 \
    --walkforward --force
```

**3. Multi-season + Performance boost combo**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_MULTISZN_PERF" \
    --quantile-alpha 0.43 \
    --train-start 2023-10-01 \
    --train-end 2026-02-10 \
    --recency-weight 120 \
    --category-weight "recent_performance=2.0,matchup=1.5,vegas=0.5" \
    --walkforward --force
```

**4. Simulate direction filter (SQL-only, no training)**
```sql
-- Test: suppress Role Player UNDER picks from champion
SELECT
  CASE WHEN predicted_direction = 'UNDER' AND player_tier IN ('Role', 'Bench')
       THEN 'FILTERED_OUT' ELSE 'KEPT' END as status,
  COUNT(*) as picks, COUNTIF(is_correct) as correct,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date >= '2026-02-01' AND edge >= 3
GROUP BY 1;
```

**5. Simulate stale+fresh ensemble (SQL-only)**
```sql
-- Test: champion OVER + Q43 UNDER as combined strategy
-- Check if agreement between models improves confidence
```

### Untested Ideas from Session 222 Analysis
- **`star_teammate_out` feature** — When star sits, role players get +5-10 PPG usage boost. Model doesn't know this. HIGH impact but HIGH effort.
- **V10 feature set** — Features 33-38 exist in BigQuery but aren't used: `dnp_rate`, `pts_slope_10g`, `pts_vs_season_zscore`
- **Shorter training window** (60 days vs 90 days) — The V9_FEB_RETRAIN_Q43 used Dec 7-Feb 4 (60 days) and got 51.4% HR. Baseline experiments used Nov 2-Jan 31 (90 days). Compare.

### Dead Ends (Don't Revisit)
- OVER specialist models (Q55=45%, Q57=18%) — market already adjusts lines
- Baseline/tuned retrains — too few edge picks (4-5 out of 1000+)
- Q43 + Vegas dampening combo — dilutes signal
- Residual modeling, two-stage pipeline, grow policy, CHAOS+quantile

## Also Pending (Lower Priority)

- `br-rosters-batch-daily` — teamAbbr: "all" not supported, needs scraper enhancement
- Q43 shadow model at n=31 edge 3+ graded (need 50+ for promotion, ~6 more days)
- `registry-health-check` scheduler job paused (stale gcr.io image)

## Key Reference Docs

- `docs/08-projects/current/model-improvement-analysis/01-SESSION-222-MODEL-ANALYSIS.md` — Deep decay analysis + feature gaps
- `docs/09-handoff/2026-02-12-SESSION-223-HANDOFF.md` — All 16 experiment results
- `docs/09-handoff/2026-02-12-SESSION-221-HANDOFF.md` — Infrastructure status (all green)
