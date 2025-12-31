# Session 125: Website UI Design & Phase 6 Enhancement Planning

**Date:** 2025-12-11
**Focus:** NBA Props Website Phase 1 UI specification and backend data planning
**Status:** Design complete, ready for implementation

---

## Executive Summary

This session established the complete UI specification and backend data architecture for Phase 1 of the NBA Props website. We:

1. Brainstormed UI design in a separate Opus web chat
2. Investigated data availability against the UI requirements
3. Made key technical decisions (loading strategy, fatigue calculation, search, etc.)
4. Consolidated everything into a master specification document
5. Addressed review feedback and finalized the spec

**The design phase is complete. Next step is implementing the new Phase 6 exporters.**

---

## Documents Created

| Document | Location | Purpose |
|----------|----------|---------|
| **Master Specification** | `docs/08-projects/current/website-ui/MASTER-SPEC.md` | Single source of truth - start here |
| UI Spec v2 | `docs/08-projects/current/website-ui/UI-SPEC-V2.md` | Original UI spec from brainstorm |
| Data Investigation | `docs/08-projects/current/website-ui/DATA-INVESTIGATION-RESULTS.md` | Data availability analysis |
| Brainstorm Prompt | `docs/08-projects/current/website-ui/BRAINSTORM-PROMPT.md` | Prompt used for web chat |

**Read MASTER-SPEC.md first** - it consolidates everything.

---

## Product Vision

### Core Principle
**Research-first, prediction-supplemented.** The organized, contextualized data is the product. The prediction is one data point that supports the user's own decision-making.

### Target Users
1. **Sports Bettors** - Research tonight's games, form opinion, consider our prediction, make bet
2. **Casual Fans** - Browse player stats, check performance, general NBA interest

### V1 Scope
- Tonight's Picks (players with betting lines + predictions)
- All Players (everyone playing tonight)
- Player detail panel with Tonight/Profile tabs
- Results page
- Search functionality
- Mobile-responsive

### Out of Scope (V1.5+)
- Live game scores (final scores only in V1)
- User accounts / saved players
- Streaks page
- Player comparison tool

---

## UI Architecture Summary

### Site Structure
```
NBA Props Platform
├── Tonight (Default)
│   ├── Tab: Tonight's Picks (players with lines)
│   │   ├── Best Bets section (top 5-10)
│   │   └── Player grid (filterable, sortable)
│   └── Tab: All Players (everyone tonight)
│       └── Player grid by team
├── Results (yesterday + rolling accuracy)
├── Search (find any player)
└── Player Profile (standalone page for non-playing players)
```

### Key UI Patterns
- **Best Bets:** Horizontal scrollable cards, ranked by composite score
- **Player Grid:** Cards with line, prediction, fatigue indicator, last 10 mini-grid
- **Detail Panel:** Slides from right (desktop) / bottom sheet (mobile)
- **Two Tabs in Panel:** "Tonight" (game-specific) and "Profile" (full history)
- **Fatigue Indicator:** 🟢 Fresh / 🟡 Normal / 🔴 Tired

---

## Data Loading Architecture

### Three-Chunk Strategy

```
INITIAL PAGE LOAD (~155 KB)
├── /v1/tonight/all-players.json (~150 KB) - All players in tonight's games
└── /v1/best-bets/today.json (~5 KB) - Top ranked picks

USER CLICKS PLAYER (~3-5 KB)
└── /v1/tonight/player/{lookup}.json - Tonight tab data

USER CLICKS PROFILE TAB (~30-50 KB)
└── /v1/players/{lookup}.json - Full season profile
```

### Key Decision: Load All Players Upfront
- ~150 KB is trivial for modern connections
- Enables instant search/filter
- Simpler frontend architecture
- Frontend flattens data for Tonight's Picks tab (filter to has_line: true)

---

## API Endpoints

