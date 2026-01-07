# Directory Restructure Plan for Multi-Sport Support

**Updated**: 2026-01-06

## Recommendation: Option B - Sport-Level Subdirectories

After analyzing the current codebase structure, **Option B** is recommended for the lowest disruption with highest clarity.

---

## Current Structure (Problems)

```
scrapers/
├── balldontlie/     # NBA-specific implementations
├── nbacom/          # NBA-specific
├── espn/            # Could be multi-sport
├── oddsapi/         # Could be multi-sport
└── ...

data_processors/
├── raw/
│   ├── balldontlie/  # NBA-specific
│   ├── nbacom/       # NBA-specific
│   └── ...
├── analytics/        # NBA-specific processors
└── ...

shared/config/
├── nba_teams.py      # Hardcoded NBA
├── nba_season_dates.py
└── ...
```

**Problems:**
- Not clear which components are NBA-specific vs sport-agnostic
- Adding MLB would create confusion (balldontlie_nba vs balldontlie_mlb?)
- Config files would multiply confusingly

---

## Proposed Structure (Option B)

```
scrapers/
├── base/                    # Sport-agnostic base classes
│   ├── scraper_base.py
│   └── scraper_flask_mixin.py
├── nba/                     # NBA-specific scrapers
│   ├── balldontlie/
│   ├── nbacom/
│   ├── basketball_ref/
│   ├── espn/
│   ├── oddsapi/
│   ├── bettingpros/
│   └── registry.py          # NBA scraper registry
└── mlb/                     # MLB-specific scrapers
    ├── balldontlie/
    ├── mlbcom/
    ├── baseball_savant/
    ├── oddsapi/
    └── registry.py          # MLB scraper registry

data_processors/
├── base/                    # Sport-agnostic base classes
│   ├── processor_base.py
│   ├── analytics_base.py
│   └── precompute_base.py
├── nba/
│   ├── raw/
│   ├── analytics/
│   ├── precompute/
│   └── ...
└── mlb/
    ├── raw/
    ├── analytics/
    ├── precompute/
    └── ...

shared/config/
├── sport_config.py          # NEW: Central sport abstraction
├── nba/
│   ├── teams.py
│   ├── season_dates.py
│   └── orchestration.py
└── mlb/
    ├── teams.py
    ├── season_dates.py
    └── orchestration.py

schemas/bigquery/
├── nba/
│   ├── raw/
│   ├── analytics/
│   ├── precompute/
│   └── predictions/
└── mlb/
    ├── raw/
    ├── analytics/
    ├── precompute/
    └── predictions/

backfill_jobs/
├── nba/
│   ├── scrapers/
│   ├── raw/
│   ├── analytics/
│   └── ...
└── mlb/
    ├── scrapers/
    ├── raw/
    ├── analytics/
    └── ...
```

---

## Why Option B is Best

| Criteria | Option A (Add alongside) | Option B (Sport subdirs) | Option C (Top-level sports/) |
|----------|--------------------------|--------------------------|------------------------------|
| **Disruption** | Low but messy | Medium, clean | Very High |
| **Clarity** | Poor | Excellent | Excellent |
| **Scalability** | Poor | Excellent | Excellent |
| **Import changes** | Minimal | ~400 files | All files |
| **Deployment** | Same | Same | Complex |
| **Find code** | Difficult | Easy | Easy |

---

## Migration Steps

### Phase 1: Create New Structure (No Breaking Changes)

```bash
# Create sport directories
mkdir -p scrapers/nba scrapers/mlb scrapers/base
mkdir -p data_processors/nba data_processors/mlb data_processors/base
mkdir -p shared/config/nba shared/config/mlb
mkdir -p schemas/bigquery/nba schemas/bigquery/mlb
mkdir -p backfill_jobs/nba backfill_jobs/mlb
```

### Phase 2: Move Base Classes

