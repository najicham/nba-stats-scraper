# Phase 6 API Gaps - Final Execution Plan

**Date:** February 11, 2026
**Status:** ✅ Opus-Approved with Corrections
**Execution Mode:** Feature branch → 3 sprints → merge to main

---

## 🔴 Critical Corrections from Opus Final Review

### Issue #1: Agents A and B Both Edit Same File ⚠️

**Problem:** Sprint 2 agents A (last_10_lines) and B (prediction.factors) both modify `tonight_all_players_exporter.py` → merge conflicts guaranteed

**Fix:** Serialize A and B, parallelize C with A

**Revised Sprint 2:**
```
Agent A: last_10_lines (tonight_all_players_exporter.py)     [2h]
Agent C: best_bets fix (best_bets_exporter.py)               [1h, parallel with A]
   -- WAIT for Agent A to finish --
Agent B: prediction.factors (tonight_all_players_exporter.py) [2-3h, after A]
```

**Wall time:** ~4-5 hours for Sprint 2 (not 1.5h)

---

### Issue #2: last_10_lines Array Length Mismatch ⚠️

**Problem:** Original proposal filtered to `points_line IS NOT NULL` → different array lengths

**Opus Fix:** Keep same games, use nulls for missing lines

**Correct Implementation:**
```python
# Modify EXISTING _query_last_10_results to ALSO return points_line
# Don't filter to IS NOT NULL
# Same 10 games for all arrays

{
  "last_10_points": [25, 18, 22, 30, 19, null, 24, 17, 23, 20],
  "last_10_lines":  [20.5, 18.5, null, 21.5, 17.5, null, 20.5, null, 19.5, 18.5],
  "last_10_results": ["O", "U", "-", "O", "O", "DNP", "O", "-", "O", "O"]
}

# Frontend logic:
# last_10_lines[i] !== null ? (points[i] >= lines[i] ? "O" : "U") : "-"
```

**Benefits:**
- Arrays always match in length (same 10 games)
- Frontend computes accurate O/U where lines exist
- Shows "-" where lines missing (honest, not fabricated)
- 31 all-dash players will still have mostly null lines, but games WITH lines will be accurate
- Don't need separate CTE, just add `points_line` to existing query

---

### Issue #3: Null-Safe Edge Computation ⚠️

**Problem:** Code sample didn't show null checks for predicted/line

**Fix:**
```python
predicted = player_data.get('predicted_points')
line = player_data.get('current_points_line')
if predicted and line:
    edge = abs(predicted - line)
    if edge >= 5:
        factors.append(f"Strong model conviction ({edge:.1f} point edge)")
    elif edge >= 3:
        factors.append(f"Solid model edge ({edge:.1f} points)")
```

---

## ✅ Opus Confirmations

### Directional Factors - Edge Case Handling

**Opus Clarification:**
- **Always include edge factor if edge >= 3** (don't gate on recommendation)
- Edge is inherently directional (prediction IS the direction)
- If ALL other factors contradict → return only edge factor
- Example: `["Strong model conviction (5.2 point edge)"]` = honest answer
- Empty array `[]` OK when edge < 3 and nothing supports

**Action:** Implement as specified

---

### Best Bets Race Condition

**Opus Decision:** `target >= today` is correct, keep it

**Rationale:** Yesterday's unfinished late games not appearing is acceptable (nobody betting on yesterday's games)

---

### Deployment Strategy

**Opus Recommendation:** Use feature branch (Option A)

**Workflow:**
```bash
git checkout -b feature/phase6-api-gaps
# All Sprint 1-3 work on this branch
# Merge to main when complete
```

**Rationale:** Safe, costs nothing, prevents partial deploys

---

## 🚀 Final Execution Plan

### Setup: Create Feature Branch

```bash
cd /home/naji/code/nba-stats-scraper
git checkout main
git pull origin main
git checkout -b feature/phase6-api-gaps
```

---

## Sprint 1: Quick Wins (Me, 45 minutes)

**Direct implementation - no agents**

### Changes (7 items)

