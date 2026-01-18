# Star Teammates Out - Implementation Plan

**Date:** 2026-01-18
**Session:** 105
**Status:** Design Complete, Ready for Implementation
**Priority:** High (improves prediction context significantly)

---

## 1. OBJECTIVE

Implement `star_teammates_out` metric to track how many key players on a team are unavailable (OUT/DOUBTFUL) for a given game. This context is critical for:
- Usage rate predictions (more opportunities when stars are out)
- Minute projections (backups get more playing time)
- Opponent defense adjustments (focus shifts to remaining stars)

---

## 2. DATA SOURCES

### Available Tables

| Table | Fields Used | Purpose |
|-------|-------------|---------|
| `nba_raw.nbac_injury_report` | `player_lookup`, `injury_status`, `game_date`, `team`, `report_hour` | Identify OUT/DOUBTFUL players |
| `nba_raw.espn_team_rosters` | `team_abbr`, `player_lookup`, `roster_date` | Link teammates on same team |
| `nba_analytics.player_game_summary` | `points`, `minutes_played`, `usage_rate`, `game_date`, `team_abbr` | Calculate star player status |

### Joining Keys

- **player_lookup**: Normalized player name (e.g., "lebronjames")
- **team_abbr**: Three-letter team code (e.g., "LAL", "BOS")
- **game_date**: Date of the game

---

## 3. STAR PLAYER DEFINITION

A player qualifies as a "star" if they meet **ANY** of these criteria over the last 10 games:

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Average Points | ≥ 18 PPG | Primary scoring threats |
| Average Minutes | ≥ 28 MPG | Core rotation players |
| Usage Rate | ≥ 25% | High usage in team offense |

**Design Decision:** Using OR logic (not AND) to capture different star types:
- High scorers with medium minutes (6th man stars)
- High-minute defenders with lower scoring
- High usage efficiency players

---

## 4. IMPLEMENTATION

### A. Method Signature

```python
def _get_star_teammates_out(self, team_abbr: str, game_date: date) -> int:
    """
    Count star teammates who are OUT or DOUBTFUL for the game.

    Star criteria (last 10 games):
    - Average points ≥ 18 PPG OR
    - Average minutes ≥ 28 MPG OR
    - Usage rate ≥ 25%

    Args:
        team_abbr: Team abbreviation (e.g., 'LAL')
        game_date: Game date to check

    Returns:
        int: Number of star teammates out (0-5 typical range)
    """
```

### B. Query Logic

**Step 1: Get Team Roster**
```sql
WITH team_roster AS (
    SELECT player_lookup
    FROM nba_raw.espn_team_rosters
    WHERE team_abbr = '{team_abbr}'
      AND roster_date = (
          SELECT MAX(roster_date)
          FROM nba_raw.espn_team_rosters
          WHERE roster_date <= '{game_date}'
            AND team_abbr = '{team_abbr}'
      )
)
```

**Step 2: Calculate Recent Performance**
```sql
player_recent_stats AS (
    SELECT
        player_lookup,
        AVG(points) as avg_points,
        AVG(minutes_played) as avg_minutes,
        AVG(usage_rate) as avg_usage
    FROM nba_analytics.player_game_summary
    WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 10 DAY)
      AND game_date < '{game_date}'
      AND team_abbr = '{team_abbr}'
    GROUP BY player_lookup
)
```

**Step 3: Identify Star Players**
```sql
star_players AS (
    SELECT s.player_lookup
    FROM player_recent_stats s
    INNER JOIN team_roster r ON s.player_lookup = r.player_lookup
    WHERE s.avg_points >= 18
       OR s.avg_minutes >= 28
       OR s.avg_usage >= 25
)
```

**Step 4: Get Injured/Out Players**
```sql
injured_players AS (
    SELECT DISTINCT player_lookup
    FROM nba_raw.nbac_injury_report
    WHERE game_date = '{game_date}'
      AND team = '{team_abbr}'
      AND UPPER(injury_status) IN ('OUT', 'DOUBTFUL')
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_lookup
        ORDER BY report_hour DESC
    ) = 1
)
```

**Step 5: Count Star Players Out**
```sql
SELECT COUNT(*) as star_teammates_out
FROM star_players s
INNER JOIN injured_players i ON s.player_lookup = i.player_lookup
```

### C. Error Handling

