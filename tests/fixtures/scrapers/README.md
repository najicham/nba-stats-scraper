# Scraper Test Fixtures

This directory contains test fixtures for all NBA Stats Scraper scrapers.

## Directory Structure

```
scrapers/
├── balldontlie/      # BallDontLie API fixtures
│   ├── bdl_games_raw.json
│   ├── bdl_games_expected.json
│   ├── bdl_games_empty.json
│   ├── bdl_games_paginated.json
│   ├── bdl_injuries_raw.json
│   ├── bdl_injuries_expected.json
│   ├── bdl_injuries_empty.json
│   ├── bdl_box_scores_raw.json
│   └── bdl_standings_raw.json
│
├── espn/             # ESPN API/HTML fixtures
│   ├── espn_scoreboard_raw.json
│   ├── espn_scoreboard_expected.json
│   ├── espn_scoreboard_empty.json
│   ├── espn_scoreboard_live.json
│   ├── espn_boxscore_bxscr.json
│   └── espn_boxscore_expected.json
│
├── nbacom/           # NBA.com API fixtures
│   ├── nbac_scoreboard_v2_raw.json
│   ├── nbac_schedule_api_raw.json
│   └── nbac_player_boxscore_raw.json
│
├── oddsapi/          # The Odds API fixtures
│   ├── oddsa_events_raw.json
│   ├── oddsa_events_expected.json
│   ├── oddsa_events_empty.json
│   ├── oddsa_events_error.json
│   ├── oddsa_player_props_raw.json
│   └── oddsa_game_lines_raw.json
│
├── basketball_ref/   # Basketball Reference HTML fixtures
│   ├── br_roster_raw.html
│   ├── br_roster_expected.json
│   ├── br_roster_unicode.html
│   └── br_roster_suffix.html
│
├── bigdataball/      # BigDataBall fixtures (placeholder)
└── bettingpros/      # BettingPros fixtures (placeholder)
```

## Usage

### Loading Fixtures in Tests

```python
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scrapers"

def load_fixture(source: str, filename: str):
    """Load a fixture file."""
    path = FIXTURES_DIR / source / filename

    if filename.endswith('.json'):
        with open(path) as f:
            return json.load(f)
    else:
        with open(path) as f:
            return f.read()

# Example usage
raw_response = load_fixture("balldontlie", "bdl_games_raw.json")
expected = load_fixture("balldontlie", "bdl_games_expected.json")
```

### Creating New Fixtures

Use the capture tool to create fixtures from live API responses:

```bash
python tools/fixtures/capture.py <scraper_name> [options] --debug

# Examples:
python tools/fixtures/capture.py bdl_games --startDate 2025-01-15 --debug
python tools/fixtures/capture.py espn_scoreboard_api --gamedate 20250120 --debug
```

## Fixture Naming Convention

- `*_raw.json` - Raw API response
- `*_raw.html` - Raw HTML source
- `*_expected.json` - Expected transformed output
- `*_empty.json` - Empty response edge case
- `*_error.json` - Error response
- `*_<variant>.json` - Specific edge case variants

## Documentation

See [docs/SCRAPER-FIXTURES.md](/docs/SCRAPER-FIXTURES.md) for detailed documentation on:
- Response formats for each scraper
- Edge cases and error handling
- Transform rules and expected outputs
- Test usage examples
