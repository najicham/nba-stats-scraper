# Session 45 Handoff: V1+4 Deployed, BDL Mapping Built, Splits Scraper Fixed

**Date:** 2026-01-14
**Previous Session:** 44 (V1+4 Features Success)
**Status:** V1+4 deployed, infrastructure for V2 features in place

---

## Executive Summary

Session 45 achieved three major milestones:
1. **Deployed V1+4 Features model to production** (MAE 1.66, 2.8% improvement)
2. **Built BDL player ID mapping** (466 pitchers mapped, 91%+ match rate)
3. **Fixed splits scraper** to correctly parse BDL API response

The splits backfill is running and will provide `home_away_k_diff` and `day_night_k_diff` features for V2 training.

---

## What Was Accomplished

### 1. V1+4 Features Model Deployed to Production

**Model ID:** `mlb_pitcher_strikeouts_v1_4features_20260114_142456`

**Changes Made:**
- Updated `predictions/mlb/pitcher_strikeouts_predictor.py`:
  - Added 6 new features to FEATURE_ORDER (25 total)
  - Added FEATURE_DEFAULTS for new features
  - Updated prepare_features() with new feature mappings
  - Updated BigQuery queries to fetch new columns
  - Changed model path to new V1+4 model

**New Features Added:**
| Feature | Default | Description |
|---------|---------|-------------|
| f15_opponent_team_k_rate | 0.22 | Opponent's team-wide K rate |
| f16_ballpark_k_factor | 1.0 | Ballpark strikeout factor |
| f17_month_of_season | 6 | Month (1-12) |
| f18_days_into_season | 90 | Days since season start |
| f27_avg_k_vs_opponent | 5.0 | Historical Ks vs opponent |
| f28_games_vs_opponent | 2 | Games vs opponent |

**GCS Location:** `gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json`

### 2. BDL Player ID Mapping Built

**Script:** `scripts/mlb/build_bdl_player_mapping.py`

**Results:**
- 466 pitchers with BDL IDs (91.3% of 505 total)
- 44 pitchers not found (mostly due to special characters or timeouts)
- Updated `mlb_reference.mlb_players_registry.bdl_player_id` column

**Sample Mappings:**
| Player | MLB Lookup | BDL ID |
|--------|------------|--------|
| Logan Webb | logan_webb | 971 |
| Kevin Gausman | kevin_gausman | 741 |
| Cole Ragans | cole_ragans | 56 |
| Clayton Kershaw | clayton_kershaw | 2680 |

**Not Found (Special Characters):**
- Cristopher Sánchez, Germán Márquez, Jesús Luzardo
- Fix: Search without accents or by last name only

### 3. Splits Scraper Fixed

**File:** `scrapers/mlb/balldontlie/mlb_player_splits.py`

**Problem:** Transform expected flat keys (`home`, `away`) but API returns nested arrays (`byBreakdown[]`)

**Fix Applied:**
```python
# Old (broken):
processed_splits["home"] = splits_data.get("home", {})

# New (working):
for split in splits_data.get("byBreakdown", []):
    if split.get("split_name", "").lower() == "home":
        home_split = split
```

**Now Calculates:**
- `home_k_per_9`, `away_k_per_9`, `home_away_k_diff`
- `day_k_per_9`, `night_k_per_9`, `day_night_k_diff`

**Validated with Logan Webb 2024:**
- Home K/9: 7.03
- Away K/9: 8.13
- Home-Away Diff: -1.10 (better away)

### 4. Splits Backfill Running

**Script:** `scripts/mlb/backfill_pitcher_splits.py`

**Status:** Running in background
- 466 pitchers x 2 seasons = 932 requests
- First run: 915/932 success (98.2%)
- Re-running with fixed BigQuery save

**Table:** `mlb_raw.bdl_pitcher_splits`

---

## Files Created/Modified

| File | Action | Purpose |
|------|--------|---------|
| `predictions/mlb/pitcher_strikeouts_predictor.py` | MODIFIED | V1+4 features support |
| `scripts/mlb/build_bdl_player_mapping.py` | CREATED | BDL player ID mapping |
| `scripts/mlb/backfill_pitcher_splits.py` | CREATED | Splits data backfill |
| `scripts/mlb/populate_splits_features.py` | CREATED | Feature population |
| `scrapers/mlb/balldontlie/mlb_player_splits.py` | MODIFIED | Fixed transform_data() |
| `scripts/mlb/bdl_mapping_results.json` | CREATED | Mapping results |
| `scripts/mlb/splits_backfill_results.json` | CREATED | Backfill results |

---

## Remaining Tasks for Next Session

