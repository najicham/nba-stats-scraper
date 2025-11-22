# NBA Shared Utilities Reference

**Created:** 2025-11-21 17:40:00 PST
**Last Updated:** 2025-11-21 17:40:00 PST

Quick reference for shared utility services used across processors and backfills.

## NBA Team Mapper

**Purpose:** Team name/code mapping with fuzzy matching

**File:** `shared/utils/nba_team_mapper.py`

### Basic Setup

```python
from shared.utils.nba_team_mapper import NBATeamMapper

# For backfills
mapper = NBATeamMapper(use_database=False)

# For processors
mapper = NBATeamMapper(use_database=True)
```

### Common Operations

#### Get Team Code from Name

```python
# Exact matching (handles variations)
code = mapper.get_nba_tricode('Lakers')              # 'LAL'
code = mapper.get_nba_tricode('LA Lakers')           # 'LAL'
code = mapper.get_nba_tricode('Los Angeles Lakers')  # 'LAL'
code = mapper.get_nba_tricode('LAL')                 # 'LAL'
```

#### Get Team Full Name

```python
full_name = mapper.get_team_full_name('LAL')
# Returns: 'Los Angeles Lakers'
```

#### Fuzzy Matching (Typos)

```python
# Handle misspellings
code = mapper.get_nba_tricode_fuzzy('Lakres')     # 'LAL'
code = mapper.get_nba_tricode_fuzzy('Worriers')   # 'GSW'

# With confidence threshold
code = mapper.get_nba_tricode_fuzzy('Lakres', min_confidence=85)
```

#### Validate Team Code

```python
if mapper.is_valid_team('LAL'):
    # Valid team code
    pass
```

#### Get All Teams

```python
# All team codes
all_teams = mapper.get_all_team_codes()
# Returns: ['ATL', 'BOS', 'BKN', ..., 'WAS']

# Full team info
team_info = mapper.get_team_info('LAL')
# Returns: TeamInfo object with full_name, city, nickname, etc.
```

#### Find Teams by City

```python
la_teams = mapper.find_teams_by_city('Los Angeles')
# Returns: ['LAL', 'LAC']

chicago = mapper.find_teams_by_city('Chicago')
# Returns: ['CHI']
```

### Schedule-Aware Features

**Requires:** `NBAScheduleService` (if available)

```python
# Get team schedule
schedule = mapper.get_team_schedule('LAL', season=2024)

# Check rest days before game
rest = mapper.get_rest_days('LAL', '2024-01-15')

# Check if home game
is_home = mapper.is_home_game('LAL', '2024-01-15')

# Get opponent
opponent = mapper.get_opponent('LAL', '2024-01-15')

# Get comprehensive game context
context = mapper.get_game_context('LAL', '2024-01-15')
# Returns: {
#   'team': 'LAL',
#   'opponent': 'GSW',
#   'is_home_game': True,
#   'rest_days': 2,
#   'is_back_to_back': False,
#   'matchup': 'GSW@LAL'
# }
```

### TeamInfo Object

```python
team_info = mapper.get_team_info('LAL')

team_info.nba_tricode       # 'LAL'
team_info.br_tricode        # 'LAL' (Basketball Reference)
team_info.espn_tricode      # 'LAL' (ESPN)
team_info.full_name         # 'Los Angeles Lakers'
team_info.city              # 'Los Angeles'
team_info.nickname          # 'Lakers'
team_info.state             # 'California'
team_info.division          # 'Pacific'
team_info.conference        # 'Western'
team_info.common_variations # ['lakers', 'la lakers', ...]
```

### Multiple Tricode Systems

```python
# NBA.com tricode (standard)
nba_code = mapper.get_nba_tricode('Lakers')  # 'LAL'

# Basketball Reference tricode
br_code = mapper.get_br_tricode('Nets')  # 'BRK' (not BKN)

# ESPN tricode
espn_code = mapper.get_espn_tricode('Warriors')  # 'GS' (not GSW)
```

## Common Patterns

### Pattern 1: Backfill with Team Mapping

```python
from shared.utils.nba_team_mapper import NBATeamMapper

class MyBackfillJob:
    def __init__(self):
        # GCS-only for backfills
        self.team_mapper = NBATeamMapper(use_database=False)

    def process_data(self, raw_data):
        for record in raw_data:
            # Map external team name to NBA code
            team_code = self.team_mapper.get_nba_tricode(record.team_name)

            if not team_code:
                logger.warning(f"Unknown team: {record.team_name}")
                continue

            # Get full name for display
            team_full = self.team_mapper.get_team_full_name(team_code)

            self._save_record(team_code, team_full, record)
```

### Pattern 2: External Name Matching

```python
from shared.utils.nba_team_mapper import NBATeamMapper

mapper = NBATeamMapper()

def match_external_team(external_team_name: str) -> Optional[str]:
    """Map external team name to NBA code."""

    # Try exact match first
    code = mapper.get_nba_tricode(external_team_name)
    if code:
        return code

    # Try fuzzy match for typos
    code = mapper.get_nba_tricode_fuzzy(
        external_team_name,
        min_confidence=85
    )
    if code:
        logger.info(f"Fuzzy matched '{external_team_name}' to {code}")
        return code

    # No match found
    logger.error(f"Could not match team: {external_team_name}")
    return None
```

### Pattern 3: Team Validation