### Existing Endpoints (Ready to Use)
| Endpoint | Purpose | Status |
|----------|---------|--------|
| `/v1/best-bets/today.json` | Top ranked picks | ✅ Ready |
| `/v1/players/index.json` | Player directory (519 players) | ✅ Ready |
| `/v1/results/{date}.json` | Daily results | ✅ Ready |
| `/v1/systems/performance.json` | System accuracy | ✅ Ready |

### New Endpoints to Build
| Endpoint | Purpose | Effort |
|----------|---------|--------|
| `/v1/tonight/all-players.json` | Grid data for all players tonight | 3-4 hrs |
| `/v1/tonight/player/{lookup}.json` | Tonight tab detail data | 2-3 hrs |

### Endpoints to Enhance
| Endpoint | Changes | Effort |
|----------|---------|--------|
| `/v1/players/{lookup}.json` | Expand to 50 games, add defense tier splits, add streak | 2 hrs |

---

## Key Technical Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| All players upfront vs game selection | **Load all upfront** | ~150 KB trivial, enables instant search |
| Fatigue calculation location | **Backend** | Already computed in Phase 4, just expose it |
| Tonight's Factors filtering | **Frontend** | Send all splits, frontend filters by context |
| Explanation text | **Frontend templates** | Easier to maintain, tweak copy without deploy |
| Game log depth | **50 games** | ~2 months, good for trends, reasonable size |
| Live scores | **Defer to V1.5** | Final scores only for V1 |
| Search implementation | **Client-side** | Filter loaded data, no new endpoint needed |

---

## Fatigue Score System

### Already Exists
- **Table:** `nba_precompute.player_composite_factors`
- **Field:** `fatigue_score` (0-100, where 100 = fully rested)
- **Context:** `fatigue_context_json` with breakdown

### Calculation Formula (in player_composite_factors_processor.py)
```python
score = 100  # Start at baseline
if back_to_back: score -= 15
elif days_rest >= 3: score += 5
if games_last_7 >= 4: score -= 10
if minutes_last_7 > 240: score -= 10
if avg_mpg_last_7 > 35: score -= 8
if back_to_backs_last_14 >= 2: score -= 12
elif back_to_backs_last_14 == 1: score -= 5
if age >= 35: score -= 10
elif age >= 30: score -= 5
```

### Mapping to UI Levels
```javascript
if (fatigue_score >= 95) return "fresh";    // 🟢
if (fatigue_score >= 75) return "normal";   // 🟡
return "tired";                              // 🔴
```

### Action Needed
Add `fatigue_score` and `fatigue_level` to Phase 6 JSON exports (currently not exposed).

---

## Best Bets Ranking Formula

The existing `/v1/best-bets/today.json` uses this formula (in best_bets_exporter.py):

```python
composite_score = confidence_score
    × min(1.5, 1.0 + edge/10.0)  # edge_factor
    × coalesce(player_historical_accuracy, 0.85)  # historical_accuracy
```

This is already implemented and working correctly.

---

## Game State Handling (V1)

### V1 Scope: Scheduled → Final Only
```
SCHEDULED (game_status = 1) → FINAL (game_status = 3)
```
No live scores in V1.

### Data Sources
- Game status: `nba_raw.nbac_schedule.game_status`
- Final scores: `nba_analytics.player_game_summary.points` (1-6 hrs post-game)

### V1.5 Addition
- Real-time game scraper
- `game_status = 2` (in progress)
- Current points during game

---

## Search Implementation

### Strategy: Client-Side Filtering
No new backend endpoints needed.

### Flow
1. Players with games today → Filter `/v1/tonight/all-players.json`
2. All other players → Filter `/v1/players/index.json` (already exists, 519 players)
3. On selection → Open detail panel or Profile page

### UX Details
- Min 2 characters before showing results
- 150ms debounce
- Show top 10 matches
- Sort: players with games today first

---

## Data Availability Summary

### Fully Supported (No Work Needed)
- Player cards with lines
- Injury status + reason
- Days rest / B2B flag
- Home/Away
- Last 10 results
- Season/Last 5/10 averages
- Line movement
- System agreement
- Defensive ratings
- Track record per player
- Best bets ranking
- Results/accuracy

