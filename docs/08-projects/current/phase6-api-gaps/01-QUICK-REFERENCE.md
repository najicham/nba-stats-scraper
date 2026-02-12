# Phase 6 API Gaps - Quick Reference

**TL;DR:** Frontend identified 16 issues across 12 endpoints. **4 quick wins** (<30 min total), **2 high-impact features** (8 hours), **3 enhancements** (2 hours).

---

## 🚀 Quick Wins (30 minutes total)

```bash
# 1. days_rest - ALREADY QUERIED, just add to output
# File: tonight_all_players_exporter.py, line ~385
'days_rest': p.get('days_rest'),

# 2. minutes_avg - Alias for season_mpg
'minutes_avg': safe_float(p.get('season_mpg')),

# 3. game_time - Remove leading whitespace
# Line 108: Change %l to %-I
FORMAT_TIMESTAMP('%-I:%M %p ET', game_date_est, 'America/New_York')

# 4. Confidence scale - Change to 0.0-1.0
# Line 433
'confidence': safe_float(p.get('confidence_score')) / 100.0

# 5. recent_form - Calculate from last_5 vs season
if last_5_ppg and season_ppg:
    diff = last_5_ppg - season_ppg
    recent_form = 'Hot' if diff >= 3 else 'Cold' if diff <= -3 else 'Neutral'
```

**Result:** 5 fields populated, better data formatting, immediate UX improvement

---

## ⭐ High-Impact Features (8 hours)

### prediction.factors (6 hours)
**Frontend's #1 request** - "Why this pick?" reasoning

```python
def _build_prediction_factors(player_data, feature_data):
    factors = []

    # Matchup
    opp_def_rating = feature_data.get('feature_13_value')
    if opp_def_rating > 115:
        factors.append("Faces weak defense (115+ def rating)")

    # Historical trend
    if overs >= 7:
        factors.append(f"Hot streak: {overs}-{unders} over last 10")

    # Fatigue
    if fatigue_level == 'fresh':
        factors.append("Well-rested (3+ days)")

    # Edge
    if edge >= 5:
        factors.append(f"Strong model edge ({edge:.1f} points)")

    return factors[:4]
```

### last_10_lines array (2 hours)
**Fixes inaccurate O/U calculation** for 31 players (16% of lined players)

```sql
-- Add to tonight_all_players_exporter.py query
WITH last_10_lines AS (
  SELECT
    player_lookup,
    ARRAY_AGG(points_line ORDER BY game_date DESC LIMIT 10) as historical_lines
  FROM nba_analytics.player_game_summary
  WHERE game_date < @target_date AND points_line IS NOT NULL
  GROUP BY player_lookup
)
```

**Output:**
```json
{
  "last_10_points": [25, 18, 22, 30, 19, 21, 24, 17, 23, 20],
  "last_10_lines": [20.5, 18.5, 19.5, 21.5, 17.5, 19.5, 20.5, 16.5, 19.5, 18.5],
  "last_10_results": ["O", "U", "O", "O", "O", "O", "O", "O", "O", "O"]
}
```

Frontend can now accurately compute O/U by comparing `last_10_points[i]` to `last_10_lines[i]`.

---

## 🔧 Medium-Priority Fixes (2 hours)

### Bogus odds validation (30 min)
```python
def safe_odds(value):
    if value and -10000 <= value <= 10000:
        return value
    return None

'over_odds': safe_odds(p.get('over_odds')),
'under_odds': safe_odds(p.get('under_odds')),
```

### player_lookup in picks (30 min)
Check `all_subsets_picks_exporter.py` - already in materialized table, may just need to add to output.

### Best bets methodology (1 hour)
**Problem:** Queries `prediction_accuracy` (graded historical data) for current date → 0 results

**Fix:**
```python
# Use different table based on date
if target_date <= today:
    query_table = 'nba_predictions.prediction_accuracy'  # Historical/graded
else:
    query_table = 'nba_predictions.player_prop_predictions'  # Current/future
```

---

## 📅 New Endpoints (2 hours)

### 1. Date-specific tonight files (15 min)
```python
# Export both formats
self.upload_to_gcs(json_data, 'tonight/all-players.json', 'max-age=300')
self.upload_to_gcs(json_data, f'tonight/{target_date}.json', 'max-age=86400')
```

Enables: `/tonight/2026-02-10.json` for historical browsing

### 2. Calendar game counts (1 hour)
```python
# New: calendar_exporter.py
def generate_json(days_back=30):
    # Query game counts per date
    return {
        "2026-02-11": 14,
        "2026-02-10": 4,
        ...
    }
```

Enables: Calendar widget with game indicators

---

## 📊 Impact Summary

| Sprint | Items | Hours | Impact |
|--------|-------|-------|--------|
| Sprint 1: Quick Wins | 7 | 0.5h | Immediate data completeness |
| Sprint 2: High-Impact | 2 | 8h | Major UX features unlocked |
| Sprint 3: Enhancements | 3 | 2h | Nice-to-have improvements |
| **TOTAL** | **12** | **10.5h** | **Comprehensive API coverage** |

---

## 🎯 Recommended Order

1. **Deploy Quick Wins** (30 min) → Push today
   - `days_rest`, `minutes_avg`, `game_time`, `confidence`, `recent_form`

2. **Implement High-Impact** (8 hours) → Sprint this week
   - `prediction.factors` (Phase 1 - basic)
   - `last_10_lines` array

3. **Fix Best Bets** (1 hour) → Sprint this week
   - 0 picks → 10-25 picks for current date

4. **Add Enhancements** (2 hours) → Next week
   - Odds validation
   - `player_lookup` in picks
   - Date-specific tonight files
   - Calendar endpoint

---

## 🧪 Testing Commands

```bash
# Test tonight endpoint
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | jq '.games[0].players[0]'

# Verify fields populated
jq '.games[0].players[] | select(.has_line == true) | {
  days_rest,
  minutes_avg,
  recent_form,
  prediction: {factors, confidence}
}' all-players.json

# Check best bets
curl https://storage.googleapis.com/nba-props-platform-api/v1/best-bets/latest.json | jq '.total_picks'

# Test historical date
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/2026-02-10.json

# Calendar counts
curl https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json
```

---

## 📁 Files to Modify

```
data_processors/publishing/
├── tonight_all_players_exporter.py    ← Most changes here (factors, fields, validation)
├── best_bets_exporter.py              ← Fix date-based table selection
├── all_subsets_picks_exporter.py      ← Add player_lookup to output
├── calendar_exporter.py               ← NEW FILE
└── exporter_utils.py                  ← Add safe_odds() helper

backfill_jobs/publishing/
└── daily_export.py                    ← Add calendar to export types
```

---

## 🚦 Status Tracking

- [ ] Sprint 1 approved
- [ ] Sprint 2 approved
- [ ] Sprint 3 approved
- [ ] Quick wins deployed
- [ ] High-impact features tested
- [ ] Frontend validated changes
- [ ] Documentation updated

---

**See:** `00-FRONTEND-GAP-ANALYSIS.md` for detailed analysis and implementation specs.
