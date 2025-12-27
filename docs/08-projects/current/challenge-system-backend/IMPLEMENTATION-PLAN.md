# Challenge System Backend - Implementation Plan

**Created:** 2025-12-27
**Related:** [SCHEMA-ALIGNMENT.md](./SCHEMA-ALIGNMENT.md)

---

## Phase 1: Critical Fixes (Tonight's Players)

### 1.1 Fix game_time NULL

**File:** `data_processors/publishing/tonight_all_players_exporter.py`
**Method:** `_query_games()` (lines 91-109)

**Current Query:**
```sql
SELECT DISTINCT
    CONCAT(...) as game_id,
    home_team_tricode as home_team_abbr,
    away_team_tricode as away_team_abbr,
    game_status
FROM nbac_schedule
WHERE game_date = @target_date
```

**Updated Query:**
```sql
SELECT DISTINCT
    CONCAT(...) as game_id,
    home_team_tricode as home_team_abbr,
    away_team_tricode as away_team_abbr,
    game_status,
    FORMAT_TIMESTAMP('%I:%M %p ET', game_date_est, 'America/New_York') as game_time
FROM nbac_schedule
WHERE game_date = @target_date
ORDER BY game_date_est, game_id
```

**Effort:** 5 minutes

---

### 1.2 Rename Field: player_full_name → name

**File:** `data_processors/publishing/tonight_all_players_exporter.py`
**Location:** `_build_games_data()` (line 340)

**Change:**
```python
# Before
'player_full_name': p.get('player_full_name', player_lookup),

# After
'name': p.get('player_full_name', player_lookup),
```

**Effort:** 2 minutes

---

### 1.3 Rename Field: team_abbr → team

**File:** `data_processors/publishing/tonight_all_players_exporter.py`
**Location:** `_build_games_data()` (line 341)

**Change:**
```python
# Before
'team_abbr': p.get('team_abbr'),

# After
'team': p.get('team_abbr'),
```

**Effort:** 2 minutes

---

## Phase 2: Props Array Structure

### 2.1 Add Odds Query

**New CTE in `_query_players()`:**
```sql
best_odds AS (
    SELECT
        player_lookup,
        points_line,
        MAX(CASE WHEN bet_side = 'over' THEN odds_american END) as over_odds,
        MAX(CASE WHEN bet_side = 'under' THEN odds_american END) as under_odds
    FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
    WHERE game_date = @target_date
      AND is_best_line = TRUE
    GROUP BY player_lookup, points_line
)
```

**Join:**
```sql
LEFT JOIN best_odds bo ON gc.player_lookup = bo.player_lookup
```

**Select:**
```sql
bo.over_odds,
bo.under_odds
```

**Effort:** 15 minutes

---

### 2.2 Restructure to Props Array

**File:** `data_processors/publishing/tonight_all_players_exporter.py`
**Location:** `_build_games_data()` (lines 364-376)

**Current Structure:**
```python
if p.get('has_line'):
    player_data.update({
        'current_points_line': ...,
        'predicted_points': ...,
        'confidence_score': ...,
        'recommendation': ...,
    })
```

**New Structure:**
```python
if p.get('has_line'):
    player_data['props'] = [{
        'stat_type': 'points',
        'line': self._safe_float(p.get('current_points_line')),
        'over_odds': p.get('over_odds'),
        'under_odds': p.get('under_odds'),
    }]
    # Keep prediction data separate (not in frontend spec but useful)
    player_data['prediction'] = {
        'predicted': self._safe_float(p.get('predicted_points')),
        'confidence': self._safe_float(p.get('confidence_score')),
        'recommendation': p.get('recommendation'),
    }
```

**Effort:** 20 minutes

---

## Phase 3: Live Scores Alignment

### 3.1 Investigate game_id Matching

**Check frontend code:**
```bash
grep -r "game_id" /home/naji/code/props-web/src/lib/firebase-challenges.ts
```

**Questions to Answer:**
1. Does frontend match picks to live scores by game_id?
2. Or does it match by player_lookup only?

If matching by player_lookup: No changes needed.
If matching by game_id: Need to add formatted game_id to live scores.

---

### 3.2 Add Formatted game_id (if needed)

**File:** `data_processors/publishing/live_scores_exporter.py`
**Location:** `_transform_games()` (lines 257-268)

**Add:**
```python
# Generate consistent game_id format
game_date_str = target_date.replace("-", "")
formatted_game_id = f"{game_date_str}_{away_abbr}_{home_abbr}"

games.append({
    'game_id': game_id,  # Keep BDL ID
    'formatted_game_id': formatted_game_id,  # Add formatted version
    ...
})
```

---

## Phase 4: Testing & Deployment

### 4.1 Local Testing

```bash
# Export for today
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. .venv/bin/python -c "
from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
from datetime import date
exporter = TonightAllPlayersExporter()
data = exporter.generate_json(str(date.today()))
import json
print(json.dumps(data['games'][0] if data['games'] else {}, indent=2))
"
```

### 4.2 Deploy Phase 6 Service

```bash
./bin/deploy/deploy_phase6_function.sh
```

### 4.3 Verify Production Output

```bash
# Wait for next export cycle, then:
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | jq '.games[0]'
```

### 4.4 Update Frontend Mock Data

**File:** `/home/naji/code/props-web/public/mock/v1/tonight/all-players.json`

Update to match new schema structure.

---

## Risk Assessment

| Change | Risk Level | Mitigation |
|--------|------------|------------|
| game_time addition | Low | Pure addition, no breaking changes |
| Field renames | Medium | Frontend must update field references |
| Props array | Medium | Frontend must adapt parsing logic |
| Odds data | Low | Pure addition if structured correctly |
| game_id format | High | Could break pick-to-live matching |

---

## Rollback Plan

If issues arise:
1. Revert commits in nba-stats-scraper
2. Redeploy Phase 6 service
3. Manual export to reset GCS files:
   ```bash
   PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --date $(date +%Y-%m-%d) --only tonight
   ```

---

## Acceptance Criteria

1. `game_time` returns formatted time like "7:30 PM ET"
2. Player objects have `name` and `team` fields (not `player_full_name`, `team_abbr`)
3. Players with lines have `props` array with `stat_type`, `line`, `over_odds`, `under_odds`
4. Live scores can be matched to picks via `player_lookup`
5. Frontend challenge creation and grading work end-to-end