### Exists But Not Exposed (Add to Phase 6)
- Fatigue score (0-100)
- Fatigue context JSON
- Defense tier splits
- Current streak

### Not Available (V1.5)
- Live game scores
- Pre-game lineup confirmations

---

## Implementation Plan

### Phase 6 Backend Work

| Task | Effort | Priority |
|------|--------|----------|
| Create `/v1/tonight/all-players.json` exporter | 3-4 hrs | High |
| Create `/v1/tonight/player/{lookup}.json` exporter | 2-3 hrs | High |
| Add fatigue_level to predictions output | 1 hr | High |
| Enhance `/v1/players/{lookup}.json` (50 games, splits) | 2 hrs | High |
| Add defense tier splits computation | 1 hr | Medium |
| Add current streak computation | 30 min | Medium |

**Total backend:** ~10-12 hours

### Implementation Order
1. `all-players.json` - Enables initial page render
2. Enhance player profiles - Enables Profile tab
3. `tonight/player/{lookup}.json` - Enables Tonight tab
4. Add fatigue to existing - Polish

---

## JSON Schema Examples

### /v1/tonight/all-players.json (NEW)
```json
{
  "game_date": "2024-12-11",
  "generated_at": "2024-12-11T07:00:00Z",
  "total_players": 156,
  "total_with_lines": 98,
  "games": [
    {
      "game_id": "20241211_LAL_DEN",
      "home_team": "DEN",
      "away_team": "LAL",
      "game_time": "19:30",
      "game_status": "scheduled",
      "players": [
        {
          "player_lookup": "lebronjames",
          "player_full_name": "LeBron James",
          "team_abbr": "LAL",
          "has_line": true,
          "current_points_line": 25.5,
          "opening_line": 24.0,
          "predicted_points": 22.4,
          "confidence_score": 74,
          "recommendation": "UNDER",
          "fatigue_level": "tired",
          "fatigue_score": 72,
          "injury_status": "available",
          "injury_reason": null,
          "season_ppg": 24.8,
          "last_5_ppg": 20.4,
          "last_10_results": ["O","O","U","O","U","U","O","U","U","O"],
          "last_10_record": "4-6"
        }
      ]
    }
  ]
}
```

### /v1/tonight/player/{lookup}.json (NEW)
See MASTER-SPEC.md §7.3 for full schema - includes:
- game_context (opponent, line, movement, rest, injury)
- quick_numbers (season/last10/last5 avgs, minutes trend)
- fatigue (score, level, factors, context)
- current_streak
- tonights_factors (only applicable splits)
- recent_form (last 10 games with details)
- prediction (predicted pts, confidence, recommendation, system agreement)

### /v1/players/{lookup}.json (ENHANCED)
See MASTER-SPEC.md §7.4 for full schema - includes:
- season_overview
- game_log (50 games with full box scores)
- splits (rest, location, defense_tier, opponents)
- our_track_record
- next_game

---

## File Locations

### Existing Phase 6 Code
```
data_processors/publishing/
├── __init__.py
├── base_exporter.py          # Base class with GCS/BQ helpers
├── best_bets_exporter.py     # /v1/best-bets/ (working)
├── player_profile_exporter.py # /v1/players/ (enhance this)
├── predictions_exporter.py   # /v1/predictions/ (working)
├── results_exporter.py       # /v1/results/ (working)
└── system_performance_exporter.py # /v1/systems/ (working)

backfill_jobs/publishing/
└── daily_export.py           # CLI orchestrator
```

### New Exporters to Create
```
data_processors/publishing/
├── tonight_all_players_exporter.py  # NEW
└── tonight_player_exporter.py       # NEW
```

### Key Data Sources
```
BigQuery Tables:
- nba_predictions.player_prop_predictions  # Predictions
- nba_analytics.player_game_summary        # Historical stats
- nba_analytics.upcoming_player_game_context # Game context
- nba_precompute.player_composite_factors  # Fatigue score
- nba_raw.nbac_injury_report              # Injury status
- nba_raw.nbac_schedule                   # Game schedule
- nba_analytics.team_defense_game_summary # Defense ratings
- nba_predictions.prediction_accuracy     # Track record
```

