# Smart Idempotency - Remaining Processor Implementation Plan
**Date**: 2025-11-21
**Status**: 5/22 Complete (Critical processors done)

## Progress Summary

### ✅ Completed (5/22)
1. **nbac_injury_report_processor** - APPEND_ALWAYS
2. **bdl_injuries_processor** - APPEND_ALWAYS
3. **odds_api_props_processor** - APPEND_ALWAYS
4. **bettingpros_player_props_processor** - CHECK_BEFORE_INSERT
5. **odds_game_lines_processor** - MERGE_UPDATE

### 🔄 Remaining (17/22)

#### Medium Priority (6 processors)
6. nbac_play_by_play_processor
7. nbac_player_boxscores_processor
8. nbac_gamebook_processor
9. bdl_boxscores_processor
10. espn_scoreboard_processor
11. espn_boxscores_processor

#### Low Priority (10 processors)
12. nbac_schedule_processor
13. nbac_player_list_processor
14. nbac_player_movement_processor
15. nbac_referee_processor
16. bdl_active_players_processor
17. bdl_standings_processor
18. espn_team_rosters_processor
19. bigdataball_pbp_processor
20. br_rosters_processor
21. nbac_scoreboard_v2_processor

#### Not Yet Created (1 processor)
22. nbac_team_boxscore_processor (table doesn't exist in production yet)

---

## Implementation Pattern

For each processor, follow this 4-step pattern:

### Step 1: Add Import
```python
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
```

### Step 2: Update Class Definition
```python
# Before
class MyProcessor(ProcessorBase):

# After
class MyProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    MyProcessor description

    Processing Strategy: [APPEND_ALWAYS|MERGE_UPDATE|CHECK_BEFORE_INSERT]
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: [list of hash fields]
        Expected Skip Rate: [50%|N/A]
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'field1',
        'field2',
        # ... (meaningful fields only, exclude metadata)
    ]
```

### Step 3: Add Hash Computation Call
In `transform_data()`, after `self.transformed_data = rows`:
```python
    self.transformed_data = rows

    # Smart Idempotency: Add data_hash to all records
    self.add_data_hash()
```

### Step 4: Verify
- Import added ✓
- Mixin in class definition (BEFORE ProcessorBase) ✓
- HASH_FIELDS defined ✓
- `add_data_hash()` called ✓

---

## Detailed Processor Specifications

### 6. nbac_play_by_play_processor
**File**: `data_processors/raw/nbacom/nbac_play_by_play_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'event_id',
    'period',
    'game_clock',
    'event_type',
    'event_description',
    'score_home',
    'score_away'
]
```

---

### 7. nbac_player_boxscores_processor
**File**: `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'player_lookup',
    'points',
    'rebounds',
    'assists',
    'minutes',
    'field_goals_made',
    'field_goals_attempted'
]
```

---

### 8. nbac_gamebook_processor
**File**: `data_processors/raw/nbacom/nbac_gamebook_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'player_lookup',
    'minutes',
    'field_goals_made',
    'field_goals_attempted',
    'points',
    'rebounds',
    'assists'
]
```

---

### 9. bdl_boxscores_processor
**File**: `data_processors/raw/balldontlie/bdl_boxscores_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'player_lookup',
    'points',
    'rebounds',
    'assists',
    'field_goals_made',
    'field_goals_attempted'
]
```

---

### 10. espn_scoreboard_processor
**File**: `data_processors/raw/espn/espn_scoreboard_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'game_status',
    'home_score',
    'away_score',
    'home_team_abbr',
    'away_team_abbr'
]
```

---

### 11. espn_boxscores_processor
**File**: `data_processors/raw/espn/espn_boxscore_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'player_lookup',
    'points',
    'rebounds',
    'assists',
    'field_goals_made',
    'field_goals_attempted'
]
```

---

### 12. nbac_schedule_processor
**File**: `data_processors/raw/nbacom/nbac_schedule_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'game_date',
    'game_time_utc',
    'home_team_tricode',
    'away_team_tricode',
    'game_status'
]
```

---

### 13. nbac_player_list_processor
**File**: `data_processors/raw/nbacom/nbac_player_list_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'player_lookup',
    'team_abbr',
    'position',
    'jersey_number',
    'is_active'
]
```

---

### 14. nbac_player_movement_processor
**File**: `data_processors/raw/nbacom/nbac_player_movement_processor.py`
**Strategy**: APPEND_ALWAYS
**HASH_FIELDS**:
```python
[
    'player_lookup',
    'transaction_date',
    'transaction_type',
    'team_abbr',
    'transaction_description'
]
```

---

### 15. nbac_referee_processor
**File**: `data_processors/raw/nbacom/nbac_referee_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'official_code',
    'official_name',
    'assignment_type'
]
```

---

### 16. bdl_active_players_processor
**File**: `data_processors/raw/balldontlie/bdl_active_players_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'player_lookup',
    'team_abbr',
    'position',
    'jersey_number',
    'is_active'
]
```

---

### 17. bdl_standings_processor
**File**: `data_processors/raw/balldontlie/bdl_standings_processor.py`
**Strategy**: APPEND_ALWAYS
**HASH_FIELDS**:
```python
[
    'team_abbr',
    'date_recorded',
    'wins',
    'losses',
    'win_percentage',
    'conference_rank'
]
```

---

### 18. espn_team_rosters_processor
**File**: `data_processors/raw/espn/espn_team_roster_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'roster_date',
    'team_abbr',
    'player_lookup',
    'position',
    'jersey_number'
]
```

---

### 19. bigdataball_pbp_processor
**File**: `data_processors/raw/bigdataball/bigdataball_pbp_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'event_id',
    'period',
    'game_clock',
    'event_type',
    'score_home',
    'score_away'
]
```

---

### 20. br_rosters_processor
**File**: `data_processors/raw/basketball_ref/br_roster_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'season_year',
    'team_abbrev',
    'player_lookup',
    'jersey_number',
    'position'
]
```

---

### 21. nbac_scoreboard_v2_processor
**File**: `data_processors/raw/nbacom/nbac_scoreboard_v2_processor.py`
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'game_state',
    'home_score',
    'away_score',
    'home_team_abbr',
    'away_team_abbr'
]
```

---

### 22. nbac_team_boxscore_processor (Future)
**File**: `data_processors/raw/nbacom/nbac_team_boxscore_processor.py`
**Status**: Table not yet created in production
**Strategy**: MERGE_UPDATE
**HASH_FIELDS**:
```python
[
    'game_id',
    'team_abbr',
    'field_goals_made',
    'field_goals_attempted',
    'points',
    'rebounds',
    'assists'
]
```
**Note**: Implement when table is created

---

## Implementation Checklist

Use this checklist when implementing each processor:

```
Processor: [Name]
- [ ] Read processor file to locate class and transform_data method
- [ ] Add SmartIdempotencyMixin import
- [ ] Update class definition (mixin BEFORE ProcessorBase)
- [ ] Add docstring with strategy and hash fields
- [ ] Define HASH_FIELDS list
- [ ] Add add_data_hash() call in transform_data()
- [ ] Verify no syntax errors (grep or python compile check)
- [ ] Update this document to mark as complete
```

---

## Verification Commands

After implementing each processor, verify with:

```bash
# Check Python syntax
python3 -m py_compile data_processors/raw/path/to/processor.py