1. **days_rest** - Add to output (already queried)
2. **minutes_avg** - Add alias for season_mpg
3. **game_time** - Use LTRIM() to remove leading space
4. **recent_form** - Calculate Hot/Cold/Neutral
5. **safe_odds()** - Add validation helper
6. **player_lookup** - Add to picks endpoint
7. Apply odds validation

### Files Modified
- `data_processors/publishing/tonight_all_players_exporter.py`
- `data_processors/publishing/exporter_utils.py`
- `data_processors/publishing/all_subsets_picks_exporter.py`

### Validation
```bash
# Test locally
PYTHONPATH=. python -c "
from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
exporter = TonightAllPlayersExporter()
data = exporter.generate_json('2026-02-11')
print(f'Total players: {data[\"total_players\"]}')
print(f'Sample fields: {list(data[\"games\"][0][\"players\"][0].keys())}')
"

# Commit on feature branch
git add .
git commit -m "feat: Sprint 1 - Quick wins (7 changes)

- Add days_rest field
- Add minutes_avg alias
- Fix game_time whitespace with LTRIM()
- Add recent_form calculation
- Add safe_odds() validation
- Add player_lookup to picks
- Apply odds validation

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Sprint 2: High-Impact Features (3 Agents, 4-5 hours wall time)

**CRITICAL:** Serialize agents A and B (both edit same file)

### Agent A: last_10_lines Implementation (2 hours)

**File:** `data_processors/publishing/tonight_all_players_exporter.py`

**Task:** Modify existing `_query_last_10_results` to ALSO return `points_line`

**CRITICAL from Opus:** Same-length arrays, nulls for missing lines

**Implementation:**
```python
def _query_last_10_results(self, player_lookups: List[str], before_date: str) -> Dict[str, List]:
    """Query last 10 over/under results AND lines for players."""
    if not player_lookups:
        return {}

    query = """
    WITH recent_games AS (
        SELECT
            player_lookup,
            game_date,
            over_under_result,
            points,
            points_line  -- ADD THIS (don't filter to IS NOT NULL)
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date < @before_date
          AND player_lookup IN UNNEST(@player_lookups)
          -- NOTE: Don't filter to points_line IS NOT NULL
          -- We want same 10 games for all arrays
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) <= 10
    )
    SELECT
        player_lookup,
        ARRAY_AGG(
            STRUCT(over_under_result, points, points_line)
            ORDER BY game_date DESC
        ) as last_10
    FROM recent_games
    GROUP BY player_lookup
    """

    params = [
        bigquery.ScalarQueryParameter('before_date', 'DATE', before_date),
        bigquery.ArrayQueryParameter('player_lookups', 'STRING', player_lookups)
    ]
    results = self.query_to_list(query, params)

    # Build lookup map
    last_10_map = {}
    for r in results:
        player = r['player_lookup']
        games = r.get('last_10', [])

        results_list = []
        points_list = []
        lines_list = []  # ADD THIS

        for g in games:
            if isinstance(g, dict):
                ou = g.get('over_under_result')
                pts = g.get('points')
                line = g.get('points_line')  # ADD THIS
            else:
                ou = getattr(g, 'over_under_result', None)
                pts = getattr(g, 'points', None)
                line = getattr(g, 'points_line', None)  # ADD THIS

            # O/U result
            if ou == 'OVER':
                results_list.append('O')
            elif ou == 'UNDER':
                results_list.append('U')
            else:
                results_list.append('-')

            # Points (can be None if DNP)
            points_list.append(int(pts) if pts is not None else None)

            # Lines (can be None if no line that game)
            lines_list.append(float(line) if line is not None else None)

        # Calculate record
        overs = results_list.count('O')
        unders = results_list.count('U')

        last_10_map[player] = {
            'results': results_list,
            'points': points_list,
            'lines': lines_list,  # ADD THIS
            'record': f"{overs}-{unders}" if (overs + unders) > 0 else None
        }

    return last_10_map

# In _build_games_data, add to output:
player_data['last_10_points'] = last_10.get('points', [])
player_data['last_10_lines'] = last_10.get('lines', [])   # ADD THIS
player_data['last_10_results'] = last_10.get('results', [])
```

**Validation:**
```bash
# Arrays must match in length
jq '.games[0].players[] | select(.has_line) | {
  name,
  points_len: (.last_10_points | length),
  lines_len: (.last_10_lines | length),
  results_len: (.last_10_results | length)
}' all-players.json | head -10

