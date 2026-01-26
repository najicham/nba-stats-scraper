# Refactor Session R5: Analytics Processors

**Scope:** 3 files, ~6,983 lines + 1 large function
**Risk Level:** Medium (individual processors, not base classes)
**Estimated Effort:** 2-3 hours
**Model:** Sonnet recommended
**Dependency:** Complete R4 (Base Classes) first

---

## Overview

Refactor the three largest analytics processors by extracting calculation logic into domain-specific modules.

---

## Files to Refactor

### 1. upcoming_player_game_context_processor.py (2,641 lines)

**Location:** `data_processors/analytics/upcoming_player_game_context/`

**Current State:** Large processor handling player stats, team context, travel calculations, betting data, fatigue metrics.

**Note:** This processor already has some extracted modules:
- `player_stats.py` - fatigue metrics, performance metrics
- `team_context.py` - opponent metrics, variance
- `travel_context.py` - travel distance, timezone
- `betting_data.py` - prop lines, game lines

**Target Structure:**
```
data_processors/analytics/upcoming_player_game_context/
├── upcoming_player_game_context_processor.py  # Core processor (~500 lines)
├── player_stats.py              # Already exists
├── team_context.py              # Already exists
├── travel_context.py            # Already exists
├── betting_data.py              # Already exists
├── calculators/
│   ├── __init__.py
│   ├── historical_stats.py      # Historical performance aggregation
│   ├── quality_flags.py         # Data completeness flags
│   └── context_builder.py       # Final context assembly
```

**What to Extract:**
1. Historical performance aggregation (last 5, 10, 30 days)
2. Quality flag calculations
3. Context assembly/building logic

### 2. upcoming_team_game_context_processor.py (2,288 lines)

**Location:** `data_processors/analytics/upcoming_team_game_context/`

**Current State:** Handles team-level context with dependency validation, fatigue, betting, personnel, performance, travel.

**Target Structure:**
```
data_processors/analytics/upcoming_team_game_context/
├── upcoming_team_game_context_processor.py  # Core processor (~500 lines)
├── calculators/
│   ├── __init__.py
│   ├── dependency_validator.py  # Phase 2 dependency checking
│   ├── fatigue_calculator.py    # Team fatigue metrics
│   ├── betting_context.py       # Team betting context
│   ├── personnel_tracker.py     # Roster/injury tracking
│   ├── performance_analyzer.py  # Momentum, recent performance
│   ├── travel_calculator.py     # Team travel metrics
│   └── source_fallback.py       # Dual-source fallback logic
```

**What to Extract:**
1. Dependency validation logic
2. Each of the 27 hash field calculations
3. Source fallback (nbac_schedule → espn_scoreboard)

### 3. player_game_summary_processor.py (2,054 lines)

**Location:** `data_processors/analytics/player_game_summary/`

**Current State:** Multi-source fallback processor combining 6 Phase 2 tables.

**Target Structure:**
```
data_processors/analytics/player_game_summary/
├── player_game_summary_processor.py  # Core processor (~500 lines)
├── sources/
│   ├── __init__.py
│   ├── stats_aggregator.py      # NBA.com + BDL fallback
│   ├── shot_zone_analyzer.py    # BigDataBall + NBAC PBP
│   ├── prop_calculator.py       # OddsAPI + BettingPros
│   └── player_registry.py       # Universal ID integration
├── calculators/
│   ├── __init__.py
│   ├── quality_scorer.py        # Source coverage scoring
│   └── change_detector.py       # Meaningful change detection
```

**What to Extract:**
1. Stats aggregation with NBA.com → BDL fallback
2. Shot zone analysis
3. Prop betting result calculation
4. Quality scoring logic
5. Change detection logic

### 4. _build_backfill_mode_query() (453 lines)

**Location:** `data_processors/analytics/upcoming_player_game_context/async_upcoming_player_game_context_processor.py`

**Current State:** Giant SQL query builder with multiple CTEs.

**Target Structure:**
```python
# queries/backfill_query_builder.py
class BackfillQueryBuilder:
    def build(self, date_str: str, sport: str) -> str:
        return f"""
        {self._schedule_cte()}
        {self._players_with_games_cte()}
        {self._props_cte()}
        {self._final_select()}
        """

    def _schedule_cte(self) -> str:
        """Build schedule data CTE."""

    def _players_with_games_cte(self) -> str:
        """Build players with games CTE."""

    def _props_cte(self) -> str:
        """Build props combination CTE."""

    def _final_select(self) -> str:
        """Build final aggregation select."""
```