```python
try:
    query = f"""..."""
    result = self.bq_client.query(query).result()
    for row in result:
        return int(row.star_teammates_out) if row.star_teammates_out is not None else 0
    return 0
except Exception as e:
    logger.error(f"Error getting star teammates out for {team_abbr}: {e}")
    return 0
```

### D. Integration Points

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Location 1: Method Call** (around line 2261, after opponent metrics)
```python
# Calculate opponent metrics
opponent_pace_variance = self._get_opponent_pace_variance(opponent_team_abbr, self.target_date)

# Calculate star teammates out
star_teammates_out = self._get_star_teammates_out(team_abbr, self.target_date)
```

**Location 2: Context Dictionary** (around line 2345, replace TODO)
```python
# Player characteristics
'player_age': None,  # TODO: from roster

# Star teammates context
'star_teammates_out': star_teammates_out,  # NEW - Session 105
```

---

## 5. TEST PLAN

### Test Class: `TestStarTeammatesOut`

Following established 4-test pattern:

```python
class TestStarTeammatesOut:
    """Test star teammates out calculation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_get_star_teammates_out_normal(self, processor):
        """Test with 2 star players out."""
        mock_row = Mock()
        mock_row.star_teammates_out = 2
        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._get_star_teammates_out('LAL', date(2025, 1, 20))

        assert result == 2
        assert processor.bq_client.query.called

    def test_get_star_teammates_out_no_stars_out(self, processor):
        """Test with all stars healthy."""
        mock_row = Mock()
        mock_row.star_teammates_out = 0
        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._get_star_teammates_out('LAL', date(2025, 1, 20))

        assert result == 0

    def test_get_star_teammates_out_no_data(self, processor):
        """Test when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_star_teammates_out('LAL', date(2025, 1, 20))

        assert result == 0

    def test_get_star_teammates_out_query_error(self, processor):
        """Test error handling."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_star_teammates_out('LAL', date(2025, 1, 20))

        assert result == 0
```

**Expected Test Results:**
- All 4 tests pass
- Test count: 75 → 79 tests total
- Test file lines: 904 → ~1,000 lines

---

## 6. VALIDATION QUERIES

### Query 1: Verify Star Identification

```sql
-- Check star players for LAL on 2026-01-18
WITH player_recent_stats AS (
    SELECT
        player_lookup,
        AVG(points) as avg_points,
        AVG(minutes_played) as avg_minutes,
        AVG(usage_rate) as avg_usage,
        COUNT(*) as games
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB('2026-01-18', INTERVAL 10 DAY)
      AND game_date < '2026-01-18'
      AND team_abbr = 'LAL'
    GROUP BY player_lookup
)
SELECT
    player_lookup,
    ROUND(avg_points, 1) as ppg,
    ROUND(avg_minutes, 1) as mpg,
    ROUND(avg_usage, 1) as usg,
    games,
    CASE
        WHEN avg_points >= 18 THEN 'YES (Points)'
        WHEN avg_minutes >= 28 THEN 'YES (Minutes)'
        WHEN avg_usage >= 25 THEN 'YES (Usage)'
        ELSE 'NO'
    END as is_star
FROM player_recent_stats
ORDER BY avg_points DESC
LIMIT 10
```

**Expected Results:**
- 3-5 players marked as "YES"
- Top scorers (LeBron, AD, etc.) identified
- Usage leaders captured

### Query 2: Verify Injury Report Integration

```sql
-- Check injured stars for today's games
SELECT
    i.game_date,
    i.team,
    i.player_lookup,
    i.injury_status,
    i.reason,
    s.avg_points as ppg_last_10,
    s.is_star
FROM `nba-props-platform.nba_raw.nbac_injury_report` i
LEFT JOIN (
    SELECT
        player_lookup,
        AVG(points) as avg_points,
        CASE WHEN AVG(points) >= 18 OR AVG(minutes_played) >= 28 OR AVG(usage_rate) >= 25
             THEN 'YES' ELSE 'NO' END as is_star
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= CURRENT_DATE() - 10
    GROUP BY player_lookup
) s ON i.player_lookup = s.player_lookup
WHERE i.game_date = CURRENT_DATE()
  AND UPPER(i.injury_status) IN ('OUT', 'DOUBTFUL')
QUALIFY ROW_NUMBER() OVER (PARTITION BY i.player_lookup ORDER BY i.report_hour DESC) = 1
ORDER BY s.is_star DESC, s.avg_points DESC
```

**Expected Results:**
- List of all injured players today
- "YES" marked for star players
- Empty if no games today or no injuries

---

## 7. EXPECTED OUTPUT VALUES

