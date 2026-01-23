# Line Source Fallback Improvement

**Created:** 2026-01-23
**Status:** IMPLEMENTED
**Priority:** P2
**Implemented:** 2026-01-23

---

## Problem Statement

The current line source fallback system prioritizes **data source** over **sportsbook quality**:

```
Current: Odds API (DK→FD→BetMGM) → BettingPros (DK→FD→BetMGM)
```

This means if Odds API has FanDuel but not DraftKings, we use FanDuel from Odds API even though BettingPros might have DraftKings.

**Impact on Historical Data:**
- 2021-22: Odds API has 0 dates, but BettingPros has 213 dates with DK/FD lines
- 2022-23: Odds API has 27 dates, but BettingPros has 212 dates with DK/FD lines
- Current predictions use "VEGAS_BACKFILL" or "NO_VEGAS_DATA" instead of actual DK/FD lines

---

## Proposed Solution

Prioritize **sportsbook quality** across both sources:

```
Proposed: DraftKings (OddsAPI→BettingPros) → FanDuel (OddsAPI→BettingPros) → Other books
```

### New Fallback Order

1. Odds API DraftKings
2. BettingPros DraftKings (if Odds API DK not found)
3. Odds API FanDuel
4. BettingPros FanDuel (if Odds API FD not found)
5. Odds API BetMGM
6. BettingPros BetMGM
7. Continue for other books...
8. Estimated line (last resort)

---

## Implementation

### File: `predictions/coordinator/player_loader.py`

**Status:** IMPLEMENTED on 2026-01-23

**Changes Made:**
1. Rewrote `_query_actual_betting_line()` with sportsbook-priority fallback
2. Added `_query_odds_api_betting_line_for_book()` for specific sportsbook queries
3. Added `_query_bettingpros_betting_line_for_book()` for specific sportsbook queries
4. Enhanced `_track_line_source()` with detailed tracking by source and sportsbook
5. Enhanced `get_line_source_stats()` with summary stats and health alerts

**Previous Method:** `_query_actual_betting_line()` (lines 499-539)

```python
# CURRENT
def _query_actual_betting_line(self, player_lookup: str, game_date: date):
    # Try odds_api first (all books)
    result = self._query_odds_api_betting_line(player_lookup, game_date)
    if result is not None:
        return result
    # Fallback to bettingpros (all books)
    result = self._query_bettingpros_betting_line(player_lookup, game_date)
    return result
```

**Proposed Method:**

```python
# PROPOSED
def _query_actual_betting_line(self, player_lookup: str, game_date: date):
    """
    Query betting line with sportsbook-priority fallback.

    Prioritizes sportsbook quality over data source:
    DraftKings (OddsAPI→BettingPros) → FanDuel (OddsAPI→BettingPros) → etc.
    """
    preferred_sportsbooks = ['draftkings', 'fanduel']
    fallback_sportsbooks = ['betmgm', 'caesars', 'pointsbet']

    # Try preferred sportsbooks first, checking both sources
    for sportsbook in preferred_sportsbooks:
        # Try Odds API for this specific sportsbook
        result = self._query_odds_api_betting_line_for_book(
            player_lookup, game_date, sportsbook
        )
        if result is not None:
            self._track_line_source('odds_api', player_lookup)
            return result

        # Try BettingPros for this specific sportsbook
        result = self._query_bettingpros_betting_line_for_book(
            player_lookup, game_date, sportsbook
        )
        if result is not None:
            self._track_line_source('bettingpros_preferred', player_lookup)
            return result

    # Try fallback sportsbooks
    for sportsbook in fallback_sportsbooks:
        result = self._query_odds_api_betting_line_for_book(
            player_lookup, game_date, sportsbook
        )
        if result is not None:
            self._track_line_source('odds_api_fallback', player_lookup)
            return result

        result = self._query_bettingpros_betting_line_for_book(
            player_lookup, game_date, sportsbook
        )
        if result is not None:
            self._track_line_source('bettingpros_fallback', player_lookup)
            return result

    # No line found from any source
    self._track_line_source('no_line_data', player_lookup)
    return None
```