---

## GCS Storage Structure

```
gs://nba-props-platform-api/v1/
├── tonight/                    # NEW
│   ├── all-players.json       # NEW - all players tonight
│   └── player/                # NEW
│       ├── lebronjames.json   # NEW - tonight detail
│       └── {lookup}.json
├── best-bets/
│   ├── {date}.json
│   └── latest.json
├── predictions/
│   └── today.json
├── results/
│   ├── {date}.json
│   └── latest.json
├── systems/
│   └── performance.json
└── players/
    ├── index.json             # Already exists (519 players)
    └── {lookup}.json          # Enhance with more data
```

---

## Questions Resolved

| Question | Answer |
|----------|--------|
| Where do final scores come from? | `player_game_summary.points` via Phase 3, 1-6 hrs post-game |
| Search for non-playing players in V1? | Yes, use existing `/v1/players/index.json` |
| Best bets formula? | Already correct: confidence × edge_factor × historical_accuracy |
| Fatigue calculation exists? | Yes, in `player_composite_factors.fatigue_score` |
| Tonight's factors - backend or frontend? | Frontend filters, backend sends all splits |
| Load all players or require game selection? | Load all upfront (~150 KB) |

---

## Next Steps for Implementation

### Immediate (Backend)
1. Create `TonightAllPlayersExporter` class
   - Query predictions + context for today's date
   - Group by game
   - Include all players (with and without lines)
   - Include OUT players with injury info

2. Create `TonightPlayerExporter` class
   - Query single player's game context
   - Compute applicable splits (B2B, home/away, vs opponent, vs defense tier)
   - Include fatigue details
   - Include recent form with game details

3. Enhance `PlayerProfileExporter`
   - Expand game log to 50 games
   - Add defense tier splits
   - Add vs_line_pct to all splits
   - Add current streak

4. Add fatigue fields to existing exporters
   - Add `fatigue_score` and `fatigue_level` to predictions output

### After Backend (Frontend)
1. Build player grid component
2. Build detail panel with tab structure
3. Implement client-side search
4. Build Results page
5. Mobile responsive styling

---

## Testing Considerations

### For New Exporters
- Test with dates that have games vs no games
- Test players with lines vs without lines
- Test OUT players appear correctly
- Test fatigue calculation edge cases (rookies, traded players)
- Verify JSON schema matches spec

### Data Edge Cases
- Players with < 10 games (limited history)
- Rookies (no historical accuracy)
- Recently traded players
- Players with no prop line
- Games with unusual start times

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/08-projects/current/phase-6-publishing/DESIGN.md` | Phase 6 architecture |
| `docs/08-projects/current/phase-6-publishing/OPERATIONS.md` | Phase 6 operations |
| `schemas/bigquery/predictions/01_player_prop_predictions.sql` | Predictions schema |
| `schemas/bigquery/analytics/player_game_summary_tables.sql` | Game summary schema |
| `schemas/bigquery/precompute/player_composite_factors.sql` | Fatigue schema |

---

## Session Notes

- This was a design/planning session - no code was written
- UI was brainstormed in a separate Opus web chat, then brought into Claude Code
- Multiple rounds of feedback were incorporated into the master spec
- All data availability was verified against actual BigQuery schemas
- Fatigue calculation was confirmed to exist in Phase 4 (just not exposed in Phase 6)
- Player index already exists with 519 players (can be used for search)

---

## Handoff Checklist

- [x] Master specification complete (MASTER-SPEC.md v1.1)
- [x] Data availability verified
- [x] Technical decisions documented
- [x] JSON schemas defined
- [x] Implementation plan created
- [x] Existing code locations identified
- [x] GCS storage structure defined
- [ ] New exporters to be implemented
- [ ] Player profile exporter to be enhanced
- [ ] Frontend to be built

**Ready for implementation phase.**