# All should be same length (0-10)

# Check for nulls where lines missing
jq '.games[0].players[] | select(.has_line) | {
  name,
  lines: .last_10_lines
}' all-players.json | head -20
```

**Commit:**
```bash
git add data_processors/publishing/tonight_all_players_exporter.py
git commit -m "feat: Add last_10_lines array with same-length nulls

- Modify _query_last_10_results to return points_line
- Arrays match in length (same 10 games)
- Nulls where lines missing (accurate, not fabricated)
- Fixes 31 players with all-dash O/U results

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Agent C: Best Bets Table Selection (1 hour) - PARALLEL with Agent A

**File:** `data_processors/publishing/best_bets_exporter.py`

**Task:** Add date-based table selection (use predictions table for current/future dates)

**CRITICAL from Opus:**
- Keep `target >= today` boundary
- Use explicit boolean flag
- Keep UNDER-only filter in historical accuracy CTE

**Implementation:** See `05-CORRECTED-IMPLEMENTATION-PLAN.md` lines 580-720

**Validation:**
```bash
# Historical date (should use accuracy table)
PYTHONPATH=. python -c "
from data_processors.publishing.best_bets_exporter import BestBetsExporter
exporter = BestBetsExporter()
data = exporter.generate_json('2026-02-09')
print(f'Historical: {data[\"total_picks\"]} picks')"

# Current date (should use predictions table, return >0 picks)
PYTHONPATH=. python -c "
from data_processors.publishing.best_bets_exporter import BestBetsExporter
exporter = BestBetsExporter()
data = exporter.generate_json('2026-02-11')
print(f'Current: {data[\"total_picks\"]} picks (was 0, should be >0 now)')"
```

**Commit:**
```bash
git add data_processors/publishing/best_bets_exporter.py
git commit -m "fix: Best bets table selection for current dates

- Use predictions table for current/future dates
- Use accuracy table for historical dates
- Explicit boolean flag (not string matching)
- Fixes 0 picks for current date issue

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### ⏸️ WAIT for Agent A to Complete

**Why:** Agent B also edits `tonight_all_players_exporter.py`

---

### Agent B: prediction.factors with Directional Logic (2-3 hours) - AFTER Agent A

**File:** `data_processors/publishing/tonight_all_players_exporter.py`

**Task:** Add feature store JOIN and directional factor generation

**CRITICAL from Opus:**
- Always include edge factor if edge >= 3 (don't gate on recommendation)
- Only include other factors if they support the recommendation
- Null-safe edge computation

**Implementation:**

**Step 1: Add feature store CTE**
```sql
-- In main query, add CTE after game_context:
feature_data AS (
    SELECT
        player_lookup,
        game_date,
        matchup_quality_pct,
        feature_13_value as opponent_def_rating,
        feature_14_value as opponent_pace,
        feature_quality_score,
        default_feature_count
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date = @target_date
)

