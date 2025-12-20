# Frontend API Backend - Project Overview

**Created:** December 17, 2025
**Updated:** December 19, 2025
**Status:** Complete - API Endpoints Done, Prediction Pipeline Deployed
**Priority:** Critical

---

## CURRENT STATUS (December 19, 2025)

### Data Pipeline: COMPLETE
- 2025-26 season data fully backfilled (Oct 21 - Dec 16)
- 227,561 play-by-play events
- 99.7% zone data coverage (616/618 games)
- TDZA: 646 records (30 teams, 27 dates)

### Prediction Pipeline: DEPLOYED (Session 148)
- Phase 4 backfill complete (ml_feature_store through 2025-12-13)
- prediction-coordinator deployed and healthy
- phase4-to-phase5-orchestrator deployed
- Predictions tested successfully with 2025-26 data
- **Gap:** Phase 5B grading needs scheduler job (prediction_accuracy stale)

### Frontend API Endpoints: COMPLETE

| Phase | Component | Status | Priority |
|-------|-----------|--------|----------|
| **Phase 1** | Results Page Fields | **COMPLETE** | High |
| **Phase 2** | Trends Page Endpoints | **COMPLETE** | High |
| **Phase 3** | Player Modal Endpoints | **COMPLETE** | Medium |
| **Shared** | Archetype/Shot Profile Classification | Included in Phase 1-3 | High |

### Phase 1 Completed (December 19, 2025)

All Results page backend fields implemented in `ResultsExporter`:
- `confidence_tier`: high/medium/low (thresholds: 70%, 55%)
- `player_tier`: elite/starter/role_player (thresholds: 25 PPG, 15 PPG)
- Context fields: `is_home`, `is_back_to_back`, `days_rest`
- Breakdowns: `by_player_tier`, `by_confidence`, `by_recommendation`, `by_context`
- 17 unit tests added and passing

### Phase 2 Completed (December 19, 2025)

Trends page exporters enhanced to match frontend requirements:

**WhosHotColdExporter** (`whos_hot_cold_exporter.py`):
- Renamed fields: `team` → `team_abbr`, `player_name` → `player_full_name`
- Added `position` field
- Heat score scaled 0-10 (was 0-1)
- `streak_type` → `streak_direction` (lowercase: "over"/"under")
- Tonight object: `{opponent, game_time, home}`
- `hit_rate_games` added

**BounceBackExporter** (`bounce_back_exporter.py`):
- Renamed fields: `team` → `team_abbr`, `player_name` → `player_full_name`
- `last_game.points` → `last_game.result`, added `last_game.margin`
- Tonight object: `{opponent, game_time, home}`

**SystemPerformanceExporter** - Already aligned with frontend (no changes needed)

- All 41 unit tests passing

### Phase 3 Completed (December 19, 2025)

Player Modal endpoints implemented:

**PlayerGameReportExporter** (`player_game_report_exporter.py`):
- `GET /v1/player/{player_lookup}/game-report/{date}`
- Player profile with shot profile classification (interior/perimeter/mid_range/balanced)
- Opponent context with defense ratings and zone analysis
- Moving averages (L5, L10, L20, season)
- Prediction angles (supporting/against factors)
- Recent games, head-to-head history, result

**PlayerSeasonExporter** (`player_season_exporter.py`):
- `GET /v1/player/{player_lookup}/season/{season}`
- Season averages (PPG, RPG, APG, shooting splits)
- Current form with heat score (0-10) and temperature
- Key patterns (rest sensitive, home performer, etc.)
- Prop hit rates from prediction accuracy
- Full game log, splits (home/away, rested/B2B), monthly breakdown
- Player tier classification (elite/starter/role_player)

---

## Phase 1: Results Page Backend Fields

From Session 142 handoff - enhance `ResultsExporter` with:

### 1.1 `confidence_tier` Field (Easiest)
**Type:** enum - `"high"`, `"medium"`, `"low"`