# Verify imports resolve
python3 -c "from data_processors.raw.path.to import ProcessorClass; print('OK')"

# Check HASH_FIELDS defined
grep -A 10 "HASH_FIELDS = \[" data_processors/raw/path/to/processor.py

# Check add_data_hash() called
grep "self.add_data_hash()" data_processors/raw/path/to/processor.py
```

---

## Next Steps

1. **Option A**: Implement all 17 remaining processors in one session
   - Estimated time: 1-2 hours
   - Systematic implementation following pattern

2. **Option B**: Implement in phases
   - Week 1: Deploy 5 critical (already done)
   - Week 2: Implement + deploy 6 medium priority
   - Week 3: Implement + deploy 10 low priority

3. **Option C**: Create automation script
   - Python script to auto-update all processors
   - Requires careful validation of each processor's structure

**Recommendation**: Option A - implement all now while pattern is fresh, deploy in phases for safety.

---

## Success Metrics (After Full Implementation)

Expected impact across all 22 processors:

| Category | Scrapes/Day | Expected Skips | Ops Saved/Day |
|----------|-------------|----------------|---------------|
| Critical (5) | 50-70 | 50% | 4500+ |
| Medium (6) | 20-30 | 30% | 600+ |
| Low (10) | 10-20 | 20% | 200+ |
| **TOTAL** | **80-120** | **40%** | **5300+** |

**ROI**: Prevents ~5300 unnecessary operations daily across Phase 3/4/5 processors.

---

## References

- Mixin source code: `data_processors/raw/smart_idempotency_mixin.py`
- Implementation guide: `docs/implementation/03-smart-idempotency-implementation-guide.md`
- Schema definitions: `schemas/bigquery/raw/*_tables.sql`
- Completed examples: 5 critical processors (lines 1-5 above)