### 1. Complete Splits Backfill (In Progress)
The backfill is running. After completion:
```bash
# Check results
cat scripts/mlb/splits_backfill_results.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Records: {d[\"success_count\"]}')"

# Verify BigQuery table
python3 << 'EOF'
from google.cloud import bigquery
client = bigquery.Client()
query = "SELECT COUNT(*) as cnt FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`"
print(list(client.query(query).result())[0].cnt)
EOF
```

### 2. Populate Features in pitcher_game_summary
```bash
python scripts/mlb/populate_splits_features.py
```

This will update `pitcher_game_summary` with:
- `home_away_k_diff`
- `day_night_k_diff`

### 3. Add Splits Features to Training Script

In `scripts/mlb/train_pitcher_strikeouts.py`, add:
```python
# After f18_days_into_season
'f19_home_away_k_diff',  # NEW: Pitcher's home-away K/9 difference
'f14_day_night_k_diff',  # NEW: Pitcher's day-night K/9 difference
```

Also add to BigQuery query and COALESCE defaults.

### 4. Train V2 with Full Features

After features populated:
```bash
PYTHONPATH=. python scripts/mlb/train_pitcher_strikeouts.py
```

Expected: MAE < 1.65 (improvement over V1+4's 1.66)

---

## Feature Population Status

| Feature | Status | Population | Notes |
|---------|--------|------------|-------|
| opponent_team_k_rate | ✅ DONE | 100% | In V1+4 |
| ballpark_k_factor | ✅ DONE | 100% | In V1+4, ranked #7 |
| month_of_season | ✅ DONE | 100% | In V1+4 |
| days_into_season | ✅ DONE | 100% | In V1+4 |
| home_away_k_diff | 🔄 PENDING | 0% | Backfill running |
| day_night_k_diff | 🔄 PENDING | 0% | Backfill running |
| vs_opponent_k_per_9 | ⏸️ LATER | 0% | Versus scraper ready |
| is_day_game | ❌ No Source | 0% | Need to research |
| game_total_line | ❌ Empty | 0% | Need backfill |
| umpire_k_factor | ❌ No Table | 0% | Table doesn't exist |

---

## Commands to Resume

### Check Backfill Progress
```bash
tail -20 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b994bae.output
```

### Verify Splits Data in BigQuery
```bash
python3 << 'EOF'
from google.cloud import bigquery
client = bigquery.Client()
query = """
SELECT season, COUNT(*) as cnt,
       AVG(home_away_k_diff) as avg_home_away,
       AVG(day_night_k_diff) as avg_day_night
FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`
GROUP BY season
"""
for row in client.query(query).result():
    print(f"Season {row.season}: {row.cnt} records, avg_home_away={row.avg_home_away:.2f}, avg_day_night={row.avg_day_night:.2f}")
EOF
```

### Populate Features
```bash
python scripts/mlb/populate_splits_features.py
```

### Train V2
```bash
PYTHONPATH=. python scripts/mlb/train_pitcher_strikeouts.py
```

---

## Key Insights

### 1. Home vs Away K/9 Varies Significantly
Logan Webb example:
- Home: 7.03 K/9 (ERA 2.83)
- Away: 8.13 K/9 (ERA 4.11)
- Diff: -1.10 (counterintuitively better away)

This suggests home_away_k_diff is a valuable feature that captures pitcher-specific tendencies.

### 2. BDL API Has Rate Limits
- Some timeouts during backfill (~2% error rate)
- 0.1-0.15s delay between requests works well
- Retry logic could improve success rate

### 3. BDL Player IDs Different from MLB Stats API
- Logan Webb: MLB ID 657277, BDL ID 971
- Need mapping table for all BDL scrapers
- Special characters in names cause issues (Sánchez, Márquez)

---

## Model Comparison Summary

| Model | Algorithm | Features | Test MAE | Status |
|-------|-----------|----------|----------|--------|
| V1 Original | XGBoost | 19 | 1.708 | Archived |
| **V1+4 Features** | XGBoost | 25 | **1.66** | **Production** |
| V2-Lite CatBoost | CatBoost | 21 | 1.75 | Failed |
| V2 Full (Planned) | XGBoost | 27 | TBD | Pending |

---

## Session Statistics

- **Duration:** ~2 hours
- **Tasks Completed:** 4 (deploy, mapping, scraper fix, backfill script)
- **Tasks In Progress:** 1 (splits backfill)
- **Key Wins:**
  - V1+4 model in production
  - Infrastructure for V2 features ready
  - 466 pitcher BDL IDs mapped

---

## Next Session Priority Order

1. ✅ Verify splits backfill completed successfully
2. Run `populate_splits_features.py` to update pitcher_game_summary
3. Add f19_home_away_k_diff and f14_day_night_k_diff to training script
4. Train V2 with full feature set (27 features)
5. Compare V2 vs V1+4 performance
6. If improved, deploy V2 to production