### New Helper Methods

```python
def _query_odds_api_betting_line_for_book(
    self, player_lookup: str, game_date: date, sportsbook: str
) -> Optional[Dict]:
    """Query Odds API for a specific sportsbook."""
    query = """
    SELECT points_line as line_value, bookmaker, minutes_before_tipoff
    FROM `{project}.nba_raw.odds_api_player_points_props`
    WHERE player_lookup = @player_lookup
      AND game_date = @game_date
      AND LOWER(bookmaker) = @sportsbook
    ORDER BY snapshot_timestamp DESC
    LIMIT 1
    """
    # ... implementation

def _query_bettingpros_betting_line_for_book(
    self, player_lookup: str, game_date: date, sportsbook: str
) -> Optional[Dict]:
    """Query BettingPros for a specific sportsbook."""
    query = """
    SELECT points_line as line_value, bookmaker, created_at
    FROM `{project}.nba_raw.bettingpros_player_points_props`
    WHERE player_lookup = @player_lookup
      AND game_date = @game_date
      AND LOWER(bookmaker) = @sportsbook
      AND bet_side = 'over'
      AND is_active = TRUE
    ORDER BY created_at DESC
    LIMIT 1
    """
    # ... implementation
```

---

## Expected Impact

### Historical Seasons (2021-23)

| Season | Current Source | New Source | Improvement |
|--------|---------------|------------|-------------|
| 2021-22 | VEGAS_BACKFILL/NO_VEGAS_DATA | BettingPros DK/FD | Real lines instead of estimates |
| 2022-23 | VEGAS_BACKFILL/NO_VEGAS_DATA | BettingPros DK/FD | Real lines instead of estimates |

### Current Season (2025-26)

| Scenario | Current | New |
|----------|---------|-----|
| Odds API has DK | Use DK | Use DK (no change) |
| Odds API has FD only | Use FD | Try BettingPros DK first, then FD |
| Odds API down | Fall back to any BP book | Fall back to BP DK/FD specifically |

### Monitoring Changes

New tracking categories:
- `odds_api` - Primary source with preferred sportsbook
- `bettingpros_preferred` - BettingPros DK/FD (good fallback)
- `odds_api_fallback` - Odds API with secondary sportsbook
- `bettingpros_fallback` - BettingPros secondary sportsbook
- `no_line_data` - No line found anywhere

---

## Migration Path

### Phase 1: Implement New Logic (No Breaking Changes)
1. Add new helper methods `_query_*_for_book()`
2. Add feature flag `USE_SPORTSBOOK_PRIORITY_FALLBACK`
3. Test with flag disabled

### Phase 2: Enable for New Predictions
1. Enable flag for future predictions
2. Monitor line source distribution
3. Verify no regression in coverage

### Phase 3: Backfill Historical Predictions
1. Re-run predictions for 2021-23 with new logic
2. Verify BettingPros DK/FD lines are used
3. Re-grade predictions

---

## Testing

```python
def test_sportsbook_priority_fallback():
    """Test that DraftKings is preferred across sources."""
    loader = PlayerLoader()

    # Mock: Odds API has FanDuel only, BettingPros has DraftKings
    mock_odds_api_data = {'fanduel': 25.5}
    mock_bettingpros_data = {'draftkings': 24.5, 'fanduel': 25.5}

    result = loader._query_actual_betting_line('test-player', date(2024, 1, 1))

    # Should return BettingPros DraftKings, not Odds API FanDuel
    assert result['sportsbook'] == 'DRAFTKINGS'
    assert result['line_source_api'] == 'BETTINGPROS'
```

---

## Related Files

- `predictions/coordinator/player_loader.py` - Main implementation
- `data_processors/enrichment/prediction_line_enrichment/` - Post-game enrichment
- `tests/predictions/test_player_loader.py` - Unit tests