```python
def get_confidence_tier(confidence_score):
    if confidence_score >= 0.70:
        return "high"
    elif confidence_score >= 0.55:
        return "medium"
    else:
        return "low"
```

**Source:** `prediction_accuracy.confidence_score`

### 1.2 `player_tier` Field
**Type:** enum - `"elite"`, `"starter"`, `"role_player"`

**Logic:** Based on season PPG ranking
- Elite: Top 30 PPG (~25+ PPG)
- Starter: Mid-tier PPG (~15-25 PPG)
- Role player: Lower PPG (<15 PPG)

**Source:** `ml_feature_store_v2.season_ppg` or `player_game_summary` aggregated

### 1.3 Context Fields
| Field | Type | Source |
|-------|------|--------|
| `is_home` | bool | `nbac_schedule` or parse `game_id` |
| `is_back_to_back` | bool | Check if team played previous day |
| `days_rest` | int | Days since team's last game |

### 1.4 Pre-computed Breakdowns
```typescript
interface ResultBreakdowns {
  by_player_tier: { elite, starter, role_player };
  by_confidence: { high, medium, low };
  by_recommendation: { over, under };
  by_context: { home, away, back_to_back, rested };
}

interface BreakdownStats {
  total: number;
  wins: number;
  losses: number;
  pushes: number;
  win_rate: number;
  avg_error: number;
}
```

**Implementation file:** `data_processors/publishing/results_exporter.py`

---

## Phase 2: Trends Page Endpoints

New endpoints needed for props-web Trends page.

### 2.1 Tonight's Trend Plays
**Endpoint:** `GET /api/trends/tonight-plays`

Players playing tonight with qualifying trends:
- 3+ game OVER/UNDER streak vs line
- 15%+ scoring change (L5 vs L15)
- On B2B (tired) or 3+ days rest (fresh)

### 2.2 Hot/Cold Streaks
**Endpoint:** `GET /api/trends/streaks?direction={hot|cold}&method={vs_line|vs_average}`

```typescript
interface StreakEntry {
  player_lookup: string;
  player_full_name: string;
  team_abbr: string;
  streak_length: number;
  avg_margin: number;
  intensity_score: number;  // streak_length x |avg_margin|
  intensity_level: "scorching" | "hot" | "warm" | "freezing" | "cold" | "cool";
  games: GameDetail[];
  tonight: TonightGame | null;
}
```

### 2.3 Bounce-Back Watch
**Endpoint:** `GET /api/trends/bounce-back`

Players with:
- Season hit rate >= 55% (normally reliable)
- 2+ consecutive misses OR single miss >= 20% of line

### 2.4 System Performance
**Endpoint:** `GET /api/trends/system-performance`

Track record across time windows (L7, L30, season).

---

## Phase 3: Player Modal Endpoints

### 3.1 Game Report
**Endpoint:** `GET /v1/player/{player_lookup}/game-report/{date}`

Per-game deep dive with:
- Player profile (archetype, shot profile)
- Opponent context (pace, defense rank, defense by zone)
- Prop lines (current, opening, movement)
- Moving averages (L5, L10, L20, season)
- Line analysis (inflation score, bounce-back score)
- Prediction angles (supporting and against)
- Recent games, head-to-head, result

### 3.2 Season Data
**Endpoint:** `GET /v1/player/{player_lookup}/season/{season}`

Season aggregates with:
- Player profile
- Averages (PPG, RPG, APG, shooting splits)
- Current form (heat score, temperature, streak)
- Key patterns (rest sensitive, home performer, etc.)
- Prop hit rates (points, rebounds, assists)
- Game log, splits, monthly chart data

---

## Shared Data Infrastructure

### Player Archetypes (Build Once, Use Everywhere)