-- Join in main query:
LEFT JOIN feature_data fd ON gc.player_lookup = fd.player_lookup
```

**Step 2: Add directional factor builder**
```python
def _build_prediction_factors(
    self,
    player_data: Dict,
    feature_data: Dict,
    last_10_record: Optional[str]
) -> List[str]:
    """
    Build up to 4 DIRECTIONAL factors supporting the recommendation.

    Opus Priority: Edge > Matchup > Trend > Fatigue > Form
    Edge is always included if >= 3 (inherently directional).
    Other factors only if they support the recommendation.
    """
    factors = []
    rec = player_data.get('recommendation')

    if not rec:
        return []

    # 1. EDGE FIRST - Always include if >= 3 (Opus: don't gate on rec)
    predicted = player_data.get('predicted_points')
    line = player_data.get('current_points_line')
    if predicted and line:  # Null-safe (Opus Issue #3)
        edge = abs(predicted - line)
        if edge >= 5:
            factors.append(f"Strong model conviction ({edge:.1f} point edge)")
        elif edge >= 3:
            factors.append(f"Solid model edge ({edge:.1f} points)")

    # 2. MATCHUP - Only if supports recommendation
    opp_def_rating = feature_data.get('opponent_def_rating')
    if opp_def_rating:
        if opp_def_rating > 115 and rec == 'OVER':
            factors.append("Weak opposing defense favors scoring")
        elif opp_def_rating < 105 and rec == 'UNDER':
            factors.append("Elite opposing defense limits scoring")

    # 3. HISTORICAL TREND - Only if supports
    if last_10_record:
        try:
            overs, unders = map(int, last_10_record.split('-'))
            total = overs + unders
            if total >= 5:
                if overs >= 7 and rec == 'OVER':
                    factors.append(f"Hot over streak: {overs}-{unders} last 10")
                elif unders >= 7 and rec == 'UNDER':
                    factors.append(f"Cold under streak: {overs}-{unders} last 10")
                elif overs >= 5 and rec == 'OVER':
                    factors.append(f"Trending over: {overs}-{unders} last 10")
                elif unders >= 5 and rec == 'UNDER':
                    factors.append(f"Trending under: {overs}-{unders} last 10")
        except (ValueError, AttributeError):
            pass

    # 4. FATIGUE - Only if supports
    fatigue_level = player_data.get('fatigue_level')
    days_rest = player_data.get('days_rest')
    if (fatigue_level == 'fresh' or (days_rest and days_rest >= 3)) and rec == 'OVER':
        factors.append("Well-rested, favors performance")
    elif (fatigue_level == 'tired' or (days_rest is not None and days_rest == 0)) and rec == 'UNDER':
        factors.append("Back-to-back fatigue risk")

    # 5. RECENT FORM - Only if supports
    recent_form = player_data.get('recent_form')
    if recent_form == 'Hot' and rec == 'OVER':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        if last_5 and season:
            diff = last_5 - season
            factors.append(f"Scoring surge: +{diff:.1f} vs season avg")
    elif recent_form == 'Cold' and rec == 'UNDER':
        last_5 = player_data.get('last_5_ppg')
        season = player_data.get('season_ppg')
        if last_5 and season:
            diff = abs(last_5 - season)
            factors.append(f"Recent slump: -{diff:.1f} vs season avg")

    return factors[:4]
```

**Step 3: Integrate into output**
```python
# In _build_games_data:
if p.get('has_line'):
    # Build feature data dict
    player_feature_data = {
        'opponent_def_rating': p.get('opponent_def_rating'),
        'opponent_pace': p.get('opponent_pace'),
        'matchup_quality_pct': p.get('matchup_quality_pct'),
    }

    # Build directional factors
    factors = self._build_prediction_factors(
        player_data=player_data,
        feature_data=player_feature_data,
        last_10_record=last_10.get('record')
    )

    player_data['prediction'] = {
        'predicted': safe_float(p.get('predicted_points')),
        'confidence': safe_float(p.get('confidence_score')),  # Keep 0-100
        'recommendation': p.get('recommendation'),
        'factors': factors
    }
```

**Validation (Opus recommended tests):**
```bash
# 1. No contradictions
jq '.games[].players[] |
    select(.prediction.recommendation == "OVER") |
    select(.prediction.factors | any(contains("Elite") or contains("slump") or contains("fatigue")))' \
    all-players.json
# Should return 0 results

# 2. Max 4 factors
jq '[.games[].players[] | select(.prediction.factors) | .prediction.factors | length] | max' all-players.json
# Should be <= 4

# 3. All lined players have factors field
jq '[.games[].players[] | select(.has_line) | select(.prediction.factors == null)] | length' all-players.json
# Should be 0

# 4. Spot check OVER picks
jq '.games[].players[] | select(.prediction.recommendation == "OVER" and (.prediction.factors | length > 0)) | {name, factors: .prediction.factors}' all-players.json | head -20
```

**Commit:**
```bash
git add data_processors/publishing/tonight_all_players_exporter.py
git commit -m "feat: Add prediction.factors with directional logic