| Value | Meaning | Impact on Predictions |
|-------|---------|----------------------|
| 0 | All stars healthy | Normal game context |
| 1 | One key player out | Moderate usage increase for others |
| 2 | Two stars out | Significant opportunity for backups |
| 3+ | Major lineup disruption | High usage shifts, unreliable predictions |

**Typical Distribution (based on 2024-25 season):**
- 0 stars out: ~70% of games
- 1 star out: ~22% of games
- 2 stars out: ~6% of games
- 3+ stars out: ~2% of games

---

## 8. IMPLEMENTATION TIMELINE

| Phase | Duration | Description |
|-------|----------|-------------|
| **Phase 1**: Code Implementation | 20 min | Add method to processor |
| **Phase 2**: Integration | 15 min | Wire into context calculation |
| **Phase 3**: Test Implementation | 20 min | Add 4 comprehensive tests |
| **Phase 4**: Test Execution | 5 min | Run all 79 tests |
| **Phase 5**: Validation Queries | 10 min | Verify data quality |
| **Total** | **70 min** | Complete implementation |

---

## 9. RISKS & MITIGATION

### Risk 1: Injury Reports Not Available

**Issue:** `nbac_injury_report` may not have data for game_date

**Mitigation:**
- Return 0 if no injury data (conservative approach)
- Consider using previous day's report as fallback
- Log warning when injury data missing

### Risk 2: Recent Stats Not Available

**Issue:** New players or post-trade players may lack 10-game history

**Mitigation:**
- Reduce lookback to 5 games if < 10 games available
- Use season averages as fallback
- Return 0 for edge cases rather than failing

### Risk 3: Star Definition Too Restrictive

**Issue:** May miss important players below thresholds

**Mitigation:**
- Monitor validation queries for borderline cases
- Consider future refinement based on actual impact
- Document threshold choices for future adjustment

### Risk 4: Team Abbreviation Mismatch

**Issue:** Different sources may use different team codes

**Mitigation:**
- Use standardized `team_abbr` from schedule/roster
- Validate team codes match across tables
- Log mismatches for investigation

---

## 10. SUCCESS CRITERIA

### Code Quality
- [ ] Method follows established pattern (similar to opponent metrics)
- [ ] Error handling with graceful fallback to 0
- [ ] Clear docstring with examples
- [ ] Logging for debugging

### Testing
- [ ] 4 comprehensive tests added
- [ ] All 79 tests passing (up from 75)
- [ ] Test coverage ≥ 80% for new method

### Data Quality
- [ ] Validation query returns expected star players
- [ ] Injury integration correctly identifies OUT players
- [ ] Values in expected range (0-5)
- [ ] No NULL values in output

### Deployment
- [ ] Processor deployed successfully
- [ ] BigQuery shows populated field
- [ ] No errors in Cloud Run logs
- [ ] Field appears in upcoming_player_game_context table

---

## 11. FUTURE ENHANCEMENTS

### Phase 2 Features (Not in Initial Implementation)

1. **Questionable Stars Tracking**
   - Add `questionable_star_teammates` field
   - Track players likely to play but uncertain
   - Helps model uncertainty in predictions

2. **Star Tier Classification**
   - Tier 1: Superstar (25+ PPG)
   - Tier 2: All-Star (18-25 PPG)
   - Tier 3: Key Starter (15-18 PPG)
   - Weight impact differently by tier

3. **Position-Specific Impact**
   - Track which position stars are out
   - Guard out vs Big out has different impact
   - More granular prediction adjustments

4. **Historical Pattern Learning**
   - Track how player performance changes when specific stars are out
   - Build "star out" multiplier per player
   - Improve prediction accuracy

---

## 12. REFERENCES

### Investigation Reports
- **Injury Data Investigation**: Session 105, Agent aa412d9
- **Roster Data Investigation**: Session 105, Agent aa6452b

### Related Code
- **upcoming_player_game_context_processor.py**: Lines 2254-2345 (metric integration)
- **nbac_injury_report_processor.py**: Injury parsing logic
- **espn_team_rosters_processor.py**: Roster management

### Related Documentation
- **SESSION-105-HANDOFF.md**: Session context
- **SESSION-103-FINAL-STATUS.md**: Opponent metrics pattern
- **SESSION-104-HANDOFF.md**: Recent metrics implementation

---

**Implementation Ready:** YES
**Estimated Completion:** 70 minutes
**Recommended Session:** 106 (after Session 105 verifications)