---

## Key Patterns

### Calculator Module Pattern
```python
# calculators/fatigue_calculator.py
class FatigueCalculator:
    """Calculate team fatigue metrics."""

    def __init__(self, bigquery_client):
        self.client = bigquery_client

    def calculate(self, team_id: str, game_date: str) -> dict:
        """Calculate fatigue metrics for a team."""
        return {
            'days_rest': self._calculate_days_rest(team_id, game_date),
            'games_in_last_7': self._count_recent_games(team_id, game_date, 7),
            'back_to_back': self._is_back_to_back(team_id, game_date),
        }

    def _calculate_days_rest(self, team_id, game_date):
        # Implementation
```

### Source Module Pattern
```python
# sources/stats_aggregator.py
class StatsAggregator:
    """Aggregate player stats from multiple sources with fallback."""

    PRIMARY_SOURCE = 'nbac_gamebook_player_stats'
    FALLBACK_SOURCE = 'bdl_player_boxscores'

    def aggregate(self, player_id: str, game_id: str) -> dict:
        """Get stats with automatic fallback."""
        stats = self._try_primary(player_id, game_id)
        if not stats:
            stats = self._try_fallback(player_id, game_id)
        return stats
```

---

## Testing Strategy

```bash
# 1. Run processor-specific tests
python -m pytest tests/unit/data_processors/analytics/upcoming_player_game_context/ -v
python -m pytest tests/unit/data_processors/analytics/upcoming_team_game_context/ -v
python -m pytest tests/unit/data_processors/analytics/player_game_summary/ -v

# 2. Verify processor initialization
python -c "
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
print('UpcomingPlayerGameContextProcessor OK')
"

# 3. Check existing extracted modules still work
python -c "
from data_processors.analytics.upcoming_player_game_context.player_stats import calculate_fatigue_metrics
print('player_stats OK')
"
```

---

## Success Criteria

- [ ] Each main processor file reduced to <600 lines
- [ ] Each calculator/source module <300 lines
- [ ] _build_backfill_mode_query() reduced to <50 lines
- [ ] All processor tests pass
- [ ] Existing extracted modules continue to work

---

## Files to Create

| File | Purpose | Estimated Lines |
|------|---------|-----------------|
| **Upcoming Player Game Context** | | |
| `calculators/__init__.py` | Calculator exports | ~10 |
| `calculators/historical_stats.py` | Historical aggregation | ~200 |
| `calculators/quality_flags.py` | Quality calculations | ~100 |
| `calculators/context_builder.py` | Context assembly | ~150 |
| **Upcoming Team Game Context** | | |
| `calculators/__init__.py` | Calculator exports | ~10 |
| `calculators/dependency_validator.py` | Dependency checking | ~150 |
| `calculators/fatigue_calculator.py` | Fatigue metrics | ~150 |
| `calculators/betting_context.py` | Betting context | ~150 |
| `calculators/personnel_tracker.py` | Personnel tracking | ~150 |
| `calculators/performance_analyzer.py` | Performance analysis | ~150 |
| `calculators/travel_calculator.py` | Travel metrics | ~100 |
| `calculators/source_fallback.py` | Source fallback | ~100 |
| **Player Game Summary** | | |
| `sources/__init__.py` | Source exports | ~10 |
| `sources/stats_aggregator.py` | Stats with fallback | ~200 |
| `sources/shot_zone_analyzer.py` | Shot zone analysis | ~150 |
| `sources/prop_calculator.py` | Prop calculations | ~150 |
| `sources/player_registry.py` | Registry integration | ~100 |
| `calculators/__init__.py` | Calculator exports | ~10 |
| `calculators/quality_scorer.py` | Quality scoring | ~100 |
| `calculators/change_detector.py` | Change detection | ~100 |
| **Async Processor** | | |
| `queries/backfill_query_builder.py` | Query builder | ~200 |

---

## Notes

- These processors use `SmartSkipMixin`, `EarlyExitMixin`, `CircuitBreakerMixin` - don't break those
- Some calculation logic is already in extracted files - build on that pattern
- The worker functions (`_process_single_player_worker`) must stay module-level for multiprocessing
- Quality flags have specific meanings for downstream ML - preserve logic exactly