- Add feature store JOIN for matchup data
- Implement directional factor generation (supports recommendation)
- Priority order: Edge > Matchup > Trend > Fatigue > Form
- Edge always included if >= 3 (inherently directional)
- Other factors only if they support the rec
- Max 4 factors per player

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Sprint 3: Enhancements (1 Agent, 1.5 hours)

### Agent D: Date Navigation + Calendar

**Files:**
- `data_processors/publishing/tonight_all_players_exporter.py` (modify export method)
- `data_processors/publishing/calendar_exporter.py` (NEW)
- `backfill_jobs/publishing/daily_export.py` (add calendar type)

**Tasks:**
1. Export both `tonight/all-players.json` AND `tonight/YYYY-MM-DD.json`
2. Create `CalendarExporter` class
3. Add calendar to export types

**Implementation:** See `05-CORRECTED-IMPLEMENTATION-PLAN.md` lines 800-950

**Validation:**
```bash
# Both files exist
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | jq '.game_date'
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/2026-02-11.json | jq '.game_date'

# Calendar counts
curl https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json | jq 'keys | length'
# Should be 30+
```

**Commit:**
```bash
git add .
git commit -m "feat: Add date navigation and calendar widget

- Export date-specific tonight files for historical browsing
- Add CalendarExporter for game counts per date
- Add calendar to export types

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Final Steps: Merge to Main

```bash
# Verify all changes on feature branch
git log --oneline

# Should see 5-6 commits:
# - Sprint 1: Quick wins
# - Sprint 2A: last_10_lines
# - Sprint 2C: best_bets
# - Sprint 2B: prediction.factors
# - Sprint 3: date navigation + calendar

# Push feature branch
git push origin feature/phase6-api-gaps

# Merge to main (triggers auto-deploy)
git checkout main
git merge feature/phase6-api-gaps
git push origin main

# Monitor Cloud Build
gcloud builds list --region=us-west2 --limit=1

# Wait for deployment (~10 min)
# Trigger Phase 6 export
# Validate all endpoints
```

---

## Post-Deployment Validation

### Comprehensive Testing
```bash
# 1. Quick wins (Sprint 1)
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[0].players[0] | {days_rest, minutes_avg, recent_form, game_time: .game_time}'

# 2. last_10_lines (Sprint 2A)
jq '.games[0].players[] | select(.has_line) | {
  name,
  points: (.last_10_points | length),
  lines: (.last_10_lines | length),
  results: (.last_10_results | length)
}' all-players.json | head -5
# All arrays should match in length

# 3. prediction.factors (Sprint 2B)
jq '.games[0].players[] | select(.has_line and (.prediction.factors | length > 0)) | {
  name,
  rec: .prediction.recommendation,
  factors: .prediction.factors
}' all-players.json | head -20
# No contradictions (OVER + "Elite defense" = bug)

# 4. best bets (Sprint 2C)
curl https://storage.googleapis.com/nba-props-platform-api/v1/best-bets/latest.json | jq '.total_picks'
# Should be >0 (was 0)

# 5. Date navigation (Sprint 3)
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/2026-02-11.json | jq '.game_date'

# 6. Calendar (Sprint 3)
curl https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json | jq '. | length'
```

---

## Success Criteria

**Data Quality:**
- [ ] 0 fields missing for lined players
- [ ] 0 invalid odds >10000
- [ ] 0 contradictory factors
- [ ] Arrays match in length (last_10_*)

**Feature Completeness:**
- [ ] 100% lined players have factors field
- [ ] Best bets returns picks for current date
- [ ] Accurate O/U with last_10_lines

**Endpoints:**
- [ ] 10/10 endpoints functional
- [ ] Historical date browsing works
- [ ] Calendar widget data available

---

## Timeline

**Setup:** 5 min (create feature branch)
**Sprint 1:** 45 min (me, direct)
**Sprint 2:** 4-5 hours wall time (agents A+C parallel, then B)
**Sprint 3:** 1.5 hours (agent D)
**Merge & Deploy:** 15 min

**Total Wall Time:** ~6.5 hours

---

**Status:** ✅ Ready to Execute
**Next:** Begin Sprint 1 implementation
