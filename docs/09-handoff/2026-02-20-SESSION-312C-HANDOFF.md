# Session 312C Handoff — CRITICAL: Best Bets Producing Zero Picks

**Date:** 2026-02-20
**Status:** CRITICAL BUG FOUND — needs immediate fix
**Priority:** P0 — best bets have been outputting 0 picks

---

## The Problem

**Best bets are producing 0 picks every day.** The signal best bets exporter runs, writes a GCS file, but the file always contains `"picks": [], "total_picks": 0`.

- Feb 19: 0 picks (10 games played)
- Feb 20: 0 picks (9 games scheduled)
- The GCS files exist at `gs://nba-props-platform-api/v1/signal-best-bets/`

## Root Cause: ANTI_PATTERN Combo Registry Blocking Everything

The `signal_combo_registry` BQ table has two entries that block **every** edge 5+ pick:

| combo_id | classification | signals | hit_rate | sample_size |
|----------|---------------|---------|----------|-------------|
| `high_edge` | **ANTI_PATTERN** | `["high_edge"]` | 31.3 | 16 |
| `edge_spread_optimal+high_edge` | **ANTI_PATTERN** | `["edge_spread_optimal","high_edge"]` | 31.3 | 16 |

**Why this blocks everything:** The `high_edge` signal fires on every pick with edge >= 5.0 (that's its definition in `ml/signals/high_edge.py`). The `edge_spread_optimal` signal also fires on every edge 5+ pick. So every edge 5+ candidate matches one of these ANTI_PATTERN combos and gets rejected by the aggregator at line 211 of `ml/signals/aggregator.py`:

```python
# Block ANTI_PATTERN combos
if matched and matched.classification == 'ANTI_PATTERN':
    filter_counts['anti_pattern'] += 1
    continue
```

### Proof

Running the exporter locally for 2026-02-20:

```bash
PYTHONPATH=. python3 -c "
from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter
import json
exporter = SignalBestBetsExporter()
result = exporter.generate_json('2026-02-20')
print(json.dumps(result.get('filter_summary'), indent=2))
"
```

Output:
```json
{
  "total_candidates": 60,
  "passed_filters": 0,
  "rejected": {
    "edge_floor": 58,
    "anti_pattern": 2,
    "blacklist": 0, "under_edge_7plus": 0, "familiar_matchup": 0,
    "quality_floor": 0, "bench_under": 0, "line_jumped_under": 0,
    "line_dropped_under": 0, "neg_pm_streak": 0, "signal_count": 0,
    "confidence": 0
  }
}
```

58 rejected by edge floor (< 5.0), **2 rejected by ANTI_PATTERN** (the only 2 edge 5+ picks).

The 2 edge 5+ candidates:
- **LeBron James** OVER 6.5 (catboost_v12, confidence 92.0, quality 96.74)
- **Luka Doncic** UNDER 5.0 (catboost_v9, confidence 87.0, quality 96.74)

Both pass EVERY other filter. Only ANTI_PATTERN blocks them.

## The Fix

### Step 1: Remove the two ANTI_PATTERN entries from BQ

```sql
DELETE FROM `nba-props-platform.nba_predictions.signal_combo_registry`
WHERE classification = 'ANTI_PATTERN'
```

**Why this is safe:** The `high_edge` standalone was meant to be "Standalone BLOCKED" (shouldn't drive selection alone), but the current system already requires MIN_SIGNAL_COUNT=2, so `high_edge` alone never drives selection. The ANTI_PATTERN entry is redundant AND harmful.

The 31.3% HR / N=16 data point is from an old analysis of picks where `high_edge` was the ONLY signal. That scenario can't happen anymore because of the MIN_SIGNAL_COUNT gate.

### Step 2: Update the fallback registry in code

The combo registry has a hardcoded fallback in `ml/signals/combo_registry.py` that's used when BQ isn't available. Check if the fallback also has these ANTI_PATTERN entries and remove them too.

```bash
grep -n "ANTI_PATTERN" ml/signals/combo_registry.py
```

### Step 3: Re-run the export

```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-20 --only signal-best-bets
```

### Step 4: Verify

```bash
# Check GCS output has picks
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/2026-02-20.json | python3 -c "
import json, sys; d=json.load(sys.stdin); print(f'picks: {d[\"total_picks\"]}')
for p in d.get('picks',[]): print(f'  {p[\"player_lookup\"]} {p[\"direction\"]} edge={p[\"edge\"]}')
"

# Check BQ table
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT player_lookup, recommendation, edge, source_model_id
   FROM nba_predictions.signal_best_bets_picks WHERE game_date = '2026-02-20'"
```

### Step 5: Update CLAUDE.md

- Remove `high_edge` "Standalone BLOCKED" status from the signals table
- Note that ANTI_PATTERN entries were removed from combo registry
- Update the `signal_combo_registry` reference: "11 SYNERGISTIC, 0 ANTI_PATTERN"

## Additional Context

### BEST_BETS_MODEL_ID=catboost_v12 on phase6-export

Someone set this env var on the Cloud Function. Check if intentional:
```bash
gcloud run services describe phase6-export --region=us-west2 --project=nba-props-platform \
  --format="yaml(spec.template.spec.containers[0].env)" | grep -A1 BEST_BETS
```

Effects:
- Signal annotator queries V12 predictions (pick_signal_tags shows V12-only for recent dates)
- Aggregator min_confidence = 0.90 (V12 config) — but since confidence scores are 87-95 on 0-100 scale and floor is 0.90 on 0-1 scale, this never actually blocks anything
- **This is a scale mismatch bug** — harmless now but should be fixed eventually

### Multi-model Phase A is deployed and working

Algorithm version = `v307_multi_source` since Feb 11. The multi-model query correctly finds picks from all CatBoost families. The problem is entirely the ANTI_PATTERN registry entries.

### Combo Registry After Fix (11 entries, all SYNERGISTIC)

| combo_id | hit_rate | N |
|----------|----------|---|
| bench_under | 76.9% | 156 |
| blowout_recovery | 56.9% | 112 |
| prop_line_drop_over | 71.6% | 109 |
| high_ft_under | 64.1% | 74 |
| high_usage_under | 68.1% | 47 |
| high_edge+minutes_surge | 79.4% | 34 |
| 3pt_bounce | 74.9% | 28 |
| volatile_under | 73.1% | 26 |
| edge_spread_optimal+high_edge+minutes_surge | 95.5% | 22 |
| cold_snap | 93.3% | 15 |
| b2b_fatigue_under | 85.7% | 14 |

## Key Files

| File | Line | What |
|------|------|------|
| `ml/signals/aggregator.py` | 204-213 | ANTI_PATTERN blocking logic |
| `ml/signals/combo_registry.py` | - | Combo loading + fallback entries |
| `ml/signals/high_edge.py` | 11-17 | high_edge signal (fires at edge >= 5.0) |
| `data_processors/publishing/signal_best_bets_exporter.py` | 236-244 | Aggregator creation + call |
| `shared/config/model_selection.py` | 17-21 | V12 min_confidence config |