```bash
# Move base classes to base/ directories
mv scrapers/scraper_base.py scrapers/base/
mv data_processors/raw/processor_base.py data_processors/base/
mv data_processors/analytics/analytics_base.py data_processors/base/
mv data_processors/precompute/precompute_base.py data_processors/base/
```

### Phase 3: Move NBA-Specific Code

```bash
# Move scraper directories
mv scrapers/balldontlie scrapers/nba/
mv scrapers/nbacom scrapers/nba/
mv scrapers/basketball_ref scrapers/nba/
mv scrapers/espn scrapers/nba/
mv scrapers/oddsapi scrapers/nba/
mv scrapers/bettingpros scrapers/nba/
mv scrapers/bigdataball scrapers/nba/

# Move registry
mv scrapers/registry.py scrapers/nba/registry.py
```

### Phase 4: Update Imports

```python
# Before
from scrapers.scraper_base import ScraperBase
from scrapers.balldontlie.bdl_games import BdlGamesScraper

# After
from scrapers.base.scraper_base import ScraperBase
from scrapers.nba.balldontlie.bdl_games import BdlGamesScraper
```

### Phase 5: Create Sport Config

```python
# shared/config/sport_config.py
import os

SPORT = os.environ.get('SPORT', 'nba')

def get_config(module_name: str):
    """Dynamically load sport-specific config."""
    return importlib.import_module(f'shared.config.{SPORT}.{module_name}')

# Usage:
teams = get_config('teams')
```

---

## Files Affected

| Category | Files to Move/Update | Effort |
|----------|---------------------|--------|
| Base classes | 4 files | Low |
| NBA scrapers | ~40 files | Medium (move + update imports) |
| NBA processors | ~80 files | Medium |
| Config files | ~10 files | Low |
| Schemas | ~30 files | Low (just move) |
| Backfill jobs | ~20 files | Medium |
| Import updates | ~400 files | Medium (regex/IDE refactor) |
| **Total** | ~580 files | 2-3 days |

---

## Import Update Strategy

Use IDE refactoring or script:

```bash
# Example: Update scraper imports
find . -name "*.py" -exec sed -i \
  's/from scrapers\.balldontlie/from scrapers.nba.balldontlie/g' {} \;

find . -name "*.py" -exec sed -i \
  's/from scrapers\.scraper_base/from scrapers.base.scraper_base/g' {} \;
```

---

## Service Entry Point Updates

### main_scraper_service.py

```python
# Before
from scrapers.registry import get_scraper_instance

# After
def get_scraper_instance(scraper_name: str, sport: str = 'nba'):
    if sport == 'nba':
        from scrapers.nba.registry import get_scraper_instance as get_nba_scraper
        return get_nba_scraper(scraper_name)
    elif sport == 'mlb':
        from scrapers.mlb.registry import get_scraper_instance as get_mlb_scraper
        return get_mlb_scraper(scraper_name)
```

### main_processor_service.py

```python
# Same pattern - route based on sport parameter
def get_processor(processor_name: str, sport: str = 'nba'):
    module = importlib.import_module(f'data_processors.{sport}.raw.{processor_name}')
    return module
```

---

## Backward Compatibility

During transition, keep aliases:

```python
# scrapers/__init__.py (temporary)
# Backward compatibility - remove after migration
from scrapers.base.scraper_base import ScraperBase
from scrapers.nba.registry import get_scraper_instance

import warnings
warnings.warn(
    "Import from scrapers.nba.* directly. Top-level imports deprecated.",
    DeprecationWarning
)
```

---

## Benefits After Restructure

1. **Clear Ownership** - First glance shows sport scope
2. **Easy Navigation** - `scrapers/mlb/` vs `scrapers/nba/`
3. **Independent Testing** - Test one sport in isolation
4. **Flexible Deployment** - Could deploy sport-specific containers later
5. **Clean Scaling** - Adding NHL/NFL follows same pattern
6. **Reduced Confusion** - No mixed NBA/MLB in same directory