```python
def validate_teams(team_codes: List[str]) -> bool:
    """Validate all team codes."""
    mapper = NBATeamMapper()

    invalid = []
    for code in team_codes:
        if not mapper.is_valid_team(code):
            invalid.append(code)

    if invalid:
        logger.error(f"Invalid team codes: {invalid}")
        return False

    return True
```

## Travel Utilities

**Purpose:** Calculate travel distances between team cities

**File:** `shared/utils/travel_team_info.py`

### Basic Usage

```python
from shared.utils.travel_team_info import get_travel_distance

# Get distance between teams
miles = get_travel_distance('LAL', 'BOS')
# Returns: Distance in miles between Los Angeles and Boston

# Returns None if either team invalid
miles = get_travel_distance('INVALID', 'BOS')  # None
```

## Best Practices

### ✅ DO

**Use team mapper for all team matching:**
```python
# Good - centralized mapping
mapper = NBATeamMapper()
code = mapper.get_nba_tricode(name)

# Bad - hardcoded dictionary
TEAM_MAP = {'Lakers': 'LAL', ...}  # Don't duplicate!
```

**Handle fuzzy matching carefully:**
```python
# Good - require high confidence
code = mapper.get_nba_tricode_fuzzy(name, min_confidence=85)

# Bad - accept low confidence matches
code = mapper.get_nba_tricode_fuzzy(name, min_confidence=50)
```

**Validate team codes:**
```python
# Good - validate before using
if mapper.is_valid_team(code):
    process_team(code)

# Bad - assume valid
process_team(code)  # Might fail later
```

**Use correct mode:**
```python
# Good - GCS-only for backfills
mapper = NBATeamMapper(use_database=False)

# Good - database for processors
mapper = NBATeamMapper(use_database=True)

# Bad - wrong mode
mapper = NBATeamMapper(use_database=True)  # In backfill script!
```

### ❌ DON'T

**Don't create custom team dictionaries:**
```python
# Bad - duplication
NBA_TEAMS = {
    'LAL': 'Los Angeles Lakers',
    'BOS': 'Boston Celtics',
    # ... 28 more teams
}

# Good - use mapper
mapper = NBATeamMapper()
name = mapper.get_team_full_name('LAL')
```

**Don't hardcode team variations:**
```python
# Bad - incomplete/outdated
if name in ['Lakers', 'LA Lakers', 'Los Angeles Lakers']:
    code = 'LAL'

# Good - handles all variations
code = mapper.get_nba_tricode(name)
```

**Don't ignore failed matches:**
```python
# Bad - silent failure
code = mapper.get_nba_tricode(name)
# code might be None!
process_team(code)

# Good - handle None
code = mapper.get_nba_tricode(name)
if not code:
    logger.warning(f"Unknown team: {name}")
    return
process_team(code)
```

## Troubleshooting

### Issue: Team Name Not Matching

**Solution:** Try fuzzy matching

```python
# If exact match fails
code = mapper.get_nba_tricode(name)
if not code:
    # Try fuzzy
    code = mapper.get_nba_tricode_fuzzy(name, min_confidence=80)
    if code:
        logger.info(f"Fuzzy matched '{name}' to {code}")
```

### Issue: Wrong Tricode System

**Problem:** BRK vs BKN, GS vs GSW

**Solution:** Use correct getter

```python
# For NBA.com (standard)
mapper.get_nba_tricode('Nets')  # 'BKN'

# For Basketball Reference
mapper.get_br_tricode('Nets')  # 'BRK'

# For ESPN
mapper.get_espn_tricode('Warriors')  # 'GS'
```

### Issue: Missing Schedule Features

**Problem:** `get_game_context()` not working

**Solution:** Check if `NBAScheduleService` available

```python
# These require schedule service
try:
    context = mapper.get_game_context('LAL', '2024-01-15')
except AttributeError:
    logger.warning("Schedule features not available")
```

## Testing

### Quick Test

```python
from shared.utils.nba_team_mapper import NBATeamMapper

mapper = NBATeamMapper(use_database=False)

# Test basic mapping
assert mapper.get_nba_tricode('Lakers') == 'LAL'
assert mapper.get_team_full_name('LAL') == 'Los Angeles Lakers'

# Test fuzzy matching
assert mapper.get_nba_tricode_fuzzy('Lakres') == 'LAL'

# Test validation
assert mapper.is_valid_team('LAL')
assert not mapper.is_valid_team('INVALID')

# Test all teams loaded
assert len(mapper.get_all_team_codes()) == 30

print("All tests passed!")
```

## All NBA Teams

**30 Teams (2024-25 Season):**

```
Eastern Conference:
  Atlantic:    BOS, BKN, NYK, PHI, TOR
  Central:     CHI, CLE, DET, IND, MIL
  Southeast:   ATL, CHA, MIA, ORL, WAS

Western Conference:
  Northwest:   DEN, MIN, OKC, POR, UTA
  Pacific:     GSW, LAC, LAL, PHX, SAC
  Southwest:   DAL, HOU, MEM, NOP, SAS
```

## Files

**Team Mapper:**
- `shared/utils/nba_team_mapper.py` - Main team mapper class

**Travel:**
- `shared/utils/travel_team_info.py` - Travel distance calculations

**Schedule (if available):**
- `shared/utils/schedule.py` - Schedule service

## See Also

- [Scrapers Reference](01-scrapers-reference.md)
- [Processors Reference](02-processors-reference.md)
- [Analytics Processors Reference](03-analytics-processors-reference.md)