| Archetype | Criteria | Rest Impact |
|-----------|----------|-------------|
| `veteran_star` | 10+ years, 20+ PPG, 25%+ usage | High (+4-5 PPG) |
| `prime_star` | 5-9 years, 22+ PPG, 28%+ usage | Medium (+2-3 PPG) |
| `young_star` | <5 years, 18+ PPG, 22%+ usage | Low (+0-1 PPG) |
| `ironman` | <1.5 PPG variance by rest | None |
| `role_player` | Everyone else | Varies |

**Data source:** `player_game_summary` + `nba_players_registry`

### Shot Profiles

| Profile | Criteria |
|---------|----------|
| `interior` | 50%+ shots in paint |
| `perimeter` | 50%+ shots from 3 |
| `mid_range` | 30%+ mid-range shots |
| `balanced` | No dominant zone |

**Data source:** `nba_precompute.player_shot_zone_analysis`

### Heat Score Algorithm

```
HeatScore = (0.50 x HitRateScore) + (0.25 x StreakScore) + (0.25 x MarginScore)

Temperature thresholds:
- 8.0+: hot
- 6.5-7.9: warm
- 4.5-6.4: neutral
- 3.0-4.4: cool
- <3.0: cold
```

---

## Data Sources Available

| Table | Purpose | Status |
|-------|---------|--------|
| `nba_analytics.player_game_summary` | Player stats per game | Ready |
| `nba_precompute.player_shot_zone_analysis` | Shot profiles | Ready (10,513 records) |
| `nba_precompute.team_defense_zone_analysis` | Defense by zone | Ready (646 records) |
| `nba_analytics.team_offense_game_summary` | Pace, ratings | Ready |
| `ml_feature_store_v2` | Season averages | Ready |
| `bettingpros_player_points_props` | Prop lines | Ready |
| `nba_raw.nbac_schedule` | Schedule/B2B info | Ready |
| `nba_predictions.prediction_accuracy` | Graded predictions | Ready (315k) |

---

## Key Files

### Results API (Phase 1)
- `data_processors/publishing/results_exporter.py` - Enhance with new fields

### Trends API (Phase 2)
- TBD - New exporter or API service

### Player Modal API (Phase 3)
- TBD - New exporter or API service

### Shared Infrastructure
- `data_processors/classification/player_archetype.py` - NEW
- `data_processors/classification/shot_profile.py` - NEW
- `data_processors/classification/heat_score.py` - NEW

---

## Implementation Order

1. **Phase 1A:** Add `confidence_tier` to ResultsExporter (simple bucketing)
2. **Phase 1B:** Add `player_tier` (query ML feature store for PPG)
3. **Phase 1C:** Add context fields (join with schedule)
4. **Phase 1D:** Pre-compute breakdowns
5. **Shared:** Build archetype/shot profile classification
6. **Phase 2:** Trends page endpoints
7. **Phase 3:** Player Modal endpoints

---

## Related Documentation

### This Repo (nba-stats-scraper)
- Session handoff: `docs/09-handoff/2025-12-19-SESSION142-BIGDATABALL-BACKFILL-COMPLETE.md`
- Phase 5B testing: `docs/09-handoff/2025-12-18-PHASE5B-TESTING-AND-VALIDATION.md`

### Props-Web Repo
- Player Modal spec: `props-web/docs/06-projects/current/player-modal/data-requirements.md`
- Trends Page spec: `props-web/docs/06-projects/current/trends-page/data-requirements.md`
- Results Page spec: `props-web/docs/06-projects/current/results-page/data-requirements.md`

---

## Success Criteria

- [x] Results page shows `player_tier` and `confidence_tier` ✅ (December 19)
- [x] Results page shows context (home/away, B2B, rest days) ✅ (December 19)
- [x] Results page shows breakdown stats ✅ (December 19)
- [x] Trends page hot/cold lists working ✅ (December 19)
- [x] Trends page bounce-back watch working ✅ (December 19)
- [x] Player Modal game report endpoint ✅ (December 19)
- [x] Player Modal season endpoint ✅ (December 19)

## All Phases Complete

All backend exporters for props-web frontend are now implemented.
